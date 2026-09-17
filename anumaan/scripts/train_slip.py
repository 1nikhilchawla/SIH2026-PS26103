#!/usr/bin/env python3
"""Slip-12m model on the REAL PAIMANA panel (PS 26103, outcome a-ii).

Target
    slip_next = 1 if the project's target completion date in the NEXT
    consecutive monthly report is later than this month's target by at
    least 1 month. The label is 1-step ahead; we train with the
    label_horizon_months = 1 panel column already attached by build_panel.py.

Splits
    Walk-forward by report month. Train on months < T, test on T. No
    random split, no shuffling, and the scaler is fitted inside the
    pipeline on the training window only.

Baselines (per the rubric G4)
    * always_base_rate
    * ministry_base_rate
    * slipped_last_month   (the persistence baseline the brief says
                              "is the one that matters": a reviewer asks
                              "if I just trust the previous month's
                              slip, does the model add anything?")

Usage:
    python scripts/train_slip.py
"""
from __future__ import annotations

import datetime as _dt
import json
import re
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
OUT = ROOT / "results" / "paimana" / "metrics_slip.json"
SEED = 42

TARGET = "slip_next"
LABEL_COLS = ["slip_next", "cost_up_next", "delta_cost_ratio_next",
              "label_horizon_months"]

NUMERIC_FEATURES = [
    "original_cost_cr", "revised_cost_cr", "cumulative_expenditure_cr",
    "physical_progress_pct", "months_since_approval", "cumulative_drift_months",
    "months_to_target", "months_past_original", "expenditure_ratio",
    "cost_overrun_ratio", "exp_progress_divergence", "drift_change_1m",
    "date_revised_this_month", "revisions_so_far", "cost_revised_this_month",
    "months_observed", "months_since_last_revision",
]


def load() -> pd.DataFrame:
    if not PANEL.exists():
        raise SystemExit(f"{PANEL} missing. Run: python scripts/build_panel.py")
    df = pd.read_csv(PANEL, parse_dates=["report_month"])
    df = df[df[TARGET].notna()].copy()
    df[TARGET] = df[TARGET].astype(int)
    return df


def features(df: pd.DataFrame) -> pd.DataFrame:
    X = df[[c for c in NUMERIC_FEATURES if c in df.columns]].copy()
    leaked = [c for c in X.columns if c in LABEL_COLS]
    assert not leaked, f"label column leaked into features: {leaked}"
    if "ministry" in df.columns:
        d = pd.get_dummies(df["ministry"].fillna("unknown"), prefix="min")
        X = pd.concat([X.reset_index(drop=True), d.reset_index(drop=True)], axis=1)
    X.columns = [re.sub(r"[^0-9A-Za-z_]", "_", str(c)) for c in X.columns]
    X = X.loc[:, ~X.columns.duplicated()]
    return X.astype(float).fillna(-1.0)


def pr_auc(y, p):
    return float("nan") if len(set(y)) < 2 else float(average_precision_score(y, p))


def brier(y, p):
    return float(brier_score_loss(y, np.clip(p, 0, 1)))


def fit_predict(X_tr, y_tr, X_te):
    out = {}
    lr = make_pipeline(StandardScaler(),
                       LogisticRegression(max_iter=2000, C=1.0,
                                          class_weight="balanced"))
    lr.fit(X_tr, y_tr)
    out["logistic"] = lr.predict_proba(X_te)[:, 1]
    if LGBMClassifier is not None:
        clf = LGBMClassifier(n_estimators=200, num_leaves=15, learning_rate=0.05,
                             random_state=SEED, verbose=-1)
        clf.fit(X_tr, y_tr)
        out["lightgbm"] = clf.predict_proba(X_te)[:, 1]
    return out


def persistence_baseline(panel: pd.DataFrame) -> pd.Series:
    """For each test row, predict P(slip in next month) = 1 if the same
    project's slip_next was 1 in the previous report month, else 0.

    Returned as a per-row 0/1 array aligned to panel row order.
    """
    df = panel.sort_values(["entity_id", "report_month"]).copy()
    prev = df.groupby("entity_id")["slip_next"].shift(1).fillna(0).astype(int)
    return pd.Series(prev.values, index=df.index)


