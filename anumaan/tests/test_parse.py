"""Tests for the parsing core (scripts/parse_core.py).

These run with only the Python standard library + bs4 - no pdfplumber, no
yaml, no numpy. That is the P1 acceptance criterion for `make test`.

Synthetic inputs are built from the column layouts documented in the
docstring of parse_core. Once real Flash Reports are on disk, integration
tests wrap pdfplumber.open(...) around the same core functions.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.parse_core import (  # noqa: E402
    parse_summary,
    parse_date,
    to_float,
    to_int,
    reconcile,
    _extract_id_from_ocms_project,
    _extract_id_from_paimana_project,
    _looks_like_id,
    _looks_like_agency,
    _is_header_row,
    _is_summary_or_footer,
    OCMS_EXPECTED_COLS,
    PAIMANA_EXPECTED_COLS,
)


OCMS_SUMMARY_TEXT = (
    "The Flash Report for July 2019 contains information on the status of the "
    "1623 Central Sector Infrastructure Projects costing 150 crore and above. "
    "Of these, 552 projects are delayed with respect to their original schedules. "
    "Total original cost of these 1623 projects is 19,33,390.22 crore and their "
    "anticipated completion cost is likely to be 23,21,502.84 crore, which "
    "reflects overall cost overruns of 3,88,112.62 crore (20.07% of original cost)."
)

PAIMANA_SUMMARY_TEXT = (
    "1775 | 17  Ongoing Projects | Line Ministries & Departments\n"
    "Rs 33,70,138 Original Cost (crores)\n"
    "Rs 37,10,642 Revised Cost (crores)\n"
    "Rs 19,26,100 (51.91% of Revised Cost) Cumulative Expenditure\n"
)


# ---------------------------------------------------------------------------
# summary / era tests
# ---------------------------------------------------------------------------

def test_summary_ocms_parses_all_fields():
    s = parse_summary(OCMS_SUMMARY_TEXT)
    assert s["era"] == "ocms"
    assert s["projects_on_monitor"] == 1623
    assert s["projects_delayed"] == 552
    assert abs(s["original_cost_cr"] - 1933390.22) < 0.01
    assert abs(s["anticipated_cost_cr"] - 2321502.84) < 0.01
    assert abs(s["cost_overrun_cr"] - 388112.62) < 0.01
    assert abs(s["cost_overrun_pct"] - 20.07) < 0.01


def test_summary_paimana_parses_all_fields():
    s = parse_summary(PAIMANA_SUMMARY_TEXT)
    assert s["era"] == "paimana"
    assert s["projects_on_monitor"] == 1775
    assert abs(s["original_cost_cr"] - 3370138.0) < 0.01
    assert abs(s["revised_cost_cr"] - 3710642.0) < 0.01
    assert abs(s["expenditure_cr"] - 1926100.0) < 0.01
    assert abs(s["expenditure_pct_of_revised"] - 51.91) < 0.01


def test_summary_unknown_era_returns_all_none_keys():
    s = parse_summary("This document contains nothing relevant.")
    assert s["era"] is None
    for k in ("projects_on_monitor", "projects_delayed", "original_cost_cr",
              "revised_cost_cr", "anticipated_cost_cr"):
        assert s[k] is None


# ---------------------------------------------------------------------------
# numeric and date helpers
# ---------------------------------------------------------------------------

def test_to_float_handles_comma_separated():
    assert to_float("19,33,390.22") == 1933390.22
    assert to_float("") is None
    assert to_float(None) is None
    assert to_float("n/a") is None


def test_to_float_strips_currency_and_footnote_markers():
    assert to_float("Rs. 1,234.56") == 1234.56
    assert to_float("₹1234.56") == 1234.56
    assert to_float("1,234.56*") == 1234.56   # footnote asterisk
    assert to_float("1,234.56 (#)") == 1234.56  # footnote in parens
    assert to_float("(-)12.5") == -12.5       # Indian-accounting convention: (-) means negative
    assert to_float("−12.5") == -12.5         # unicode minus
    assert to_float("nan") is None
    assert to_float("inf") is None
    assert to_float("-") is None


def test_to_int_handles_comma_separated():
    assert to_int("1,623") == 1623
    assert to_int(None) is None


def test_parse_date_iso():
    assert parse_date("2026-09-15") == "2026-09-15"


def test_parse_date_dd_mm_yyyy():
    assert parse_date("15/09/2026") == "2026-09-15"


def test_parse_date_dd_mm_yy():
    assert parse_date("15/09/26") == "2026-09-15"
    assert parse_date("15/09/95") == "1995-09-15"


def test_parse_date_mm_yyyy():
    assert parse_date("09/2026") == "2026-09-01"


def test_parse_date_dd_mon_yyyy():
    assert parse_date("31-Mar-2027") == "2027-03-31"
    assert parse_date("1 Mar 2027") == "2027-03-01"


def test_parse_date_sentinels():
    for s in ("NA", "N.A.", "N/A", "", "01/1900", "01-01-1900", "01/01/1900",
              "Not Available", "-"):
        assert parse_date(s) is None, s


def test_parse_date_invalid_calendar():
    """Real-but-impossible dates must not slip through (DQ003 trap)."""
    assert parse_date("31/02/2026") is None  # 31 Feb does not exist
    assert parse_date("15/13/2026") is None  # month 13


def test_parse_date_yy_pivot():
    assert parse_date("01/01/69") == "2069-01-01"
    assert parse_date("01/01/70") == "1970-01-01"


# ---------------------------------------------------------------------------
# bracketed ID extraction
# ---------------------------------------------------------------------------

def test_extract_id_ocms_full():
    ids = _extract_id_from_ocms_project("New BG line by NR (NR) (1234)")
    assert ids["project_name"].startswith("New BG")
    assert ids["agency"] == "NR"
    assert ids["code"] == "1234"


def test_extract_id_ocms_no_agency():
    ids = _extract_id_from_ocms_project("Project X (1234)")
    assert ids["agency"] is None
    assert ids["code"] == "1234"
    assert ids["project_name"].startswith("Project X")


def test_extract_id_ocms_id_first_then_agency():
    """PAIMANA findings 7: bracketed groups map by shape, not by position."""
    ids = _extract_id_from_ocms_project("Foo (NHAI) (P-002)")
    assert ids["agency"] == "NHAI"
    assert ids["code"] == "P-002"


def test_extract_id_paimana_full():
    cell = "Construction of Highway (NHAI) (P-001) (OCMS-9999) (PMGID-42)"
    ids = _extract_id_from_paimana_project(cell)
    assert ids["agency"] == "NHAI"
    assert ids["project_code"] == "P-001"
    assert ids["legacy_ocms_code"] == "OCMS-9999"
    assert ids["pmgid"] == "PMGID-42"
    assert ids["project_name"].startswith("Construction")


def test_extract_id_paimana_minimal():
    """Only PMGID is present; everything else stays None."""
    ids = _extract_id_from_paimana_project("Project X (PMGID-42)")
    assert ids["pmgid"] == "PMGID-42"
    assert ids["project_code"] is None
    assert ids["legacy_ocms_code"] is None
    assert ids["agency"] is None
    assert ids["project_name"].startswith("Project X")


def test_extract_id_paimana_agency_not_promoted_to_legacy_code():
    """Review finding 7: 'NHAI' must not land in legacy_ocms_code."""
    ids = _extract_id_from_paimana_project("Bridge over Ganga (NHAI) (P-002)")
    assert ids["agency"] == "NHAI"
    assert ids["project_code"] == "P-002"
    assert ids["legacy_ocms_code"] is None
    assert ids["pmgid"] is None


def test_looks_like_id_recognises_code_prefixes():
    for s in ("PMGID-42", "OCMS-9999", "P-001", "OMC-77", "ID-7"):
        assert _looks_like_id(s), s
    for s in ("NHAI", "NR", "Railway"):
        assert not _looks_like_id(s), s


def test_looks_like_agency_recognises_known_acronyms():
    assert _looks_like_agency("NHAI")
    assert _looks_like_agency("NR")
    assert _looks_like_agency("MoRTH")
    assert _looks_like_agency("Railways")   # in KNOWN_AGENCY_ACRONYMS
    assert not _looks_like_agency("PMGID-42")
    assert not _looks_like_agency("")       # empty is not an agency


def test_is_header_row_recognises_table_headers():
    ocms_header = ["Sl.No", "Project", "Date of Approval", "Original Cost",
                   "Revised Cost", "Anticipated Cost", "Cumulative Expenditure",
                   "Original Date of Commissioning", "Revised Date of Commissioning",
                   "Anticipated Date of Commissioning", "Time Overrun (Months)",
                   "Cost Overrun (%)", "Reasons for Delay"]
    assert _is_header_row(ocms_header, "ocms") is True


def test_is_header_row_rejects_data_rows():
    data = ["1", "Some project (NR) (100)", "01/04/2019", "1,000.00", "",
            "1,200.00", "500.00", "03/2024", "", "06/2026", "27", "20.0",
            "Land acquisition pending."]
    assert _is_header_row(data, "ocms") is False


def test_is_summary_or_footer_catches_page_chrome():
    assert _is_summary_or_footer(["Total 1,234.56 crore", "", "", ""])
    assert _is_summary_or_footer(["Page 12 of 340", "", "", ""])
    assert not _is_summary_or_footer(["1", "Project X", "01/04/2019", "100.00"])


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def _ocms_rows(n: int = 5) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        rows.append({
            "sl_no": i,
            "original_cost": 100.0,
            "revised_cost": 110.0,
            "anticipated_cost": 120.0,
            "cumulative_expenditure": 50.0,
            "time_overrun_months": 12,
            "cost_overrun_pct": 20.0,
        })
    return rows


def test_reconcile_passes_when_counts_and_totals_match():
    summary = {"era": "ocms", "projects_on_monitor": 5,
               "original_cost_cr": 500.0, "anticipated_cost_cr": 600.0}
    cfg = {"parse": {"count_tolerance": 0, "cost_tolerance_pct": 0.5}}
    rec = reconcile(_ocms_rows(5), [], summary, cfg)
    assert rec["ok"] is True
    assert {c["check"] for c in rec["checks"]} >= {"row_count", "sum_original_cost",
                                                   "sum_anticipated_cost"}


def test_reconcile_fails_when_no_rows_but_summary_announced_count():
    """Review finding 3: empty rows + expected count -> vacuous pass was a bug."""
    summary = {"era": "ocms", "projects_on_monitor": 1623,
               "original_cost_cr": 500.0, "anticipated_cost_cr": 600.0}
    cfg = {"parse": {"count_tolerance": 0, "cost_tolerance_pct": 0.5}}
    rec = reconcile([], [], summary, cfg)
    assert rec["ok"] is False
    count_check = next(c for c in rec["checks"] if c["check"] == "row_count")
    assert count_check["ok"] is False
    assert "no rows" in count_check["reason"].lower()


def test_reconcile_reports_missing_summary_field():
    summary = {"era": "ocms", "projects_on_monitor": None,
               "original_cost_cr": None, "anticipated_cost_cr": None}
    cfg = {"parse": {"count_tolerance": 0, "cost_tolerance_pct": 0.5}}
    rec = reconcile(_ocms_rows(3), [], summary, cfg)
    assert "projects_on_monitor" in rec["missing_summary_fields"]
    assert "sum_original_cost" in rec["missing_summary_fields"]


def test_reconcile_fails_on_count_mismatch():
    summary = {"era": "ocms", "projects_on_monitor": 10,
               "original_cost_cr": 500.0, "anticipated_cost_cr": 600.0}
    cfg = {"parse": {"count_tolerance": 0, "cost_tolerance_pct": 0.5}}
    rec = reconcile(_ocms_rows(5), [], summary, cfg)
    assert rec["ok"] is False
    count_check = next(c for c in rec["checks"] if c["check"] == "row_count")
    assert count_check["ok"] is False


def test_reconcile_fails_on_cost_drift():
    summary = {"era": "ocms", "projects_on_monitor": 5,
               "original_cost_cr": 1000.0, "anticipated_cost_cr": 600.0}
    cfg = {"parse": {"count_tolerance": 0, "cost_tolerance_pct": 0.5}}
    rec = reconcile(_ocms_rows(5), [], summary, cfg)
    assert rec["ok"] is False


def test_reconcile_paimana_checks_revised_and_expenditure():
    rows = _ocms_rows(4)
    summary = {"era": "paimana", "projects_on_monitor": 4,
               "original_cost_cr": 400.0, "revised_cost_cr": 440.0,
               "expenditure_cr": 200.0}
    cfg = {"parse": {"count_tolerance": 0, "cost_tolerance_pct": 0.5}}
    rec = reconcile(rows, [], summary, cfg)
    assert rec["ok"] is True
    assert {c["check"] for c in rec["checks"]} >= {"row_count",
                                                   "sum_original_cost",
                                                   "sum_revised_cost",
                                                   "sum_expenditure"}