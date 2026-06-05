# Project Guide — Carbon-Aware Scheduling for Data Centres

**IS6611 Applied Research in Business Analytics · Group 11**

A complete walkthrough of the project: what it does, how it is built, how to run
it, how to read the outputs, and how to extend it.

---

## Table of Contents

1. [What This Project Does](#1-what-this-project-does)
2. [Core Concepts (for newcomers)](#2-core-concepts)
3. [Prerequisites & Setup](#3-prerequisites--setup)
4. [Project Structure](#4-project-structure)
5. [The Data Flow](#5-the-data-flow)
6. [How to Run Everything](#6-how-to-run-everything)
7. [Phase-by-Phase Walkthrough](#7-phase-by-phase-walkthrough)
8. [Configuration Reference](#8-configuration-reference)
9. [Outputs Reference](#9-outputs-reference)
10. [Key Numbers](#10-key-numbers)
11. [Troubleshooting](#11-troubleshooting)
12. [What Remains](#12-what-remains)

---

## 1. What This Project Does

Data centres and HPC facilities run around the clock, but the carbon footprint of
the electricity they draw changes every hour as the grid's generation mix shifts
between clean sources (nuclear, hydro, wind, solar) and fossil fuels (coal, gas).
Most schedulers ignore this and run jobs whenever a node is free — often during the
dirtiest hours.

This project **forecasts grid carbon intensity 48 hours ahead** and identifies the
cleanest windows so that **delay-tolerant workloads** can be shifted into them,
cutting Scope 2 carbon emissions **at zero hardware cost** with **no reduction in
computation**.

It is validated on real data from the **ORNL Summit supercomputer** and the
**Tennessee Valley Authority (TVA)** electricity grid, but the method replicates to
any in-premise data centre running flexible workloads (batch ETL, backups, ML
training, report generation).

---

## 2. Core Concepts

**Carbon intensity (CI)** — how much CO₂ is emitted per unit of electricity, in
**gCO₂/kWh**. Higher = dirtier. It changes hourly with the grid's fuel mix.

**Delay-tolerant workload** — a job that does not need to run immediately (e.g. a
batch simulation due "this week"). These can be shifted to cleaner hours. The
opposite is a **time-critical** job (real-time, hard deadline).

**Scope 2 emissions** — indirect emissions from purchased electricity. For data
centres this is the dominant footprint and is mandated for disclosure under the EU
**CSRD** (Corporate Sustainability Reporting Directive) from 2025.

**The opportunity** — if a flexible job runs when the grid is 70% nuclear instead of
60% coal, it emits far less CO₂ for the same computation.

---

## 3. Prerequisites & Setup

### Requirements
- Python 3.11+ (developed on 3.13)
- ~5 GB free disk (raw Parquet data)
- A free EIA API key — register at https://www.eia.gov/opendata/

### Install

```bash
cd "HPC Optimizer"
pip install -r requirements.txt
```

**macOS + XGBoost note:** XGBoost needs the OpenMP runtime. If you have Homebrew:
`brew install libomp`. If not, point XGBoost at scikit-learn's bundled copy (no
admin rights needed):

```bash
SKL=$(python3 -c "import sklearn,os;print(os.path.join(os.path.dirname(sklearn.__file__),'.dylibs'))")
XGB=$(python3 -c "import xgboost,os;print(os.path.join(os.path.dirname(xgboost.__file__),'lib','libxgboost.dylib'))")
install_name_tool -add_rpath "$SKL" "$XGB"
```

### Configure secrets

```bash
cp .env.example .env
# edit .env → EIA_API_KEY=your_key_here
```

### Add raw data
Place the 5 ORNL Parquet files in `data/raw/`:
```
data/raw/20200120.parquet   data/raw/20200820.parquet
data/raw/20210220.parquet   data/raw/20210810.parquet
data/raw/20220120.parquet
```
The TVA supply CSV is fetched automatically by Notebook 01 (or the pipeline) if not
already present.

---

## 4. Project Structure

```
HPC Optimizer/
├── config/
│   └── settings.py              # SINGLE source of truth — all constants & paths
├── data/
│   ├── raw/                     # 5 Parquet + supply CSV   (gitignored, large)
│   └── processed/               # pipeline outputs + charts (gitignored)
├── src/
│   ├── acquisition/
│   │   └── eia_fetcher.py       # EIA API client (paginated, idempotent)
│   ├── data/
│   │   ├── demand_processor.py  # ORNL Parquet → hourly cluster metrics
│   │   ├── supply_processor.py  # TVA CSV → hourly carbon intensity
│   │   └── integrator.py        # join demand × supply → carbon metrics
│   ├── models/
│   │   ├── features.py          # 27 engineered forecasting features
│   │   ├── evaluation.py        # split, metrics, rolling-origin harness
│   │   └── forecaster.py        # Baseline, SARIMA, Prophet, XGBoost, LSTM
│   └── utils/
│       └── logger.py            # shared logging format
├── pipelines/
│   └── run_integration.py       # one-command end-to-end runner
├── notebooks/
│   ├── 01_data_acquisition.ipynb
│   ├── 02_data_integration.ipynb
│   ├── 03_descriptive_eda.ipynb
│   └── 04_forecasting.ipynb
├── diagrams/                    # as-is, to-be, technology architecture (draw.io)
├── docs/
│   └── PROJECT_GUIDE.md         # this file
├── requirements.txt
├── .env.example
└── README.md
```

**Design principle:** nothing is hardcoded in processing code. Every path,
threshold, and factor lives in `config/settings.py`. Modules are imported by both
the pipeline runner and the notebooks, so there is one implementation, used
everywhere.

---

## 5. The Data Flow

```
  ORNL Parquet (5 days)          EIA API (TVA grid)
   6.8M rows/day                  280,503 rows
        │                              │
        ▼                              ▼
  demand_processor.py            supply_processor.py
   UTC→Eastern                    long→wide pivot
   GPU>300W = active              carbon intensity calc
   minute→hourly rollup           rolling + calendar features
        │                              │
        ▼                              ▼
  demand_engineered.csv          supply_engineered.csv
   (120 rows)                     (35,064 rows)
        │                              │
        └──────────────┬───────────────┘
                       ▼
                 integrator.py
            join on Eastern hour
            baseline vs optimised CO₂
                       │
                       ▼
              integrated.csv (120 rows)
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
   03_descriptive_eda         features.py → forecaster.py
   (patterns & insights)      (48h CI forecast, XGBoost)
```

**Why 120 demand rows?** 5 snapshot days × 24 hours = 120. Each row is one hour of
the entire 4,626-node cluster on one observed day.

---

## 6. How to Run Everything

### Option A — One command (recommended)

```bash
python pipelines/run_integration.py          # full pipeline (Steps 1–3)
python pipelines/run_integration.py --force   # re-run from scratch
python pipelines/run_integration.py --demand-only   # ORNL only
python pipelines/run_integration.py --supply-only   # TVA only
```

This produces `demand_engineered.csv`, `supply_engineered.csv`, and
`integrated.csv` in `data/processed/`.

### Option B — Notebooks (for exploration & charts)

Run in order:

| Notebook | Produces |
|----------|----------|
| `01_data_acquisition.ipynb` | Source inspection, GPU threshold validation, data-quality summary |
| `02_data_integration.ipynb` | Runs pipeline, demand/supply/carbon charts |
| `03_descriptive_eda.ipynb` | 11 EDA charts incl. the "moving clean window" insight |
| `04_forecasting.ipynb` | Model comparison, 5 forecasting charts |

To execute a notebook headless (and save outputs in place):
```bash
python -m jupyter nbconvert --to notebook --execute --inplace notebooks/03_descriptive_eda.ipynb
```

### Build the forecasting feature table directly
```bash
python -c "import sys; sys.path.insert(0,'.'); from src.models.features import build_features; build_features()"
```

---

## 7. Phase-by-Phase Walkthrough

### Phase 1 — Data Acquisition & Integration

**Acquisition.** Two sources: ORNL Summit telemetry (hardware sensors — BMC for PSU
input power, NVIDIA DCGM for GPU power) downloaded as Parquet, and TVA grid
generation fetched from the EIA API v2 (mandatory FERC Order 830 reporting). The
fetcher paginates 5,000 rows/page and skips if the file already exists.

**Integration — key decisions:**
- **Timezone:** ORNL is UTC, TVA is Eastern → convert ORNL to Eastern before
  joining (verified: 0/120 unmatched rows).
- **Active classification:** GPU total > 300W = running a job (V100s idle ~180W).
- **Aggregation:** minute → per-node hourly → cluster hourly (two stages).
- **Carbon intensity:** `CI = Σ(generation × IPCC_AR5_factor) / total_generation`.
- **Anomalies:** negatives clipped to 0 (pumped hydro, sensor faults); nulls filled
  group-wise; raw never modified.
- **Shiftable energy:** 30% of active energy (central), plus 20% and 40% sensitivity.

### Phase 2 — Descriptive EDA

Three layers — demand, supply, integrated. **The headline finding:** the grid's
clean window *moves unpredictably*. Hour-of-day CI averaged over 4 years spans only
~8 gCO₂/kWh (looks flat), but *within a single day* the range averages 51 gCO₂/kWh.
The most-frequent cleanest hour (09:00) is optimal on only 9.4% of days — so a fixed
"always run at X" rule misses the clean window 90.6% of the time. **This proves
forecasting is necessary.**

### Phase 3 — Predictive Forecasting

Forecast CI 48 hours ahead. Four models benchmarked with **rolling-origin
evaluation** (122 origins across a 4-month held-out test set), scored on MAE / RMSE /
MAPE:

| Model | MAE | Verdict |
|-------|-----|---------|
| **XGBoost** | **17.95** | Selected — best, beats naive by 6.8% |
| Naive (24h) | 19.27 | Strong baseline (CI is daily-periodic) |
| SARIMA | 20.60 | ≈ naive |
| Prophet | 30.39 | Worst — non-autoregressive |

XGBoost is ~40% better than naive at short horizons (h+1–6); all models converge to
naive by h+48. Feature importance confirms recent CI lags dominate.

---

## 8. Configuration Reference

All in `config/settings.py`:

| Setting | Value | Meaning |
|---------|-------|---------|
| `TOTAL_NODES` | 4626 | Summit cluster size |
| `GPU_ACTIVE_THRESHOLD_W` | 300 | Total GPU W above which a node is "active" |
| `SHIFTABLE_FRACTION` | 0.30 | Central flexible-workload assumption |
| `SHIFTABLE_LOW / HIGH` | 0.20 / 0.40 | Sensitivity bounds |
| `EMISSION_FACTORS` | dict | IPCC AR5 gCO₂/kWh per fuel |
| `FACILITY_TIMEZONE` | America/New_York | For ORNL UTC→Eastern conversion |
| `EIA_API_KEY` | from `.env` | EIA credential |

Emission factors: Coal 1000 · Gas 450 · Oil 800 · Nuclear/Solar/Hydro/Wind 0 · Other 500.

---

## 9. Outputs Reference

`data/processed/`:

| File | Rows | Description |
|------|------|-------------|
| `demand_engineered.csv` | 120 | Hourly cluster power, utilisation, shiftable energy |
| `supply_engineered.csv` | 35,064 | Hourly carbon intensity, fuel mix, features |
| `integrated.csv` | 120 | Baseline vs optimised carbon, all flex scenarios |
| `features_for_forecasting.csv` | 35,064 | 27 engineered model features |
| `forecast_comparison.csv` | 4 | Model MAE/RMSE/MAPE table |
| `*.png` | 16+ | All EDA and forecasting charts |

Chart prefixes: `eda_*` (Phase 2), `fc_*` (Phase 3).

---

## 10. Key Numbers

| Metric | Value |
|--------|-------|
| Mean TVA carbon intensity | 283 gCO₂/kWh (range 76–500) |
| Low-carbon grid share | 56.3% |
| Mean cluster utilisation | 68.7% |
| Total shiftable energy (5 days, 30%) | 137,887 kWh |
| Carbon saved (5 days) | 4,007.6 kg → 2.75% reduction |
| **Projected annual saving** | **293 tCO₂/year** (30% flex; range 195–390) |
| Forecast accuracy (XGBoost) | MAE 17.95 gCO₂/kWh |
| Hardware cost | €0 |

> The annual figure is a **projection** (mean daily saving × 365) extrapolated from
> 5 snapshot days, not a measured total.

---

## 11. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: config` | Run from project root, or ensure `sys.path` includes root (notebooks handle this automatically) |
| `XGBoostError: libomp` (macOS) | Apply the `install_name_tool` fix in §3 |
| `EIA_API_KEY not found` | Add it to `.env` |
| Supply CSV missing | Run Notebook 01 §3 to fetch from EIA |
| Pipeline says "SKIP" | Output already exists — use `--force` to re-run |
| Notebook `mticker not defined` | Already fixed; ensure imports are in the setup cell |

---

## 12. What Remains

| Phase | Scope | Status |
|-------|-------|--------|
| **Phase 4 — Prescriptive Optimisation** | Greedy heuristic + Linear Programming (PuLP/CBC) to place jobs in forecast clean windows under node & deadline constraints | Not started |
| **Phase 5 — Delivery** | Streamlit dashboard: Operations Manager view + CSRD Compliance view, job scheduler widget, audit exports | Not started |
| **Spatial shifting** | Compare TVA vs other US grids (MISO/CAISO) for cross-regional savings | Optional enhancement |

The full data-to-insight pipeline (acquisition → integration → descriptive →
predictive) is **built and validated**. What remains turns those forecasts into
actionable schedules (Phase 4) and packages them for stakeholders (Phase 5).
