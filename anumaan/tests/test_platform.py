"""Tests for the deck-driven platform features: ministry-scoped logins,
tamper-evident audit log, personal-data redaction, offline snapshot and
bundle, Laya remark triage, SBOM / AI-BOM. Plain functions with no pytest
fixtures, so tests/run_tests.py can run them too."""
from __future__ import annotations

import base64
import contextlib
import gzip
import hashlib
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import laya_client, security as sec  # noqa: E402
from app.audit import AuditLog, verify_file  # noqa: E402
from app.main import app  # noqa: E402
from app.redact import redact  # noqa: E402
from app.users import AuthCache, UserStore, hash_password, verify_password  # noqa: E402

ENV_KEYS = ("ANUMAAN_ENV", "ANUMAAN_VIEW_USER", "ANUMAAN_VIEW_PASSWORD", "ANUMAAN_ADMIN_TOKEN",
            "ANUMAAN_INTEGRITY_KEY", "ANUMAAN_ALLOWED_HOSTS", "ANUMAAN_USERS_FILE",
            "ANUMAAN_AUDIT_FILE", "ANUMAAN_LAYA_URL", "ANUMAAN_LAYA_TOKEN",
            "ANUMAAN_RATE_API_PER_MIN", "ANUMAAN_MAX_BODY_BYTES")
MORTH = "Ministry of Road Transport & Highways"
RAIL = "Ministry of Railways"
PW = "correct-horse-battery-1"
LAYA_TOKEN = "t" * 40


@contextlib.contextmanager
def env(**values):
    saved = {k: os.environ.get(k) for k in ENV_KEYS}
    try:
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        os.environ.update(values)
        sec.LIMITER.reset()
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        sec.LIMITER.reset()


@contextlib.contextmanager
def client(**values):
    with env(**values), TestClient(app) as c:
        yield c


def basic(user: str, pw: str = PW) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}


_USERS_FILE = None


def users_file() -> str:
    """One users file for the module: scrypt hashing is deliberately slow."""
    global _USERS_FILE
    if _USERS_FILE is None:
        d = tempfile.mkdtemp()
        h = hash_password(PW)
        blob = {"users": [
            {"user": "ipmd.admin", "role": "mospi", "ministry": None, "password": h},
            {"user": "morth.nodal", "role": "ministry", "ministry": MORTH, "password": h},
            {"user": "rail.nodal", "role": "ministry", "ministry": RAIL, "password": h},
        ]}
        _USERS_FILE = os.path.join(d, "users.json")
        Path(_USERS_FILE).write_text(json.dumps(blob), encoding="utf-8")
    return _USERS_FILE


# ---------------------------------------------------------------------------
# Ministry-scoped logins
# ---------------------------------------------------------------------------

def test_password_hashing_and_auth_cache():
    h = hash_password(PW)
    assert h.startswith("scrypt$") and PW not in h
    assert verify_password(PW, h) and not verify_password(PW + "x", h)
    store = UserStore.from_file(Path(users_file()))
    cache = AuthCache()
    hdr = basic("morth.nodal")["Authorization"]
    p = sec.resolve_principal(store, cache, hdr)
    assert p.role == "ministry" and p.ministry == MORTH
    assert cache.get(hdr) == p                        # second request skips scrypt
    wrong = basic("morth.nodal", "wrong-password-x")["Authorization"]
    assert sec.resolve_principal(store, cache, wrong) is None
    assert sec.resolve_principal(store, cache, basic("nobody")["Authorization"]) is None


