#!/usr/bin/env python3
"""Tamper-evident audit log.

Every audit event is one JSON line. When ANUMAAN_AUDIT_FILE is set the line is
also appended to that file as a hash chain:

    {"seq": 41, "ts": "...", ...event..., "prev": "<hash of line 40>",
     "hash": sha256(prev + canonical JSON of this line without "hash")}

Editing, deleting or reordering any line breaks every hash after it, and
`python scripts/verify_audit_log.py <file>` says exactly where. It does not
stop someone with write access from truncating the tail - ship the file to a
log drain (CERT-In: 180 days, kept in India) so a copy exists outside the
server.

Never logged: passwords, tokens, Authorization headers, query strings, and
remark text before redaction.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import threading
from pathlib import Path

GENESIS = "0" * 64


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str,
                      ensure_ascii=False).encode("utf-8")


def line_hash(prev: str, body: dict) -> str:
    return hashlib.sha256(prev.encode("ascii") + canonical(body)).hexdigest()


class AuditLog:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._prev = GENESIS
        self._seq = 0
        if self.path and self.path.exists() and self.path.stat().st_size:
            last = self._last_line(self.path)
            rec = json.loads(last)
            body = {k: v for k, v in rec.items() if k != "hash"}
            if line_hash(rec["prev"], body) != rec["hash"]:
                raise RuntimeError(f"{self.path}: last line fails its own hash - the log has "
                                   "been edited; run scripts/verify_audit_log.py")
            self._prev, self._seq = rec["hash"], int(rec["seq"])

    @staticmethod
    def _last_line(path: Path) -> str:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            end = fh.tell()
            size = min(end, 64 * 1024)
            fh.seek(end - size)
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        return lines[-1].decode("utf-8")

    def write(self, event: dict) -> dict:
        with self._lock:
            body = {"seq": self._seq + 1,
                    "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds"),
                    "kind": "audit", **event, "prev": self._prev}
            h = line_hash(self._prev, body)
            rec = {**body, "hash": h}
            line = json.dumps(rec, separators=(",", ":"), default=str, ensure_ascii=False)
            print(line, flush=True)
            if self.path:
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            self._prev, self._seq = h, body["seq"]
            return rec


def verify_file(path: Path) -> tuple[int, list[str]]:
    """Return (lines_checked, problems). Problems name the first broken line."""
    prev = GENESIS
    expected_seq = None
    problems: list[str] = []
    n = 0
    with Path(path).open(encoding="utf-8") as fh:
        for i, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            n += 1
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                problems.append(f"line {i}: not JSON")
                break
            body = {k: v for k, v in rec.items() if k != "hash"}
            if expected_seq is None:
                expected_seq = int(rec.get("seq", 1))
                prev = rec.get("prev", GENESIS)        # a rotated file starts mid-chain
            if rec.get("prev") != prev:
                problems.append(f"line {i}: prev does not match the hash of the line before")
                break
            if line_hash(prev, body) != rec.get("hash"):
                problems.append(f"line {i}: content does not match its hash (edited)")
                break
            if int(rec.get("seq", -1)) != expected_seq:
                problems.append(f"line {i}: sequence {rec.get('seq')} where {expected_seq} expected "
                                "(a line was removed or reordered)")
                break
            prev, expected_seq = rec["hash"], expected_seq + 1
    return n, problems
