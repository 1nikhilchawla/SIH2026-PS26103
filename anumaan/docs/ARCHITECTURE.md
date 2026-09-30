# ANUMAAN - complete architecture

Every component: what it is, why it exists, and what changed because of it.
Numbers here were produced by the commands named beside them.

---

## 0. The shape of the thing

```
PAIMANA portal (MoSPI)
      |
      | 1. harvest_paimana.py          JSON endpoints, polite egress
      v
data/raw/*.pdf + manifest.csv          32 PDFs, SHA-256 each
      |
      | 2. verify_corpus.py            fail-closed integrity gate
      v
      | 3. parse_paimana.py            era from CONTENT, reconcile vs printed totals
      v
data/interim/paimana/*.rows.json       17,010 rows from 11 reports
      |
      | 4. build_panel.py              point-in-time features + labels
      v
results/paimana/panel.csv              17,010 rows x 2,195 projects x 11 months
      |
      +-- 5. train_slip.py             9 walk-forward folds, 3 baselines, 2 leak controls
      +-- 6. train_cost.py             same harness, different target
      +-- 7. diagnose_cost_target.py   why the cost target fails
      +-- 8. eval_slip.py              precision@k, calibration, SHAP export
      |
      v
results/paimana/*.json                 the evidence a judge can re-run
      |
      +-- 9.  app/main.py              live API + UI, trains in-process
      +-- 10. build_demo_paimana.py    static pages that need no server
```

Two rules shape all of it:

1. **Nothing enters the panel unless the source report proves itself.**
2. **Nothing that looks forward is ever a feature.**

Everything below is downstream of those two sentences.

---

## 1. Harvest - `scripts/harvest_paimana.py`

**What.** Pulls the monthly Flash Report PDFs from the PAIMANA portal and
records per file: report id, financial year, URL, SHA-256, byte size, fetch
timestamp, status. Written to `data/raw/manifest.csv`.

**Why it exists.** The corpus IS the project. If the inputs are not pinned,
every number downstream is unfalsifiable - a reviewer cannot tell whether a
figure moved because the model improved or because the file changed.

**Design decision that mattered.** The portal serves reports through JSON
endpoints (`/ReportPage/GetFinancialYearList`, `/ReportPage/Report`,
`/ReportPage/ArchiveReport`) rather than static links. Harvesting those
directly is faster and far less brittle than scraping rendered HTML. Egress is
deliberately polite: one request at a time, identified user agent.

**What it changed.** 32 PDFs on disk with a hash apiece, which makes
`verify_corpus.py` possible and makes "we used the official data" checkable
rather than asserted.

---

## 2. Verify - `scripts/verify_corpus.py`

**What.** Recomputes SHA-256 for every manifest row, checks the file exists and
begins with `%PDF-`, writes `results/paimana/manifest_verification.json`, and
exits non-zero on any mismatch.

**Why it exists.** This check previously ran as an inline one-off; its output
recorded `generated_by: "(inline) manifest SHA-256 verification"` - an artefact
nobody could regenerate. The live app reports its `sha_ok` count on screen, so
an unreproducible artefact was feeding a user-facing claim.

**What it changed.** 32/32 verified, exit 0, and the claim became a pipeline
step instead of a memory. It is step 1 of `run.ps1`, so a corrupted corpus
stops the run before anything is parsed.

---

## 3. Parse - `scripts/parse_paimana.py`

The hardest and most important component.

**What.** Turns a Flash Report PDF into project rows. Detects the report era
from the **document's own content**, not the filename. Extracts the "All
Ongoing Projects" table with an 8-column model, reading packed cells such as
`Original/Target DoC (Revised DoC)` and `Original Cost (Revised Cost)`.

**Why content-based era detection.** The manifest carries an `era` column, but
it is assigned by a filename heuristic. Trusting it would mean a renamed file
silently parsed with the wrong layout. The parser ignores it.

**The reconciliation gate - the single most important design choice.** A report
is admitted only if its parsed rows re-add to the totals the report itself
prints:

- parsed row count == printed "projects on monitor"
- sum of costs == printed cost total (within 1%)
- sum of expenditure == printed expenditure total
- zero unparsed non-blank cells