def test_ministry_user_sees_only_its_ministry_everywhere():
    with client(ANUMAAN_USERS_FILE=users_file()) as c:
        st = c.get("/api/status", headers=basic("morth.nodal")).json()
        assert st["principal"] == {"user": "morth.nodal", "role": "ministry", "ministry": MORTH}
        d = c.get("/api/projects?limit=500", headers=basic("morth.nodal")).json()
        assert d["count"] > 0 and {a["ministry"] for a in d["alerts"]} == {MORTH}
        assert d["ministries"] == [MORTH]
        rail = c.get("/api/projects?limit=500", headers=basic("rail.nodal")).json()
        assert {a["ministry"] for a in rail["alerts"]} == {RAIL}
        rail_id = rail["alerts"][0]["entity_id"]
        morth_id = d["alerts"][0]["entity_id"]
        # another ministry's project is indistinguishable from a missing one
        r = c.get(f"/api/project/{rail_id}", headers=basic("morth.nodal"))
        assert r.status_code == 404 and r.json() == {"detail": "unknown project"}
        assert c.get(f"/api/project/{morth_id}", headers=basic("morth.nodal")).status_code == 200
        assert c.post("/api/score", json={"entity_id": rail_id},
                      headers=basic("morth.nodal")).status_code == 404
        assert c.post(f"/api/project/{rail_id}/remark", json={"text": "probe"},
                      headers=basic("morth.nodal")).status_code == 404
        snap = c.get("/api/snapshot", headers=basic("morth.nodal")).json()
        assert snap["dict"]["ministry"] == [MORTH] and snap["scope"]["ministry"] == MORTH
        allsnap = c.get("/api/snapshot", headers=basic("ipmd.admin")).json()
        assert allsnap["n_projects"] > snap["n_projects"] and len(allsnap["dict"]["ministry"]) > 1
        bundle = c.get("/api/offline-bundle", headers=basic("rail.nodal")).text
        data = json.loads(re.search(r'id="data">(.*?)</script>', bundle, re.S).group(1))
        assert data["dict"]["ministry"] == [RAIL] and data["n_projects"] == len(data["rows"])
        rail_ids = {a["entity_id"] for a in rail["alerts"]}
        morth_ids = {a["entity_id"] for a in d["alerts"]}
        assert not ({r[0] for r in data["rows"]} & morth_ids) and rail_ids


def test_users_file_naming_an_unknown_ministry_stops_startup():
    d = tempfile.mkdtemp()
    f = os.path.join(d, "users.json")
    Path(f).write_text(json.dumps({"users": [{"user": "typo.user", "role": "ministry",
                                              "ministry": "Ministry of Raliways",
                                              "password": hash_password(PW)}]}), encoding="utf-8")
    try:
        with client(ANUMAAN_USERS_FILE=f):
            pass
    except RuntimeError as exc:
        assert "Raliways" in str(exc)
    else:
        raise AssertionError("a misspelt ministry login started")


def test_users_cli_refuses_a_ministry_not_in_the_panel():
    d = tempfile.mkdtemp()
    f = os.path.join(d, "u.json")
    py = sys.executable
    ok = subprocess.run([py, "scripts/users.py", "--file", f, "add", "--user", "rail.x",
                         "--role", "ministry", "--ministry", RAIL, "--password-stdin"],
                        input=PW + "\n", capture_output=True, text=True, cwd=ROOT)
    assert ok.returncode == 0, ok.stderr
    stored = Path(f).read_text(encoding="utf-8")
    assert json.loads(stored)["users"][0]["password"].startswith("scrypt$") and PW not in stored
    bad = subprocess.run([py, "scripts/users.py", "--file", f, "add", "--user", "rail.y",
                          "--role", "ministry", "--ministry", "Ministry of Nothing",
                          "--password-stdin"],
                         input=PW + "\n", capture_output=True, text=True, cwd=ROOT)
    assert bad.returncode != 0


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def test_audit_chain_detects_edit_removal_and_reorder():
    d = tempfile.mkdtemp()
    f = Path(d) / "audit.jsonl"
    log = AuditLog(f)
    for i in range(5):
        log.write({"event": "view_project", "user": "u", "entity_id": str(i)})
    assert verify_file(f) == (5, [])
    AuditLog(f).write({"event": "restart-continues-chain"})       # reopen continues
    assert verify_file(f)[1] == []
    lines = f.read_text(encoding="utf-8").splitlines()
    for mutate in (lambda L: L[:2] + [L[2].replace('"2"', '"9"')] + L[3:],   # edit
                   lambda L: L[:2] + L[3:],                                   # removal
                   lambda L: [L[0], L[2], L[1]] + L[3:]):                     # reorder
        g = Path(d) / "bad.jsonl"
        g.write_text("\n".join(mutate(lines)) + "\n", encoding="utf-8")
        assert verify_file(g)[1], "tampering went undetected"
    f.write_text("\n".join(lines[:-1] + [lines[-1].replace("restart", "RESTART")]) + "\n",
                 encoding="utf-8")
    try:
        AuditLog(f)
    except RuntimeError:
        pass
    else:
        raise AssertionError("an edited log was reopened for appending")


