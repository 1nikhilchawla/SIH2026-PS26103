# ANUMAAN — Research Pack for SIH26103

**Problem statement:** SIH26103 — Ministry of Statistics & Programme Implementation (MoSPI),
Data Informatics & Innovation Division. Predictive analytics for infrastructure project
monitoring on PAIMANA.

**Compiled:** 15 September 2026. **Submission deadline:** 30 September 2026.

Everything you need to start is in this one file. Links are grouped by what they are *for*,
not by where they came from. Each entry says what to take from it.

### Honesty labels used below

| Label | Meaning |
|---|---|
| `[READ]` | The page/PDF was opened and its content confirmed. Facts quoted here come from it. |
| `[LISTED]` | Found in search results; title and URL confirmed, full text **not** read. Open it before citing. |
| `[CHECK]` | The resource is believed to exist but its exact contents/availability were not confirmed. |

Do not put a number on a slide unless you have personally opened the source and seen it.

---

## 0. How to use this pack

Three passes, in this order. Do not skip pass 1.

1. **Pass 1 — Establish the gap (½ day, PPT team + you).** Read §1 and §3. By the end you
   should be able to say in one sentence what MoSPI publishes today, what it stopped
   publishing, and why that is a problem. That sentence is slide 1.
2. **Pass 2 — Get the data (2 days, data scientist + backend).** §2 only. Run the harvester,
   get the PDFs on disk, build the panel. Nothing else matters until this works.
3. **Pass 3 — Justify the method (ongoing, ML engineer).** §5–§7 when you are choosing models,
   §8 when parsing breaks, §9–§11 before you write the security slide.

---

## 1. The competition and the problem statement

| What | Link |
|---|---|
| SIH 2026 problem statement list | https://www.sih.gov.in/sih2026PS |
| SIH 2026 portal home | https://www.sih.gov.in |

**Rules that shape your strategy** (confirmed from the portal earlier in this project):
one team may submit against a **maximum of 2 problem statements**; each PS accepts up to
**500 ideas**; the idea submission is a **6-slide PDF**; deadline **30 Sep 2026**; 4–5 teams
per PS are shortlisted for the grand finale.

---

## 2. Tier-1 primary data — this is what you actually model

This is the moat. There is **no machine-readable feed** of central-sector project monitoring
data. The numbers live in monthly PDF Flash Reports. Everyone who tries this PS will build a
dashboard on a screenshot; you will build a panel on 300+ reports.

### 2.1 PAIMANA portal — the live system and the report archive `[READ]`

| Resource | URL |
|---|---|
| PAIMANA portal root | https://paimana-proj.mospi.gov.in |
| Current reports listing | https://paimana-proj.mospi.gov.in/ReportPage |
| Archive listing (older reports) | https://paimana-proj.mospi.gov.in/ReportPage/ArchiveProjectMonitoring |

The listing pages contain links of the form `ViewPdf?id=<n>&path=<path>`. `scripts/harvest_paimana.py`
in this kit parses exactly that pattern and downloads every report with a manifest and SHA-256
checksums. **Start here.**

> **What PAIMANA is, officially** `[READ]` — PIB release, MoSPI, 25 Mar 2026:
> https://www.pib.gov.in/PressReleasePage.aspx?PRID=2244898&reg=3&lang=1
> PAIMANA = *Project Assessment Infrastructure Monitoring and Analytics for Nation-Building*.
> Covers ongoing central-sector projects of **₹150 crore and above**. As of January 2026 it
> held **1,702 projects across 17 Central Ministries/Departments**, original cost
> **₹33.71 lakh crore**, cumulative expenditure **₹20.01 lakh crore**. It ingests from the
> Integrated Project Monitoring Portal (IPMP) via API; about **64%** of projects (Road Transport
> & Highways, Petroleum & Natural Gas, Coal) update **automatically** — meaning roughly a third
> are still **manual entry**. That one-third is the entire justification for your data-quality gate.

### 2.2 Flash Report PDFs — direct hosts

| Host | Pattern | Status |
|---|---|---|
| `mospi.gov.in` publications | `https://www.mospi.gov.in/uploads/publications_reports/<opaque-hash>_Flash_Report_<Month>_<Year>.pdf` | `[READ]` — works, but the filename contains an opaque hash, so you **cannot** guess URLs. Harvest from the listing page. |
| `ipm.mospi.gov.in` | `https://ipm.mospi.gov.in/Content/PDF/FlashReport_<Month>_<Year>.pdf` | `[READ]` — predictable pattern, **but the TLS certificate on this host is expired as of 15 Sep 2026.** |

