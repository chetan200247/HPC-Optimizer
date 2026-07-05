# -*- coding: utf-8 -*-
# Content for the full project report. Executed within generate_report.py,
# where helpers (chapter, h2, h3, body, bullets, quote, code, figure, table,
# gap) and `story` are already defined.

# ══════════════════════════════════════════════════════════════════════════════
#  EXECUTIVE SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
chapter("Executive Summary")

body("Data centres and high-performance computing (HPC) facilities consume electricity "
     "around the clock. Globally they drew approximately 415 terawatt-hours in 2024 — "
     "about 1.5% of world electricity — and this is projected to double by 2030 as "
     "artificial-intelligence workloads accelerate. Yet the carbon footprint of that "
     "electricity is not constant: it changes every hour as the grid's generation mix "
     "shifts between clean sources (nuclear, hydro, wind, solar) and fossil fuels (coal, "
     "gas, oil). Despite this, the vast majority of facilities schedule their workloads "
     "on computational priority alone, with no awareness of grid conditions, so "
     "intensive jobs routinely run during the dirtiest hours of the day.")

body("This project designs, builds, validates and deploys an end-to-end carbon-aware "
     "scheduling system. It forecasts grid carbon intensity up to 48 hours ahead and "
     "identifies the cleanest windows in which to run <i>delay-tolerant</i> workloads, "
     "reducing Scope 2 emissions at zero additional hardware cost and with no reduction "
     "in computation performed. The system is validated using real per-node power "
     "telemetry from the Oak Ridge National Laboratory (ORNL) Summit supercomputer paired "
     "with real generation data from the Tennessee Valley Authority (TVA) grid, retrieved "
     "from the U.S. Energy Information Administration (EIA) API.")

body("The work spans the full analytics lifecycle: acquisition, integration, descriptive "
     "analysis, predictive forecasting, prescriptive optimisation and delivery through a "
     "live interactive dashboard. Along the way the project produced several findings of "
     "genuine analytical significance, three of which deserve emphasis:")

bullets([
    "<b>The clean window moves unpredictably.</b> Averaged across four years, the spread "
    "between the cleanest and dirtiest hour of the day on the TVA grid is only about 8 "
    "gCO₂/kWh — almost flat. Yet <i>within any single day</i> the range averages 51 "
    "gCO₂/kWh. The single most frequently cleanest hour (09:00) is optimal on only "
    "9.4% of days, so a fixed 'always run at hour X' rule misses the clean window on 90.6% "
    "of days. This proves that forecasting — not a static schedule — is required.",
    "<b>The best forecasting model is not the best scheduling model.</b> Of four models "
    "benchmarked, XGBoost achieved the lowest point-forecast error (MAE 17.95 gCO₂/kWh). "
    "But its recursive multi-step forecast collapses to a near-flat line, losing the daily "
    "<i>shape</i> that scheduling depends on — and when used to drive the scheduler it "
    "actually increased carbon. A simple shape-preserving forecast captured far more of the "
    "available saving. The metric that selects a forecaster (error) is not aligned with the "
    "objective that matters (ordering of clean hours).",
    "<b>Real constraints sharply reduce achievable savings — and honesty about this "
    "matters.</b> An unconstrained calculation suggested 314 tCO₂/year. Accounting for "
    "real cluster node capacity reduced the ceiling to 87 tCO₂/year, and accounting "
    "for forecast error reduced the realistic figure to roughly 34 tCO₂/year. Presenting "
    "this full hierarchy is more defensible than a single optimistic headline.",
])

