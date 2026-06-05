"""
ORNL Summit demand data processor.

Input  : 5 parquet snapshot files (minute-level, per-node, ~800 MB each)
Output : demand_engineered.csv  (hourly, cluster-level, 5 × 24 = 120 rows)

Processing steps
────────────────
1. Read only the 12 power-relevant columns (skip ~60 temperature columns).
2. Convert UTC timestamps → Eastern Prevailing Time (facility local time),
   then floor to the hour boundary for aggregation.
3. Derive per-node metrics:
     total_gpu_power_W  = sum of all 6 GPU power readings
     total_node_power_W = sum of the two PSU input readings (actual grid draw)
     is_active          = total_gpu_power_W > GPU_ACTIVE_THRESHOLD_W
4. Aggregate minute-level rows → per-node per-hour averages.
5. Aggregate per-node per-hour → cluster-level hourly totals.
6. Annotate with shiftable energy at 20 %, 30 %, and 40 % flexibility.
7. Concatenate all 5 days and save.

Timezone note
─────────────
The EIA / TVA grid data is published in Eastern Prevailing Time (EPT).
ORNL data is UTC.  Converting ORNL to Eastern before flooring to the hour
ensures demand and supply records join on the same local-time index.
"""

import gc
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from config.settings import (
    ORNL_PARQUET_FILES,
    ORNL_DATE_MAP,
    PARQUET_READ_COLS,
    GPU_POWER_COLS,
    PSU_POWER_COLS,
    GPU_ACTIVE_THRESHOLD_W,
    SHIFTABLE_FRACTION,
    SHIFTABLE_LOW,
    SHIFTABLE_HIGH,
    TOTAL_NODES,
    DEMAND_OUTPUT,
    FACILITY_TIMEZONE,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def process_all_days(
    parquet_files: Optional[List[Path]] = None,
    output_path: Optional[Path] = None,
    gpu_threshold: float = GPU_ACTIVE_THRESHOLD_W,
) -> pd.DataFrame:
    """
    Process all ORNL parquet files and return the combined hourly demand DataFrame.

    Parameters
    ----------
    parquet_files : list of Path, optional
        Override the default list from settings.
    output_path : Path, optional
        Where to save the CSV.  Uses settings.DEMAND_OUTPUT when None.
    gpu_threshold : float
        Total-GPU-power threshold (W) for classifying a node as active.

    Returns
    -------
    pd.DataFrame
        One row per (snapshot_date, local_hour), 120 rows total.
    """
    if parquet_files is None:
        parquet_files = ORNL_PARQUET_FILES
    if output_path is None:
        output_path = DEMAND_OUTPUT

    daily_frames: List[pd.DataFrame] = []

    for filepath in parquet_files:
        filepath = Path(filepath)
        date_str = ORNL_DATE_MAP.get(filepath.name, filepath.stem)

        logger.info(f"Processing {filepath.name}  →  {date_str}")

        raw = _load_file(filepath)
        hourly = _aggregate_to_hourly(raw, date_str, gpu_threshold)

        logger.info(
            f"  {len(hourly)} hourly rows | "
            f"avg utilisation {hourly['utilization_rate'].mean():.1%} | "
            f"avg CI-relevant active power {hourly['active_power_kW'].mean():.0f} kW"
        )

        daily_frames.append(hourly)
        del raw
        gc.collect()

    combined = (
        pd.concat(daily_frames, ignore_index=True)
        .sort_values(["snapshot_date", "local_hour"])
        .reset_index(drop=True)
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)

    logger.info(
        f"\nSaved → {output_path}  "
        f"({len(combined)} rows, {combined['snapshot_date'].nunique()} days)"
    )
    _print_demand_summary(combined)

    return combined


def validate_gpu_threshold(filepath: Path) -> pd.Series:
    """
    Return the distribution of per-node total-GPU-power for one parquet file
    so the caller can inspect whether GPU_ACTIVE_THRESHOLD_W is appropriate.

    Prints percentiles and returns the full Series.
    """
    filepath = Path(filepath)
    df = pd.read_parquet(filepath, columns=GPU_POWER_COLS + ["hostname"])
    total_gpu = df[GPU_POWER_COLS].sum(axis=1)

    pcts = [0, 5, 10, 25, 50, 75, 90, 95, 99, 100]
    logger.info("Total-GPU-power distribution (W) — %s", filepath.name)
    for p, v in zip(pcts, np.percentile(total_gpu.dropna(), pcts)):
        marker = " ← threshold" if abs(v - GPU_ACTIVE_THRESHOLD_W) < 50 else ""
        logger.info(f"  p{p:3d}: {v:8.1f} W{marker}")

    return total_gpu


# ── Private helpers ───────────────────────────────────────────────────────────

def _load_file(filepath: Path) -> pd.DataFrame:
    """
    Load one parquet file, select power columns, convert timestamps to
    facility local time (Eastern Prevailing), and derive per-node metrics.
    """
    df = pd.read_parquet(filepath, columns=PARQUET_READ_COLS)

    # Convert UTC → Eastern Prevailing Time, then strip tz for simplicity
    df["timestamp"] = (
        pd.to_datetime(df["timestamp"], utc=True)
        .dt.tz_convert(FACILITY_TIMEZONE)
        .dt.tz_localize(None)
    )

    # Hour bucket for grouping (naive Eastern datetime)
    df["local_hour"] = df["timestamp"].dt.floor("h")

    # Fill the rare GPU power nulls (~1 481 per file on edge nodes) with
    # the per-node forward/backward fill before summing.
    for col in GPU_POWER_COLS:
        df[col] = (
            df.groupby("hostname")[col]
            .transform(lambda s: s.ffill().bfill())
        )

    df["total_gpu_power_W"]  = df[GPU_POWER_COLS].sum(axis=1)

    # Sum PSU input power across both power supply units.
    # Data inspection found one file (20200120) has PSU readings as low as
    # -1,102.5W on specific nodes — a confirmed sensor fault. A PSU unit
    # draws power from the grid and can never push back into it, so any
    # negative reading is physically impossible. We clip to 0 before summing.
    df["total_node_power_W"] = (
        df[PSU_POWER_COLS].clip(lower=0).sum(axis=1)
    )

    return df[["local_hour", "hostname", "total_gpu_power_W", "total_node_power_W"]]


def _aggregate_to_hourly(
    df: pd.DataFrame,
    date_str: str,
    gpu_threshold: float,
) -> pd.DataFrame:
    """
    Two-stage aggregation:
      minute → per-node per-hour mean
      per-node per-hour → cluster-level totals
    """
    # Stage 1: per-node per-hour averages (reduces 6.8 M rows → ~111 K)
    node_hr = (
        df.groupby(["local_hour", "hostname"])
        .agg(
            mean_gpu_W  = ("total_gpu_power_W",  "mean"),
            mean_node_W = ("total_node_power_W", "mean"),
        )
        .reset_index()
    )

    node_hr["is_active"]    = node_hr["mean_gpu_W"] > gpu_threshold
    node_hr["active_psu_W"] = node_hr["mean_node_W"] * node_hr["is_active"]
    node_hr["idle_psu_W"]   = node_hr["mean_node_W"] * ~node_hr["is_active"]

    # Stage 2: cluster-level per-hour totals
    cluster = (
        node_hr.groupby("local_hour")
        .agg(
            total_nodes     = ("hostname",    "count"),
            active_nodes    = ("is_active",   "sum"),
            cluster_power_W = ("mean_node_W", "sum"),
            active_power_W  = ("active_psu_W","sum"),
            idle_power_W    = ("idle_psu_W",  "sum"),
            avg_gpu_power_W = ("mean_gpu_W",  "mean"),
        )
        .reset_index()
    )

    cluster["idle_nodes"]        = cluster["total_nodes"] - cluster["active_nodes"]
    cluster["utilization_rate"]  = cluster["active_nodes"] / cluster["total_nodes"]

    # kW = W / 1 000 ; kWh = kW × 1 h (one row = one hour)
    cluster["cluster_power_kW"]     = cluster["cluster_power_W"] / 1000
    cluster["active_power_kW"]      = cluster["active_power_W"]  / 1000
    cluster["idle_power_kW"]        = cluster["idle_power_W"]    / 1000
    cluster["active_energy_kWh"]    = cluster["active_power_kW"]   # × 1 h

    # Shiftable energy at three flexibility assumptions
    cluster["shiftable_energy_kWh"]     = cluster["active_energy_kWh"] * SHIFTABLE_FRACTION
    cluster["shiftable_energy_20p_kWh"] = cluster["active_energy_kWh"] * SHIFTABLE_LOW
    cluster["shiftable_energy_40p_kWh"] = cluster["active_energy_kWh"] * SHIFTABLE_HIGH

    cluster["snapshot_date"] = date_str
    cluster["hour_of_day"]   = cluster["local_hour"].dt.hour

    # Round floats for cleaner output
    float_cols = cluster.select_dtypes("float64").columns
    cluster[float_cols] = cluster[float_cols].round(3)

    return cluster.drop(columns=["cluster_power_W", "active_power_W", "idle_power_W"])


def _print_demand_summary(df: pd.DataFrame) -> None:
    logger.info("\n── Demand Summary ──────────────────────────────────────────")
    logger.info(f"  Snapshot days            : {sorted(df['snapshot_date'].unique())}")
    logger.info(f"  Total active energy      : {df['active_energy_kWh'].sum():,.0f} kWh")
    logger.info(f"  Total shiftable energy   : {df['shiftable_energy_kWh'].sum():,.0f} kWh  (30 % flex)")
    logger.info(f"  Mean cluster utilisation : {df['utilization_rate'].mean():.1%}")
    logger.info(f"  Mean active nodes/hour   : {df['active_nodes'].mean():.0f} / {TOTAL_NODES}")
    logger.info("────────────────────────────────────────────────────────────")
