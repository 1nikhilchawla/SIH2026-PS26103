"""Re-tag the era column in data/raw/manifest.csv based on FY.

Rule: FY >= 2025-26 -> paimana, else -> ocms. PAIMANA launched in
September 2025, which falls inside FY 2025-26, so the FY boundary is the
correct discriminator.

Also recomputes SHA-256 for every file as a round-trip check.
"""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path

RAW = Path("data/raw")
manifest_path = RAW / "manifest.csv"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fy_to_era(fy: str) -> str:
    """PAIMANA era starts at FY 2025-26."""
    try:
        # "2025-26" -> 2025
        yr = int(fy.split("-")[0])
        return "paimana" if yr >= 2025 else "ocms"
    except (ValueError, IndexError):
        return "ocms"


def main() -> None:
    with open(manifest_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    print(f"loaded {len(rows)} manifest rows")

    fixed = 0
    sha_mismatch = 0
    missing = 0
    for row in rows:
        new_era = fy_to_era(row.get("fy", ""))
        if row.get("era") != new_era:
            row["era"] = new_era
            fixed += 1
        # Recompute sha256 for round-trip integrity.
        pdf_path = RAW / row["filename"]
        if not pdf_path.exists():
            print(f"  MISSING on disk: {row['filename']}")
            missing += 1
            continue
        actual = sha256_of(pdf_path)
        if row.get("sha256") and actual != row["sha256"]:
            print(f"  SHA mismatch: {row['filename']} "
                  f"manifest={row['sha256'][:12]} actual={actual[:12]}")
            sha_mismatch += 1
        row["sha256"] = actual
        row["bytes"] = str(pdf_path.stat().st_size)

    cols = ["filename", "report_id", "fy", "era", "path", "url",
            "sha256", "bytes", "fetched_at", "status"]
    with open(manifest_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"re-tagged {fixed} rows")
    print(f"sha mismatches: {sha_mismatch}")
    print(f"missing files: {missing}")
    print(f"final manifest: {manifest_path}")

    # Summary by era
    by_era: dict = {}
    for row in rows:
        by_era[row["era"]] = by_era.get(row["era"], 0) + 1
    print("by era:")
    for era, n in sorted(by_era.items()):
        print(f"  {era}: {n}")


if __name__ == "__main__":
    main()