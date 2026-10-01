"""Sign the release with the integrity key that is ALREADY in Railway.

    python deploy/sign_release.py            # reads the key from the clipboard
    python deploy/sign_release.py --prompt   # or type/paste it at a hidden prompt

Copy ANUMAAN_INTEGRITY_KEY's value from Railway -> Variables first.

Before signing anything it checks the key against the signature of the
build that is live now (integrity/MANIFEST.json on origin/main). A wrong key
- for example one copied with its "ANUMAAN_INTEGRITY_KEY=" prefix or quotes -
is refused here, on your machine, instead of producing a build that Railway
cannot start. The key is never printed or written to disk.

Run it yourself (AGENTS.md: an agent must never hold the integrity key).
"""
from __future__ import annotations

import argparse
import getpass
import hmac
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import integrity  # noqa: E402

LIVE_REF = "origin/main"
MANIFEST_IN_REPO = "anumaan/integrity/MANIFEST.json"


def read_clipboard() -> str:
    if sys.platform == "win32":
        cmd = ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]
    else:
        cmd = ["sh", "-c", "pbpaste 2>/dev/null || wl-paste 2>/dev/null || xclip -o -selection clipboard"]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def clean(raw: str) -> str:
    # Accepts the bare value, one KEY=value line, or Railway's whole Raw Editor
    # (ENV or JSON view): the ANUMAAN_INTEGRITY_KEY entry is picked out.
    found = re.search(r'ANUMAAN_INTEGRITY_KEY"?\s*[:=]\s*["\']?([^"\'\s,]+)', raw)
    if found:
        return found.group(1)
    key = raw.strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
        key = key[1:-1].strip()
    return key


def live_manifest() -> dict:
    subprocess.run(["git", "fetch", "-q", "origin", "main"], cwd=ROOT, check=True)
    out = subprocess.run(["git", "show", f"{LIVE_REF}:{MANIFEST_IN_REPO}"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", action="store_true", help="type/paste the key at a hidden prompt instead")
    args = ap.parse_args()

    key = clean(getpass.getpass("integrity key (hidden): ") if args.prompt else read_clipboard())
    if len(key) < integrity.MIN_KEY_CHARS:
        print(f"That is not an integrity key ({len(key)} characters, need {integrity.MIN_KEY_CHARS}+). "
              "Copy the value of ANUMAAN_INTEGRITY_KEY from Railway and run this again.", file=sys.stderr)
        return 1

    live = live_manifest()
    if not live.get("hmac_sha256"):
        print(f"The live manifest on {LIVE_REF} is unsigned, so there is no key to check against.", file=sys.stderr)
        return 1
    if not hmac.compare_digest(integrity.sign(live["files"], key), live["hmac_sha256"]):
        print("This is NOT the key the live site uses. Nothing was signed.\n"
              "In Railway -> Variables, reveal ANUMAAN_INTEGRITY_KEY, copy only its value, and run this again.",
              file=sys.stderr)
        return 1

    blob = integrity.seal(key=key)
    report = integrity.verify(key=key, require_signature=True)
    print(f"OK: the key matches the live site. Signed {blob['n_files']} files "
          f"(signature {report['signature']}). Tell Claude: signed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
