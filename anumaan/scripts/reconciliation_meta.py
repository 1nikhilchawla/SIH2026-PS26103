#!/usr/bin/env python3
"""Summarise the parser's reconciliation table into reconciliation_meta.json.

Why this exists: the live app's Data Pipeline tab reads
results/paimana/reconciliation_meta.json. That file used to be written once,
inline, by the OLD parser (scripts/parse_report.py) and was never regenerated,
so the tab kept reporting that run - 0 of 32 reports reconciling - long after
scripts/parse_paimana.py reconciled every PAIMANA-era report. A number no
script regenerates is not evidence.

Now there is one code path: parse_paimana.py writes reconciliation.csv and
then calls write_meta() here, so the summary is rebuilt on every parse. Every
figure below is counted from that CSV - nothing is typed in.

Strict by design: a row whose flags are not True/False, whose counts are not
whole numbers, or that fits no status bucket stops the run.

Usage (normally called by parse_paimana.py; standalone re-summarises the
CSV already on disk, without re-parsing 32 PDFs):
    python scripts/reconciliation_meta.py
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "paimana"
CSV_PATH = RESULTS / "reconciliation.csv"
META_PATH = RESULTS / "reconciliation_meta.json"

EXPECTED_COLUMNS = ["report", "era", "pages", "parsed_rows", "quarantined_rows",
                    "summary_projects", "row_count_ok", "cost_ok", "exp_ok",
                    "unparsed_cells", "reconcile_ok", "reason"]


def _bool(value: str, field: str, report: str) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise ValueError(f"{report}: {field}={value!r} is not True/False")


def _int(value: str, field: str, report: str, blank_ok: bool = False) -> int | None:
    if value == "" and blank_ok:
        return None
    if not value.isdigit():
        raise ValueError(f"{report}: {field}={value!r} is not a whole number")
    return int(value)


def read_rows(csv_path: Path = CSV_PATH) -> list[dict]:
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise ValueError(f"{csv_path.name}: columns {reader.fieldnames} != {EXPECTED_COLUMNS}")
        return list(reader)


def summarise(rows: list[dict]) -> dict:
    """Count, never infer. Each report lands in exactly one status bucket:
    reconciled         PAIMANA-era, every check passed
    reconcile_failed   PAIMANA-era, parsed, but a check failed
    not_paimana_era    content detection says it is not the PAIMANA layout
                       (the older OCMS-period layout); not parsed yet
    """
    if not rows:
        raise ValueError("reconciliation.csv has no rows")
    reports = []
    for r in rows:
        name = r["report"]
        era = r["era"]
        if era not in ("paimana", ""):
            raise ValueError(f"{name}: unexpected era {era!r}")
        ok = _bool(r["reconcile_ok"], "reconcile_ok", name)
        if ok and era != "paimana":
            raise ValueError(f"{name}: reconciled but not PAIMANA-era - parser output is inconsistent")
        status = ("reconciled" if ok else
                  "reconcile_failed" if era == "paimana" else
                  "not_paimana_era")
        reports.append({
            "report": name,
            "era": era or None,
            "status": status,
            "pages": _int(r["pages"], "pages", name),
            "parsed_rows": _int(r["parsed_rows"], "parsed_rows", name),
            "quarantined_rows": _int(r["quarantined_rows"], "quarantined_rows", name),
            "summary_projects": _int(r["summary_projects"], "summary_projects", name, blank_ok=True),
            "unparsed_cells": _int(r["unparsed_cells"], "unparsed_cells", name, blank_ok=True),
            "reason": r["reason"] or None,
        })

    def by(status: str) -> list[dict]:
        return [x for x in reports if x["status"] == status]

    paimana = [x for x in reports if x["era"] == "paimana"]
    reconciled = by("reconciled")
    parsed = sum(x["parsed_rows"] for x in paimana)
    quarantined = sum(x["quarantined_rows"] for x in paimana)
    unparsed_cells = sum(x["unparsed_cells"] or 0 for x in paimana)
    return {
        "data_source": "paimana",
        "n_reports": len(reports),
        "paimana_era_reports": len(paimana),
        "reconciled": len(reconciled),
        "reconcile_failed": len(by("reconcile_failed")),
        "not_paimana_era_reports": len(by("not_paimana_era")),
        "reconcile_rate_pct_of_paimana_era": (round(100.0 * len(reconciled) / len(paimana), 1)
                                              if paimana else None),
        "rows_parsed_paimana_era": parsed,
        "rows_in_reconciled_reports": sum(x["parsed_rows"] for x in reconciled),
        "rows_quarantined": quarantined,
        "reports_with_quarantined_rows": sum(1 for x in paimana if x["quarantined_rows"]),
        "quarantined_row_pct": (round(100.0 * quarantined / (parsed + quarantined), 3)
                                if parsed + quarantined else None),
        "unparsed_nonblank_cells": unparsed_cells,
        "status_breakdown": {s: len(by(s)) for s in
                             ("reconciled", "reconcile_failed", "not_paimana_era")},
        "reports": reports,
        "notes": ("A report enters the panel only if its parsed rows re-add to the "
                  "project count, original cost and expenditure printed inside that "
                  "same report. not_paimana_era reports are in the older layout; they "
                  "are reported as not parsed rather than half-read."),
    }


def write_meta(csv_path: Path = CSV_PATH, out_path: Path = META_PATH,
               generated_by: str = "python scripts/reconciliation_meta.py") -> dict:
    meta = summarise(read_rows(csv_path))
    try:
        source = csv_path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        source = csv_path.name
    meta["source_file"] = source
    meta["source_sha256"] = hashlib.sha256(
        csv_path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    meta["generated_at"] = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
    meta["generated_by"] = generated_by
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return meta


def main() -> int:
    if not CSV_PATH.exists():
        raise SystemExit(f"{CSV_PATH} missing - run: python scripts/parse_paimana.py --all")
    m = write_meta()
    print(f"reports {m['n_reports']} | PAIMANA-era {m['paimana_era_reports']} | "
          f"reconciled {m['reconciled']} | failed {m['reconcile_failed']} | "
          f"not PAIMANA-era {m['not_paimana_era_reports']} | "
          f"rows {m['rows_in_reconciled_reports']} | quarantined {m['rows_quarantined']} | "
          f"unparsed cells {m['unparsed_nonblank_cells']}")
    print(f"wrote {META_PATH.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
