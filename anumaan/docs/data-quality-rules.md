# Data-quality rules and reason codes

Each rule emits a reason code. Records failing a BLOCKER rule are never scored.

| Code | Rule | Severity |
|---|---|---|
| DQ001 | Approval date missing or sentinel (`NA`, `01/1900`) | BLOCKER |
| DQ002 | Original completion date missing or sentinel | BLOCKER |
| DQ003 | Completion date earlier than approval date | BLOCKER |
| DQ004 | Original cost missing or <= 0 | BLOCKER |
| DQ005 | Expenditure > revised cost | WARN (real, and worth surfacing) |
| DQ006 | Physical progress decreased vs previous month | WARN |
| DQ007 | Physical progress = 0 but expenditure ratio > 0.2 | WARN |
| DQ008 | Revised cost missing while a revision is implied elsewhere | WARN |
| DQ009 | Duplicate `(entity_id, report_month)` | BLOCKER |
| DQ010 | Parsed totals disagree with the report's own summary page | BLOCKER (rejects the parse) |
| DQ011 | Physical progress > 100 or < 0 | BLOCKER |
| DQ012 | Cost revised downward by more than 50% | WARN |

Seen in the real data (July 2026 flash report): several new medical colleges carry `NA`
approval dates, `01/1900` completion dates and 0% physical progress with crores already
spent. Do not impute these. They are the finding.