def test_every_project_view_and_export_is_audited():
    d = tempfile.mkdtemp()
    f = Path(d) / "audit.jsonl"
    with client(ANUMAAN_USERS_FILE=users_file(), ANUMAAN_AUDIT_FILE=str(f)) as c:
        pid = c.get("/api/projects?limit=1", headers=basic("ipmd.admin")).json()["alerts"][0]["entity_id"]
        c.get(f"/api/project/{pid}", headers=basic("ipmd.admin"))
        c.get("/api/snapshot", headers=basic("ipmd.admin"))
        c.get("/api/offline-bundle", headers=basic("ipmd.admin"))
        c.get("/api/metrics", headers=basic("ipmd.admin", "wrong-password-x"))
    events = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
    kinds = [e.get("event") for e in events]
    assert "view_project" in kinds and "export_snapshot" in kinds and "export_bundle" in kinds
    failed = [e for e in events if e.get("status") == 401]
    assert failed and failed[0]["user_attempted"] == "ipmd.admin"
    raw = f.read_text(encoding="utf-8")
    assert "wrong-password-x" not in raw and "Authorization" not in raw and PW not in raw
    assert verify_file(f)[1] == []


# ---------------------------------------------------------------------------
# Redaction and remarks
# ---------------------------------------------------------------------------

def test_redaction_masks_identifiers_but_keeps_project_facts():
    text = ("Call contractor at +91 9876543210 or 09876543210, mail pm@nhai.org. "
            "Aadhaar 2345 6789 0123, PAN ABCDE1234F, a/c 123456789012345, IFSC SBIN0001234. "
            "Project 619103, Rs 1,234.56 crore, due 07/2026.")
    out, found = redact(text)
    for secret in ("9876543210", "pm@nhai.org", "2345 6789 0123", "ABCDE1234F",
                   "123456789012345", "SBIN0001234"):
        assert secret not in out, secret
    for kept in ("619103", "Rs 1,234.56 crore", "07/2026"):
        assert kept in out, kept
    assert found["phone"] == 2 and found["email"] == 1 and found["aadhaar"] == 1


class _StubLaya(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        return None

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("X-Laya-Token") != LAYA_TOKEN:
            self.send_response(401)
            self.end_headers()
            return
        remark = body["state"]["remark"].lower()
        cause = "land_acquisition" if "land" in remark else "contractor_performance"
        p = 0.9 if ("land" in remark or "contractor" in remark) else 0.1
        out = {"answers": {"describes_delay": {"type": "noul", "noul": p},
                           "cause": {"type": "choice", "choice": cause,
                                     "probabilities": {cause: 0.99, "litigation": 0.01}}},
               "ms": 12.5, "revision": "68f27dfe5a27"}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_remark_is_redacted_triaged_and_routed():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StubLaya)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with client(ANUMAAN_USERS_FILE=users_file(), ANUMAAN_LAYA_URL=url,
                    ANUMAAN_LAYA_TOKEN=LAYA_TOKEN) as c:
            h = basic("morth.nodal")
            pid = c.get("/api/projects?limit=1", headers=h).json()["alerts"][0]["entity_id"]
            r = c.post(f"/api/project/{pid}/remark", headers=h,
                       json={"text": "Land compensation pending; call 9876543210 for details."}).json()
            assert "9876543210" not in r["text"] and r["personal_data_removed"] == {"phone": 1}
            t = r["triage"]
            assert t["status"] == "ok" and t["routing"] == "auto"
            assert t["suggested_cause"] == "land_acquisition"
            assert t["owner"] == "State revenue department / district collector"
            vague = c.post(f"/api/project/{pid}/remark", headers=h,
                           json={"text": "Status as reported earlier."}).json()["triage"]
            assert vague["routing"] == "human_review" and vague["owner"] == "n/a"
            page = c.get(f"/api/project/{pid}", headers=h).json()
            assert len(page["remarks"]) >= 2 and page["remarks"][0]["text"] == "Status as reported earlier."
    finally:
        srv.shutdown()


def test_remark_without_laya_is_recorded_not_guessed():
    with client() as c:
        pid = c.get("/api/projects?limit=1").json()["alerts"][0]["entity_id"]
        r = c.post(f"/api/project/{pid}/remark", json={"text": "Land handed over last week."}).json()
        assert r["triage"]["status"] == "not_configured"
        assert "suggested_cause" not in r["triage"]


def test_laya_unreachable_is_reported_not_guessed():
    out = laya_client.triage("http://127.0.0.1:9", LAYA_TOKEN, "land pending",
                             {"land_acquisition": {}}, 0.6)
    assert out["status"] == "unavailable" and "suggested_cause" not in out


def test_laya_url_without_a_token_is_refused():
    with env(ANUMAAN_LAYA_URL="http://127.0.0.1:8090"):
        assert any("ANUMAAN_LAYA_TOKEN" in p for p in sec.load_settings().problems)