If any check fails the report is **rejected**, not partially used. Zero parsed
rows cannot pass by default.

**Why fail closed.** A silent parse error is the worst failure mode here: it
produces plausible numbers that are wrong, and nothing downstream can detect
it. Reconciling against the document's own arithmetic turns a silent error into
a loud one.

**What it changed.** 11/11 PAIMANA-era reports reconcile exactly, with **0
unparsed cells**. The 21 older OCMS-era reports are rejected as "not a
PAIMANA-era report" and reported as unparsed rather than half-read.

**The bug that mattered most.** Ministry and sector group rows carry their
label in ONE cell and leave the other seven blank. A blank-cell trim ran first
and collapsed them to a single cell, so they were quarantined as
`wrong_column_count`. Effect: `ministry` was **null on all 17,010 rows**, which
silently made the `ministry_base_rate` baseline a duplicate of the global base
rate - a baseline that could not lose.

Fixed by reading group rows *before* the trim. Result: ministry populated on
17,010/17,010 rows, **17 distinct ministries - exactly the count each report's
own summary prints** - and quarantine fell to 0 on 10 of 11 reports.
Downstream: LightGBM 0.6609 -> **0.6791**, ministry baseline became real
(0.1830 -> 0.2157), precision@50 0.880 -> **0.960**, lift 4.81x -> **5.24x**.

---

## 4. Panel - `scripts/build_panel.py`

**What.** Joins the reconciled reports into one row per project per month.

**Identity.** `entity_id` is the portal's project code, falling back to
`ministry::project_name` when a code is missing, so a missing code cannot
collapse two projects into one.

**Point-in-time features.** Computed from this row and *earlier* rows of the
same project only: cumulative drift, months to target, months past original,
expenditure ratio, cost overrun ratio, spend-vs-progress divergence, drift
change, revisions so far, months since last revision, months observed.

**Labels - the only forward-looking columns.** `slip_next`, `cost_up_next`,
`delta_cost_ratio_next`, `label_horizon_months`. Named as labels, dropped from
the feature matrix by name, and an assertion fails the run if one survives.

**Gap handling.** Labels are defined only where the next report is the next
consecutive month. Where the corpus has a hole the label is left undefined
rather than stretched across it - a stretched label would quietly become a
multi-month horizon wearing a one-month name.

**What it changed.** 17,010 rows, 2,195 projects, 11 months (2025-09 to
2026-07), and the finding the whole product rests on: **19.2%** of labelled
project-months see the agency move its own stated completion date in the very
next report.

---

## 5. Slip model - `scripts/train_slip.py`

**What.** Predicts `slip_next`. Walk-forward: train on months < T, test on T,
across 9 folds.

**Three baselines, deliberately.** `always_base_rate`, `ministry_base_rate` and
`slipped_last_month` (persistence). The third is the one a reviewer always
asks: *if I simply assume a project that moved its date last month moves it
again, what does your model add?*

**Two leakage controls on every build.** Shuffled labels must collapse towards
the base rate; a deliberately planted label column must saturate. Current:
shuffled 0.1717, real 0.6791, planted 1.0000.

**Why controls rather than trust.** Earlier in this project a shuffle-time
check was shown, with runnable evidence, to be unable to separate a clean
pipeline from a leaky one. Controls that can actually fail are the only ones
worth running.

**What it changed.** LightGBM 0.6791 against a best baseline of 0.2814 - a 2.4x
edge on the held-out month, with Brier 0.0959 against 0.1496 for the base rate.

---

## 6-7. Cost model and its diagnostic

**What.** `train_cost.py` runs the identical harness on `cost_up_next`.
`diagnose_cost_target.py` sweeps the threshold that defines an overrun.

**Why the diagnostic exists.** The obvious response to a weak cost model is to
lower the threshold until positives appear - that is tuning towards a
conclusion. The sweep tests it instead: dropping from 0.5% to **0%** moves
positives only 114 -> 136, because **98.55%** of project-months carry exactly
zero change in revised cost. Only 200 projects ever change it, and 88 of those
136 changes land in a single month.

