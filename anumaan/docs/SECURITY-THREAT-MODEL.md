# ANUMAAN - threat model and security test brief

Prepared 28 Sep 2026 from a full read of the codebase: `app/`, `scripts/`,
`tests/`, `config/`, the `Dockerfile`, `railway.json` and the repository
settings. Part A is written to paste straight into a security-testing intake
form. Part B is the full threat register with the status of every item.

Controls and deployment steps: [../SECURITY.md](../SECURITY.md).

---

# Part A - security testing intake form

## What security threats are you most concerned about?

1. **Unauthorised change to what the service serves** - backend code, the
   trained model or the training data (`results/paimana/panel.csv`) - by
   anyone with repository or deployment access, and specifically by
   autonomous AI coding agents (OpenClaw / Hermes Agent style) acting on
   their own or on instructions injected through documents they read. Please
   try to get production to start, or keep running, with a modified file.
2. **Authentication and authorisation bypass** - the viewer login (HTTP Basic
   on every route except `/api/health`) and the admin token on
   `POST /api/retrain`, the only route that changes server state.
3. **Stored XSS through government data** - project, ministry and agency
   names are parsed from MoSPI PDFs and rendered in the dashboard. Try to
   execute script through them, and try to bypass the Content-Security-Policy.
4. **Government data exposure** - any path that returns project data, internal
   paths or configuration to an unauthenticated user: error bodies, headers,
   `/docs`, `/openapi.json`, static files.
5. **API abuse and denial of service** - `/api/project/{id}` runs a SHAP
   explainer per request and `/api/retrain` refits the model; rate-limit
   evasion (including `X-Forwarded-For` spoofing), large or malformed bodies,
   NaN/infinity inputs.
6. **Supply chain** - a poisoned Python dependency, base image or CI action,
   and a forged or planted Flash Report PDF entering the training data.
7. **Host header abuse and clickjacking.**

## Which parts of the application should we focus on?

- **`app/main.py`** - the request guard middleware (host allow-list, body
  cap, auth, rate limit, headers, audit) and every route:
  `/api/status`, `/api/projects`, `/api/project/{entity_id}`, `/api/score`,
  `/api/retrain`, `/api/metrics`, `/api/pipeline`, `/api/competitors`, `/`,
  `/static/*`.
- **`app/security.py`** - settings validation, Basic-auth parsing,
  constant-time comparisons, the loopback exemption for retrain (development
  only), the in-memory rate limiter.
- **Startup integrity check** - `scripts/integrity.py` plus
  `main._check_integrity`. Production must refuse to start on any changed,
  missing or extra file, an unsigned manifest, a manifest signed with another
  key, or a panel path outside the sealed set.
- **`app/static/app.js`** - every `innerHTML` write goes through the `h`
  escaping template tag; `safeUrl` for links; retrain token handling.
- **`Dockerfile`** - non-root user, root-owned read-only code, build-time
  integrity check, production defaults.
- Lower priority, runs offline and never in the container:
  `scripts/harvest_paimana.py`, `scripts/parse_paimana.py`,
  `scripts/verify_corpus.py`.

## Anything else that would help us test better?

- **Stack:** Python 3.14, FastAPI 0.141.1 on Starlette 1.6.0, uvicorn 0.53.0,
  pydantic 2.13.5, pandas 2.3.3, LightGBM 4.7.0, SHAP 0.52.0; vanilla
  JavaScript, no framework. One container on Railway; no database, no object
  store, no background worker. The model trains in-process at startup (under
  2 s) and is held in memory.
- **Auth:** HTTP Basic for viewers; `X-Admin-Token` header for
  `/api/retrain`. Test credentials will be shared separately, not in this
  form.
- **Data:** built only from publicly published MoSPI PAIMANA Flash Reports -
  17,010 project-month rows, 2,195 projects, 17 ministries. No personal data.
- **Out of scope:** the MoSPI portal itself (`paimana-proj.mospi.gov.in`) -
  please do not test it - and the Railway platform.
- **Rate limits** default to 240 requests/min per client on the API, 30/min on
  `/api/score`, 6/hour on `/api/retrain`. Tell us your test window and source
  IPs and we will raise them for it.
- **Known limitations, already documented - please confirm rather than
  rediscover:** the rate limiter is per process and in memory; behind
  Railway's proxy all clients share one bucket because `X-Forwarded-For` is
  deliberately not trusted; Basic auth has no lockout or MFA and is a
  prototype gate, not SSO; the CSP allows inline *styles* (not scripts); the
  in-app integrity check cannot stop an edit that also deletes the check,
  which is why branch protection and CODEOWNERS exist; the base image is
  pinned by tag, not digest; `requirements.txt` pins versions but not hashes.
