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

Security (app/security.py, app/users.py, app/audit.py, scripts/integrity.py,
SECURITY.md):
    - Ministry-scoped logins: a `ministry` user sees only that ministry's
      projects in every list, page, what-if, snapshot and offline bundle;
      anything else answers 404. `mospi` users see everything. Logins are
      mandatory in production.
    - /api/retrain is the only route that changes server state. It needs
      X-Admin-Token; without a configured token it is open to a loopback
      client in development only.
    - Every input is bounded and typed; error bodies never echo input back.
      Free-text remarks are stripped of personal identifiers (app/redact.py)
      before they are stored, logged or triaged.
    - Every request, project view and export is written to the audit log,
      hash-chained on disk when ANUMAAN_AUDIT_FILE is set.
    - The files this process runs on are checked against integrity/
      MANIFEST.json at startup. In production a changed file, an unsigned
      manifest or a panel path outside the sealed set stops the service.

Offline and speed (app/offline.py, app/static/sw.js):
    - /api/snapshot: the forecast for every project in the latest report,
      compact and columnar, with an ETag so a re-sync that finds nothing new
      costs a body-less 304. Responses over 1 KB are gzipped.
    - /api/offline-bundle: the same data as one self-contained HTML file that
      works with no server and cannot make a network request.
    - The dashboard installs as an offline-capable web app (service worker).
    - Lists, ranks and reference rates are computed once per training run,
      not once per request.

Laya (app/laya_client.py, laya-sidecar/): field remarks are triaged to a
delay cause and its owner by the open-weights Laya model running on the same
server. Optional; without it remarks are recorded for a person to classify.

Run:
    .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
Defaults to the real PAIMANA panel. To serve the synthetic panel instead
(development only):
    ANUMAAN_PANEL=data/synthetic/panel.csv
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import threading
import time
import traceback
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import shap
import yaml
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import laya_client, offline  # noqa: E402
from app import security as sec  # noqa: E402
from app.audit import AuditLog  # noqa: E402
from app.panel_adapter import (  # noqa: E402
    load_panel, build_features, drift_magnitude_quantiles,
)
from app.redact import redact  # noqa: E402
from app.users import AuthCache, Principal  # noqa: E402
from scripts import integrity  # noqa: E402
from scripts.train_t1 import (  # noqa: E402
    fit_logistic, fit_lightgbm, predict_logistic, predict_lightgbm,
    pr_auc, brier, reliability_table, leakage_check,
)

SEALED_PANEL = ROOT / "results/paimana/panel.csv"
PANEL_PATH = Path(os.environ.get("ANUMAAN_PANEL", SEALED_PANEL))
CUTOFF_ENV = os.environ.get("ANUMAAN_CUTOFF")
STATIC = Path(__file__).parent / "static"
TAXONOMY = yaml.safe_load((ROOT / "config/delay_taxonomy.yaml").read_text(encoding="utf-8"))
LABELS = TAXONOMY.get("labels", {})
MIN_CONFIDENCE = float(TAXONOMY.get("rules", {}).get("min_confidence", 0.6))

# PAIMANA project codes are 6 digits; synthetic ids look like P00012. Anything
# outside this shape cannot be a project, so it is refused before any lookup.
ENTITY_ID_RE = r"^[A-Za-z0-9_.-]{1,40}$"
CUTOFF_RE = r"^\d{4}-\d{2}$"

# STATE["data"]     immutable after startup: panel, features, meta, provenance
# STATE["model"]    one snapshot per training run, replaced as a whole
# STATE["live"]     forecast for the latest report (offline snapshot source)
# STATE["settings"] validated security settings
STATE: dict = {}
_RETRAIN_LOCK = threading.Lock()

# Field remarks: newest 20 per project, at most 5,000 projects, in memory.
# The durable record is the hash-chained audit log.
_REMARKS: OrderedDict[str, deque] = OrderedDict()
_REMARKS_LOCK = threading.Lock()


def _meta():
    return STATE["data"]["meta"]


def _provenance() -> dict:
    return dict(STATE["data"]["provenance"])


