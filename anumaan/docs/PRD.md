# ANUMAAN - Product Requirements Document

Problem statement: **SIH26103** - predictive analytics for central-sector
infrastructure project monitoring (MoSPI / PAIMANA).
Team: **The Raftaar Titans**.

Every quantity below is read from an artefact in this repository at the time
this document was generated. Regenerate with `./run.ps1`.

---

## 1. The problem, in one sentence

PAIMANA publishes what a project's completion date **is** today. Nobody is told
which of those dates is **about to move**.

That matters: **19.2%** of 10,463
labelled project-months see the agency push its own stated completion date out
in the very next monthly report.

## 2. Who it is for

| User | Today | With ANUMAAN |
|---|---|---|
| Ministry monitoring cell | Reads a monthly status list of ~2,195 projects | Gets a ranked shortlist of the dates about to move |
| MoSPI / PAIMANA analyst | Reports the current position | Can audit each agency's forecasting record over time |
| Reviewer or auditor | Has no way to challenge a date | Sees the exact source rows and the model attribution behind each score |

## 3. What it does

1. **Harvests** the official monthly Flash Report PDFs and pins each by SHA-256
   (32/32 verified).
2. **Parses** them, and rejects any report whose rows do not re-add to the
   totals printed inside that same report.
3. **Builds** a project x month panel: 17,010 rows,
   2,195 projects, 11 months
   (2025-09 to 2026-07).
4. **Forecasts** `slip_next` - will this project state a later completion date
   in the next report?
5. **Ranks** projects against an inspection budget and explains every score.

## 4. Scope

**In scope.** One-month time-overrun forecasting; ranked watchlist; per-project
audit with evidence and SHAP; calibration and honesty screen; JSON API;
deployable container.

**Deliberately out of scope.**

- **Cost-overrun forecasting.** Tested and reported as a negative result:
  98.6% of project-months carry exactly zero change in revised cost,
  and on the only informative fold a ministry base rate
  (0.1119) beats the model
  (0.0923).
- **Horizons beyond one month.** The panel is 11 months long; a
  twelve-month claim would not be supportable.
- **The 21 pre-PAIMANA (OCMS-era) reports.** Not parsed yet, and they
  contribute to nothing in this document.

## 5. Requirements

### 5.1 Functional

| ID | Requirement | Verified by |
|---|---|---|
| F1 | Ingest official PDFs, recording URL, SHA-256, size and fetch time | `data/raw/manifest.csv`, `scripts/verify_corpus.py` |
| F2 | Reject any report that fails reconciliation | `results/paimana/reconciliation.csv` |
| F3 | Build a point-in-time panel with no forward-looking feature | `scripts/build_panel.py` |
| F4 | Forecast P(date moves next report) per project per month | `metrics_slip.json` |
| F5 | Rank projects for a stated inspection budget | `precision_at_k.json` |
| F6 | Explain each score with source rows and SHAP values | `shap_slip.json` |
| F7 | Publish calibration and leakage evidence in the product | `reliability_slip.json` |
| F8 | Serve a live API and UI trained in-process from the panel | `app/main.py` |

### 5.2 Quality bars, all currently met

| ID | Bar | Actual |
|---|---|---|
| Q1 | Beat every trivial baseline on the held-out month | 0.6791 vs 0.2814 / 0.2157 / 0.1830 |
| Q2 | Shuffled-label control collapses towards the base rate | 0.1717 (base 0.1830) |
| Q3 | Planted-leak control saturates | 1.0 |
| Q4 | Publish a calibration curve | 10 bins, Brier 0.0960 |
| Q5 | Reproducible in one command | `./run.ps1`, 45/45 tests green |

### 5.3 Non-functional

Cold start under two seconds (model trains in-process in 1.6 s); 260 MB
resident; no database; no external API call at serve time; no new data
collection and no agency co-operation required.

## 6. Success metrics

| Metric | Definition | Current |
|---|---|---|
| Catch rate at budget 50 | slips found in the top 50 ranked projects | **48 of 257** |
| Lift over random | catch rate / random catch rate at the same budget | **5.24x** |
| Recall at budget 250 | share of all slips found | 60.7% |
| Ranking quality | PR-AUC on the held-out month | 0.6791 |
| Calibration | Brier score | 0.0960 |

## 7. Risks and mitigations

| Risk | Mitigation in place |
|---|---|
| Portal changes the PDF layout | Era detected from content; a new layout fails closed rather than parsing wrongly |
| Silent parse corruption | Reconciliation against the report's own printed totals |
| Time leakage inflating results | Walk-forward only, plus two controls on every build |
| Over-claiming coverage | The 21 unparsed reports are named on the honesty page and here |
| Drift as the corpus grows | Re-run `./run.ps1`; artefacts, figures and these documents regenerate |

## 8. Status

Working today: harvest, verify, parse, panel, slip model, evaluation, SHAP,
static demo pages, live API and UI, container build.

Next: parse the 21 OCMS-era reports to extend the panel beyond
11 months - the single change that would support a longer
forecast horizon.
