#!/usr/bin/env python3
"""ANUMAAN live service.

Loads a project x month panel, trains the models in-process at startup, and
serves a judge-facing UI plus a JSON API. The model runs inside this process:
/api/score and /api/retrain compute on request, they do not replay a stored
CSV.

Data source is detected from the panel's own columns by app/panel_adapter.py,
never from the filename. The horizon and target definition travel with every
response that carries a probability, so a 1-month number can never be
rendered under a 12-month label.

Provenance rule: every response that carries numbers also carries the
provenance block (data_source, n_projects, n_months, panel_span,
generated_at, generated_by).

Run:
    .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
Defaults to the real PAIMANA panel. To serve the synthetic panel instead:
    ANUMAAN_PANEL=data/synthetic/panel.csv
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import shap
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.panel_adapter import (  # noqa: E402
    load_panel, build_features, drift_magnitude_quantiles,
)
from scripts.train_t1 import (  # noqa: E402
    fit_logistic, fit_lightgbm, predict_logistic, predict_lightgbm,
    pr_auc, brier, reliability_table, leakage_check,
)

PANEL_PATH = Path(os.environ.get("ANUMAAN_PANEL",
                                 ROOT / "results/paimana/panel.csv"))
CUTOFF_ENV = os.environ.get("ANUMAAN_CUTOFF")
TAXONOMY = yaml.safe_load((ROOT / "config/delay_taxonomy.yaml").read_text(encoding="utf-8"))
LABELS = TAXONOMY.get("labels", {})

app = FastAPI(title="ANUMAAN", version="0.2")
STATE: dict = {}


def _meta():
    return STATE["meta"]


def _provenance() -> dict:
    return dict(STATE["provenance"])


def _horizon_block() -> dict:
    m = _meta()
    return {"target": m.target_name,
            "horizon_months": m.horizon_months,
            "horizon_label": m.horizon_label,
            "target_definition": m.target_definition}


def _jsonable(obj):
    """Convert numpy scalars/arrays to plain Python so pydantic can serialize.

    pandas hands back numpy.int64 / numpy.float64 from to_dict("records") and
    .get() on a row, and pydantic refuses those. Coerce once, at the boundary.
    """
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [_jsonable(v) for v in obj.tolist()]
    # NaT, pd.NA and numpy nan all have to become null before pydantic sees
    # them; pydantic raises rather than emitting NaN, and NaT is not a
    # Timestamp instance, so it slips past a Timestamp check.
    if obj is pd.NaT or obj is pd.NA or obj is None:
        return None
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, np.generic):
        obj = obj.item()
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    return obj


def _num(row, key, default=0.0):
    v = row.get(key, default)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(f) else f


def _slip_forecast(p: float) -> dict:
    """Plain-language magnitude, measured on the training window.

    The synthetic build used a hardcoded p*12*0.6 formula. On real data we
    report what the corpus actually shows: among training rows whose date did
    move, the median and 90th-percentile move in months. When the panel cannot
    supply that (synthetic), the block says so instead of inventing a number.
    """
    q = STATE.get("drift_quantiles")
    if q is None:
        return {"available": False,
                "note": "This panel does not carry observed move magnitudes."}
    return {"available": True,
            "p_slip": round(float(p), 4),
            "if_it_slips_p50_months": q["p50_months"],
            "if_it_slips_p90_months": q["p90_months"],
            "measured_on_moves": q["n_observed_moves"],
            "note": ("Magnitudes are the observed distribution of date moves in "
                     "the training window, not a model output.")}


# ---------------------------------------------------------------------------
# Baselines - generic over either panel
# ---------------------------------------------------------------------------

def _baselines(tr: pd.DataFrame, te: pd.DataFrame, y_tr: pd.Series) -> dict:
    base = float(y_tr.mean())
    rates = tr.groupby("ministry")["target"].mean()
    return {
        "always_base_rate": np.full(len(te), base),
        "ministry_base_rate": te["ministry"].map(rates).fillna(base).to_numpy(float),
        "revised_date_this_month": te["persistence_signal"].fillna(0).to_numpy(float),
    }


def train_all(cutoff: str) -> dict:
    """Train every model on the panel and return the metric block.

    Walk-forward only: the split is a temporal mask on the row month. No
    random split, no shuffling, and every transformer is fitted inside
    fit_logistic on the training window only.
    """
    t0 = time.time()
    panel = STATE["panel"]
    X = STATE["X_all"]
    y = panel["target"].astype(int)

    cut = pd.Timestamp(cutoff)
    mask_tr = panel["month"] < cut
    tr, te = panel[mask_tr], panel[~mask_tr]
    X_tr, X_te = X[mask_tr.to_numpy()], X[(~mask_tr).to_numpy()]
    y_tr, y_te = y[mask_tr], y[~mask_tr]
    if y_tr.nunique() < 2 or len(y_te) == 0:
        raise RuntimeError(f"cutoff {cutoff} leaves an unusable split "
                           f"(train={len(y_tr)}, test={len(y_te)})")

    log_pack = fit_logistic(X_tr, y_tr)
    lgb = fit_lightgbm(X_tr, y_tr)
    p_log = predict_logistic(log_pack, X_te)
    p_lgb = predict_lightgbm(lgb, X_te)

    models = dict(_baselines(tr, te, y_tr))
    models["logistic"] = p_log
    models["lightgbm"] = p_lgb
    table = {name: {"pr_auc": float(pr_auc(y_te, p)), "brier": float(brier(y_te, p))}
             for name, p in models.items()}

    # TreeExplainer is built once per training run and reused for the
    # per-project "why this score" panel. Exact SHAP values for tree models.
    explainer = shap.TreeExplainer(lgb)

    STATE.update(model_lgb=lgb, model_log=log_pack, feature_cols=list(X.columns),
                 keep_test=te, X_test=X_te, p_lgb=p_lgb, y_test=y_te,
                 explainer=explainer,
                 drift_quantiles=drift_magnitude_quantiles(tr))

    return {
        "split_cutoff": cutoff,
        "split_rule": "train on month < cutoff, test on month >= cutoff",
        "test_months": sorted(te["month"].dt.strftime("%Y-%m").unique().tolist()),
        "n_train": int(len(y_tr)), "n_test": int(len(y_te)),
        "base_rate_test": float(y_te.mean()),
        "test_positives": int(y_te.sum()),
        "models": table,
        "beats_every_baseline": bool(
            table["lightgbm"]["pr_auc"] > max(
                table[b]["pr_auc"] for b in
                ("always_base_rate", "ministry_base_rate", "revised_date_this_month"))),
        "reliability_lightgbm": reliability_table(y_te, p_lgb).to_dict("records"),
        "leakage_check": leakage_check(X_tr, y_tr, X_te, y_te),
        "drift_magnitude": STATE.get("drift_quantiles"),
        "horizon": _horizon_block(),
        "train_seconds": round(time.time() - t0, 2),
        "provenance": _provenance(),
    }


@app.on_event("startup")
def _startup() -> None:
    if not PANEL_PATH.exists():
        raise RuntimeError("panel not found: " + str(PANEL_PATH))
    panel, meta = load_panel(PANEL_PATH)
    STATE["panel_full"] = panel
    labelled = panel[panel["target"].notna()].copy()
    labelled["target"] = labelled["target"].astype(int)
    STATE["panel"] = labelled
    STATE["meta"] = meta
    STATE["X_all"] = build_features(labelled, meta)
    STATE["provenance"] = {
        "data_source": meta.data_source,
        "panel_file": meta.panel_file,
        "n_projects": meta.n_projects,
        "n_months": meta.n_months,
        "n_rows": meta.n_rows,
        "n_labelled_rows": int(len(labelled)),
        "panel_span": meta.panel_span,
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_by": "app.main:startup -> app/panel_adapter.py + scripts/train_t1.py",
    }
    STATE["metrics"] = train_all(CUTOFF_ENV or meta.default_cutoff)
    print("[anumaan] panel=" + str(PANEL_PATH)
          + " source=" + meta.data_source
          + " target=" + meta.target_name
          + " rows=" + str(len(panel))
          + " labelled=" + str(len(labelled))
          + " cutoff=" + STATE["metrics"]["split_cutoff"]
          + " trained_in=" + str(STATE["metrics"]["train_seconds"]) + "s")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "provenance": _provenance(),
            "cutoff": STATE["metrics"]["split_cutoff"],
            "horizon": _horizon_block(),
            "train_seconds": STATE["metrics"]["train_seconds"]}


@app.get("/api/metrics")
def metrics() -> dict:
    return _jsonable(STATE["metrics"])


@app.get("/api/projects")
def projects(min_p: float = 0.0, ministry: str = "", q: str = "",
             limit: int = 50) -> dict:
    keep = STATE["keep_test"].copy()
    keep["p_slip"] = STATE["p_lgb"]
    latest = (keep.sort_values("month").groupby("entity_id").tail(1)
              .sort_values("p_slip", ascending=False))
    has_cause = _meta().has_delay_cause
    rows = []
    for _, src in latest.iterrows():
        eid = src["entity_id"]
        if float(src["p_slip"]) < min_p:
            continue
        if ministry and str(src.get("ministry")) != ministry:
            continue
        hay = (str(eid) + " " + str(src.get("project_name", "")) + " "
               + str(src.get("ministry", ""))).lower()
        if q and q.lower() not in hay:
            continue
        cause = str(src.get("delay_cause", "")) if has_cause else ""
        rows.append({
            "entity_id": eid,
            "project_name": src.get("project_name"),
            "month": src["month"],
            "ministry": src.get("ministry"), "sector": src.get("sector"),
            "original_doc": src.get("original_doc"),
            "stated_doc": src.get("stated_doc"),
            "drift_months": _num(src, "cumulative_drift_months"),
            "p_slip": round(float(src["p_slip"]), 4),
            "delay_cause": cause or "not published in the source report",
            "owning_authority": (LABELS.get(cause, {}).get("owner", "n/a")
                                 if cause else "n/a"),
            "escalation": (LABELS.get(cause, {}).get("escalation", "n/a")
                           if cause else "n/a"),
        })
        if len(rows) >= limit:
            break
    ministries = sorted(str(m) for m in STATE["panel"]["ministry"].dropna().unique())
    return _jsonable({"count": len(rows), "alerts": rows, "ministries": ministries,
                      "horizon": _horizon_block(), "provenance": _provenance()})


@app.get("/api/project/{entity_id}")
def project(entity_id: str) -> dict:
    panel = STATE["panel_full"]
    hist = panel[panel["entity_id"] == entity_id].sort_values("month")
    if hist.empty:
        raise HTTPException(404, "unknown project " + entity_id)
    keep = STATE["keep_test"].copy()
    keep["p"] = STATE["p_lgb"]
    mine = keep[keep["entity_id"] == entity_id].sort_values("month")
    p_now = float(mine["p"].iloc[-1]) if len(mine) else None
    last = hist.iloc[-1]
    first = hist.iloc[0]
    has_cause = _meta().has_delay_cause
    cause = str(last.get("delay_cause", "")) if has_cause else ""

    # --- why this score: exact SHAP contributions for the latest scored row --
    contributions = []
    if len(mine):
        idx = mine.index[-1]
        x_row = STATE["X_test"].loc[[idx]]
        arr = np.array(STATE["explainer"].shap_values(x_row))
        if arr.ndim == 3:                      # (classes, rows, features)
            arr = arr[-1]
        vals = np.asarray(arr).reshape(-1)[:len(STATE["feature_cols"])]
        trio = zip(STATE["feature_cols"], vals, np.asarray(x_row.iloc[0].values))
        for col, v, raw in sorted(trio, key=lambda t: -abs(float(t[1])))[:8]:
            contributions.append({
                "feature": col.replace("_", " "),
                "value": round(float(raw), 4),
                "shap": round(float(v), 4),
                "direction": "raises risk" if float(v) > 0 else "lowers risk",
            })

    # --- the rows that drove it: what actually changed, month by month -------
    evidence = []
    prev = None
    for _, r in hist.iterrows():
        m = r["month"]
        doc = r.get("stated_doc")
        if prev is not None and pd.notna(doc) and pd.notna(prev[1]) and doc != prev[1]:
            days = int((doc - prev[1]).days)
            evidence.append({
                "from_month": prev[0].strftime("%Y-%m"),
                "to_month": m.strftime("%Y-%m"),
                "what": "stated completion date moved",
                "detail": (f"{prev[1].strftime('%Y-%m')} -> "
                           f"{doc.strftime('%Y-%m')} ({days:+d} days)"),
            })
        prev = (m, doc)
    if not evidence:
        evidence.append({"from_month": None, "to_month": None,
                         "what": "no date change observed in the corpus",
                         "detail": "the stated completion date held across every "
                                   "month this project appears in"})

    # --- reference class: what the held-out months say about its peers -------
    kt = STATE["keep_test"].copy()
    kt["y"] = np.asarray(STATE["y_test"])
    kt["p"] = STATE["p_lgb"]
    sector, ministry = last.get("sector"), last.get("ministry")
    sector_rate = float(kt[kt["sector"] == sector]["y"].mean()) if sector in set(kt["sector"]) else None
    ministry_rate = float(kt[kt["ministry"] == ministry]["y"].mean()) if ministry in set(kt["ministry"]) else None
    overall_rate = float(kt["y"].mean())
    latest_each = kt.sort_values("month").groupby("entity_id").tail(1)
    percentile = (None if p_now is None
                  else round(float((latest_each["p"] < p_now).mean() * 100), 1))
    rank = (None if p_now is None
            else int((latest_each["p"] > p_now).sum()) + 1)

    # --- behaviour summary over the project's whole observed history --------
    drift_now = _num(last, "cumulative_drift_months")
    silent = _num(last, "silent_streak", _num(last, "months_since_last_revision"))
    behaviour = {
        "months_observed": int(len(hist)),
        "first_stated_doc": first.get("stated_doc"),
        "current_stated_doc": last.get("stated_doc"),
        "original_doc": last.get("original_doc"),
        "total_drift_months": drift_now,
        "revisions_so_far": int(_num(last, "revisions_so_far")),
        "months_since_last_revision": int(_num(last, "months_since_last_revision")),
        "silent_streak": int(silent),
        "expenditure_ratio": round(_num(last, "expenditure_ratio"), 4),
        "physical_progress_pct": round(_num(last, "physical_progress_pct"), 2),
        "exp_progress_divergence": round(_num(last, "exp_progress_divergence"), 4),
        "months_since_approval": int(_num(last, "months_since_approval")),
        "original_cost_cr": _num(last, "original_cost_cr"),
        "revised_cost_cr": _num(last, "revised_cost_cr"),
    }

    # --- panel-level quality flags (DQ001-DQ012 run at parse time, not here) -
    flags = []
    if behaviour["physical_progress_pct"] == 0 and behaviour["expenditure_ratio"] > 0.2:
        flags.append({"code": "PANEL-A", "severity": "WARN",
                      "text": "Zero physical progress with more than 20% of cost already spent."})
    if behaviour["expenditure_ratio"] > 1.0:
        flags.append({"code": "PANEL-B", "severity": "WARN",
                      "text": "Cumulative expenditure exceeds the sanctioned cost."})
    if behaviour["silent_streak"] >= 3:
        flags.append({"code": "PANEL-C", "severity": "WARN",
                      "text": f"No revision reported for {behaviour['silent_streak']} consecutive months — "
                              "silence is not the same as being on schedule."})
    if behaviour["exp_progress_divergence"] > 0.25:
        flags.append({"code": "PANEL-D", "severity": "WARN",
                      "text": "Money is moving faster than physical progress."})
    if not flags:
        flags.append({"code": "PANEL-OK", "severity": "INFO",
                      "text": "No panel-level quality flag raised on the latest row."})

    # --- plain-English reading of the number --------------------------------
    horizon = _meta().horizon_label
    base = round(overall_rate * 100, 1)
    if p_now is None:
        verdict = "This project has no scored month in the held-out window."
    elif p_now >= 0.5:
        verdict = (f"More likely than not to push its completion date out in the "
                   f"{horizon}. Held-out base rate is {base}%.")
    elif p_now >= 0.25:
        verdict = (f"Elevated risk of a date move in the {horizon}: well above the "
                   f"held-out base rate of {base}%, but not a majority call.")
    else:
        verdict = (f"Low risk of a date move in the {horizon} relative to the "
                   f"held-out base rate of {base}%.")

    hist_cols = [c for c in ("month", "stated_doc", "cumulative_drift_months",
                             "revisions_so_far", "expenditure_ratio",
                             "physical_progress_pct", "revised_cost_cr",
                             "silent_streak", "months_since_last_revision")
                 if c in hist.columns]

    return _jsonable({
        "entity_id": entity_id,
        "project_name": last.get("project_name"),
        "ministry": ministry, "sector": sector,
        "state": last.get("state"),
        "cost_band_cr": last.get("cost_band_cr"), "agency": last.get("agency"),
        "approval_month": last.get("approval_month"),
        "original_doc": last.get("original_doc"), "stated_doc": last.get("stated_doc"),
        "p_slip": None if p_now is None else round(p_now, 4),
        "forecast": None if p_now is None else _slip_forecast(p_now),
        "delay_cause": cause or "not published in the source report",
        "owning_authority": LABELS.get(cause, {}).get("owner", "n/a") if cause else "n/a",
        "escalation": LABELS.get(cause, {}).get("escalation", "n/a") if cause else "n/a",
        "cause_description": LABELS.get(cause, {}).get("description", "") if cause else "",
        "verdict": verdict,
        "behaviour": behaviour,
        "contributions": contributions,
        "evidence": evidence,
        "reference_class": {
            "sector": sector, "sector_slip_rate": sector_rate,
            "ministry": ministry, "ministry_slip_rate": ministry_rate,
            "overall_slip_rate": overall_rate,
            "percentile_among_projects": percentile,
            "rank": rank, "of_projects": int(len(latest_each)),
        },
        "quality_flags": flags,
        "horizon": _horizon_block(),
        "history": hist[hist_cols].to_dict("records"),
        "risk_series": mine[["month", "p"]].rename(
            columns={"p": "p_slip"}).to_dict("records"),
        "provenance": _provenance(),
    })


@app.get("/api/competitors")
def competitors() -> dict:
    """Capability comparison. Competitor rows come from config/competitors.yaml
    with a source URL and a verified flag; ANUMAAN's column is computed from
    the live model run so it cannot drift from the artefacts."""
    cfg = yaml.safe_load((ROOT / "config/competitors.yaml").read_text(encoding="utf-8"))
    m = STATE["metrics"]
    base = m["base_rate_test"]
    lgb = m["models"]["lightgbm"]["pr_auc"]
    log = m["models"]["logistic"]["pr_auc"]
    ours = dict(cfg.get("anumaan_axes", {}))
    ours.update({
        "pr_auc_lightgbm": round(lgb, 4),
        "pr_auc_logistic": round(log, 4),
        "base_rate": round(base, 4),
        "uplift_vs_base_rate": round(lgb / base, 2) if base else None,
        "brier_lightgbm": round(m["models"]["lightgbm"]["brier"], 4),
        "calibration_bins": len(m["reliability_lightgbm"]),
        "leakage_check": m["leakage_check"],
        "train_seconds": m["train_seconds"],
        "panel_rows": _provenance()["n_rows"],
        "split_cutoff": m["split_cutoff"],
        "horizon": _horizon_block(),
        "scale": (f"{_provenance()['n_projects']} projects x "
                  f"{_provenance()['n_months']} months "
                  f"({_provenance()['panel_span']})"),
        "data_source": _provenance()["data_source"],
    })
    corpus = ROOT / "results/paimana/manifest_verification.json"
    if corpus.exists():
        blob = json.loads(corpus.read_text(encoding="utf-8"))
        ours["corpus_pdfs_sha_verified"] = f"{blob.get('sha_ok')}/{blob.get('manifest_rows')}"
    return _jsonable({"updated": str(cfg.get("updated")),
                      "competitors": cfg.get("competitors", []),
                      "anumaan": ours, "provenance": _provenance()})


class ScoreRequest(BaseModel):
    entity_id: str
    cumulative_drift_months: float | None = None
    revisions_so_far: float | None = None
    months_since_last_revision: float | None = None
    expenditure_ratio: float | None = None
    physical_progress_pct: float | None = None


@app.post("/api/score")
def score(req: ScoreRequest) -> dict:
    """Live what-if: override point-in-time features on the project's latest
    row and re-run the trained model. No stored prediction is read."""
    panel = STATE["panel_full"]
    rows = panel[panel["entity_id"] == req.entity_id]
    if rows.empty:
        raise HTTPException(404, "unknown project " + req.entity_id)
    row = rows.sort_values("month").tail(1).copy()
    overrides = {k: v for k, v in req.model_dump().items()
                 if k != "entity_id" and v is not None}
    for k, v in overrides.items():
        row[k] = v
    if "expenditure_ratio" in overrides or "physical_progress_pct" in overrides:
        row["exp_progress_divergence"] = (row["expenditure_ratio"]
                                          - row["physical_progress_pct"] / 100.0)
    # Build features from the single overridden row and reindex to the trained
    # column order. Do NOT append it to the panel and take tail(1): the panel
    # is sorted by (entity_id, month), so the appended row is not last and the
    # override would be silently ignored.
    X_one = build_features(row, _meta())
    X_one = X_one.reindex(columns=STATE["feature_cols"], fill_value=0.0)
    p = float(predict_lightgbm(STATE["model_lgb"], X_one)[0])
    return _jsonable({"entity_id": req.entity_id, "overrides": overrides,
                      "p_slip": round(p, 4),
                      "forecast": _slip_forecast(p),
                      "horizon": _horizon_block(),
                      "computed_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                      "provenance": _provenance()})


class RetrainRequest(BaseModel):
    cutoff: str | None = None


@app.post("/api/retrain")
def retrain(req: RetrainRequest) -> dict:
    STATE["metrics"] = train_all(req.cutoff or _meta().default_cutoff)
    return _jsonable(STATE["metrics"])


@app.get("/api/pipeline")
def pipeline() -> dict:
    """Honest status of the REAL PDF ingest, read from artefacts on disk."""
    out: dict = {"real_data": {}, "notes": []}
    for key, rel in (("manifest", "results/paimana/manifest_verification.json"),
                     ("reconciliation", "results/paimana/reconciliation_meta.json"),
                     ("panel", "results/paimana/panel_provenance.json"),
                     ("cost_target", "results/paimana/cost_target_diagnostic.json")):
        p = ROOT / rel
        if p.exists():
            blob = json.loads(p.read_text(encoding="utf-8"))
            blob["_file"] = rel
            out["real_data"][key] = blob
        else:
            out["notes"].append(rel + " not on disk")
    out["serving"] = _provenance()
    out["horizon"] = _horizon_block()
    return _jsonable(out)


app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")),
          name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(Path(__file__).parent / "static" / "index.html"))