def _snap() -> dict:
    """The current model snapshot. Read it ONCE per request and use the local
    reference throughout, so a concurrent retrain cannot mix two models."""
    return STATE["model"]


def _principal(request: Request) -> Principal:
    p = getattr(request.state, "principal", None)
    if p is None:                                 # the guard sets it on every
        raise HTTPException(401, "authentication required")   # non-public path
    return p


def _visible(request: Request, entity_id: str) -> str:
    """The project's ministry if the caller may see it; otherwise 404 - the
    same answer as for a project that does not exist, so a ministry user
    cannot probe for another ministry's project codes."""
    missing = object()
    ministry = STATE["data"]["entity_ministry"].get(entity_id, missing)
    if ministry is missing or not _principal(request).can_see(ministry):
        raise HTTPException(404, "unknown project")
    return ministry


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


def _slip_forecast(p: float, snap: dict) -> dict:
    """Plain-language magnitude, measured on the training window.

    The synthetic build used a hardcoded p*12*0.6 formula. On real data we
    report what the corpus actually shows: among training rows whose date did
    move, the median and 90th-percentile move in months. When the panel cannot
    supply that (synthetic), the block says so instead of inventing a number.
    """
    q = snap.get("drift_quantiles")
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


def _shap_matrix(explainer, X: pd.DataFrame, n_features: int) -> np.ndarray:
    arr = np.array(explainer.shap_values(X))
    if arr.ndim == 3:                       # (classes, rows, features)
        arr = arr[-1]
    return np.asarray(arr).reshape(len(X), -1)[:, :n_features]


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


def _alert_rows(latest: pd.DataFrame) -> list[dict]:
    """The watchlist, built once per training run. Each row keeps its
    ministry and a lower-cased search string as private fields for filtering;
    /api/projects strips them."""
    has_cause = _meta().has_delay_cause
    rows = []
    for _, src in latest.iterrows():
        eid = src["entity_id"]
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
            "_p": float(src["p_slip"]),
            "_ministry": src.get("ministry"),
            "_hay": (str(eid) + " " + str(src.get("project_name", "")) + " "
                     + str(src.get("ministry", ""))).lower(),
        })
    return _jsonable(rows)


def train_all(cutoff: str) -> dict:
    """Train every model on the panel and return a complete model snapshot,
    metrics and per-request lookups included. Does not touch STATE: the
    caller installs the snapshot in one assignment.

    Walk-forward only: the split is a temporal mask on the row month. No
    random split, no shuffling, and every transformer is fitted inside
    fit_logistic on the training window only.
    """
    t0 = time.time()
    data = STATE["data"]
    panel = data["panel"]
    X = data["X_all"]
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
    drift_q = drift_magnitude_quantiles(tr)

    # --- per-request lookups, computed once here instead of on every call ---
    keep = te.copy()
    keep["p"] = p_lgb
    keep["y"] = np.asarray(y_te)
    keep_sorted = keep.sort_values("month", kind="stable")
    # Ties in p_slip are broken by project id, so the watchlist order is the
    # same on every run (a plain sort left tied projects in arbitrary order).
    latest = (keep_sorted.groupby("entity_id").tail(1)
              .rename(columns={"p": "p_slip"})
              .sort_values(["p_slip", "entity_id"], ascending=[False, True], kind="stable"))
    latest_each = keep_sorted.groupby("entity_id").tail(1)

    snap = dict(model_lgb=lgb, model_log=log_pack, feature_cols=list(X.columns),
                keep_test=te, X_test=X_te, p_lgb=p_lgb, y_test=y_te,
                explainer=explainer, drift_quantiles=drift_q,
                alerts=_alert_rows(latest),
                keep_by_entity={k: keep_sorted.iloc[v] for k, v in
                                keep_sorted.groupby("entity_id", sort=False).indices.items()},
                sector_rate=keep.groupby("sector")["y"].mean().to_dict(),
                ministry_rate=keep.groupby("ministry")["y"].mean().to_dict(),
                overall_rate=float(keep["y"].mean()),
                rank_p=np.sort(latest_each["p"].to_numpy()))
    snap["metrics"] = {
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
        "drift_magnitude": drift_q,
        "horizon": _horizon_block(),
        "train_seconds": round(time.time() - t0, 2),
        "provenance": _provenance(),
    }
    return snap


