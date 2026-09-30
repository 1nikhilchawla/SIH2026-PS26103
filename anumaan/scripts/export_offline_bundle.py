#!/usr/bin/env python3
"""Write the offline bundle to a file - for a pen drive, an e-mail, or a
district office with no connection.

    python scripts/export_offline_bundle.py                         all ministries
    python scripts/export_offline_bundle.py --ministry "Ministry of Railways"
    python scripts/export_offline_bundle.py --out D:/anumaan-offline.html

Same code path as GET /api/offline-bundle (app/offline.py): trains the model
exactly as the service does at startup, scores every project in the latest
report, filters to the ministry if given, and writes one self-contained HTML
file. The file opens in any browser with no server, cannot make a network
request (CSP default-src 'none'), and checks its own SHA-256 when opened.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ministry", help="exact ministry name (scripts/users.py ministries)")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    from app import main as svc, offline
    from app.users import Principal

    with contextlib.redirect_stdout(io.StringIO()):
        svc._load_and_train()
    live = svc.STATE["live"]
    known = set(live["df"]["ministry"].dropna())
    if args.ministry and args.ministry not in known:
        raise SystemExit(f"{args.ministry!r} is not in the latest report. "
                         "Run `python scripts/users.py ministries` for the exact names.")
    who = (Principal("export-script", "ministry", args.ministry) if args.ministry
           else Principal("export-script", "mospi"))
    snap_obj, _body, _etag = svc._scoped_snapshot(who)
    page, sha = offline.render_bundle(snap_obj)
    out = args.out or (ROOT / "demo" / "offline" /
                       f"anumaan-offline-{snap_obj['month']}-{svc._slug(args.ministry)}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} - {snap_obj['n_projects']} projects, {out.stat().st_size:,} bytes, "
          f"data SHA-256 {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
