# ANUMAAN - advantages, with the evidence for each

Every claim below names the artefact that backs it. Regenerate them all with
`./run.ps1`. If a claim has no artefact, it is not in this file.

---

## The one-line advantage

**PAIMANA tells a ministry what a project's completion date is. ANUMAAN tells
it which of those dates is about to move - ranked, calibrated, and traceable
back to the printed page.**

Measured: a ministry that inspects **50 projects a month catches 48 of the 257
that will slip, against 9 at random - 5.24x better than chance.**
(`results/paimana/precision_at_k.json`)

---

## 1. Advantages over the incumbent (PAIMANA itself)

| Advantage | Evidence |
|---|---|
| **Forecast, not status.** The portal is descriptive; we rank what is about to change | `metrics_slip.json`: PR-AUC 0.6791 on the held-out month |
| **Uses only what MoSPI already publishes.** No new data collection, no agency co-operation, no MoU, no portal change | `data/raw/manifest.csv` - 32 public Flash Report PDFs |
| **Zero marginal burden on agencies.** Nobody fills in a new form | The label is the agency's own published revision |
| **Every number is auditable to the source page** | `shap_slip.json` + audit page: "2026-05 -> 2026-06: target moved +31 days" |
| **Deploys beside the portal, not instead of it** | One container, 260 MB resident, no database |

---

## 2. Advantages over the commercial alternatives

Checked against `config/competitors.yaml`, where every row carries a source URL,
a fetch date and a `verified` flag.

| Axis | nPlan / Oracle Primavera | ANUMAAN |
|---|---|---|
| **Input required** | Detailed CPM programme files, or an analyst-supplied uncertainty model | The public monthly PDF. Nothing else |
| **Works on Indian central-sector projects today** | Needs schedule files the ministries do not publish | Runs on what is already published |
| **Publishes calibration** | No (neither vendor page does) | Yes - 10-bin reliability, Brier 0.0959 |
| **Publishes a leakage test** | No | Yes - two controls on every build |
| **Cost** | Commercial licence | Open-source stack, no paid service |

The honest framing for a judge: those tools are stronger at *schedule-level*
simulation. They cannot run at all without inputs that do not exist here. We
operate on the data that does.

---

## 3. Engineering advantages a reviewer can verify in minutes

### 3.1 The parser cannot fail silently

A report is admitted only if its parsed rows re-add to the totals **printed
inside that same report** - project count, cost and expenditure. Otherwise it
is rejected whole.

Result: **11/11 PAIMANA-era reports reconcile with 0 unparsed cells**; the 21
older OCMS-era reports are reported as unparsed rather than half-read.
(`results/paimana/reconciliation.csv`)

*Why this is an advantage:* the standard failure mode of a PDF-driven project
is plausible wrong numbers. Ours stops at the door.

### 3.2 The corpus is pinned

32 PDFs, SHA-256 each, re-verified as step 1 of every pipeline run.
(`manifest_verification.json`, `scripts/verify_corpus.py`)

*Why:* a figure cannot quietly change because a file changed.

### 3.3 Leakage is tested, not assumed

Two controls run on **every** build: shuffled labels must collapse towards the
base rate; a deliberately planted leak must saturate.

Current: shuffled **0.1717**, real **0.6791**, planted **1.0000**.
(`metrics_slip.json`)

*Why:* time leakage is the defect that makes a forecasting demo look brilliant
and be worthless. Controls that can actually fail are the only ones worth
running.

### 3.4 The horizon cannot be misread

Every API response carrying a probability also carries `horizon_months` and
`target_definition`, and the UI renders the label the API sends. A one-month
number physically cannot appear under a twelve-month heading.
(`app/main.py`, `app/panel_adapter.py`)

### 3.5 Beats every baseline a reviewer will name

| Model | PR-AUC |
|---|---|
| Always base rate | 0.1830 |
| Ministry base rate | 0.2157 |
| **Slipped last month (persistence)** | **0.2814** |
| Logistic | 0.4858 |
| **ANUMAAN (LightGBM)** | **0.6791** |

The third row is the one that matters: *"if I just assume a project that moved
its date last month moves it again, what does your model add?"* Answer: 2.4x.

---

## 4. Operational and economic advantages

| Advantage | Number |
|---|---|
| Cold start | Model trains in-process in **1.6 s** |
| Footprint | **260 MB** resident, no database, no external API at serve time |
| Reproducibility | **One command** (`./run.ps1`), 9 steps, stops on first failure |
| Test suite | **45/45** green |
| Deployment | One container; panel schema checked **at build time**, so a bad panel fails the build rather than the first request |
| Marginal cost per ministry | Zero - the same panel serves all 17 |

---

## 5. The credibility advantage

The one most entries will not have.

- **We publish a negative result.** Cost-overrun forecasting was built, tested
  and **declined**: on the only informative fold a ministry base rate (0.1119)
  beats our model (0.0923), and 98.55% of project-months show zero cost change.
  It is on the honesty page, not buried. (`cost_target_diagnostic.json`)
- **We name what does not work yet.** 21 of 32 reports do not parse, and that
  sentence appears in the deck, the PRD and the product itself.
- **We label unverified sources as unverified.** Two of five benchmark rows are
  marked `verified: false` rather than quoted as fact.
- **The deck is generated from the artefacts**, so a slide cannot drift from
  the repository.

*Why this is an advantage rather than a weakness:* every judge has seen a demo
that claims everything works. The defensible position is the one where each
claim has a command behind it and each gap is named before they find it.

---

## 6. Advantages that are also honest limits

| Strength | The limit attached to it |
|---|---|
| A label with no judgement call - the agency's own revision | It predicts the *revision*, not the eventual overrun |
| Point-in-time discipline, no leakage | Costs accuracy that a leaky model would fake |
| 11 months of verified data | Not the ~20 years the PS assumes; horizon is one month |
| Fail-closed parsing | 21 reports rejected rather than partially used |

---

## 7. One-sentence answers to the obvious challenges

**"PAIMANA already does this."** PAIMANA reports the date; it does not rank
which dates are about to move, and publishes neither a per-project forecast nor
a calibration curve.

**"Only 11 months of data?"** Yes - and every number we show comes from those
11 months, which is exactly why the horizon is one month and not twelve.
Extending to the 21 older reports is the same parser, one more layout.

**"Is 0.68 PR-AUC good?"** Against a 0.183 base rate and a 0.281 persistence
baseline it is 2.4x - and the operational form is the one that matters: 48
slips caught per 50 inspections instead of 9.

**"How do I know it isn't leaking?"** Shuffle the labels and the score collapses
to 0.17; plant a leak and it jumps to 1.00. Both run on every build and both
are printed on the honesty page.

**"Why no cost model?"** Because we tested it and it lost to a ministry base
rate. Shipping it would have been the dishonest option.