body("The final deliverable is a publicly deployed Streamlit dashboard with two stakeholder "
     "views — an Operations Manager view with an interactive job scheduler, and a CSRD "
     "compliance view with audit-ready carbon reporting — backed by a fully reproducible "
     "Python codebase hosted on GitHub. This document records the entire journey: every "
     "major decision, the alternatives weighed against it, the methods that worked, those "
     "that did not, and the significance of what was found.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 1 — INTRODUCTION & BACKGROUND
# ══════════════════════════════════════════════════════════════════════════════
chapter("Introduction and Background")

h2("1.1  What is a data centre?")
body("A data centre is a physical building housing hundreds or thousands of computers — "
     "servers — that run continuously to deliver digital services: web applications, data "
     "storage, artificial-intelligence model training, scientific simulation. When a person "
     "streams a video or sends an email, the request is processed by servers in a data "
     "centre. Because these servers never switch off, they consume very large amounts of "
     "electricity. In 2024 data centres consumed roughly 415 TWh globally, comparable to "
     "the annual electricity use of a mid-sized country, and the International Energy Agency "
     "projects this could reach 945 TWh by 2030.")

h2("1.2  What is high-performance computing?")
body("A high-performance computing (HPC) centre is a specialised data centre built for a "
     "single purpose: executing extremely large scientific calculations that no single "
     "computer could handle. Thousands of powerful machines are wired together to act as "
     "one enormous computer. HPC centres simulate weather and climate, model protein "
     "folding for drug discovery, run nuclear-physics simulations and train large AI models. "
     "Jobs may run for hours, days or weeks and can occupy thousands of processors at once.")

body("The facility at the centre of this project is <b>ORNL Summit</b>, located at Oak Ridge "
     "National Laboratory in Tennessee and operated by the U.S. Department of Energy. When "
     "built in 2018 it was the world's most powerful supercomputer. Summit comprises "
     "<b>4,626 computing nodes</b>, each a powerful computer in its own right, and at full "
     "load draws approximately 13 megawatts — enough to power around 10,000 homes.")

h2("1.3  Why the source of electricity matters")
body("Not all electricity is equal from a climate perspective. Power generated by burning "
     "coal, gas or oil releases carbon dioxide; power from nuclear, solar, wind or hydro "
     "produces little or none. The measure of how much CO₂ is released per unit of "
     "electricity is <b>carbon intensity</b>, expressed in grams of CO₂ per kilowatt-hour "
     "(gCO₂/kWh). The higher the number, the dirtier the electricity.")

body("The decisive insight behind this project is that carbon intensity is <b>not constant</b>. "
     "It changes every hour with the mix of power plants currently generating. At 2 a.m. on a "
     "windy night a grid might be dominated by nuclear and wind (low intensity); at 7 p.m. on "
     "a hot evening every fossil plant may run at full capacity to meet peak demand (high "
     "intensity). A computational job that could be deferred a few hours to a cleaner window "
     "would emit substantially less CO₂ for exactly the same computation.")

h2("1.4  The opportunity")
body("Many HPC and data-centre jobs are time-flexible. A scientific parameter sweep due "
     "'sometime this week', a nightly backup, a machine-learning training run or a batch "
     "report does not need to start immediately. If such delay-tolerant work could be shifted "
     "into the cleanest hours, an organisation would cut its Scope 2 emissions without buying "
     "any new hardware and without performing less computation. This project quantifies that "
     "opportunity using real operational data, and builds the tools to capture it.")

h2("1.5  Regulatory context")
body("The urgency is amplified by regulation. The EU Corporate Sustainability Reporting "
     "Directive (CSRD), effective from 2025, requires large organisations to disclose Scope "
     "1, 2 and 3 greenhouse-gas emissions with third-party assurance. For data centres, "
     "Scope 2 emissions from purchased electricity are the dominant contributor. The European "
     "Energy Efficiency Directive further requires data centres above 2,780 MWh annual "
     "consumption to report performance metrics including Carbon Usage Effectiveness. A system "
     "that both reduces and credibly reports Scope 2 emissions therefore addresses a live "
     "commercial and compliance need.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 2 — PROBLEM STATEMENT & OBJECTIVES
# ══════════════════════════════════════════════════════════════════════════════
chapter("Problem Statement and Objectives")

h2("2.1  Problem statement")
quote("Data centres and HPC facilities consume electricity around the clock, yet the carbon "
      "footprint of that electricity changes significantly every hour depending on how it is "
      "generated. Most facilities schedule workloads on computational priority alone, with no "
      "awareness of these fluctuations, so intensive jobs routinely run during the dirtiest "
      "hours of the day simply because a server became available.")

body("This project addresses that gap by forecasting grid carbon intensity 48 hours ahead and "
     "recommending optimal scheduling windows for flexible workloads, reducing Scope 2 "
     "emissions without reducing computation. While ORNL Summit is used as the data source — "
     "being the only publicly available high-resolution per-node power dataset from a major "
     "operational computing facility — the methodology is directly replicable for any "
     "in-premise data centre running delay-tolerant workloads such as batch jobs, backups and "
     "model training.")

h2("2.2  Why ORNL, and why this generalises")
body("ORNL Summit is an extreme example of a computing facility, but it was chosen as a data "
     "source for a deliberate reason: it is the only public dataset providing per-node, "
     "per-minute power telemetry from a major operational facility, and it is peer-reviewed. "
     "The scheduling mechanism — identify which jobs can wait, forecast when the grid will be "
     "cleanest, run them then — is identical for any facility. In a typical corporate data "
     "centre the delay-tolerant workloads are nightly database backups, batch ETL and "
     "reporting pipelines, machine-learning training, video transcoding, log aggregation and "
     "software builds. Indeed, because HPC scientific jobs tend to be more tightly constrained "
     "than corporate batch work, the flexible fraction assumed here is a conservative lower "
     "bound for most commercial settings.")

h2("2.3  Objectives")
bullets([
    "Acquire and validate real demand (facility power) and supply (grid generation) data from "
    "authoritative sources.",
    "Integrate the two into a single hourly dataset and compute grid carbon intensity using "
    "internationally recognised emission factors.",
    "Characterise, through descriptive analysis, when the facility consumes power and when the "
    "grid is cleanest — establishing whether a scheduling opportunity genuinely exists.",
    "Forecast grid carbon intensity 48 hours ahead, comparing multiple modelling approaches "
    "rigorously on held-out data.",
    "Optimise the scheduling of flexible workloads into low-carbon windows under realistic "
    "node-capacity and deadline constraints, and honestly quantify the achievable saving.",
    "Deliver the results through an interactive dashboard serving two stakeholders — facility "
    "operators and sustainability/compliance officers — and deploy it publicly at no cost.",
])

h2("2.4  Alignment with the Sustainable Development Goals")
body("The work aligns directly with SDG 13 (Climate Action) by reducing greenhouse-gas "
     "emissions from computing, and with SDG 7 (Affordable and Clean Energy) by increasing the "
     "effective utilisation of clean generation that would otherwise be displaced by fossil "
     "dispatch at peak hours.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 3 — LITERATURE REVIEW
# ══════════════════════════════════════════════════════════════════════════════
chapter("Literature Review")

h2("3.1  The scale of the problem")
body("Data-centre electricity demand is one of the few sectors where emissions are projected "
     "to grow rather than decline (IEA, 2025). The challenge is not merely the magnitude of "
     "consumption but that it is drawn from grids whose carbon intensity fluctuates hourly. "
     "Most facilities schedule without awareness of these fluctuations, so computationally "
     "intensive jobs frequently run during periods of high fossil-fuel dispatch.")

h2("3.2  Evidence that carbon-aware scheduling works")
body("The feasibility of carbon-aware scheduling has been demonstrated at three levels of "
     "evidence. In production, temporal shifting has been deployed across more than 20 data "
     "centres on four continents, where day-ahead carbon-intensity forecasts were used to "
     "reshape cluster power profiles, achieving measurable reductions during peak-carbon hours "
     "(Radovanovic et al., 2023). In simulation, carbon-aware scheduling tested against HPC "
     "workload traces and national grid data has achieved up to 40.5% carbon reduction "
     "compared with conventional scheduling, with only an 8% increase in average job wait "
     "time, while an energy-only scheduler on the same workload achieved just 14.3% — "
     "confirming that carbon-intensity awareness, not merely energy efficiency, drives the "
     "reductions (Anasuri and Pappula, 2023). A broader survey of scheduling frameworks finds "
     "that greedy deferral heuristics capture over 90% of the achievable savings relative to "
     "complex optimal solutions (Emergent Mind, 2025).")

body("It is important to read these headline figures in context. The 40.5% reduction was "
     "achieved on grids and workloads with large carbon swings and high scheduling freedom. "
     "As this project's own results show, a nuclear-heavy grid such as TVA, combined with "
     "real node-capacity constraints, yields far more modest realistic savings. Reporting the "
     "achievable figure honestly, rather than citing the most favourable literature value, is "
     "a deliberate methodological stance taken throughout.")

h2("3.3  The flexible fraction of HPC workloads")
body("No single published study gives an exact split of delay-tolerant versus time-critical "
     "HPC jobs, because it varies by facility and scientific domain. The Bag-of-Tasks pattern "
     "— independent, parallelisable jobs — accounts for up to 70% of jobs on parallel systems, "
     "though these may consume a smaller share of total CPU-hours (Rodrigo et al., 2018). "
     "Actual utilisation in HPC clusters often reaches only about 60% of allocated capacity, "
     "with roughly 40% of computational units idling at any moment due to over-provisioning "
     "and scheduling fragmentation (Vergara Larrea et al., 2024) — a natural buffer within "
     "which flexible jobs can be shifted. At NERSC, 82–87% of jobs ran for two hours or less "
     "and 60% used under half their requested walltime, indicating significant runtime "
     "over-estimation and natural scheduling slack (Rodrigo et al., 2018). Synthesising this "
     "evidence, the project adopts a conservative <b>30% flexible-workload assumption</b> with "
     "a sensitivity range of 20–40%.")

h2("3.4  The regulatory imperative")
body("The EU CSRD (European Commission, 2024) mandates Scope 1–3 disclosure with assurance "
     "from 2025; for data centres Scope 2 dominates. The methodology in this project uses IPCC "
     "AR5 lifecycle emission factors precisely because they are the basis recognised under "
     "CSRD and the GHG Protocol, making the carbon figures audit-ready rather than merely "
     "indicative.")

h2("3.5  Positioning of this contribution")
body("Where existing work has focused on fleet-scale spatial shifting across continents or on "
     "theoretical simulations with synthetic workloads, this project is an end-to-end "
     "feasibility study that applies temporal shifting to a single on-premise facility using "
     "real power telemetry and real grid data, and quantifies the achievable saving under "
     "realistic constraints. Its contribution is not a new scheduling algorithm but a "
     "rigorous, honest, reproducible pipeline from raw data to a deployed decision-support "
     "tool — including the critical, and rarely reported, finding that point-forecast accuracy "
     "is the wrong objective for scheduling.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 4 — SOLUTION ARCHITECTURE & METHODOLOGY
# ══════════════════════════════════════════════════════════════════════════════
chapter("Solution Architecture and Methodology")

h2("4.1  The analytics lifecycle")
body("The project follows a five-stage analytics lifecycle, each stage feeding the next: "
     "Acquisition, Integration, Analysis (descriptive, predictive and prescriptive), and "
     "Delivery. This structure mirrors the Data Value Map presented to stakeholders and "
     "organises the remainder of this report.")

table([
    ["Stage", "Purpose", "Key technologies"],
    ["Acquisition", "Capture demand and supply data from authoritative sources",
     "pandas, pyarrow, requests, EIA API v2"],
    ["Integration", "Merge, clean, classify and compute carbon intensity",
     "pandas, NumPy"],
    ["Descriptive", "Characterise power and carbon-intensity patterns",
     "matplotlib, seaborn"],
    ["Predictive", "Forecast carbon intensity 48 hours ahead",
     "statsmodels, Prophet, XGBoost, TensorFlow"],
    ["Prescriptive", "Optimise job placement into clean windows",
     "PuLP + CBC solver"],
    ["Delivery", "Present insights to two stakeholder groups",
     "Streamlit, Plotly"],
], col_widths=[3*cm, 7.5*cm, 5*cm])

body("A guiding principle throughout is a <b>data-first mindset</b>: raw data is never "
     "modified; every load is validated at the point of entry; anomalies are treated, not "
     "dropped; all constants live in a single configuration file; the pipeline is idempotent; "
     "and every output is traceable to its source. These behaviours are revisited in the "
     "acquisition and integration chapters.")

h2("4.2  Engineering design decisions")
body("Several architectural decisions shaped the codebase and are worth recording explicitly, "
     "because they materially affected reproducibility and reliability.")

table([
    ["Decision", "Choice", "Rationale"],
    ["Configuration", "Single settings module", "No magic numbers in processing code; one "
     "place to audit thresholds, paths and emission factors"],
    ["Raw data", "Immutable", "Source of truth never overwritten; outputs are regenerated"],
    ["Storage format", "CSV for processed data", "Portable, Git-diffable, no database overhead "
     "for 120 + 35k row tables"],
    ["Idempotency", "Skip-if-exists", "Re-running never corrupts prior results"],
    ["Module reuse", "src/ imported by both pipeline and notebooks",
     "One implementation, used everywhere; no copy-paste drift"],
], col_widths=[3.2*cm, 4.3*cm, 8*cm])

h2("4.3  Reproducibility")
body("The complete pipeline runs from a single command, and each notebook re-derives its "
     "outputs from the processed data. The repository is public on GitHub, the dashboard is "
     "deployed on Streamlit Community Cloud, and the only secret — the EIA API key — is kept "
     "out of version control through an environment file. A reader can clone the repository, "
     "install dependencies, supply their own free API key and reproduce every figure in this "
     "report.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 5 — DATA ACQUISITION
# ══════════════════════════════════════════════════════════════════════════════
chapter("Data Acquisition")

h2("5.1  How the data is captured")
body("The project draws on <b>two datasets</b>, captured in two different ways — one passive, one "
     "active. A third input, the IPCC AR5 emission factors, is not a data feed but a set of "
     "published reference constants; it is therefore introduced in the Integration chapter "
     "(Section 6.2), where it is applied to convert the grid's fuel mix into carbon intensity.")

h3("Source 1 — ORNL Summit power telemetry (passive hardware capture)")
body("Summit's own monitoring infrastructure records power continuously during normal "
     "operation. Inside each node, two hardware layers emit readings. The NVIDIA Data Center "
     "GPU Manager (DCGM) reads the power draw of each of the six V100 GPUs from on-board "
     "sensors. Separately, the node's Baseboard Management Controller (BMC) reads the input "
     "wattage of each of the two power-supply units (PSUs) — the actual electricity drawn from "
     "the facility distribution, physically measured rather than estimated. These readings, "
     "averaged to one-minute resolution across all 4,626 nodes, were published as Apache "
     "Parquet files on the ORNL Constellation portal, associated with the peer-reviewed paper "
     "of Shin et al. (2021). The project downloads five pre-captured snapshot days.")

h3("Source 2 — TVA grid generation (active API retrieval)")
body("The Tennessee Valley Authority reports its hourly generation by fuel type to the EIA "
     "under FERC Order 830 — a legal mandate, not a voluntary submission. The project actively "
     "retrieves this through the EIA Open Data API v2, paginating in 5,000-record pages until "
     "the full 2019–2022 range is collected. The data arrives in long format (one row per fuel "
     "type per hour) and is saved verbatim before any processing.")

h2("5.2  Explicit data sources")
table([
    ["#", "Dataset", "Side", "Organisation", "Access", "Volume"],
    ["1", "Per-node power", "Demand", "ORNL (US DoE)", "Parquet download", "5 files, ~4 GB"],
    ["2", "TVA generation by fuel", "Supply", "EIA (federal)", "REST API v2", "280,503 rows"],
], col_widths=[0.8*cm, 4.2*cm, 1.7*cm, 3*cm, 3.3*cm, 2.5*cm])

h2("5.3  Evaluating source reliability")
body("Each source was assessed on authority, data lineage, completeness and consistency.")

h3("ORNL Constellation")
bullets([
    "<b>Authority:</b> a US Department of Energy national laboratory, one of the world's "
    "leading HPC institutions.",
    "<b>Peer review:</b> the exact dataset underpins Shin et al. (2021), published at SC '21, "
    "the flagship supercomputing conference.",
    "<b>Lineage:</b> readings come directly from hardware sensors (BMC, DCGM), not estimates.",
    "<b>Completeness:</b> about 0.02% of GPU readings are null (transient sensor dropouts).",
    "<b>Known limitation:</b> only five snapshot days exist — a dataset design choice, not a "
    "quality defect, but one that shapes how annual figures must be framed.",
])

h3("EIA API")
bullets([
    "<b>Authority:</b> the primary US federal energy-statistics agency.",
    "<b>Legal basis:</b> data reported under FERC Order 830, a regulatory obligation.",
    "<b>Cross-validation:</b> TVA's published annual generation matches the API totals.",
    "<b>Completeness:</b> 1,160 null values (0.4%), concentrated in solar in early 2019 when "
    "TVA had negligible solar capacity.",
    "<b>Known anomaly:</b> occasional negative values (pumped-hydro storage, solar net-metering "
    "artefacts) — physically meaningful, handled in integration.",
])

h2("5.4  Options considered and why the chosen approach was selected")
body("For demand data, three alternatives were rejected before settling on ORNL.")
table([
    ["Option", "Why rejected"],
    ["Synthetic workload traces", "Not representative of real production; a simulation, not "
     "an evidence base"],
    ["NERSC Perlmutter telemetry", "Per-node, per-minute PSU power not publicly available at "
     "this resolution"],
    ["Cloud (Google/AWS/Azure) data", "Not published at node level; only aggregate "
     "sustainability reports exist"],
    ["ORNL Summit (chosen)", "Only public per-node-per-minute PSU telemetry from a major "
     "facility; peer-reviewed; PSU input is true grid draw, no estimation"],
], col_widths=[5*cm, 10.5*cm])

body("For supply data, the chosen EIA API was weighed against commercial and regional "
     "alternatives.")
table([
    ["Option", "Why rejected"],
    ["Electricity Maps API", "Paid; historical data behind paywall; not reproducible"],
    ["WattTime API", "Provides marginal (not average) emissions; commercial licence"],
    ["Carbon Intensity UK API", "Wrong geography — ORNL is on the TVA grid"],
    ["CAISO / MISO feeds", "Different balancing authorities; not TVA"],
    ["EIA API v2 (chosen)", "Free, official, TVA-specific, complete for 2019–2022, "
     "cross-validated against TVA reports"],
], col_widths=[5*cm, 10.5*cm])

body("For emission factors, EPA eGRID and commercial real-time factors were considered but "
     "IPCC AR5 was selected because it is the CSRD-recognised basis and applies cleanly to a "
     "generation-mix composition rather than to specific plants.")

h2("5.5  Data-first behaviours in acquisition")
body("Validation occurs at the point of entry. The acquisition module logs, for every load, "
     "the row count, date range, fuel types present, null counts, the number and source of "
     "negative values, and the value range. Any deviation is surfaced before processing "
     "begins. The figure below, produced during acquisition, validates empirically that the "
     "250-watt threshold used later to classify a node as active sits in the natural gap of "
     "the bimodal GPU-power distribution.")
figure("gpu_threshold_check.png",
       "Figure 5.1  Empirical validation of the GPU active-node threshold. The distribution of "
       "total GPU power is multi-modal: a dense idle cluster near 200–225 W, a low-density valley "
       "around 225–275 W, then the active clusters. The chosen 250 W line (red) sits in the "
       "valley; 180 W and 200 W (grey/orange) fall inside the idle cluster and would misclassify "
       "idle nodes as active.")

body("The annual generation mix retrieved from the EIA API is shown below, confirming TVA as "
     "a nuclear-dominated grid with coal and gas providing flexible capacity.")
figure("tva_generation_mix.png",
       "Figure 5.2  TVA annual average hourly generation by fuel type, 2019–2022, "
       "retrieved from the EIA API. Nuclear provides the baseload; coal and gas flex to meet "
       "demand; wind and solar are negligible on this grid.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 6 — DATA INTEGRATION
# ══════════════════════════════════════════════════════════════════════════════
chapter("Data Integration")

h2("6.1  Overview")
body("Integration transforms two very different raw sources — minute-level per-node power and "
     "hourly grid generation — into a single aligned hourly dataset with carbon metrics. The "
     "demand side reduces roughly 34 million raw rows (6.8 million per file × 5 files) into "
     "120 hourly cluster-level rows; the supply side becomes 35,064 hourly rows; and the two "
     "are joined into a 120-row integrated table.")

h2("6.2  The integration decisions")
body("Twelve decisions defined this stage. Each is recorded with its rationale and the "
     "alternative rejected, because integration is where most of the project's methodological "
     "risk lived.")

h3("Decision 1 — Timezone alignment (the highest-risk step)")
body("ORNL timestamps are in UTC; TVA/EIA data is in Eastern Prevailing Time. Because Summit "
     "physically sits in TVA territory, the grid powering it at any moment is TVA's. The "
     "demand timestamps are therefore converted from UTC to US/Eastern before the join. "
     "Without this conversion every hour would be misaligned by four or five hours "
     "(daylight-saving dependent), silently attributing the wrong grid carbon to each "
     "workload hour. The correctness of the alignment is confirmed by the join producing "
     "<b>zero unmatched rows out of 120</b>. The rejected alternative — joining on raw UTC — "
     "would have invalidated every carbon figure undetectably.")

h3("Decision 2 — Active/idle classification")
body("The dataset's node-state column reads 'Powered On' for every row and is therefore "
     "useless for telling whether a node is running a job. Classification is instead inferred "
     "from GPU power: a node is active when its total GPU power across six V100s exceeds "
     "<b>250 W</b>. The threshold was set by inspecting the actual data rather than assuming a "
     "value. The per-node total-GPU-power distribution is clearly multi-modal: a dense idle "
     "cluster sits at roughly 200–225 W (idle V100s draw a little above their nominal 30 W once "
     "driver and power-management overhead are included), followed by a distinct low-density "
     "valley around 225–275 W, before the active clusters begin near 290 W and rise well beyond. "
     "A threshold of 250 W sits in the middle of that empty valley, cleanly separating the two "
     "states. Lower candidates were rejected on the evidence: 180 W or 200 W fall inside the idle "
     "cluster itself (classifying ~98–100% of readings as active, which is implausible), whereas "
     "250 W leaves a safe margin above idle fluctuation yet still catches every genuine workload "
     "(Figure 5.1). The rejected alternative of using PSU power as the classifier was discarded "
     "because PSU draw includes a large fixed node overhead that blurs the active/idle boundary.")

h3("Decisions 3–4 — Two-stage aggregation and the granularity decision")
body("Aggregation proceeds in two stages: minute readings are first averaged to a per-node "
     "hourly value, then summed across all nodes to a cluster-level hourly total. This "
     "preserves the per-node active/idle split before summing and keeps memory bounded by "
     "processing one 800 MB file at a time. Because grid carbon intensity is only published "
     "hourly, hourly is the finest meaningful join resolution; demand is therefore aggregated "
     "<i>up</i> to hourly rather than fabricating sub-hourly grid data.")

h3("Decision 5 — Carbon-intensity formula and emission factors")
body("This is the step where the grid's fuel mix becomes a single carbon number, and where the "
     "IPCC AR5 emission factors introduced in Section 5.1 are applied. For each hour the carbon "
     "intensity is the generation-weighted average of the lifecycle emission factors (IPCC Fifth "
     "Assessment Report, Working Group III, Annex III), chosen because they are the methodology "
     "recognised under the EU CSRD, making the resulting figures audit-ready:")
code("CI (gCO2/kWh) = sum( generation_fuel x EF_fuel ) / total_generation")
table([
    ["Fuel", "Factor (gCO₂/kWh)", "Note"],
    ["Coal (COL)", "1,000", "Highest emitter"],
    ["Petroleum (OIL)", "800", "Rare for electricity; included for completeness"],
    ["Natural Gas (NG)", "450", "Cleaner than coal; methane leakage in lifecycle"],
    ["Other (OTH)", "500", "Conservative geothermal/tidal assumption"],
    ["Nuclear · Hydro · Solar · Wind", "0", "No combustion; negligible at lifecycle median"],
], col_widths=[6*cm, 3.5*cm, 6*cm])
body("Because generation is in MWh and the factors are per kWh, the unit conversion cancels "
     "between numerator and denominator, yielding gCO₂/kWh directly. The result ranges from "
     "75.7 to 499.9 gCO₂/kWh across the four years, with a mean of 283.1.")

h3("Decisions 6–8 — Anomaly and missing-value handling")
body("Negative generation values are clipped to zero. Each negative has a physical "
     "explanation: TVA's Raccoon Mountain pumped-hydro facility consumes power to pump water "
     "uphill (appearing as negative generation, down to −1,155 MWh), and solar occasionally "
     "reports small negatives from net-metering. A PSU sensor fault in the January 2020 file "
     "produced an impossible −1,102 W reading, also clipped, since a power supply cannot push "
     "energy back to the grid. Missing values are filled group-wise — GPU nulls within each "
     "node, supply nulls within each fuel type — so a coal gap is never filled from nuclear. "
     "Crucially, <b>no rows are ever dropped</b>; the continuous hourly series the forecaster "
     "needs is preserved.")

h3("Decision 9 — Flexible fraction with sensitivity")
body("Because the ORNL data contains no job metadata, shiftability cannot be classified "
     "per job; a literature-backed 30% flexible fraction is applied, with every carbon column "
     "also computed at 20% and 40%. Computing all three in one pass makes the dashboard "
     "sensitivity analysis instantaneous.")

h3("Decisions 10–12 — Baseline, annualisation and storage")
body("The optimised case initially modelled shifting flexible energy to the day's lowest-CI "
     "hour — a greedy upper bound later refined in the optimisation chapter. Annual figures "
     "are projected as mean daily saving × 365 and explicitly labelled projections, because "
     "only five snapshot days exist. Processed data is stored as CSV, raw data is kept "
     "immutable, and the pipeline is idempotent.")

h2("6.3  Challenges experienced")
bullets([
    "<b>Timezone alignment</b> was the most error-prone step; a silent offset would have been "
    "undetectable without the zero-unmatched-rows check.",
    "<b>Granularity mismatch</b> forced a deliberate trade-off — aggregating fine-grained "
    "demand up to hourly rather than inventing sub-hourly grid data.",
    "<b>Physically real anomalies</b> (pumped hydro to −1,155 MWh) had to be distinguished "
    "from sensor faults (PSU −1,102 W); both were clipped but for different reasons.",
    "<b>DST-transition gaps</b> left three isolated hours with missing fuel rows after "
    "pivoting, filled with zero for the near-zero fuels affected.",
    "<b>Sparse demand</b> — five snapshot days rather than a continuous record — shaped the "
    "honest 'projection' framing of every annual figure.",
])

h2("6.4  Robustness of the hourly active/idle classification")
body("A node can be active for part of an hour and idle for the rest, so classifying it from its "
     "hourly-mean GPU power is an approximation of a sub-hourly mix. This was checked directly. "
     "On the January 2020 file, of 111,024 node-hours, 68.3% were active for the full hour, 7.8% "
     "idle for the full hour, and <b>23.9% were mixed</b> (both active and idle minutes). However, "
     "recomputing the day's total active energy with an exact per-minute classification changed "
     "the total by only <b>0.8%</b> versus the hourly-mean method. The distortion is small because "
     "most mixed hours are lopsided, over- and under-counts cancel across 4,626 nodes, and "
     "boundary cases carry little energy. This 0.8% is far below the uncertainty already carried "
     "by the 30% flexibility assumption (a ±10-point band), so the hourly-mean classifier is a "
     "sound simplification; the exact per-minute method remains available as a refinement.")

h2("6.5  The integrated dataset")
body("Integration yields three clean, fully validated, null-free outputs: a 120-row demand "
     "table, a 35,064-row supply table, and a 120-row integrated table carrying baseline and "
     "optimised carbon at all three flexibility assumptions. These feed every subsequent "
     "stage.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 7 — DESCRIPTIVE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
chapter("Descriptive Analysis")

body("Descriptive analysis answers three questions before any modelling: when does the "
     "facility consume power, when is the grid cleanest, and do these currently align or "
     "misalign? It is organised across the demand, supply and integrated layers.")

h2("7.1  Demand — power-consumption profiles")
body("Across the five snapshot days ORNL Summit averaged 76.5% node utilisation, with "
     "active (job-driven) energy representing 65–89% of total draw. Utilisation declined over "
     "the observation period — from 89% node utilisation in January 2020 to 56% by January "
     "2022 — consistent with Summit being progressively wound down as its exascale successor, "
     "Frontier, was commissioned. This declining trend is significant for the project: lower "
     "utilisation means more idle headroom, and therefore more room to shift flexible work.")

figure("eda_demand_hourly_profile.png",
       "Figure 7.1  Hourly active power and node utilisation for each of the five snapshot "
       "days. Utilisation is high but variable within each day, and declines across the "
       "two-year span.")

figure("eda_demand_active_idle_split.png",
       "Figure 7.2  Energy split between active (job-driven, shiftable) and idle (standby, "
       "fixed) load. Only the active portion can be scheduled; the rising idle share toward "
       "2022 reflects Summit's wind-down.")

figure("eda_demand_utilisation_heatmap.png",
       "Figure 7.3  Node-utilisation heatmap (five days × twenty-four hours). The absence of "
       "a single consistently-idle hour across days foreshadows the central scheduling "
       "challenge.")

h2("7.2  Supply — grid carbon-intensity patterns")
body("The TVA grid averaged 283 gCO₂/kWh over 2019–2022, ranging from 76 to 500, with a "
     "56.3% low-carbon share dominated by nuclear baseload. The grid decarbonised modestly "
     "over the period, from a 2019 mean of 301 to a 2022 mean of 293 gCO₂/kWh.")

figure("eda_supply_ci_by_hour.png",
       "Figure 7.4  Mean carbon intensity by hour of day with percentile bands. Strikingly, "
       "averaged across four years the daily profile is nearly flat — the cleanest and "
       "dirtiest hours differ by only about 8 gCO₂/kWh.")

figure("eda_supply_ci_heatmap_hour_month.png",
       "Figure 7.5  Mean carbon intensity by hour and month. Seasonal structure is visible "
       "(summer is dirtier), but no fixed hour-of-day is reliably clean across all months.")

figure("eda_supply_ci_trend.png",
       "Figure 7.6  Monthly mean carbon-intensity trend, 2019–2022, with the five ORNL "
       "snapshot months highlighted. The gentle downward trend strengthens the future case "
       "for carbon-aware scheduling.")

figure("eda_supply_ci_seasonal.png",
       "Figure 7.7  Seasonal distribution of carbon intensity. Summer (mean 334 gCO₂/kWh) is "
       "markedly dirtier than winter (254), explaining why the August snapshot days saved "
       "less carbon than the January ones.")

h2("7.3  The central finding — the clean window moves")
body("The single most important result of the descriptive phase emerges from contrasting two "
     "facts. Averaged across four years, the hour-of-day spread in carbon intensity is only "
     "about 8 gCO₂/kWh (Figure 7.4) — which would suggest time-of-day barely matters. Yet the "
     "carbon-intensity range <i>within</i> a single day averages 51 gCO₂/kWh, more than six "
     "times larger. The resolution is that on the TVA grid the clean window does not sit at a "
     "fixed hour: it moves unpredictably from day to day, driven by nuclear maintenance "
     "cycles, hydro availability and demand swings.")

figure("eda_supply_daily_ci_range.png",
       "Figure 7.8  Distribution of the daily carbon-intensity range across all 1,461 days. "
       "The mean within-day range is 51 gCO₂/kWh and 49% of days exceed 50 — a substantial "
       "scheduling opportunity that the flat hourly average conceals.")

figure("eda_supply_moving_clean_window.png",
       "Figure 7.9  The moving clean window. Left: the single most frequently cleanest hour "
       "(09:00) is optimal on only 9.4% of days, and every one of the 24 hours is the "
       "cleanest on at least ten days. Right: the cleanest hour scattered across the calendar "
       "shows no stable pattern.")

quote("Because the clean window is not fixed, a static 'always run at hour X' rule would miss "
      "it on 90.6% of days. To exploit the 51 gCO₂/kWh daily opportunity, the cleanest window "
      "must be forecast for each day. This single finding is the empirical justification for "
      "the entire predictive and prescriptive effort that follows.")

h2("7.4  Integrated — the opportunity made concrete")
body("Overlaying the grid carbon intensity with the facility's shiftable energy for each "
     "observed day visualises the mismatch the scheduler exists to correct.")

figure("eda_integrated_ci_vs_shiftable.png",
       "Figure 7.10  Grid carbon intensity (line) against shiftable energy (bars) for each of "
       "the five snapshot days, with the day's minimum-CI target marked. The opportunity is "
       "the gap between where energy is consumed and where the grid is cleanest.")

figure("eda_integrated_baseline_vs_optimised.png",
       "Figure 7.11  Average baseline versus optimised carbon emissions by hour of day, and "
       "the carbon saved per hour, indicating where temporal shifting helps most.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 8 — PREDICTIVE FORECASTING
# ══════════════════════════════════════════════════════════════════════════════
chapter("Predictive Forecasting")

h2("8.1  Objective and approach")
body("The descriptive phase established that the clean window must be forecast. The predictive "
     "phase builds and rigorously compares models that forecast TVA carbon intensity up to 48 "
     "hours ahead. Four models plus a naive baseline were evaluated: a seasonal-naive baseline, "
     "SARIMA, Prophet, XGBoost and (deferred) an LSTM.")

h2("8.2  Feature engineering")
body("From the supply series, 27 predictor features were engineered: autoregressive lags at "
     "1, 2, 3, 6, 12, 24, 48 and 168 hours; rolling means and standard deviations over 6, 24 "
     "and 168 hours; cyclical sine/cosine encodings of hour, day-of-week and month; calendar "
     "flags; and 24-hour-lagged fuel-mix shares. Cyclical encoding matters: it tells the model "
     "that hour 23 and hour 0 are adjacent on a circle rather than 23 units apart. The first "
     "168 rows, which lack complete lag history, are retained but excluded from training.")

h2("8.3  Evaluation methodology")
body("Time-series data cannot be split randomly without leaking the future into the past. The "
     "data was split chronologically: training on 2019-01 to 2022-08 (32,136 hours) and "
     "testing on the held-out final four months, 2022-09 to 2022-12 (2,928 hours). Models were "
     "evaluated by <b>rolling-origin 48-hour-ahead forecasting</b>: from origins spaced 24 "
     "hours apart across the test set (122 origins), each model forecast the next 48 hours, "
     "and errors were pooled into MAE, RMSE and MAPE and broken down by horizon.")

figure("fc_train_test_split.png",
       "Figure 8.1  Chronological train/test split. Training spans 2019 to August 2022; the "
       "held-out test period is September–December 2022. No future information leaks into "
       "training.")

h2("8.4  The naive baseline — a demanding bar")
body("Before the trained models, two naive baselines were computed. The seasonal-naive "
     "'same hour 24 hours ago' achieved MAE 19.27 gCO₂/kWh (MAPE 6.30%); the weekly version "
     "fared far worse at MAE 37.00. The strength of the 24-hour naive reflects the grid's "
     "strong daily persistence and sets a demanding bar: any model must beat MAE 19.27 to "
     "justify its complexity.")

h2("8.5  Model results")
body("Seven models were benchmarked in total: the naive baseline, SARIMA, Prophet and XGBoost, "
     "plus three common machine-learning regressors added to test whether XGBoost's win holds up "
     "— Linear Regression, Random Forest and k-Nearest Neighbours. All were run through the "
     "identical rolling-origin evaluation.")
table([
    ["Model", "MAE", "RMSE", "MAPE", "Beats naive?"],
    ["XGBoost (selected)", "17.95", "23.80", "6.80%", "Yes"],
    ["Random Forest", "19.16", "25.43", "7.19%", "Yes (just)"],
    ["Naive (24h)", "19.27", "25.41", "7.35%", "— baseline"],
    ["SARIMA", "20.60", "26.36", "7.95%", "No"],
    ["k-Nearest Neighbours", "23.46", "29.49", "8.78%", "No"],
    ["Prophet", "30.39", "37.94", "11.48%", "No"],
    ["Linear Regression", "52.63", "68.19", "19.75%", "No"],
], col_widths=[5.2*cm, 2.4*cm, 2.4*cm, 2.4*cm, 3*cm])

figure("fc_comparison_all.png",
       "Figure 8.2  Full seven-model comparison (MAE, rolling-origin 48-hour evaluation). Only "
       "XGBoost and Random Forest — both tree ensembles — beat the naive baseline.")

body("The extended benchmark reinforces the selection. <b>Only two of seven models beat the "
     "naive baseline, and both are tree ensembles</b> — confirming that family is the right "
     "choice, with gradient boosting (XGBoost) edging out bagging (Random Forest, MAE 19.16). "
     "The common alternatives behaved instructively: <b>Linear Regression failed badly</b> "
     "(MAE 52.63) because, over 48 recursive steps, a linear model extrapolates and compounds "
     "its errors; <b>k-NN was mid-pack</b> (23.46), hampered by the curse of dimensionality in "
     "a 27-feature space. That five of six trained models fail to clear the naive baseline "
     "underlines how strongly daily-periodic the TVA grid is.")

h2("8.6  What worked, what did not, and why")
h3("XGBoost — selected")
body("XGBoost, gradient-boosted trees over the engineered features, achieved the lowest error "
     "(MAE 17.95), trained in about two seconds and predicted instantly. Its feature "
     "importance confirmed that recent lags dominate — the last hour's carbon intensity alone "
     "carries over half the predictive weight.")

figure("fc_xgb_feature_importance.png",
       "Figure 8.3  XGBoost feature importance. Recent autoregressive lags dominate; "
       "calendar and fuel-mix features contribute marginally.")

h3("SARIMA — competitive but slower")
body("SARIMA with daily (24-hour) seasonality matched the naive at short horizons but degraded "
     "faster and was far slower to fit. To keep it tractable it was fitted on a recent 90-day "
     "window and rolled forward with state updates rather than full refits.")

h3("Prophet — a corrected near-failure")
body("Prophet initially produced a catastrophic MAE of 122 because, being non-autoregressive, "
     "a single global fit ignored recent observations and its trend extrapolation drifted "
     "badly over the four-month test horizon. The standard remedy for rolling forecasts — "
     "refitting on a trailing 180-day window at each origin, with yearly seasonality disabled "
     "and the trend tightened — reduced this to MAE 30.39. It remains the weakest model, an "
     "honest reflection that decomposition models are poorly suited to short-horizon, "
     "autoregressive grid forecasting.")

h3("LSTM — deferred")
body("A stacked LSTM was implemented but proved impractical to train reliably within "
     "reasonable time on the available CPU hardware, even after aggressive reduction of "
     "sequence length, network size and training-set stride. More importantly, the "
     "prescriptive phase later revealed that recursive multi-step neural forecasts suffer the "
     "same flattening problem as XGBoost for scheduling, so an LSTM would offer no advantage "
     "for the objective that matters. It was therefore deferred and documented honestly rather "
     "than forced.")

h2("8.7  The horizon finding")
body("Breaking error down by forecast horizon revealed where each model adds value.")

table([
    ["Horizon", "XGBoost", "Naive (24h)", "SARIMA", "Prophet"],
    ["h+1 to 6", "9.46", "15.87", "9.93", "27.67"],
    ["h+7 to 24", "16.33", "16.78", "18.15", "29.96"],
    ["h+25 to 48", "21.32", "22.01", "25.15", "31.40"],
], col_widths=[3.5*cm, 3*cm, 3*cm, 3*cm, 3*cm])

figure("fc_error_by_horizon.png",
       "Figure 8.4  Forecast error against horizon. Autoregressive models (XGBoost, SARIMA) "
       "excel at short horizons where recent carbon intensity carries signal; by 48 hours all "
       "models converge toward the naive, because two days out 'the same as yesterday' is "
       "close to the best anyone can do.")

figure("fc_example_windows.png",
       "Figure 8.5  Example 48-hour forecasts from each model against the actual carbon "
       "intensity for one test window.")

body("The horizon analysis carries a practical implication: a scheduler should weight the "
     "near-term forecast most heavily, because that is where the models are genuinely "
     "informative. It also foreshadows the prescriptive finding — that point accuracy, which "
     "this chapter optimised, is not the same as scheduling usefulness.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 9 — PRESCRIPTIVE OPTIMISATION
# ══════════════════════════════════════════════════════════════════════════════
chapter("Prescriptive Optimisation")

h2("9.1  From forecast to decision")
body("The prescriptive phase turns the forecast into an actual scheduling decision: given a "
     "job needing a number of nodes for a duration with a deadline, when should it run to "
     "minimise carbon? Three schedulers were built — a greedy heuristic, a Linear Programme, "
     "and a carbon-blind baseline — plus a fleet-level load-shifting Linear Programme for the "
     "headline figure.")

h2("9.2  The greedy job scheduler")
body("For a single flexible job the greedy scheduler slides a duration-wide window across the "
     "forecast within the deadline and selects the block with the lowest mean carbon intensity "
     "that fits node capacity; urgent jobs run immediately. It is fast, intuitive and powers "
     "the dashboard's interactive scheduler widget. The literature indicates greedy deferral "
     "captures over 90% of achievable savings, making it a strong baseline for the LP.")

figure("opt_job_placement.png",
       "Figure 9.1  Greedy placement of a four-hour job: deferring from hour 0 into a cleaner "
       "window later in the forecast reduces its carbon for identical computation.")

h2("9.3  The Linear Programme and the correct baseline")
body("When many jobs compete for the 4,626 nodes, greedy's first-come-first-served placement "
     "can be beaten by a Mixed-Integer Programme that places all jobs simultaneously, "
     "minimising total carbon subject to a one-run-per-job constraint, per-hour node-capacity "
     "limits and deadlines, solved with the open-source CBC solver via PuLP. An early test "
     "exposed a subtle but important error: comparing against a hypothetical 'everything runs "
     "at hour 0' baseline produced <i>negative</i> savings, because five jobs totalling 9,800 "
     "nodes cannot all run at once on a 4,626-node cluster. The correct as-is baseline is a "
     "<b>carbon-blind scheduler</b> that packs jobs as early as capacity allows while ignoring "
     "carbon — exactly what a real scheduler does today. Against that baseline the LP "
     "consistently beats greedy by resolving capacity contention globally, and neither can be "
     "worse than the baseline.")

h2("9.4  The fleet load-shifting Linear Programme")
body("An important honesty point governs the fleet-level figure. The historical power data "
     "contains no job metadata — no job identifiers, deadlines or durations — so the system "
     "cannot identify or move individual jobs. Instead it treats each day's active energy as a "
     "single <b>divisible pool</b> and asks how much carbon would be saved if the flexible "
     "portion (the literature-backed 30%) were shifted from dirty hours to clean ones. This is a "
     "load-redistribution model, not a job scheduler, and the 30% assumption is the bridge over "
     "the missing job data — which is why the fleet figures are feasibility estimates, presented "
     "as a range, rather than a record of jobs actually moved.")
body("Mechanically, a transportation LP redistributes each day's shiftable energy across hours, "
     "minimising carbon under the decision forecast and scored against the actual carbon "
     "intensity, subject to per-hour capacity headroom and a deferral-only constraint. This "
     "corrects the Phase-1 integrated figure, which had implicitly assumed all shiftable energy "
     "could be dumped into the single cleanest hour — ignoring that clean hours have limited "
     "spare capacity.")

h2("9.5  The savings hierarchy")
body("The result is a hierarchy of honest savings figures, each level adding a real-world "
     "constraint.")

table([
    ["Level", "Annual saving", "What it accounts for"],
    ["Unconstrained potential", "314 tCO₂/yr", "Shift to cleanest hour; ignores capacity"],
    ["Capacity-aware ceiling", "87 tCO₂/yr", "Real node limits; perfect (hindsight) forecast"],
    ["Realistic forecast-driven", "34 tCO₂/yr", "Capacity limits plus day-ahead forecast error"],
], col_widths=[4.5*cm, 3.5*cm, 7.5*cm])

figure("opt_savings_hierarchy.png",
       "Figure 9.2  The carbon-savings hierarchy. Each constraint — first capacity, then "
       "forecast error — reduces the achievable saving from the optimistic potential to a "
       "realistic figure. Presenting all three is more defensible than a single headline.")

body("Capacity is by far the largest single constraint: it cuts the achievable saving to only "
     "about a quarter of the unconstrained figure (314 → 87 tCO₂/yr). Although roughly half the "
     "available flexible energy can be moved, it cannot all reach the very cleanest hours — those "
     "hours are already carrying fixed load and fill up quickly — so much of it lands in "
     "merely-cleaner hours that save less per kilowatt-hour. This is a genuine and important "
     "correction to the optimistic Phase-1 figure, and it is more pronounced at the 250 W "
     "threshold, where higher measured utilisation leaves even less idle headroom to absorb "
     "shifted load.")

h2("9.6  The key finding — forecast shape beats point accuracy")
body("The most significant prescriptive result concerns which forecast to use. XGBoost won the "
     "predictive comparison on point accuracy, yet when used to drive the scheduler it "
     "performed worst of all — often producing <i>negative</i> savings. The reason is that its "
     "recursive multi-step forecast reverts to a near-flat line: it captures the average level "
     "well but loses the daily <i>shape</i>, and a scheduler fed a flat forecast cannot tell "
     "clean hours from dirty ones, so it shifts energy to the wrong hours. A simple "
     "shape-preserving forecast — yesterday's profile — captured roughly 39% of the "
     "capacity-aware ceiling, far more than XGBoost, and it is this shape-preserving forecast, "
     "not XGBoost, that drives the realistic saving reported above.")

table([
    ["Forecast driving the scheduler", "5-day saving", "Share of ceiling"],
    ["Hindsight (perfect CI)", "1,198 kg", "100% (ceiling)"],
    ["Yesterday's profile (shape-preserving)", "464 kg", "39%"],
    ["XGBoost (best point accuracy)", "negative", "harmful"],
], col_widths=[7.5*cm, 3.5*cm, 4*cm])

figure("opt_forecast_shape.png",
       "Figure 9.3  Forecast shape matters. Left: carbon saved per day by forecast type — "
       "XGBoost goes negative because its flat forecast misleads the scheduler. Right: the "
       "20 January 2022 case, where the actual cleanest hour (03:00) and the previous day's "
       "(18:00) were anti-correlated (r = −0.54) — the clean window flipped overnight.")

quote("The metric that selects a forecaster — point error — is not aligned with the objective "
      "that matters for scheduling: the correct ordering of clean and dirty hours. This is a "
      "genuine, and rarely reported, insight with direct practical consequences for anyone "
      "building such a system.")

h2("9.7  Phase 2 and Phase 4 lock together")
body("The catastrophic failure on 20 January 2022 is not a bug but the descriptive 'moving "
     "clean window' finding made concrete. On that day the clean window flipped from the "
     "previous day (correlation −0.54), so any day-ahead forecast misled the scheduler and "
     "committing energy to the forecast-clean hours actively increased carbon. The opportunity "
     "is real — the hindsight ceiling proves it — but capturing it is hard precisely because, "
     "on this grid, the target moves unpredictably. The descriptive phase predicted this "
     "difficulty; the prescriptive phase quantified it. That internal coherence is one of the "
     "project's stronger features.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 10 — DELIVERY & DEPLOYMENT
# ══════════════════════════════════════════════════════════════════════════════
chapter("Delivery and Deployment")

h2("10.1  Choosing the delivery platform")
body("The insights are delivered through an interactive Streamlit dashboard. Streamlit was "
     "chosen over Power BI and Tableau because the dashboard integrates directly with the "
     "Python analytics pipeline — the same environment used for forecasting and optimisation. "
     "This eliminates any need to export model outputs to an external tool and allows the "
     "scheduler to run live within the application.")

table([
    ["Option", "Why rejected / chosen"],
    ["Power BI / Tableau", "Would require exporting model outputs to an external tool, breaking "
     "the Python pipeline; no native way to run the live LP scheduler"],
    ["Static report / slides", "No interactivity; cannot run the scheduler against user input"],
    ["Streamlit (chosen)", "Runs the analytics pipeline in-app; free public hosting; fast to "
     "build; native Python"],
], col_widths=[4*cm, 11.5*cm])

h2("10.2  Two stakeholder views")
body("The dashboard serves two decision-makers with distinct needs.")

h3("Operations Manager view")
bullets([
    "Headline tiles: current grid carbon intensity, forecasted low, active node count, mean "
    "utilisation.",
    "A 48-hour forecast chart overlaying carbon intensity and electricity price on twin axes.",
    "An interactive job scheduler: the operator enters node count, duration, deadline and "
    "priority, sets a <b>carbon-vs-cost balance</b> on a slider, and the optimiser returns the "
    "recommended start time together with both the carbon saved (kg CO₂) and the cost saved "
    "($) in real time.",
])

h3("CSRD Compliance view")
bullets([
    "Headline tiles: projected annual saving, Scope 2 reduction, average grid carbon "
    "intensity, low-carbon share.",
    "The savings hierarchy, baseline-versus-optimised emissions, the grid fuel mix and the "
    "monthly carbon-intensity trend.",
    "An audit-ready CSV export and a methodology note citing IPCC AR5 factors and the "
    "flexibility assumptions — making the output suitable for CSRD Scope 2 disclosure.",
])

h2("10.3  Engineering for free, reliable deployment")
body("The dashboard was deliberately engineered to deploy free on Streamlit Community Cloud. "
     "It reads small precomputed files — about 50 kilobytes of CSV and JSON — and runs a "
     "numpy-only greedy scheduler, so it needs none of the heavy machine-learning libraries at "
     "runtime. The runtime dependency set is therefore just four packages (Streamlit, pandas, "
     "NumPy, Plotly), kept separate from the full pipeline dependencies. This makes the cloud "
     "build fast and robust. The repository is public on GitHub and the only secret, the EIA "
     "API key, is excluded from version control.")

h2("10.4  Technology decisions summary")
body("The architecture spans six layers, each with a deliberate technology choice: Parquet and "
     "the EIA REST API for sources; pandas, pyarrow and requests for ingestion; pandas and "
     "NumPy for integration; matplotlib, statsmodels, Prophet, XGBoost and PuLP for analytics; "
     "and Streamlit with Plotly for delivery — all coordinated by a single configuration "
     "module, structured logging and Git version control.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 11 — CONSOLIDATED FINDINGS & INSIGHTS
# ══════════════════════════════════════════════════════════════════════════════
chapter("Consolidated Findings and Insights")

h2("11.1  The findings, and why they matter")

h3("Finding 1 — The clean window moves unpredictably")
body("On the TVA grid the cleanest hour of the day moves from day to day; the most frequent "
     "clean hour is optimal only 9.4% of the time. <b>Significance:</b> this rules out simple "
     "static scheduling rules and justifies the whole forecasting effort. It also explains why "
     "savings on a nuclear-heavy, low-variability grid are inherently harder to capture than "
     "the headline figures from solar-heavy grids in the literature.")

h3("Finding 2 — Point-forecast accuracy is the wrong objective for scheduling")
body("XGBoost minimised forecast error but failed at scheduling because its recursive forecast "
     "lost the daily shape; a shape-preserving forecast did far better. <b>Significance:</b> "
     "this is a transferable lesson for any carbon-aware scheduling system — models should be "
     "selected and evaluated on the ordering of clean hours, not on aggregate error. It is a "
     "subtle point rarely made explicit in the literature.")

h3("Finding 3 — Real constraints sharply reduce achievable savings")
body("Capacity constraints roughly halved the achievable saving, and forecast error roughly "
     "halved it again: 314 → 87 → 34 tCO₂/year. <b>Significance:</b> honest, constraint-aware "
     "estimation produces a credible business case rather than an inflated one, and identifies "
     "cluster headroom and forecast quality as the two levers that most increase savings.")

h3("Finding 4 — The naive baseline is hard to beat")
body("The 'same hour yesterday' baseline achieved MAE 19.27, beaten only modestly by XGBoost. "
     "<b>Significance:</b> grid carbon intensity is strongly daily-periodic; sophisticated "
     "models add most value at short horizons, and a system should not assume complexity is "
     "automatically warranted.")

h3("Finding 5 — Utilisation headroom is rising")
body("Summit's node utilisation fell from 89% in early 2020 to 56% by 2022. "
     "<b>Significance:</b> falling utilisation increases the idle headroom available for "
     "shifting, so the opportunity grows precisely as facilities are under-utilised — a "
     "favourable dynamic for adoption.")

h2("11.2  How the findings interlock")
body("The findings are not independent observations but a coherent chain. The moving clean "
     "window (Finding 1) makes day-ahead shape hard to predict, which is why point-accurate "
     "but shape-poor models fail at scheduling (Finding 2), which in turn is a major reason "
     "the realistic figure falls so far below the capacity-aware ceiling (Finding 3). The "
     "project's descriptive phase predicted a difficulty that its prescriptive phase then "
     "measured — an internal consistency that lends the conclusions weight.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 12 — BUSINESS VALUE
# ══════════════════════════════════════════════════════════════════════════════
chapter("Business Value")

h2("12.1  Value to two stakeholders")
body("The Operations Manager uses the scheduling dashboard to shift flexible workloads into "
     "low-carbon windows, projecting a realistic 34 tonnes of CO₂ per year of avoided Scope 2 "
     "emissions from ORNL Summit alone, at zero additional hardware cost and with no reduction "
     "in computation. The Sustainability and Compliance Officer uses the CSRD view to track "
     "savings and export audit-ready reports, meeting EU CSRD Scope 2 disclosure requirements.")

h2("12.2  Why the value proposition is strong despite modest tonnage")
bullets([
    "<b>Zero capital expenditure</b> — it is a software change to the scheduling layer, not new "
    "infrastructure.",
    "<b>No performance penalty</b> — the same computation is performed; only its timing changes.",
    "<b>Compliance-ready</b> — hourly Scope 2 data and IPCC-based reporting directly serve CSRD "
    "disclosure, which is otherwise costly to produce.",
    "<b>Replicable and scalable</b> — the same method applies to any in-premise data centre with "
    "delay-tolerant workloads, where the flexible fraction is typically higher than in HPC, so "
    "the per-facility saving would be larger.",
    "<b>Improving over time</b> — as grids decarbonise and renewable variability grows, both the "
    "clean-window depth and the value of shifting increase.",
])

h2("12.3  The honest framing as an asset")
body("Presenting the full savings hierarchy rather than a single optimistic number is itself a "
     "business asset: it gives a sustainability officer a defensible figure that will survive "
     "third-party assurance, and gives an operations manager a clear understanding of the two "
     "levers — cluster headroom and forecast quality — that would increase the saving.")

h2("12.4  The cost dimension — joint carbon and cost optimisation")
body("The project's primary metric is carbon, but the scheduler was extended to co-optimise "
     "<b>electricity cost</b> alongside it, so the value proposition is not limited to emissions. "
     "The Operations Manager view carries a slider that sets a carbon-versus-cost balance; the "
     "optimiser blends the (normalised) carbon-intensity and electricity-price forecasts and "
     "returns the recommended start time with both the carbon saved and the money saved. Because "
     "TVA is a regulated utility with no public hourly market price, the cost side uses a "
     "representative Time-of-Use tariff — cheap overnight, expensive on-peak — clearly labelled "
     "as a model that a real deployment would replace with the facility's actual contract.")
body("An important honesty point governs this feature: <b>carbon-optimal is not the same as "
     "cost-optimal.</b> Clean hours are driven by the generation mix while cheap hours are driven "
     "by demand; they often overlap (overnight tends to be both cleaner and cheaper) but not "
     "always. On an evening-peak job, for example, deferring overnight can save both carbon and "
     "cost simultaneously, whereas chasing the single cleanest hour may push the job into an "
     "expensive on-peak slot. The slider makes this trade-off explicit and lets the operator "
     "choose — prioritise carbon, prioritise cost, or balance the two — rather than hiding it. "
     "This turns the tool from a carbon-only utility into a genuine operational decision aid, "
     "while the honest caveat keeps it from over-claiming an automatic bill reduction.")

h2("12.5  Cost–carbon trade-off and ROI")
body("To quantify the financial dimension, the load-shifting optimiser was swept across the full "
     "carbon-versus-cost weighting, recording for each setting the annual carbon saved and the "
     "annual electricity cost saved. This traces a Pareto trade-off frontier (Figure 12.1), with "
     "carbon then monetised at roughly $85/tCO₂ (EU ETS level) to give a single annual benefit.")
table([
    ["Setting", "Carbon (tCO₂/yr)", "Electricity ($/yr)", "Total benefit ($/yr)"],
    ["Pure cost (w=0)", "23.9", "$71,710", "$73,742"],
    ["Balanced (w=0.5)", "57.7", "$64,008", "$68,917"],
    ["Pure carbon (w=1)", "87.5", "−$4,837", "$2,597"],
], col_widths=[4*cm, 3.6*cm, 3.9*cm, 4*cm])
figure("cost_carbon_pareto.png",
       "Figure 12.1  Cost-versus-carbon trade-off frontier. As the weighting moves from cost to "
       "carbon, the recommended schedule trades electricity savings for emissions savings; the "
       "flat left region is a 'free-carbon' zone where both are captured at once.")
body("Three findings stand out. First, in money terms the <b>electricity cost savings (up to "
     "~$72,000/yr) dwarf the monetised carbon (~$2,000–7,400/yr) by a factor of ten to twenty-"
     "five</b>: the financial case rests on the bill, with carbon reduction as a valuable "
     "co-benefit. Second, there is a <b>'free-carbon' region</b> — at low carbon weight the full "
     "cost saving is captured together with about 45 tCO₂/yr, because cheap off-peak hours are "
     "often also cleaner. Third, <b>chasing maximum carbon can cost money</b> (pure carbon loses "
     "~$4,800/yr on the bill by pushing jobs into expensive on-peak hours), which is exactly the "
     "trade-off the slider exposes. Because the intervention is a software change costing "
     "essentially nothing, an annual benefit of tens of thousands of dollars implies effectively "
     "immediate payback — carbon-aware scheduling here is a <b>negative-cost abatement measure</b>, "
     "reducing emissions while being paid to do so. A structural bonus is that the ToU tariff is "
     "known in advance with no forecast error, so the cost savings are more reliably capturable "
     "than the forecast-dependent carbon savings. The dollar magnitudes scale with the modelled "
     "tariff and are illustrative; the shape of the trade-off does not.")

# ══════════════════════════════════════════════════════════════════════════════
#  CH 13 — LIMITATIONS
# ══════════════════════════════════════════════════════════════════════════════
chapter("Limitations")

bullets([
    "<b>Sparse demand data.</b> Only five snapshot days exist, not a continuous record, so all "
    "annual figures are projections (mean daily saving × 365), clearly labelled as such.",
    "<b>No job-level metadata.</b> The ORNL data records power, not job type or deadline, so "
    "shiftability is applied as a literature-backed 30% fraction rather than classified per job.",
    "<b>Single grid.</b> Results are specific to the nuclear-heavy TVA grid; a grid with higher "
    "renewable variability would offer deeper, though differently-shaped, clean windows.",
    "<b>Forecast difficulty.</b> Day-ahead carbon-intensity shape is hard to predict on TVA, "
    "limiting realised savings to roughly half the capacity-aware ceiling.",
    "<b>Static capacity model.</b> The load-shifting LP uses a representative per-node power and "
    "a fixed cluster capacity; a production system would use live node availability.",
    "<b>LSTM deferred.</b> The deep-learning model was not trained to completion on available "
    "hardware; its omission is documented rather than hidden.",
])

# ══════════════════════════════════════════════════════════════════════════════
#  CH 14 — FUTURE WORK
# ══════════════════════════════════════════════════════════════════════════════
chapter("Future Work")

bullets([
    "<b>Shape-aware forecasting.</b> Develop and evaluate forecasters explicitly on the ordering "
    "of clean hours — for example seasonal models, direct multi-horizon learners, or hybrid "
    "level-plus-shape models — rather than on aggregate error.",
    "<b>Spatial shifting.</b> Extend temporal shifting with cross-regional migration by "
    "substituting TVA data with other US grids (for example MISO or CAISO) to estimate the "
    "additional saving from running workloads where the grid is cleanest, not only when.",
    "<b>Probabilistic scheduling.</b> Use forecast confidence bands to hedge scheduling "
    "decisions, deferring less aggressively when the forecast is uncertain — directly "
    "addressing the days on which the clean window flips.",
    "<b>Stochastic and robust optimisation.</b> The current schedulers are Linear and "
    "Mixed-Integer Programmes solved on a single point forecast. The strongest optimisation "
    "extension is stochastic programming, which would optimise over a distribution of possible "
    "carbon-intensity scenarios rather than betting on one forecast, directly hedging the days "
    "when the clean window flips; robust optimisation offers a lighter worst-case alternative "
    "that needs no scenario probabilities. Both require far more than five days of data. "
    "Duality analysis of the existing LP is a quick add-on whose shadow prices would reveal "
    "which clean hours are the binding capacity bottlenecks. Non-linear programming is not "
    "warranted at this scale, and reinforcement learning would be disproportionate for a "
    "feasibility study.",
    "<b>Live integration.</b> Connect the scheduler to a real batch system (SLURM/PBS) and live "
    "node-availability and grid feeds for a production pilot. This is also what would replace "
    "the 30% flexibility assumption with real job metadata (deadlines and durations a live "
    "scheduler already holds), turning the feasibility study into a deployable system.",
    "<b>Continuous demand data.</b> Acquire a continuous facility power trace to replace the "
    "five-day projection with a measured annual figure.",
])

# ══════════════════════════════════════════════════════════════════════════════
#  CH 15 — CONCLUSION
# ══════════════════════════════════════════════════════════════════════════════
chapter("Conclusion")

body("This project set out to test whether carbon-aware scheduling could reduce the Scope 2 "
     "emissions of a computing facility using real data, and to deliver the result as a usable "
     "tool. It succeeded on both counts, and did so with an unusual degree of honesty about "
     "what is and is not achievable.")

body("The complete analytics lifecycle was built and validated: two authoritative data sources "
     "acquired and quality-assured; a carefully aligned hourly integrated dataset with "
     "audit-grade carbon intensity; a descriptive analysis that uncovered the pivotal "
     "moving-clean-window phenomenon; a rigorous forecasting comparison that selected XGBoost "
     "on point accuracy; a prescriptive optimisation that built greedy, LP and load-shifting "
     "schedulers; and a publicly deployed dashboard serving two stakeholders.")

body("Three findings give the work its character. The clean window on the TVA grid moves "
     "unpredictably, so forecasting is essential. The best point-forecast model is not the best "
     "scheduling model, because scheduling depends on the shape of the day rather than the "
     "accuracy of the level. And real constraints — node capacity and forecast error — reduce "
     "the achievable saving from an optimistic 314 to a realistic 34 tonnes of CO₂ per year, a "
     "figure presented openly as part of a hierarchy rather than disguised.")

body("The contribution is not a new algorithm but a rigorous, reproducible, honest pipeline "
     "from raw sensor data to a deployed decision-support tool — including a transferable "
     "lesson, rarely made explicit, that those building carbon-aware schedulers should select "
     "their forecasts on the ordering of clean hours, not on error alone. For an organisation "
     "facing CSRD disclosure, the result is a zero-capital, no-performance-penalty pathway to "
     "measurable and auditable carbon reduction, ready to replicate wherever delay-tolerant "
     "workloads run.")

# ══════════════════════════════════════════════════════════════════════════════
#  REFERENCES
# ══════════════════════════════════════════════════════════════════════════════
chapter("References")

for ref in [
    "Anasuri, S. and Pappula, K.K. (2023) 'Green HPC: Carbon-Aware Scheduling in Cloud Data "
    "Centers', IJERET, 4(2), pp. 106–114.",
    "Benhari, A. and Trystram, D. (2025) 'Adaptive Carbon-Aware Scheduling Policies for HPC "
    "Systems', Lecture Notes in Computer Science, 16210, pp. 1–15, Springer.",
    "EkkoSense (2025) 'ESG Data Centers — Climate Accountability Reporting for U.S. Data "
    "Centers'.",
    "Emergent Mind (2025) 'Carbon-Aware Scheduling — Survey of Frameworks'.",
    "European Commission (2024) 'Corporate Sustainability Reporting Directive (CSRD)'.",
    "IEA (2025) 'Energy and AI', International Energy Agency.",
    "Li, K. et al. (2025) 'More for Less: Integrating Capability-Predominant and "
    "Capacity-Predominant Computing', arXiv:2501.12464.",
    "Li, Z. et al. (2019) 'Thermal-Aware Hybrid Workload Management in a Green Datacenter "
    "Towards Renewable Energy Utilization', Energies, 12(8), pp. 1–18.",
    "Radovanovic, A. et al. (2023) 'Carbon-Aware Computing for Datacenters', IEEE Transactions "
    "on Power Systems, 38(2), pp. 1270–1280.",
    "Rodrigo, G.P. et al. (2018) 'Towards Understanding HPC Users and Systems: A NERSC Case "
    "Study', Journal of Parallel and Distributed Computing, 111, pp. 206–221.",
    "Shin, W. et al. (2021) 'Revealing Power, Energy and Thermal Dynamics of a 200PF "
    "Pre-Exascale Supercomputer', SC '21, ACM, Article 12, pp. 1–14.",
    "Vergara Larrea, V.G. et al. (2024) 'An HPC Co-Scheduler with Reinforcement Learning', "
    "arXiv:2401.09706.",
    "Verma, A. et al. (2015) 'Large-Scale Cluster Management at Google with Borg', EuroSys '15, "
    "ACM.",
]:
    story.append(Paragraph(ref, styles["Body"]))
    gap(2)

# ══════════════════════════════════════════════════════════════════════════════
#  APPENDICES
# ══════════════════════════════════════════════════════════════════════════════
chapter("Appendix A — Project Structure and Reproducibility")
body("The repository is organised into a configuration module, a data directory (raw and "
     "processed), a source package (acquisition, data, models, utilities), a pipelines runner, "
     "executed notebooks, diagrams, documentation and the deployed application.")
code("HPC Optimizer/\n"
     "  config/settings.py        single source of truth for constants & paths\n"
     "  data/raw/                 5 Parquet + supply CSV (gitignored)\n"
     "  data/processed/           pipeline outputs + charts\n"
     "  src/acquisition/          EIA API fetcher\n"
     "  src/data/                 demand, supply, integrator processors\n"
     "  src/models/               features, evaluation, forecaster, optimizer\n"
     "  pipelines/run_integration.py   one-command end-to-end runner\n"
     "  notebooks/01..05          executed analysis notebooks\n"
     "  app/main.py               Streamlit dashboard (two views)\n"
     "  docs/                     PROJECT_GUIDE, DEPLOY, this report\n"
     "  requirements.txt          slim deployment deps\n"
     "  requirements-dev.txt      full pipeline deps")

chapter("Appendix B — Decisions Log")
table([
    ["Stage", "Decision", "Chosen", "Rejected alternative"],
    ["Acquisition", "Demand source", "ORNL Summit", "Synthetic / cloud / NERSC"],
    ["Acquisition", "Supply source", "EIA API v2", "Electricity Maps / WattTime"],
    ["Acquisition", "Emission factors", "IPCC AR5", "EPA eGRID / commercial"],
    ["Integration", "Timezone", "UTC→Eastern", "Raw UTC join"],
    ["Integration", "Active classifier", "GPU > 250 W", "PSU power / node_state"],
    ["Integration", "Granularity", "Hourly", "Sub-hourly interpolation"],
    ["Integration", "Anomalies", "Clip to 0", "Drop rows"],
    ["Integration", "Missing values", "Group-wise fill", "Global fill / drop"],
    ["Forecasting", "Split", "Chronological", "Random split"],
    ["Forecasting", "Model", "XGBoost", "SARIMA / Prophet / LSTM"],
    ["Optimisation", "Baseline", "Carbon-blind", "Everything-at-hour-0"],
    ["Optimisation", "Fleet method", "Load-shift LP", "Unconstrained shift-to-min"],
    ["Delivery", "Platform", "Streamlit", "Power BI / Tableau"],
], col_widths=[2.6*cm, 3.2*cm, 3.4*cm, 6.3*cm], font=8.2)

chapter("Appendix C — Key Configuration and Results")
table([
    ["Parameter / Result", "Value"],
    ["Total nodes", "4,626"],
    ["GPU active threshold", "250 W"],
    ["Flexible fraction (sensitivity)", "30% (20–40%)"],
    ["Power per active node", "≈ 1.2 kW"],
    ["Mean grid carbon intensity", "283 gCO₂/kWh (76–500)"],
    ["Low-carbon grid share", "56.3%"],
    ["Mean cluster utilisation", "76.5%"],
    ["Selected forecast model", "XGBoost (MAE 17.95)"],
    ["Unconstrained annual saving", "314 tCO₂/yr"],
    ["Capacity-aware ceiling", "87 tCO₂/yr"],
    ["Realistic forecast-driven saving", "34 tCO₂/yr"],
    ["Hardware cost", "€0"],
], col_widths=[8.5*cm, 7*cm])

# ══════════════════════════════════════════════════════════════════════════════
#  APPENDIX D — DATA DICTIONARIES
# ══════════════════════════════════════════════════════════════════════════════
chapter("Appendix D — Data Dictionaries")

body("This appendix documents the columns of the three processed datasets so that any reader "
     "can interpret the outputs without reading the source code.")

h2("D.1  demand_engineered.csv (120 rows)")
table([
    ["Column", "Type", "Description"],
    ["local_hour", "datetime", "Hour bucket in Eastern Prevailing Time"],
    ["snapshot_date", "date", "One of the five ORNL observation days"],
    ["hour_of_day", "int", "0–23 hour within the day"],
    ["total_nodes", "int", "Nodes reporting that hour"],
    ["active_nodes", "int", "Nodes with GPU power > 250 W (running a job)"],
    ["idle_nodes", "int", "Nodes powered on but not running a job"],
    ["utilization_rate", "float", "active_nodes / total_nodes"],
    ["avg_gpu_power_W", "float", "Mean per-node total GPU power"],
    ["cluster_power_kW", "float", "Total cluster power that hour"],
    ["active_power_kW", "float", "Power attributable to active nodes"],
    ["idle_power_kW", "float", "Standby power of idle nodes"],
    ["active_energy_kWh", "float", "Active energy that hour (= active_power_kW × 1 h)"],
    ["shiftable_energy_kWh", "float", "30% of active energy (central assumption)"],
    ["shiftable_energy_20p_kWh", "float", "20% sensitivity"],
    ["shiftable_energy_40p_kWh", "float", "40% sensitivity"],
], col_widths=[5.3*cm, 2.2*cm, 8*cm], font=8.2)

h2("D.2  supply_engineered.csv (35,064 rows) — selected columns")
table([
    ["Column", "Type", "Description"],
    ["datetime", "datetime", "Hour in Eastern Prevailing Time"],
    ["COL, NG, NUC, OIL, OTH, SUN, WAT, WND", "float", "Generation by fuel type (MWh)"],
    ["total_generation_MWh", "float", "Sum across all fuels"],
    ["carbon_intensity_gCO2_per_kWh", "float", "Generation-weighted IPCC AR5 intensity"],
    ["low_carbon_share", "float", "Clean generation / total"],
    ["fossil_share", "float", "Fossil generation / total"],
    ["hour_of_day, day_of_week, month", "int", "Calendar features"],
    ["is_weekend", "int", "Weekend flag"],
    ["season", "str", "Winter / Spring / Summer / Autumn"],
    ["ci_rolling_24h, ci_rolling_7d", "float", "Rolling mean carbon intensity"],
    ["day_min_ci, day_max_ci", "float", "Daily minimum / maximum intensity"],
], col_widths=[6.3*cm, 2.2*cm, 7*cm], font=8.2)

h2("D.3  integrated.csv (120 rows) — selected columns")
table([
    ["Column", "Type", "Description"],
    ["carbon_intensity_gCO2_per_kWh", "float", "Grid intensity for that ORNL hour"],
    ["day_min_ci", "float", "Cleanest hour's intensity that day"],
    ["baseline_carbon_gCO2 / _kg", "float", "active_energy × actual intensity"],
    ["optimized_carbon_gCO2 / _kg", "float", "After shifting 30% to day minimum"],
    ["carbon_saved_gCO2 / _kg", "float", "Baseline − optimised (≥ 0)"],
    ["carbon_reduction_pct", "float", "Saving as % of baseline"],
    ["optimized_carbon_20p / 40p_gCO2", "float", "Sensitivity variants"],
    ["is_green_hour", "int", "1 if intensity ≤ daily median"],
    ["projected_annual_saving_tCO2", "float", "Mean daily saving × 365 (projection)"],
], col_widths=[6.3*cm, 2.2*cm, 7*cm], font=8.2)

# ══════════════════════════════════════════════════════════════════════════════
#  APPENDIX E — WORKED EXAMPLES
# ══════════════════════════════════════════════════════════════════════════════
chapter("Appendix E — Worked Examples")

h2("E.1  Computing carbon intensity for one hour")
body("Consider a single hour on the TVA grid with the following generation (MWh): Nuclear "
     "8,204; Hydro 4,751; Natural Gas 1,684; Coal 1,672; Other 11; with Solar, Wind and "
     "Petroleum at zero. The total is 16,322 MWh. Applying the IPCC AR5 factors:")
code("weighted = 1672*1000 + 1684*450 + 8204*0 + 4751*0 + 11*500\n"
     "         = 1,672,000 + 757,800 + 0 + 0 + 5,500\n"
     "         = 2,435,300  (gCO2 per MWh-equivalent units)\n"
     "CI = 2,435,300 / 16,322 = 149.2 gCO2/kWh")
body("This hour is unusually clean (149 versus the 283 mean) because nuclear and hydro "
     "together supply over 79% of generation and the only fossil contributions are modest "
     "coal and gas. The low-carbon share for this hour is (8,204 + 4,751) / 16,322 = 79.4%.")

h2("E.2  A greedy scheduling decision")
body("Suppose an operator submits a flexible job requiring 2,000 nodes for 4 hours, due "
     "within 24 hours, and the 48-hour forecast has its lowest 4-hour mean intensity at hours "
     "14–18 (300.9 gCO₂/kWh) versus 311.0 for running immediately at hours 0–4. The job's "
     "energy is:")
code("energy = nodes x power_per_node x duration\n"
     "       = 2000 x 1.2 kW x 4 h = 9,600 kWh")
body("Running now would emit 9,600 × 311.0 / 1000 = 2,985.6 kg CO₂; deferring to hours 14–18 "
     "emits 9,600 × 300.9 / 1000 = 2,888.6 kg. The saving is 97.0 kg CO₂ for identical "
     "computation — about 3.3% — achieved purely by waiting fourteen hours. This is exactly "
     "what the dashboard's scheduler widget returns.")

h2("E.3  Why capacity limits the fleet saving")
body("On 20 January 2020 the cluster's active energy peaked near 5,290 kWh in an hour, against "
     "a capacity ceiling of 4,626 nodes × 1.2 kW = 5,551 kWh. With roughly 70% of each hour's "
     "load fixed (non-shiftable), a clean evening hour carrying 2,800 kWh of fixed load can "
     "absorb only about 2,750 kWh of incoming shifted energy before hitting the ceiling. "
     "Across the few clean hours within reach, only about 11,091 kWh of the day's 30,477 kWh "
     "of shiftable energy could actually be moved — which is why the realistic saving is far "
     "below the unconstrained figure that assumed unlimited absorption.")

# ══════════════════════════════════════════════════════════════════════════════
#  APPENDIX F — GLOSSARY
# ══════════════════════════════════════════════════════════════════════════════
chapter("Appendix F — Glossary")

for term, defn in [
    ("Active node", "A node whose total GPU power exceeds 250 W, taken to indicate a running job."),
    ("Baseboard Management Controller (BMC)", "Embedded controller in each node that measures "
     "PSU input power independently of the operating system."),
    ("Balancing authority", "An entity responsible for matching electricity supply and demand "
     "on a grid; TVA is one."),
    ("Carbon intensity (CI)", "Grams of CO₂ emitted per kilowatt-hour of electricity; varies "
     "hourly with the generation mix."),
    ("Carbon-aware scheduling", "Scheduling workloads with awareness of grid carbon intensity "
     "to run them when electricity is cleanest."),
    ("CSRD", "EU Corporate Sustainability Reporting Directive, mandating Scope 1–3 emissions "
     "disclosure from 2025."),
    ("DCGM", "NVIDIA Data Center GPU Manager, which reads per-GPU power from on-board sensors."),
    ("Delay-tolerant workload", "A job that can be deferred without harm, e.g. a batch "
     "simulation, backup or training run."),
    ("Greedy heuristic", "A scheduler that places each job in the lowest-carbon feasible window "
     "one job at a time."),
    ("Linear Programme (LP) / MIP", "A mathematical optimisation that minimises an objective "
     "subject to linear constraints; MIP adds integer/binary variables."),
    ("Rolling-origin evaluation", "Forecasting from many successive origins and pooling errors, "
     "used to assess multi-step forecast accuracy honestly."),
    ("Scope 2 emissions", "Indirect emissions from purchased electricity — the dominant "
     "footprint for data centres."),
    ("Shiftable energy", "The portion of active energy assumed flexible enough to move to a "
     "cleaner hour (30% centrally)."),
    ("Temporal shifting", "Moving a workload to a different time to reduce its carbon, the core "
     "mechanism of this project."),
]:
    story.append(Paragraph(f"<b>{term}.</b> {defn}", styles["Body"]))
    gap(2)
