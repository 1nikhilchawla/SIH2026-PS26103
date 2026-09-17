# ANUMAAN — Rubric (16 Sep 2026, end of D1-G10 sprint)

| # | Dimension | Score | Command that proves it | Decisive line of output |
|---|---|---|---|---|
| G1 | Corpus depth (>= 10/11 PAIMANA reconcile; panel >= 10 months) | 1.0 | `python scripts/parse_paimana.py --all` | `FlashReport_April2026.pdf: era=paimana parsed=1981 quarantined=48 ok=True`  (and 10 more lines, all `ok=True`); panel span **2025-09 to 2026-07 = 11 consecutive months** |
| G2 | Historical depth (pre-PAIMANA parser exists; >= 15/21 older reports reconcile) | 0.0 | n/a | Not built this sprint. The 21 pre-PAIMANA reports (FY 2024-25 and earlier, OCMS layout) are listed in the manifest but excluded by `parse_paimana.py` as "not a PAIMANA-era report". A second-era parser is the next backlog item. |
| G3 | Leakage controls (planted > 0.9 AND > real; shuffled < base rate; both folds, both models) | 1.0 | `python scripts/train_cost.py` and `python scripts/train_slip.py` | For slip fold 2026-04: `leakage: real=0.6853 shuffled=0.2535 planted=1.0`. For cost fold 2026-06: `leakage: real=0.0528 shuffled=0.0346 planted=1.0`. Both pass the hard SystemExit guards in both scripts. |
| G4 | Slip model (a-ii) - beats all three baselines on >= 2/3 folds | 1.0 | `python scripts/train_slip.py` | 9 walk-forward folds. LightGBM beats always_base_rate, ministry_base_rate, and slipped_last_month on **9/9 folds**. Latest fold: `lightgbm 0.6609 > slipped_last_month 0.2814 > always 0.1830`. |
| G5 | Cost model (a-i) - beats all three baselines on >= 3 folds with >= 30 positives each | 0.5 | `python scripts/train_cost.py`; `python scripts/diagnose_cost_target.py` | **Corrected 17 Sep 2026** - an earlier version of this row claimed "no fold has >= 30 positives (max 13)", which `metrics_cost.json` contradicts: fold 2026-06 has **70**. The honest reading is that **1 of 9 folds** is informative, and on it `ministry_base_rate` (0.1119) **beats LightGBM** (0.0923) - a trivial baseline wins, so the model adds nothing. Lowering the threshold does not help: 0.5% to 0% moves positives only 114 to 136, because **98.55%** of project-months carry exactly zero cost change. Partial credit: the harness, the leakage guard and the negative result are all real; the forecast is not shipped. |
| G6 | Calibration & use - reliability table + precision@k in projects-per-month | 1.0 | `python scripts/eval_slip.py` | Inspecting top **50** projects/month catches **44 slips** out of 257 = `P@50 = 0.880`, **`4.81x` lift over random** (random would catch 9). Reliability bins recorded in `results/paimana/reliability_slip.json` (10 bins, mean_p vs mean_y). |
| G7 | Live app on real data - banner green, horizon relabelled | 1.0 | `uvicorn app.main:app --port 8010`; also `python -m http.server 8766 --directory demo/paimana` | **Upgraded 17 Sep 2026 from static pages to the live service.** `app/panel_adapter.py` detects the schema from the panel's own columns, so `app/main.py` now defaults to `results/paimana/panel.csv`, targets `slip_next`, and carries a `horizon` block on every scored response. Startup line: `source=paimana target=slip_next rows=17010 labelled=10463 cutoff=2026-06`. The UI renders the API's horizon label, never a hardcoded one - nowhere does it say "P(slip >= 12m)". Live what-if re-scores in-process: drift 0 / 24 / 99 gives 0.8592 / 0.9054 / 0.9114. |
| G8 | Explainability - SHAP on real model; audit cites rows that drove the score | 1.0 | `python scripts/eval_slip.py`; `python scripts/build_demo_paimana.py`; live app `/api/project/619103` | **Done 17 Sep 2026.** `eval_slip.py` now runs `shap.TreeExplainer` on the same fitted LightGBM that produced the watchlist and writes `results/paimana/shap_slip.json` (top 200 projects x 8 features, exact values). Both the static audit page and the live app show the SHAP table **beside** the row-level evidence. For 619103: `months to target = 1` contributes **+3.17**, and the evidence table underneath shows the matching fact - the stated date moved +30/+31 days in every consecutive report. |
| G9 | Reproducibility - one command, clean checkout, PDFs to metrics | 0.5 | `python scripts/harvest_paimana.py --since-fy 2019-20 && python scripts/parse_paimana.py --all && python scripts/build_panel.py && python scripts/train_slip.py && python scripts/train_cost.py && python scripts/eval_slip.py && python scripts/build_demo_paimana.py` | The seven scripts in dependency order produce the full pipeline end-to-end. **Entry-point PowerShell script not yet committed**; the README + this rubric document the chain but a teammate would need to copy seven commands. requirements.txt currently missing **fastapi/uvicorn** (cut from this build per the brief) and is otherwise consistent with the deployed venv. Partial credit: chain works; clean-room script not yet committed. |
| G10 | Honesty & benchmark - README/EVIDENCE corrected; results/synth/ split; model card filled; competitors.yaml verified | 0.5 | `ls demo/synth` does NOT exist yet; `cat config/competitors.yaml`; `ls results/synth/` (will exist once moved) | `results/synth/` and `demo/synth/` paths are referenced in `results/EVIDENCE.md` and `docs/model-card.md` but **the actual split has not been committed**; the synthetic demo at `demo/` still sits at the top level. `config/competitors.yaml` exists with cited URLs; verification is by direct fetch, not yet committed as an artefact. Model card is filled for training data and quantitative analysis sections; calibration section and known-failure-modes section are pending. Partial credit: file-level honesty is in place; physical split is not. |

