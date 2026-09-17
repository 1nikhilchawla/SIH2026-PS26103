"""Data-quality rules for ANUMAAN.

Each rule returns a list of reason codes emitted against a row. Rules tagged
BLOCKER prevent the row from being scored or trained on; WARN rules surface
the issue but keep the row in the dataset. The exact list mirrors
docs/data-quality-rules.md (DQ001-DQ012).
"""
from __future__ import annotations

import re
from typing import Any

# Severity constants
BLOCKER = "BLOCKER"
WARN = "WARN"

SENTINEL_DATES = {"", "NA", "N.A.", "N/A", "01/01/1900", "01/1900",
                  "01-01-1900", "01-1900", "Not Available", "-"}


def _is_sentinel(value: Any, sentinels: set[str] = SENTINEL_DATES) -> bool:
    if value is None:
        return True
    return str(value).strip() in sentinels


def _months_between(a: str | None, b: str | None) -> int | None:
    """Months between two ISO YYYY-MM-DD strings. None if either is missing."""
    if not a or not b:
        return None
    try:
        ya, ma, da = (int(x) for x in a.split("-"))
        yb, mb, db = (int(x) for x in b.split("-"))
    except (ValueError, AttributeError):
        return None
    return (yb - ya) * 12 + (mb - ma) + (1 if db >= da else 0)


# --- Individual rules ---------------------------------------------------------

def dq001_missing_approval(row: dict) -> str | None:
    if _is_sentinel(row.get("date_of_approval")):
        return "DQ001"
    return None


def dq002_missing_original_doc(row: dict) -> str | None:
    if _is_sentinel(row.get("original_doc")):
        return "DQ002"
    return None


def dq003_doc_before_approval(row: dict) -> str | None:
    months = _months_between(row.get("date_of_approval"),
                             row.get("original_doc"))
    if months is not None and months < 0:
        return "DQ003"
    return None


def dq004_missing_original_cost(row: dict) -> str | None:
    cost = row.get("original_cost")
    if cost is None or cost <= 0:
        return "DQ004"
    return None


def dq005_expenditure_exceeds_revised(row: dict) -> str | None:
    exp = row.get("cumulative_expenditure")
    rev = row.get("revised_cost")
    if exp is None or rev is None:
        return None
    if exp > rev:
        return "DQ005"
    return None


def dq006_progress_decreased(row: dict, prev_progress: float | None) -> str | None:
    cur = row.get("physical_progress_pct")
    if cur is None or prev_progress is None:
        return None
    if cur < prev_progress:
        return "DQ006"
    return None


def dq007_zero_progress_high_spend(row: dict) -> str | None:
    pp = row.get("physical_progress_pct")
    orig = row.get("original_cost")
    exp = row.get("cumulative_expenditure")
    if pp is None or orig is None or exp is None or orig <= 0:
        return None
    spend_ratio = exp / orig
    if pp == 0 and spend_ratio > 0.2:
        return "DQ007"
    return None


def dq008_missing_revised_cost(row: dict, has_revision_signal: bool) -> str | None:
    if row.get("revised_cost") is None and has_revision_signal:
        return "DQ008"
    return None


def dq009_duplicate(row: dict, seen_keys: set[tuple]) -> str | None:
    """Detect (entity_id, report_month) duplicates. Caller maintains seen_keys."""
    key = (row.get("entity_id"), row.get("report_month"))
    if key[0] is None or key[1] is None:
        return None
    if key in seen_keys:
        return "DQ009"
    seen_keys.add(key)
    return None


def dq010_totals_disagree(row: dict, parser_reconciled: bool) -> str | None:
    # DQ010 lives at the report level (reconciliation), not the row level.
    # We surface it on every row of a report whose reconciliation failed.
    if not parser_reconciled:
        return "DQ010"
    return None


def dq011_progress_out_of_range(row: dict) -> str | None:
    pp = row.get("physical_progress_pct")
    if pp is None:
        return None
    if pp < 0 or pp > 100:
        return "DQ011"
    return None


def dq012_cost_revised_downward(row: dict) -> str | None:
    orig = row.get("original_cost")
    rev = row.get("revised_cost")
    if orig is None or rev is None or orig <= 0:
        return None
    if rev < orig * 0.5:
        return "DQ012"
    return None


# --- Orchestration ------------------------------------------------------------

RULES_ROW_LEVEL = (
    ("DQ001", dq001_missing_approval, BLOCKER),
    ("DQ002", dq002_missing_original_doc, BLOCKER),
    ("DQ003", dq003_doc_before_approval, BLOCKER),
    ("DQ004", dq004_missing_original_cost, BLOCKER),
    ("DQ005", dq005_expenditure_exceeds_revised, WARN),
    ("DQ007", dq007_zero_progress_high_spend, WARN),
    ("DQ011", dq011_progress_out_of_range, BLOCKER),
    ("DQ012", dq012_cost_revised_downward, WARN),
)

# Cross-row or context-dependent rules (need call-site help).
# These are NOT in RULES_ROW_LEVEL because they require state from adjacent
# rows or from the parser. Wire them in at the panel-building stage.
RULES_CONTEXT_DEP = (
    # DQ006: physical progress decreased vs previous month for the same project.
    #   Signature: dq006_progress_decreased(row, prev_progress: float | None) -> str | None
    ("DQ006", dq006_progress_decreased, WARN),
    # DQ008: revised_cost missing while a revision is implied elsewhere.
    #   Signature: dq008_missing_revised_cost(row, has_revision_signal: bool) -> str | None
    ("DQ008", dq008_missing_revised_cost, WARN),
    # DQ009: duplicate (entity_id, report_month) — maintained by the caller
    #   across the full panel, not per-row. Already in check_row() via seen_keys.
)

ALL_RULES = RULES_ROW_LEVEL + RULES_CONTEXT_DEP


def check_row(row: dict, parser_reconciled: bool = True,
              seen_keys: set[tuple] | None = None) -> list[dict]:
    """Return the list of DQ codes raised against a single row.

    Each entry is {code, severity, field?, value?}. Cross-row rules
    (DQ006, DQ008, DQ009) need call-site help; this function handles the rest.
    """
    seen = seen_keys if seen_keys is not None else set()
    findings: list[dict] = []
    for code, fn, severity in RULES_ROW_LEVEL:
        hit = fn(row)
        if hit:
            findings.append({"code": code, "severity": severity})
    if not parser_reconciled:
        findings.append({"code": "DQ010", "severity": BLOCKER})
    dq009 = dq009_duplicate(row, seen)
    if dq009:
        findings.append({"code": dq009, "severity": BLOCKER})
    return findings


def partition_by_blocker(rows: list[dict], **kwargs) -> tuple[list[dict], list[dict]]:
    """Split rows into (trainable, blocked). Each row gets a dq_codes field."""
    seen = set()
    trainable: list[dict] = []
    blocked: list[dict] = []
    for r in rows:
        codes = check_row(r, seen_keys=seen, **kwargs)
        r2 = dict(r)
        r2["dq_codes"] = [c["code"] for c in codes]
        r2["dq_blockers"] = [c["code"] for c in codes if c["severity"] == BLOCKER]
        if r2["dq_blockers"]:
            blocked.append(r2)
        else:
            trainable.append(r2)
    return trainable, blocked