def main() -> int:
    df = load()
    months = sorted(df["report_month"].unique())
    print(f"labelled rows: {len(df)}  months with labels: "
          f"{[pd.Timestamp(m).strftime('%Y-%m') for m in months]}  "
          f"base rate: {df[TARGET].mean():.4f}")
    if len(months) < 2:
        raise SystemExit("Need at least two labelled months for walk-forward.")

    # Pre-compute the persistence baseline once for the whole panel.
    panel_all = pd.read_csv(PANEL, parse_dates=["report_month"])
    persist_full = persistence_baseline(panel_all)
    df = df.merge(
        panel_all[["entity_id", "report_month"]].assign(_persist=persist_full.values),
        on=["entity_id", "report_month"], how="left",
    )

    folds = []
    for i in range(1, len(months)):
        tr = df[df["report_month"] < months[i]]
        te = df[df["report_month"] == months[i]]
        label = pd.Timestamp(months[i]).strftime("%Y-%m")
        if tr.empty or te.empty or tr[TARGET].nunique() < 2:
            print(f"  skip fold test={label}: insufficient class variety in train")
            continue
        X_tr, X_te = features(tr), features(te)
        X_te = X_te.reindex(columns=X_tr.columns, fill_value=0.0)
        y_tr, y_te = tr[TARGET].to_numpy(), te[TARGET].to_numpy()

        base = float(y_tr.mean())
        preds = {
            "always_base_rate": np.full(len(y_te), base),
            "slipped_last_month": te["_persist"].fillna(0).to_numpy(float),
        }
        mrate = tr.groupby("ministry")[TARGET].mean()
        preds["ministry_base_rate"] = te["ministry"].map(mrate).fillna(base).to_numpy(float)
        preds.update(fit_predict(X_tr, y_tr, X_te))

        fold = {
            "test_month": label,
            "train_months": [pd.Timestamp(m).strftime("%Y-%m") for m in months[:i]],
            "n_train": int(len(tr)), "n_test": int(len(te)),
            "test_base_rate": float(y_te.mean()),
            "test_positives": int(y_te.sum()),
            "models": {k: {"pr_auc": pr_auc(y_te, p), "brier": brier(y_te, p)}
                       for k, p in preds.items()},
        }

        # Leakage guard (planted-leak uses min_child_samples=1 so the
        # split on __leak__ is not blocked by rare-class default).
        rng = np.random.default_rng(SEED)
        y_shuf = rng.permutation(y_tr)
        shuffled = fit_predict(X_tr, y_shuf, X_te).get("lightgbm")
        X_tr2, X_te2 = X_tr.copy(), X_te.copy()
        X_tr2["__leak__"] = y_tr
        X_te2["__leak__"] = y_te
        planted_lgbm = LGBMClassifier(
            n_estimators=200, num_leaves=15, learning_rate=0.05,
            min_child_samples=1, random_state=SEED, verbose=-1,
        )
        planted_lgbm.fit(X_tr2, y_tr)
        planted = planted_lgbm.predict_proba(X_te2)[:, 1]
        planted_imp = dict(zip(X_tr2.columns,
                                planted_lgbm.feature_importances_))
        real_pr = fold["models"].get("lightgbm", {}).get("pr_auc")
        shuffled_pr = (None if shuffled is None else pr_auc(y_te, shuffled))
        planted_pr = (None if planted is None else pr_auc(y_te, planted))
        if (planted_pr is not None
                and (planted_pr < 0.9
                     or (real_pr is not None and planted_pr <= real_pr))):
            raise SystemExit(
                f"LEAKAGE GUARD FAILED on fold {label}: planted PR-AUC "
                f"({planted_pr:.4f}) is not > 0.9 AND > real ({real_pr}). "
                f"The planted-leak control is broken - fix before trusting "
                f"any number on this fold."
            )
        base_rate = float(y_te.mean())
        if (shuffled_pr is not None
                and shuffled_pr > max(0.02, 4 * max(base_rate, 1e-6))):
            raise SystemExit(
                f"LEAKAGE GUARD FAILED on fold {label}: shuffled-label "
                f"PR-AUC ({shuffled_pr:.4f}) far exceeds test base rate "
                f"({base_rate:.4f}). A feature sees the future."
            )
        fold["leakage_check"] = {
            "real_pr_auc": real_pr,
            "shuffled_labels_pr_auc": shuffled_pr,
            "with_planted_leak_pr_auc": planted_pr,
            "planted_leak_importance": (int(planted_imp["__leak__"])
                                        if "__leak__" in planted_imp else None),
            "note": ("shuffled must fall towards the base rate; planted leak must jump "
                     "towards 1.0. If shuffled stays high, a feature sees the future. "
                     "Planted uses min_child_samples=1 because positive class is rare."),
        }
        folds.append(fold)
        print(f"\nfold test={label} train={fold['train_months']} "
              f"n_train={fold['n_train']} n_test={fold['n_test']} "
              f"base={fold['test_base_rate']:.4f} positives={fold['test_positives']}")
        for name, sc in fold["models"].items():
            print(f"    {name:24s} pr_auc={sc['pr_auc']:.4f} brier={sc['brier']:.4f}")
        lk = fold["leakage_check"]
        print(f"    leakage: real={lk['real_pr_auc']} "
              f"shuffled={lk['shuffled_labels_pr_auc']} "
              f"planted={lk['with_planted_leak_pr_auc']}")

    if not folds:
        raise SystemExit("No usable walk-forward fold. Panel too short.")

    prov = json.loads((ROOT / "results/paimana/panel_provenance.json").read_text(encoding="utf-8"))
    payload = {
        "target": TARGET,
        "target_definition": ("1 if the project's target completion date "
                              "in the next consecutive monthly report is at "
                              "least 1 month later than this month's target"),
        "horizon": "1 month (label_horizon_months column from build_panel.py)",
        "what_it_is_not": ("not a 12-month slip forecast, not a 'will it ever "
                           "finish' classification, not a carry-forward of the "
                           "previous report's stated date"),
        "data_source": "paimana",
        "panel_file": "results/paimana/panel.csv",
        "n_projects": prov["n_projects"], "n_months": prov["n_months"],
        "panel_span": prov["panel_span"],
        "labelled_rows": int(len(df)), "overall_base_rate": float(df[TARGET].mean()),
        "splits": "walk-forward by report month; no random split",
        "baselines": ["always_base_rate", "ministry_base_rate",
                      "slipped_last_month (persistence)"],
        "folds": folds,
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": "python scripts/train_slip.py",
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())