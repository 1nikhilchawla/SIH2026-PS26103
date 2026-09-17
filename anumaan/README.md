# ANUMAAN — starter kit for SIH26103

Predictive analytics for central-sector infrastructure project monitoring (MoSPI / PAIMANA).

**What this is:** a working skeleton so that on day 1 you are downloading real data instead of
arguing about folder structure. Nothing here is a toy — the offline test suite runs (45/45 pass;
heavy-dep-blocked run is the P1 acceptance), the parser extracts both OCMS-era and PAIMANA-era
tables with reconciliation against each report's own summary totals, and the harvest/parse/train
pipeline runs end-to-end on synthetic Flash-Report-shaped data via `make demo`.

**Reality check (16 Sep 2026):** `data/raw/` is empty. The live portal's report listing is
client-rendered, so the current harvester's HTML regex returns 0 reports. ADR-0002 documents the
route work in flight (D1); until that lands, every number in this repo comes from synthetic data
shaped like Flash Reports, with the banner and provenance block making that explicit. See
`results/EVIDENCE.md`.

**Start with [`SOURCES.md`](SOURCES.md)** — every link, dataset, paper and article, annotated.

---

## The idea in one paragraph

MoSPI publishes monthly Flash Reports on every central-sector project costing ₹150 crore or more.
Each report states, per project, the original completion date and the agency's *own current
estimate* of when it will finish. Those estimates are revised, month after month, and they drift.
**Nobody audits them.** ANUMAAN builds a project-month panel from the historical Flash Reports
and learns which agencies' forecasts slip, by how much, and how early that was visible — then issues a
calibrated, interval-bounded forecast for every ongoing project, with the reason and the authority
who can act on it. (Real ingestion is in flight; the panel currently comes from a synthetic
generator shaped like Flash Reports — see `results/EVIDENCE.md`.)

You are not building another dashboard. You are building the thing that tells you the dashboard is
lying — politely, with a confidence interval.

---

## Quickstart

```bash
make setup          # creates .venv, installs pinned deps
cp config/settings.example.yaml config/settings.yaml
$EDITOR config/settings.yaml      # put a real contact email in user_agent

make list           # dry run: list every report found, download nothing
make harvest        # download all reports -> data/raw/ + manifest.csv
make parse FILE=data/raw/<one-report>.pdf
make test           # offline tests, no network
```

No virtualenv yet? The tests also run with nothing but the standard library plus `bs4`:

```bash
python3 tests/run_tests.py
```

### Be a good citizen

`settings.yaml` sets `delay_seconds: 2.0` between requests and a descriptive `user_agent`.
**Put your actual email in it.** This is a government server; you are a student doing research;
identify yourself and go slowly. Getting your college IP blocked in week 1 would be an
unrecoverable, entirely self-inflicted wound.

---

## What's in here

```
config/
  settings.example.yaml     # portal URLs, rate limits, reconciliation tolerances
  delay_taxonomy.yaml       # 13 delay causes -> owning authority -> escalation
docs/
  label-spec.md             # the 4 prediction targets, defined precisely
  data-quality-rules.md     # DQ001-DQ012, BLOCKER vs WARN
  decisions/ADR-0001-panel-design.md
scripts/
  harvest_paimana.py        # discover + download every Flash Report, with manifest + SHA-256
  parse_report.py           # per-era PDF parsing, summary reconciliation
  leakage_test.py           # the shuffle test that catches time leakage
tests/
  test_harvest_links.py     # offline tests against a fixture
  run_tests.py              # minimal runner if pytest isn't installed
data/raw/                   # downloaded PDFs (gitignored)
data/interim/               # parsed intermediates (gitignored)
SOURCES.md                  # the research pack
```

---

## The four things that make this project credible

Most SIH teams will build a dashboard on one month of scraped data. These four choices are what
separate you from them. Each takes a day or less.

### 1. A panel, not a snapshot

One row per **project × month**. A snapshot tells you a project is late. A panel tells you *when
the lateness became visible* — and that is the only thing worth forecasting. It also gives you
every feature that matters: date-drift velocity, silent months, expenditure-progress divergence,
revision cadence. See `docs/decisions/ADR-0001-panel-design.md`.