⚠️ **On the expired certificate:** do **not** "fix" this with `verify=False`. A judge asking
about your security posture will find it, and it is a real MITM hole. Either download those
files by hand in a browser, or stick to the PAIMANA listing route the harvester uses. Note the
expiry in your risk register — it is also a legitimate slide: *"the source system's own
certificate has lapsed; our ingest pins the reports by SHA-256 instead of trusting the channel."*

### 2.3 Related official portals

| Portal | URL | What you get |
|---|---|---|
| MoSPI home / publications | https://www.mospi.gov.in | Flash Reports, statistical releases, the IPMD section |
| eSankhyiki (MoSPI data portal) | https://esankhyiki.mospi.gov.in | `[READ]` API + Python client for ~30 MoSPI datasets — **project monitoring is not one of them.** Useful for macro covariates (WPI/CPI for cost deflation, IIP). |
| data.gov.in | https://www.data.gov.in | `[CHECK]` search "infrastructure project monitoring", "central sector projects". Robots-restricted from automated checking here; verify by hand. |
| PM Gati Shakti NMP | https://pmgatishakti.gov.in | `[CHECK]` the geospatial layer for infrastructure planning — good for a "future integration" slide |
| PIB releases | https://pib.gov.in | Ministry-level announcements, project inaugurations, official statements |
| Parliament Q&A (Lok Sabha / Rajya Sabha) | https://sansad.in | `[CHECK]` **Underrated.** Starred/unstarred questions on project delays return tabular annexures, often with per-project delay reasons. Search "cost overrun", "time overrun", "delayed projects". |
| CAG audit reports | https://cag.gov.in | `[CHECK]` performance audits of specific infrastructure programmes — the best independent source of *causes* |
| NITI Aayog | https://www.niti.gov.in | Policy framing for the "why this matters" slide |

**Sector-specific (for cross-checking a handful of projects):** NHAI https://www.nhai.gov.in ·
Indian Railways https://indianrailways.gov.in · Ministry of Road Transport & Highways
https://morth.nic.in — all `[CHECK]`.

---

## 3. The "why now" — journalism and commentary

These three sources are your slide 1. Two of them are hostile to the status quo and one is
MoSPI's own defence. **Read all three.** You will be asked about the third.

### 3.1 ThePrint — the transparency gap `[READ]` ⭐ strongest single citation

**"When 'delayed' becomes 'ongoing', the growing transparency gap in India's infrastructure"**
— Sharmila Chavaly, 13 August 2026.
https://theprint.in/opinion/when-delayed-becomes-ongoing-the-growing-transparency-gap-in-indias-infrastructure/3013777/

What it establishes, in the author's words:

- As of **April 2026**: **1,981** ongoing central-sector projects, cumulative cost overrun
  **₹5.65 trillion**, revised cost **₹42.78 trillion** against original **₹37.12 trillion**.
- **PAIMANA launched September 2025** and reclassified projects behind schedule from
  "delayed" to "ongoing" — *the word "delay" was removed from official reports.*
- Ministry of Railways discontinued the annual **"Pink Book" in April 2025**, making railway
  project delays hard to isolate.
- Of **129 highway projects** awarded 2021–2025 (₹1.40 trillion), close to **65%** of
  under-construction projects were more than **six months** behind schedule as of April 2026.
- Ratings agencies independently found ~**79 road projects** delayed by more than **three years** —
  proving the granular data exists.

This is published one month before your deadline, by a former senior civil servant, in a
mainstream outlet. It is the cleanest possible framing of your problem.

### 3.2 Business Standard — MoSPI's own answer `[READ]` ⚠️ read this before the judges do

**"Line ministries are being apprised of project spillages in real time: Mospi"**
— Himanshi Bhardwaj, 20 July 2026.
https://www.business-standard.com/industry/news/line-ministries-are-being-apprised-of-project-spillages-in-real-time-mospi-126072001234_1.html

