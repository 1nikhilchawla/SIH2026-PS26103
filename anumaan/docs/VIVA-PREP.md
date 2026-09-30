# ANUMAAN - viva preparation for the SIH26103 deck

Covers `ANUMAAN_SIH26103_Idea.pdf` (6 slides): every key point, why it is
there, what it maps to in the problem statement, what the repository actually
does, and the questions a judge is likely to ask.

Team: **The Raftaar Titans**.

> **Update, 18 Sep 2026.** `ANUMAAN_SIH26103_Idea_fixed.pptx` resolves every
> item in Part A.2 below: 65 text edits, the slide-4 proof table and the slide-5
> chart rebuilt from reconciled reports, and the team name filled on all six
> slides. Part A is kept as the record of what changed and why - read it so you
> can explain the corrections if asked.

---

## PART A - READ THIS FIRST: where the deck says more than the build does

This deck was written as the **plan**. The repository is the **build**. They
diverge in places a judge can check with one question. Every claim below was
tested against the repository on 18 Sep 2026.

### A.1 Claims the build backs - say these with confidence

| Deck claim | Verified against |
|---|---|
| Jul 2026: 1,775 projects, 17 ministries, Rs 33,70,138 cr -> Rs 37,10,642 cr, +10.10% | Parsed summary of `FlashReport_July_2026.pdf`, exact match |
| Apr 2026: 1,981 projects, Rs 5.65 lakh cr overrun | Parsed summary: 1,981 projects, Rs 5,65,740 cr (15.24%) |
| Rs 19,26,100 cr expenditure / 1,775 = Rs 1,085 cr per project | Jul 2026 summary; arithmetic checks |
| Oct 2025 report covers 820 projects | `reconciliation.csv`: 820 |
| Each file pinned by SHA-256 | `verify_corpus.py`: 32/32 |
| Reconcile against the report's own totals, fail closed | `parse_paimana.py`: 11/11 reconcile, 0 unparsed cells |
| One row per project x month, point-in-time features only | `build_panel.py`, asserted in code |
| Walk-forward folds; logistic vs LightGBM | `train_slip.py`: 9 folds, both models |
| Reliability diagram and Brier score | `reliability_slip.json`: 10 bins, Brier 0.0960 |
| SHAP reasons | `shap_slip.json`, exact TreeExplainer |
| FastAPI | `app/main.py` |
| All references on slide 6 | Recorded in `SOURCES.md` |

### A.2 Claims the build does NOT back - fix the slide or have the answer ready

| # | Slide | Deck says | What the build actually does | Say this instead |
|---|---|---|---|---|
| 1 | 1 | PS title "Predictive analytics for infrastructure project monitoring"; theme "Smart Automation / Data Analytics" | Official title is **"Use case on web-based integrated project-monitoring platform"**; theme **"Smart Automation"** | Correct slide 1 before submission |
| 2 | 2, 3, 6 | "Harvest all **307** Flash Reports" / "a panel of 307 reports" | 307 are **listed** on the portal. **32 harvested, 11 parsed** | "307 are listed; we harvested 32, and every number comes from the 11 that reconcile" |
| 3 | 2 | "**4 distinct layouts** (2019-2026) already parsed and reconciled" | **One** layout (PAIMANA) parses. The 21 OCMS-era reports are rejected | "The PAIMANA layout parses and reconciles; OCMS is the next layout" |
| 4 | 2, 3 | **Four targets** T1-T4: slip >= 6/12 months, hazard, conformal cost, months past | **One** target built: `slip_next`, a **1-month** horizon | "We ship one target because 11 months cannot support a 12-month one" |
| 5 | 2 | **P10/P50/P90 completion window**, conformal coverage | Not built. MAPIE is never imported | The app shows the **observed** distribution of date moves (median +3, p90 +15.9 months), labelled as data |
| 6 | 2, 4 | Censoring via a **discrete-time hazard** | Not built. `lifelines` is never imported | "The next-month label is observable for every ongoing project, so there is nothing to censor at that horizon" |
| 7 | 2 | **DQ001-DQ012 gate** fails closed | `scripts/dq.py` exists but **nothing imports it** | "Our fail-closed gate is reconciliation against the report's printed totals" |
| 8 | 2, 3 | Every alert names cause and **owning authority** from a **13-cause taxonomy** | The PDFs do **not publish a delay cause**. The panel has no cause column; the UI says "not published in the source report" | "The taxonomy is ready; the cause field needs agency-side data we do not have" |
| 9 | 2, 3 | Identity resolution across OCMS / PAIMANA / PMGID, fuzzy name matching | Portal project code, falling back to ministry + name. No fuzzy match, no cross-era join | Claim only what exists |
| 10 | 2 | **Forecast-vs-outcome scorecard per agency** | Not built | Move it to the roadmap |
| 11 | 3 | Python **3.11**, **DuckDB**, **pandera**, **React** dashboard | Python **3.14**, **pandas + CSV**, no pandera, **vanilla JS** single page | Use the real stack (Part C) |
| 12 | 3, 6 | "~**1.6 lakh** project-month rows" | **17,010** rows | Use 17,010 |
| 13 | 4, 5 | Jul 2019, Jun 2025 and Apr 2024 figures (e.g. 43.1% delayed, 20.07% overrun) | Read from OCMS / pre-PAIMANA reports the pipeline **does not parse**; no artefact reproduces them | Cite them as "read from the report" or drop them |
| 14 | 3, 4 | Parse throughput 2.4 pages/s; full corpus 8.9 h | Earlier measurement, not re-run. The current 32-PDF run takes 1,636 s end to end | Say "measured on an earlier run" |

