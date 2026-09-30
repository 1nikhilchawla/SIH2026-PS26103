# ANUMAAN - Technical Requirements Document

Companion to `docs/PRD.md`. Problem statement **SIH26103**.
Team **The Raftaar Titans**.

---

## 1. System shape

```
PAIMANA portal
   |  harvest_paimana.py       polite egress, identified user agent
   v
data/raw/*.pdf + manifest.csv  SHA-256 per file
   |  verify_corpus.py         fail-closed integrity check
   v
parse_paimana.py               era detected from CONTENT, 8-column table model
   |                           reconciled against the report's printed totals
   v
data/interim/paimana/*.rows.json
   |  build_panel.py           point-in-time features; labels named as labels
   v
results/paimana/panel.csv      17,010 rows / 2,195 projects / 11 months
   |  train_slip.py, eval_slip.py, train_cost.py, diagnose_cost_target.py
   v
results/paimana/*.json         metrics, calibration, SHAP, diagnostics
   |  app/main.py (FastAPI)    trains in-process at startup
   v
watchlist UI + JSON API + static demo pages
```

## 2. Stack

| Layer | Choice | Why |
|---|---|---|
| Runtime | Python 3.14 | `requirements.txt` pins the exact versions that produced the artefacts |
| PDF extraction | pdfplumber | Line-based tables with a per-page word-position fallback |
| Data | pandas, numpy | Panel construction |
| Models | scikit-learn (logistic), LightGBM | Strong tabular model plus a linear reference |
| Explanation | SHAP TreeExplainer | Exact contributions, not a sampling approximation |
| Service | FastAPI + uvicorn | Trains at startup; no model artefact to load |
| Container | python:3.14-slim + libgomp1 | LightGBM links OpenMP at runtime |
| Deploy | Railway, Dockerfile builder | Health check on `/api/health` |

## 3. Data contracts

**Manifest** (`data/raw/manifest.csv`):
`filename, report_id, fy, era, path, url, sha256, bytes, fetched_at, status`.
The `era` column is a filename heuristic and is **not** trusted by the parser.

**Panel** (`results/paimana/panel.csv`). Identity: `entity_id` (portal project
code, else `NAME:<ministry>::<name>`), `report_month` as `YYYY-MM-01`.

Point-in-time features - this row and earlier rows of the same project only:
`original_cost_cr, revised_cost_cr, cumulative_expenditure_cr,
physical_progress_pct, months_since_approval, cumulative_drift_months,
months_to_target, months_past_original, expenditure_ratio, cost_overrun_ratio,
exp_progress_divergence, drift_change_1m, date_revised_this_month,
revisions_so_far, cost_revised_this_month, months_observed,
months_since_last_revision`, plus ministry one-hots.

Labels - the only forward-looking columns: `slip_next`, `cost_up_next`,
`delta_cost_ratio_next`, `label_horizon_months`. Dropped from the feature
matrix by name; an assertion fails the run if one survives.

## 4. Hard rules

1. **Walk-forward only.** No `train_test_split`, no `KFold`, no `shuffle=True`
   in the modelling path. Splits are temporal masks on `report_month`.
2. **Fit inside the training window.** Transformers are fitted on train rows
   only, inside the pipeline.
3. **Labels look forward; features never do.** Enforced by name and asserted.
4. **Gaps break labels.** Where consecutive months are missing, the label is
   undefined rather than stretched across the hole.
5. **Fail closed.** A report that does not reconcile is rejected; zero parsed
   rows cannot pass.
6. **No silent coercion.** Null counts are printed; nothing is imputed quietly.

## 5. Validation design

9 walk-forward folds across 11 months.
Baselines: `always_base_rate`, `ministry_base_rate`, and `slipped_last_month`
(persistence) - the one a reviewer always asks about. Metrics: PR-AUC for a
rare positive class, Brier, 10-bin reliability, and
precision / recall / lift at realistic inspection budgets.

Leakage controls on every build: shuffled labels
0.1717, real 0.6791, planted
leak 1.0.

Held-out month 2026-06: 1404 projects,
257 slips.

| Model | PR-AUC | Brier |
|---|---|---|
| always_base_rate | 0.1830 | 0.1496 |
| ministry_base_rate | 0.2157 | 0.1534 |
| slipped_last_month | 0.2814 | 0.2137 |
| logistic | 0.4858 | 0.2245 |
| **LightGBM** | **0.6791** | **0.0959** |

## 6. API surface

| Endpoint | Returns |
|---|---|
| `GET /api/health` | status, provenance, horizon block |
| `GET /api/metrics` | fold metrics, baselines, calibration, leakage |
| `GET /api/projects` | ranked watchlist with filters |
| `GET /api/project/{entity_id}` | score, SHAP, evidence rows, reference class, flags |
| `POST /api/score` | live what-if against the trained model |
| `POST /api/retrain` | re-train at a different cutoff |
| `GET /api/pipeline` | ingest provenance read from disk |
| `GET /api/competitors` | benchmark rows plus our live metrics |

Every response carrying a probability also carries `horizon` (`target`,
`horizon_months`, `horizon_label`, `target_definition`), so a one-month number
can never render under a twelve-month label.

## 7. Deployment

`Dockerfile`: `python:3.14-slim`, `libgomp1`, non-root user, and a panel schema
check **at build time** so a bad panel fails the build rather than the first
request. `railway.json`: Dockerfile builder, health check `/api/health`,
restart on failure. Binds `0.0.0.0:$PORT`. Measured: trains in 1.6 s, 260 MB
resident. The panel is baked into the image, so new monthly data is a redeploy,
not a background job.

## 8. Reproducibility

`./run.ps1` runs: verify corpus, parse all, build panel, train slip, train cost,
diagnose cost target, evaluate, build demo pages, run tests. It stops at the
first non-zero exit rather than producing pages of stale numbers. Observed full
run 1636 s, dominated by PDF parsing; 45/45 tests green.

## 9. Known technical debt

| Item | Impact | Fix |
|---|---|---|
| 21 OCMS-era reports unparsed | Panel limited to 11 months | Second-era layout inside the same content-detection framework |
| Parse step re-reads unchanged PDFs | ~26 min of the 27-minute pipeline | Cache keyed on SHA-256 plus parser version |
| Cost model ships as a negative result | No cost forecast in the product | Needs a longer panel; monthly cadence is the wrong question |
