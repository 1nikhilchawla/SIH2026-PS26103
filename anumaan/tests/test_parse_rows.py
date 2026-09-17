"""Tests for the per-era row parsers in scripts/parse_core.py.

The row parsers operate on a `cells_per_page` iterable that yields
(page_idx, list_of_cell_lists) tuples. Tests construct that iterable
directly with synthetic data, so no pdfplumber / real PDF is required.
This is the P1 acceptance criterion for `make test`.

Once real PDFs are on disk, scripts/parse_report.py wires
pdfplumber.extract_tables() into the same core - the integration test
for that path lives in tests/test_parse_integration.py (to be added in
P3 once we have real PDFs).
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.parse_core import (  # noqa: E402
    parse_rows,
    parse_rows_dispatch,
    OCMS_EXPECTED_COLS,
    PAIMANA_EXPECTED_COLS,
)


def _ocms_table_with_header() -> list[list[str]]:
    header = ["Sl.No", "Project", "Date of Approval", "Original Cost",
              "Revised Cost", "Anticipated Cost", "Cumulative Expenditure",
              "Original Date of Commissioning", "Revised Date of Commissioning",
              "Anticipated Date of Commissioning", "Time Overrun (Months)",
              "Cost Overrun (%)", "Reasons for Delay"]
    rows = [header]
    for i in range(1, 4):
        rows.append([
            str(i),
            f"Project { i} (NR) (10{i})",
            "01/04/2019",
            "1,000.00",
            "1,200.00",
            "1,500.00",
            "500.00",
            "03/2024",
            "09/2025",
            "06/2026",
            "27",
            "50.00",
            "Land acquisition pending with state revenue dept.",
        ])
    return rows


def _paimana_table_with_header() -> list[list[str]]:
    header = ["Sl.No", "Project", "State", "Date of Approval",
              "Original Date of Commissioning", "Target Date of Commissioning",
              "Original Cost", "Revised Cost", "Cumulative Expenditure",
              "Physical Progress (%)"]
    rows = [header]
    for i in range(1, 4):
        rows.append([
            str(i),
            f"Highway project {i} (NHAI) (P-{i:03d}) (OCMS-{i:04d}) (PMG-{i:05d})",
            "Maharashtra",
            "01/04/2020",
            "03/2025",
            "03/2027",
            "2,000.00",
            "2,500.00",
            "1,000.00",
            "42.0",
        ])
    return rows


# ---------------------------------------------------------------------------
# OCMS row parser
# ---------------------------------------------------------------------------

def test_ocms_parses_well_formed_table():
    parsed, quarantined = parse_rows([(0, _ocms_table_with_header())], "ocms")
    assert len(quarantined) == 0
    assert len(parsed) == 3
    first = parsed[0]
    assert first["sl_no"] == 1
    assert first["project_name"].startswith("Project")
    assert first["agency"] == "NR"
    assert first["code"] == "101"
    assert first["original_cost"] == 1000.0
    assert first["date_of_approval"] == "2019-04-01"
    assert first["time_overrun_months"] == 27


def test_ocms_quarantines_wrong_column_count():
    header = _ocms_table_with_header()[0]
    bad_row = [str(i) for i in range(1, 12)]  # 11 cells, OCMS wants 13
    parsed, quarantined = parse_rows([(0, [header, bad_row])], "ocms")
    assert len(parsed) == 0
    assert len(quarantined) == 1
    assert quarantined[0]["reason"] == "wrong_column_count"
    assert quarantined[0]["expected"] == OCMS_EXPECTED_COLS
    assert quarantined[0]["got"] == len(bad_row)


def test_ocms_skips_header_row():
    parsed, _ = parse_rows([(0, _ocms_table_with_header())], "ocms")
    # 3 project rows, not 4 - header was skipped
    assert len(parsed) == 3


def test_ocms_skips_summary_and_footer_pages():
    """A page that is just summary text or footer chrome must not be parsed."""
    summary_page = [
        ["The Flash Report for July 2019 contains 1623 projects."],
        ["Total: 19,33,390.22 crore.", "Crore", "Crore", "Crore"],
    ]
    footer_page = [
        ["Page 12 of 340"],
        ["Source: Ministry of Statistics and Programme Implementation"],
    ]
    parsed, quarantined = parse_rows(
        [(0, summary_page), (1, footer_page)], "ocms",
    )
    assert parsed == []
    assert quarantined == []


# ---------------------------------------------------------------------------
# PAIMANA row parser
# ---------------------------------------------------------------------------

def test_paimana_parses_well_formed_table():
    parsed, quarantined = parse_rows([(0, _paimana_table_with_header())], "paimana")
    assert len(quarantined) == 0
    assert len(parsed) == 3
    first = parsed[0]
    assert first["sl_no"] == 1
    assert first["agency"] == "NHAI"
    assert first["project_code"] == "P-001"
    assert first["legacy_ocms_code"] == "OCMS-0001"
    assert first["pmgid"] == "PMG-00001"
    assert first["state"] == "Maharashtra"
    assert first["physical_progress_pct"] == 42.0
    # PAIMANA does not carry these fields
    assert first["anticipated_cost"] is None
    assert first["time_overrun_months"] is None
    assert first["reasons_for_delay"] is None


def test_paimana_quarantines_wrong_column_count():
    header = _paimana_table_with_header()[0]
    bad_row = ["1", "Project", "State", "Date", "Original DoC", "Target DoC",
               "Original Cost", "Revised Cost", "Cumulative Expenditure"]
    parsed, quarantined = parse_rows([(0, [header, bad_row])], "paimana")
    assert len(parsed) == 0
    assert len(quarantined) == 1
    assert quarantined[0]["reason"] == "wrong_column_count"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def test_dispatch_routes_by_era():
    parsed, _ = parse_rows_dispatch([(0, _ocms_table_with_header())],
                                    {"era": "ocms"})
    assert all("code" in p for p in parsed)
    assert all("pmgid" not in p for p in parsed)

    parsed2, _ = parse_rows_dispatch([(0, _paimana_table_with_header())],
                                     {"era": "paimana"})
    assert all("pmgid" in p for p in parsed2)
    assert all("code" not in p for p in parsed2)


def test_dispatch_unknown_era_returns_empty():
    parsed, quarantined = parse_rows_dispatch([(0, [])], {"era": "unknown"})
    assert parsed == []
    assert quarantined == []


def test_dispatch_empty_cells_returns_empty():
    parsed, quarantined = parse_rows_dispatch([], {"era": "ocms"})
    assert parsed == []
    assert quarantined == []


# ---------------------------------------------------------------------------
# Multi-page behaviour
# ---------------------------------------------------------------------------

def test_continues_across_multiple_pages():
    header = _ocms_table_with_header()[0]
    page1 = [header] + _ocms_table_with_header()[1:]
    page2 = [header] + _ocms_table_with_header()[1:]
    parsed, _ = parse_rows([(0, page1), (1, page2)], "ocms")
    assert len(parsed) == 6


def test_quarantine_does_not_emit_below_four_cells():
    """Rows with <4 cells are page chrome, not rows - they are not quarantined."""
    parsed, quarantined = parse_rows(
        [(0, [["a"], ["1", "2"], ["1", "2", "3"], _ocms_table_with_header()[1]])],
        "ocms",
    )
    assert len(parsed) == 1
    assert quarantined == []  # short rows are silently skipped, not quarantined