**Recommendation.** Either present `ANUMAAN_SIH26103_Idea_v2.pptx`, which is
generated from the repository and matches the build, or at minimum fix items
1-4 and 11-12 on this deck. Items 5-10 are defensible only as **roadmap**, and
must be labelled that way on the slide.

A judge who asks "show me the hazard model" or "show me the 307-report panel"
will find the gap in under a minute. A judge who hears you name the gap first
will usually credit the honesty.

---

## PART B - slide by slide

### Slide 1 - Title

**Key point.** "We audit the completion date the agency itself published - and
forecast the slip before it is announced."

**Why it is there.** It frames the product as an audit of a *published
estimate*, not a guess about construction. The agency already states a date
every month; we measure how reliable that statement is.

**PS link.** The PS's stated challenge: move from descriptive reporting to
predictive analytics.

**Fix.** PS title and theme (A.2 item 1).

### Slide 2 - Proposed solution

| Point | Why it is necessary | Build status |
|---|---|---|
| Project x month **panel**, not a snapshot | One month cannot show drift; drift across months is the signal | Built - 17,010 rows, 11 months |
| SHA-256 pinning | Makes "we used official data" checkable | Built |
| Reconcile against the report's own totals | Stops silent parse errors, the main failure mode of a PDF project | Built |
| Point-in-time features only | Prevents leakage, the defect that makes a forecast look brilliant and be worthless | Built and asserted |
| Four targets T1-T4 | Would cover time AND cost, point AND interval | **Only a one-month slip target is built** |
| SHAP reason + owning authority | Makes an alert actionable rather than just a number | SHAP built; authority not available from PDFs |
| "PAIMANA publishes status. Nobody audits the estimate." | The problem in one sentence | True, and the core pitch |
| Jul 2026 overrun +10.10% | Grounds the pitch in the corpus | Verified |
| Apr 2024: 43.1% delayed | Scale of the problem | From an unparsed OCMS report - no artefact |

**PS link.** Deliverables 1 (time overrun), 2 (risk scoring), 3 (early warning).

### Slide 3 - Technical approach: the seven nodes

| Node | Deck says | Why it is necessary | Real status |
|---|---|---|---|
| **1 HARVEST** | Ingest 307 reports via portal endpoints; manifest + SHA-256 | Without pinned inputs, every result is unfalsifiable | Built for 32 PDFs via the portal's JSON endpoints |
| **2 PARSE** | Per-layout parsers: OCMS, Part I/II, Synopsis+Tables, PAIMANA | The portal changed layouts over the years | PAIMANA parser built; the other three are not |
| **3 RECONCILE** | Detail rows vs the report's own summary totals, fail closed | Turns a silent parse error into a loud one | Built: 11/11, 0 unparsed cells |
| **4 RESOLVE ID** | Exact code, then fuzzy name, then manual residual | The same project must be one entity across months | Exact code + name fallback only |
| **5 PANEL** | One row per project x month, point-in-time features | The unit a forecaster needs | Built |
| **6 MODEL** | Walk-forward with label embargo; logistic vs LightGBM | The PS invites an ML-vs-statistical comparison | Built: 9 folds, both models, 3 baselines, 2 leakage controls |
| **7 ALERT** | Calibrated probability + P10/P50/P90 + reason + authority | Makes the forecast usable by a ministry | Probability, ranking and SHAP built; interval and authority not |

