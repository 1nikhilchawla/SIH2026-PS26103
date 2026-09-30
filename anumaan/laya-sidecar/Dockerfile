# ANUMAAN Laya sidecar. Optional: the core service runs without it and says
# "triage not configured". Needs about 2 GB of RAM for the model.
#
# The model is NOT baked into the image. Fetch and verify it once on the host
# (node fetch-model.mjs), then mount that directory read-only at /models.
# The server re-verifies every file's SHA-256 at start and never downloads.
FROM node:22-slim

WORKDIR /srv
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY server.mjs verify.mjs fetch-model.mjs model-manifest.json ./

# Code is root-owned and read-only; the service runs as the image's
# unprivileged `node` user and writes nothing.
RUN chmod -R a-w /srv
USER node

ENV LAYA_HOST=0.0.0.0 \
    LAYA_PORT=8090 \
    LAYA_MODEL_DIR=/models
EXPOSE 8090
CMD ["node", "server.mjs"]