MoSPI's position: login credentials for customised dashboards "have already been shared with
all line ministries/departments"; PAIMANA "provides project-wise details in its flash report and
is designed with rich data analytics and output-oriented reports". The article also lists the
delay causes the government itself names: **"land acquisition issues, forest, wildlife and
environmental clearances, law and order problems, utility shifting, and delays in civil works."**

**Two things to take from this:**

1. **Your delay taxonomy should use the ministry's own vocabulary.** `config/delay_taxonomy.yaml`
   in this kit already does. Say so on the slide — it is a credibility win.
2. **Your hardest judge question lives here:** *"MoSPI says PAIMANA already has rich analytics.
   What are you adding?"* Your answer must be crisp: PAIMANA reports **status** — what the
   agency says the position is. Nothing in any official statement claims it **forecasts** future
   slippage, or **audits the agency's own claimed completion date** against that agency's track
   record. Descriptive ≠ predictive. Rehearse this answer until it is one breath long.

### 3.3 The Wire — the accounting change `[LISTED]`

**"Infrastructure Projects Worth Rs 42 Lakh Crore Running Late, But Govt Doesn't Track it as 'Delayed'"**
https://m.thewire.in/article/economy/infrastructure-projects-worth-rs-42-lakh-crore-running-late-but-govt-doesnt-track-it-as-delayed

Same thesis as ThePrint from a different outlet. Open and verify the figure before quoting it;
two independent outlets on one point is worth more than one.

### 3.4 Deccan Herald — routine monthly coverage `[LISTED]`

https://www.deccanherald.com/business/mospi-says-431-infra-projects-hit-by-cost-overrun-of-rs-480-lakh-crore-in-january-2909272

Useful mainly as a **validation oracle**: news reports of a given month's Flash Report quote
headline counts. If your parser's totals disagree with the press coverage of the same month,
your parser is wrong. Build this into your reconciliation step.

---

## 4. Closest prior work — read this one first

### ⭐ Determining Cost and Causes of Overruns in Infrastructure Projects in South Asia `[READ]`

Andrić, J.M., Lin, S., Cheng, Y., Sun, B. — *Sustainability* **16**(24):11159, 2024.
DOI: 10.3390/su162411159 · https://www.mdpi.com/2071-1050/16/24/11159

**Why this is the most important paper in the pack:** it uses ADB completion reports **and
India's Infrastructure and Project Monitoring Division data** — the same source family as yours.
Findings: 138 projects across 7 South Asian countries; average cost overrun **3.3%**; roadways
and highways highest at **13.96%**; energy showed an **underrun of −0.80%**; the most frequently
cited cause was **fluctuation in resource prices**; and **random forest regression beat linear
and quadratic regression**.

**How to use it:** this is simultaneously your validation *and* your gap.

- *Validation:* someone has already shown ML beats conventional statistics on this exact data
  family. That is literally research question 2 of SIH26103. Cite it.
- *Gap:* **n = 138 projects, completion reports only.** No time dimension, no monthly panel, no
  point-in-time features, no calibrated intervals, no forecast-vs-outcome audit. You have
  ~1,700–2,000 projects × 300+ months. State the contrast explicitly on your methodology slide:
  *"the closest published work uses 138 completed projects; we use a project-month panel two
  orders of magnitude larger, and we evaluate the way a forecaster must — walk-forward."*

---

## 5. Research papers — delay and cost-overrun prediction

**Read §4 first, then skim these.** A pattern will emerge fast, and the pattern is your
opportunity: **most of this literature predicts delay from questionnaire responses about
perceived delay factors, not from administrative records of actual projects.** Say that out
loud in your presentation.

