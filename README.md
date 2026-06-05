# HPC Carbon Optimizer

**IS6611 Applied Research in Business Analytics — Group 11**  
Carbon Emission Reduction in Data Centres through Smart Scheduling

---

## Overview

This project builds an end-to-end analytics pipeline that:

1. **Ingests** ORNL Summit per-node power telemetry (5 snapshot days) and TVA electricity grid generation data (2019–2022)
2. **Computes** hourly carbon intensity for the TVA grid and active energy demand for the ORNL cluster
3. **Quantifies** carbon savings achievable by shifting delay-tolerant workloads into low-carbon windows
4. **Delivers** results via a Streamlit dashboard with CSRD compliance and Operations Manager views

---

## Project Structure

```
hpc-carbon-optimizer/
├── config/
│   └── settings.py              # All constants: emission factors, paths, thresholds
├── data/
│   ├── raw/                     # ORNL .parquet files + supply_all_years.csv (gitignored)
│   └── processed/               # Pipeline outputs (gitignored)
├── src/
│   ├── data/
│   │   ├── demand_processor.py  # ORNL parquet → hourly cluster metrics
│   │   ├── supply_processor.py  # TVA CSV → carbon intensity per hour
│   │   └── integrator.py        # Merge demand + supply, compute carbon metrics
│   ├── models/                  # Forecasting & optimisation (Phase 3)
│   └── utils/
│       └── logger.py
├── pipelines/
│   └── run_integration.py       # CLI runner for the integration phase
├── notebooks/
│   ├── 01_data_acquisition.ipynb
│   └── 02_data_integration.ipynb
└── app/                         # Streamlit dashboard (Phase 4)
```

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd hpc-carbon-optimizer
pip install -r requirements.txt
```

> **macOS note (XGBoost):** XGBoost needs the OpenMP runtime `libomp`. If you have
> Homebrew, run `brew install libomp`. If not, scikit-learn ships a copy you can
> point XGBoost at without admin rights:
> ```bash
> SKL=$(python3 -c "import sklearn,os;print(os.path.join(os.path.dirname(sklearn.__file__),'.dylibs'))")
> XGB=$(python3 -c "import xgboost,os;print(os.path.join(os.path.dirname(xgboost.__file__),'lib','libxgboost.dylib'))")
> install_name_tool -add_rpath "$SKL" "$XGB"
> ```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your EIA API key (free at https://www.eia.gov/opendata/)
```

### 3. Add data files

Place the 5 ORNL parquet files in `data/raw/`:
```
data/raw/20200120.parquet
data/raw/20200820.parquet
data/raw/20210220.parquet
data/raw/20210810.parquet
data/raw/20220120.parquet
```

If `supply_all_years.csv` is not yet in `data/raw/`, run Notebook 01 to fetch it from the EIA API.

### 4. Run the integration pipeline

```bash
# Full pipeline (Steps 1–3)
python pipelines/run_integration.py

# Re-run everything from scratch
python pipelines/run_integration.py --force

# Step 1 only (ORNL demand — ~15–25 min)
python pipelines/run_integration.py --demand-only

# Step 2 only (TVA supply — < 1 min)
python pipelines/run_integration.py --supply-only
```

### 5. Explore with notebooks

```bash
jupyter notebook notebooks/
```

| Notebook | Description |
|----------|-------------|
| `01_data_acquisition.ipynb` | Schema inspection, GPU threshold validation, EIA API fetch |
| `02_data_integration.ipynb` | Run pipeline, visualise demand/supply profiles, carbon savings |

---

## Data Sources

### ORNL Summit Power Telemetry
- **What:** Per-node power consumption (4,626 nodes, 1-minute intervals)
- **Period:** 5 snapshot days — 2020-01-20, 2020-08-20, 2021-02-20, 2021-08-10, 2022-01-20
- **Source:** [ORNL Constellation](https://constellation.ornl.gov/)
- **Format:** Parquet, ~800 MB per file

### TVA Electricity Grid Power Mix
- **What:** Hourly generation by fuel type (MWh) for the Tennessee Valley Authority grid
- **Period:** January 2019 – December 2022
- **Source:** EIA API v2 (`electricity/rto/fuel-type-data`)
- **Fuel types:** Coal (COL), Natural Gas (NG), Nuclear (NUC), Petroleum (OIL), Solar (SUN), Hydro (WAT), Wind (WND), Other (OTH)

---

## Key Parameters

| Parameter | Value | Source |
|-----------|-------|--------|
| GPU active threshold | 300 W (total of 6 GPUs) | ORNL V100 idle ~180 W |
| Shiftable workload fraction | 30% (central estimate) | Literature review (Appendix) |
| Sensitivity range | 20% – 40% | Literature review |
| Coal emission factor | 1,000 gCO₂/kWh | IPCC AR5 lifecycle |
| Natural Gas emission factor | 450 gCO₂/kWh | IPCC AR5 lifecycle |
| Nuclear / Solar / Hydro / Wind | 0 gCO₂/kWh | IPCC AR5 lifecycle |

---

## Pipeline Outputs

After running the pipeline, `data/processed/` will contain:

| File | Description | Rows |
|------|-------------|------|
| `demand_engineered.csv` | Hourly cluster-level power and shiftable energy | 120 (5 days × 24h) |
| `supply_engineered.csv` | Hourly carbon intensity and grid mix | ~35,040 (4 years) |
| `integrated.csv` | Merged dataset with baseline and optimised carbon metrics | 120 |

---

## Team

| Name | Student ID |
|------|-----------|
| Aditya Anil More | 125122479 |
| Chetan Dummegere Kumar | 125111933 |
| Jobi Joy Mathew | 125111294 |
| Kartik Anil Shah | 124119829 |
| Sarvesh Deepak Pisal | 125119869 |
| Srushti Rajendrakumar Shetti | 125121632 |
