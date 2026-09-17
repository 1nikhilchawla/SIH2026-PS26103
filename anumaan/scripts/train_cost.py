#!/usr/bin/env python3
"""Cost-overrun model on the REAL PAIMANA panel (PS 26103, outcome a-i).

Target
    cost_up_next = 1 if the project's revised cost in the NEXT monthly report
    is more than 0.5% above the revised cost stated in THIS report.
    It is a forecast of the next upward cost revision, not a restatement of
    the current overrun.

The leak this target invites, and how it is avoided
    revised_cost appears on both sides: it is a feature at month M and it is
    inside the label at M+1. That is legitimate only because the label is a
    strictly FUTURE comparison the features cannot see. To keep it that way:
      * every column produced by build_panel.py that looks forward
        (cost_up_next, delta_cost_ratio_next, slip_next, label_horizon_months)
        is dropped from the feature matrix by name, and
      * the shuffled-label control below must collapse towards the base rate.
        If a future value had leaked into a feature, that control would stay high.

Splits
    Walk-forward by report month. Train on months < T, test on T. No random
    split, no shuffling, and the scaler is fitted inside the pipeline on the
    training window only.

Usage:
    python scripts/train_cost.py
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
OUT = ROOT / "results" / "paimana" / "metrics_cost.json"
SEED = 42

TARGET = "cost_up_next"
LABEL_COLS = ["cost_up_next", "delta_cost_ratio_next", "slip_next",
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
    # LightGBM refuses feature names containing JSON-special characters, and
    # ministry names carry "&" and ",". Sanitise, keeping names unique.
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


def main() -> int:
    df = load()
    months = sorted(df["report_month"].unique())
    print(f"labelled rows: {len(df)}  months with labels: "
          f"{[pd.Timestamp(m).strftime('%Y-%m') for m in months]}  "
          f"base rate: {df[TARGET].mean():.4f}")
    if len(months) < 2:
        raise SystemExit("Need at least two labelled months for walk-forward.")

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
            "cost_revised_this_month": te["cost_revised_this_month"].fillna(0).to_numpy(float),
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

        rng = np.random.default_rng(SEED)
        y_shuf = rng.permutation(y_tr)
        shuffled = fit_predict(X_tr, y_shuf, X_te).get("lightgbm")
        X_tr2, X_te2 = X_tr.copy(), X_te.copy()
        X_tr2["__leak__"] = y_tr
        X_te2["__leak__"] = y_te
        # Planted-leak uses min_child_samples=1 so the split on __leak__ is
        # not blocked by the default min_child_samples=20 when the positive
        # class is rare (4 train positives in 3776 rows; a perfect split
        # on __leak__ would put the 4 positives in one leaf, violating 20).
        planted_lgbm = LGBMClassifier(
            n_estimators=200, num_leaves=15, learning_rate=0.05,
            min_child_samples=1,
            random_state=SEED, verbose=-1,
        )
        planted_lgbm.fit(X_tr2, y_tr)
        planted = planted_lgbm.predict_proba(X_te2)[:, 1]
        planted_imp = dict(zip(X_tr2.columns,
                                planted_lgbm.feature_importances_))
        real_imp = (None if fold["models"].get("lightgbm") is None
                    else planted_imp)  # filled below
        real_pr = fold["models"].get("lightgbm", {}).get("pr_auc")
        shuffled_pr = (None if shuffled is None else pr_auc(y_te, shuffled))
        planted_pr = (None if planted is None else pr_auc(y_te, planted))
        # Hard assertions.
        # 1. If planted leak does not jump far above the real score, the
        #    control is broken and downstream metrics are untrustworthy.
        if (real_pr is not None and planted_pr is not None
                and planted_pr <= 2 * max(real_pr, 1e-6)):
            raise SystemExit(
                f"LEAKAGE GUARD FAILED on fold {label}: planted PR-AUC "
                f"({planted_pr:.4f}) is not > 2x real ({real_pr:.4f}). "
                f"The planted-leak control is broken - fix before trusting "
                f"any number on this fold."
            )
        # 2. Shuffled labels must collapse to the test base rate. If
        #    shuffled PR-AUC >> base rate, a feature is reading the
        #    future. We use a generous 4x absolute tolerance on the base
        #    rate for folds with very few positives.
        base = float(y_te.mean())
        if (shuffled_pr is not None
                and shuffled_pr > max(0.02, 4 * max(base, 1e-6))):
            raise SystemExit(
                f"LEAKAGE GUARD FAILED on fold {label}: shuffled-label "
                f"PR-AUC ({shuffled_pr:.4f}) far exceeds test base rate "
                f"({base:.4f}). A feature sees the future."
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
            print(f"    {name:26s} pr_auc={sc['pr_auc']:.4f} brier={sc['brier']:.4f}")
        lk = fold["leakage_check"]
        print(f"    leakage: real={lk['real_pr_auc']} "
              f"shuffled={lk['shuffled_labels_pr_auc']} "
              f"planted={lk['with_planted_leak_pr_auc']}")

    if not folds:
        raise SystemExit("No usable walk-forward fold. Panel too short.")

    prov = json.loads((ROOT / "results/paimana/panel_provenance.json").read_text(encoding="utf-8"))
    payload = {
        "target": TARGET,
        "target_definition": ("1 if the revised cost in the next monthly report exceeds "
                              "this month's revised cost by more than 0.5%"),
        "what_it_is_not": ("not a prediction of the final cost, not the current overrun "
                           "ratio restated, and not defined where the next report is missing"),
        "data_source": "paimana",
        "panel_file": "results/paimana/panel.csv",
        "n_projects": prov["n_projects"], "n_months": prov["n_months"],
        "panel_span": prov["panel_span"],
        "labelled_rows": int(len(df)), "overall_base_rate": float(df[TARGET].mean()),
        "splits": "walk-forward by report month; no random split",
        "folds": folds,
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": "python scripts/train_cost.py",
    }
    OUT.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
