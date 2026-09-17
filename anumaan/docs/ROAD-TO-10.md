# ANUMAAN — road to 10/10 (paste this as the next session's prompt)

You are continuing ANUMAAN (SIH 2026, problem statement SIH26103, MoSPI / PAIMANA
infrastructure project forecasting). The MVP currently scores **4.5 / 10** against the
problem statement. Your job is to take it to 10/10 by closing ten named gaps, in order,
each with runnable evidence.

---

## STANDING LAWS (unchanged, still binding)

**Law 1 — Do not hallucinate.** Never write a number you did not produce. Never reference
an artefact that does not exist. Never invent a citation, dataset, field name or statistic.
If something is not public, write "not public". If you cannot verify something, write
"not verified". Quote actual stdout, not a paraphrase of it.

**Law 2 — Do not leak.** Every feature for month M uses only data printed on or before M.
Walk-forward splits only. If you introduce `train_test_split`, `KFold`, or `shuffle=True`
anywhere in the modelling path, you have broken the project. Fit every transformer inside
the training window. Aggregates expand through time. Censored rows stay in.

**Law 3 — It must run, not compile.** Run the exact command and paste the actual
stdout/stderr. No `try/except: pass`. No `errors="coerce"` without a follow-up null count.
No stub that returns a plausible value. "Imports cleanly" is not evidence.

**Provenance.** Every generated artefact carries `data_source`, `n_projects`, `n_months`,
`panel_span`, `generated_at`, `generated_by`. Never overwrite a synthetic artefact with a
real one under the same filename — synthetic lives in `results/synth/`, real in
`results/paimana/`. Never set `verify=False` anywhere, ever.

**Still cut, do not build:** TEE / Nitro narrative, LLM assistant, conformal intervals,
survival T2, CUF schema reverse-engineering, any claim of two-decade or 1,981-project
empirical coverage that the corpus does not support.

---

## VERIFIED BASELINE — this is what actually exists today

Do not re-derive these. Do not contradict them without re-running the command that produced
them and pasting the new output.

| Fact | Value | Where |
|---|---|---|
| Corpus | 32 PDFs, all SHA-256 verified | `results/paimana/manifest_verification.json` |
| PAIMANA-era reports | 11 of 32 | `scripts/parse_paimana.py` |
| Reports that reconcile | **5** — Nov 2025, Apr/May/Jun/Jul 2026 | `results/paimana/reconciliation.csv` |
| Reports that fail | 6 — Sep/Oct/Dec 2025, Jan/Feb/Mar 2026 | same |
| Pre-PAIMANA-era reports | 21, **no parser at all** | — |
| Rows parsed | 16,699 | — |
| Panel | 8,413 rows, 2,155 projects, 5 months | `results/paimana/panel.csv` |
| `slip_next` base rate | 0.2102 on 4,501 labelled rows | `results/paimana/panel_provenance.json` |
| `cost_up_next` base rate | 0.0134 on 5,508 labelled rows | same |
| Cost model, fold 2026-06 | LightGBM PR-AUC 0.0528 vs base rate 0.0404, 70 positives | `results/paimana/metrics_cost.json` |
| Cost model, fold 2026-05 | 1 positive — uninformative, do not quote | same |
| App data source | **synthetic**, banner correctly red | `app/main.py`, `ANUMAAN_PANEL` unset |
| Tests | 45/45 pass | `python -m pytest -q` |

**Three known defects, already diagnosed, not yet fixed:**

1. The planted-leak control in `scripts/train_cost.py` returns *exactly* the real PR-AUC on
   both folds (0.000852 and 0.05277). A deliberately planted label column must push PR-AUC
   towards 1.0. It does not, so that control currently proves nothing.
2. The 6 failing reports fail because pdfplumber's line-based table extractor returns zero
   rows on some pages (September 2025 page 50: `text_rows=22, table_rows=0`). It is not a
   column-model problem — those reports show 0 unparsed cells where extraction succeeds.
3. The app's model targets `slip_12m`; the real panel's label is `slip_next` (1 month).
   Pointing `ANUMAAN_PANEL` at the real panel without relabelling the horizon in the UI
   would put "P(slip >= 12m)" over a number that means something else — a Law 1 violation.

---

## THE RUBRIC — ten points, one per dimension

Score 1 point only when its **gate** passes with pasted output. Partial credit is 0.5 and
must be justified in writing. At the end, write `docs/RUBRIC.md` with one row per dimension:
dimension, score, the command that proves it, and the decisive line of its output.

| # | Dimension | Gate for the point |
|---|---|---|
| G1 | Corpus depth | >= 10 of 11 PAIMANA reports reconcile; panel has >= 10 consecutive months |
| G2 | Historical depth | Pre-PAIMANA-era parser exists; >= 15 of the 21 older reports reconcile |
| G3 | Leakage controls | Planted-leak control jumps above 0.5 PR-AUC; shuffled control collapses to base rate; both folds; both models |
| G4 | Slip model (a-ii) | Walk-forward on the real panel beats all three baselines on >= 2/3 of folds |
| G5 | Cost model (a-i) | Same, on >= 3 folds with >= 30 positives each |
| G6 | Calibration & usefulness | Reliability table + precision@k where k is a realistic inspection budget, stated in projects-per-month |
| G7 | Live app on real data | `ANUMAAN_PANEL=results/paimana/panel.csv`, banner green, horizon relabelled everywhere |
| G8 | Explainability | SHAP on the real model; per-project audit cites the actual rows that drove the score |
| G9 | Reproducibility | One command, clean checkout, PDFs to metrics; `requirements.txt` complete; tests green |
| G10 | Honesty & benchmark | README/EVIDENCE corrected; `results/synth/` split; model card filled; every competitor row either verified or labelled unverified |

