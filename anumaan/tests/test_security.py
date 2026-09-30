"""Security regression tests.

Each test pins one control from SECURITY.md so that removing or weakening it
fails the build. Plain functions with no pytest fixtures, so
tests/run_tests.py can run them too.
"""
from __future__ import annotations

import base64
import contextlib
import csv
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import security as sec  # noqa: E402
from app.main import app  # noqa: E402
from scripts import integrity  # noqa: E402

SECURITY_ENV = ("ANUMAAN_ENV", "ANUMAAN_VIEW_USER", "ANUMAAN_VIEW_PASSWORD",
                "ANUMAAN_ADMIN_TOKEN", "ANUMAAN_INTEGRITY_KEY", "ANUMAAN_ALLOWED_HOSTS",
                "ANUMAAN_RATE_API_PER_MIN", "ANUMAAN_RATE_SCORE_PER_MIN",
                "ANUMAAN_RATE_RETRAIN_PER_HOUR", "ANUMAAN_MAX_BODY_BYTES")
ADMIN = "a" * 40
KEY = "k" * 40
PROJECT = "619103"          # a real PAIMANA project code present in the panel


@contextlib.contextmanager
def env(**values):
    """Set exactly these security variables for the duration, clear the rest."""
    saved = {k: os.environ.get(k) for k in SECURITY_ENV}
    try:
        for k in SECURITY_ENV:
            os.environ.pop(k, None)
        for k, v in values.items():
            os.environ[k] = v
        sec.LIMITER.reset()
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        sec.LIMITER.reset()


def client(**values):
    """A TestClient whose startup reads `values` as its environment."""
    @contextlib.contextmanager
    def _c():
        with env(**values), TestClient(app) as c:
            yield c
    return _c()


