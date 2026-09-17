"""Verify the min_data_in_leaf hypothesis for the planted-leak control."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import average_precision_score

ROOT = Path("C:/Users/Asus/OneDrive/Desktop/SIH/anumaan")
sys.path.insert(0, str(ROOT))

import importlib.util
spec = importlib.util.spec_from_file_location("tc",
                                              ROOT / "scripts/train_cost.py")
tc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tc)

df = tc.load()
months = sorted(df["report_month"].unique())
i = len(months) - 1
tr = df[df["report_month"] < months[i]]
te = df[df["report_month"] == months[i]]
X_tr, X_te = tc.features(tr), tc.features(te)
X_te = X_te.reindex(columns=X_tr.columns, fill_value=0.0)
y_tr, y_te = tr[tc.TARGET].to_numpy(), te[tc.TARGET].to_numpy()

X_tr2 = X_tr.copy()
X_te2 = X_te.copy()
X_tr2["__leak__"] = y_tr
X_te2["__leak__"] = y_te

# Test with min_data_in_leaf=1 (allows small leaves)
clf = LGBMClassifier(n_estimators=200, num_leaves=15, learning_rate=0.05,
                     min_data_in_leaf=1,
                     random_state=tc.SEED, verbose=-1)
clf.fit(X_tr2, y_tr)
p = clf.predict_proba(X_te2)[:, 1]
auc = average_precision_score(y_te, p)
imp = dict(zip(X_tr2.columns, clf.feature_importances_))
print(f"With min_data_in_leaf=1:")
print(f"  PR-AUC = {auc:.4f}  importance['__leak__'] = {imp.get('__leak__')}")
trees = clf.booster_.dump_model()
n_use = sum(1 for t in trees["tree_info"]
            if "__leak__" in str(t.get("split_feature", "")))
print(f"  Trees using __leak__: {n_use} / {len(trees['tree_info'])}")

# Test with min_data_in_leaf=2
clf2 = LGBMClassifier(n_estimators=200, num_leaves=15, learning_rate=0.05,
                      min_data_in_leaf=2,
                      random_state=tc.SEED, verbose=-1)
clf2.fit(X_tr2, y_tr)
p2 = clf2.predict_proba(X_te2)[:, 1]
auc2 = average_precision_score(y_te, p2)
imp2 = dict(zip(X_tr2.columns, clf2.feature_importances_))
print(f"\nWith min_data_in_leaf=2:")
print(f"  PR-AUC = {auc2:.4f}  importance['__leak__'] = {imp2.get('__leak__')}")
trees2 = clf2.booster_.dump_model()
n_use2 = sum(1 for t in trees2["tree_info"]
             if "__leak__" in str(t.get("split_feature", "")))
print(f"  Trees using __leak__: {n_use2} / {len(trees2['tree_info'])}")

# Confirm: train has very few positives
print(f"\ny_tr.sum() = {y_tr.sum()}, len(y_tr) = {len(y_tr)}")
print(f"__leak__=1 row count = {(X_tr2['__leak__']==1).sum()}")

# Test with min_child_samples=1 too
clf3 = LGBMClassifier(n_estimators=200, num_leaves=15, learning_rate=0.05,
                      min_child_samples=1,
                      random_state=tc.SEED, verbose=-1)
clf3.fit(X_tr2, y_tr)
p3 = clf3.predict_proba(X_te2)[:, 1]
auc3 = average_precision_score(y_te, p3)
imp3 = dict(zip(X_tr2.columns, clf3.feature_importances_))
print(f"\nWith min_child_samples=1:")
print(f"  PR-AUC = {auc3:.4f}  importance['__leak__'] = {imp3.get('__leak__')}")