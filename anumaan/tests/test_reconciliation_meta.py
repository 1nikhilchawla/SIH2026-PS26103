"""reconciliation_meta.json must be a faithful summary of the parser's own
reconciliation.csv - the Data Pipeline tab shows it to judges, and a stale
copy once told them 0 of 32 reports reconciled. Plain functions, no pytest
fixtures, so tests/run_tests.py can run them too."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import reconciliation_meta as rm  # noqa: E402

GENERATED = ("generated_at", "generated_by", "source_file", "source_sha256")


def test_meta_on_disk_is_the_summary_of_the_csv_on_disk():
    on_disk = json.loads(rm.META_PATH.read_text(encoding="utf-8"))
    fresh = rm.summarise(rm.read_rows())
    assert {k: v for k, v in on_disk.items() if k not in GENERATED} == fresh, \
        "reconciliation_meta.json is stale - run: python scripts/reconciliation_meta.py"
    csv_sha = hashlib.sha256(rm.CSV_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert on_disk["source_sha256"] == csv_sha


def test_meta_rows_match_the_panel_being_served():
    meta = json.loads(rm.META_PATH.read_text(encoding="utf-8"))
    prov = json.loads((ROOT / "results/paimana/panel_provenance.json").read_text(encoding="utf-8"))
    assert meta["rows_in_reconciled_reports"] == prov["n_rows"]


def _row(report, era, ok, parsed="0", quarantined="0", reason=""):
    return {"report": report, "era": era, "pages": "10", "parsed_rows": parsed,
            "quarantined_rows": quarantined, "summary_projects": parsed if era else "",
            "row_count_ok": ok if era else "", "cost_ok": ok if era else "",
            "exp_ok": ok if era else "", "unparsed_cells": "0" if era else "",
            "reconcile_ok": ok, "reason": reason}


def test_summarise_counts_every_bucket():
    m = rm.summarise([
        _row("a.pdf", "paimana", "True", parsed="100"),
        _row("b.pdf", "paimana", "False", parsed="40", quarantined="5", reason="row_count"),
        _row("c.pdf", "", "False", reason="not a PAIMANA-era report"),
    ])
    assert m["status_breakdown"] == {"reconciled": 1, "reconcile_failed": 1, "not_paimana_era": 1}
    assert (m["paimana_era_reports"], m["reconciled"], m["not_paimana_era_reports"]) == (2, 1, 1)
    assert m["rows_in_reconciled_reports"] == 100 and m["rows_parsed_paimana_era"] == 140
    assert m["rows_quarantined"] == 5 and m["reports_with_quarantined_rows"] == 1


def test_summarise_refuses_malformed_or_inconsistent_rows():
    for bad in (
        [_row("a.pdf", "paimana", "yes")],                      # flag not True/False
        [_row("a.pdf", "paimana", "True", parsed="1.5")],       # count not whole
        [_row("a.pdf", "", "True")],                            # reconciled, not PAIMANA-era
        [_row("a.pdf", "ocms?", "False")],                      # unknown era
        [],                                                     # nothing to summarise
    ):
        try:
            rm.summarise(bad)
        except ValueError:
            continue
        raise AssertionError(f"summarise accepted {bad}")