**PS link.** Deliverables 1, 2, 3, 6 and 8.

### Slide 4 - Feasibility and viability

**Technical feasibility - the strong part.** Data is public and reachable; the
model trains in seconds; the whole pipeline is one command (`./run.ps1`).

| Challenge on the slide | Why it is a real risk | What the build does |
|---|---|---|
| Layout drift across years | A parser silently returning zero rows | Reconciliation rejects the report; zero rows cannot pass |
| Panel breaks (Oct 2025 = 820 projects vs 1,775 in Jul 2026) | A ministry dropping out looks like projects finishing | Labels only defined for consecutive months; gaps leave them undefined |
| Sentinel values (01/1900 dates, 0% progress with crores spent) | Garbage becomes features | Nulls kept and counted, never imputed silently |
| Right-censoring | Most projects are still running | At a one-month horizon the label is observable for every ongoing project |
| Time leakage | Inflates every score | Walk-forward only, plus two controls on every build |

**Economic.** Rs 2.0 lakh/year on NIC MeghRaj (VM Rs 1.44 L + storage Rs 0.06 L
+ contingency Rs 0.5 L). No licence cost. This is a **proposal**; the build
currently ships as a Docker image for Railway.

**The proof table.** The Jul 2026 row is verified. The Jul 2019 and Jun 2025
rows come from reports the pipeline does not parse (A.2 item 13).

### Slide 5 - Impact and benefits

| Number | What it is | How solid |
|---|---|---|
| Rs 5.65 lakh cr | Cost overrun across 1,981 projects, Apr 2026 | **Verified** - our parse gives Rs 5,65,740 cr |
| 43.1% | Delayed vs original schedule, Apr 2024 | From an unparsed report - no artefact |
| Rs 6.33 cr | Idle capital per project per month of delay | **Arithmetic on an assumption**: Rs 1,085 cr x 7% / 12 |
| Rs 500 cr / yr | Value of acting one month earlier on 10% of delayed projects | **Arithmetic on assumptions**: 79 x Rs 6.33 cr |

Present the last two as *illustrative calculations*, never as measured
savings. The 7% cost of capital and the 10% share are assumptions - say so if
asked.

**Who benefits.** IPMD (a ranked watch-list instead of a 153-page PDF), line
ministries, PMG/DPIIT and NITI Aayog, and - through calibrated public risk -
Parliament, CAG and citizens.

**PS link.** Deliverables 3 (early warning) and 6 (dashboards).

### Slide 6 - Research and references

**Why it is there.** Shows the approach is grounded, and states the gap: the
closest published work (Andric et al. 2024) uses 138 completed projects; this
works on live, ongoing ones.

**Strongest line on the slide - keep it:** "No published benchmark exists for
delay prediction on Indian central-sector projects, so we establish the first
walk-forward baseline rather than claim to beat a state of the art that does
not exist."

**Fix.** "About 1.6 lakh project-month rows" -> 17,010 (A.2 item 12).

---

## PART C - tech stack: as claimed vs as built, and why each exists

| Layer | On the deck | Actually used | Why it is needed |
|---|---|---|---|
| Language | Python 3.11 | **Python 3.14** | Whole pipeline; pinned in `requirements.txt` |
| Fetch | requests | **requests 2.34.2**, beautifulsoup4 4.15.0 | Calls the portal's report endpoints |
| PDF | pdfplumber | **pdfplumber 0.11.10** | Line-based table extraction with a per-page word-position fallback |
| Storage / compute | DuckDB, pandas | **pandas 2.3.3, numpy 2.5.3, CSV** | 17,010 rows fit easily in memory; DuckDB becomes worth it at multi-year scale |
| Schema checks | pandera | **Not used** | Reconciliation and code assertions do this job today |
| Models | LightGBM + regularised logistic | **LightGBM 4.7.0 + scikit-learn 1.9.1 logistic** | Strong tabular model plus the statistical baseline the PS asks us to compare |
| Survival | lifelines | **Not used** | Cut; unnecessary at a one-month horizon |
| Intervals | MAPIE | **Not used** | Cut |
| Explanation | SHAP | **SHAP 0.52.0** TreeExplainer | Exact per-project reasons |
| API | FastAPI | **FastAPI 0.141.1 + uvicorn 0.53.0** | Serves the model; trains in-process at startup |
| UI | React | **Vanilla JavaScript**, one HTML page | No build step, nothing to break during a demo |
| Deploy | NIC MeghRaj VM | **Docker (python:3.14-slim) for Railway**; MeghRaj is the target | One container, 260 MB resident |
| Tests | - | **pytest 9.1.1**, 45 tests | Guard the parser |
| Orchestration | - | **run.ps1** | One command, stops on first failure |

