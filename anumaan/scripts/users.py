#!/usr/bin/env python3
"""Manage ANUMAAN logins (the file ANUMAAN_USERS_FILE points at).

    python scripts/users.py ministries
        print the exact ministry names in the panel - a ministry login must
        use one of these, character for character
    python scripts/users.py add --user morth.nodal --role ministry \\
        --ministry "Ministry of Road Transport & Highways"
    python scripts/users.py add --user ipmd.admin --role mospi
    python scripts/users.py list
    python scripts/users.py remove --user morth.nodal

Passwords are typed twice and never echoed (or read from stdin with
--password-stdin, for automation). Only a scrypt hash is written. The default
file is secrets/users.json, which .gitignore and .dockerignore both exclude:
it is mounted into the container at run time, never baked into the image.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.users import MIN_PASSWORD_CHARS, ROLES, USERNAME_RE, hash_password  # noqa: E402

DEFAULT_FILE = ROOT / "secrets" / "users.json"
PANEL = ROOT / "results" / "paimana" / "panel.csv"


def panel_ministries() -> list[str]:
    import pandas as pd
    col = pd.read_csv(PANEL, usecols=["ministry"])["ministry"]
    missing = int(col.isna().sum())
    if missing:
        raise SystemExit(f"panel has {missing} rows with no ministry - rebuild the panel first")
    return sorted(col.unique().tolist())


def load(path: Path) -> dict:
    if not path.exists():
        return {"users": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, blob: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(blob, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)                     # owner read/write only (POSIX)
    except OSError as exc:
        print(f"note: could not restrict permissions on {path}: {exc}", file=sys.stderr)


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        pw = sys.stdin.readline().rstrip("\n")
    else:
        pw = getpass.getpass("password (not echoed): ")
        if getpass.getpass("again: ") != pw:
            raise SystemExit("passwords do not match")
    if len(pw) < MIN_PASSWORD_CHARS:
        raise SystemExit(f"password must be at least {MIN_PASSWORD_CHARS} characters")
    return pw


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ministries")
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("--user", required=True)
    a.add_argument("--role", required=True, choices=ROLES)
    a.add_argument("--ministry")
    a.add_argument("--password-stdin", action="store_true")
    r = sub.add_parser("remove")
    r.add_argument("--user", required=True)
    args = ap.parse_args()

    if args.cmd == "ministries":
        for m in panel_ministries():
            print(m)
        return 0

    blob = load(args.file)
    users = blob.setdefault("users", [])

    if args.cmd == "list":
        for u in users:
            print(f"{u['user']:24s} {u['role']:9s} {u.get('ministry') or '(all ministries)'}")
        print(f"{len(users)} user(s) in {args.file}")
        return 0

    if args.cmd == "remove":
        kept = [u for u in users if u["user"] != args.user]
        if len(kept) == len(users):
            raise SystemExit(f"no user {args.user!r}")
        blob["users"] = kept
        save(args.file, blob)
        print(f"removed {args.user}")
        return 0

    # add
    if not USERNAME_RE.fullmatch(args.user):
        raise SystemExit("user name: 3-64 characters, letters, digits, _ . @ -")
    if any(u["user"] == args.user for u in users):
        raise SystemExit(f"user {args.user!r} exists - remove it first to reset")
    if args.role == "ministry":
        if not args.ministry:
            raise SystemExit("--ministry is required for a ministry user")
        names = panel_ministries()
        if args.ministry not in names:
            raise SystemExit(f"{args.ministry!r} is not a ministry in the panel. "
                             "Run `python scripts/users.py ministries` for the exact names.")
    elif args.ministry:
        raise SystemExit("a mospi user sees every ministry; do not pass --ministry")
    users.append({"user": args.user, "role": args.role,
                  "ministry": args.ministry if args.role == "ministry" else None,
                  "password": hash_password(read_password(args.password_stdin))})
    save(args.file, blob)
    print(f"added {args.user} ({args.role}{', ' + args.ministry if args.ministry else ''}) to {args.file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
