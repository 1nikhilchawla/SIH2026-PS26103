# The deck, claim by claim, against the software

Source deck: `ANUMAAN_SIH26103-1.pptx` (6 slides). This file lists every claim
the deck makes about security, offline use, hosting and speed, and says
exactly where it now lives in the code - or that it does not yet. Measured
numbers come from runs on 29 Sep 2026 on the development laptop.

Status: **Built** = in the code and tested. **Partly** = built with a stated
limit. **Next** = not built; the deck already says "next".

---

## Security for government data (slide 3)

| Deck says | Status | Where, and what it does |
|---|---|---|
| "Prototype uses public reports only; production reads the CRIP API on NIC / MeghRaj cloud" | **Partly** | Hosting on NIC / MeghRaj is ready: `docker-compose.yml`, `deploy/k8s/anumaan.yaml`, `DEPLOY-CLOUD.md`. Reading the CRIP API is **Next** - it needs MoSPI access. |
| "No foreign AI APIs; in production all data stays on government cloud in India" | **Built** | The only model besides LightGBM is Laya, running in `laya-sidecar/` on the same host, on an internal network with no route out. No hosted AI API is called anywhere. |
| "Scores shown only to MoSPI and the owning ministry, never published (next)" | **Built** | `app/users.py`: `mospi` and `ministry` logins. A ministry login sees only its own projects in every list, page, what-if, snapshot and offline file; any other project answers 404. Production refuses to start without logins. |
| "Ministry-scoped logins and an audit log of every view and export (next)" | **Built** | Logins as above. `app/audit.py`: every request, every project view (`view_project`), every export (`export_snapshot`, `export_bundle`), every remark and retrain is logged; with `ANUMAAN_AUDIT_FILE` the log is hash-chained so an edited, removed or reordered line is detected (`scripts/verify_audit_log.py`). Passwords, tokens and query strings are never logged. |
| "CERT-In 6-hour reporting, 180-day logs" | **Partly** | The service writes the logs. 180-day retention in India is a setting on the log drain; 6-hour reporting is an incident-response duty. Both are in SECURITY.md section 6, not in code. |
| "SBOM + AI-BOM" | **Built** | `scripts/make_sbom.py` writes CycloneDX 1.6 `results/sbom/sbom.cdx.json` (73 Python + 19 npm components) and `aibom.cdx.json` (the training panel with its SHA-256, the LightGBM model card with its measured PR-AUC and Brier score, and the Laya model with its pinned revision and hashes). |
| "DPDP-safe redaction" | **Built** | `app/redact.py` removes phone numbers, e-mail, Aadhaar, PAN, IFSC and long account numbers from free-text remarks before they are stored, logged or sent to Laya. Project codes, amounts and dates are kept. Pattern-based: it does not catch names or addresses, and the remark box says so. |

## Speed and access for remote users (slide 3)

| Deck says | Status | Measured now |
|---|---|---|
| "Scores every project in a monthly report in one pass" | **Built** | At startup the service scores all 1,775 projects in the July 2026 report in one batch, with the top two SHAP drivers for each (`app/main.py: _live_forecast`). Model: the evaluated LightGBM recipe, trained on every month whose outcome is known. |
| "retrains in 0.57 s on a CPU" | **Built** | Startup training measured 0.43-0.69 s across runs on 29 Sep 2026. |
| "Monthly snapshot 217 KB, update 3.2 KB (measured): about 36 s even on 2G" | **Built, different numbers - update the deck** | The snapshot this build serves is **104 KB on the wire** (323 KB before gzip) for all 1,775 projects: **17.4 s** at the 48 kbit/s the deck's 36 s implies. A re-sync when the month has not changed is a **304 with an empty body**. There is no 3.2 KB incremental update: when a new month arrives the full 104 KB snapshot is sent. The deck's 217 KB and 3.2 KB are not produced by this code. |
| "Offline-first app" | **Built** | `app/static/sw.js` makes the dashboard an installable web app. *Save for offline use* keeps the forecast in the browser; the app then opens with no network. `/api/offline-bundle` and `scripts/export_offline_bundle.py` produce one HTML file (31 KB for Railways, 329 KB for all ministries) that works from a pen drive and cannot make a network request. |
| "SMS alerts via NIC's gateway, 160 characters in English or 70 in Hindi (next)" | **Next** | Needs NIC SMS gateway credentials. |
| "Hindi + English screens; pilot States' languages via Bhashini; GIGW 3.0 accessibility (next)" | **Next** | Not built. |
| "Jev, a hosted AI decision tool (TypeSafe), was evaluated and rejected: no public weights, data location not disclosed" | **Built - and the deck can now say more** | Laya (`@receptron/laya`, weights Apache-2.0) is the open-weights, Jev-compatible model. It runs on the ANUMAAN server and triages field remarks to a delay cause and its owner. Suggested deck line: *"Jev rejected (no public weights, data location not disclosed); its open-weights equivalent, Laya, runs on our own server."* |

