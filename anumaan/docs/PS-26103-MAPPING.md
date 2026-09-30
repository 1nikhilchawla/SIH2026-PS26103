# SIH26103 - the problem statement, and where each ask lives in this repo

## 0. Provenance of the PS text below

**Caveat that matters.** The official SIH portal text is not in this
repository. The wording below was retrieved on 17 Sep 2026 from two third-party
aggregators, which agree with each other on title, organisation, category and
theme:

- https://sih2026.vuce.in/en/ps/SIH26103
- https://www.sihbuddy.in/ps/SIH26103

Treat the Background and Expected Outcomes below as **reconstructed, not
official**. Before submission, paste the portal's own text into this file and
re-check the mapping. Nothing else in this repository depends on this file.

---

## 1. The problem statement as retrieved

| Field | Value |
|---|---|
| ID | SIH26103 |
| Title | Use case on web-based integrated project-monitoring platform |
| Organisation | MoSPI (Ministry of Statistics and Programme Implementation) |
| Department | Data Informatics & Innovation Division (DIID) |
| Category | Software |
| Theme | Smart Automation |

**Background (reconstructed).** The Infrastructure & Project Monitoring
Division monitors Central Sector Infrastructure Projects costing Rs 150 crore
and above across ministries. The legacy Online Computerised Monitoring System
(OCMS), running since 2006, evolved into the PAIMANA portal - a national
repository tracking project cost, expenditure, timelines and implementation
status across **1,981 ongoing projects, 17 ministries and 22 infrastructure
sectors**. Despite the monitoring, projects frequently encounter cost overruns,
schedule delays and bottlenecks. The challenge is to move from **descriptive
reporting to predictive analytics**, using historical project data spanning
nearly two decades.

**Expected solution (reconstructed).** An AI-powered predictive system
analysing PAIMANA data with open-source tools to forecast cost escalation and
implementation risk. Possible deliverables:

1. Cost and time overrun prediction models
2. Project risk scoring frameworks
3. Early warning alert systems
4. Benchmarking analytics modules
5. Cost escalation driver analysis
6. AI-powered monitoring dashboards
7. LLM-enabled project intelligence assistants
8. Documentation and deployment frameworks

---

## 2. The corroboration worth noticing

The PS background states the portal covers **1,981 ongoing projects, 17
ministries, 22 sectors**. Our parser, reading the PDFs independently, produces:

| PS says | We parsed | Where |
|---|---|---|
| 1,981 ongoing projects | **1,981 rows** from `FlashReport_April2026.pdf` | `results/paimana/reconciliation.csv` |
| 17 ministries | **17 distinct ministries** | `panel.csv`; also matches each report's own printed summary |
| 22 infrastructure sectors | **22 distinct sectors** | `panel.csv` |

We did not target those numbers; they fell out of a parser that reconciles
against each report's own printed totals. That is independent agreement with
the problem statement's own description of the data.

---

## 3. Deliverable-by-deliverable mapping

| # | PS deliverable | Status | Where it is | Evidence |
|---|---|---|---|---|
| 1 | Cost and **time** overrun prediction models | **Time: built. Cost: tested and declined.** | `scripts/train_slip.py`, `scripts/train_cost.py` | Slip: PR-AUC 0.6791 vs best baseline 0.2814 over 9 walk-forward folds. Cost: a ministry base rate (0.1119) beats the model (0.0923); 98.55% of project-months show zero cost change - `cost_target_diagnostic.json` |
| 2 | Project risk scoring framework | **Built** | `eval_slip.py`, `/api/projects` | Calibrated probability per project per month; 10-bin reliability, Brier 0.0959 - `reliability_slip.json` |
| 3 | Early warning alert system | **Built** | `app/main.py` watchlist, `demo/paimana/index.html` | Ranked top-50 catches 48 of 257 slips vs 9 at random, 5.24x - `precision_at_k.json` |
| 4 | Benchmarking analytics module | **Partly built** | `/api/competitors`, `config/competitors.yaml` | Benchmarks ANUMAAN against PAIMANA, PMG, nPlan and Oracle Primavera on 6 axes, each row carrying a source URL and a verified flag. **Ministry-vs-ministry benchmarking inside the data is not built** |
| 5 | Cost escalation **driver** analysis | **Partly built, and honestly qualified** | `shap_slip.json`, audit page | Exact SHAP drivers per project, shown beside the source rows that moved. But these are drivers of the **date moving**, not of cost escalation, because the cost target does not hold up on this corpus |
| 6 | AI-powered monitoring dashboard | **Built** | `app/main.py` + `app/static/index.html` | 5 tabs, live in-process scoring, what-if re-score (drift 0 / 24 / 99 gives 0.8592 / 0.9054 / 0.9114) |
| 7 | LLM-enabled project intelligence assistant | **Not built - deliberately cut** | - | Cut early to protect the evidence chain. An LLM layer over unverified numbers would have been the easiest thing to demo and the hardest to defend |
| 8 | Documentation and deployment framework | **Built** | `docs/`, `run.ps1`, `Dockerfile`, `railway.json`, `DEPLOY.md` | PRD, TRD, architecture, model card, label spec, rubric; one-command pipeline; container that fails the build on a bad panel |

**Against the PS as stated: 5 built, 2 partly built, 1 deliberately cut.**

---

## 4. Where we diverge from the PS, and why

### 4.1 "Nearly two decades" of history - we have 11 months

The single largest gap, and it is a data-access gap rather than a method gap.

The PS assumes roughly 20 years of OCMS history. What is publicly downloadable
from the portal today is the monthly Flash Report PDF. We harvested 32 of them:
**11 are PAIMANA-era and parse; 21 are OCMS-era and do not parse yet**, so the
panel spans 2025-09 to 2026-07.

Consequences we accept and state on every screen:

- The forecast horizon is **one month**, not twelve. A 12-month claim on an
  11-month panel would be unsupportable.
- The cost target fails partly because cost revisions are episodic. Over 20
  years they would be visible; over 11 months, 98.55% of project-months show no
  change at all.

The fix is mechanical, not speculative: extend the same content-based era
detection to the OCMS layout. No new data source, no new permission.

### 4.2 "72% of projects experience delays, averaging 30+ months"

That statistic appears in the PS background. **We did not verify it and we do
not quote it** in the deck or the product. What we measured ourselves, on a
corpus we can prove, is narrower: **19.2% of project-months** see the stated
completion date move in the very next report. The two are not in conflict - one
is a lifetime rate, ours is a monthly rate - but only ours is backed by an
artefact in this repository.

### 4.3 The PS says "predict overruns"; we predict the agency's own revision

A deliberate reframing, worth being able to defend out loud.

"Will this project overrun?" has no ground truth until the project ends, and
most are ongoing - a censoring problem. "Will the agency state a later date in
the next report?" is observable next month, for every project, with no
judgement call. It is the earliest honest signal in the data, and it is the
behaviour that precedes an admitted overrun.

---

## 5. If a judge asks "how is this different from PAIMANA itself?"

PAIMANA reports what the completion date **is**. It does not rank which of
those dates is about to move. Evidence: PAIMANA's own June 2026 figures
(1,847 projects, 17 ministries, revised cost Rs 40.54 lakh crore) describe
status, dashboards and analytics - and neither that page nor the portal
publishes a per-project forecast, a calibration curve, or a leakage test. Those
three columns are `false` for every alternative we checked in
`config/competitors.yaml`, including the commercial ones.