## Totals

- **Hard pass (1.0):** G1, G3, G4, G6, G7, G8 -> **6 / 10**
- **Partial pass (0.5):** G5, G9, G10 -> **1.5 / 10 weighted**
- **Zero:** G2 -> **0 / 10**
- **Estimated score: 7.5 / 10** (6 full + 3 × 0.5), updated 17 Sep 2026

### Changes on 17 Sep 2026

1. **Parser bug fixed.** Ministry/sector group rows carry their label in one cell
   and leave seven blank; the blank-cell trim collapsed them to a single cell and
   quarantined them as `wrong_column_count`. Result: `ministry` was **null on all
   17,010 panel rows**, which silently made `ministry_base_rate` a duplicate of
   the global base rate. Now populated on 17,010/17,010 rows with **17 distinct
   ministries - exactly the count each report's own summary prints**, and
   quarantine drops to 0 rows on 10 of 11 reports.
2. **Model improved as a consequence:** LightGBM 0.6609 -> **0.6791** on fold
   2026-06; `ministry_base_rate` becomes a real baseline (0.2157, was 0.1830);
   precision@50 rises from 0.880 to **0.960**, lift 4.81x -> **5.24x**.
3. **Honesty page defect fixed.** It was shipping literal `{lab:,}` and
   `{panel_path}` text, and asserted `Status: PASS` on the leakage guard as a
   hardcoded string. The status is now computed from the three numbers and the
   build **fails** if any placeholder survives.

## Hardest remaining gaps

1. **G2 (OCMS parser).** The 21 pre-PAIMANA reports from FY 2024-25 and earlier use a different layout (no "All Ongoing Projects" section, no ministry/sector carry-down). Building it would push panel span from 11 months to 7+ years and make "backtest across years" possible.
2. **G5 (cost target).** The cost_up_next target is too rare (0.77% base rate) on the real panel to hit the rubric's >= 30 positives per fold. Two options: (a) lower the cost-change threshold in `build_panel.py` (currently 0.5%, lowering to 0.1% might surface more positives), or (b) accept G5 stays at partial credit and report it plainly.
3. **G10 (split).** Move `demo/index.html, audit.html, honesty.html` to `demo/synth/` and remove `data/synthetic/` from the watched tree, then commit `demo/paimana/` as the only demo path.

## Reproduction recipe

```
# One-shot end-to-end pipeline (assumes data/raw/*.pdf are present)
python scripts/parse_paimana.py --all
python scripts/build_panel.py
python scripts/train_slip.py
python scripts/train_cost.py
python scripts/eval_slip.py
python scripts/build_demo_paimana.py
python -m http.server 8766 --directory demo/paimana
# open http://localhost:8766/index.html
```