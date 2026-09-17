#!/usr/bin/env python3
"""Operational evaluation of the slip model on the REAL PAIMANA panel.

Outputs
    results/paimana/predictions_slip.csv      - per-(project, month) P(slip) for the
                                              most recent month in the panel
    results/paimana/precision_at_k.json      - precision@k, recall@k, lift@k
                                              at a stated inspection budget (projects
                                              per month)
    results/paimana/reliability_slip.json     - 10-bin calibration (reliability table)
                                              for the most recent month

The brief's rubric G6 demands:
    "if you inspect the top 50 projects per month, how many of the
    roughly 380 that will slip do you catch, versus the roughly 10
    you would catch inspecting 50 at random?"

We compute exactly that, plus the reliability table that justifies
"70% slip risk means 70%".

Usage:
    python scripts/eval_slip.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

try:
    from lightgbm import LGBMClassifier
except ImportError:  # pragma: no cover
    LGBMClassifier = None

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "results" / "paimana" / "panel.csv"
OUT_PRED = ROOT / "results" / "paimana" / "predictions_slip.csv"
OUT_PRECISION = ROOT / "results" / "paimana" / "precision_at_k.json"
OUT_RELIABILITY = ROOT / "results" / "paimana" / "reliability_slip.json"
OUT_SHAP = ROOT / "results" / "paimana" / "shap_slip.json"
SHAP_TOP_N = 200          # projects, ranked by risk, whose attributions we store
SHAP_FEATURES = 8         # features kept per project
SEED = 42

TARGET = "slip_next"
INSPECTION_BUDGETS = [10, 25, 50, 100, 250]

NUMERIC_FEATURES = [
    "original_cost_cr", "revised_cost_cr", "cumulative_expenditure_cr",
    "physical_progress_pct", "months_since_approval", "cumulative_drift_months",
    "months_to_target", "months_past_original", "expenditure_ratio",
    "cost_overrun_ratio", "exp_progress_divergence", "drift_change_1m",
    "date_revised_this_month", "revisions_so_far", "cost_revised_this_month",
    "months_observed", "months_since_last_revision",
]
LABEL_COLS = {"slip_next", "cost_up_next", "delta_cost_ratio_next",
              "label_horizon_months"}


def features(df: pd.DataFrame) -> pd.DataFrame:
    X = df[[c for c in NUMERIC_FEATURES if c in df.columns]].copy()
    leaked = [c for c in X.columns if c in LABEL_COLS]
    assert not leaked, f"label column leaked into features: {leaked}"
    if "ministry" in df.columns:
        d = pd.get_dummies(df["ministry"].fillna("unknown"), prefix="min")
        X = pd.concat([X.reset_index(drop=True), d.reset_index(drop=True)], axis=1)
    import re
    X.columns = [re.sub(r"[^0-9A-Za-z_]", "_", str(c)) for c in X.columns]
    X = X.loc[:, ~X.columns.duplicated()]
    return X.astype(float).fillna(-1.0)


def pr_auc(y, p):
    return float("nan") if len(set(y)) < 2 else float(average_precision_score(y, p))


def brier(y, p):
    return float(brier_score_loss(y, np.clip(p, 0, 1)))


def fit_lightgbm(X_tr, y_tr):
    clf = LGBMClassifier(n_estimators=200, num_leaves=15, learning_rate=0.05,
                         min_child_samples=1, random_state=SEED, verbose=-1)
    clf.fit(X_tr, y_tr)
    return clf


def reliability_table(y_true, y_score, n_bins: int = 10) -> pd.DataFrame:
    """10-bin calibration: predicted-prob quantile bin -> observed frequency."""
    df = pd.DataFrame({"y": y_true, "p": y_score})
    df["bin"] = pd.qcut(df["p"], q=n_bins, duplicates="drop")
    out = (df.groupby("bin", observed=True)
             .agg(n=("y", "size"),
                  mean_p=("p", "mean"),
                  mean_y=("y", "mean"))
             .reset_index(drop=True))
    return out


def main() -> int:
    if not PANEL.exists():
        sys.exit(f"{PANEL} missing. Run: python scripts/build_panel.py")
    panel = pd.read_csv(PANEL, parse_dates=["report_month"])
    panel = panel[panel[TARGET].notna()].copy()
    panel[TARGET] = panel[TARGET].astype(int)

    months = sorted(panel["report_month"].unique())
    if len(months) < 2:
        sys.exit("Need at least 2 labelled months.")
    eval_month = months[-1]
    train = panel[panel["report_month"] < eval_month].copy()
    test = panel[panel["report_month"] == eval_month].copy()
    print(f"eval month: {pd.Timestamp(eval_month).strftime('%Y-%m')}  "
          f"train n={len(train)}  test n={len(test)}  "
          f"test positives={int(test[TARGET].sum())}  "
          f"test base rate={test[TARGET].mean():.4f}")

    X_tr, X_te = features(train), features(test)
    X_te = X_te.reindex(columns=X_tr.columns, fill_value=0.0)
    y_tr = train[TARGET].to_numpy()
    y_te = test[TARGET].to_numpy()

    clf = fit_lightgbm(X_tr, y_tr)
    p_te = clf.predict_proba(X_te)[:, 1]

    # --- Predictions CSV (per-row, only the eval month) -----------------
    preds = pd.DataFrame({
        "entity_id": test["entity_id"].values,
        "report_month": test["report_month"].values,
        "ministry": test["ministry"].values,
        "sector": test["sector"].values,
        "y_true": y_te,
        "p_slip": p_te,
        "stated_doc": test["target_doc"].values,
        "original_doc": test["original_doc"].values,
    })
    preds.to_csv(OUT_PRED, index=False)
    print(f"wrote {OUT_PRED} ({len(preds)} rows)")

    # --- Precision@k --------------------------------------------------
    # Sort by predicted probability descending; precision@k = slips in top k / k.
    df_eval = preds.sort_values("p_slip", ascending=False).reset_index(drop=True)
    rows = []
    for k in INSPECTION_BUDGETS:
        top_k = df_eval.head(k)
        n_slips = int(top_k["y_true"].sum())
        baseline = float(y_te.mean())  # random-selection slip rate
        baseline_n_slips = int(round(k * baseline))
        precision = n_slips / max(k, 1)
        recall = n_slips / max(int(y_te.sum()), 1)
        lift = precision / max(baseline, 1e-9)
        rows.append({
            "k": k,
            "n_slips_caught": n_slips,
            "n_slips_at_random_k": baseline_n_slips,
            "precision_at_k": round(precision, 4),
            "recall_at_k": round(recall, 4),
            "lift_over_random": round(lift, 2),
        })
    precision_payload = {
        "eval_month": pd.Timestamp(eval_month).strftime("%Y-%m"),
        "data_source": "paimana",
        "n_test": int(len(test)),
        "test_positives": int(y_te.sum()),
        "test_base_rate": float(y_te.mean()),
        "rows": rows,
        "interpretation": (
            "If a ministry inspects `k` projects each month, our model puts "
            "`n_slips_caught` of them in the top-k list. Random inspection would "
            "catch `n_slips_at_random_k` of the same size. The `lift_over_random` "
            "shows how many times better than chance the ranked list is."
        ),
    }
    OUT_PRECISION.write_text(json.dumps(precision_payload, indent=1),
                              encoding="utf-8")
    print(f"wrote {OUT_PRECISION}")
    for r in rows:
        print(f"  k={r['k']:3d}  slips_caught={r['n_slips_caught']:3d}  "
              f"vs_random={r['n_slips_at_random_k']:3d}  "
              f"P@k={r['precision_at_k']:.3f}  R@k={r['recall_at_k']:.3f}  "
              f"lift={r['lift_over_random']}x")

    # --- Reliability table (10-bin calibration) -----------------------
    rel = reliability_table(y_te, p_te, n_bins=10)
    rel_payload = {
        "eval_month": pd.Timestamp(eval_month).strftime("%Y-%m"),
        "data_source": "paimana",
        "n_test": int(len(test)),
        "pr_auc": pr_auc(y_te, p_te),
        "brier": brier(y_te, p_te),
        "bins": rel.to_dict(orient="records"),
    }
    OUT_RELIABILITY.write_text(json.dumps(rel_payload, indent=1),
                                encoding="utf-8")
    print(f"wrote {OUT_RELIABILITY}")

    # --- SHAP attributions for the ranked list -------------------------
    # Exact contributions from the fitted trees, for the same model that
    # produced p_slip above. Written to disk so the demo pages render a
    # checked-in artefact instead of retraining and possibly disagreeing
    # with the numbers on the watchlist.
    try:
        import shap
    except ImportError:
        print("shap not installed - skipping shap_slip.json")
        return 0

    explainer = shap.TreeExplainer(clf)
    order = np.argsort(-p_te)[:SHAP_TOP_N]
    X_top = X_te.iloc[order]
    arr = np.array(explainer.shap_values(X_top))
    if arr.ndim == 3:                       # (rows, features, classes)
        arr = arr[:, :, -1] if arr.shape[-1] <= 2 else arr[-1]
    cols = list(X_te.columns)
    ids = test["entity_id"].to_numpy()[order]
    shap_rows = []
    for i, eid in enumerate(ids):
        vals = np.asarray(arr[i]).reshape(-1)[:len(cols)]
        raw = X_top.iloc[i].to_numpy()
        trio = sorted(zip(cols, vals, raw), key=lambda t: -abs(float(t[1])))
        shap_rows.append({
            "entity_id": str(eid),
            "p_slip": round(float(p_te[order[i]]), 4),
            "contributions": [
                {"feature": c.replace("_", " "),
                 "value": round(float(v), 4),
                 "shap": round(float(s), 4),
                 "direction": "raises risk" if float(s) > 0 else "lowers risk"}
                for c, s, v in trio[:SHAP_FEATURES]],
        })
    OUT_SHAP.write_text(json.dumps({
        "eval_month": pd.Timestamp(eval_month).strftime("%Y-%m"),
        "data_source": "paimana",
        "model": "lightgbm, same fit as predictions_slip.csv",
        "explainer": "shap.TreeExplainer - exact values, not a sampling approximation",
        "n_projects": len(shap_rows),
        "features_per_project": SHAP_FEATURES,
        "projects": shap_rows,
        "generated_by": "python scripts/eval_slip.py",
    }, indent=1), encoding="utf-8")
    print(f"wrote {OUT_SHAP} ({len(shap_rows)} projects)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())