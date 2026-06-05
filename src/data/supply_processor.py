"""
TVA electricity grid supply data processor.

Input  : supply_all_years.csv  (long format, 280 K rows, Jan 2019 – Dec 2022)
Output : supply_engineered.csv (wide format, one row per hour, with carbon
         intensity, low-carbon share, and time features)

Processing steps
────────────────
1. Parse the period column ("2019-01-01T00") as Eastern Prevailing Time.
2. Clean: clip negative generation values (solar measurement artefacts),
   forward/backward-fill the ~1 160 missing value-cells per fuel type.
3. Pivot from long (one row per fuel type per hour) → wide (one row per hour).
4. Compute carbon intensity (gCO₂ / kWh) as the generation-weighted average
   of IPCC AR5 lifecycle emission factors.
5. Compute low-carbon share (Nuclear + Hydro + Solar + Wind / total).
6. Add calendar time features used by the forecasting models.

Carbon intensity formula
────────────────────────
    CI = Σ (generation_fuel_MWh × EF_fuel_gCO2_per_kWh) / total_generation_MWh

Since generation is in MWh and EF is in gCO₂/kWh, the MWh units cancel and
the result is already in gCO₂/kWh (the MWh → kWh factor of 1 000 applies
to both numerator and denominator and cancels out).
"""

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import (
    SUPPLY_CSV_CANDIDATES,
    EMISSION_FACTORS,
    CLEAN_FUELS,
    FOSSIL_FUELS,
    ALL_FUELS,
    SUPPLY_OUTPUT,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_SEASON_MAP = {
    12: "Winter", 1: "Winter",  2: "Winter",
     3: "Spring", 4: "Spring",  5: "Spring",
     6: "Summer", 7: "Summer",  8: "Summer",
     9: "Autumn", 10: "Autumn", 11: "Autumn",
}


# ── Public API ────────────────────────────────────────────────────────────────

def process_supply(
    csv_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Process the raw TVA supply CSV into an hourly carbon-intensity DataFrame.

    Parameters
    ----------
    csv_path : Path, optional
        Override the default search path list in settings.
    output_path : Path, optional
        Where to save the output CSV.  Uses settings.SUPPLY_OUTPUT when None.

    Returns
    -------
    pd.DataFrame
        One row per hour (Eastern time), 2019-01-01 00:00 → 2022-12-31 23:00.
    """
    if csv_path is None:
        csv_path = _find_supply_csv()
    if output_path is None:
        output_path = SUPPLY_OUTPUT

    logger.info(f"Loading supply data from {csv_path}")
    raw = pd.read_csv(csv_path)
    logger.info(f"  Raw shape: {raw.shape[0]:,} rows × {raw.shape[1]} cols")

    wide = _clean_and_pivot(raw)
    wide = _compute_carbon_intensity(wide)
    wide = _add_time_features(wide)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wide.to_csv(output_path, index=False)

    logger.info(f"Saved → {output_path}  ({len(wide):,} rows)")
    _print_supply_summary(wide)

    return wide


# ── Private helpers ───────────────────────────────────────────────────────────

def _find_supply_csv() -> Path:
    """Return the first candidate supply CSV that actually exists."""
    for candidate in SUPPLY_CSV_CANDIDATES:
        if Path(candidate).exists():
            return Path(candidate)
    raise FileNotFoundError(
        "supply_all_years.csv not found in any of:\n"
        + "\n".join(f"  {p}" for p in SUPPLY_CSV_CANDIDATES)
        + "\nRun notebooks/01_data_acquisition.ipynb to fetch it from the EIA API."
    )


def _clean_and_pivot(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the long-format supply DataFrame and pivot to wide (one row per hour).
    """
    # Parse Eastern Prevailing Time (naive datetime — no DST conversion needed
    # because we match against demand data on the same naive Eastern index).
    df["datetime"] = pd.to_datetime(df["period"], format="%Y-%m-%dT%H")

    # Clip negative values (solar can report −2 MWh due to net-metering artefacts)
    df["value"] = df["value"].clip(lower=0)

    # Fill per-fuel-type gaps with forward then backward fill
    df = df.sort_values(["fueltype", "datetime"])
    df["value"] = (
        df.groupby("fueltype")["value"]
        .transform(lambda s: s.ffill().bfill())
    )

    logger.info(f"  Null values after fill: {df['value'].isna().sum()}")

    # Pivot: rows = hours, columns = fuel types
    wide = df.pivot_table(
        index="datetime",
        columns="fueltype",
        values="value",
        aggfunc="first",
    ).reset_index()

    wide.columns.name = None

    # Ensure all expected fuel columns exist (safeguard against API gaps)
    for fuel in ALL_FUELS:
        if fuel not in wide.columns:
            logger.warning(f"Fuel type '{fuel}' missing from data — filled with 0")
            wide[fuel] = 0.0

    # After pivoting, 3 DST-transition hours have nulls in OIL, SUN, WND
    # because the EIA did not report those fuels for those specific timestamps.
    # All three are near-zero contributors (OIL ≈ 0%, WND ≈ 0%, SUN ≈ 0% at 06:00).
    # Filling with 0 is the correct and conservative treatment.
    remaining_nulls = wide[ALL_FUELS].isnull().sum().sum()
    if remaining_nulls > 0:
        logger.warning(
            f"  {remaining_nulls} null values remain after pivot "
            f"(DST transition gaps) — filled with 0"
        )
        wide[ALL_FUELS] = wide[ALL_FUELS].fillna(0.0)

    return wide


def _compute_carbon_intensity(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add carbon intensity and generation-mix columns to the wide DataFrame.
    """
    # Total generation (sum across all fuel types)
    df["total_generation_MWh"] = df[ALL_FUELS].sum(axis=1)

    # Weighted-average emission factor = carbon intensity in gCO₂/kWh
    weighted_emissions = sum(df[fuel] * ef for fuel, ef in EMISSION_FACTORS.items())
    df["carbon_intensity_gCO2_per_kWh"] = (
        weighted_emissions / df["total_generation_MWh"]
    ).round(2)

    # Generation-mix shares
    df["low_carbon_MWh"]  = df[CLEAN_FUELS].sum(axis=1)
    df["fossil_MWh"]      = df[FOSSIL_FUELS].sum(axis=1)
    df["low_carbon_share"]= (df["low_carbon_MWh"] / df["total_generation_MWh"]).round(4)
    df["fossil_share"]    = (df["fossil_MWh"]      / df["total_generation_MWh"]).round(4)

    return df


def _add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add calendar features used by forecasting models and the dashboard.
    """
    dt = df["datetime"]

    df["year"]          = dt.dt.year
    df["month"]         = dt.dt.month
    df["day"]           = dt.dt.day
    df["hour_of_day"]   = dt.dt.hour
    df["day_of_week"]   = dt.dt.dayofweek   # 0 = Monday
    df["is_weekend"]    = (dt.dt.dayofweek >= 5).astype(int)
    df["season"]        = dt.dt.month.map(_SEASON_MAP)

    # Rolling 24-h and 7-day averages of carbon intensity (useful as model features)
    df = df.sort_values("datetime").reset_index(drop=True)
    df["ci_rolling_24h"] = (
        df["carbon_intensity_gCO2_per_kWh"].rolling(24,  min_periods=1).mean().round(2)
    )
    df["ci_rolling_7d"]  = (
        df["carbon_intensity_gCO2_per_kWh"].rolling(168, min_periods=1).mean().round(2)
    )

    # Daily min / max CI (used later by the optimizer for "best window" lookup)
    df["date_key"] = dt.dt.date
    day_stats = (
        df.groupby("date_key")["carbon_intensity_gCO2_per_kWh"]
        .agg(day_min_ci="min", day_max_ci="max")
        .reset_index()
    )
    df = df.merge(day_stats, on="date_key", how="left")

    return df


def _print_supply_summary(df: pd.DataFrame) -> None:
    logger.info("\n── Supply Summary ──────────────────────────────────────────")
    logger.info(f"  Date range   : {df['datetime'].min()}  →  {df['datetime'].max()}")
    logger.info(f"  Total rows   : {len(df):,}")
    logger.info(f"  Mean CI      : {df['carbon_intensity_gCO2_per_kWh'].mean():.1f} gCO₂/kWh")
    logger.info(f"  CI range     : {df['carbon_intensity_gCO2_per_kWh'].min():.1f}  –  "
                f"{df['carbon_intensity_gCO2_per_kWh'].max():.1f} gCO₂/kWh")
    logger.info(f"  Avg low-carbon share : {df['low_carbon_share'].mean():.1%}")
    logger.info("────────────────────────────────────────────────────────────")
