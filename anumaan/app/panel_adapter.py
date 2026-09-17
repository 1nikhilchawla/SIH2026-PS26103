#!/usr/bin/env python3
"""Make the live service panel-agnostic.

The app was written against the synthetic panel (month, stated_doc,
slip_12m). The real PAIMANA panel uses different column names, a different
horizon, and a different label (report_month, target_doc, slip_next). Rather
than fake synthetic columns onto real data - which would put a 12-month label
over a 1-month number and break Law 1 - this module normalises both panels to
one canonical frame and reports honestly which one is loaded.

Canonical columns produced for either source:
    entity_id, month, ministry, sector, agency, project_name,
    original_doc, stated_doc, target, persistence_signal

`target` is the label. Its meaning is carried in PanelMeta.target_definition
and must be rendered wherever the number is shown.

Nothing here looks forward except the label columns, which are named as
labels and never returned in the feature matrix. drift_next_months is also
forward-looking; it is used ONLY to summarise the training window (how far
dates move when they move) and is never a feature.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

# Point-in-time features on the real PAIMANA panel. Identical to the list in
# scripts/train_slip.py, so the app reproduces that script's fold numbers.
REAL_NUMERIC = [
    "original_cost_cr", "revised_cost_cr", "cumulative_expenditure_cr",
    "physical_progress_pct", "months_since_approval", "cumulative_drift_months",
    "months_to_target", "months_past_original", "expenditure_ratio",
    "cost_overrun_ratio", "exp_progress_divergence", "drift_change_1m",
    "date_revised_this_month", "revisions_so_far", "cost_revised_this_month",
    "months_observed", "months_since_last_revision",
]
REAL_CATEGORICAL = ["ministry"]

SYNTH_NUMERIC = [
    "cumulative_drift_months", "revisions_so_far", "months_since_last_revision",
    "silent_streak", "expenditure_ratio", "physical_progress_pct",
    "exp_progress_divergence", "months_since_approval",
]
SYNTH_CATEGORICAL = ["ministry", "sector", "cost_band_cr", "agency"]

# Columns that look forward. Never features, in either schema.
LABEL_COLS = ["slip_next", "cost_up_next", "delta_cost_ratio_next",
              "label_horizon_months", "slip_3m", "slip_6m", "slip_12m",
              "target", "drift_next_months"]


@dataclass
class PanelMeta:
    data_source: str
    panel_file: str
    target_name: str
    horizon_months: int
    horizon_label: str
    target_definition: str
    default_cutoff: str
    numeric: list[str]
    categorical: list[str]
    n_rows: int
    n_projects: int
    n_months: int
    panel_span: str
    months: list[str] = field(default_factory=list)
    has_delay_cause: bool = False
    has_drift_magnitude: bool = False


def _months_between(a, b):
    if pd.isna(a) or pd.isna(b):
        return np.nan
    return (b.year - a.year) * 12 + (b.month - a.month)


def is_real(df: pd.DataFrame) -> bool:
    return "report_month" in df.columns and "slip_next" in df.columns


def _load_real(df: pd.DataFrame, path: Path) -> tuple[pd.DataFrame, PanelMeta]:
    out = df.copy()
    for c in ("report_month", "original_doc", "target_doc", "approval_month"):
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], errors="coerce")
    out["month"] = out["report_month"]
    out["stated_doc"] = out["target_doc"]
    out["target"] = out["slip_next"]

    # Persistence baseline: the project moved its date in the current report.
    out["persistence_signal"] = out.get("date_revised_this_month", 0)

    # Magnitude of the next move, in months. LABEL - training-window stats only.
    out = out.sort_values(["entity_id", "month"]).reset_index(drop=True)
    nxt = out.groupby("entity_id", sort=False)["target_doc"].shift(-1)
    consecutive = out["label_horizon_months"] == 1
    out["drift_next_months"] = [
        _months_between(a, b) if ok else np.nan
        for a, b, ok in zip(out["target_doc"], nxt, consecutive)]

    months = sorted(out["month"].dropna().dt.strftime("%Y-%m").unique())
    labelled = out[out["target"].notna()]
    last_labelled = (sorted(labelled["month"].dt.strftime("%Y-%m").unique())[-1]
                     if len(labelled) else months[-1])

    meta = PanelMeta(
        data_source="paimana",
        panel_file=str(path).replace("\\", "/").split("anumaan/")[-1],
        target_name="slip_next",
        horizon_months=1,
        horizon_label="next monthly report",
        target_definition=(
            "slip_next = 1 if the completion date the project states in the "
            "NEXT monthly report is later than the date it states this month. "
            "Horizon is one month - the next consecutive report. Every feature "
            "uses only figures printed on or before this month."),
        # Test on the last month that has a label, so the app's split matches
        # the final walk-forward fold in scripts/train_slip.py exactly.
        default_cutoff=last_labelled,
        numeric=REAL_NUMERIC,
        categorical=REAL_CATEGORICAL,
        n_rows=int(len(out)),
        n_projects=int(out["entity_id"].nunique()),
        n_months=len(months),
        panel_span=f"{months[0]} to {months[-1]}",
        months=months,
        has_delay_cause=False,
        has_drift_magnitude=True,
    )
    return out, meta


def _load_synth(df: pd.DataFrame, path: Path) -> tuple[pd.DataFrame, PanelMeta]:
    out = df.copy()
    for c in ("month", "original_doc", "stated_doc", "approval_month"):
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], errors="coerce")
    out["target"] = out["slip_12m"]
    out = out.sort_values(["entity_id", "month"]).reset_index(drop=True)

    g = out.groupby("entity_id", sort=False)["stated_doc"]
    revised = np.zeros(len(out))
    for k in (1, 2, 3):
        revised = np.maximum(revised,
                             (out["stated_doc"] != g.shift(k)).fillna(False)
                             .astype(float).to_numpy())
    out["persistence_signal"] = revised
    out["drift_next_months"] = np.nan

    months = sorted(out["month"].dropna().dt.strftime("%Y-%m").unique())
    meta = PanelMeta(
        data_source="synthetic",
        panel_file=str(path).replace("\\", "/").split("anumaan/")[-1],
        target_name="slip_12m",
        horizon_months=12,
        horizon_label="next 12 months",
        target_definition=(
            "slip_12m = 1 if the stated completion date 12 months ahead is "
            "later than the date stated this month. SYNTHETIC DATA - the "
            "numbers describe a simulation, not any real project."),
        default_cutoff="2025-01",
        numeric=SYNTH_NUMERIC,
        categorical=SYNTH_CATEGORICAL,
        n_rows=int(len(out)),
        n_projects=int(out["entity_id"].nunique()),
        n_months=len(months),
        panel_span=f"{months[0]} to {months[-1]}",
        months=months,
        has_delay_cause="delay_cause" in out.columns,
        has_drift_magnitude=False,
    )
    return out, meta


def load_panel(path: Path) -> tuple[pd.DataFrame, PanelMeta]:
    """Read a panel CSV and normalise it. Schema is detected from the columns,
    never from the filename, so a renamed file cannot mislabel the source."""
    raw = pd.read_csv(path)
    # PAIMANA project codes are numeric, so pandas types them int64 and a URL
    # path parameter ("/api/project/619103") would never match. Ids are keys,
    # not numbers - keep them as strings everywhere.
    raw["entity_id"] = raw["entity_id"].astype(str)
    return (_load_real(raw, path) if is_real(raw) else _load_synth(raw, path))


def build_features(panel: pd.DataFrame, meta: PanelMeta) -> pd.DataFrame:
    """Point-in-time feature matrix. Row order is the caller's row order -
    this function must not re-sort, or predictions get attached to the wrong
    projects."""
    X = panel[[c for c in meta.numeric if c in panel.columns]].copy()
    leaked = [c for c in X.columns if c in LABEL_COLS]
    assert not leaked, f"label column leaked into features: {leaked}"
    for c in meta.categorical:
        if c in panel.columns:
            d = pd.get_dummies(panel[c].fillna("unknown"), prefix=c[:3])
            X = pd.concat([X.reset_index(drop=True), d.reset_index(drop=True)],
                          axis=1)
    # LightGBM rejects JSON-special characters, and ministry names carry & and ,
    X.columns = [re.sub(r"[^0-9A-Za-z_]", "_", str(c)) for c in X.columns]
    X = X.loc[:, ~X.columns.duplicated()]
    X.index = panel.index
    return X.astype(float).fillna(-1.0)


def drift_magnitude_quantiles(train: pd.DataFrame) -> dict | None:
    """How far dates actually move, measured on the TRAINING window only.

    Replaces the synthetic panel's hardcoded p*12*0.6 formula with the
    observed distribution. Returns None when the panel cannot supply it.
    """
    if "drift_next_months" not in train.columns:
        return None
    moved = train.loc[train["target"] == 1, "drift_next_months"].dropna()
    moved = moved[moved > 0]
    if len(moved) < 30:
        return None
    return {
        "n_observed_moves": int(len(moved)),
        "p50_months": float(moved.quantile(0.50)),
        "p90_months": float(moved.quantile(0.90)),
        "mean_months": float(moved.mean()),
        "measured_on": "training window only, rows where the date did move",
    }