**If a judge asks about Node.js:** there is none. The stack is Python end to
end, and the UI is plain JavaScript served by FastAPI.

---

## PART D - workflow against the actual PS

The PS (MoSPI, Data Informatics & Innovation Division, Software, Smart
Automation) asks to move from descriptive reporting to predictive analytics on
PAIMANA data. Its eight possible deliverables, and where each sits:

| PS deliverable | Workflow node | Status |
|---|---|---|
| 1. Cost and time overrun prediction | 6 MODEL | Time built; cost tested and declined (a ministry base rate beats it) |
| 2. Project risk scoring framework | 6 MODEL -> 7 ALERT | Built - calibrated probability, 10-bin reliability |
| 3. Early warning alert system | 7 ALERT | Built - ranked top-50 watch-list |
| 4. Benchmarking analytics | alongside 7 | Partly - vs PAIMANA, PMG, nPlan, Primavera |
| 5. Cost escalation driver analysis | 6 MODEL (SHAP) | Partly - drivers of date moves, not of cost |
| 6. AI-powered monitoring dashboard | 7 ALERT (UI) | Built - live app, 5 tabs |
| 7. LLM project intelligence assistant | - | Not built, deliberately |
| 8. Documentation and deployment | all | Built - docs, run.ps1, Dockerfile |

**The PS's own numbers match our parser.** It describes 1,981 projects, 17
ministries and 22 sectors. We parsed 1,981 rows from the April 2026 report, and
17 ministries and 22 sectors across the panel - without targeting them.

---

## PART E - questions a judge is likely to ask

### Evaluation

**Q. How did you evaluate the model?**
Walk-forward: train on every month before T, test on month T, repeated across 9
folds. No random split anywhere - a random split lets the model see the future
and inflates every score. On the held-out month 2026-06 (1,404 projects, 257
slips): PR-AUC 0.6791, Brier 0.0959.

**Q. Why PR-AUC and not accuracy?**
Only 18-19% of project-months slip. A model that always says "no slip" is about
81% accurate and useless. PR-AUC measures how well we rank the rare positives.

**Q. What is it compared against?**
Three baselines: always-base-rate (0.1830), ministry base rate (0.2157), and
persistence - "it slipped last month, so it will again" (0.2814). LightGBM at
0.6791 is 2.4x the strongest. Logistic regression scores 0.4858.

**Q. How do you know it is not leaking?**
Two controls on every build. Shuffle the training labels and PR-AUC collapses
to 0.1717, near the base rate. Plant a copy of the label as a feature and it
jumps to 1.0000. If shuffling did not collapse the score, a feature would be
seeing the future.

**Q. Is it calibrated?**
Yes - a 10-bin reliability table of predicted probability against observed
frequency, published in the product. Brier 0.0960.

**Q. What does it mean in practice?**
Inspect the top 50 projects a month and you catch 48 of the 257 that will slip.
Random inspection catches 9. That is 5.24x.

### Model choice

**Q. Which model, and why that one?**
LightGBM - gradient-boosted decision trees. Three reasons:
1. The data is tabular and mid-sized (17,010 rows); tree ensembles are the
   documented state of the art there (Grinsztajn et al., NeurIPS 2022).
2. It handles mixed-scale features and missing values without heavy
   preprocessing, and captures interactions such as "one month from its target
   AND already revised three times".
3. It supports exact SHAP explanations, so every alert has a reason.

**Q. Why not deep learning?**
17,010 rows is far too few. Neural networks underperform tree ensembles on
tabular data of this size, and are harder to explain to a ministry.

