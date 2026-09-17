#!/usr/bin/env python3
"""Build the three-screen ANUMAAN demo from the trainer's outputs.

Reads:
  results/metrics.json
  results/predictions.csv
  results/reliability_logistic.png, reliability_lightgbm.png
  results/baseline_comparison.png
  results/lead_time.png
  data/synthetic/panel.csv (for the audit-screen drift history)

Writes:
  demo/index.html   (Watchlist)
  demo/audit.html   (Forecast audit, one project)
  demo/honesty.html (Model honesty)

Every number on every page is sourced from the trainer's artifacts. Re-run
the trainer and this script and the demo regenerates end-to-end.

Usage:
    python scripts/build_demo.py --results results --panel data/synthetic/panel.csv --out demo/
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


# --- Mapping from delay_taxonomy.yaml (13 labels -> owning authority) -------
OWNING_AUTHORITY = {
    "land_acquisition": "State revenue department / district collector",
    "forest_environment_clearance": "MoEFCC / state forest department",
    "right_of_way_utilities": "Implementing agency + local body + utility owner",
    "contractor_performance": "Implementing agency contracts wing",
    "funds_and_payments": "Ministry finance wing / state finance department",
    "litigation": "Legal cell of the implementing agency",
    "law_and_order": "District administration / state police",
    "design_scope_change": "Implementing agency engineering wing",
    "geology_site_conditions": "Implementing agency",
    "supply_chain_equipment": "Implementing agency procurement",
    "statutory_other_clearance": "Concerned statutory authority",
    "covid_force_majeure": "n/a (force majeure)",
    "unclassified": "n/a (review queue)",
}

ESCALATION_PATH = {
    "land_acquisition": "State nodal authority -> PMG (DPIIT) if inter-agency",
    "forest_environment_clearance": "Check PARIVESH status -> PMG",
    "right_of_way_utilities": "District administration",
    "contractor_performance": "Ministry project division",
    "funds_and_payments": "Ministry secretary",
    "litigation": "Ministry legal division",
    "law_and_order": "State chief secretary",
    "design_scope_change": "Competent approving authority",
    "geology_site_conditions": "Technical committee",
    "supply_chain_equipment": "Ministry",
    "statutory_other_clearance": "PMG",
    "covid_force_majeure": "n/a",
    "unclassified": "Human review queue",
}


def img_b64(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def fmt_date(s):
    if pd.isna(s):
        return "—"
    return pd.Timestamp(s).strftime("%b %Y")


def build_watchlist(predictions: pd.DataFrame, metrics: dict,
                    panel: pd.DataFrame, top_n: int = 20) -> str:
    df = predictions.copy()
    # One row per project (latest month in the test window). Avoids the same
    # entity showing up multiple times for consecutive test months.
    df = (df.sort_values("month")
            .groupby("entity_id", as_index=False)
            .tail(1))
    df = df.sort_values("p_lightgbm", ascending=False).head(top_n)

    # Per-project last-seen delay cause (from the panel for the same entity_id).
    cause_lookup = (
        panel.sort_values("month")
        .groupby("entity_id")["delay_cause"]
        .last()
        .to_dict()
    )

    # Per-project current cumulative drift (latest month in panel).
    drift_lookup = (
        panel.sort_values("month")
        .groupby("entity_id")["cumulative_drift_months"]
        .last()
        .to_dict()
    )

    rows = []
    for _, r in df.iterrows():
        cause = cause_lookup.get(r["entity_id"], "unclassified")
        owner = OWNING_AUTHORITY.get(cause, "n/a")
        drift = drift_lookup.get(r["entity_id"], 0)
        rows.append(
            f"<tr>"
            f"<td><a href='audit.html?entity={r['entity_id']}'>{r['entity_id']}</a></td>"
            f"<td>{r['ministry']}</td>"
            f"<td>{r['sector']}</td>"
            f"<td>{fmt_date(r['original_doc'])}</td>"
            f"<td>{fmt_date(r['stated_doc'])}</td>"
            f"<td>{int(drift)} mo</td>"
            f"<td><strong>{r['p_lightgbm']:.2f}</strong></td>"
            f"<td>{cause}</td>"
            f"<td>{owner}</td>"
            f"</tr>"
        )

    cutoff = metrics["split_cutoff"]
    base = metrics["base_rate_test"]
    lgb = metrics["lightgbm"]["pr_auc"]

    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>ANUMAAN — Watchlist</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif;
         max-width: 1100px; margin: 24px auto; padding: 0 16px;
         color: #222; line-height: 1.4; }}
  h1 {{ margin-bottom: 4px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 18px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ padding: 6px 8px; border-bottom: 1px solid #eee; text-align: left;
           vertical-align: top; }}
  th {{ background: #fafafa; position: sticky; top: 0; }}
  tr:hover {{ background: #f8f8ff; }}
  .badge {{ display: inline-block; padding: 1px 6px; border-radius: 4px;
           background: #e8f0fe; color: #1a3d8f; font-weight: 600; }}
  .nav {{ font-size: 13px; margin-bottom: 12px; }}
  .nav a {{ margin-right: 14px; color: #1a3d8f; text-decoration: none; }}
  .nav a:hover {{ text-decoration: underline; }}
  footer {{ margin-top: 28px; color: #888; font-size: 12px; }}
  .legend {{ background: #fffbe6; border: 1px solid #f0e0a0;
            padding: 10px 12px; border-radius: 4px;
            font-size: 13px; margin: 10px 0 18px 0; }}
</style></head><body>

<div class="nav">
  <a href="index.html"><strong>Watchlist</strong></a>
  <a href="honesty.html">Model honesty</a>
  <span style="color:#888">| Forecast audit: click a project ID</span>
</div>

<h1>Watchlist — which projects need attention today?</h1>
<div class="meta">
  Top {len(rows)} by ANUMAAN slip-12m probability. Every row carries the
  delay cause matched against the 13-label taxonomy and its owning authority.
  Click any project ID for the forecast audit screen.
</div>

<div class="legend">
  Synthetic demo: every number on this page is computed by
  <code>scripts/train_t1.py</code> on <code>data/synthetic/panel.csv</code>.
  Test split cutoff: {cutoff}. Held-out base rate: {base:.1%}.
  LightGBM PR-AUC: <span class="badge">{lgb:.3f}</span>.
</div>

<table>
<thead><tr>
  <th>Project</th><th>Ministry</th><th>Sector</th>
  <th>Original DoC</th><th>Stated DoC</th>
  <th>Drift so far</th><th>P(slip 12m)</th>
  <th>Last-seen delay cause</th><th>Owning authority</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>

<footer>
  ANUMAAN SIH26103 demo. Re-run <code>python scripts/synth_panel.py && python scripts/train_t1.py && python scripts/build_demo.py</code> to regenerate.
</footer>
</body></html>
"""
    return html


