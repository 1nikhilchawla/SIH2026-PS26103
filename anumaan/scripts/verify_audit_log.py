#!/usr/bin/env python3
"""Verify a hash-chained ANUMAAN audit log (ANUMAAN_AUDIT_FILE).

    python scripts/verify_audit_log.py /var/lib/anumaan/audit.jsonl

Exit 0 when every line's hash matches its content and the line before it,
and sequence numbers run without a gap. Exit 1 at the first line that was
edited, removed or reordered, naming it. See app/audit.py for the format.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.audit import verify_file  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    n, problems = verify_file(Path(sys.argv[1]))
    if problems:
        print(f"audit log BROKEN after checking {n} line(s):")
        for p in problems:
            print("  - " + p)
        return 1
    print(f"audit log intact: {n} line(s), hash chain and sequence unbroken")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