- **Existing tests:** 66, of which 21 are security regression tests
  (`tests/test_security.py`).

## Documentation to upload

- `anumaan/docs/openapi.json` - OpenAPI 3 spec with the two security schemes
- `anumaan/SECURITY.md` - controls, deployment variables, repository settings
- `anumaan/docs/SECURITY-THREAT-MODEL.md` - this file
- `anumaan/DEPLOY.md` - how the container is built and configured

---

# Part B - threat register

Status key: **Fixed** = in code, tested, verified. **Your action** = needs a
setting or decision only the owner can make. **Open** = known, not yet done.

Severity is for a deployment holding government data on a public URL.

## B1. Unauthorised change - people and AI agents

| # | Threat | Sev | Found | Status |
|---|---|---|---|---|
| T1 | **Unreviewed changes reach production.** No branch protection, no CODEOWNERS, no CI, and Railway redeploys on every push to `main`. Anyone - or any agent - with push access changes production directly. | Critical | repository had no `.github/` at all | **Files added** (`CODEOWNERS`, `workflows/ci.yml`, `dependabot.yml`). **Your action:** switch on branch protection - checklist in SECURITY.md section 4. Until then this row is not closed. |
| T2 | **Code and derived data bound to nothing.** The 32 PDFs were SHA-pinned, but `panel.csv` and the code were not. An edited panel - which no reviewer can eyeball - would be built and served. | High | `panel_provenance.json` carried no hash | **Fixed:** `scripts/integrity.py` seals 40 files with SHA-256 + HMAC; production refuses to start on any mismatch or an unsigned manifest; build fails on a hash mismatch. **Your action:** generate the key and sign (SECURITY.md 3.3). |
| T3 | **The service could rewrite its own code.** The Dockerfile ran `chown -R anumaan /app`, giving the runtime user write access to `app/`, `scripts/` and the panel. | High | `Dockerfile` (before) | **Fixed:** code stays root-owned, `chmod -R a-w /app`, non-root user. |
| T4 | **Planted PDF path.** `parse_paimana.py --all` parsed every PDF in `data/raw`; `verify_corpus.py` only noted unlisted files. A self-consistent forged report would have entered the training panel. | High | `parse_paimana.py` `RAW.glob("*.pdf")` | **Fixed:** parser reads only manifest-listed files and stops on a stray one; verifier fails on it. Tested. |
| T5 | **Prompt injection into coding agents.** Agents read PDFs, web pages and docs that can carry instructions; agent skills and plugins run with your permissions; tokens on the dev machine give an agent push and deploy rights. | High | process, not code | **Partly:** `AGENTS.md` (guidance), SECURITY.md section 5 (rules). **Your action:** agents get no push rights to `main`, no Railway token, no integrity key. |

## B2. The live API and government data

| # | Threat | Sev | Found | Status |
|---|---|---|---|---|
| T6 | **`POST /api/retrain` unauthenticated.** Anyone on the internet, or any browsing agent, could replace the model every viewer sees, with any cutoff, repeatedly - an integrity attack and a CPU denial of service in one. | Critical | `app/main.py` retrain route (before) | **Fixed:** admin token (constant-time), cutoff must be a panel month, one retrain at a time (409), 6/hour limit, audited. |
| T7 | **No authentication anywhere.** Every project, ministry, cost and SHAP attribution was on the open internet, and `/docs` + `/openapi.json` mapped the API. | Critical | no auth code existed | **Fixed:** HTTP Basic on everything but `/api/health`, mandatory in production; docs return 404 in production. **Open:** SSO (e.g. Parichay) for a ministry deployment. |
| T8 | **Stored XSS from PDF text.** 7 `innerHTML` templates inserted project, ministry, agency and cause text unescaped; the static demo pages did the same; competitor URLs went straight into `href`. Today 1,702 project-name rows and 10,516 ministry rows contain `&` or `'`, and none contain `<` - latent, not exploited. | High | `app/static/index.html`, `build_demo_paimana.py` | **Fixed:** escaping-by-default `h` template tag, `safeUrl`, `html.escape` in static pages, script moved out of the page so the CSP forbids inline script. **Verified live** with a poisoned panel: 0 injected elements; with escaping bypassed by hand, the CSP still blocked the handler. |
| T9 | **Input reflected in errors.** 404 said `"unknown project " + id`, FastAPI's 422 echoes input, and the dashboard wrote error text via `innerHTML`. | Medium | `main.py` 404s, `index.html` catch block | **Fixed:** fixed 404 text, 422 handler drops input, errors rendered as text. |
| T10 | **Unbounded input.** `limit` unbounded, NaN / infinity / 1e9 reached the model, free-text `cutoff` produced 500s, unknown JSON fields accepted. | Medium | route signatures | **Fixed:** typed bounds on every parameter, `extra="forbid"`. Bounds are wider than any real value (drift observed -356..300 months, accepted -600..600). |
| T11 | **No rate limit or size cap.** SHAP per request and retrain are CPU-heavy. | Medium | - | **Fixed:** per-client sliding window, bounded memory; 4 KB body cap; `--limit-concurrency 64`. **Open:** shared store (Redis) if replicas > 1. |
| T12 | **No browser security headers.** Clickjacking, MIME sniffing, no CSP, no HSTS. | Medium | - | **Fixed:** CSP, `frame-ancestors 'none'`, `X-Frame-Options`, nosniff, no-referrer, Permissions-Policy, COOP/CORP, HSTS in production, `no-store` on API. |
| T13 | **Host header not validated.** | Medium | - | **Fixed:** allow-list; `*` refused; required in production. |
| T14 | **Race on retrain.** Retrain wrote shared state key by key while requests read it - a request could mix two models. | Medium | `train_all` STATE.update (before) | **Fixed:** snapshot built off to the side, installed in one assignment, under a lock. |
| T15 | **Information disclosure.** `/api/health` (public) returned full provenance; `panel_file` showed the container path; uvicorn sent a server banner. | Low | `health()`, `panel_adapter` | **Fixed:** health returns only `{"status":"ok"}`; paths relative; `--no-server-header`. |
| T16 | **No audit trail.** No record of who called what or who retrained. CERT-In's Directions of 28 Apr 2022 require 180-day log retention in India and 6-hour incident reporting. | Medium | - | **Fixed in code:** one JSON audit line per request plus retrain events, no credentials or query strings logged. **Your action:** a log drain with 180-day retention in India. |