def _live_forecast(evaluated: dict) -> dict:
    """Score every project in the LATEST report - the early warning a ministry
    acts on, whose outcome is not known yet.

    Same recipe as the evaluated model (same features, same LightGBM
    settings), trained walk-forward on every month whose label is already
    known, i.e. every month before the latest report. Its accuracy is the
    walk-forward accuracy of that recipe, reported alongside; the forecast
    itself is checked when the next report arrives.
    """
    t0 = time.time()
    data = STATE["data"]
    meta, full, lab = data["meta"], data["panel_full"], data["panel"]
    last = full["month"].max()
    tr_mask = (lab["month"] < last).to_numpy()
    y_tr = lab["target"][tr_mask]
    if y_tr.nunique() < 2:
        raise RuntimeError("not enough labelled months before the latest report")
    cols = list(data["X_all"].columns)
    model = fit_lightgbm(data["X_all"][tr_mask], y_tr)
    rows = full[full["month"] == last]
    X = build_features(rows, meta).reindex(columns=cols, fill_value=0.0)
    p = predict_lightgbm(model, X)
    sv = _shap_matrix(shap.TreeExplainer(model), X, len(cols))
    order = np.argsort(-np.abs(sv), axis=1)[:, :2]
    names = [c.replace("_", " ") for c in cols]
    # One-hot ministry columns read "min_Ministry_of_..." - turn them back into
    # "ministry is / is not <name>", using the row's own 0/1 value, so an
    # offline reader sees a sentence rather than a column name.
    sanitized = {re.sub(r"[^0-9A-Za-z_]", "_", "min_" + str(m)): str(m)
                 for m in full["ministry"].dropna().unique()}
    xv = X.to_numpy()

    def why(i: int, k: int) -> str:
        j = order[i, k]
        sign = "+" if sv[i, j] > 0 else "-"
        if cols[j] in sanitized:
            return sign + ("ministry is " if xv[i, j] >= 0.5 else "ministry is not ") + sanitized[cols[j]]
        return sign + names[j]

    def col(name: str) -> np.ndarray:
        return rows[name].to_numpy() if name in rows.columns else np.full(len(rows), None)

    df = pd.DataFrame({
        "entity_id": col("entity_id"), "project_name": col("project_name"),
        "ministry": col("ministry"), "sector": col("sector"), "state": col("state"),
        "stated_doc": col("stated_doc"), "original_doc": col("original_doc"),
        "cumulative_drift_months": col("cumulative_drift_months"),
        "physical_progress_pct": col("physical_progress_pct"),
        "p_slip": p,
        "why1": [why(i, 0) for i in range(len(rows))],
        "why2": [why(i, 1) for i in range(len(rows))],
    }).sort_values("p_slip", ascending=False, kind="stable").reset_index(drop=True)
    lab_months = lab.loc[tr_mask, "month"]
    info = {
        "month": last.strftime("%Y-%m"),
        "forecast_for": f"the next monthly report after {last.strftime('%Y-%m')}",
        "outcome_known": False,
        "horizon": _horizon_block(),
        "model": {
            "recipe": "LightGBM, same features and settings as the evaluated model",
            "trained_on_months": f"{lab_months.min():%Y-%m} to {lab_months.max():%Y-%m}",
            "n_train_rows": int(tr_mask.sum()),
            "walk_forward_pr_auc_lightgbm": round(evaluated["models"]["lightgbm"]["pr_auc"], 4),
            "walk_forward_test_months": evaluated["test_months"],
        },
        "generated_at": _provenance()["generated_at"],
        "seconds": round(time.time() - t0, 2),
    }
    return {"df": df, "info": info, "cache": {}}


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def _check_integrity(settings: sec.Settings) -> dict:
    """Production: a changed or missing file, an unsigned manifest, or a panel
    served from outside the sealed set stops startup. Development: the
    mismatch is printed and the service runs, so a local edit does not need a
    re-seal after every save - CI runs the strict check on every push."""
    if settings.production and PANEL_PATH.resolve() != SEALED_PANEL.resolve():
        raise RuntimeError("production serves only the sealed panel "
                           "results/paimana/panel.csv; unset ANUMAAN_PANEL")
    try:
        rep = integrity.verify(ROOT, key=settings.integrity_key,
                               require_signature=settings.production)
        rep["status"] = "ok"
    except integrity.IntegrityError as exc:
        if settings.production:
            raise RuntimeError(str(exc)) from exc
        print("[anumaan] WARNING (development, not enforced): "
              + str(exc).replace("\n", " | "), flush=True)
        rep = {"status": "mismatch - development mode, not enforced"}
    return rep


