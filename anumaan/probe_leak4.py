"""Reproduce the 34-features + __leak__ case from the actual pipeline."""
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

print(f"X_tr.shape: {X_tr.shape}, dtypes: {X_tr.dtypes.value_counts().to_dict()}")
print(f"X_tr.head(2):\n{X_tr.head(2)}")
print(f"y_tr dtype: {y_tr.dtype}, sum={y_tr.sum()}, n={len(y_tr)}")

# Reproduce exactly: copy, add __leak__, fit, predict, check importance
X_tr2 = X_tr.copy()
X_te2 = X_te.copy()
X_tr2["__leak__"] = y_tr
X_te2["__leak__"] = y_te

print(f"\nAfter adding __leak__:")
print(f"  X_tr2['__leak__'] dtype: {X_tr2['__leak__'].dtype}")
print(f"  X_tr2['__leak__'] values: {X_tr2['__leak__'].unique()}")
print(f"  X_te2['__leak__'] values: {X_te2['__leak__'].unique()}")
print(f"  X_tr2 columns count: {len(X_tr2.columns)}")
print(f"  __leak__ in X_tr2: {'__leak__' in X_tr2.columns}")
print(f"  X_tr2.isna().sum().sum() = {X_tr2.isna().sum().sum()}")

clf = LGBMClassifier(n_estimators=200, num_leaves=15, learning_rate=0.05,
                     random_state=tc.SEED, verbose=-1)
clf.fit(X_tr2, y_tr)
p = clf.predict_proba(X_te2)[:, 1]
auc = average_precision_score(y_te, p)
imp = dict(zip(X_tr2.columns, clf.feature_importances_))
print(f"\nResult: PR-AUC = {auc:.4f}, importance['__leak__'] = {imp.get('__leak__')}")

# Inspect the trees
trees = clf.booster_.dump_model()
n_trees_using_leak = 0
for tree in trees["tree_info"]:
    splits = tree.get("split_feature")
    if isinstance(splits, str) and "__leak__" in splits:
        n_trees_using_leak += 1
    elif isinstance(splits, int):
        feat_name = trees["feature_names"][splits] if splits < len(trees["feature_names"]) else "?"
        if feat_name == "__leak__":
            n_trees_using_leak += 1
    elif isinstance(splits, list):
        for s in splits:
            if isinstance(s, str) and s == "__leak__":
                n_trees_using_leak += 1
            elif isinstance(s, int):
                feat_name = trees["feature_names"][s] if s < len(trees["feature_names"]) else "?"
                if feat_name == "__leak__":
                    n_trees_using_leak += 1
print(f"Trees using __leak__: {n_trees_using_leak} / {len(trees['tree_info'])}")

# Check what type 'split_feature' is
print(f"\nFirst tree structure:")
first_tree = trees["tree_info"][0]
for k, v in first_tree.items():
    if k != "tree_structure":
        print(f"  {k}: {repr(v)[:200]}")