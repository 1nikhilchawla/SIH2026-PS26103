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
# The integrity manifest, and the two build files it also covers, so the
# container can prove at build time and at every start that it is running
# exactly the sealed file set (scripts/integrity.py, SECURITY.md).
COPY integrity/ ./integrity/
COPY Dockerfile railway.json ./

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

# Fail the BUILD if any sealed file differs from integrity/MANIFEST.json.
# Hashes only here - the signature needs the key, which is a runtime secret
# and must never be passed as a build argument (build args land in the image
# history). The signature is checked at every start instead.
RUN python scripts/integrity.py verify

# Run as a non-root user that can READ the code but not change it. /app stays
# owned by root and every write bit is removed, so even code running inside
# the service - an injected payload, a compromised dependency - cannot
# rewrite app/, scripts/ or the panel. Nothing under /app is ever written.
# /var/lib/anumaan is the one writable place: the hash-chained audit log
# (ANUMAAN_AUDIT_FILE), normally a mounted volume.
RUN useradd --create-home --uid 10001 anumaan \
 && chmod -R a-w /app \
 && mkdir -p /var/lib/anumaan && chown anumaan:anumaan /var/lib/anumaan
USER anumaan

# Secure by default. With ANUMAAN_ENV=production the service refuses to start
# unless ANUMAAN_VIEW_USER / ANUMAAN_VIEW_PASSWORD, ANUMAAN_ADMIN_TOKEN,
# ANUMAAN_INTEGRITY_KEY and ANUMAAN_ALLOWED_HOSTS are set and the manifest
# signature verifies. See DEPLOY.md for the variables.
ENV ANUMAAN_ENV=production \
    PORT=8000
EXPOSE 8000

# Shell form so ${PORT} is expanded: Railway assigns the port at runtime and
# the process must bind 0.0.0.0, not localhost, or the health check never
# reaches it. No server banner; the app writes its own audit line per
# request, so uvicorn's access log would only duplicate it.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-server-header --no-access-log --timeout-keep-alive 5 --limit-concurrency 64
