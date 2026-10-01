"""Prepare a signed release for Railway. Run it yourself, in your own terminal.

    python deploy/prepare_railway_release.py [--user mospi] [--host <railway host>]

It generates the viewer password, the admin token and the integrity key;
signs integrity/MANIFEST.json with that key and verifies the signature; and
copies the five Railway variables to the clipboard, ready to paste into
Railway -> Variables -> Raw Editor.

What it deliberately does not do:
- write any secret to disk (the key and token exist only in the clipboard
  until you paste them into Railway, and in Railway after that);
- print the integrity key or admin token (only the viewer login is shown,
  because you have to share it with your team and the judges).

It is a human step on purpose. AGENTS.md: an AI agent must never create the
integrity key or sign the manifest, because an agent holding the key could
change the backend and re-sign it.

If the clipboard is lost before you paste, run it again: it re-signs with a
new key, and you then need to paste the new values.
"""
from __future__ import annotations

import argparse
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import integrity  # noqa: E402

DEFAULT_HOST = "sih2026-ps26103-production.up.railway.app"
RAILWAY_HEALTHCHECK_HOST = "healthcheck.railway.app"   # Railway's health check sends this Host


def to_clipboard(text: str) -> bool:
    for cmd in (["clip"], ["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=text.encode("ascii"), check=True)
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", default="mospi", help="viewer login name (default: mospi)")
    ap.add_argument("--host", default=DEFAULT_HOST, help=f"public Railway host (default: {DEFAULT_HOST})")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", args.user):
        print("--user: 3-64 characters, letters, digits, dot, dash, underscore", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", args.host.lower()):
        print("--host: a host name such as your-app.up.railway.app", file=sys.stderr)
        return 2

    view_password = secrets.token_urlsafe(12)      # 16 characters
    admin_token = secrets.token_urlsafe(48)        # 64 characters
    integrity_key = secrets.token_urlsafe(48)      # 64 characters

    blob = integrity.seal(key=integrity_key)
    report = integrity.verify(key=integrity_key, require_signature=True)
    print(f"signed {blob['n_files']} files -> integrity/MANIFEST.json (signature {report['signature']})")

    variables = "\n".join([
        f"ANUMAAN_VIEW_USER={args.user}",
        f"ANUMAAN_VIEW_PASSWORD={view_password}",
        f"ANUMAAN_ADMIN_TOKEN={admin_token}",
        f"ANUMAAN_INTEGRITY_KEY={integrity_key}",
        f"ANUMAAN_ALLOWED_HOSTS={args.host.lower()},{RAILWAY_HEALTHCHECK_HOST}",
    ]) + "\n"

    if not to_clipboard(variables):
        print("No clipboard tool found. Paste these five lines into Railway yourself:\n")
        print(variables)
    else:
        print("The five Railway variables are on your clipboard.")
        print("  -> Railway: SIH2026-PS26103 service -> Variables -> Raw Editor -> paste -> Update Variables")
        print("  -> Then copy any other text, so the key does not stay on the clipboard.")
    print()
    print("Dashboard login to share with your team and the judges:")
    print(f"  user:     {args.user}")
    print(f"  password: {view_password}")
    print()
    print("The integrity key and admin token are not shown or saved. Keep them only in")
    print("Railway (and a password manager if you want a copy). Next: commit")
    print("integrity/MANIFEST.json, merge to main, push.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
