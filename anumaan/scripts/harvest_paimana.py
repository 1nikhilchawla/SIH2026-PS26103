#!/usr/bin/env python3
"""ANUMAAN harvester for MoSPI PAIMANA / OCMS Flash Reports.

Discovers every Flash Report by calling the report-listing endpoint
discovered in D1 (Route A in ADR-0002), then downloads each PDF into
data/raw/ with polite pacing (2s delay between requests), resumability
(.part files; rename on success), SHA-256 verification, and a Content-Length
+ %%EOF magic check.

Two eras are detected from the report path:
    flash/YYYY-YY/FR_<Month>_<Year>.pdf       -- PAIMANA (Sep 2025 onward)
    flash/YYYY-YY/<Month>_Part-<X>.pdf        -- older OCMS layout

Both eras are downloaded into the same data/raw/ tree.

Usage:
    python scripts/harvest_paimana.py --list-only
    python scripts/harvest_paimana.py --since-fy 2019-20
    python scripts/harvest_paimana.py --fy 2024-25 --fy 2025-26
    python scripts/harvest_paimana.py --max 5 --dry-run
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
UA = "ANUMAAN-SIH26103/0.1 (research; contact: nik@anumaan.example.in)"
BASE = "https://paimana-proj.mospi.gov.in"
DELAY = 2.0

LINK_RE = re.compile(
    r"ViewPdf\?id=(\d+)(?:&amp;)?&path=([^\"'<>]+)",
    re.IGNORECASE,
)

# Flash Report years we want to harvest. Adjust here.
DEFAULT_SINCE_FY = "2019-20"


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

@dataclass
class Report:
    """One row of the report listing. Public because the offline test
    (tests/test_harvest_links.py) asserts against these fields."""
    fy: str
    month: str
    report_id: str
    path: str
    filename: str

    @property
    def start_year(self) -> int:
        try:
            return int(self.fy.split("-")[0])
        except (ValueError, IndexError):
            return 0

    @property
    def full_url(self) -> str:
        return f"{BASE}/ReportPage/ViewPdf?id={self.report_id}&path={self.path}"


def parse_listing(html: str) -> list[Report]:
    """Pure function: listing HTML -> Report rows. No network.

    Works on both shapes we have seen: the old server-rendered table and the
    table returned inside the JSON payload of /ReportPage/Report. FY and month
    come from the row's own cells when present, so they are read, not guessed.
    """
    out: list[Report] = []
    seen: set[str] = set()
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I) or [html]
    for row in rows:
        m = LINK_RE.search(row.replace("&amp;", "&"))
        if not m:
            continue
        rid, path = m.group(1), m.group(2)
        if rid in seen:
            continue
        seen.add(rid)
        clean_path = unquote(path.replace("&amp;", "&")).replace("\\", "/")
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
        fy = cells[1] if len(cells) > 1 else "unknown"
        month = cells[2] if len(cells) > 2 else "unknown"
        filename = re.split(r"[\\/]", clean_path)[-1] or f"report_{rid}.pdf"
        out.append(Report(fy=fy, month=month, report_id=rid,
                          path=clean_path, filename=filename))
    return out


def list_year(fyear: str, session: requests.Session) -> list[dict]:
    """GET /ReportPage/Report with reportType=F, month=0, quater=0 for the
    given FY. Returns a list of {report_id, path, full_url} dicts."""
    url = f"{BASE}/ReportPage/Report"
    params = {"fyear": fyear, "month": "0", "quater": "0", "reportType": "F"}
    r = session.get(url, params=params, timeout=180,
                   headers={"User-Agent": UA,
                            "Accept": "application/json,*/*",
                            "X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    payload = r.json()
    html = payload.get("html", "") if isinstance(payload, dict) else ""
    return [{"report_id": rep.report_id, "path": rep.path,
             "full_url": rep.full_url, "fy": rep.fy, "month": rep.month,
             "filename": rep.filename}
            for rep in parse_listing(html)]


def list_current_years(session: requests.Session) -> list[str]:
    """GET /ReportPage/GetFinancialYearList and /GetArchiveFinancialYearList,
    return the union of FY strings."""
    cur = session.get(f"{BASE}/ReportPage/GetFinancialYearList", timeout=180,
                      headers={"User-Agent": UA}).json()
    arch = session.get(f"{BASE}/ReportPage/GetArchiveFinancialYearList",
                        timeout=180,
                        headers={"User-Agent": UA}).json()
    return list(dict.fromkeys(list(cur) + list(arch)))


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def looks_like_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
            if head != b"%PDF":
                return False
            fh.seek(max(0, path.stat().st_size - 1024))
            tail = fh.read()
            return b"%%EOF" in tail
    except OSError:
        return False


def download_one(rec: dict, dest_dir: Path, session: requests.Session) -> dict:
    """Download one PDF with .part staging, then atomically rename.

    Returns {report_id, path, full_url, status, sha256, bytes, error?}.
    Status values: ok, already_have, downloaded, invalid_pdf, http_error.
    """
    out_path = dest_dir / Path(rec["path"]).name
    if out_path.exists() and looks_like_pdf(out_path):
        return {"report_id": rec["report_id"], "path": rec["path"],
                "filename": out_path.name, "url": rec["full_url"],
                "status": "already_have",
                "sha256": sha256_of(out_path),
                "bytes": out_path.stat().st_size}
    part_path = out_path.with_suffix(out_path.suffix + ".part")
    r = session.get(rec["full_url"], timeout=180, stream=True,
                    headers={"User-Agent": UA})
    r.raise_for_status()
    cl = r.headers.get("Content-Length")
    bytes_written = 0
    try:
        with open(part_path, "wb") as fh:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)
                    bytes_written += len(chunk)
    except requests.RequestException as exc:
        if part_path.exists():
            part_path.unlink()
        return {"report_id": rec["report_id"], "path": rec["path"],
                "filename": out_path.name, "url": rec["full_url"],
                "status": "http_error",
                "error": repr(exc), "bytes": bytes_written}

    if not looks_like_pdf(part_path):
        part_path.unlink()
        return {"report_id": rec["report_id"], "path": rec["path"],
                "filename": out_path.name, "url": rec["full_url"],
                "status": "invalid_pdf",
                "error": "no %PDF header or no %%EOF marker",
                "content_length": cl, "bytes": bytes_written}

    part_path.replace(out_path)
    return {"report_id": rec["report_id"], "path": rec["path"],
            "filename": out_path.name, "url": rec["full_url"],
            "status": "downloaded",
            "sha256": sha256_of(out_path),
            "bytes": out_path.stat().st_size,
            "content_length": cl}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> dict:
    """Read existing manifest.csv into {filename: row_dict} for resumability."""
    if not manifest_path.exists():
        return {}
    out = {}
    with open(manifest_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["filename"]] = row
    return out


def append_manifest(manifest_path: Path, row: dict) -> None:
    is_new = not manifest_path.exists()
    with open(manifest_path, "a", newline="", encoding="utf-8") as fh:
        cols = ["filename", "report_id", "fy", "era", "path",
                "url", "sha256", "bytes", "fetched_at", "status"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        if is_new:
            w.writeheader()
        w.writerow(row)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list-only", action="store_true",
                   help="only list, do not download")
    p.add_argument("--since-fy", default=None,
                   help="earliest FY to harvest (e.g. 2019-20)")
    p.add_argument("--fy", action="append", default=[],
                   help="specific FY to harvest (repeatable)")
    p.add_argument("--max", type=int, default=0,
                   help="cap the number of PDFs downloaded (0 = no cap)")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    if args.list_only:
        # Discover FYs, list what each would yield, do not download.
        print("discovering available fiscal years ...")
        all_fys = list_current_years(session)
        print(f"  portal returned {len(all_fys)} FYs")
        fys = args.fy or [fy for fy in all_fys if fy >= (args.since_fy or DEFAULT_SINCE_FY)]
        for fy in fys:
            recs = list_year(fy, session)
            print(f"  FY {fy}: {len(recs)} PDF link(s)")
            for r in recs[:3]:
                print(f"    {r['full_url']}")
            if len(recs) > 3:
                print(f"    ... and {len(recs)-3} more")
            time.sleep(DELAY)
        return 0

    print("discovering available fiscal years ...")
    all_fys = list_current_years(session)
    print(f"  portal returned {len(all_fys)} FYs: {all_fys[:6]}...")

    fys_to_process: list[str] = []
    if args.fy:
        fys_to_process = list(dict.fromkeys(args.fy))
    elif args.since_fy:
        fys_to_process = [fy for fy in all_fys if fy >= args.since_fy]
    else:
        fys_to_process = [fy for fy in all_fys if fy >= DEFAULT_SINCE_FY]

    if not fys_to_process:
        print("no fiscal years matched -- exiting")
        return 1

    print(f"will process {len(fys_to_process)} FYs: {fys_to_process}")

    RAW.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / "manifest.csv"
    existing = load_manifest(manifest_path)
    if existing:
        print(f"manifest has {len(existing)} rows; resumable")

    summary = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "fys": fys_to_process,
               "per_fy": {},
               "totals": {}}

    total_downloaded = 0
    total_failed = 0
    total_existing = 0

    for fy in fys_to_process:
        print(f"\n--- listing FY {fy} ---")
        recs = list_year(fy, session)
        print(f"  {len(recs)} PDF links")
        per_fy = {"listed": len(recs), "downloaded": 0,
                  "already_have": 0, "failed": 0}
        for i, rec in enumerate(recs, 1):
            if args.max and total_downloaded >= args.max:
                print(f"  hit --max {args.max}, stopping")
                break
            if args.dry_run:
                print(f"  [{i:>2d}/{len(recs)}] DRY: {rec['full_url']}")
                continue

            print(f"  [{i:>2d}/{len(recs)}] {rec['path']}", end=" ", flush=True)
            try:
                result = download_one(rec, RAW, session)
            except requests.RequestException as exc:
                result = {"status": "http_error", "error": repr(exc)}
            if result["status"] == "already_have":
                print(f"already have ({result['bytes']} bytes, sha256={result['sha256'][:12]}...)")
                per_fy["already_have"] += 1
                total_existing += 1
            elif result["status"] == "downloaded":
                print(f"OK ({result['bytes']} bytes, sha256={result['sha256'][:12]}...)")
                # determine era from the path. PAIMANA switched to a
                # new filename convention in Sep 2025. The two patterns
                # seen in the wild are:
                #   paimana: FlashReport_<Month>_<Year>.pdf  or  FR<Month><YYYY>.pdf
                #   ocms:    <Month>.pdf  or  <Month>_Part-<I|II|1|2>.pdf
                p = rec["path"]
                if (re.search(r"FlashReport_\w+_\d{4}\.pdf$", p)
                        or re.search(r"FR\w+\d{4}\.pdf$", p)):
                    era = "paimana"
                else:
                    era = "ocms"
                append_manifest(manifest_path, {
                    "filename": result["filename"],
                    "report_id": rec["report_id"],
                    "fy": fy, "era": era,
                    "path": rec["path"], "url": rec["full_url"],
                    "sha256": result["sha256"],
                    "bytes": result["bytes"],
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "status": "downloaded",
                })
                per_fy["downloaded"] += 1
                total_downloaded += 1
            else:
                print(f"FAILED: {result.get('error', result['status'])}")
                per_fy["failed"] += 1
                total_failed += 1
            time.sleep(DELAY)
        summary["per_fy"][fy] = per_fy

    summary["totals"] = {"downloaded": total_downloaded,
                          "already_have": total_existing,
                          "failed": total_failed,
                          "pdfs_on_disk": sum(
                              1 for p in RAW.rglob("*.pdf")
                          )}
    summary["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    summary_path = RAW / "harvest_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2),
                              encoding="utf-8")
    print(f"\nSummary written: {summary_path}")
    print(f"PDFs on disk: {summary['totals']['pdfs_on_disk']} | "
          f"newly downloaded: {total_downloaded} | "
          f"already had: {total_existing} | failed: {total_failed}")
    return 0 if total_failed == 0 else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)