"""
Central configuration for the HPC Carbon Optimizer project.

All paths, constants, and domain parameters are defined here.
Import from this module rather than hardcoding values in processing scripts.
"""

from pathlib import Path
import os

# ── Project root ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent

# ── Data paths ───────────────────────────────────────────────────────────────
RAW_DATA_DIR       = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"

# ORNL Summit per-node power (5 snapshot days)
ORNL_PARQUET_FILES = [
    RAW_DATA_DIR / "20200120.parquet",
    RAW_DATA_DIR / "20200820.parquet",
    RAW_DATA_DIR / "20210220.parquet",
    RAW_DATA_DIR / "20210810.parquet",
    RAW_DATA_DIR / "20220120.parquet",
]

# Map parquet filename → ISO date (Eastern time, where ORNL is located)
ORNL_DATE_MAP = {
    "20200120.parquet": "2020-01-20",
    "20200820.parquet": "2020-08-20",
    "20210220.parquet": "2021-02-20",
    "20210810.parquet": "2021-08-10",
    "20220120.parquet": "2022-01-20",
}

# TVA supply data from EIA API (may be in notebooks/ from prior run)
SUPPLY_CSV_CANDIDATES = [
    RAW_DATA_DIR / "supply_all_years.csv",
    PROJECT_ROOT / "notebooks" / "supply_all_years.csv",
]

# ── Processed output paths ────────────────────────────────────────────────────
DEMAND_OUTPUT     = PROCESSED_DATA_DIR / "demand_engineered.csv"
SUPPLY_OUTPUT     = PROCESSED_DATA_DIR / "supply_engineered.csv"
INTEGRATED_OUTPUT = PROCESSED_DATA_DIR / "integrated.csv"

# ── ORNL Summit cluster hardware config ──────────────────────────────────────
TOTAL_NODES = 4626

# The 6 GPU power columns across both sockets (p0: GPUs 0-2, p1: GPUs 3-5)
GPU_POWER_COLS = [
    "p0_gpu0_power", "p0_gpu1_power", "p0_gpu2_power",
    "p1_gpu0_power", "p1_gpu1_power", "p1_gpu2_power",
]

# PSU input power = actual watts drawn from the grid per node
PSU_POWER_COLS = ["ps0_input_power", "ps1_input_power"]

# Columns to read from each parquet file (drop ~60 temperature columns)
PARQUET_READ_COLS = ["timestamp", "hostname", "node_state"] + GPU_POWER_COLS + PSU_POWER_COLS

# A node is running a job when its total GPU power exceeds this threshold (Watts).
# Summit V100 GPUs idle at ~30 W each → 6 GPUs × 30 W = ~180 W idle total.
# Any meaningful GPU workload pushes total above 300 W.
GPU_ACTIVE_THRESHOLD_W = 300

# ── Workload flexibility assumptions (literature-backed) ─────────────────────
SHIFTABLE_FRACTION   = 0.30   # Conservative central estimate (30 %)
SHIFTABLE_LOW        = 0.20   # Sensitivity lower bound
SHIFTABLE_HIGH       = 0.40   # Sensitivity upper bound

# Representative power drawn by one active node (kW), derived empirically from
# the ORNL data (active_power_kW / active_nodes ≈ 1.2 kW mean). The scheduler
# uses this to convert (nodes × duration) into energy, then energy × CI into carbon.
POWER_PER_NODE_KW = 1.2

# Forecast horizon for scheduling decisions (hours).
FORECAST_HORIZON_H = 48

# ── Emission factors — IPCC AR5 lifecycle medians (gCO₂ / kWh generated) ─────
EMISSION_FACTORS = {
    "COL": 1000,   # Coal
    "NG":   450,   # Natural Gas
    "OIL":  800,   # Petroleum
    "NUC":    0,   # Nuclear
    "SUN":    0,   # Solar
    "WAT":    0,   # Hydro
    "WND":    0,   # Wind
    "OTH":  500,   # Other (geothermal / tidal mix)
}

CLEAN_FUELS  = ["NUC", "SUN", "WAT", "WND"]
FOSSIL_FUELS = ["COL", "NG",  "OIL"]
ALL_FUELS    = list(EMISSION_FACTORS.keys())

# ── EIA API config ────────────────────────────────────────────────────────────
EIA_API_KEY      = os.getenv("EIA_API_KEY", "")
EIA_BASE_URL     = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
TVA_RESPONDENT   = "TVA"
EIA_FETCH_START  = "2019-01-01T00"
EIA_FETCH_END    = "2022-12-31T23"
EIA_PAGE_SIZE    = 5000

# ── Timezone ──────────────────────────────────────────────────────────────────
# ORNL is in Oak Ridge, Tennessee → Eastern Prevailing Time, same as TVA grid data
FACILITY_TIMEZONE = "America/New_York"