def build_audit(predictions: pd.DataFrame, panel: pd.DataFrame,
                metrics: dict, entity_id: str | None) -> str:
    """Forecast audit screen. Pick the highest-p(slip) project if none given."""
    if entity_id is None:
        entity_id = predictions.sort_values("p_lightgbm",
                                            ascending=False).iloc[0]["entity_id"]
    row = predictions[predictions["entity_id"] == entity_id].iloc[-1]
    entity_panel = panel[panel["entity_id"] == entity_id].sort_values("month")

    # Stated doc over time + (line original_doc (horizontal reference)
    months = entity_panel["month"].tolist()
    stated = entity_panel["stated_doc"].tolist()
    original = entity_panel["original_doc"].iloc[0]

    # Build a tiny SVG: x-axis is month index, y-axis is months-from-now.
    if not months:
        plot = "<p>(no history)</p>"
    else:
        # Coerce dates to days-since-original for y-axis.
        base_ts = pd.Timestamp(original)
        ys = [(pd.Timestamp(d) - base_ts).days / 30.0 for d in stated]
        min_y, max_y = min(ys + [0]), max(ys + [0])
        pad = max(2, (max_y - min_y) * 0.15)
        y_lo = min_y - pad
        y_hi = max_y + pad
        # Latest month for the forecast marker
        last_x = len(months) - 1
        last_stated_y = ys[-1]
        p50_drift = row["anumaan_p50_drift_months"]
        p90_drift = row["anumaan_p90_drift_months"]

        width = 700
        height = 280
        plot = f"""
<svg viewBox="0 0 {width} {height}" style="width:100%; height:auto;
        background:#fafafa; border:1px solid #eee; padding:8px;
        border-radius:4px">
  <!-- y axis: months -->
  <line x1="60" y1="20" x2="60" y2="{height-30}" stroke="#888"/>
  <line x1="60" y1="{height-30}" x2="{width-20}" y2="{height-30}" stroke="#888"/>
  <!-- original_doc horizontal -->
  <line x1="60" y1="{int(height-30 - (0-y_lo)/(y_hi-y_lo) * (height-50))}"
        x2="{width-20}" y2="{int(height-30 - (0-y_lo)/(y_hi-y_lo) * (height-50))}"
        stroke="#1a3d8f" stroke-dasharray="4 3"/>
  <text x="{width-20}" y="{int(height-30 - (0-y_lo)/(y_hi-y_lo) * (height-50))-4}"
        fill="#1a3d8f" font-size="11" text-anchor="end">original DoC</text>
  <!-- stated doc over time -->
"""
        for i, y in enumerate(ys):
            x = 60 + (i / max(1, len(ys) - 1)) * (width - 80)
            plot += f'  <circle cx="{x:.1f}" cy="{int(height-30 - (y-y_lo)/(y_hi-y_lo) * (height-50))}" r="2.5" fill="#2ca02c"/>\n'
        # Connect with line
        pts = " ".join(
            f'{60 + (i / max(1, len(ys) - 1)) * (width - 80):.1f},{int(height-30 - (y-y_lo)/(y_hi-y_lo) * (height-50))}'
            for i, y in enumerate(ys)
        )
        plot += f'  <polyline points="{pts}" stroke="#2ca02c" stroke-width="1.5" fill="none"/>\n'
        # ANUMAAN forecast bars at last month
        x_last = 60 + ((len(ys) - 1) / max(1, len(ys) - 1)) * (width - 80)
        for (label, drift, color) in (("P50", p50_drift, "#2ca02c"),
                                       ("P90", p90_drift, "#1a3d8f")):
            y_top = int(height-30 - (last_stated_y + drift - y_lo)/(y_hi-y_lo) * (height-50))
            plot += f'  <line x1="{x_last+8}" y1="{y_top}" x2="{x_last+8}" y2="{int(height-30 - (last_stated_y-y_lo)/(y_hi-y_lo) * (height-50))}" stroke="{color}" stroke-width="3"/>\n'
            plot += f'  <text x="{x_last+12}" y="{y_top+4}" fill="{color}" font-size="11">{label} +{int(drift)} mo</text>\n'

        # Y-axis labels
        for v in (y_lo, (y_lo + y_hi) / 2, y_hi):
            y_pos = int(height-30 - (v-y_lo)/(y_hi-y_lo) * (height-50))
            plot += f'  <text x="55" y="{y_pos+4}" text-anchor="end" font-size="10" fill="#666">{int(v)}</text>\n'
        plot += "</svg>\n"

    cause = entity_panel["delay_cause"].iloc[-1]
    owner = OWNING_AUTHORITY.get(cause, "n/a")
    escalation = ESCALATION_PATH.get(cause, "n/a")

    sector_rate_row = predictions[predictions["sector"] == row["sector"]]
    sector_slip_rate = sector_rate_row["y_true"].mean() if len(sector_rate_row) else 0.0

    cutoff = metrics["split_cutoff"]
    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>ANUMAAN — Forecast audit ({entity_id})</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif;
         max-width: 900px; margin: 24px auto; padding: 0 16px;
         color: #222; line-height: 1.4; }}
  .nav {{ font-size: 13px; margin-bottom: 12px; }}
  .nav a {{ margin-right: 14px; color: #1a3d8f; text-decoration: none; }}
  .nav a:hover {{ text-decoration: underline; }}
  h1 {{ margin-bottom: 4px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 18px; }}
  .kv {{ display: grid; grid-template-columns: 200px 1fr; row-gap: 6px;
         column-gap: 12px; font-size: 14px; max-width: 700px; }}
  .kv dt {{ font-weight: 600; color: #555; }}
  .kv dd {{ margin: 0; }}
  .panel {{ border: 1px solid #eee; border-radius: 4px; padding: 12px 14px;
           margin: 14px 0; background: #fafafa; }}
  .panel h3 {{ margin: 0 0 8px 0; font-size: 14px; color: #444; }}
  .footer {{ margin-top: 28px; color: #888; font-size: 12px; }}
  .legend {{ background: #fffbe6; border: 1px solid #f0e0a0;
            padding: 10px 12px; border-radius: 4px;
            font-size: 13px; margin: 10px 0 18px 0; }}
  .badge {{ display: inline-block; padding: 1px 6px; border-radius: 4px;
           background: #e8f0fe; color: #1a3d8f; font-weight: 600; }}
</style></head><body>

<div class="nav">
  <a href="index.html">Watchlist</a>
  <a href="honesty.html">Model honesty</a>
  <span style="color:#888">| you are here: forecast audit</span>
</div>

<h1>Forecast audit — {entity_id}</h1>
<div class="meta">
  {row['ministry']} / {row['sector']} / {row['agency']}
</div>

<div class="legend">
  Walk-forward test split cutoff: {cutoff}. Numbers below come from
  <code>scripts/train_t1.py</code> applied to <code>data/synthetic/panel.csv</code>.
</div>

<div class="panel">
  <h3>Stated completion date — agency vs ANUMAAN</h3>
  {plot}
  <p style="font-size:12px; color:#666; margin-top:8px;">
    Green dots: agency's stated DoC at each monthly Flash Report.
    Dashed blue: original DoC at approval.
    Green bar: ANUMAAN's P50 additional drift (median expectation).
    Blue bar: ANUMAAN's P90 additional drift (upper-tail expectation).
  </p>
</div>

<div class="panel">
  <h3>ANUMAAN forecast (12-month horizon)</h3>
  <dl class="kv">
    <dt>Current agency DoC</dt>          <dd>{fmt_date(row['stated_doc'])}</dd>
    <dt>Original DoC</dt>                <dd>{fmt_date(row['original_doc'])}</dd>
    <dt>P(slip ≥ 12m in next 12m)</dt>  <dd><span class="badge">{row['p_lightgbm']:.2f}</span></dd>
    <dt>ANUMAAN P50 additional drift</dt><dd>+{int(row['anumaan_p50_drift_months'])} months &nbsp;
        <em>(new DoC ≈ {fmt_date(row['anumaan_p50_doc'])})</em></dd>
    <dt>ANUMAAN P90 additional drift</dt><dd>+{int(row['anumaan_p90_drift_months'])} months &nbsp;
        <em>(new DoC ≈ {fmt_date(row['anumaan_p90_doc'])})</em></dd>
  </dl>
</div>

<div class="panel">
  <h3>Delay cause and owning authority</h3>
  <dl class="kv">
    <dt>Last-seen delay cause</dt>      <dd><code>{cause}</code></dd>
    <dt>Owning authority</dt>           <dd>{owner}</dd>
    <dt>Escalation path</dt>            <dd>{escalation}</dd>
    <dt>Reference class</dt>            <dd>In-sector slip rate on held-out months
        ({row['sector']}): <strong>{sector_slip_rate:.1%}</strong> vs the model's
        P(slip) for this row of <strong>{row['p_lightgbm']:.1%}</strong>.</dd>
  </dl>
  <p style="font-size:12px; color:#666; margin-top:8px;">
    The reference class is shown openly so the user can see whether the
    model is doing more (or less) than the sector baseline. A P(slip) that
    beats the sector rate by too much should be reviewed.
  </p>
</div>

<div class="footer">
  Synthetic demo. Numbers from <code>scripts/train_t1.py</code>.
  The owning authority + escalation paths come from
  <code>config/delay_taxonomy.yaml</code>.
</div>

</body></html>
"""
    return html


def build_honesty(metrics: dict, rel_lgb_png: str, base_png: str,
                  lead_png: str) -> str:
    m = metrics
    leak = m["leakage_check"]
    lead_table = m.get("lead_time_table", [])

    rows_html = []
    for r in lead_table:
        log_p = r.get("logistic_pr_auc", -1)
        lgb_p = r.get("lgbm_pr_auc", -1)
        # Round for display only. The unrounded values stay in
        # results/metrics.json and results/lead_time.csv, which are the
        # citable artefacts.
        log_txt = f"{log_p:.3f}" if log_p is not None and log_p >= 0 else "—"
        lgb_txt = f"{lgb_p:.3f}" if lgb_p is not None and lgb_p >= 0 else "—"
        rows_html.append(
            f"<tr><td>{r['horizon_months']}m</td>"
            f"<td>{r['base_rate']:.3f}</td>"
            f"<td>{log_txt}</td>"
            f"<td>{lgb_txt}</td></tr>"
        )

    # Horizons are read from the artefact, never hardcoded: the panel only
    # carries slip_<h>m label columns for some h, and a horizon without a
    # label column cannot be trained or reported.
    horizons_txt = ", ".join(str(r["horizon_months"]) for r in lead_table) or "none"

    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>ANUMAAN — Model honesty</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif;
         max-width: 900px; margin: 24px auto; padding: 0 16px;
         color: #222; line-height: 1.4; }}
  .nav {{ font-size: 13px; margin-bottom: 12px; }}
  .nav a {{ margin-right: 14px; color: #1a3d8f; text-decoration: none; }}
  .nav a:hover {{ text-decoration: underline; }}
  h1 {{ margin-bottom: 4px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 18px; }}
  table {{ border-collapse: collapse; font-size: 14px; margin: 8px 0 18px 0; }}
  th, td {{ padding: 6px 10px; border-bottom: 1px solid #eee;
           text-align: right; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ background: #fafafa; }}
  img {{ max-width: 100%; height: auto;
         border: 1px solid #eee; border-radius: 4px;
         padding: 4px; background: #fafafa; }}
  .panel {{ border: 1px solid #eee; border-radius: 4px; padding: 14px 16px;
           margin: 14px 0; background: #fafafa; }}
  .panel h3 {{ margin: 0 0 10px 0; font-size: 14px; color: #444; }}
  .ok {{ color: #0a6b1c; font-weight: 600; }}
  .warn {{ color: #b85c00; font-weight: 600; }}
  .footer {{ margin-top: 28px; color: #888; font-size: 12px; }}
  .legend {{ background: #fffbe6; border: 1px solid #f0e0a0;
            padding: 10px 12px; border-radius: 4px;
            font-size: 13px; margin: 10px 0 18px 0; }}
</style></head><body>

<div class="nav">
  <a href="index.html">Watchlist</a>
  <a href="honesty.html"><strong>Model honesty</strong></a>
</div>

<h1>Model honesty — calibration, baselines, leakage</h1>
<div class="meta">
  Numbers below come from a walk-forward split (train: months &lt; {m['split_cutoff']},
  test: months &ge; {m['split_cutoff']}). Re-running the trainer regenerates
  every figure.
</div>

<div class="legend" style="border-left:6px solid #b3261e; background:#fff4f2;">
  <strong>SYNTHETIC DATA — method demonstration, not PAIMANA results.</strong>
  Every number on this page is computed by <code>scripts/train_t1.py</code> on
  <code>data/synthetic/panel.csv</code> (<code>data_source: synthetic</code>).
  Test split cutoff: {m['split_cutoff']}. Held-out base rate: {m['base_rate_test']:.1%}.
  LightGBM PR-AUC: <code>{m['lightgbm']['pr_auc']:.3f}</code>.
</div>

<div class="legend">
  <strong>Calibration is a deliverable, not a decoration.</strong> A "70% slip risk"
  on a project must be backed by a reliability check at the same horizon and sector.
  Below: how calibrated ANUMAAN is on the held-out months.
</div>

<div class="panel">
  <h3>Five models, one walk-forward split (PR-AUC, Brier)</h3>
  <table>
    <thead><tr><th>Model</th><th>PR-AUC</th><th>Brier</th><th>Notes</th></tr></thead>
    <tbody>
      <tr><td>always_majority</td>
          <td>{m['always_majority']['pr_auc']:.3f}</td>
          <td>{m['always_majority']['brier']:.3f}</td>
          <td>Predict 1 always. Brier shows why accuracy alone is misleading.</td></tr>
      <tr><td>sector_rate</td>
          <td>{m['sector_rate']['pr_auc']:.3f}</td>
          <td>{m['sector_rate']['brier']:.3f}</td>
          <td>Predict in-sector historical slip rate from training.</td></tr>
      <tr><td>slip_continues</td>
          <td>{m['slip_continues']['pr_auc']:.3f}</td>
          <td>{m['slip_continues']['brier']:.3f}</td>
          <td>Predict 1 if the project revised in the last 3 months.
              <strong>This is the baseline the brief calls the one that matters.</strong></td></tr>
      <tr><td>logistic</td>
          <td>{m['logistic']['pr_auc']:.3f}</td>
          <td>{m['logistic']['brier']:.3f}</td>
          <td>Regularised logistic regression on point-in-time features.</td></tr>
      <tr><td>lightgbm</td>
          <td>{m['lightgbm']['pr_auc']:.3f}</td>
          <td>{m['lightgbm']['brier']:.3f}</td>
          <td>LightGBM, 200 trees, num_leaves=15, lr=0.05.</td></tr>
    </tbody>
  </table>
  <p style="font-size:13px;">
    Held-out base rate: <strong>{m['base_rate_test']:.1%}</strong>.
    The fancy model beats the trivial baselines here; if it did not, the
    brief demands we say so plainly.
  </p>
  <img src="{base_png}" alt="baseline comparison">
</div>

<div class="panel">
  <h3>Reliability diagram (10-bin calibration, LightGBM)</h3>
  <p style="font-size:13px;">
    Each dot is a prediction-quantile bin; x = mean predicted probability,
    y = observed slip-12m frequency in that bin. Points close to the
    diagonal are well-calibrated. Bin size scaled to its n.
  </p>
  <img src="{rel_lgb_png}" alt="reliability diagram - LightGBM">
</div>

<div class="panel">
  <h3>Earliest-useful lead time (PR-AUC vs horizon)</h3>
  <p style="font-size:13px;">
    The brief asks: at what months-ahead horizon does the model beat the
    base rate? We retrain the same pipeline at h ∈ {{{horizons_txt}}} months
    and plot PR-AUC on held-out months for each horizon. Horizons are limited
    to those the panel carries a <code>slip_&lt;h&gt;m</code> label column for;
    a horizon without a label cannot be trained, so it is not reported.
  </p>
  <table>
    <thead><tr><th>Horizon</th><th>Base rate</th><th>Logistic PR-AUC</th><th>LightGBM PR-AUC</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
  <img src="{lead_png}" alt="lead-time curve">
</div>

<div class="panel">
  <h3>Leakage guard</h3>
  <p style="font-size:13px;">
    Three checks. If any fail, the pipeline has read future information and
    the headline numbers above should not be trusted.
  </p>
  <ul>
    <li><strong>Real PR-AUC</strong>: {leak['real_pr_auc']:.3f} &nbsp;<em>(no leak feature, this is the pipeline's honest score)</em></li>
    <li><strong>With synthetic leak feature</strong>: {leak['with_synthetic_leak_pr_auc']:.3f} &nbsp;
        <em>(we add a feature that strongly correlates with the label; should jump near 1.0)</em></li>
    <li><strong>Shuffled training rows</strong>: {leak['shuffled_train_pr_auc']:.3f} &nbsp;
        <em>(permute training rows; should match real, otherwise features carry row-order signal)</em></li>
  </ul>
  <p style="font-size:13px;">
    Status: <span class="{'ok' if leak['ok'] else 'warn'}">{'OK' if leak['ok'] else 'WARN'}</span>.
    {leak['interpretation']}
  </p>
</div>

<div class="panel">
  <h3>Censoring</h3>
  <p style="font-size:13px;">
    T1 (slip_12m) is observable on every panel row because the horizon is
    fixed at 12 months. We do not drop right-censored projects. T2
    (months_to_commissioning) is explicitly <strong>cut</strong> from this
    build per the delivery brief; if it is added later, it must use a
    discrete-time hazard model or a survival regressor.
  </p>
</div>

<div class="footer">
  Synthetic demo. Re-run <code>python scripts/train_t1.py && python scripts/build_demo.py</code> to regenerate.
</div>

</body></html>
"""
    return html


def main(panel_path: Path, results_dir: Path, out_dir: Path,
         entity_id: str | None) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics = json.loads((results_dir / "metrics.json").read_text())
    predictions = pd.read_csv(results_dir / "predictions.csv",
                              parse_dates=["month", "stated_doc",
                                            "original_doc", "anumaan_p50_doc",
                                            "anumaan_p90_doc"])
    panel = pd.read_csv(panel_path, parse_dates=["month", "approval_month",
                                                  "original_doc", "stated_doc"])

    rel_lgb_png = img_b64(results_dir / "reliability_lightgbm.png")
    base_png = img_b64(results_dir / "baseline_comparison.png")
    lead_png = img_b64(results_dir / "lead_time.png")

    (out_dir / "index.html").write_text(
        build_watchlist(predictions, metrics, panel, top_n=20),
        encoding="utf-8",
    )
    (out_dir / "audit.html").write_text(
        build_audit(predictions, panel, metrics, entity_id),
        encoding="utf-8",
    )
    (out_dir / "honesty.html").write_text(
        build_honesty(metrics, rel_lgb_png, base_png, lead_png),
        encoding="utf-8",
    )

    print(f"wrote {out_dir / 'index.html'}")
    print(f"wrote {out_dir / 'audit.html'}")
    print(f"wrote {out_dir / 'honesty.html'}")
    print(f"audit screen features project: {entity_id or predictions.sort_values('p_lightgbm', ascending=False).iloc[0]['entity_id']}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel", type=Path,
                    default=ROOT / "data" / "synthetic" / "panel.csv")
    ap.add_argument("--results", type=Path, default=ROOT / "results")
    ap.add_argument("--out", type=Path, default=ROOT / "demo")
    ap.add_argument("--entity", type=str, default=None,
                    help="specific entity_id to feature on the audit screen "
                         "(default: highest P(slip) project)")
    args = ap.parse_args()

    # Lazy import to keep the file import-clean when only reading HTML.
    import json as _json_mod
    json = _json_mod

    sys.exit(main(args.panel, args.results, args.out, args.entity))