| Paper | Link | Take-away |
|---|---|---|
| **Applied artificial intelligence for predicting construction projects delay** — Egwim, Alaka, Toriola-Coker, Balogun, Sunmola. *Machine Learning with Applications* **6**, 2021. DOI 10.1016/j.mlwa.2021.100166 `[READ]` | https://www.sciencedirect.com/science/article/pii/S2666827021000839 | Stacked ensemble-of-ensembles beats single models. **Caveat that is your advantage: trained on 120 expert survey responses, not project records.** Cite it for method, then contrast your data. |
| **Prediction of Risk Delay in Construction Projects Using a Hybrid Artificial Intelligence Model** — *Sustainability* **12**(4):1514, 2020 `[LISTED]` | https://www.mdpi.com/2071-1050/12/4/1514 | Hybrid AI for delay-risk. Commonly cited baseline. |
| **Comparative analysis of deep learning algorithms for predicting construction project delays in Saudi Arabia** — *Applied Soft Computing*, 2025 `[LISTED]` | https://www.sciencedirect.com/science/article/abs/pii/S1568494625002017 | Recent DL comparison. Check whether DL actually beat trees — cross-read with §7. |
| **Machine Learning Model for Construction Time Prediction (Hosanna, Ethiopia)** — Debero, *Journal of Engineering*, 2024 `[LISTED]` | https://onlinelibrary.wiley.com/doi/full/10.1155/2024/5653690 | Public-building projects, developing-economy context. Closer to your setting than OECD studies. |
| **A Machine Learning Approach to Predict Time Delays in Marine Construction Projects** — *ETASR*, 2024 `[LISTED]` | https://etasr.com/index.php/ETASR/article/view/8173 | Domain-specific; useful for feature ideas. |
| **AI-Driven Schedule Delay Prediction and Mitigation: A Systematic Literature Review** `[LISTED]` | https://amresearchjournal.com/index.php/Journal/article/view/2153 | Use as a **map** to find more papers; it is in a low-profile journal, so do not lean on it as authority. |
| **Applied AI for delay risk prediction of BIM-based projects** (PhD thesis, Univ. of Hertfordshire) `[LISTED]` | https://uhra.herts.ac.uk/id/eprint/16918/ | Full thesis — its literature review chapter will save you a week of searching. |

---

## 6. Research papers — forecasting methodology

This is where you win on rigour. Judges see a hundred "we got 92% accuracy" slides. Almost none
of them can answer *"is your 70% probability actually 70%?"*

### 6.1 Calibration — the single most important idea in your project

**Probabilistic forecasts, calibration and sharpness** — Gneiting, Balabdaoui & Raftery,
*JRSS-B* **69**(2):243–268, 2007. `[LISTED]`
https://academic.oup.com/jrsssb/article/69/2/243/7109375 ·
open PDF: https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jrssb.pdf

The principle: **maximise sharpness subject to calibration.** For you: a model saying "80%
chance of a 6-month slip" must be right 80% of the time when it says 80%. Put a reliability
diagram on a slide. Almost nobody else will, and it is the difference between a demo and a
system a ministry could act on.

Practical: https://scikit-learn.org/stable/modules/calibration.html · Brier score,
`CalibratedClassifierCV`, `calibration_curve`.

### 6.2 Conformal prediction — honest intervals with a guarantee

| Paper | Link |
|---|---|
| **Conformalized Survival Analysis** — Candès, Lei, Ren. arXiv 2103.09763; *JRSS-B* **85**(1):24, 2023 `[LISTED]` | https://arxiv.org/abs/2103.09763 · https://academic.oup.com/jrsssb/article/85/1/24/7008653 |
| **Doubly Robust Conformalized Survival Analysis with Right-Censored Data** — arXiv 2412.09729 `[LISTED]` | https://arxiv.org/abs/2412.09729 |
| **Conformal predictive intervals in survival analysis: a re-sampling approach** — arXiv 2408.06539 `[LISTED]` | https://arxiv.org/abs/2408.06539 |
| **Two-sided conformalized survival analysis** — arXiv 2410.24136 `[LISTED]` | https://arxiv.org/abs/2410.24136 |

Implementation: **MAPIE** — https://github.com/scikit-learn-contrib/MAPIE (split conformal,
conformalised quantile regression). Pinned in `requirements.txt`.

Why this matters for SIH26103 specifically: your target is **right-censored** — an ongoing
project has not finished, so you do not know its completion date, only that it exceeds today.
Throwing those rows away is the single most common fatal mistake on this problem, and it
silently biases every number you report. §6.3 is the fix.

### 6.3 Survival / discrete-time hazard — how to handle "not finished yet"

| Resource | Link |
|---|---|
| **Survival prediction models: an introduction to discrete-time modeling** — *BMC Medical Research Methodology*, 2022 `[LISTED]` | https://link.springer.com/article/10.1186/s12874-022-01679-6 |
| Discrete-time survival tutorial (R, applied) `[LISTED]` | https://www.rensvandeschoot.com/tutorials/discrete-time-survival/ |
| Stata manual chapter on discrete-time survival `[LISTED]` | https://www.stata.com/manuals13/stdiscrete.pdf |
| `lifelines` (Python) | https://lifelines.readthedocs.io |

