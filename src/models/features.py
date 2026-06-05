"""
Feature engineering for carbon intensity forecasting.

Input  : data/processed/supply_engineered.csv  (35,064 hourly rows)
Output : data/processed/features_for_forecasting.csv

Target variable
───────────────
carbon_intensity_gCO2_per_kWh — the value we want to forecast 48 hours ahead.

What this module builds
───────────────────────
The tree-based model (XGBoost) and, in part, the LSTM rely on engineered
predictor variables. SARIMA and Prophet work off the raw series and do not
need these — but building one consistent feature table keeps the pipeline
clean and lets every model read from the same source.

Feature groups
──────────────
1. Lag features      — CI at t-1, t-2, t-3, t-6, t-12, t-24, t-48, t-168
2. Rolling windows   — rolling mean / std over 6h, 24h, 168h
3. Cyclical calendar — sin/cos of hour, day-of-week, month
4. Fuel-mix lags     — nuclear / coal / gas share at t-24

The first 168 rows contain NaN lag values (no history that far back); they
are retained in the file but excluded from training downstream.
"""

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config.settings import SUPPLY_OUTPUT, PROCESSED_DATA_DIR, ALL_FUELS
from src.utils.logger import get_logger

logger = get_logger(__name__)

TARGET = "carbon_intensity_gCO2_per_kWh"

# Lags (in hours) chosen to capture short-term momentum, the daily cycle (24h),
# the two-day cycle (48h) and the weekly cycle (168h).
LAG_HOURS = [1, 2, 3, 6, 12, 24, 48, 168]

FEATURES_OUTPUT = PROCESSED_DATA_DIR / "features_for_forecasting.csv"


# ── Public API ────────────────────────────────────────────────────────────────

def build_features(
    supply_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Build the full feature table for forecasting and save to CSV.

    Returns
    -------
    pd.DataFrame
        One row per hour with the target plus all engineered features.
    """
    if supply_path is None:
        supply_path = SUPPLY_OUTPUT
    if output_path is None:
        output_path = FEATURES_OUTPUT

    logger.info(f"Loading supply data from {supply_path}")
    df = pd.read_csv(supply_path, parse_dates=["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    logger.info(f"  {len(df):,} hourly rows loaded")

    df = _add_lag_features(df)
    df = _add_rolling_features(df)
    df = _add_cyclical_features(df)
    df = _add_fuel_mix_lags(df)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    n_complete = df.dropna(subset=_feature_columns(df)).shape[0]
    logger.info(f"Saved → {output_path}")
    logger.info(f"  Total rows           : {len(df):,}")
    logger.info(f"  Rows with all features: {n_complete:,}  (after dropping first 168h warm-up)")
    logger.info(f"  Feature columns      : {len(_feature_columns(df))}")

    return df


def get_feature_columns(df: pd.DataFrame) -> list:
    """Public accessor for the list of engineered feature column names."""
    return _feature_columns(df)


# ── Private helpers ───────────────────────────────────────────────────────────

def _add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add lagged values of the target.  lag_24 = the CI value 24 hours earlier
    (same hour yesterday); lag_168 = same hour one week ago.
    """
    for lag in LAG_HOURS:
        df[f"ci_lag_{lag}h"] = df[TARGET].shift(lag)
    return df


def _add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add rolling-window statistics of the target.

    We shift by 1 before rolling so each row's rolling feature uses only PAST
    values (no leakage of the current hour into its own predictor).
    The 24h and 168h rolling means already exist in the supply file; here we
    add a 6h mean and rolling standard deviations (volatility).
    """
    shifted = df[TARGET].shift(1)

    df["ci_roll_mean_6h"]  = shifted.rolling(6,   min_periods=1).mean()
    df["ci_roll_std_6h"]   = shifted.rolling(6,   min_periods=1).std()
    df["ci_roll_std_24h"]  = shifted.rolling(24,  min_periods=1).std()
    df["ci_roll_std_168h"] = shifted.rolling(168, min_periods=1).std()

    return df


def _add_cyclical_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Encode cyclical calendar variables as sin/cos pairs so the model sees
    that e.g. hour 23 and hour 0 are adjacent (one step apart on a circle),
    not 23 steps apart.
    """
    # Hour of day (period = 24)
    df["hour_sin"] = np.sin(2 * np.pi * df["hour_of_day"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour_of_day"] / 24)

    # Day of week (period = 7)
    df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)

    # Month of year (period = 12)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

    return df


def _add_fuel_mix_lags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add the generation share of the three CI-driving fuels, lagged 24 hours.

    We use the share (fuel / total generation) rather than raw MWh so the
    feature is comparable across high- and low-demand hours. Lagged 24h to
    avoid leaking same-hour generation into the forecast.
    """
    total = df[ALL_FUELS].sum(axis=1).replace(0, np.nan)

    for fuel in ["NUC", "COL", "NG"]:
        share = (df[fuel] / total).fillna(0)
        df[f"{fuel.lower()}_share_lag_24h"] = share.shift(24)

    return df


def _feature_columns(df: pd.DataFrame) -> list:
    """
    Return the list of engineered feature columns (everything the models can
    use as input — excludes the target, datetime, and raw bookkeeping columns).
    """
    lag_cols     = [f"ci_lag_{lag}h" for lag in LAG_HOURS]
    roll_cols    = ["ci_roll_mean_6h", "ci_roll_std_6h",
                    "ci_roll_std_24h", "ci_roll_std_168h",
                    "ci_rolling_24h", "ci_rolling_7d"]
    cyclical     = ["hour_sin", "hour_cos", "dow_sin", "dow_cos",
                    "month_sin", "month_cos"]
    calendar     = ["hour_of_day", "day_of_week", "month", "is_weekend"]
    fuel_lags    = ["nuc_share_lag_24h", "col_share_lag_24h", "ng_share_lag_24h"]

    all_feats = lag_cols + roll_cols + cyclical + calendar + fuel_lags
    # Only return columns that actually exist in the frame
    return [c for c in all_feats if c in df.columns]