## B3. Supply chain and ingest

| # | Threat | Sev | Found | Status |
|---|---|---|---|---|
| T17 | **Dependencies and CI.** Versions pinned but not hash-pinned, no vulnerability scan, base image by tag. | Medium | `requirements.txt`, `Dockerfile` | **Audited today:** pip-audit 2.10.1 on all 72 installed packages - 0 known vulnerabilities. **Fixed:** pip-audit in CI, Dependabot, CI actions pinned to commit SHAs, CI token read-only. **Open:** `--require-hashes` requirements; base image digest pin (Docker was not running here, so no digest was verified). |
| T18 | **Harvester trusted the server.** Filename taken from the listing, no size cap, redirects followed anywhere, truncation unchecked. | Medium | `harvest_paimana.download_one` | **Fixed:** filename allow-list (all 32 real names pass; traversal, dotfile and non-PDF names refused), HTTPS-on-portal-host only, 64 MB cap, Content-Length must match. Tested. |
| T19 | **Hostile PDF parsing** (pdfminer CPU/memory exhaustion). | Low | `parse_paimana.py` | **Mitigated by design:** offline, only on hash-pinned files, never in the container. **Open:** per-file timeout and page cap. |
| T20 | **Silent data corruption.** Dates parsed with `errors="coerce"` and no count - a tampered date would have become "missing". | Low | `panel_adapter.py` | **Fixed:** parsing fails if any non-empty value is lost (0 lost today, so no behaviour change). |

## B4. Platform and compliance

| # | Threat | Sev | Found | Status |
|---|---|---|---|---|
| T21 | **Hosting and data residency.** Railway is a general-purpose PaaS, not a MeitY-empanelled cloud. Acceptable for the public Flash Report data; not for non-public ministry data. | High (for non-public data) | deployment choice | **Your decision** before any non-public data is loaded. |
| T22 | **Secret hygiene.** No ignore rules for `.env` or key files. | Medium | `.gitignore` | **Checked:** 0 secrets in the 74 tracked files. **Fixed:** `.env`, `*.key`, `*.pem`, `secrets/` ignored in git and Docker. **Your action:** enable GitHub secret scanning and push protection. |

## Summary

| Severity | Found | Fixed in code | Code done, rest needs you / still open |
|---|---|---|---|
| Critical | 3 | T6, T7 | T1 - files added; branch protection is your setting |
| High | 6 | T3, T4, T8 | T2 - key and signing; T5 - agent access rules; T21 - hosting decision |
| Medium | 10 | T9, T10, T11, T12, T13, T14, T18 | T16 - log retention; T17 - hash pins, image digest; T22 - secret scanning |
| Low | 3 | T15, T20 | T19 - per-file parse timeout |

Verification: `python -m pytest -q` - 66 passed (21 security tests).
`python scripts/integrity.py verify` - 40 files ok. Two controls were broken
deliberately in memory (auth bypass, headers removed) and the tests failed as
they should.