**The trick that makes this easy:** a discrete-time hazard model *is* a logistic regression on
a person-period (here: **project-month**) table — exactly the panel your harvester builds. Each
row asks "did this project complete in this month, given it had not completed before?" You can
therefore use LightGBM for it directly. Explain that on a slide; it lands well.

### 6.4 Reference-class forecasting — the base-rate layer

| Resource | Link |
|---|---|
| **Reference class forecasting: promises, problems, and a research agenda moving forward** — Cantarelli, Davis, Pinto & Turner, *Production Planning & Control*, 2025. DOI 10.1080/09537287.2025.2578708 `[READ]` | open copy: https://dspace.lib.cranfield.ac.uk/server/api/core/bitstreams/076d9c29-659d-4bfd-9b1b-e0019ea9ad20/content |
| **From Nobel Prize to Project Management: Getting Risks Right** — Flyvbjerg (PMI) `[LISTED]` | https://www.pmi.org/learning/library/nobel-project-management-reference-class-forecasting-8068 |
| **Reducing risks in megaprojects: the potential of reference class forecasting** `[LISTED]` | https://www.sciencedirect.com/science/article/pii/S2666721523000248 |
| **Reference class forecasting for Hong Kong's major roadworks projects** `[LISTED]` | https://www.researchgate.net/publication/305820925 |

**Use the critical paper, not just the promotional ones.** Cantarelli et al. document RCF's real
problems: the difficulty of defining a reference class that is both statistically valid and large
enough; **manipulation risk — stakeholders lowering initial estimates once they anticipate an
uplift**; and the question of whether historical risk data addresses genuine uncertainty at all.

This gives you a red-team slide that will impress a sceptical judge: *"here is the known failure
mode of our own base-rate layer, and here is what we do about it — we shrink toward a wider class
when n < 30, we publish the reference class with every forecast, and we monitor for estimate
drift at project inception."* Showing you know your method's weaknesses beats claiming it has none.

---

## 7. Research papers — why LightGBM, not a neural network

Expect the question *"why didn't you use deep learning?"* Have citations ready.

| Paper | Link |
|---|---|
| **Why do tree-based models still outperform deep learning on tabular data?** — Grinsztajn, Oyallon & Varoquaux, NeurIPS 2022 Datasets & Benchmarks `[LISTED]` | https://papers.neurips.cc/paper_files/paper/2022/file/0378c7692da36807bdec87ab043cdadc-Paper-Datasets_and_Benchmarks.pdf |
| **When Do Neural Nets Outperform Boosted Trees on Tabular Data?** — McElfresh et al., NeurIPS 2023 D&B. arXiv 2305.02997 `[LISTED]` | https://arxiv.org/abs/2305.02997 |
| **TabArena: A Living Benchmark for Machine Learning on Tabular Data** — arXiv 2506.16791 `[LISTED]` | https://arxiv.org/abs/2506.16791 |
| **Training GBDTs on Tabular Data Containing Label Noise** — arXiv 2409.08647 `[LISTED]` | https://arxiv.org/abs/2409.08647 |

Your answer: *"On tabular data of this size the published benchmarks favour gradient-boosted
trees, they train in seconds so we could run proper walk-forward validation instead of one split,
and SHAP gives a ministry-readable reason for every alert. We report a regularised logistic
baseline alongside — SIH26103 asks whether ML beats conventional statistics, so we have to show
the conventional model, not assume it loses."*

**Do not skip the baseline.** Research question 2 of the PS is literally a comparison. A team that
reports only the fancy model has failed to answer the question asked.

---

## 8. Data engineering — PDF parsing and data quality

| Resource | Link | Note |
|---|---|---|
| **A Comparative Study of PDF Parsing Tools Across Diverse Document Categories** — arXiv 2410.09871 `[LISTED]` | https://arxiv.org/abs/2410.09871 | Cite this when a judge asks how you chose your parser |
| `pdfplumber` | https://github.com/jsvine/pdfplumber | Primary tool. Word-level positions; best for these reports |
| `camelot` | https://camelot-py.readthedocs.io | Fallback for ruled tables. Needs Ghostscript |
| `tabula-py` | https://tabula-py.readthedocs.io | Second fallback. Needs Java |
| Camelot's own comparison wiki `[LISTED]` | https://github.com/camelot-dev/camelot/wiki/Comparison-with-other-PDF-Table-Extraction-libraries-and-tools | Honest about where each tool fails |
| `pandera` | https://pandera.readthedocs.io | Schema + validation for DataFrames. Implements `docs/data-quality-rules.md` |
| Great Expectations | https://greatexpectations.io | Heavier alternative; only if you have time |

