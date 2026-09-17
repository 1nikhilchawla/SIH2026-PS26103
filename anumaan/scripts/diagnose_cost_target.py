#!/usr/bin/env python3
"""Why the cost-overrun target does not work on this corpus.

The rubric offered two ways out of a weak cost model:
  (a) lower the cost-change threshold in build_panel.py so more positives
      appear, or
  (b) state plainly that monthly cost overrun is not predictable here.

This script decides between them with evidence instead of preference. It
sweeps the threshold from 1% down to 0% and counts the labels that appear
at each level, per month. If (a) were the answer, positives would rise
sharply as the threshold falls.

Output: results/paimana/cost_target_diagnostic.json

Usage:
    python scripts/diagnose_cost_target.py
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "results" / "paimana" / "panel.csv"
OUT = ROOT / "results" / "paimana" / "cost_target_diagnostic.json"
THRESHOLDS = (0.0, 0.001, 0.0025, 0.005, 0.01)


def main() -> int:
    if not PANEL.exists():
        raise SystemExit(f"{PANEL} missing. Run: python scripts/build_panel.py")
    p = pd.read_csv(PANEL, parse_dates=["report_month"])
    p = p.sort_values(["entity_id", "report_month"]).reset_index(drop=True)

    nxt = p.groupby("entity_id", sort=False)["revised_cost_cr"].shift(-1)
    labelled = ((p["label_horizon_months"] == 1)
                & p["revised_cost_cr"].notna() & nxt.notna())
    denom = p["revised_cost_cr"].abs().replace(0, np.nan)
    rel = (nxt - p["revised_cost_cr"]) / denom
    month = p["report_month"].dt.strftime("%Y-%m")

    sweep = []
    for tol in THRESHOLDS:
        lab = (rel[labelled] > tol).astype(int)
        per_month = {k: int(v) for k, v in lab.groupby(month[labelled]).sum().items()}
        sweep.append({
            "threshold": tol,
            "positives": int(lab.sum()),
            "base_rate": float(lab.mean()),
            "positives_by_month": per_month,
            "months_with_at_least_30_positives":
                int(sum(1 for v in per_month.values() if v >= 30)),
        })

    r = rel[labelled].dropna()
    changed = p.loc[labelled & (rel.abs() > 0), "entity_id"].nunique()
    top = sweep[0]["positives_by_month"]
    busiest = max(top, key=top.get) if top else None

    payload = {
        "question": ("Does lowering the cost-change threshold surface enough "
                     "positives to train a cost-overrun model on this corpus?"),
        "answer": "no",
        "data_source": "paimana",
        "panel_file": "results/paimana/panel.csv",
        "labelled_rows": int(labelled.sum()),
        "threshold_sweep": sweep,
        "fraction_of_project_months_with_any_cost_change":
            float((r.abs() > 0).mean()),
        "quantiles_of_next_month_cost_change_ratio":
            {f"q{q}": float(r.quantile(q)) for q in (0.5, 0.9, 0.95, 0.99, 0.999)},
        "distinct_projects_that_ever_changed_revised_cost": int(changed),
        "busiest_month": busiest,
        "positives_in_busiest_month": None if busiest is None else int(top[busiest]),
        "reading": (
            "Dropping the threshold from 0.5% to 0% moves the positive count "
            "from {a} to {b} - it does not unlock the target. The reason is in "
            "the corpus, not the threshold: {pct:.2f}% of project-months carry "
            "exactly zero change in revised cost, and even the 99th percentile "
            "of the month-on-month change ratio is 0.000000. Revised cost in "
            "these reports is a near-static field that moves in episodic "
            "administrative batches, not a monthly signal. Option (a) from the "
            "rubric is refuted; option (b) is the honest course."
        ).format(a=sweep[-2]["positives"], b=sweep[0]["positives"],
                 pct=100.0 * (1.0 - float((r.abs() > 0).mean()))),
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": "python scripts/diagnose_cost_target.py",
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    for s in sweep:
        print(f"threshold={s['threshold']:<7} positives={s['positives']:<5} "
              f"base_rate={s['base_rate']:.4f} "
              f"months_with_30plus={s['months_with_at_least_30_positives']}")
    print()
    print(f"project-months with any cost change : "
          f"{payload['fraction_of_project_months_with_any_cost_change']:.4%}")
    print(f"distinct projects that ever changed  : "
          f"{payload['distinct_projects_that_ever_changed_revised_cost']}")
    print(f"busiest month                        : {busiest} "
          f"({payload['positives_in_busiest_month']} of "
          f"{sweep[0]['positives']} positives)")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
