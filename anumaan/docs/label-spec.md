# Label specification (v0.1)

Change this file deliberately; a change here invalidates every model comparison you have run.

## Unit of observation
One row per `(entity_id, report_month)` - a project as it appeared in one monthly report.

## Prediction time
Features for a row use reports **up to and including** `report_month`. Nothing from a later
report may enter the feature set. Enforce with `scripts/leakage_test.py`.

## Targets

### T1 - `slip_6m` / `slip_12m` (binary)
1 if the stated completion date in the report at `t + 6` (or `t + 12`) months is later than
the stated date at `t`; 0 if unchanged or earlier.
- Undefined (dropped) if the project leaves the panel before the horizon for a reason other
  than commissioning.
- If commissioned before the horizon, label 0.

### T2 - `months_to_commissioning` (duration, right-censored)
Months from `t` until the project first appears in a completed-projects table. Censored at
the last observed month for projects still running. Use a discrete-time hazard model (one row
per project-month) or a survival model that accepts censoring.

### T3 - `final_cost_ratio` (continuous)
`final_cost / original_cost` at commissioning. Defined only for commissioned projects.
Predict P10/P50/P90 and conformalise on a time-held-out calibration slice.

### T4 - `months_past_original` (continuous, always defined)
`report_month - original_date_of_completion`, floored at 0. Catches projects that never
revise their date - the blind spot of T1.

## Splits
Time-based only. Train on months <= Y, validate on the next 6 months, test on the following
12, then walk forward. Never a random split on a panel.

## Exclusions
- Rows failing a BLOCKER data-quality rule are excluded from training and never scored; they
  appear in the UI as "insufficient data" with the reason code.
- Projects with fewer than 3 observed months have no panel features and fall back to the
  reference-class base rate with wider intervals.

## Reference class
`sector x cost_band x progress_quartile x agency_type`, shrunk toward the parent class when
n < 30. Always report n next to a base rate.
