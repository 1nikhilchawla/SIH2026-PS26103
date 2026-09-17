# ANUMAAN — Demo Runbook

Status: scaffold. Filled at P7 (29 Sep) once the snapshot is rehearsed.

The demo currently builds from `data/synthetic/panel.csv` (synthetic
panel, see `results/EVIDENCE.md`). At P7 it will be replaced by a fixed
checked-in snapshot under `data/snapshot/` (built at P5 by
`make snapshot`). It runs offline. The total live path is budgeted at
< 90 seconds from cold start to "top screen answered".

## The path (today, synthetic)

1. `make demo` (runs `synth_panel.py` -> `train_t1.py` -> `build_demo.py`)
2. `python -m http.server 8765 --directory demo`
3. Load `http://localhost:8765/index.html` — top screen renders the
   ranked risk list (≤ 10s).
4. Click any project — forecast audit screen shows agency stated date
   vs ANUMAAN P50/P90, revision history, delay cause, owning authority,
   reference class.
5. `http://localhost:8765/honesty.html` — calibration, baseline
   comparison, lead-time curve, leakage guard.

## The three most likely live failures and their mitigations

> Placeholder. Filled at P7 once the snapshot is built and rehearsed.

1. **Likely failure #1 — _pending P7_**
   - Symptom:
   - Mitigation:

2. **Likely failure #2 — _pending P7_**
   - Symptom:
   - Mitigation:

3. **Likely failure #3 — _pending P7_**
   - Symptom:
   - Mitigation:

## Rehearsal cadence

P7 requires three full dry-runs on the cached snapshot before the live
demo. Rehearsals will be logged under `results/rehearsals/` with date,
start-to-answer time, and any failure observed.