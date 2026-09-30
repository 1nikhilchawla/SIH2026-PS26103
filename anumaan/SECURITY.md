# ANUMAAN - security

How this service protects government project data, and how it stops anyone -
a person, a bot or an AI coding agent - from changing what it serves without
a human signing off.

The full threat analysis, with every finding and its status, is in
[docs/SECURITY-THREAT-MODEL.md](docs/SECURITY-THREAT-MODEL.md).

---

## 1. The idea in one paragraph

Three independent locks, each held by something an agent does not have:

1. **Review lock (GitHub).** Nothing merges to `main` without an approving
   review from the code owner and a green CI run. An agent can open a pull
   request; it cannot approve or merge one.
2. **Signature lock (key).** Production starts only if every file it runs on
   matches `integrity/MANIFEST.json` *and* that manifest carries an HMAC
   signature made with `ANUMAAN_INTEGRITY_KEY`. The key lives in Railway's
   secret store and in your password manager - never in the repository, a
   `.env` file or a shell profile. An agent can re-hash files; it cannot sign.
3. **Runtime lock (container).** The code in the image is owned by root with
   every write bit removed, and the service runs as an unprivileged user. Even
   code running inside the service cannot rewrite the service.

Why all three: review catches a code change a person can read; the signature
catches a data change nobody can read (a 17,010-row `panel.csv`); the runtime
lock catches anything that gets in after deployment.

**Honest limit.** The in-app integrity check cannot defend against an edit
that deletes the check itself - which is exactly why lock 1 exists and why
`app/`, `scripts/integrity.py` and `.github/` are code-owned.

---

## 2. Controls in the code

| Control | Where | Test |
|---|---|---|
| Viewer login (HTTP Basic) on every route except `/api/health`, `/sw.js` and `/manifest.webmanifest` (none carries data); mandatory in production | `app/security.py`, `app/main.py` guard | `test_viewer_auth_protects_everything_but_health`, `test_service_worker_and_manifest_are_public_but_data_is_not` |
| **Ministry-scoped logins**: `mospi` sees all; a `ministry` login sees only its ministry in every list, page, what-if, snapshot and offline file - any other project is a 404. scrypt password hashes; misspelt ministry stops startup | `app/users.py`, `scripts/users.py` | `test_ministry_user_sees_only_its_ministry_everywhere`, `test_users_file_naming_an_unknown_ministry_stops_startup` |
| **Tamper-evident audit log**: every request, project view, export, remark and retrain; hash-chained on disk; edits, removals and reordering detected | `app/audit.py`, `scripts/verify_audit_log.py` | `test_audit_chain_detects_*`, `test_every_project_view_and_export_is_audited` |
| **Personal data removed** from free-text remarks (phone, e-mail, Aadhaar, PAN, IFSC, account numbers) before storage, logging or Laya | `app/redact.py` | `test_redaction_masks_identifiers_but_keeps_project_facts` |
| **Laya sidecar**: open-weights model on the same host; refuses to start without a 32+ char token and a SHA-256-verified bundle; loads from disk only; internal network, no route out; 16 KB body cap; never logs text | `laya-sidecar/`, `app/laya_client.py` | `test_remark_is_redacted_triaged_and_routed`, `test_laya_*` |
| **Offline file** cannot make a network request (CSP `default-src 'none'`, its one script pinned by hash) and checks its own SHA-256 | `app/offline.py` | `test_offline_bundle_is_self_contained_and_cannot_call_out` |
| **SBOM + AI-BOM** (CycloneDX 1.6) generated from the environment, the npm lockfile and the model manifest | `scripts/make_sbom.py` | `test_sbom_and_aibom_are_generated_from_the_environment` |
| `/api/retrain` needs `X-Admin-Token` (constant-time compare); no token = closed, except loopback in development | `app/main.py` retrain | `test_retrain_*`, `test_loopback_exemption_is_development_only` |
| Production refuses to start on a missing/weak secret, a wildcard host, an unsigned manifest, or a panel outside the sealed set | `security.enforce`, `main._check_integrity` | `test_production_refuses_*` |
| Every input typed and bounded; unknown fields rejected; NaN/inf rejected | `ScoreRequest`, `RetrainRequest`, `Query`/`Path` bounds | `test_inputs_are_bounded_and_errors_do_not_echo_them` |
| Error bodies never echo input | custom 422 handler, fixed 404 text | same test |
| Host allow-list, 4 KB body cap, `Content-Length` required on writes | guard middleware | `test_oversized_body_and_foreign_host_are_refused` |
| Rate limits: 240/min API, 30/min what-if, 20/min remarks, 6/hour retrain - per signed-in user (per client when logins are off), bounded memory | `security.RateLimiter` | `test_rate_limit_answers_429_with_retry_after`, `test_rate_limit_is_per_user_not_per_shared_proxy_ip` |
| CSP `script-src 'self'`, `frame-ancestors 'none'`, nosniff, no-referrer, HSTS in production, `no-store` on API | `security.security_headers` | `test_security_headers_on_pages_and_api` |
| No inline script; every `innerHTML` write goes through an escaping template tag | `app/static/app.js` | `test_no_inline_script_*`, `test_every_innerhtml_write_*` |
| Static demo pages HTML-escape all PDF-derived text | `build_demo_paimana._e` | `test_static_pages_escape_pdf_text` |
| Integrity manifest: SHA-256 of 40 files + HMAC signature | `scripts/integrity.py` | `test_integrity_detects_tamper_*`, `test_repository_manifest_*` |
| Harvester: filename allow-list, portal-only HTTPS redirects, 64 MB cap, truncation check | `harvest_paimana.download_one` | `test_harvester_refuses_*` |
| Parser reads only manifest-pinned PDFs; a stray PDF stops the run | `parse_paimana.manifest_listed`, `verify_corpus.py` | `test_parser_reads_only_manifest_listed_pdfs` |
| Date parsing fails on any value it cannot read, instead of silently nulling it | `panel_adapter._to_dates` | full suite |
| One JSON audit line per request (no credentials, no query string); retrain audited separately | `security.audit` | - |
| Model swapped as one object under a lock; concurrent retrain gets 409 | `main.retrain` | - |
| Container: root-owned read-only code, non-root user, no server banner, concurrency cap; one writable directory for the audit log | `Dockerfile` | build step `integrity.py verify` |
| Government-cloud hosting: read-only root filesystem, no capabilities, no privilege escalation, memory caps, loopback-only port, Laya on an internal network; Kubernetes under the `restricted` Pod Security Standard with a default-deny NetworkPolicy | `docker-compose.yml`, `deploy/k8s/anumaan.yaml` | YAML validated; not run on a cluster here |

