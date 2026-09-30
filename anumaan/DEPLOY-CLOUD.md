# Hosting ANUMAAN - cloud, government cloud, and offline

ANUMAAN is one stateless web service (plus an optional Laya sidecar). It
needs no database, no object store and no outside API at run time, so the same
container runs on a public PaaS for a demo, on a government cloud VM for
production, or on a laptop with no network at all.

| Where | Use it for | How |
|---|---|---|
| Railway or Render | the public demo on public Flash Report data | `railway.json` or `../render.yaml` + `Dockerfile` - see [DEPLOY.md](DEPLOY.md) |
| NIC / MeghRaj VM, or any Linux VM | production for ministries | `docker-compose.yml` - section 1 |
| Kubernetes (e.g. a MeghRaj cluster) | production at scale | `deploy/k8s/anumaan.yaml` - section 2 |
| A laptop or district office, no network | field use | the offline file - section 3 |

The deck's position - *production on NIC / MeghRaj, all data on government
cloud in India, no foreign AI APIs* - is what sections 1 and 2 deliver: every
component, including the Laya model, runs on the host you deploy to.

---

## 1. A government cloud VM (NIC / MeghRaj) with Docker Compose

Prerequisites on the VM: Docker with the Compose plugin, and a TLS reverse
proxy (the host's nginx, or NIC's load balancer) for your domain.

```bash
git clone <repository> && cd SIH2026-PS26103/anumaan

# 1. Logins - one per ministry nodal officer, plus MoSPI / IPMD
python scripts/users.py ministries                 # exact names
python scripts/users.py add --user ipmd.admin --role mospi
python scripts/users.py add --user morth.nodal --role ministry \
    --ministry "Ministry of Road Transport & Highways"
#    -> secrets/users.json (scrypt hashes only; git- and docker-ignored)

# 2. Secrets, in .env next to docker-compose.yml (git- and docker-ignored)
python -c "import secrets; print(secrets.token_urlsafe(48))"   # run once per secret
cat > .env <<EOF
ANUMAAN_ALLOWED_HOSTS=anumaan.example.gov.in
ANUMAAN_ADMIN_TOKEN=<generated>
ANUMAAN_INTEGRITY_KEY=<generated>
EOF

# 3. Sign the release with the same integrity key (typed, not echoed)
python scripts/integrity.py seal --prompt-key

# 4. Start
docker compose up -d --build
```

Point the reverse proxy at `127.0.0.1:8000` - the container is published on
loopback only. The container refuses to start if any secret is missing, if a
login names a ministry that is not in the panel, or if a file differs from
the signed manifest; `docker compose logs anumaan` says which.

What the compose file enforces: read-only root filesystem, no capabilities,
no privilege escalation, 1 GB memory cap, and one writable volume for the
hash-chained audit log (`/var/lib/anumaan/audit.jsonl`). Verify that log at any
time with `python scripts/verify_audit_log.py <copy of the file>`.

### Adding Laya (field-remark triage)

```bash
cd laya-sidecar
npm ci --omit=dev
node fetch-model.mjs          # 1.7 GB, pinned commit, every file SHA-256 checked
cd ..
cat >> .env <<EOF
LAYA_TOKEN=<generated>
LAYA_MODEL_DIR=/home/<you>/.cache/anumaan-laya/receptron--laya-onnx/68f27dfe5a27a54fb2b1fefc432f43f972e90868
ANUMAAN_LAYA_URL=http://laya:8090
EOF
docker compose --profile laya up -d --build
```

The Laya container sits on an **internal** Docker network: no published port
and no route to the internet. It re-verifies all five model files against
`laya-sidecar/model-manifest.json` at every start (19.5 s for 1.7 GB on the
development laptop, then 17.8 s to load) and needs about 2 GB of RAM - the
compose file caps it at 3 GB.

For an air-gapped VM: run `node fetch-model.mjs` on a connected machine, copy
the model directory and `laya-sidecar/node_modules` across, then
`node fetch-model.mjs --verify-only` on the VM before starting.

---

## 2. Kubernetes

`deploy/k8s/anumaan.yaml` creates a namespace under the `restricted` Pod
Security Standard, a non-root read-only pod with every capability dropped, a
persistent volume for the audit log, and a NetworkPolicy that admits traffic
only from the ingress controller and allows no outbound connections except
DNS. Build the image from `Dockerfile`, push it to the cluster's own registry,
and reference it **by digest**. Create the secret first (commands at the top
of the file).

Replicas: keep 1. Rate limits and the login cache are per process; more
replicas need a shared store (Redis) first - see SECURITY.md.

---

## 3. No network at all

Two ways, both already built:

**In the browser.** Open the app once while connected, go to the Offline tab,
press *Save for offline use*. The app then opens and shows the latest
forecast with no network. Measured on the July 2026 report: the full
snapshot for all 1,775 projects is 104 KB on the wire (323 KB uncompressed);
a re-sync when nothing changed is one 304 response with an empty body.
*Clear offline data* removes it - do that on shared machines.

**As a file.** *Download offline file* (or
`python scripts/export_offline_bundle.py --ministry "<name>"`) writes one HTML
file - 31 KB for Railways' 190 projects, 329 KB for all 1,775. It opens in
any browser from a pen drive, cannot make a network request (its
Content-Security-Policy is `default-src 'none'`), and checks its own SHA-256
when opened.

---

## Speed, measured

Median of 40 requests on the development laptop, before and after this
change (same data, same answers - verified field by field against the
previous build):

| Request | Before | After | Bytes on the wire, after |
|---|---|---|---|
| Watchlist, 60 projects | 30.2 ms | 4.0 ms | 5.1 KB (28.6 KB before gzip) |
| Watchlist, 500 projects | 113.8 ms | 8.8 ms | 36.2 KB (237.7 KB before) |
| One project, with SHAP | 56.3 ms | 8.8 ms | 1.7 KB (5.2 KB before) |
| Full snapshot, 1,775 projects | - | 11.8 ms | 104.3 KB (323.3 KB before) |

Where it came from: the watchlist, ranks and reference rates are computed
once per training run instead of on every request; project lookups use an
index instead of scanning 17,010 rows; responses over 1 KB are gzipped;
the snapshot is columnar with an ETag.

Laya is not in that table on purpose. It does not make the forecast faster
- the forecast is already a few milliseconds. What it adds is local,
open-weights triage of free-text remarks with no hosted AI service. On the
development laptop's CPU a warm call takes 1.1-1.9 s (cold first calls
0.4-10 s, one 63 s outlier), so the remark is recorded first and triage
never blocks a page.
