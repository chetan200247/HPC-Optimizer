"""
Shared evaluation utilities for forecasting models.

Provides:
  • time_split()        — chronological train/test split (no leakage)
  • compute_metrics()   — MAE, RMSE, MAPE for any prediction
  • naive_forecast()    — "same hour 24h ago" baseline
  • seasonal_naive()    — "same hour 168h (1 week) ago" baseline

Every model in Phase 3 is evaluated with the same functions so the
comparison table is strictly like-for-like.
"""

from typing import Tuple, Dict

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Chronological cut point. Everything before is training, on/after is test.
TEST_START = "2022-09-01"


# ── Train/test split ──────────────────────────────────────────────────────────

def time_split(
    df: pd.DataFrame,
    datetime_col: str = "datetime",
    test_start: str = TEST_START,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split a time-indexed DataFrame chronologically.

    Rows with datetime < test_start go to train; the rest to test.
    This preserves temporal order — the model never sees future data
    during training.

    Returns
    -------
    (train_df, test_df)
    """
    df = df.sort_values(datetime_col).reset_index(drop=True)
    cut = pd.Timestamp(test_start)

    train = df[df[datetime_col] < cut].copy()
    test  = df[df[datetime_col] >= cut].copy()

    logger.info(
        f"Time split @ {test_start}:  "
        f"train={len(train):,} rows ({train[datetime_col].min().date()} → "
        f"{train[datetime_col].max().date()})  |  "
        f"test={len(test):,} rows ({test[datetime_col].min().date()} → "
        f"{test[datetime_col].max().date()})"
    )
    return train, test


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_metrics(
    actual: np.ndarray,
    predicted: np.ndarray,
    label: str = "",
) -> Dict[str, float]:
    """
    Compute MAE, RMSE and MAPE between actual and predicted values.

    NaNs in either array are dropped pairwise before computing.

    Returns
    -------
    dict with keys: model, MAE, RMSE, MAPE, n
    """
    actual    = np.asarray(actual,    dtype=float)
    predicted = np.asarray(predicted, dtype=float)

    # Drop any positions where either value is NaN
    mask = ~(np.isnan(actual) | np.isnan(predicted))
    actual, predicted = actual[mask], predicted[mask]

    errors = actual - predicted
    mae  = np.mean(np.abs(errors))
    rmse = np.sqrt(np.mean(errors ** 2))

    # MAPE — guard against division by zero (CI is never 0 in practice, but
    # we mask any zeros to be safe).
    nonzero = actual != 0
    mape = np.mean(np.abs(errors[nonzero] / actual[nonzero])) * 100

    return {
        "model": label,
        "MAE":   round(float(mae),  3),
        "RMSE":  round(float(rmse), 3),
        "MAPE":  round(float(mape), 3),
        "n":     int(len(actual)),
    }


# ── Baselines ─────────────────────────────────────────────────────────────────

def naive_forecast(series: pd.Series, season: int = 24) -> pd.Series:
    """
    Seasonal-naive forecast: predict each value as the value `season` hours ago.

    season=24  → "same hour yesterday"  (default, daily seasonality)
    season=168 → "same hour last week"  (weekly seasonality)

    This is the benchmark every trained model must beat to justify its
    complexity.
    """
    return series.shift(season)


def seasonal_naive(series: pd.Series) -> pd.Series:
    """Weekly seasonal-naive: same hour one week (168h) ago."""
    return series.shift(168)


# ── Rolling-origin 48-hour-ahead evaluation ───────────────────────────────────

def rolling_origin_eval(
    model,
    full_df: pd.DataFrame,
    test_start: str = TEST_START,
    horizon: int = 48,
    step: int = 24,
    datetime_col: str = "datetime",
    target_col: str = "carbon_intensity_gCO2_per_kWh",
) -> pd.DataFrame:
    """
    Evaluate a fitted model with rolling-origin multi-step forecasts.

    Starting at the first test timestamp, the model forecasts `horizon` hours
    ahead from each origin; origins advance by `step` hours. All (origin,
    horizon, actual, predicted) tuples are collected into one long DataFrame.

    The model must already be fitted. Its `.forecast(history_df, horizon)`
    receives every row strictly before the origin (no leakage).

    Returns
    -------
    pd.DataFrame with columns:
        origin, horizon_h, datetime, actual, predicted, model
    """
    full_df = full_df.sort_values(datetime_col).reset_index(drop=True)
    cut = pd.Timestamp(test_start)

    test_idx = full_df.index[full_df[datetime_col] >= cut].tolist()
    origins  = test_idx[::step]

    records = []
    for origin_pos in origins:
        # History = everything strictly before this origin
        history_df = full_df.iloc[:origin_pos]
        if len(history_df) < horizon:
            continue

        # Actuals for the horizon window (may be shorter at the very end)
        actual_window = full_df.iloc[origin_pos:origin_pos + horizon]
        h = len(actual_window)
        if h == 0:
            continue

        preds = model.forecast(history_df, horizon=horizon)[:h]

        for k in range(h):
            records.append({
                "origin":    history_df[datetime_col].iloc[-1],
                "horizon_h": k + 1,
                "datetime":  actual_window[datetime_col].iloc[k],
                "actual":    actual_window[target_col].iloc[k],
                "predicted": preds[k],
                "model":     getattr(model, "name", model.__class__.__name__),
            })

    return pd.DataFrame(records)