def _load_and_train() -> None:
    if not PANEL_PATH.exists():
        raise RuntimeError("panel not found: " + str(PANEL_PATH))
    panel, meta = load_panel(PANEL_PATH)
    labelled = panel[panel["target"].notna()].copy()
    labelled["target"] = labelled["target"].astype(int)
    by_entity = panel.sort_values("month", kind="stable").groupby("entity_id", sort=False)
    STATE["data"] = {
        "panel_full": panel,
        "panel": labelled,
        "meta": meta,
        "X_all": build_features(labelled, meta),
        # project lookups by id instead of a 17,010-row scan per request
        "full_by_entity": {k: panel.iloc[np.sort(v)].sort_values("month", kind="stable")
                           for k, v in panel.groupby("entity_id", sort=False).indices.items()},
        "entity_ministry": by_entity["ministry"].last().to_dict(),
        "provenance": {
            "data_source": meta.data_source,
            "panel_file": meta.panel_file,
            "n_projects": meta.n_projects,
            "n_months": meta.n_months,
            "n_rows": meta.n_rows,
            "n_labelled_rows": int(len(labelled)),
            "panel_span": meta.panel_span,
            "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "generated_by": "app.main:startup -> app/panel_adapter.py + scripts/train_t1.py",
        },
    }
    snap = train_all(CUTOFF_ENV or meta.default_cutoff)
    STATE["model"] = snap
    STATE["live"] = _live_forecast(snap["metrics"])
    print("[anumaan] panel=" + meta.panel_file
          + " source=" + meta.data_source
          + " target=" + meta.target_name
          + " rows=" + str(len(panel))
          + " labelled=" + str(len(labelled))
          + " cutoff=" + snap["metrics"]["split_cutoff"]
          + " trained_in=" + str(snap["metrics"]["train_seconds"]) + "s"
          + " live_forecast=" + STATE["live"]["info"]["month"]
          + " (" + str(len(STATE["live"]["df"])) + " projects, "
          + str(STATE["live"]["info"]["seconds"]) + "s)", flush=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = sec.load_settings()
    sec.enforce(settings)
    STATE["settings"] = settings
    sec.AUDIT = AuditLog(Path(settings.audit_file) if settings.audit_file else None)
    STATE["users"] = sec.build_user_store(settings)
    STATE["auth_cache"] = AuthCache()
    STATE["integrity"] = _check_integrity(settings)
    if "model" not in STATE:
        _load_and_train()
    store = STATE["users"]
    if store is not None:
        known = set(STATE["data"]["entity_ministry"].values())
        unknown = sorted(store.ministries() - known)
        if unknown:
            raise RuntimeError("users file names ministries that are not in the panel "
                               "(check the spelling): " + "; ".join(unknown))
    print(f"[anumaan] security: production={settings.production} "
          f"logins={'off' if store is None else str(len(store)) + ' user(s)'} "
          f"admin_token={'set' if settings.admin_token else 'unset'} "
          f"audit_file={'on' if settings.audit_file else 'off'} "
          f"laya={'on' if settings.laya_url else 'off'} "
          f"integrity={STATE['integrity'].get('status')} "
          f"hosts={','.join(settings.allowed_hosts)}", flush=True)
    yield


app = FastAPI(title="ANUMAAN", version="0.4", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Request guard: host, size, auth, rate limit, headers, audit
# ---------------------------------------------------------------------------

def _host_only(raw: str) -> str:
    raw = raw.strip().lower()
    if raw.startswith("["):                       # [::1]:8000
        return raw[1:raw.find("]")] if "]" in raw else raw
    return raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw


def _buckets(path: str, settings: sec.Settings):
    yield "api", settings.rate_api_per_min, 60.0
    if path == "/api/score":
        yield "score", settings.rate_score_per_min, 60.0
    if path == "/api/retrain":
        yield "retrain", settings.rate_retrain_per_hour, 3600.0
    if path.startswith("/api/project/") and path.endswith("/remark"):
        yield "remark", settings.rate_remark_per_min, 60.0


@app.middleware("http")
async def guard(request: Request, call_next):
    settings: sec.Settings = STATE["settings"]
    t0 = time.perf_counter()
    path = request.url.path
    client = request.client.host if request.client else "unknown"
    principal: Principal | None = None
    attempted = None
    extra: dict[str, str] = {}

    def refuse(status: int, detail: str):
        return JSONResponse({"detail": detail}, status_code=status, headers=extra)

    response = None
    if _host_only(request.headers.get("host", "")) not in settings.allowed_hosts:
        response = refuse(400, "invalid host")
    elif settings.production and path in sec.DOCS_PATHS:
        response = refuse(404, "Not Found")
    elif request.method in ("POST", "PUT", "PATCH"):
        cl = request.headers.get("content-length")
        if cl is None or not cl.isdigit():
            response = refuse(411, "Content-Length required")
        elif int(cl) > settings.max_body_bytes:
            response = refuse(413, "request body too large")

    if response is None and path not in sec.PUBLIC_PATHS:
        header = request.headers.get("authorization")
        principal = sec.resolve_principal(STATE["users"], STATE["auth_cache"], header)
        if principal is None:
            creds = sec.parse_basic(header)
            attempted = creds[0][:64] if creds else None
            extra["WWW-Authenticate"] = 'Basic realm="ANUMAAN", charset="UTF-8"'
            response = refuse(401, "authentication required")
        else:
            request.state.principal = principal

    if response is None and path.startswith("/api/"):
        # Signed-in users are limited per user; everyone else per client.
        key = principal.user if principal and principal.role != "open" else client
        for bucket, limit, window in _buckets(path, settings):
            ok, retry = sec.LIMITER.allow(bucket, key, limit, window)
            if not ok:
                extra["Retry-After"] = str(retry)
                response = refuse(429, "rate limit exceeded")
                break

    if response is None:
        try:
            response = await call_next(request)
        except Exception:                        # never leak a trace to the client
            traceback.print_exc()
            response = refuse(500, "internal error")

    for k, v in sec.security_headers(settings, path).items():
        if k not in response.headers:
            response.headers[k] = v
    event = {"method": request.method, "path": path, "status": response.status_code,
             "ms": round((time.perf_counter() - t0) * 1000, 1), "client": client,
             "user": principal.user if principal else "anonymous",
             "role": principal.role if principal else None}
    if attempted:
        event["user_attempted"] = attempted
    sec.audit(event)
    return response


# Outermost: compress whatever the guard lets through (bodies over 1 KB).
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.exception_handler(RequestValidationError)
async def _validation_error(_request: Request, exc: RequestValidationError):
    """FastAPI's default 422 body includes the rejected input verbatim. Keep
    the location and the reason, drop the input, so an error can never
    reflect attacker text back into a page."""
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", "invalid"),
         "type": e.get("type", "value_error")} for e in exc.errors()]})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    """Public liveness probe for the platform. Deliberately says nothing about
    the data: /api/status carries the detail, behind authentication."""
    return {"status": "ok"}