`python -m pytest -q` runs all of it. Deployment on NIC / MeghRaj, Kubernetes
and offline: [DEPLOY-CLOUD.md](DEPLOY-CLOUD.md). What the deck promises
against what is built: [docs/DECK-TO-SOFTWARE.md](docs/DECK-TO-SOFTWARE.md).

---

## 3. Deploying securely (Railway)

### 3.1 Generate the secrets - once, on your own machine

```
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Run it three times: one value each for `ANUMAAN_ADMIN_TOKEN`,
`ANUMAAN_INTEGRITY_KEY` and `ANUMAAN_VIEW_PASSWORD`. Put them in your password
manager. Do not paste them into chat tools, AI assistants, issues or commits.

### 3.2 Railway variables

| Variable | Value |
|---|---|
| `ANUMAAN_VIEW_USER` | a login name for viewers |
| `ANUMAAN_VIEW_PASSWORD` | generated, 12+ characters |
| `ANUMAAN_ADMIN_TOKEN` | generated, 32+ characters |
| `ANUMAAN_INTEGRITY_KEY` | generated, 32+ characters |
| `ANUMAAN_ALLOWED_HOSTS` | your public host, e.g. `anumaan-production.up.railway.app` |

`ANUMAAN_ENV=production` is already baked into the image. With any variable
missing the container exits at startup and the log names what is missing.

### 3.3 Sign each release

After a change has been reviewed and merged:

```
python scripts/integrity.py seal --prompt-key
git add integrity/MANIFEST.json
git commit -m "Seal release"
```

`--prompt-key` reads the key without echoing it, so it never enters shell
history or the environment of other processes. Add the same key as the GitHub
Actions secret `ANUMAAN_INTEGRITY_KEY` so CI checks the signature too.

---

## 4. Repository controls - switch these on in GitHub

The files are in the repo; the enforcement is a setting only the owner can
turn on. **Settings -> Branches -> Add rule for `main`:**

- [ ] Require a pull request before merging, with at least 1 approval
- [ ] Require review from Code Owners (`.github/CODEOWNERS`)
- [ ] Dismiss stale approvals when new commits are pushed
- [ ] Require status checks to pass: `verify` (from `.github/workflows/ci.yml`)
- [ ] Require signed commits
- [ ] Do not allow bypassing the above settings (applies to admins too)
- [ ] Block force pushes and branch deletion

Also:

- [ ] Settings -> Actions -> General -> Workflow permissions: **Read repository contents**
- [ ] Settings -> Code security: enable **secret scanning** and **push protection**
- [ ] Railway: deploy only from `main`, and turn on waiting for CI checks before deploying if your plan offers it

---

## 5. Working with AI coding agents

Tools such as OpenClaw, Hermes Agent, Claude Code, Codex or Cursor act with
whatever access the machine and its tokens give them - and they read text
(PDFs, web pages, issues, READMEs) that can carry hidden instructions. Rules
for this repository:

- Give agents **no push rights to `main`** and no Railway token. They work on
  a branch or a worktree and open a pull request; a person reviews it.
- Never give an agent `ANUMAAN_INTEGRITY_KEY`, `ANUMAAN_ADMIN_TOKEN`, a GitHub
  token with write scope, or your password manager.
- Install agent skills and plugins only from sources you have read. A skill is
  code that runs with your permissions.
- Treat every PDF from the portal as untrusted input. The pipeline already
  does: the parser runs offline, only on hash-pinned files, and everything it
  extracts is escaped before display.
- `AGENTS.md` states these rules for agents that read it. It is guidance, not
  enforcement - the locks in section 1 are the enforcement.

---

## 6. Government data - obligations outside the code

These are deployment decisions, not code changes, and they matter before any
non-public data is loaded:

- **Hosting.** The current panel is built from publicly published Flash
  Reports. Before loading non-public ministry data, host on a MeitY-empanelled
  cloud or NIC infrastructure rather than a general-purpose PaaS.
- **Logs.** CERT-In's Directions of 28 April 2022 require ICT system logs to
  be kept for 180 days within India and cyber incidents to be reported to
  CERT-In within 6 hours of noticing them. The service emits the audit lines;
  retention is a setting on the log drain.
- **Personal data.** The panel holds project data, not personal data. If
  officer names or contact details are ever added, the Digital Personal Data
  Protection Act, 2023 applies.
- **Single sign-on.** HTTP Basic is a prototype gate. A production
  deployment for ministries should sit behind the government SSO (e.g.
  Parichay) or an identity-aware proxy.

---

## 7. Reporting a vulnerability

Email the maintainer listed in the repository profile with steps to
reproduce. Please do not open a public issue for a security problem.