### 2. Point-in-time features only

Every feature for month *M* uses only information printed on or before month *M*. This sounds
obvious and it is violated constantly, usually by a join that quietly pulls in a later revision.

`scripts/leakage_test.py` gives you two guards:

- `shuffle_time_check()` — shuffle the time index and retrain. If the shuffled score is close to
  the real one, your model is reading the future. **Run this before you believe any result.**
- `assert_feature_asof()` — hard-fails if any feature's source date is later than its as-of date.

A 0.94 AUC that collapses to 0.61 when you fix the leak, discovered at the finale, is the
single most common way this kind of project dies. Find it in week 1 instead.

### 3. Walk-forward validation, never a random split

Train on months ≤ T, test on T+1 … T+k, roll forward, repeat. A random train/test split on a
panel is meaningless: the same project appears on both sides, and you get a beautiful number that
predicts nothing. Judges who know time-series will ask. Judges who don't will believe your number
and you will have misled them, which is worse.

### 4. Calibration and intervals, not just accuracy

Report a reliability diagram and a Brier score, and put a conformal interval on every date
forecast. "P50 November 2027, P90 June 2028" is something an official can act on. "92% accuracy"
is not. See `SOURCES.md` §6.

---

## The targets

Defined precisely in `docs/label-spec.md`:

| ID | Target | Type |
|---|---|---|
| T1 | `slip_6m` / `slip_12m` — will the agency's stated date slip by ≥6 / ≥12 months? | binary, calibrated |
| T2 | `months_to_commissioning` | **right-censored** — needs survival methods |
| T3 | `final_cost_ratio` — P10/P50/P90 with conformal coverage | quantile regression |
| T4 | `months_past_original` | regression |

**T2 is where teams go wrong.** Ongoing projects have no completion date — they are censored, not
missing. Dropping them biases everything toward projects that finished, which are exactly the
projects that did not have the problem you are predicting. `SOURCES.md` §6.3 has the fix, and it
is simpler than it sounds: a discrete-time hazard model is just a logistic regression on your
project-month panel.

---

## First week

| Day | Goal | Done when |
|---|---|---|
| 1 | Harvest | Every Flash Report on disk, manifest complete, checksums recorded |
| 2 | Parse one report | Detail rows reconcile against that report's own summary totals |
| 3 | Parse all reports | < 2% rows unparsed, each failure logged with a reason |
| 4 | Build the panel | project × month table; identity resolution across OCMS/PAIMANA codes |
| 5 | Baseline | Logistic vs LightGBM, walk-forward, leakage test green |
| 6 | Intervals | Conformal coverage checked on held-out months |
| 7 | Slide 1 frozen | One sentence, one chart, one source |

Two parsers are needed: the reports changed format when PAIMANA replaced the old system in
September 2025. `scripts/parse_report.py` detects the era and branches. Do not try to write one
regex for both.

---

## Identity resolution (the unglamorous blocker)

Projects are identified differently across eras: legacy OCMS codes, PAIMANA project codes, PMGID.
Names drift ("Phase-II" becomes "Phase 2"). Before any modelling you need a stable entity ID that
survives the format change, or your panel will silently split one project into two half-length
series and every duration feature will be wrong.

Approach: exact code match first, then fuzzy name match within the same ministry and cost band
(`rapidfuzz`, pinned), then **manual review of the ambiguous residual.** Budget half a day.
Keep the mapping in a file you can hand-correct — it is your most valuable artefact and it is the
one thing nobody else will have.

---

## Honest scope note

The Flash Report data is **already public**. It needs no confidential computing. The TEE layer in
your architecture is for the production deployment — unpublished project entries, agency free-text
delay reasons, draft risk lists. Say that plainly; a judge who thinks you encrypted public PDFs
for show will discount everything else you claim. `SOURCES.md` §10.

---

## Licence / attribution

Data is Government of India material — check the terms on each portal before redistribution.
Redistribute derived analysis, not bulk copies of the source PDFs.