# ---------------------------------------------------------------------------
# Offline: snapshot, bundle, service worker, speed
# ---------------------------------------------------------------------------

def test_snapshot_is_compact_scored_gzipped_and_revalidates():
    with client() as c:
        r = c.get("/api/snapshot", headers={"accept-encoding": "gzip"})
        assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
        s = r.json()
        assert s["format"] == "anumaan-snapshot/1" and s["month"] == "2026-07"
        assert s["outcome_known"] is False and s["n_projects"] == len(s["rows"]) > 1000
        assert s["columns"][0] == "id" and all(0 <= row[9] <= 1 for row in s["rows"])
        ps = [row[9] for row in s["rows"]]
        assert ps == sorted(ps, reverse=True)
        etag = r.headers["etag"]
        again = c.get("/api/snapshot", headers={"if-none-match": etag})
        assert again.status_code == 304 and again.content == b""


def test_offline_bundle_is_self_contained_and_cannot_call_out():
    with client() as c:
        r = c.get("/api/offline-bundle")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    page = r.text
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', page).group(1)
    assert "default-src 'none'" in csp and "connect-src" not in csp
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    want = "sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"script-src '{want}'" in csp                      # the one script is pinned by hash
    data = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S).group(1)
    assert "<" not in data
    sha = hashlib.sha256(data.encode()).hexdigest()
    assert sha == re.search(r'data-sha256="([0-9a-f]{64})"', page).group(1)
    assert r.headers["x-content-sha256"] == sha
    assert not re.search(r'(src|href)="https?://', page)


def test_service_worker_and_manifest_are_public_but_data_is_not():
    with client(ANUMAAN_USERS_FILE=users_file()) as c:
        sw = c.get("/sw.js")
        assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
        assert "anumaan-shell" in sw.text
        assert c.get("/manifest.webmanifest").status_code == 200
        assert c.get("/api/snapshot").status_code == 401
        assert c.get("/api/offline-bundle").status_code == 401


def test_rate_limit_is_per_user_not_per_shared_proxy_ip():
    with client(ANUMAAN_USERS_FILE=users_file(), ANUMAAN_RATE_API_PER_MIN="3") as c:
        codes_a = [c.get("/api/metrics", headers=basic("morth.nodal")).status_code for _ in range(4)]
        code_b = c.get("/api/metrics", headers=basic("rail.nodal")).status_code
    assert codes_a == [200, 200, 200, 429] and code_b == 200


def test_watchlist_order_is_deterministic():
    with client() as c:
        a = c.get("/api/projects?limit=500").json()["alerts"]
        b = c.get("/api/projects?limit=500").json()["alerts"]
    ps = [x["p_slip"] for x in a]
    assert ps == sorted(ps, reverse=True) and a == b


def test_offline_drivers_are_readable_sentences():
    with client() as c:
        s = c.get("/api/snapshot").json()
    drivers = s["dict"]["driver"]
    assert drivers and not any(d.startswith("min ") for d in drivers)
    assert any(d.startswith("ministry is") for d in drivers)


def test_gzip_really_shrinks_the_wire():
    with client() as c:
        with c.stream("GET", "/api/projects?limit=500", headers={"accept-encoding": "gzip"}) as r:
            wire = b"".join(r.iter_raw())
    assert len(gzip.decompress(wire)) > 3 * len(wire)


# ---------------------------------------------------------------------------
# SBOM / AI-BOM
# ---------------------------------------------------------------------------

def test_sbom_and_aibom_are_generated_from_the_environment():
    r = subprocess.run([sys.executable, "scripts/make_sbom.py"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    sbom = json.loads((ROOT / "results/sbom/sbom.cdx.json").read_text(encoding="utf-8"))
    names = {c["name"].lower() for c in sbom["components"]}
    assert sbom["bomFormat"] == "CycloneDX" and {"lightgbm", "fastapi"} <= names
    ai = json.loads((ROOT / "results/sbom/aibom.cdx.json").read_text(encoding="utf-8"))
    kinds = [c["type"] for c in ai["components"]]
    assert "machine-learning-model" in kinds and "data" in kinds
    slip = next(c for c in ai["components"] if c["bom-ref"] == "model:slip")
    metrics = json.loads((ROOT / "results/paimana/metrics_slip.json").read_text(encoding="utf-8"))
    want = str(round(metrics["folds"][-1]["models"]["lightgbm"]["pr_auc"], 4))
    assert slip["modelCard"]["quantitativeAnalysis"]["performanceMetrics"][0]["value"] == want