---

## WORK ORDER — do these in sequence, do not skip ahead

### G3 first (it is a gate on everything downstream)

Fix the planted-leak control before you trust any model number. Hypothesis to test first:
`fit_predict` reindexes the test matrix to the training columns somewhere, or LightGBM's
column handling drops the appended `__leak__` column, so the model never sees it. Prove the
cause by printing the column list and the fitted feature importance of `__leak__`, not by
guessing. Then make the control a hard assertion: if planted <= 2x real, `raise SystemExit`.
Paste both folds' three numbers after the fix.

### G1 — the 6 failing PAIMANA reports

Add a per-page fallback in `scripts/parse_paimana.py`: when the line-based extractor returns
zero rows for a page that has text, reconstruct rows from word x-positions. Do not loosen
`COUNT_TOLERANCE` or `COST_TOLERANCE_PCT` to make reports pass — fail-closed reconciliation
against the report's own printed totals stays exactly as it is. Re-run `--all`, paste the
reconciliation table for all 11.

Then rebuild the panel. A 10-11 month panel changes everything downstream: more folds, more
positives, and `cost_up_next` stops being a 1-positive-per-fold problem.

### G4 / G5 — rerun both models on the deeper panel

Report baselines first, model second. If the model does not beat `always_base_rate`,
`ministry_base_rate` and the naive carry-forward baseline, say so plainly — a weak result
honestly reported is worth more than a tuned one. Add a third baseline for slip:
"project slipped last month" (persistence). It is the baseline a reviewer will ask about.

### G6 — make the number decision-useful

A PR-AUC does not tell a ministry anything. Produce: if you inspect the top 50 projects per
month, how many of the roughly 380 that will slip do you catch, versus the roughly 10 you
would catch by inspecting 50 at random? That single sentence, with real numbers, is the
strongest slide in the deck. Add the reliability table (predicted bucket, n, mean predicted,
observed).

### G7 — flip the app to real data

Switch the app's target to `slip_next`, relabel the horizon in every place the UI states a
horizon, flip the banner to green via `_data_source()`, and re-verify the what-if endpoint
returns *different* probabilities for different drift inputs. Screenshot the green banner.
If any tab still shows a synthetic-only artefact, either wire it to real data or remove the
tab — do not leave a mixed screen.

### G8 — explainability that cites evidence

The project audit must name the rows it used: "target date moved from 2027-03 to 2027-09
between the April and May reports" is evidence; "cumulative_drift_months contributed +0.08"
is a SHAP value. Show both, and label which is which.

### G2 — the older 21 reports

Only after G1-G8 are green. Content-based era detection already exists; add the second-era
layout. This is what turns an 11-month panel into a multi-year one, and it is the difference
between "we forecast next month" and "we backtest across years". Do not claim multi-year
coverage anywhere until this passes.

### G9 / G10 — last, and non-negotiable

- `requirements.txt`: re-add `fastapi`, `uvicorn`; pin everything; verify in a clean venv.
- One entry-point script (PowerShell, since `make` is unavailable here) running
  harvest, parse, reconcile, panel, train, metrics — and paste its full output.
- Move synthetic artefacts under `results/synth/`; correct `README.md` and
  `results/EVIDENCE.md` where they still say `data/raw/` is empty.
- Fill the model card: target definition, what it is **not**, horizon, base rate, folds,
  known failure modes, and the reports not yet parsed.
- `config/competitors.yaml`: PAIMANA, nPlan and Andric are verified by direct fetch. PMG and
  Oracle Primavera are **not verified** — either verify them by fetching the source and
  recording the date, or mark `verified: false` and show that on screen. Do not quote a
  competitor number you have not fetched.

---

## STOP CONDITIONS

Stop and report instead of continuing if any of these happen:

- The shuffled-label control does not collapse towards the base rate. That means a feature
  sees the future. Fix it before producing another metric.
- A reconciliation "passes" with zero parsed rows, or with fewer than 2 checks.
- A panel month appears with a label horizon other than exactly 1 month.
- You are about to write a number into a slide, the README, or the UI that no command in
  this repo produced.

## FINAL OUTPUT

1. `docs/RUBRIC.md` — ten rows, each with score, command, decisive output line.
2. A one-paragraph honest summary: what the model does, on how many real projects and
   months, how much better than the base rate, and the three biggest things it still
   cannot do.
3. The single strongest true sentence in the project. Right now that sentence is:
   *"21.0% of real monitored projects push their stated completion date out in the very next
   monthly report — and PAIMANA does not tell anyone which ones."*
   If your work produces a stronger true one, replace it.
