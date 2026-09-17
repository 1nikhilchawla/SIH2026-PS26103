# Deploying ANUMAAN on Railway

The live service is a single stateless container. It reads a baked-in panel,
trains the model in-process at startup, and serves the UI and JSON API. There
is no database, no object store and no background worker.

## What is in the image, and what is not

| In | Out |
|---|---|
| `app/`, `scripts/`, `config/` | `data/raw/` — 142 MB of source PDFs |
| `results/paimana/panel.csv` (6.7 MB, 17,010 rows) | `.venv/` — 657 MB of local wheels |
| Four provenance JSON files under `results/paimana/` | `demo/`, `docs/`, `tests/`, the deck |

The PDF-to-panel pipeline (`./run.ps1`) is a **local** step. Its output is
committed and copied into the image. That is deliberate: parsing 32 PDFs takes
minutes and needs no network at serve time, so doing it at build or boot would
buy nothing and make cold starts fragile.

**Consequence: new monthly data is a redeploy, not a background job.** Run the
pipeline locally, commit the refreshed `results/paimana/panel.csv`, push.

## One-time setup

Prerequisites: a Railway account, and either a GitHub repository or the Railway
CLI (`npm i -g @railway/cli`).

This directory is **not a git repository yet**. Pick one path.

### Path A — GitHub (recommended: gives you redeploy-on-push)

```bash
git init && git add -A && git commit -m "ANUMAAN: live service + PAIMANA pipeline"
```

Push to a new GitHub repository, then in Railway: **New Project → Deploy from
GitHub repo**. Railway reads `railway.json`, sees `"builder": "DOCKERFILE"`, and
builds. Add a public URL under **Settings → Networking → Generate Domain**.

Note `results/paimana/panel.csv` is 6.7 MB — fine for git, but do not commit
`data/raw/` (142 MB); add a `.gitignore` for it before the first commit.

### Path B — Railway CLI, no git

```bash
railway login
railway init
railway up
```

`railway up` uploads this directory honouring `.dockerignore`, so the PDFs and
the virtualenv stay on your machine.

## Configuration

Railway injects `PORT`; the container binds `0.0.0.0:$PORT`. Nothing else is
required — every other setting has a working default baked in.

| Variable | Default in image | Purpose |
|---|---|---|
| `PORT` | `8000` | Set by Railway at runtime. Do not hardcode it. |
| `ANUMAAN_PANEL` | `/app/results/paimana/panel.csv` | Panel to serve. Point it at a synthetic panel only for a method demo — the banner turns red automatically. |
| `ANUMAAN_CUTOFF` | last labelled month (`2026-06`) | Walk-forward split: train on months before it, test on it. Leave unset unless demonstrating a different split. |

The data source is detected from the panel's **columns**, never its filename,
so renaming a file cannot make synthetic data present itself as real.

## Health check

`railway.json` sets `healthcheckPath: /api/health` with a 120 s timeout. The
check passes only after the model has trained, so it reports readiness rather
than "the process exists".

Measured locally with the exact Railway start command
(`uvicorn app.main:app --host 0.0.0.0 --port $PORT`):

```
[anumaan] panel=results/paimana/panel.csv source=paimana target=slip_next
          rows=17010 labelled=10463 cutoff=2026-06 trained_in=1.56s
INFO:     Uvicorn running on http://0.0.0.0:8099
GET /api/health -> 200
```

Cold start is interpreter boot plus that ~1.6 s of training, well inside the
120 s budget.

## Sizing

Measured on this machine, serving the real panel: **260 MB resident** after
startup (pandas + LightGBM + SHAP + the 17,010-row panel + the fitted model).

Size the instance at **1 GB** rather than 512 MB. 260 MB is the idle-after-boot
figure; `/api/retrain` refits the model and `/api/project/{id}` runs the SHAP
explainer, so peak is higher than steady state and a 512 MB cap leaves little
headroom before the OOM killer restarts the container.

Multiple replicas work but each trains its own copy at boot — deterministic
(`random_state=0`), so the answers agree; it is duplicated work rather than a
benefit.

## After deploying — verify it is serving real data

```bash
curl -s https://<your-app>.up.railway.app/api/health | head -c 400
```

Look for `"data_source":"paimana"` and `"horizon_label":"next monthly report"`.
If you see `"data_source":"synthetic"`, the wrong panel is mounted and the UI
banner will be red.

Then open the app: the banner should be green and name the panel, the watchlist
should list projects with real ministries, and the audit screen should show
SHAP contributions beside the Flash Report rows that drove them.

## Troubleshooting

**Health check fails but the logs show the app started.** Almost always a bind
problem: the process must listen on `0.0.0.0` and on `$PORT`. `127.0.0.1` is
unreachable from Railway's proxy.

**`ImportError: libgomp.so.1`.** LightGBM needs OpenMP. The Dockerfile installs
`libgomp1`; if you switch to a Nixpacks build you must add it yourself. This is
the main reason this project pins a Dockerfile rather than letting Nixpacks
guess.

**Build fails on `pandas` or `scikit-learn` metadata.** The image is
`python:3.14-slim` and `requirements.txt` pins the versions that have 3.14
wheels. Changing the base image's minor version without re-pinning brings this
back.

**Build fails at the panel schema check.** That check is intentional: it fails
the build when `results/paimana/panel.csv` is missing or lacks
`report_month` / `slip_next` / `entity_id`. Run `./run.ps1` locally and commit
the regenerated panel.

**App serves but every project shows a null ministry.** The panel was built by
a parser older than the 17 Sep 2026 group-row fix. Re-run `./run.ps1`.
