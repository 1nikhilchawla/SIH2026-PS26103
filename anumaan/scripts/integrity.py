#!/usr/bin/env python3
"""Seal and verify the files the live service runs on.

Why this exists
    The PDF corpus is pinned by SHA-256 (scripts/verify_corpus.py), but until
    now nothing bound the *derived* panel or the *code* to anything. Anyone -
    or any coding agent - with write access could edit results/paimana/
    panel.csv or app/main.py and the build and the service would accept it.
    A reviewer can read a code diff; nobody can eyeball a 17,010-row CSV diff.

What it does
    `seal`   hashes every file in COVERED into integrity/MANIFEST.json and, if a
             key is available, signs the hash list with HMAC-SHA256.
    `verify` recomputes the hashes, fails on any changed, missing or unexpected
             file, and checks the HMAC when a key is available.

Where the guarantee comes from
    The key. It lives in the deploy platform's secret store and with the
    maintainer - never in the repository, never in a shell profile an agent
    can read. Without it, anyone can re-seal the hashes but cannot produce a
    signature production will accept, so a tampered panel or a tampered file
    stops the service at startup instead of being served.

What it cannot do
    Stop an edit that also deletes the check. That is the job of branch
    protection plus required review on the paths in .github/CODEOWNERS - see
    SECURITY.md. The two together are the control: review catches the code
    change, the signature catches the data change.

Line endings are normalised (CRLF -> LF) before hashing, so a Windows checkout
with core.autocrlf=true and the Linux container produce the same digest.

Usage:
    python scripts/integrity.py seal                 # hashes only (unsigned)
    python scripts/integrity.py seal --prompt-key    # sign; key typed, not echoed
    python scripts/integrity.py verify
    python scripts/integrity.py verify --require-signature
Key source for seal/verify: ANUMAAN_INTEGRITY_KEY, or --prompt-key.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import getpass
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "integrity" / "MANIFEST.json"
MIN_KEY_CHARS = 32

# Everything the container ships and the service reads or executes.
# Globs are relative to ROOT. Keep in step with the Dockerfile COPY lines.
COVERED = (
    "app/*.py",
    "app/static/*",
    "scripts/*.py",
    "config/*.yaml",
    "requirements.txt",
    "requirements-py314.txt",
    "Dockerfile",
    "railway.json",
    "results/paimana/panel.csv",
    "results/paimana/panel_provenance.json",
    "results/paimana/manifest_verification.json",
    "results/paimana/reconciliation_meta.json",
    "results/paimana/cost_target_diagnostic.json",
)


class IntegrityError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def covered_files(root: Path = ROOT) -> list[str]:
    out: set[str] = set()
    for pattern in COVERED:
        for p in root.glob(pattern):
            if p.is_file() and "__pycache__" not in p.parts:
                out.add(p.relative_to(root).as_posix())
    return sorted(out)


def compute(root: Path = ROOT) -> dict[str, str]:
    return {rel: _digest(root / rel) for rel in covered_files(root)}


def _canonical(files: dict[str, str]) -> bytes:
    return json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign(files: dict[str, str], key: str) -> str:
    return hmac.new(key.encode("utf-8"), _canonical(files), hashlib.sha256).hexdigest()


def seal(root: Path = ROOT, key: str | None = None, manifest: Path | None = None) -> dict:
    if key is not None and len(key) < MIN_KEY_CHARS:
        raise IntegrityError(f"integrity key must be at least {MIN_KEY_CHARS} characters")
    files = compute(root)
    blob = {
        "version": 1,
        "sealed_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "algorithm": "sha256, CRLF normalised to LF; signature HMAC-SHA256 over "
                     "the sorted compact JSON of `files`",
        "n_files": len(files),
        "files": files,
        "hmac_sha256": sign(files, key) if key else None,
    }
    target = manifest or (root / "integrity" / "MANIFEST.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(blob, indent=1) + "\n", encoding="utf-8")
    return blob


def verify(root: Path = ROOT, key: str | None = None, require_signature: bool = False,
           manifest: Path | None = None) -> dict:
    """Raise IntegrityError on any mismatch. Returns a short report on success."""
    target = manifest or (root / "integrity" / "MANIFEST.json")
    if not target.exists():
        raise IntegrityError(f"{target.name} missing - run: python scripts/integrity.py seal")
    blob = json.loads(target.read_text(encoding="utf-8"))
    sealed: dict[str, str] = blob.get("files") or {}
    actual = compute(root)

    changed = sorted(k for k in sealed if k in actual and actual[k] != sealed[k])
    missing = sorted(k for k in sealed if k not in actual)
    unexpected = sorted(k for k in actual if k not in sealed)
    problems = ([f"changed: {k}" for k in changed] + [f"missing: {k}" for k in missing]
                + [f"not in manifest: {k}" for k in unexpected])

    sig = blob.get("hmac_sha256")
    signature = "absent"
    if sig:
        if key:
            if hmac.compare_digest(sign(sealed, key), sig):
                signature = "valid"
            else:
                problems.append("signature does not match - sealed with a different key, "
                                "or the file list was edited after signing")
                signature = "invalid"
        else:
            signature = "present, not checked (no key)"
    if require_signature and signature != "valid":
        problems.append(f"a valid signature is required, signature is {signature}")

    if problems:
        raise IntegrityError("integrity check failed:\n  - " + "\n  - ".join(problems))
    return {"n_files": len(sealed), "signature": signature,
            "sealed_at": blob.get("sealed_at")}


def _key(args: argparse.Namespace) -> str | None:
    if getattr(args, "prompt_key", False):
        return getpass.getpass("integrity key (not echoed): ")
    return os.environ.get("ANUMAAN_INTEGRITY_KEY") or None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seal")
    s.add_argument("--prompt-key", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--prompt-key", action="store_true")
    v.add_argument("--require-signature", action="store_true")
    args = ap.parse_args()

    try:
        if args.cmd == "seal":
            blob = seal(key=_key(args))
            print(f"sealed {blob['n_files']} files -> {MANIFEST.relative_to(ROOT).as_posix()} "
                  f"(signed: {'yes' if blob['hmac_sha256'] else 'no'})")
            return 0
        rep = verify(key=_key(args), require_signature=args.require_signature)
        print(f"integrity ok: {rep['n_files']} files, signature {rep['signature']}, "
              f"sealed {rep['sealed_at']}")
        return 0
    except IntegrityError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
