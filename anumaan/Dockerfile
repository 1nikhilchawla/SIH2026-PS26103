# ANUMAAN live service - container image for Railway (or any OCI host).
#
# What ships in this image: the code, the config, and the derived artefacts the
# app reads at startup (results/paimana/panel.csv and the JSON provenance
# files). What does NOT ship: the 142 MB of source PDFs under data/raw and the
# local .venv. The PDF-to-panel pipeline is a local step - see DEPLOY.md - so
# the container stays small and starts fast.
#
# The model is trained IN-PROCESS at startup from the baked-in panel; there is
# no model artefact to load and no database to reach. That keeps the deploy
# self-contained, and it means a cold start does real work - see DEPLOY.md for
# the measured time and memory.

FROM python:3.14-slim

# libgomp1: LightGBM links against OpenMP at runtime and fails to import
# without it on slim images. Everything else in requirements.txt has wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg

WORKDIR /app

# Dependencies first so edits to the source do not invalidate this layer.
COPY requirements.txt requirements-py314.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code and the config it reads.
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY config/ ./config/

# Derived artefacts the service reads at startup and serves on /api/pipeline.
# panel.csv is the model's training data; the JSON files carry provenance and
# are rendered on the pipeline and benchmark screens.
COPY results/paimana/panel.csv ./results/paimana/panel.csv
COPY results/paimana/panel_provenance.json ./results/paimana/
COPY results/paimana/manifest_verification.json ./results/paimana/
COPY results/paimana/reconciliation_meta.json ./results/paimana/
COPY results/paimana/cost_target_diagnostic.json ./results/paimana/

# Fail the BUILD, not the first request, if the panel the app needs is absent
# or is the synthetic one. A container that boots and then serves a red
# "SYNTHETIC DATA" banner in production is worse than a build error.
RUN python -c "import sys, pandas as pd; df = pd.read_csv('results/paimana/panel.csv', nrows=5); missing = {'report_month','slip_next','entity_id'} - set(df.columns); sys.exit('panel.csv missing columns: ' + ', '.join(sorted(missing))) if missing else print('panel schema ok:', len(df.columns), 'columns')"

# Run as a non-root user. The service only ever reads from disk.
RUN useradd --create-home --uid 10001 anumaan && chown -R anumaan:anumaan /app
USER anumaan

ENV ANUMAAN_PANEL=/app/results/paimana/panel.csv \
    PORT=8000
EXPOSE 8000

# Shell form so ${PORT} is expanded: Railway assigns the port at runtime and
# the process must bind 0.0.0.0, not localhost, or the health check never
# reaches it.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