@app.get("/api/status")
def status(request: Request) -> dict:
    snap = _snap()
    live = STATE.get("live") or {}
    settings: sec.Settings = STATE["settings"]
    return {"status": "ok", "provenance": _provenance(),
            "cutoff": snap["metrics"]["split_cutoff"],
            "horizon": _horizon_block(),
            "train_seconds": snap["metrics"]["train_seconds"],
            "principal": _principal(request).public(),
            "live_forecast_month": (live.get("info") or {}).get("month"),
            "laya": {"configured": bool(settings.laya_url)}}


@app.get("/api/metrics")
def metrics() -> dict:
    return _jsonable(_snap()["metrics"])


@app.get("/api/projects")
def projects(request: Request,
             min_p: float = Query(0.0, ge=0.0, le=1.0),
             ministry: str = Query("", max_length=120),
             q: str = Query("", max_length=100),
             limit: int = Query(50, ge=1, le=500)) -> dict:
    p = _principal(request)
    ql = q.lower()
    rows = []
    for a in _snap()["alerts"]:                  # already sorted by p_slip, high first
        if a["_p"] < min_p:
            continue
        if not p.can_see(a["_ministry"]):
            continue
        if ministry and str(a["_ministry"]) != ministry:
            continue
        if ql and ql not in a["_hay"]:
            continue
        rows.append({k: v for k, v in a.items() if not k.startswith("_")})
        if len(rows) >= limit:
            break
    all_ministries = sorted(str(m) for m in STATE["data"]["panel"]["ministry"].dropna().unique())
    ministries = [m for m in all_ministries if p.can_see(m)]
    return {"count": len(rows), "alerts": rows, "ministries": ministries,
            "horizon": _horizon_block(), "provenance": _provenance()}


