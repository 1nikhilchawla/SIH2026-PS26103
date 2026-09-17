#!/usr/bin/env python3
"""The test that protects every claim you will make in front of judges.

Idea: if the model is learning real signal, destroying the time ordering must
destroy the score. If a shuffled-time model still scores well, a feature is
carrying information from the future.

Use it as a pytest, wired to your own training function:

    from scripts.leakage_test import shuffle_time_check
    def test_no_leakage(panel, train_and_score):
        drop = shuffle_time_check(panel, train_and_score, time_col="report_month")
        assert drop > 0.15, f"suspiciously small drop ({drop:.3f}) - check for leakage"
"""
from __future__ import annotations

import numpy as np


def shuffle_time_check(panel, train_and_score, time_col: str = "report_month",
                       seed: int = 0) -> float:
    """Return (real score - shuffled score). A healthy pipeline gives a big positive.

    `train_and_score(df)` must train on the earlier part of `df` and return a single
    score (AUC, say) on the later part, using only `time_col` for the split.
    """
    rng = np.random.default_rng(seed)
    real = train_and_score(panel)

    shuffled = panel.copy()
    shuffled[time_col] = rng.permutation(shuffled[time_col].values)
    fake = train_and_score(shuffled)

    print(f"real={real:.4f}  time-shuffled={fake:.4f}  drop={real - fake:.4f}")
    return real - fake


def assert_feature_asof(features_df, asof_col: str = "asof_month",
                        source_col: str = "source_month") -> None:
    """Every feature value must come from a month at or before its as-of month."""
    bad = features_df[features_df[source_col] > features_df[asof_col]]
    if len(bad):
        raise AssertionError(
            f"{len(bad)} feature rows use data from the future. "
            f"First offender:\n{bad.head(1).to_dict('records')}"
        )