**What it changed.** We do not ship a cost forecast. On the one informative
fold a ministry base rate (0.1119) beats LightGBM (0.0923). That is stated on
the honesty page, in the PRD's out-of-scope section, and in the deck.

---

## 8. Evaluation - `scripts/eval_slip.py`

**What.** Produces the numbers a ministry can act on: precision, recall and
lift at inspection budgets; a 10-bin reliability table; and per-project SHAP
attributions (`shap_slip.json`, top 200 by risk).

**Why precision@k rather than only PR-AUC.** PR-AUC tells a ministry nothing.
"Inspect 50 projects and you catch 48 of the 257 that will slip, against 9 at
random" is a decision. Same model, comprehensible units.

**Why SHAP is exported rather than computed ad hoc.** The static pages and the
live app then render the *same* attributions from the same fitted model, so two
surfaces cannot disagree.

---

## 9. Live service - `app/main.py` + `app/panel_adapter.py`

**What.** FastAPI. Loads the panel, trains in-process at startup (1.6 s,
260 MB resident), serves 8 JSON endpoints and the watchlist UI.

**Why an adapter exists.** The app was written against the synthetic panel
(`month`, `stated_doc`, `slip_12m`); the real panel uses `report_month`,
`target_doc`, `slip_next`. Faking synthetic column names onto real data would
have put a 12-month label over a 1-month number. The adapter normalises both
schemas and **detects the source from the panel's columns, never the
filename**, so a renamed file cannot make synthetic data present itself as
real.

**The horizon block.** Every response carrying a probability also carries
`target`, `horizon_months`, `horizon_label` and `target_definition`, and the UI
renders the label the API sends. A one-month number physically cannot appear
under a twelve-month heading.

**What it changed.** The banner is green, the ministry filter lists all 17
ministries, the what-if endpoint re-scores live (drift 0 / 24 / 99 gives
0.8592 / 0.9054 / 0.9114), and the app reproduces `train_slip.py`'s final fold.

**Honest caveat.** The synthetic `p * 12 * 0.6` drift formula was removed. The
magnitude shown now is the observed distribution of real date moves in the
training window (median +3 months, p90 +15.9, from 1,752 observed moves) and is
labelled as data, not model output.

---

## 10. Static demo - `scripts/build_demo_paimana.py`

**What.** Renders `demo/paimana/{index,audit,honesty}.html` from the artefacts
on disk. No server required.

**Why both a live app and static pages.** A demo that depends on a running
process fails at the worst possible moment. The static pages open from a file.

**What it changed.** The honesty page was shipping literal `{lab:,}` and
`{panel_path}` text to the reader and asserting `Status: PASS` on the leakage
guard as a hardcoded string. The status is now computed from the three numbers,
and the build **fails** if any placeholder survives.

---

## 11. Config, ops and quality

| File | Why it exists |
|---|---|
| `config/delay_taxonomy.yaml` | Maps a delay cause to an owning authority and escalation path, so an alert routes somewhere |
| `config/competitors.yaml` | Benchmark rows with `source_url`, `source_date` and a `verified` flag; unverified rows are labelled, never quoted as fact |
| `run.ps1` | One command, 9 steps, stops on the first failure so a broken step cannot produce a page of stale numbers |
| `Dockerfile` | `python:3.14-slim` + `libgomp1`; checks the panel schema **at build time** so a bad panel fails the build, not the first request |
| `railway.json` | Dockerfile builder, health check `/api/health`, restart on failure |
| `requirements.txt` | Re-pinned to the versions actually installed - it previously pinned versions never used here and omitted `fastapi`/`uvicorn` that `app/main.py` imports |
| `tests/` | 45 tests, mostly guarding the parser |

---

## 12. What the architecture refuses to do

- No `train_test_split`, `KFold` or `shuffle=True` in the modelling path.
- No `verify=False` anywhere.
- No `errors="coerce"` without a follow-up null count.
- No claim of coverage the corpus does not support: the panel is 11 months, so
  the horizon is one month and every screen says so.
- No number on a slide that no command in this repository produced.
