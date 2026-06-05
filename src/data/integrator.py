"""
Demand × Supply integrator.

Input  : demand_engineered.csv  (5 days × 24 hours = 120 rows)
         supply_engineered.csv  (4 years of hourly TVA grid data)
Output : integrated.csv         (120 rows with carbon metrics per hour)

What this module produces
─────────────────────────
For each observed hour on each snapshot day, we attach the matching TVA
grid carbon intensity and compute:

  baseline_carbon_gCO2
      Carbon emitted if all active energy ran at the actual grid CI.
      = active_energy_kWh × carbon_intensity_gCO2_per_kWh

  optimized_carbon_gCO2  (greedy day-ahead temporal shifting)
      Non-shiftable portion runs at actual CI.
      Shiftable portion is moved to the lowest-CI hour within the same
      calendar day (the "green window").
      = (active_energy_kWh − shiftable_energy_kWh) × CI_actual
      + shiftable_energy_kWh × day_min_CI

  carbon_saved_gCO2 = baseline − optimized  (clipped to ≥ 0)
  carbon_reduction_pct = carbon_saved / baseline × 100

These metrics are computed for all three flexibility assumptions (20 / 30 / 40 %).

Annualisation note
──────────────────
ORNL data covers 5 non-consecutive snapshot days.  To project annual savings
we multiply per-day averages by 365.  The dashboard clearly labels this as
a projection, not a measured figure.
"""

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import (
    DEMAND_OUTPUT,
    SUPPLY_OUTPUT,
    INTEGRATED_OUTPUT,
    SHIFTABLE_FRACTION,
    SHIFTABLE_LOW,
    SHIFTABLE_HIGH,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Columns to pull from supply into the integrated frame
_SUPPLY_COLS = [
    "datetime",
    "carbon_intensity_gCO2_per_kWh",
    "day_min_ci",
    "day_max_ci",
    "low_carbon_share",
    "fossil_share",
    "total_generation_MWh",
    "COL", "NG", "NUC", "OIL", "OTH", "SUN", "WAT", "WND",
    "ci_rolling_24h",
    "ci_rolling_7d",
]


# ── Public API ────────────────────────────────────────────────────────────────

def integrate(
    demand_path: Optional[Path] = None,
    supply_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Merge demand and supply data and compute per-hour carbon metrics.

    Parameters
    ----------
    demand_path : Path, optional
        Path to demand_engineered.csv.
    supply_path : Path, optional
        Path to supply_engineered.csv.
    output_path : Path, optional
        Where to save integrated.csv.

    Returns
    -------
    pd.DataFrame
        120-row DataFrame ready for analysis and dashboarding.
    """
    if demand_path is None:
        demand_path = DEMAND_OUTPUT
    if supply_path is None:
        supply_path = SUPPLY_OUTPUT
    if output_path is None:
        output_path = INTEGRATED_OUTPUT

    demand = _load_demand(demand_path)
    supply = _load_supply(supply_path)

    merged = _merge(demand, supply)
    merged = _carbon_metrics(merged)
    merged = _annualise(merged)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_path, index=False)

    logger.info(f"Saved → {output_path}  ({len(merged)} rows)")
    _print_integration_summary(merged)

    return merged


# ── Private helpers ───────────────────────────────────────────────────────────

def _load_demand(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["local_hour"])
    logger.info(f"Demand loaded: {len(df)} rows from {path.name}")
    return df


def _load_supply(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["datetime"])

    # Keep only the columns we need to avoid a bloated merged frame
    available = [c for c in _SUPPLY_COLS if c in df.columns]
    missing   = set(_SUPPLY_COLS) - set(available)
    if missing:
        logger.warning(f"Supply columns not found (skipped): {missing}")

    df = df[available].copy()
    logger.info(f"Supply loaded: {len(df):,} rows from {path.name}")
    return df


def _merge(demand: pd.DataFrame, supply: pd.DataFrame) -> pd.DataFrame:
    """
    Join on local Eastern datetime hour.

    demand.local_hour  — Eastern naive datetime, floored to the hour
    supply.datetime    — Eastern naive datetime (parsed from EIA "period")
    Both are in Eastern Prevailing Time with no timezone information attached,
    so a direct equality join is correct.
    """
    merged = demand.merge(
        supply,
        left_on="local_hour",
        right_on="datetime",
        how="left",
    )

    n_missing = merged["carbon_intensity_gCO2_per_kWh"].isna().sum()
    if n_missing > 0:
        logger.warning(
            f"{n_missing} demand rows could not be matched to supply data. "
            "Check that supply_all_years.csv covers the ORNL snapshot dates."
        )

    return merged


def _carbon_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute baseline and optimised carbon emissions per hour.
    """
    ci       = df["carbon_intensity_gCO2_per_kWh"]
    min_ci   = df["day_min_ci"]

    # ── 30 % flexibility (central estimate) ──────────────────────────────────
    active   = df["active_energy_kWh"]
    shift_30 = df["shiftable_energy_kWh"]       # 30 %

    df["baseline_carbon_gCO2"]   = (active * ci).round(2)
    df["optimized_carbon_gCO2"]  = (
        (active - shift_30) * ci + shift_30 * min_ci
    ).round(2)
    df["carbon_saved_gCO2"]      = (
        df["baseline_carbon_gCO2"] - df["optimized_carbon_gCO2"]
    ).clip(lower=0).round(2)
    df["carbon_reduction_pct"]   = (
        df["carbon_saved_gCO2"]
        / df["baseline_carbon_gCO2"].replace(0, np.nan)
        * 100
    ).fillna(0).round(2)

    # Convenience: kg columns (1 000 g = 1 kg)
    df["baseline_carbon_kg"]  = (df["baseline_carbon_gCO2"]  / 1000).round(3)
    df["optimized_carbon_kg"] = (df["optimized_carbon_gCO2"] / 1000).round(3)
    df["carbon_saved_kg"]     = (df["carbon_saved_gCO2"]     / 1000).round(3)

    # ── Sensitivity: 20 % flexibility ────────────────────────────────────────
    shift_20 = df["shiftable_energy_20p_kWh"]
    df["optimized_carbon_20p_gCO2"] = (
        (active - shift_20) * ci + shift_20 * min_ci
    ).round(2)
    df["carbon_saved_20p_gCO2"] = (
        df["baseline_carbon_gCO2"] - df["optimized_carbon_20p_gCO2"]
    ).clip(lower=0).round(2)

    # ── Sensitivity: 40 % flexibility ────────────────────────────────────────
    shift_40 = df["shiftable_energy_40p_kWh"]
    df["optimized_carbon_40p_gCO2"] = (
        (active - shift_40) * ci + shift_40 * min_ci
    ).round(2)
    df["carbon_saved_40p_gCO2"] = (
        df["baseline_carbon_gCO2"] - df["optimized_carbon_40p_gCO2"]
    ).clip(lower=0).round(2)

    # Flag hours that fall in a "green window" (CI below the day's median)
    day_median_ci = (
        df.groupby("snapshot_date")["carbon_intensity_gCO2_per_kWh"]
        .transform("median")
    )
    df["is_green_hour"] = (ci <= day_median_ci).astype(int)

    return df


def _annualise(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add projected annual savings columns by extrapolating from the 5 observed days.

    Method: average daily saving × 365.  Clearly labelled as a projection
    so it is not confused with a measured annual figure.
    """
    # Mean carbon saved per day (gCO₂), then × 365 days
    day_saved = df.groupby("snapshot_date")["carbon_saved_gCO2"].sum()
    avg_daily_saved_gCO2 = day_saved.mean()

    df["projected_annual_saving_tCO2"] = round(
        avg_daily_saved_gCO2 * 365 / 1e6, 2   # g → tonnes
    )

    # Same for sensitivity bounds
    for pct in ["20p", "40p"]:
        col = f"carbon_saved_{pct}_gCO2"
        avg = df.groupby("snapshot_date")[col].sum().mean()
        df[f"projected_annual_saving_{pct}_tCO2"] = round(avg * 365 / 1e6, 2)

    return df


def _print_integration_summary(df: pd.DataFrame) -> None:
    tot_base  = df["baseline_carbon_kg"].sum()
    tot_opt   = df["optimized_carbon_kg"].sum()
    tot_saved = df["carbon_saved_kg"].sum()
    reduction = tot_saved / tot_base * 100 if tot_base > 0 else 0
    annual_t  = df["projected_annual_saving_tCO2"].iloc[0]

    logger.info("\n── Integration Summary ─────────────────────────────────────")
    logger.info(f"  Observed days             : {df['snapshot_date'].nunique()}")
    logger.info(f"  Total baseline carbon     : {tot_base:,.1f} kg CO₂  (5 days)")
    logger.info(f"  Total optimised carbon    : {tot_opt:,.1f} kg CO₂  (5 days)")
    logger.info(f"  Total carbon saved        : {tot_saved:,.1f} kg CO₂  → {reduction:.2f} % reduction")
    logger.info(f"  Projected annual saving   : {annual_t:.1f} tCO₂  (extrapolated, 30 % flex)")
    logger.info(f"  Unmatched demand rows     : {df['carbon_intensity_gCO2_per_kWh'].isna().sum()}")
    logger.info("────────────────────────────────────────────────────────────")
