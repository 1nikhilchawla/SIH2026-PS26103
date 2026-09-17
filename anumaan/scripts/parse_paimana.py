#!/usr/bin/env python3
"""PAIMANA-era Flash Report parser (Sept 2025 onward).

Why a separate parser: the generic parser in parse_core.py expects a 10-column
project table. The real PAIMANA "Table 6: All Ongoing Projects" has EIGHT
columns, and three of them pack two values into one cell:

    col0  Sl.No
    col1  Project Name (Agency [CODE]) (project_code) (legacy) (pmgid)
    col2  State
    col3  Date of Approval   "MM/YYYY\\n(MM/YYYY)"  -> approval (start date)
    col4  Orignal/Target DoC "MM/YYYY\\n(MM/YYYY)"  -> original DoC (revised DoC)
    col5  Orignal/Revised Cost "265.91\\n(265.91)"  -> original (revised), Rs crore
    col6  Cumulative Expenditure, Rs crore
    col7  Physical Progress (%)

Ministry and sector arrive as group header rows: only col1 filled, rest None.
They are carried down onto the project rows that follow.

Era detection is by CONTENT, not filename: the overview page carries
    "<projects> | <ministries> Rs <original> Rs <revised> Rs <exp> (<pct>% of Revised Cost)"

Reconciliation FAILS CLOSED. A report is only "ok" when rows were actually
parsed AND the checks ran AND they passed. Zero rows can never report ok.

Usage:
    python scripts/parse_paimana.py --file data/raw/FlashReport_July_2026.pdf
    python scripts/parse_paimana.py --all
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import re
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:  # pragma: no cover - fail loudly, never silently
    sys.exit("pdfplumber missing: pip install -r requirements-py314.txt")

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim" / "paimana"
RESULTS = ROOT / "results" / "paimana"

EXPECTED_COLS = 8
COUNT_TOLERANCE = 0          # row count must match the overview exactly
COST_TOLERANCE_PCT = 1.0     # sum(original cost) vs overview, percent

SENTINELS = {"", "-", "--", "n/a", "na", "nil", "not available"}

OVERVIEW_RE = re.compile(
    r"(?P<projects>\d[\d,]*)\s*\|\s*(?P<ministries>\d+)\s*"
    r"[₹Rs.\s]*(?P<original>[\d,]+)\s*"
    r"[₹Rs.\s]*(?P<revised>[\d,]+)\s*"
    r"[₹Rs.\s]*(?P<expenditure>[\d,]+)\s*"
    r"\(\s*(?P<pct>[\d.]+)\s*%\s*of\s*Revised\s*Cost\s*\)",
    re.I,
)
SECTION_RE = re.compile(r"All\s+Ongoing\s+Projects", re.I)
MONTH_NAMES = ("JANUARY FEBRUARY MARCH APRIL MAY JUNE JULY AUGUST "
               "SEPTEMBER OCTOBER NOVEMBER DECEMBER").split()
REPORT_MONTH_RE = re.compile(r"\b(" + "|".join(MONTH_NAMES) + r")\s+(20\d\d)\b", re.I)
HEADER_RE = re.compile(r"Sl\.?\s*No", re.I)
MONTH_RE = re.compile(r"^(0?[1-9]|1[0-2])/(\d{4})$")


def _clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def _is_sentinel(s) -> bool:
    return _clean(s).lower() in SENTINELS


def to_float(s):
    """Rs crore as float. Returns (value, unparsed_flag)."""
    t = _clean(s).replace(",", "")
    if not t or _is_sentinel(t):
        return None, False
    t = t.replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        return float(t), False
    except ValueError:
        return None, True          # non-blank and unparseable: must be counted


def to_month(s):
    """MM/YYYY -> YYYY-MM-01. Returns (iso, unparsed_flag)."""
    t = _clean(s)
    if not t or _is_sentinel(t):
        return None, False
    m = MONTH_RE.match(t)
    if not m:
        return None, True
    mm, yyyy = int(m.group(1)), int(m.group(2))
    return f"{yyyy:04d}-{mm:02d}-01", False


def split_pair(cell):
    """'265.91\\n(265.91)' -> ('265.91', '265.91'). Second may be absent."""
    t = _clean(cell)
    if not t:
        return "", ""
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", t)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return t, ""


def parse_project_cell(cell) -> dict:
    """Pull name / agency / codes out of the bracketed project cell.

    Shape: "<name lines> (Agency [CODE]) (project_code) (legacy) (pmgid)"
    Trailing groups are '-' when the report has no such code. Groups are
    classified by CONTENT (digits vs agency text), never by position, so a
    missing trailing group cannot shift a value into the wrong field.
    """
    raw = (cell or "").replace("\n", " ")
    groups = re.findall(r"\(([^()]*)\)", raw)
    name = _clean(re.split(r"\(", raw)[0]) if groups else _clean(raw)

    agency = project_code = legacy = pmgid = None
    numeric = []
    for g in groups:
        g = _clean(g)
        if not g or _is_sentinel(g):
            continue
        if re.fullmatch(r"\d{4,}", g):
            numeric.append(g)
        elif re.search(r"[A-Za-z]", g) and agency is None:
            agency = g
    if numeric:
        project_code = numeric[0]
        if len(numeric) > 1:
            legacy = numeric[1]
        if len(numeric) > 2:
            pmgid = numeric[2]
    # agency short code inside square brackets: "Airport Authority of India [AAI]"
    agency_code = None
    if agency:
        m = re.search(r"\[([^\]]+)\]", agency)
        if m:
            agency_code = m.group(1).strip()
            agency = _clean(agency[: m.start()])
    return {"project_name": name or None, "agency": agency,
            "agency_code": agency_code, "project_code": project_code,
            "legacy_ocms_code": legacy, "pmgid": pmgid}


def parse_summary(pdf, pages: int = 6) -> dict:
    text = "\n".join((pdf.pages[i].extract_text() or "")
                     for i in range(min(pages, len(pdf.pages))))
    flat = re.sub(r"\s+", " ", text)
    m = OVERVIEW_RE.search(flat)
    if not m:
        return {"era": None}
    g = m.groupdict()
    # Which month this report IS, read from the document's own cover/header
    # ("... JULY 2026 ...") rather than guessed from the filename.
    rm = REPORT_MONTH_RE.search(flat)
    report_month = None
    if rm:
        mm = MONTH_NAMES.index(rm.group(1).upper()) + 1
        report_month = f"{int(rm.group(2)):04d}-{mm:02d}-01"
    return {
        "era": "paimana",
        "report_month": report_month,
        "projects_on_monitor": int(g["projects"].replace(",", "")),
        "ministries": int(g["ministries"]),
        "original_cost_cr": float(g["original"].replace(",", "")),
        "revised_cost_cr": float(g["revised"].replace(",", "")),
        "expenditure_cr": float(g["expenditure"].replace(",", "")),
        "expenditure_pct_of_revised": float(g["pct"]),
    }


def _looks_like_group_row(cells) -> bool:
    """Ministry / sector header: only col1 carries text."""
    if not cells or len(cells) < 2:
        return False
    first_blank = not _clean(cells[0])
    rest_blank = all(not _clean(c) for c in cells[2:])
    return first_blank and bool(_clean(cells[1])) and rest_blank


def _reconstruct_table_from_words(page) -> list[list[str]]:
    """Per-page fallback: when pdfplumber's line-based extractor returns 0
    rows for a page that has real text (ruling lines degrade on some pages),
    reconstruct table rows by clustering words into lines (by y) and then
    into columns (by x).

    Returns a list of cell-lists, one per row. Empty rows are dropped.
    """
    try:
        words = page.extract_words(use_text_flow=True,
                                    keep_blank_chars=False) or []
    except Exception:
        return []
    if len(words) < 20:
        return []
    # Group words by approximate top-y position (line).
    lines: dict = {}
    for w in words:
        y_key = round(w["top"] / 4) * 4
        lines.setdefault(y_key, []).append(w)
    rows: list[list[str]] = []
    for y_key in sorted(lines):
        ws = sorted(lines[y_key], key=lambda w: w["x0"])
        if not ws:
            continue
        cells: list[list[str]] = [[ws[0]["text"]]]
        last_x1 = ws[0]["x1"]
        for w in ws[1:]:
            if w["x0"] - last_x1 >= 8:
                cells.append([w["text"]])
            else:
                cells[-1].append(w["text"])
            last_x1 = max(last_x1, w["x1"])
        row_cells = [" ".join(c).strip() for c in cells]
        if any(row_cells):
            rows.append(row_cells)
    return rows


def parse_rows(pdf) -> tuple[list[dict], list[dict], dict]:
    """Walk every page and extract project rows.

    Section detection
        PAIMANA reports mention "All Ongoing Projects" once on the executive
        summary page (page 1) and again as the actual project-table header
        on a much later page (page 40+). The summary mention is harmless,
        but the original parser would enter the section on page 1, then
        exit on "Table 1: Ministry-wise" around page 21, and never re-enter
        because the only trigger is the literal "All Ongoing Projects" text
        again. Net effect: zero rows parsed.

        Fix: only enter the section when the page has BOTH the section
        header AND extracted table rows (which the summary page lacks).
        Re-entering after a section break also requires real table content,
        not just a header mention.
    """
    rows: list[dict] = []
    quarantined: list[dict] = []
    stats = {"pages_in_section": 0, "group_rows": 0, "header_rows": 0,
             "unparsed_cost_cells": 0, "unparsed_date_cells": 0}
    ministry = sector = None
    in_section = False
    lines_tables = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}

    for idx, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        # Probe what extract_tables would give us on this page. The summary
        # page has 0-2 rows; the project-table pages have >= 5.
        probe_tables = page.extract_tables(lines_tables) or []
        probe_n_rows = sum(len(t) for t in probe_tables)
        has_section_header = bool(SECTION_RE.search(text))
        has_other_table = bool(re.search(r"Table\s+\d+\s*:", text))

        if not in_section:
            # Only enter the section when we actually see the project table.
            # Mere mention of "All Ongoing Projects" in the summary is not
            # enough - the page must also produce real table rows.
            if has_section_header and probe_n_rows >= 5:
                in_section = True
        else:
            # We're in the section. Only leave when a NEW table number
            # appears AND the page is not also the project-table header.
            if has_other_table and probe_n_rows < 5:
                in_section = False

        if not in_section:
            continue
        tables = probe_tables
        # Per-page fallback: when the line-based extractor returns 0 rows
        # but the page has real text (ruling lines degrade on some pages),
        # reconstruct rows from word x/y positions.
        if (not tables or
                sum(len(t) for t in tables) == 0) and text.strip():
            fb = _reconstruct_table_from_words(page)
            if fb:
                tables = [fb]
        counted_page = False
        for table in tables:
            for r_i, raw_cells in enumerate(table):
                cells = [c if c is not None else "" for c in raw_cells]
                # Ministry / sector group rows carry their label in ONE cell
                # and leave the other seven blank. They must be read BEFORE
                # the blank-cell trim below, which would otherwise collapse
                # them to a single cell and send them to quarantine as
                # "wrong_column_count" - which is exactly what happened
                # until this was fixed, leaving ministry null on every row.
                filled = [_clean(c) for c in cells if _clean(c)]
                if len(filled) == 1 and len(cells) >= EXPECTED_COLS:
                    label = filled[0]
                    if (HEADER_RE.search(label)
                            or label.startswith(("All Ongoing Projects",
                                                 "Project Assessment", "Total "))):
                        stats["header_rows"] += 1
                        continue
                    if re.match(r"^(Ministry|Department)\b", label, re.I):
                        ministry, sector = label, None
                    else:
                        sector = label
                    stats["group_rows"] += 1
                    continue
                # Trim leading and trailing empty cells. Some pages have a
                # blank gutter on either side; without this trim the
                # column-count check rejects valid 8-column rows.
                while cells and not _clean(cells[0]):
                    cells.pop(0)
                while cells and not _clean(cells[-1]):
                    cells.pop()
                # Filter out non-project rows BEFORE the column-count check:
                #   * the running header that re-appears on every page
                #     ("All Ongoing Projects SEPTEMBER 2025 Original Cost
                #     Revised Cost Expenditure Physical Progress ...") is
                #     picked up as 2 cells by the line-based extractor.
                #   * the subtitle row
                #     ("Project Assessment, Infrastructure Monitoring and
                #     Analysis Division") is also 2 cells.
                #   * sector subtotals ("Total (26)") put the "Total (N)"
                #     label in cell 1 with cell 0 empty.
                # Skip all of these silently - they are not project rows.
                first_two = " ".join(_clean(c) for c in cells[:2])
                if (first_two.startswith("All Ongoing Projects")
                        or first_two.startswith("Project Assessment")
                        or first_two.startswith("Total ")
                        or HEADER_RE.search(_clean(cells[0]) if cells else "")):
                    stats["header_rows"] += 1
                    continue
                if len(cells) != EXPECTED_COLS:
                    if any(_clean(c) for c in cells):
                        quarantined.append({"page": idx, "row": r_i,
                                            "reason": "wrong_column_count",
                                            "got": len(cells),
                                            "raw": [_clean(c)[:40] for c in cells]})
                    continue
                if not counted_page:
                    stats["pages_in_section"] += 1
                    counted_page = True
                if _looks_like_group_row(cells):
                    label = _clean(cells[1])
                    if re.match(r"^Ministry\b|^Department\b", label, re.I):
                        ministry, sector = label, None
                    else:
                        sector = label
                    stats["group_rows"] += 1
                    continue
                sl = _clean(cells[0])
                if not re.fullmatch(r"\d+", sl):
                    quarantined.append({"page": idx, "row": r_i,
                                        "reason": "no_serial_number",
                                        "raw": [_clean(c)[:40] for c in cells]})
                    continue

                ids = parse_project_cell(cells[1])
                appr_raw, start_raw = split_pair(cells[3])
                odoc_raw, tdoc_raw = split_pair(cells[4])
                ocost_raw, rcost_raw = split_pair(cells[5])

                approval, f1 = to_month(appr_raw)
                start, f2 = to_month(start_raw)
                original_doc, f3 = to_month(odoc_raw)
                target_doc, f4 = to_month(tdoc_raw)
                ocost, f5 = to_float(ocost_raw)
                rcost, f6 = to_float(rcost_raw)
                exp, f7 = to_float(cells[6])
                prog, f8 = to_float(cells[7])
                stats["unparsed_date_cells"] += sum((f1, f2, f3, f4))
                stats["unparsed_cost_cells"] += sum((f5, f6, f7, f8))

                rows.append({
                    "sl_no": int(sl), "page": idx,
                    **ids,
                    "ministry": ministry, "sector": sector,
                    "state": _clean(cells[2]) or None,
                    "approval_month": approval, "start_month": start,
                    "original_doc": original_doc, "target_doc": target_doc,
                    "original_cost_cr": ocost, "revised_cost_cr": rcost,
                    "cumulative_expenditure_cr": exp,
                    "physical_progress_pct": prog,
                })
    return rows, quarantined, stats


def reconcile(rows, summary, stats) -> dict:
    """Fail closed: no rows, or no checks, is NOT a pass."""
    checks = []
    if not rows:
        return {"ok": False, "checks": [],
                "reason": "zero rows parsed - cannot pass by default"}
    if summary.get("era") != "paimana":
        return {"ok": False, "checks": [],
                "reason": "overview block not found - nothing to reconcile against"}

    expected = summary.get("projects_on_monitor")
    diff = abs(len(rows) - expected)
    checks.append({"check": "row_count", "expected": expected,
                   "parsed": len(rows), "diff": diff,
                   "ok": diff <= COUNT_TOLERANCE})

    parsed_cost = sum(r["original_cost_cr"] for r in rows
                      if r["original_cost_cr"] is not None)
    reported = summary.get("original_cost_cr")
    if reported:
        pct = abs(parsed_cost - reported) / reported * 100
        checks.append({"check": "sum_original_cost", "expected": reported,
                       "parsed": round(parsed_cost, 2),
                       "diff_pct": round(pct, 3),
                       "ok": pct <= COST_TOLERANCE_PCT})

    parsed_exp = sum(r["cumulative_expenditure_cr"] for r in rows
                     if r["cumulative_expenditure_cr"] is not None)
    rep_exp = summary.get("expenditure_cr")
    if rep_exp:
        pct = abs(parsed_exp - rep_exp) / rep_exp * 100
        checks.append({"check": "sum_expenditure", "expected": rep_exp,
                       "parsed": round(parsed_exp, 2),
                       "diff_pct": round(pct, 3),
                       "ok": pct <= COST_TOLERANCE_PCT})

    unparsed = stats["unparsed_cost_cells"] + stats["unparsed_date_cells"]
    checks.append({"check": "unparsed_nonblank_cells", "expected": 0,
                   "parsed": unparsed, "ok": unparsed == 0})

    return {"ok": all(c["ok"] for c in checks) and len(checks) >= 2,
            "checks": checks, "reason": None}


def process(path: Path) -> dict:
    with pdfplumber.open(path) as pdf:
        summary = parse_summary(pdf)
        if summary.get("era") != "paimana":
            return {"file": path.name, "era": None, "parsed_rows": 0,
                    "quarantined_rows": 0,
                    "reconciliation": {"ok": False, "checks": [],
                                       "reason": "not a PAIMANA-era report"},
                    "pages": len(pdf.pages)}
        rows, quarantined, stats = parse_rows(pdf)
        pages = len(pdf.pages)

    rec = reconcile(rows, summary, stats)
    out = {
        "file": path.name, "pages": pages, "era": "paimana",
        "summary": summary, "stats": stats,
        "parsed_rows": len(rows), "quarantined_rows": len(quarantined),
        "reconciliation": rec,
        "data_source": "paimana",
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": f"python scripts/parse_paimana.py --file {path.as_posix()}",
    }
    INTERIM.mkdir(parents=True, exist_ok=True)
    (INTERIM / f"{path.stem}.rows.json").write_text(
        json.dumps({**out, "rows": rows, "quarantined": quarantined[:50]},
                   indent=1, default=str), encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    targets = [args.file] if args.file else sorted(RAW.glob("*.pdf")) if args.all else []
    if not targets:
        ap.print_help()
        return 2

    results = []
    for p in targets:
        res = process(p)
        results.append(res)
        rec = res["reconciliation"]
        print(f"{p.name}: era={res['era']} parsed={res['parsed_rows']} "
              f"quarantined={res['quarantined_rows']} ok={rec['ok']}"
              + (f" reason={rec['reason']}" if rec.get("reason") else ""), flush=True)
        for c in rec["checks"]:
            extra = f" diff_pct={c['diff_pct']}" if "diff_pct" in c else ""
            print(f"    {c['check']:24s} expected={c['expected']} "
                  f"parsed={c['parsed']}{extra} ok={c['ok']}")

    paimana = [r for r in results if r["era"] == "paimana"]
    passed = [r for r in paimana if r["reconciliation"]["ok"]]
    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / "reconciliation.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["report", "era", "pages", "parsed_rows", "quarantined_rows",
                    "summary_projects", "row_count_ok", "cost_ok", "exp_ok",
                    "unparsed_cells", "reconcile_ok", "reason"])
        for r in results:
            rec = r["reconciliation"]
            by = {c["check"]: c for c in rec["checks"]}
            w.writerow([
                r["file"], r["era"], r["pages"], r["parsed_rows"], r["quarantined_rows"],
                r.get("summary", {}).get("projects_on_monitor"),
                by.get("row_count", {}).get("ok"),
                by.get("sum_original_cost", {}).get("ok"),
                by.get("sum_expenditure", {}).get("ok"),
                by.get("unparsed_nonblank_cells", {}).get("parsed"),
                rec["ok"], rec.get("reason") or "",
            ])
    print(f"\nPAIMANA-era reports: {len(paimana)} | reconciled: {len(passed)} "
          f"| rows: {sum(r['parsed_rows'] for r in paimana)}")
    print(f"wrote {RESULTS / 'reconciliation.csv'}")
    return 0 if paimana and len(passed) == len(paimana) else 1


if __name__ == "__main__":
    raise SystemExit(main())