**Q. Why not Random Forest or XGBoost?**
Random Forest is usually weaker than boosting on data like this. XGBoost would
likely perform similarly; LightGBM is faster and lighter to serve. A
like-for-like comparison is a reasonable next experiment - we have not run it.

**Q. Why keep logistic regression?**
The PS invites a comparison between ML and statistical methods. Logistic is
that comparison: 0.4858 against LightGBM's 0.6791.

**Q. What does the model actually learn?**
The top SHAP driver is `months_to_target`: projects whose stated date is a month
away and which keep rolling it forward. One real example moved its date by +30
or +31 days in every consecutive report.

**Q. Why predict a one-month slip rather than the final overrun?**
The final overrun has no answer until a project ends, and most are ongoing - a
censoring problem. Whether the agency states a later date next month is
observable for every project, with no judgement call. It is the earliest honest
signal in the data.

**Q. Why no cost-overrun model?**
We built and tested one. 98.55% of project-months show zero change in revised
cost, and on the one informative fold a ministry base rate (0.1119) beats the
model (0.0923). Lowering the threshold to zero only moves positives from 114 to
136. Shipping it would have been dishonest.

### Data

**Q. Where does the data come from?**
The official monthly Flash Report PDFs on the PAIMANA portal. 32 harvested, each
pinned by SHA-256.

**Q. How do you know the parser is right?**
Every report must re-add to its own printed totals - project count, cost and
expenditure - or it is rejected. All 11 PAIMANA-era reports pass with zero
unparsed cells. Our counts also match the PS: 1,981 projects, 17 ministries,
22 sectors.

**Q. Why only 11 months?**
Only the PAIMANA layout parses so far. The 21 older OCMS-era reports use a
different layout. Extending the parser to them is the single highest-value next
step.

### Scaling

**Q. How would you scale it?**
Four steps, each already designed for:
1. **More history.** Add the OCMS-era layout to the parser - same content-based
   era detection, same reconciliation gate. Moves the panel from 11 months to
   multi-year and makes a 6- or 12-month horizon supportable.
2. **Faster refresh.** Cache parse results by SHA-256 so unchanged PDFs are
   never re-read. The monthly top-up becomes one new report, not the corpus.
3. **More data per project.** Direct PAIMANA API access instead of PDFs would
   add fields the PDFs omit, such as delay cause - which switches on the
   13-cause taxonomy and owning-authority routing.
4. **More users.** The service is stateless: one container per replica, no
   database. Horizontal scaling means adding replicas.

**Q. Will it handle 20 years of data?**
Yes. 20 years x ~2,000 projects x 12 months is roughly 4.8 lakh rows - trivial
for LightGBM. At that scale the panel would move from CSV to DuckDB or Parquet.

**Q. What does it cost to run?**
Proposed on NIC MeghRaj: about Rs 2.0 lakh a year (4 vCPU / 16 GB VM Rs 1.44 L,
storage Rs 0.06 L, contingency Rs 0.5 L). The measured footprint is far smaller:
260 MB resident, trains in 1.6 s.

### If selected

**Q. What would you do in the next phase?**
1. Parse the OCMS layout - panel to multi-year.
2. With the longer panel, add 6- and 12-month horizons and revisit the cost
   target, which fails today partly because cost revisions are episodic.
3. Seek field-level access from MoSPI (delay cause, milestones) to switch on
   cause-and-authority routing.
4. Add the per-agency forecast-vs-outcome scorecard - grading each agency's own
   estimates over time.
5. Deploy on NIC MeghRaj with logs held in Indian jurisdiction and a
   GIGW-aligned UI, alongside PAIMANA rather than replacing it.

**Q. What about the LLM assistant the PS mentions?**
Deliberately not built. An LLM layer over unverified numbers would be the
easiest thing to demo and the hardest to defend. It becomes sensible once the
underlying numbers are complete - and it should answer only from the verified
panel.

### Robustness and governance

**Q. What if MoSPI changes the PDF format?**
The new layout fails reconciliation and is rejected, not silently misread. We
add a parser for it. The failure is loud by design.

**Q. Is it fair to agencies?**
The label is the agency's own published date, not our opinion. The model ranks
risk; a human reviews. The audit screen shows the evidence, so a flagged agency
can challenge it.

**Q. What about security and data residency?**
No personal data - public PDFs only. The target deployment is NIC MeghRaj with
logs held in Indian jurisdiction. The container runs as a non-root user.