**The rule that saves you:** every report contains its own summary totals. Parse the detail rows
*and* the summary, then assert they agree. `scripts/parse_report.py` already does this. A parser
that silently drops 8% of rows will destroy your model and you will never notice.

### Documentation standards (cheap marks, almost nobody does it)

| Resource | Link |
|---|---|
| **Datasheets for Datasets** — Gebru et al., arXiv 1803.09010 `[LISTED]` | https://arxiv.org/abs/1803.09010 |
| **Model Cards for Model Reporting** — Mitchell et al., arXiv 1810.03993 `[LISTED]` | https://arxiv.org/abs/1810.03993 |
| **Data Cards** — ACM FAccT 2022 `[LISTED]` | https://dl.acm.org/doi/10.1145/3531146.3533231 |

Ship a one-page model card with your demo. For a **government** deployment this is not decoration —
it is the artefact that lets an official defend using your output. Half a day's work, disproportionate credit.

---

## 9. LLM safety — if you use an LLM anywhere

| Resource | Link |
|---|---|
| **OWASP Top 10 for LLM Applications (2025)** | https://genai.owasp.org/llm-top-10/ |
| OWASP GenAI Security Project | https://genai.owasp.org |
| NIST AI Risk Management Framework | https://www.nist.gov/itl/ai-risk-management-framework |

**Non-negotiable rules for this project** (these are also good slide content):

1. **The model never writes SQL.** It picks from parameterised templates. Model-authored SQL
   against a government database is LLM01 prompt injection with a direct path to data.
2. **Numbers come from the database; only prose comes from the model.** Every figure in generated
   text is substituted from a query result after generation. No LLM-invented digits, ever.
3. **Enum-constrained decoding** for classification. The delay-cause classifier must emit one of
   your 13 labels, not free text.
4. **Read-only database role** for anything the LLM touches.
5. Free-text delay reasons entered by agency staff are **untrusted input**, not instructions.
   Treat them exactly as you would a web page.

---

## 10. TEE / confidential computing

**Be honest about scope, and say it before a judge says it for you:** the Flash Report data is
already public — it needs no TEE. The confidential layer is for the **production** deployment:
unpublished project entries, agency-entered free-text reasons, and draft risk lists that would
move contracts and reputations if leaked. That is a genuine argument. "We encrypted public PDFs"
is not, and a good judge will say so.

| Resource | Link |
|---|---|
| Confidential Computing Consortium | https://confidentialcomputing.io |
| AWS Nitro Enclaves | https://aws.amazon.com/ec2/nitro/nitro-enclaves/ |
| Azure confidential computing | https://learn.microsoft.com/en-us/azure/confidential-computing/ |
| Google Cloud Confidential Space | https://cloud.google.com/confidential-computing/confidential-space/docs |
| NVIDIA Confidential Computing (H100 / Blackwell) | https://www.nvidia.com/en-us/data-center/solutions/confidential-computing/ |
| Confidential Containers (CNCF) | https://confidentialcontainers.org |
| IETF RATS architecture (RFC 9334) | https://datatracker.ietf.org/doc/rfc9334/ |

**The flow to draw on your architecture slide** (RATS-style): enclave produces **evidence**
(CPU + GPU measurements) → **verifier** checks it → issues an attestation **token** → **key broker**
releases the decryption key *only* if the measurement matches the approved build → data decrypts
**inside** the boundary and never outside. **Fail closed:** no valid attestation, no key, no run.

**What TEEs do not give you** — say this yourself, it earns trust: they do not stop a bug in
*your* code inside the enclave, they do not prevent a legitimate user exfiltrating what they are
allowed to see, and they do not fix a bad access-control model. TEEs remove the *infrastructure
operator* from your trust boundary. That is all — and it is enough.