@app.get("/api/project/{entity_id}")
def project(request: Request, entity_id: str = ApiPath(pattern=ENTITY_ID_RE)) -> dict:
    scope_ministry = _visible(request, entity_id)
    snap = _snap()
    hist = STATE["data"]["full_by_entity"].get(entity_id)
    if hist is None or hist.empty:
        raise HTTPException(404, "unknown project")
    mine = snap["keep_by_entity"].get(entity_id)
    p_now = float(mine["p"].iloc[-1]) if mine is not None else None
    last = hist.iloc[-1]
    first = hist.iloc[0]
    has_cause = _meta().has_delay_cause
    cause = str(last.get("delay_cause", "")) if has_cause else ""
    sec.audit({"event": "view_project", "user": _principal(request).user,
               "entity_id": entity_id, "ministry": scope_ministry})

    # --- why this score: exact SHAP contributions for the latest scored row --
    contributions = []
    if mine is not None:
        x_row = snap["X_test"].loc[[mine.index[-1]]]
        vals = _shap_matrix(snap["explainer"], x_row, len(snap["feature_cols"]))[0]
        trio = zip(snap["feature_cols"], vals, np.asarray(x_row.iloc[0].values))
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
    sector, ministry = last.get("sector"), last.get("ministry")
    sector_rate = snap["sector_rate"].get(sector)
    ministry_rate = snap["ministry_rate"].get(ministry)
    sector_rate = None if sector_rate is None else float(sector_rate)
    ministry_rate = None if ministry_rate is None else float(ministry_rate)
    overall_rate = snap["overall_rate"]
    rank_p = snap["rank_p"]
    n_rank = len(rank_p)
    percentile = (None if p_now is None
                  else round(float(np.searchsorted(rank_p, p_now, side="left") / n_rank * 100), 1))
    rank = (None if p_now is None
            else int(n_rank - np.searchsorted(rank_p, p_now, side="right")) + 1)

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
    risk_series = ([] if mine is None else
                   mine[["month", "p"]].rename(columns={"p": "p_slip"}).to_dict("records"))
    with _REMARKS_LOCK:
        remarks = list(_REMARKS.get(entity_id, ()))

    return _jsonable({
        "entity_id": entity_id,
        "project_name": last.get("project_name"),
        "ministry": ministry, "sector": sector,
        "state": last.get("state"),
        "cost_band_cr": last.get("cost_band_cr"), "agency": last.get("agency"),
        "approval_month": last.get("approval_month"),
        "original_doc": last.get("original_doc"), "stated_doc": last.get("stated_doc"),
        "p_slip": None if p_now is None else round(p_now, 4),
        "forecast": None if p_now is None else _slip_forecast(p_now, snap),
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
            "rank": rank, "of_projects": int(n_rank),
        },
        "quality_flags": flags,
        "horizon": _horizon_block(),
        "history": hist[hist_cols].to_dict("records"),
        "risk_series": risk_series,
        "remarks": remarks,
        "provenance": _provenance(),
    })