What Laya does and does not do, measured - say this if asked:

- It classifies a remark such as *"land compensation still pending"* into the
  12 causes in `config/delay_taxonomy.yaml`, and routes it to that cause's
  owner and escalation path.
- Its 12-option probabilities are **not calibrated**: the model's own
  calibration file sets temperature 0.10 for 11+ options, so every answer
  came out at about 1.00 - including a wrong one ("work is on track" ->
  contractor performance). ANUMAAN therefore uses the cause only as a ranking.
- It auto-routes only when a separate yes/no question - *does the remark
  describe a delaying problem?* - reaches the taxonomy's 0.6 threshold.
  Otherwise the remark goes to human review with the suggestion attached.
- Laya sees **the remark alone**. Measured on the same 7 hand-written
  remarks: remark alone, **7/7 correct end to end** (five concrete problems
  routed to the right owner at 0.66-0.81; "work is on track" and "status as
  reported earlier" sent to human review at 0.08 and 0.12). With the project
  name, ministry and sector added, only 3/7 - the rest fell below the
  threshold. No wrong owner in either setting.
- Seven remarks is a smoke test, not an evaluation - no real PAIMANA remarks
  exist in the published data. Latency on this laptop: 1.1-1.9 s per warm
  call (14 calls); cold first calls 0.4-10 s, with one 63 s outlier.
- It does **not** speed up the forecast. The forecast was already a few
  milliseconds; the speed-up in this release comes from caching and gzip
  (next table).

## Speed of the live service (not in the deck; measured for this release)

| Request | Before | After |
|---|---|---|
| Watchlist, 60 projects | 30.2 ms, 28.6 KB | 4.0 ms, 5.1 KB on the wire |
| Watchlist, 500 projects | 113.8 ms, 237.7 KB | 8.8 ms, 36.2 KB |
| One project with SHAP | 56.3 ms, 5.2 KB | 8.8 ms, 1.7 KB |

Every response was compared field by field with the previous build: identical
except the order of two projects tied at exactly the same score, which is now
fixed (ties break by project ID).

## Elsewhere in the deck

| Deck says | Status |
|---|---|
| Slide 2 (d) "Early warning alerts ... SMS / Sandes / e-mail next" | Watchlist **Built**; offline delivery **Built**; SMS / Sandes / e-mail **Next** |
| Slide 2 (i) "Docs and deployment: model card and runbook next" | **Partly**: AI-BOM carries a model card; government-cloud deployment files and guide added; a separate runbook is still **Next** |
| Slide 2 "Prescriptive decision support: owner routing once reports carry a cause" | **Partly**: owner routing now works for field remarks through Laya; reports themselves still carry no cause |
| Slide 4 "A wrong flag on a flagship project -> 'contest this flag' option (next)" | **Partly**: a ministry officer can record a remark against any flag, and it is logged and routed; there is no formal contest workflow |
| Slide 4 "Weak connectivity -> offline snapshot (217 KB) and SMS alerts (next)" | Offline snapshot **Built** (104 KB on the wire - see above); SMS **Next** |
| Slide 3 "LLM project assistant, grounded in data (next)" | **Next** |
| Slide 2 (a) cost model, (f) cost drivers, CUF test | **Next**, unchanged |