def basic(user: str, pw: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


# ---------------------------------------------------------------------------
# State-changing route
# ---------------------------------------------------------------------------

def test_retrain_refused_without_admin_token():
    with client() as c:
        r = c.post("/api/retrain", json={"cutoff": None})
        assert r.status_code == 403, r.text


def test_retrain_refused_with_wrong_token_and_allowed_with_right_one():
    with client(ANUMAAN_ADMIN_TOKEN=ADMIN) as c:
        assert c.post("/api/retrain", json={}, headers={"X-Admin-Token": "b" * 40}).status_code == 403
        r = c.post("/api/retrain", json={}, headers={"X-Admin-Token": ADMIN})
        assert r.status_code == 200, r.text
        assert r.json()["split_cutoff"] == "2026-06"


def test_retrain_cutoff_must_be_a_panel_month():
    with client(ANUMAAN_ADMIN_TOKEN=ADMIN) as c:
        h = {"X-Admin-Token": ADMIN}
        assert c.post("/api/retrain", json={"cutoff": "1999-01"}, headers=h).status_code == 422
        assert c.post("/api/retrain", json={"cutoff": "'; DROP"}, headers=h).status_code == 422
        assert c.post("/api/retrain", json={"cutoff": "2026-06", "x": 1}, headers=h).status_code == 422


def test_loopback_exemption_is_development_only():
    with env():
        dev = sec.load_settings()
    assert sec.admin_ok(dev, None, "127.0.0.1")[0] is True
    assert sec.admin_ok(dev, None, "203.0.113.9")[0] is False
    with env(ANUMAAN_ENV="production"):
        prod = sec.load_settings()
    assert sec.admin_ok(prod, None, "127.0.0.1")[0] is False


# ---------------------------------------------------------------------------
# Authentication and production startup
# ---------------------------------------------------------------------------

def test_viewer_auth_protects_everything_but_health():
    with client(ANUMAAN_VIEW_USER="mospi", ANUMAAN_VIEW_PASSWORD="correct-horse-1") as c:
        assert c.get("/api/health").status_code == 200
        for path in ("/", "/api/status", "/api/metrics", "/api/projects",
                     f"/api/project/{PROJECT}", "/api/pipeline", "/static/app.js"):
            r = c.get(path)
            assert r.status_code == 401, (path, r.status_code)
            assert r.headers.get("www-authenticate", "").startswith("Basic")
        assert c.get("/api/metrics", headers=basic("mospi", "wrong-password")).status_code == 401
        assert c.get("/api/metrics", headers=basic("mospi", "correct-horse-1")).status_code == 200


def test_health_reveals_nothing_about_the_data():
    with client() as c:
        assert c.get("/api/health").json() == {"status": "ok"}


def test_production_refuses_to_start_without_secrets():
    try:
        with client(ANUMAAN_ENV="production"):
            pass
    except RuntimeError as exc:
        msg = str(exc)
        for needle in ("ANUMAAN_VIEW_USER", "ANUMAAN_ADMIN_TOKEN",
                       "ANUMAAN_INTEGRITY_KEY", "ANUMAAN_ALLOWED_HOSTS"):
            assert needle in msg, needle
    else:
        raise AssertionError("production started with no secrets")


def test_production_refuses_to_start_on_an_unsigned_manifest():
    """The repository manifest is unsigned; only the key holder can sign it.
    Production must refuse it even when every other secret is present."""
    try:
        with client(ANUMAAN_ENV="production", ANUMAAN_VIEW_USER="mospi",
                    ANUMAAN_VIEW_PASSWORD="correct-horse-1", ANUMAAN_ADMIN_TOKEN=ADMIN,
                    ANUMAAN_INTEGRITY_KEY=KEY, ANUMAAN_ALLOWED_HOSTS="testserver"):
            pass
    except RuntimeError as exc:
        assert "signature" in str(exc) or "integrity" in str(exc), str(exc)
    else:
        raise AssertionError("production started on an unsigned manifest")


def test_weak_secrets_are_rejected_in_any_mode():
    with env(ANUMAAN_ADMIN_TOKEN="short"):
        assert any("ANUMAAN_ADMIN_TOKEN" in p for p in sec.load_settings().problems)
    with env(ANUMAAN_VIEW_USER="u"):
        assert sec.load_settings().problems
    with env(ANUMAAN_ALLOWED_HOSTS="*"):
        assert sec.load_settings().problems


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def test_inputs_are_bounded_and_errors_do_not_echo_them():
    payload = "<img src=x onerror=alert(1)>"
    with client() as c:
        r = c.get("/api/project/" + payload)
        assert r.status_code in (404, 422)
        assert "onerror" not in r.text
        r = c.get("/api/project/999999")
        assert r.status_code == 404 and "999999" not in r.text
        assert c.get("/api/projects?limit=100000").status_code == 422
        assert c.get("/api/projects?min_p=5").status_code == 422
        assert c.get("/api/projects?q=" + "x" * 500).status_code == 422
        r = c.post("/api/score", json={"entity_id": PROJECT, "physical_progress_pct": payload})
        assert r.status_code == 422 and "onerror" not in r.text
        r = c.post("/api/score", content='{"entity_id":"619103","expenditure_ratio":NaN}',
                   headers={"content-type": "application/json"})
        assert r.status_code == 422
        assert c.post("/api/score", json={"entity_id": PROJECT, "revisions_so_far": 1e9}).status_code == 422
        assert c.post("/api/score", json={"entity_id": PROJECT, "extra": 1}).status_code == 422


def test_what_if_still_scores_real_inputs():
    with client() as c:
        r = c.post("/api/score", json={"entity_id": PROJECT, "cumulative_drift_months": 24})
        assert r.status_code == 200, r.text
        assert 0.0 <= r.json()["p_slip"] <= 1.0


def test_oversized_body_and_foreign_host_are_refused():
    with client(ANUMAAN_MAX_BODY_BYTES="256") as c:
        r = c.post("/api/score", content="{" + " " * 400 + "}",
                   headers={"content-type": "application/json"})
        assert r.status_code == 413
        assert c.get("/api/health", headers={"host": "evil.example"}).status_code == 400


def test_rate_limit_answers_429_with_retry_after():
    with client(ANUMAAN_RATE_API_PER_MIN="3") as c:
        codes = [c.get("/api/health").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and codes[3] == 429, codes
        assert c.get("/api/health").headers.get("retry-after")


# ---------------------------------------------------------------------------
# Browser-side protections
# ---------------------------------------------------------------------------

def test_security_headers_on_pages_and_api():
    with client() as c:
        for path in ("/", "/api/health"):
            h = c.get(path).headers
            assert "script-src 'self'" in h["content-security-policy"]
            assert "frame-ancestors 'none'" in h["content-security-policy"]
            assert h["x-frame-options"] == "DENY"
            assert h["x-content-type-options"] == "nosniff"
            assert h["referrer-policy"] == "no-referrer"
        assert c.get("/api/health").headers["cache-control"] == "no-store"


def test_no_inline_script_so_the_csp_can_forbid_it():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    assert re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html) == []
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handler in index.html"


def test_every_innerhtml_write_goes_through_the_escaping_tag():
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    writes = re.findall(r"\.innerHTML\s*=\s*(.{0,3})", js)
    assert writes, "expected innerHTML writes in app.js"
    assert all(w.startswith("h`") for w in writes), writes


def test_static_pages_escape_pdf_text():
    from scripts.build_demo_paimana import _e
    assert _e("<img src=x onerror=alert(1)>") == "&lt;img src=x onerror=alert(1)&gt;"
    assert _e("J&K 'x'") == "J&amp;K &#x27;x&#x27;"


# ---------------------------------------------------------------------------
# Integrity manifest
# ---------------------------------------------------------------------------

def _tree(tmp: Path) -> None:
    (tmp / "app").mkdir()
    (tmp / "app" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp / "results" / "paimana").mkdir(parents=True)
    (tmp / "results" / "paimana" / "panel.csv").write_text("entity_id,x\n1,2\n", encoding="utf-8")


def test_integrity_detects_tamper_wrong_key_and_planted_files():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        _tree(tmp)
        integrity.seal(tmp, key=KEY)
        assert integrity.verify(tmp, key=KEY, require_signature=True)["signature"] == "valid"

        # the same content with Windows line endings is the same file
        (tmp / "app" / "main.py").write_bytes(b"print('hi')\r\n")
        integrity.verify(tmp, key=KEY, require_signature=True)

        for mutate, expect in (
            (lambda: (tmp / "results/paimana/panel.csv").write_text("entity_id,x\n1,3\n"), "changed"),
            (lambda: (tmp / "app" / "backdoor.py").write_text("x=1\n"), "not in manifest"),
        ):
            integrity.seal(tmp, key=KEY)
            mutate()
            try:
                integrity.verify(tmp, key=KEY)
            except integrity.IntegrityError as exc:
                assert expect in str(exc), str(exc)
            else:
                raise AssertionError(f"verify accepted a tree with a {expect} file")
            (tmp / "app" / "backdoor.py").unlink(missing_ok=True)

        integrity.seal(tmp, key=KEY)
        try:
            integrity.verify(tmp, key="z" * 40)
        except integrity.IntegrityError as exc:
            assert "signature" in str(exc)
        else:
            raise AssertionError("a different key verified the signature")

        integrity.seal(tmp, key=None)            # an agent can re-hash, not sign
        try:
            integrity.verify(tmp, key=KEY, require_signature=True)
        except integrity.IntegrityError as exc:
            assert "signature" in str(exc)
        else:
            raise AssertionError("an unsigned manifest passed require_signature")


def test_repository_manifest_matches_the_working_tree():
    """CI's own check: the sealed hashes match what is committed. Fails when a
    file changes without a re-seal, which forces that change through review."""
    integrity.verify(ROOT)


# ---------------------------------------------------------------------------
# Ingest: listing, download, corpus
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, url, body=b"%PDF-1.4\n%%EOF\n", length=None):
        self.url, self._body = url, body
        self.headers = {} if length is None else {"Content-Length": str(length)}

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=65536):
        yield self._body

    def close(self):
        pass