@app.get("/api/competitors")
def competitors() -> dict:
    """Capability comparison. Competitor rows come from config/competitors.yaml
    with a source URL and a verified flag; ANUMAAN's column is computed from
    the live model run so it cannot drift from the artefacts."""
    cfg = yaml.safe_load((ROOT / "config/competitors.yaml").read_text(encoding="utf-8"))
    m = _snap()["metrics"]
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


# Bounds are wider than anything in the real panel (drift -356..300 months,
# revisions 0..6, expenditure ratio -0.03..103, progress 0..100), so no real
# what-if is refused, and NaN / infinity never reach the model.
class ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str = Field(pattern=ENTITY_ID_RE)
    cumulative_drift_months: float | None = Field(None, ge=-600, le=600, allow_inf_nan=False)
    revisions_so_far: float | None = Field(None, ge=0, le=100, allow_inf_nan=False)
    months_since_last_revision: float | None = Field(None, ge=0, le=600, allow_inf_nan=False)
    expenditure_ratio: float | None = Field(None, ge=-1, le=1000, allow_inf_nan=False)
    physical_progress_pct: float | None = Field(None, ge=0, le=100, allow_inf_nan=False)


@app.post("/api/score")
def score(req: ScoreRequest, request: Request) -> dict:
    """Live what-if: override point-in-time features on the project's latest
    row and re-run the trained model. No stored prediction is read, and
    nothing is written: the what-if never changes server state."""
    _visible(request, req.entity_id)
    snap = _snap()
    rows = STATE["data"]["full_by_entity"].get(req.entity_id)
    if rows is None or rows.empty:
        raise HTTPException(404, "unknown project")
    row = rows.tail(1).copy()
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
    X_one = X_one.reindex(columns=snap["feature_cols"], fill_value=0.0)
    p = float(predict_lightgbm(snap["model_lgb"], X_one)[0])
    return _jsonable({"entity_id": req.entity_id, "overrides": overrides,
                      "p_slip": round(p, 4),
                      "forecast": _slip_forecast(p, snap),
                      "horizon": _horizon_block(),
                      "computed_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                      "provenance": _provenance()})


class RetrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cutoff: str | None = Field(None, pattern=CUTOFF_RE)


@app.post("/api/retrain")
def retrain(req: RetrainRequest, request: Request,
            x_admin_token: str | None = Header(default=None)) -> dict:
    """The only route that changes what every other user sees. Admin only,
    one at a time, cutoff restricted to months the panel actually has, and
    the new model goes live in a single assignment."""
    settings: sec.Settings = STATE["settings"]
    client = request.client.host if request.client else None
    allowed, principal = sec.admin_ok(settings, x_admin_token, client)
    if not allowed:
        sec.audit({"event": "retrain_denied", "client": client})
        raise HTTPException(403, "retrain requires a valid X-Admin-Token")
    cutoff = req.cutoff or _meta().default_cutoff
    if cutoff not in _meta().months:
        raise HTTPException(422, "cutoff must be one of the months in the panel")
    if not _RETRAIN_LOCK.acquire(blocking=False):
        raise HTTPException(409, "a retrain is already running")
    try:
        try:
            snap = train_all(cutoff)
        except RuntimeError as exc:
            raise HTTPException(422, "that cutoff leaves an unusable train/test split") from exc
        STATE["model"] = snap
    finally:
        _RETRAIN_LOCK.release()
    sec.audit({"event": "retrain", "principal": principal, "client": client,
               "cutoff": cutoff, "train_seconds": snap["metrics"]["train_seconds"]})
    return _jsonable(snap["metrics"])


# ---------------------------------------------------------------------------
# Offline: snapshot and single-file bundle
# ---------------------------------------------------------------------------

def _scoped_snapshot(p: Principal) -> tuple[dict, bytes, str]:
    live = STATE.get("live")
    if not live:
        raise HTTPException(503, "no forecast available")
    key = (p.role, p.ministry)
    hit = live["cache"].get(key)
    if hit is None:
        df = live["df"]
        if p.role == "ministry":
            df = df[df["ministry"] == p.ministry]
        snap_obj = offline.build_snapshot(df, live["info"],
                                          scope={"role": p.role, "ministry": p.ministry})
        body, etag = offline.encode(snap_obj)
        hit = (snap_obj, body, "W/" + etag)
        live["cache"][key] = hit
    return hit


@app.get("/api/snapshot")
def snapshot(request: Request) -> Response:
    """This month's forecast for everything the caller may see, compact. A
    device that already holds it sends If-None-Match and gets a 304."""
    p = _principal(request)
    snap_obj, body, etag = _scoped_snapshot(p)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    sec.audit({"event": "export_snapshot", "user": p.user, "rows": snap_obj["n_projects"],
               "scope": p.ministry or "all", "month": snap_obj["month"]})
    return Response(body, media_type="application/json", headers={"ETag": etag})


def _slug(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "all-ministries").lower()).strip("-")[:60]


@app.get("/api/offline-bundle")
def offline_bundle(request: Request) -> Response:
    """The snapshot as one HTML file that works with no server and no network."""
    p = _principal(request)
    snap_obj, _body, _etag = _scoped_snapshot(p)
    page, sha = offline.render_bundle(snap_obj)
    sec.audit({"event": "export_bundle", "user": p.user, "rows": snap_obj["n_projects"],
               "scope": p.ministry or "all", "month": snap_obj["month"], "sha256": sha})
    name = f"anumaan-offline-{snap_obj['month']}-{_slug(p.ministry)}.html"
    return Response(page, media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"',
                             "X-Content-SHA256": sha})


