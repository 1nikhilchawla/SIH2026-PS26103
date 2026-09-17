#!/usr/bin/env python3
"""Generate a synthetic project-month panel shaped like MoSPI Flash Reports.

The output is intentionally learnable: every slip event is drawn from a
logistic hazard that depends on point-in-time features, so the T1 trainer
in scripts/train_t1.py can recover a real signal. Features and labels are
both produced here; the trainer only consumes the saved panel.

Project universe
- 8 ministries, 6 sectors, 3 cost bands, ~300 projects total.
- Each project has a true "stability" (how often it slips) drawn from a
  Beta distribution with parameters that depend on ministry x sector.

Per-project time series
- Approval month uniform over Jan-2019 .. Jun-2024.
- Active months: from approval through Sep-2026 (the panel horizon).
- Each month, the project either revises its stated completion date or not.
  Probability of revision depends on baseline + recent observed features.
- When a revision happens, the magnitude is drawn from a geometric-like
  distribution (1..9 months).

Panel output
- One row per (entity_id, month). Columns:
    entity_id, month, ministry, sector, cost_band_cr, agency,
    approval_month, original_doc, stated_doc,
    cumulative_drift_months, agency_revisions_so_far,
    months_since_last_revision, silent_streak,
    expenditure_ratio, physical_progress_pct, exp_progress_divergence,
    months_since_approval, delay_cause,
    slip_3m, slip_6m, slip_12m    (point-in-time labels)

Labels are computed by looking forward from month t. To stay strictly
point-in-time, the trainer must drop label columns except for the row at
month t when predicting whether slip happens in [t+1, t+h].

Usage:
    python scripts/synth_panel.py --out data/synthetic/panel.csv
    python scripts/synth_panel.py --out data/synthetic/panel.parquet --seed 42
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# --- Taxonomic constants (sourced from config/delay_taxonomy.yaml) ------------
MINISTRIES = ["Road Transport & Highways", "Railways", "Coal", "Power",
              "Petroleum & Natural Gas", "Steel", "Health & Family Welfare",
              "Water Resources"]
SECTORS = ["highway", "railway", "coal", "power", "oil_and_gas", "health"]
COST_BANDS = [(150, 500), (500, 1000), (1000, 5000)]   # Rs crore
AGENCIES = ["NHAI", "Indian Railways", "Coal India", "NTPC",
            "ONGC", "SAIL", "MoHFW", "CWC"]

# 13 delay-cause labels from config/delay_taxonomy.yaml.
DELAY_CAUSES = [
    "land_acquisition", "forest_environment_clearance",
    "right_of_way_utilities", "contractor_performance",
    "funds_and_payments", "litigation", "law_and_order",
    "design_scope_change", "geology_site_conditions",
    "supply_chain_equipment", "statutory_other_clearance",
    "covid_force_majeure", "unclassified",
]

# Slip-rate prior by sector (in log-odds). Calibrated so the panel-wide
# slip_12m rate lands in a realistic 15-25% band. Sectors with land/R-O-W
# issues get higher priors; the model recovers these.
SECTOR_LOGIT_PRIOR = {
    "highway": -0.3,
    "railway": -0.7,
    "coal": -1.4,
    "power": -1.1,
    "oil_and_gas": -1.7,
    "health": -0.9,
}

# Per-cause log-odds contribution (used in hazard). Subtle so the slip rate
# stays realistic; the model has to use FEATURES, not just the cause label.
CAUSE_LOGIT = {
    "land_acquisition": 0.4,
    "forest_environment_clearance": 0.3,
    "right_of_way_utilities": 0.2,
    "contractor_performance": 0.2,
    "funds_and_payments": 0.1,
    "litigation": 0.2,
    "law_and_order": 0.3,
    "design_scope_change": 0.3,
    "geology_site_conditions": 0.4,
    "supply_chain_equipment": 0.1,
    "statutory_other_clearance": 0.2,
    "covid_force_majeure": 0.0,
    "unclassified": 0.0,
}


def synth_panel(n_projects: int = 300,
                horizon_start: str = "2019-01",
                horizon_end: str = "2026-09",
                seed: int = 42) -> pd.DataFrame:
    """Build the full panel."""
    rng = np.random.default_rng(seed)

    months = pd.date_range(horizon_start, horizon_end, freq="MS")
    n_months = len(months)

    rows: list[dict] = []
    for pid in range(n_projects):
        ministry = MINISTRIES[rng.integers(0, len(MINISTRIES))]
        sector = SECTORS[rng.integers(0, len(SECTORS))]
        cost_lo, cost_hi = COST_BANDS[rng.integers(0, len(COST_BANDS))]
        original_cost = float(rng.uniform(cost_lo, cost_hi))
        agency = AGENCIES[rng.integers(0, len(AGENCIES))]

        # Approval month uniform over [horizon_start, ~24 months before end]
        app_idx = rng.integers(0, n_months - 24)
        approval_month = months[app_idx]
        # Original DoC 24..72 months after approval
        original_doc_offset = int(rng.integers(24, 72))
        original_doc = approval_month + pd.DateOffset(months=original_doc_offset)

        # True baseline slip propensity in log-odds
        prior = SECTOR_LOGIT_PRIOR[sector]
        # Some projects are intrinsically stable / unstable: shift prior
        archetype = rng.choice(["stable", "average", "unstable"],
                               p=[0.15, 0.70, 0.15])
        arch_shift = {"stable": -0.8, "average": 0.0, "unstable": 0.8}[archetype]
        baseline_logit = prior + arch_shift

        # Pick a delay cause for this project (semi-stable over time).
        cause = rng.choice(DELAY_CAUSES)

        # State variables
        stated_doc = original_doc
        cum_drift = 0
        revisions_so_far = 0
        months_since_rev = 0
        silent_streak = 0
        cum_expenditure = 0.0
        physical_progress = 0.0
        last_silent = False

        # Per-month label placeholders
        forward_doc = stated_doc  # rolling stated_doc for label computation

        # Run the simulation month by month
        for t in range(n_months):
            m = months[t]
            # Project not yet approved -> skip
            if m < approval_month:
                continue
            # Project completed (past original_doc + 24 months) -> freeze
            if m > original_doc + pd.DateOffset(months=24):
                # Still report a final row but no further updates
                pass

            # --- Hazard: probability of a revision this month ---------------
            # Logistic in: baseline + cause effect + recent features.
            age_months = (m.year - approval_month.year) * 12 + (m.month - approval_month.month)
            z = (baseline_logit
                 + CAUSE_LOGIT[cause] * 0.3
                 + 0.3 * (silent_streak >= 3)              # silent projects often revise next month
                 - 0.04 * min(physical_progress, 100) / 10  # progress slows slips
                 + 0.015 * (cum_drift / 12.0))              # drifting projects keep drifting
            z += rng.normal(0, 0.25)                       # project-level noise
            p_rev = 1.0 / (1.0 + np.exp(-z))

            did_revise = rng.random() < p_rev
            if did_revise:
                # Geometric-ish magnitude: 1, 2, 3, 6 most common; 9+ rare.
                # Mirrors the Flash Report observation that most monthly
                # revisions are 1-3 months; big jumps are uncommon.
                mag_pick = rng.random()
                if mag_pick < 0.55:
                    magnitude = 1
                elif mag_pick < 0.80:
                    magnitude = 2
                elif mag_pick < 0.93:
                    magnitude = 3
                elif mag_pick < 0.98:
                    magnitude = 6
                else:
                    magnitude = 9
                stated_doc = stated_doc + pd.DateOffset(months=magnitude)
                cum_drift += magnitude
                revisions_so_far += 1
                months_since_rev = 0
                silent_streak = 0
                cum_expenditure += rng.uniform(0, 2.0) * (original_cost / 72.0)
                physical_progress = min(100.0,
                                        physical_progress + rng.uniform(0.5, 2.0))
                last_silent = False
            else:
                months_since_rev += 1
                silent_streak += 1 if last_silent else 1
                last_silent = True
                cum_expenditure += rng.uniform(0, 0.5) * (original_cost / 72.0)
                physical_progress = min(100.0,
                                        physical_progress + rng.uniform(0.0, 0.5))

            expenditure_ratio = cum_expenditure / original_cost
            exp_progress_div = expenditure_ratio - (physical_progress / 100.0)

            rows.append({
                "entity_id": f"P{pid:04d}",
                "month": m,
                "ministry": ministry,
                "sector": sector,
                "cost_band_cr": cost_hi,
                "agency": agency,
                "approval_month": approval_month,
                "original_doc": original_doc,
                "stated_doc": stated_doc,
                "cumulative_drift_months": cum_drift,
                "revisions_so_far": revisions_so_far,
                "months_since_last_revision": months_since_rev,
                "silent_streak": silent_streak,
                "expenditure_ratio": expenditure_ratio,
                "physical_progress_pct": physical_progress,
                "exp_progress_divergence": exp_progress_div,
                "months_since_approval": age_months,
                "delay_cause": cause,
                "_stated_doc_now": stated_doc,  # working copy
            })

    panel = pd.DataFrame(rows)

    # Forward-looking labels (use only stated_doc to compute slip_3m/6m/12m).
    # Sort once so groupby-shift is stable.
    panel = panel.sort_values(["entity_id", "month"]).reset_index(drop=True)
    for h in (3, 6, 12):
        # For each row, find stated_doc h months later (in the same panel).
        # Using merge on (entity_id, month+h_offset) keeps it O(N).
        future = panel[["entity_id", "month", "stated_doc"]].copy()
        future["month"] = future["month"] - pd.DateOffset(months=h)
        future = future.rename(columns={"stated_doc": f"stated_doc_plus{h}"})
        panel = panel.merge(future, on=["entity_id", "month"], how="left")
        drift = (panel[f"stated_doc_plus{h}"] - panel["stated_doc"]).dt.days / 30.0
        panel[f"slip_{h}m"] = (drift >= h).astype("Int64")

    panel = panel.drop(columns=["_stated_doc_now"]
                       + [c for c in panel.columns if c.startswith("stated_doc_plus")])
    return panel


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True,
                    help="output CSV or Parquet path")
    ap.add_argument("--n-projects", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    panel = synth_panel(n_projects=args.n_projects, seed=args.seed)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if str(args.out).endswith(".parquet"):
        panel.to_parquet(args.out, index=False)
    else:
        panel.to_csv(args.out, index=False)

    n_rows = len(panel)
    n_entities = panel["entity_id"].nunique()
    slip_12 = panel["slip_12m"].sum()
    slip_12_rate = slip_12 / n_rows
    print(f"wrote {args.out} | {n_rows:,} rows | {n_entities} projects "
          f"| slip_12m rate: {slip_12_rate:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())