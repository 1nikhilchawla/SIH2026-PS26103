#!/usr/bin/env python3
"""Verify the raw PDF corpus against data/raw/manifest.csv.

Why this exists: results/paimana/manifest_verification.json recorded
`generated_by: "(inline) manifest SHA-256 verification"`. An artefact that no
script can regenerate is not evidence - a reviewer cannot re-run it, and the
live app reports its `sha_ok` count on the benchmark screen. This turns that
one-off check into the first step of the pipeline.

Fail-closed: a SHA mismatch, a missing file or a file that does not start with
the PDF magic bytes is an error and exits non-zero. The pipeline stops rather
than parsing a corpus that is not the one that was downloaded.

Note on `era`: the manifest's era column is assigned by a filename/FY
heuristic. It is NOT verified here and must not be trusted - parse_paimana.py
detects the era from the document's own content.

Usage:
    python scripts/verify_corpus.py
    python scripts/verify_corpus.py --quiet
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = RAW / "manifest.csv"
OUT = ROOT / "results" / "paimana" / "manifest_verification.json"
PDF_MAGIC = b"%PDF-"
CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true",
                    help="only print the summary and any failures")
    args = ap.parse_args()

    if not MANIFEST.exists():
        raise SystemExit(f"{MANIFEST} missing. Run: python scripts/harvest_paimana.py")

    rows = list(csv.DictReader(MANIFEST.open(encoding="utf-8")))
    if not rows:
        raise SystemExit("manifest.csv has no rows - nothing to verify")

    sha_ok = mismatches = missing = header_ok = 0
    failures: list[dict] = []
    for r in rows:
        name = r["filename"]
        path = RAW / name
        if not path.exists():
            missing += 1
            failures.append({"filename": name, "problem": "missing on disk"})
            continue
        with path.open("rb") as fh:
            if fh.read(len(PDF_MAGIC)) == PDF_MAGIC:
                header_ok += 1
            else:
                failures.append({"filename": name,
                                 "problem": "does not start with %PDF-"})
        expected = (r.get("sha256") or "").strip().lower()
        actual = sha256_of(path)
        if not expected:
            failures.append({"filename": name, "problem": "no sha256 in manifest"})
        elif actual == expected:
            sha_ok += 1
            if not args.quiet:
                print(f"  ok  {name[:48]:50s} {actual[:16]}...")
        else:
            mismatches += 1
            failures.append({"filename": name, "problem": "sha256 mismatch",
                             "expected": expected, "actual": actual})

    on_disk = sorted(p.name for p in RAW.glob("*.pdf"))
    listed = {r["filename"] for r in rows}
    unlisted = [n for n in on_disk if n not in listed]

    payload = {
        "data_source": "paimana",
        "manifest_file": "data/raw/manifest.csv",
        "manifest_rows": len(rows),
        "sha_ok": sha_ok,
        "sha_mismatch": mismatches,
        "missing_files": missing,
        "pdfs_on_disk": len(on_disk),
        "pdf_header_ok": header_ok,
        "unlisted_pdfs_on_disk": unlisted,
        "fy_counts": dict(sorted(Counter(r.get("fy", "?") for r in rows).items())),
        "era_column_counts": dict(sorted(Counter(r.get("era", "?") for r in rows).items())),
        "era_column_note": ("manifest 'era' is assigned by a filename/FY heuristic "
                            "and is NOT verified against PDF content; "
                            "parse_paimana.py detects era from the document itself"),
        "failures": failures,
        "ok": bool(mismatches == 0 and missing == 0 and not failures),
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": "python scripts/verify_corpus.py",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    print(f"\nmanifest rows : {len(rows)}")
    print(f"sha-256 ok    : {sha_ok}")
    print(f"sha mismatch  : {mismatches}")
    print(f"missing files : {missing}")
    print(f"pdf header ok : {header_ok}")
    if unlisted:
        print(f"unlisted PDFs on disk (not verified): {', '.join(unlisted)}")
    print(f"wrote {OUT}")

    if failures:
        print("\nFAILURES - the corpus on disk is not the corpus that was downloaded:")
        for f in failures:
            print(f"  {f['filename']}: {f['problem']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