# ---------------------------------------------------------------------------
# Field remarks, triaged by Laya
# ---------------------------------------------------------------------------

class RemarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=3, max_length=1000)


@app.post("/api/project/{entity_id}/remark")
def remark(req: RemarkRequest, request: Request,
           entity_id: str = ApiPath(pattern=ENTITY_ID_RE)) -> dict:
    """Record a field remark on a project and triage it to a delay cause and
    its owner. Personal identifiers are removed first; the model sees and the
    log keeps only the redacted text."""
    _visible(request, entity_id)
    p = _principal(request)
    settings: sec.Settings = STATE["settings"]
    text, removed = redact(req.text.strip())
    result = laya_client.triage(settings.laya_url, settings.laya_token, text,
                                LABELS, MIN_CONFIDENCE)
    rec = {"at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "by": p.user, "text": text, "personal_data_removed": removed, "triage": result}
    with _REMARKS_LOCK:
        q = _REMARKS.setdefault(entity_id, deque(maxlen=20))
        q.appendleft(rec)
        _REMARKS.move_to_end(entity_id)
        while len(_REMARKS) > 5000:
            _REMARKS.popitem(last=False)
    sec.audit({"event": "remark", "user": p.user, "entity_id": entity_id, "text": text,
               "personal_data_removed": removed, "triage_status": result["status"],
               "routing": result.get("routing"), "suggested_cause": result.get("suggested_cause")})
    return _jsonable({"entity_id": entity_id, **rec})


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
    out["integrity"] = STATE.get("integrity")
    return _jsonable(out)


# ---------------------------------------------------------------------------
# Web app shell: page, static files, offline service worker, manifest
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    """Served from the root so its scope covers the whole app."""
    return FileResponse(str(STATIC / "sw.js"), media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def web_manifest() -> FileResponse:
    return FileResponse(str(STATIC / "manifest.webmanifest"),
                        media_type="application/manifest+json")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC / "index.html"))
