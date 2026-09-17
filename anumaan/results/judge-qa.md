# ANUMAAN — Judge Q&A

This file answers the eight questions the SIH26103 judges are expected to
ask. Each answer points at the exact file, number, or experiment that backs
it. If an answer has no artefact yet, it reads **UNANSWERED** with the
backlog item that will close it.

Status legend:
- **ANSWERED** — backed by a checked-in artefact referenced below.
- **PARTIAL** — partial answer; gap documented.
- **UNANSWERED** — no artefact yet; closes at the listed milestone.

---

## 1. "PAIMANA already has analytics. What are you adding?"

**ANSWERED — RQ1 (forecast, not status).**
PAIMANA reports what each agency says the project status is. ANUMAAN
audits the agency's own forecast against its own historical slip record
and outputs a calibrated slip probability + interval for every ongoing
project. See `docs/label-spec.md` for the four targets we predict, and
`SOURCES.md` §3.2 for the framing MoSPI itself uses. The slide-1 sentence
is in `SOURCES.md` §1: descriptive ≠ predictive.

## 2. "How do I know your 70% means 70%?"

**ANSWERED on synthetic data; closes fully at D3 on real data.**
The current numbers come from `results/reliability_lightgbm.png` (10-bin
calibration diagram), `results/metrics.json` (Brier score + PR-AUC + the
leakage_check sub-object that records both real and shuffled PR-AUC),
and `scripts/train_t1.py` (the `shuffle_time_check` guard wired in).
Numbers quoted on the demo pages are copy-pasted from these files.

On **synthetic data** (current state): LightGBM PR-AUC = 0.155 vs base
rate 0.067; Brier 0.081; calibration diagram embedded on
`demo/honesty.html`. The `with_synthetic_leak` check reaches 0.985,
confirming the guard detects leakage if introduced.

On **real PAIMANA data** (closes at D3, 26 Sep): the same pipeline runs
against `data/raw/` once D1 lands, and the numbers above get replaced
with real ones in `results/paimana/` with the provenance block intact.

## 3. "Show me your baseline."

**UNANSWERED — closes at P5.**
P5 will run four baselines on identical walk-forward splits:
- always-majority (predict the prior class rate)
- sector base rate (predict the in-sector slip rate from training months)
- "current slip continues" (predict slip if the project is already late)
- regularised logistic regression

The fancy model (LightGBM) is reported alongside, *not* replacing, these.
The brief is explicit: "If ML does not beat the third baseline, report
that plainly."

## 4. "How do you know you're not reading the future?"

**ANSWERED on synthetic data; closes fully at D3 on real data.**
Three guards, all wired in `scripts/train_t1.py` and reported on
`demo/honesty.html`:
1. **Point-in-time features only.** Every feature for month M uses only
   data printed on or before M. The forward-looking columns
   (`slip_3m`, `slip_6m`, `slip_12m`) are explicitly excluded from the
   feature matrix inside `build_features()`.
2. **Leakage check.** The `leakage_check()` function runs three
   experiments: real pipeline PR-AUC, PR-AUC with a synthetic leakage
   feature added (must jump near 1.0), and PR-AUC with shuffled training
   rows (must match real). The check is recorded in
   `metrics.json["leakage_check"]` and reproduced verbatim on the
   honesty page. **Current synthetic result**:
   `real=0.137, with_synthetic_leak=0.985, shuffled_train=0.137, ok=True`.
3. **Walk-forward split only.** Temporal split at month 2025-01; no
   random splits anywhere in the pipeline. (Embargo for the
   label-horizon rule will be added in D2.)

## 5. "What about projects that never finished?"

**UNANSWERED — closes at P5 (T1 only).**
P5 trains T1 (slip_12m) on the entire panel including ongoing projects;
ongoing rows contribute as still-uncensored, slip-or-not-slip labels
evaluated at month t+12 against the future report. Per the brief, T2
(duration / hazard) is **cut** unless T1 ships first. The right-censoring
treatment is documented in `docs/label-spec.md` §T2; the model code in
`scripts/train_t1.py` does not use it.

## 6. "Which fields carry the signal?"

**UNANSWERED — closes at D5.**
D5 (28 Sep) will produce `results/paimana/ablation.csv` with five feature
families removed one at a time:
- date-drift velocity (cumulative months added since approval)
- expenditure-vs-physical-progress divergence
- revision cadence (months since last revision, count of revisions)
- ministry / sector
- cost band

Each family is tagged in `config/feature_families.yaml` as either
`report_visible`, `engineered_history`, or `external`. Until D5 ships,
the answer is **UNANSWERED — see D5 backlog**. The claim that an
ablation table exists is removed from `docs/model-card.md` until the
artefact is on disk; see `results/EVIDENCE.md` for the audit trail.

## 7. "What would make this model wrong?"

**PARTIAL.**
Known failure modes we test for:
- **Class imbalance**: brief rule #11 — operating threshold picked for a
  stated false-alert / missed-slip trade-off, documented in
  `docs/model-card.md` (P7).
- **Calibration drift on out-of-distribution months**: the reliability
  diagram (P5) is the guard. If the diagram bends away from the diagonal
  in a specific year or sector, we report it.
- **Reference class manipulation**: per `SOURCES.md` §6.4, agencies may
  shift initial estimates upward once they anticipate an uplift. The
  base-rate layer (P5 ministry × sector table) is the guard: an estimate
  that beats the base rate by too much is flagged.
- **Time-leakage in a feature**: the shuffle_time_check + as-of guards
  (P5) catch this before any number is reported.

Not yet tested (backlog):
- **Coverage failure under agency turn-over or re-organisation**: the
  panel resolves entities by code, so a re-organisation that breaks the
  code linkage will produce a new entity. P5 will report entity-survival
  statistics so this risk is visible.
- **What happens during a moratorium month (e.g. election)**: the parser
  will see fewer reports; the panel will have gaps. P5 will document.

## 8. "Who acts on this on Monday, and what do they do differently?"

**PARTIAL.**
The `config/delay_taxonomy.yaml` already maps each delay cause to an
owning authority + escalation path. For each flagged project ANUMAAN
shows: (a) agency's stated date vs ANUMAAN's P50/P90, (b) the delay cause
matched against the taxonomy's 13 labels, (c) the owning authority for
that cause. So a Monday user sees "this project is at 78% slip risk by
December; the reason matches `land_acquisition`; the owning authority is
the State Revenue Department — here is the link to the R&R status on
PARIVESH."

What is not yet built:
- The **UI surface** that renders this (P6, 28 Sep).
- The **operational handoff**: who in the State Revenue Department reads
  the alert, what they do with it, and how the action is logged back.
  This is a deployment question, not an ML one, and is documented in
  `docs/demo-runbook.md` (P7) as a stakeholder list rather than a
  feature.

---

Last updated: 16 Sep 2026. P5 closes most of the UNANSWERED entries.