**Timeline discipline:** TEE is **P1, not P0.** If it is not working by **24 September**, ship the
architecture slide and the threat model, not the implementation. A clear diagram plus an honest
"designed, not yet deployed" beats a broken enclave in a live demo.

---

## 11. India compliance, hosting and policy

| Resource | Link | Relevance |
|---|---|---|
| CERT-In | https://www.cert-in.org.in | 2022 Directions: 6-hour incident reporting, 180-day log retention **within Indian jurisdiction**, NTP sync to NIC/NPL |
| MeitY | https://www.meity.gov.in | DPDP Act/Rules, empanelled cloud providers |
| GIGW (Guidelines for Indian Government Websites) | https://guidelines.india.gov.in | GIGW 3.0 + STQC certification — a government-facing UI is expected to comply |
| NIC | https://www.nic.in | MeghRaj / NIC cloud, the realistic hosting target |
| IndiaAI Mission | https://indiaai.gov.in | GPU empanelment — the credible answer to "where would you run this?" |

**One slide on this is worth two on your model.** Most teams present a system that could never be
deployed in a ministry. Showing you know it must run on empanelled infrastructure, log within
Indian jurisdiction, and meet GIGW signals that you have thought past the hackathon.

---

## 12. Tooling documentation

| Tool | Docs |
|---|---|
| LightGBM | https://lightgbm.readthedocs.io |
| scikit-learn | https://scikit-learn.org/stable/ |
| lifelines (survival) | https://lifelines.readthedocs.io |
| MAPIE (conformal) | https://github.com/scikit-learn-contrib/MAPIE |
| SHAP | https://shap.readthedocs.io |
| pandas | https://pandas.pydata.org/docs/ |
| pandera | https://pandera.readthedocs.io |
| pdfplumber | https://github.com/jsvine/pdfplumber |
| FastAPI | https://fastapi.tiangolo.com |
| DuckDB (fast local analytics on the panel) | https://duckdb.org/docs/ |

---

## 13. Known gaps — "evidence not found"

State these honestly if asked. Claiming otherwise is how good teams lose.

1. **No machine-readable project-monitoring feed exists.** eSankhyiki's API and Python client
   cover other MoSPI series, not central-sector project monitoring. The PDF panel is a necessity,
   not a stylistic choice.
2. **CRIP / Common Upload Form field-level schema is not public.** The PIB release does not name
   it. Your feature list is reconstructed from what the Flash Reports actually print. Say
   "derived from published reports", never "from the CRIP schema".
3. **No published benchmark for delay prediction on Indian central-sector projects.** The South
   Asia paper (§4) is the closest, at n = 138. You cannot claim to beat a state of the art that
   does not exist — you can claim to *establish* the first walk-forward baseline on this panel.
   That is a stronger and more defensible claim anyway.
4. **`data.gov.in` holdings unverified.** Check by hand before listing it as a data source.
5. **Per-project ground truth for actual completion dates is partial.** Many projects are ongoing
   (right-censored) and some disappear from reports without a stated outcome. §6.3 handles the
   first; document the second as a limitation.

---

## 14. Reading order for week 1

| Day | Read | Do |
|---|---|---|
| Day 1 | §3.1 ThePrint, §3.2 Business Standard, §2.1 PIB | Write your one-sentence problem framing. Run `make harvest`. |
| Day 2 | §4 South Asia paper | Get every Flash Report on disk. Verify the manifest. |
| Day 3 | §8 parsing | Parse one report end-to-end. Make summary totals reconcile. |
| Day 4 | §6.3 discrete-time survival | Build the project-month panel. Run the leakage shuffle test. |
| Day 5 | §6.1 calibration, §7 tabular ML | First baseline: logistic vs LightGBM, walk-forward. |
| Day 6 | §6.2 conformal, §6.4 reference class | Add intervals. Add the base-rate layer. |
| Day 7 | §9–§11 | Security, compliance and model-card slides. Freeze slide 1. |

---

## Citation hygiene

- Anything marked `[LISTED]` — **open it before you cite it.** A judge who finds one fabricated
  citation stops believing the other twenty.
- Prefer primary sources (MoSPI, PIB, the reports themselves) over news coverage for numbers;
  use news for framing.
- Every figure on a slide gets a source in the footer: outlet/ministry + date. It takes ten
  seconds and it is the cheapest credibility you will ever buy.
- Record the date you accessed each source. Government URLs move.