**Q. What is novel here?**
Three things: treating the agency's published date as a forecast to be audited;
a parser that proves itself against each report's own totals; and publishing
calibration and a leakage test - which PAIMANA, PMG, nPlan and Primavera do not.

---

## PART G - scaling, and using it without internet

### G.1 How would you scale it?

Five axes. Each says what exists today and what the next step is.

| Axis | Today (built, measured) | How it scales |
|---|---|---|
| **History** | 11 months, 17,010 project-months | Add the OCMS-era layout to the parser. 20 years x ~2,000 projects x 12 months is ~4.8 lakh rows - still small for LightGBM. Move CSV to Parquet/DuckDB at that point |
| **Refresh** | Full pipeline 1,636 s on 32 PDFs | Cache each parse by SHA-256. Unchanged PDFs are never re-read, so a monthly update is one new report |
| **Users** | One container, 260 MB, no database, stateless | Horizontal: add replicas behind a load balancer. The static pages are plain files, so they scale on any web server or CDN at near-zero cost |
| **Coverage** | Central-sector projects >= Rs 150 cr, 17 ministries | Any state that publishes a similar monthly report gets a new layout parser; the reconciliation gate and the model are unchanged |
| **Horizon** | One month | With a multi-year panel: 6- and 12-month horizons, and a second look at the cost target |

**The one-line answer:** "The expensive part - proving the data - is already
built as a gate. Scaling is adding layouts and replicas, not rebuilding."

### G.2 How would it work without internet, in rural or remote areas?

Be precise about who the offline user is. The Flash Reports are published
centrally, so *someone* connected downloads them once a month. The offline
problem is the **last mile**: a district office, a project site in a remote
area, or a field engineer with no reliable connection.

**What already works offline - built and verifiable today:**

| Capability | Why it works offline | Evidence |
|---|---|---|
| The whole pipeline | No external API at runtime, no cloud service, no database | `app/main.py`; `DEPLOY.md` |
| The model | Trains in 1.6 s on a CPU, 260 MB of memory, no GPU | Measured with the production start command |
| The watch-list, audit and honesty pages | Plain HTML files - they open in any browser **with no server and no internet** | `demo/paimana/*.html`, 26.7 KB for all three |
| Integrity checking | A SHA-256 manifest lets an offline copy prove it was not altered in transit | `data/raw/manifest.csv`, `scripts/verify_corpus.py` |

**How it would be delivered - proposed, not built:**

1. **Monthly offline bundle.** One connected machine (at MoSPI or NIC) runs
   `./run.ps1` and exports the pages as a bundle a few hundred KB in size.
   Distributed by NICNET, by email whenever a connection appears, or by pen
   drive. The district office opens it in any browser - nothing to install.
2. **Store and forward.** A district laptop keeps the last bundle and fetches
   the next one when even a 2G connection is briefly available. The update is
   small because only the ranked list and the changed projects travel.
3. **SMS alerts.** The top at-risk projects for a district, one line each, sent
   through NIC's SMS gateway. Works on a basic feature phone with no data plan.
4. **Printable one-pager.** A per-district PDF of the watch-list for officials
   who work from paper.
5. **Local laptop mode.** The same Docker image or Python app runs on an
   ordinary laptop with no connection, for an office that wants the live,
   filterable dashboard rather than static pages.
6. **Language.** Hindi and regional-language labels through Bhashini -
   roadmap.

**Say this honestly if pressed:** the static pages and the local run are
built; bundle packaging, SMS alerts and regional languages are designs, not
features. Low-power hardware such as a Raspberry Pi-class board is plausible
from the 260 MB footprint but **has not been tested**.

**The one-line answer:** "The model is small enough to run on a laptop and the
output is plain HTML, so the last mile is a file transfer, not a server - a pen
drive, an email when the signal comes back, or an SMS."

---

## PART F - the six numbers to know by heart

| Number | Meaning |
|---|---|
| **19.2%** | project-months where the agency moves its date in the next report |
| **0.6791** | model PR-AUC, vs **0.2814** for the best baseline (**2.4x**) |
| **48 vs 9** | slips caught in a top-50 inspection vs random (**5.24x**) |
| **11 / 11** | PAIMANA-era reports that reconcile, with 0 unparsed cells |
| **17,010** | project-months in the panel (2,195 projects, 11 months) |
| **0.1717 / 1.0000** | shuffled-label and planted-leak controls |