class _Session:
    def __init__(self, resp):
        self.resp = resp

    def get(self, *a, **k):
        return self.resp


def test_harvester_refuses_unsafe_names_redirects_and_oversize():
    from scripts import harvest_paimana as hp
    good = "https://paimana-proj.mospi.gov.in/ReportPage/ViewPdf?id=1&path=x"
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d)
        for path, resp in (
            ("flash/../../evil.py", _Resp(good)),
            ("flash/.bashrc.pdf", _Resp(good)),
            ("flash/ok.pdf", _Resp("https://attacker.example/x.pdf")),
            ("flash/ok.pdf", _Resp(good.replace("https", "http"))),
            ("flash/ok.pdf", _Resp(good, length=hp.MAX_PDF_BYTES + 1)),
        ):
            rec = {"report_id": "1", "path": path, "full_url": good}
            try:
                hp.download_one(rec, dest, _Session(resp))
            except hp.UnsafeDownload:
                pass
            else:
                raise AssertionError(f"download accepted: {path} via {resp.url}")
        assert list(dest.iterdir()) == [], "a refused download left a file behind"

        rec = {"report_id": "1", "path": "flash/ok.pdf", "full_url": good}
        out = hp.download_one(rec, dest, _Session(_Resp(good, length=10_000)))
        assert out["status"] == "invalid_pdf" and "truncated" in out["error"]


def test_parser_reads_only_manifest_listed_pdfs():
    from scripts import parse_paimana as pp
    saved = pp.RAW
    with tempfile.TemporaryDirectory() as d:
        raw = Path(d)
        with (raw / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["filename", "sha256"])
            w.writerow(["FlashReport_July_2026.pdf", "0" * 64])
        (raw / "FlashReport_July_2026.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        pp.RAW = raw
        try:
            assert [p.name for p in pp.manifest_listed()] == ["FlashReport_July_2026.pdf"]
            (raw / "Planted_Report.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
            try:
                pp.manifest_listed()
            except SystemExit as exc:
                assert "Planted_Report.pdf" in str(exc)
            else:
                raise AssertionError("an unlisted PDF would have been parsed")
        finally:
            pp.RAW = saved
