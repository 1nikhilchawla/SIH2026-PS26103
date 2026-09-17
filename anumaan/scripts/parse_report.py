#!/usr/bin/env python3
"""pdfplumber adapter for ANUMAAN report parsing.

Thin orchestration layer: opens a PDF with pdfplumber, walks its pages,
extracts the leading text for the summary and the project-table cells for
the detail rows, and hands both to scripts.parse_core for the actual logic.

All transform code lives in parse_core.py so that unit tests can run with
only stdlib + bs4 (P1 acceptance). This module imports pdfplumber + yaml at
the top -- importing this file without those installed will fail loudly.

Usage:
    python scripts/parse_report.py --file data/raw/<one>.pdf
    python scripts/parse_report.py --all
    python scripts/parse_report.py --help

Acceptance (P3):
    * One report reconciles detail rows vs its own summary totals.
    * `make parse` runs on every downloaded PDF; <2% of rows unparsed,
      every failure logged with a reason.
    * Hard fail (exit non-zero) when >2% of reports fail to parse.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import pdfplumber
    import yaml
except ImportError:  # pragma: no cover - intentional fail-fast
    sys.exit(
        "Install dependencies first: pip install -r requirements.txt\n"
        "(For Python 3.14 local dev, use requirements-py314.txt instead.)"
    )

# Run-from-anywhere bootstrap: `python scripts/parse_report.py` puts scripts/
# on sys.path, not the repo root, so `scripts.parse_core` is unimportable
# without this. Must precede the import below.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# parse_core is stdlib-only and safe to import.
from scripts.parse_core import (  # noqa: E402
    OCMS_EXPECTED_COLS,
    PAIMANA_EXPECTED_COLS,
    parse_summary,
    parse_rows,
    parse_rows_dispatch,
    reconcile,
)

ROOT = Path(__file__).resolve().parents[1]
PAGES_TO_READ_DEFAULT = 12
MAX_UNPARSED_PCT = 2.0  # P3 hard rule

# ---------------------------------------------------------------------------
# pdfplumber glue
# ---------------------------------------------------------------------------

def _extract_text(page) -> str:
    try:
        return page.extract_text() or ""
    except Exception:
        return ""


def _is_likely_project_table_page(text: str) -> bool:
    """Heuristic to find the page where the project table starts.

    Returns True if the page text contains enough of the per-era header
    vocabulary to be the start of a project detail table (and not just
    a sentence in the executive summary that happens to mention "Project").
    """
    low = text.lower()
    ocms_markers = ("date of approval", "original cost", "anticipated cost",
                    "reasons for delay")
    pai_markers = ("date of approval", "state", "physical progress",
                   "cumulative expenditure")
    return sum(1 for m in ocms_markers if m in low) >= 3 \
        or sum(1 for m in pai_markers if m in low) >= 3


def _find_table_start_pages(pdf, era: str) -> list[int]:
    """Page indices (0-based) that look like the start of the project table.

    Era-aware: a PAIMANA-era page mentions "State" + "Physical Progress",
    OCMS-era pages mention "Reasons for Delay" + "Anticipated Cost".
    """
    out: list[int] = []
    for i, page in enumerate(pdf.pages):
        text = _extract_text(page)
        if _is_likely_project_table_page(text):
            out.append(i)
            if len(out) >= 4:
                break
    return out


def _extract_cells_from_page(page) -> list[list[str]]:
    """Get a page's table rows as list-of-cell-lists.

    Tries pdfplumber.extract_tables() first (works on ruled tables). If that
    fails or returns nothing, falls back to word-bucket reconstruction.
    """
    settings = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    try:
        tables = page.extract_tables(settings) or []
        rows: list[list[str]] = []
        for t in tables:
            for r in t:
                rows.append([(c if c is not None else "").strip() for c in r])
        if rows:
            return rows
    except Exception:
        pass
    # Word-bucket fallback - crude, but works on PDFs without ruling lines.
    try:
        words = page.extract_words(use_text_flow=True, keep_blank_chars=False) or []
    except Exception:
        return []
    if not words:
        return []
    buckets: dict[int, list[tuple[float, str]]] = {}
    for w in words:
        col = round(w["x0"] / 10) * 10
        buckets.setdefault(col, []).append((w["top"], w["text"]))
    sorted_cols = sorted(buckets)
    if len(sorted_cols) < 3:
        return []
    lines: dict[float, list[tuple[int, str]]] = {}
    for col in sorted_cols:
        for top, txt in buckets[col]:
            line_key = round(top / 4) * 4
            lines.setdefault(line_key, []).append((col, txt))
    out = []
    for top in sorted(lines):
        cells = [t for _, t in sorted(lines[top])]
        if any(cells):
            out.append(cells)
    return out


def _cells_per_page(pdf, era: str):
    """Yield (page_idx, rows-on-that-page) for the project table region.

    We try to find the first page whose text matches the per-era table
    header vocabulary, then walk forward until we hit a page that matches
    no vocabulary at all (signalling the end of the table). If no candidate
    page is found, fall back to scanning the whole PDF.
    """
    starts = _find_table_start_pages(pdf, era)
    if not starts:
        for i, page in enumerate(pdf.pages):
            yield i, _extract_cells_from_page(page)
        return
    start = starts[0]
    for i in range(start, len(pdf.pages)):
        text = _extract_text(pdf.pages[i])
        yield i, _extract_cells_from_page(pdf.pages[i])
        # Stop when we leave the table region: page text no longer mentions
        # any of the per-era column names.
        low = text.lower()
        if i > start and not _is_likely_project_table_page(text):
            return


# ---------------------------------------------------------------------------
# Process one PDF
# ---------------------------------------------------------------------------

def _report_id_from_path(path: Path) -> str:
    return path.stem[:80]


def process(path: Path, cfg: dict, pages: int = PAGES_TO_READ_DEFAULT) -> dict:
    """Parse one PDF; write summary + rows JSON; return the summary dict.

    Fails closed (sets summary["reconciliation"]["ok"] = False) when:
      * no rows were parsed but the summary announced a count,
      * any cost field listed in the summary can't be reconciled,
      * the era could not be detected.
    """
    interim = ROOT_PATH / cfg["parse"]["interim_dir"]
    interim.mkdir(parents=True, exist_ok=True)
    stem = path.stem

    with pdfplumber.open(path) as pdf:
        head = "\n".join(
            _extract_text(pdf.pages[i])
            for i in range(min(pages, len(pdf.pages)))
        )
        (interim / f"{stem}.head.txt").write_text(head, encoding="utf-8")
        summary = parse_summary(head)
        summary["source_file"] = str(path.resolve().relative_to(ROOT_PATH))
        summary["pages"] = len(pdf.pages)
        cells_per_page = list(_cells_per_page(pdf, summary.get("era") or "ocms"))
        rows, quarantined = parse_rows(cells_per_page, summary.get("era") or "")
        report_id = _report_id_from_path(path)
        for r in rows:
            r["report_id"] = report_id
        for q in quarantined:
            q["report_id"] = report_id
        summary["reconciliation"] = reconcile(rows, quarantined, summary, cfg)
        summary["parsed_rows"] = len(rows)
        summary["quarantined_rows"] = len(quarantined)

    out = interim / f"{stem}.summary.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    # Only persist rows if reconciliation succeeded - the brief's hard rule.
    if summary["reconciliation"]["ok"]:
        rows_path = interim / f"{stem}.rows.json"
        rows_path.write_text(
            json.dumps({"report_id": report_id,
                        "era": summary.get("era"),
                        "rows": rows, "quarantined": quarantined},
                       indent=2),
            encoding="utf-8",
        )

    status = "OK" if summary["reconciliation"]["ok"] else "FAIL"
    print(f"[{status}] {path.name}: era={summary.get('era')} "
          f"projects={summary.get('projects_on_monitor')} "
          f"parsed={len(rows)} quarantined={len(quarantined)} "
          f"reconcile_ok={summary['reconciliation']['ok']}")
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

ROOT_PATH = ROOT  # alias so process() can reference it without shadowing import


def _load_cfg() -> dict:
    for name in ("settings.yaml", "settings.example.yaml"):
        p = ROOT / "config" / name
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8"))
    sys.exit("No config found. Copy config/settings.example.yaml to "
             "config/settings.yaml first.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--file", type=Path, default=None,
                    help="parse a single PDF")
    ap.add_argument("--all", action="store_true",
                    help="parse every PDF under data/raw/")
    ap.add_argument("--pages", type=int, default=PAGES_TO_READ_DEFAULT,
                    help=f"how many leading pages to read (default {PAGES_TO_READ_DEFAULT})")
    args = ap.parse_args()

    cfg = _load_cfg()

    if args.file:
        summary = process(args.file, cfg, args.pages)
        return 0 if summary["reconciliation"]["ok"] else 1

    if args.all:
        pdfs = sorted((ROOT / cfg["harvest"]["raw_dir"]).rglob("*.pdf"))
        if not pdfs:
            sys.exit("No PDFs yet. Run: make harvest")
        failed = 0
        for pdf_path in pdfs:
            try:
                summary = process(pdf_path, cfg, args.pages)
            except Exception as exc:
                print(f"{pdf_path.name}: FAILED - {exc}", file=sys.stderr)
                failed += 1
                continue
            if not summary["reconciliation"]["ok"]:
                failed += 1
        pct = failed / max(len(pdfs), 1) * 100
        print(f"\n{len(pdfs) - failed}/{len(pdfs)} reports reconciled ({pct:.1f}% failed)")
        if pct > MAX_UNPARSED_PCT:
            print(f"FAIL: >{MAX_UNPARSED_PCT}% of reports failed to reconcile",
                  file=sys.stderr)
            return 2
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())