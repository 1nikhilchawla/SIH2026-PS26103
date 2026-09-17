#!/usr/bin/env python3
"""Build the real PAIMANA project x month panel.

Input:  data/interim/paimana/*.rows.json, but ONLY reports whose
        reconciliation passed. A report that did not reconcile against its
        own printed totals does not enter the panel.
Output: results/paimana/panel.csv + panel_provenance.json

Point-in-time rule (Law 2): every feature on the row for month M is computed
from that row and EARLIER rows of the same project only. The label columns
(slip_next, cost_up_next, delta_cost_ratio_next) are the only columns that
look forward, they are named as labels, and they are never fed back in as
features.

Horizon: labels compare month M against the NEXT CONSECUTIVE report month
(gap of exactly 1 month). Where the corpus has a gap - e.g. Nov 2025 to
Apr 2026, because the intervening reports did not reconcile - the label is
left undefined rather than silently stretched across the hole.

Usage:
    python scripts/build_panel.py
    python scripts/build_panel.py --include-unreconciled   (diagnostics only)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INTERIM = ROOT / "data" / "interim" / "paimana"
OUT = ROOT / "results" / "paimana"
COST_TOL = 0.005          # 0.5% - below this a cost change is rounding, not a revision


def _months_between(a, b):
    """Whole months from a to b; both timestamps or NaT."""
    if pd.isna(a) or pd.isna(b):
        return None
    return (b.year - a.year) * 12 + (b.month - a.month)


def load_rows(include_unreconciled: bool) -> tuple[pd.DataFrame, list[dict]]:
    frames, sources = [], []
    for f in sorted(INTERIM.glob("*.rows.json")):
        blob = json.loads(f.read_text(encoding="utf-8"))
        ok = blob.get("reconciliation", {}).get("ok", False)
        if not ok and not include_unreconciled:
            continue
        month = (blob.get("summary") or {}).get("report_month")
        if not month:
            print(f"  SKIP {f.name}: no report_month in summary (re-parse needed)")
            continue
        df = pd.DataFrame(blob["rows"])
        if df.empty:
            continue
        df["report_month"] = month
        df["source_report"] = blob["file"]
        frames.append(df)
        sources.append({"file": blob["file"], "report_month": month,
                        "rows": len(df), "reconciled": ok,
                        "summary_projects": (blob.get("summary") or {}).get("projects_on_monitor")})
    if not frames:
        raise SystemExit("No reconciled reports with a report_month found. "
                         "Run: python scripts/parse_paimana.py --all")
    return pd.concat(frames, ignore_index=True), sources


def build(df: pd.DataFrame) -> pd.DataFrame:
    # --- identity ---------------------------------------------------------
    # project_code is the portal's own key; fall back to ministry+name so a
    # missing code cannot collapse two projects into one entity.
    code = df["project_code"].fillna("").astype(str).str.strip()
    fallback = (df["ministry"].fillna("?").astype(str) + "::"
                + df["project_name"].fillna("?").astype(str).str.slice(0, 80))
    df["entity_id"] = code.where(code != "", "NAME:" + fallback)

    for c in ("report_month", "approval_month", "start_month",
              "original_doc", "target_doc"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
        if df[c].isna().any():
            print(f"  note: {c} null on {int(df[c].isna().sum())} rows "
                  "(kept, not imputed)")

    df = df.sort_values(["entity_id", "report_month"]).reset_index(drop=True)

    dup = int(df.duplicated(["entity_id", "report_month"]).sum())
    if dup:
        print(f"  WARNING: {dup} duplicate (entity_id, report_month) rows dropped")
        df = df.drop_duplicates(["entity_id", "report_month"], keep="first")
        df = df.reset_index(drop=True)

    # --- point-in-time features (this row + earlier rows only) ------------
    df["months_since_approval"] = [
        _months_between(a, m) for a, m in zip(df["approval_month"], df["report_month"])]
    df["cumulative_drift_months"] = [
        _months_between(o, t) for o, t in zip(df["original_doc"], df["target_doc"])]
    df["months_to_target"] = [
        _months_between(m, t) for m, t in zip(df["report_month"], df["target_doc"])]
    df["months_past_original"] = [
        (max(0, v) if v is not None else None)
        for v in (_months_between(o, m)
                  for o, m in zip(df["original_doc"], df["report_month"]))]

    oc = df["original_cost_cr"].replace(0, pd.NA)
    df["expenditure_ratio"] = df["cumulative_expenditure_cr"] / oc
    df["cost_overrun_ratio"] = df["revised_cost_cr"] / oc
    df["exp_progress_divergence"] = (df["expenditure_ratio"]
                                     - df["physical_progress_pct"] / 100.0)

    g = df.groupby("entity_id", sort=False)
    prev_target = g["target_doc"].shift(1)
    prev_drift = g["cumulative_drift_months"].shift(1)
    prev_revised = g["revised_cost_cr"].shift(1)

    df["drift_change_1m"] = df["cumulative_drift_months"] - prev_drift
    df["date_revised_this_month"] = (
        prev_target.notna() & (df["target_doc"] != prev_target)).astype(int)
    df["revisions_so_far"] = g["date_revised_this_month"].cumsum()
    df["cost_revised_this_month"] = (
        prev_revised.notna()
        & ((df["revised_cost_cr"] - prev_revised).abs()
           > (prev_revised.abs() * COST_TOL))).astype(int)
    df["months_observed"] = g.cumcount() + 1

    # months since last revision, expanding, no future information
    since, counter = [], {}
    for eid, rev in zip(df["entity_id"], df["date_revised_this_month"]):
        c = counter.get(eid)
        if c is None:
            since.append(0)
            counter[eid] = 0
        else:
            counter[eid] = 0 if rev else c + 1
            since.append(counter[eid])
    df["months_since_last_revision"] = since

    # --- labels (the ONLY forward-looking columns) ------------------------
    nxt_month = g["report_month"].shift(-1)
    nxt_target = g["target_doc"].shift(-1)
    nxt_revised = g["revised_cost_cr"].shift(-1)
    gap = [(None if pd.isna(a) or pd.isna(b) else _months_between(a, b))
           for a, b in zip(df["report_month"], nxt_month)]
    df["label_horizon_months"] = gap
    consecutive = pd.Series([x == 1 for x in gap], index=df.index)

    df["slip_next"] = pd.NA
    valid_slip = consecutive & df["target_doc"].notna() & nxt_target.notna()
    df.loc[valid_slip, "slip_next"] = (
        nxt_target[valid_slip] > df.loc[valid_slip, "target_doc"]).astype(int)

    df["cost_up_next"] = pd.NA
    df["delta_cost_ratio_next"] = pd.NA
    valid_cost = consecutive & df["revised_cost_cr"].notna() & nxt_revised.notna()
    denom = df.loc[valid_cost, "revised_cost_cr"].abs().replace(0, pd.NA)
    rel = (nxt_revised[valid_cost] - df.loc[valid_cost, "revised_cost_cr"]) / denom
    df.loc[valid_cost, "cost_up_next"] = (rel > COST_TOL).astype(int)
    df.loc[valid_cost, "delta_cost_ratio_next"] = rel

    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-unreconciled", action="store_true",
                    help="diagnostics only; such rows must never be modelled")
    args = ap.parse_args()

    raw, sources = load_rows(args.include_unreconciled)
    print(f"loaded {len(raw)} rows from {len(sources)} reports")
    panel = build(raw)

    assert not panel.duplicated(["entity_id", "report_month"]).any(), \
        "duplicate (entity_id, report_month) survived - panel is not a panel"

    OUT.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUT / "panel.csv", index=False)

    months = sorted(panel["report_month"].dt.strftime("%Y-%m").unique())
    prov = {
        "data_source": "paimana",
        "n_rows": int(len(panel)),
        "n_projects": int(panel["entity_id"].nunique()),
        "n_months": len(months),
        "panel_span": f"{months[0]} to {months[-1]}",
        "months": months,
        "source_reports": sources,
        "labelled_rows_slip_next": int(panel["slip_next"].notna().sum()),
        "labelled_rows_cost_up_next": int(panel["cost_up_next"].notna().sum()),
        "slip_next_base_rate": (float(panel["slip_next"].dropna().mean())
                                if panel["slip_next"].notna().any() else None),
        "cost_up_next_base_rate": (float(panel["cost_up_next"].dropna().mean())
                                   if panel["cost_up_next"].notna().any() else None),
        "label_horizon_months": 1,
        "include_unreconciled": bool(args.include_unreconciled),
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": "python scripts/build_panel.py",
    }
    (OUT / "panel_provenance.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")

    print(f"\npanel rows      : {prov['n_rows']}")
    print(f"projects        : {prov['n_projects']}")
    print(f"months          : {prov['n_months']}  ({prov['panel_span']})")
    print(f"  {months}")
    print(f"slip_next labels: {prov['labelled_rows_slip_next']} "
          f"(base rate {prov['slip_next_base_rate']})")
    print(f"cost_up_next    : {prov['labelled_rows_cost_up_next']} "
          f"(base rate {prov['cost_up_next_base_rate']})")
    print(f"wrote {OUT / 'panel.csv'} and panel_provenance.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
