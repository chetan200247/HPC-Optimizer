"""
Carbon intensity forecasting models.

Four models plus a naive baseline, each exposing a consistent interface for
rolling-origin 48-hour-ahead evaluation:

    model.fit(train_df)
    model.forecast(history_series, horizon=48)  ->  np.ndarray of length `horizon`

Models
──────
  • BaselineForecaster — seasonal naive (same hour 24h ago)
  • SarimaForecaster   — SARIMA(2,0,1)(1,1,1,24) on a recent window
  • ProphetForecaster  — Meta Prophet with daily/weekly/yearly seasonality
  • XGBoostForecaster  — gradient-boosted trees on engineered features (recursive)
  • LSTMForecaster     — stacked LSTM on scaled CI sequences (recursive)

Target: carbon_intensity_gCO2_per_kWh
"""

import warnings
from typing import Optional

import numpy as np
import pandas as pd

from src.models.features import LAG_HOURS, get_feature_columns
from src.utils.logger import get_logger

warnings.filterwarnings("ignore")
logger = get_logger(__name__)

TARGET = "carbon_intensity_gCO2_per_kWh"


# ══════════════════════════════════════════════════════════════════════════════
#  Baseline — seasonal naive
# ══════════════════════════════════════════════════════════════════════════════

class BaselineForecaster:
    """Seasonal-naive: forecast every hour as the value `season` hours earlier."""

    name = "Naive (24h)"

    def __init__(self, season: int = 24):
        self.season = season

    def fit(self, train_df: pd.DataFrame) -> "BaselineForecaster":
        return self  # nothing to learn

    def forecast(self, history_df: pd.DataFrame, horizon: int = 48) -> np.ndarray:
        """
        Predict the next `horizon` hours as the values `season` hours before
        each forecast step. For horizon ≤ season, this simply repeats the last
        `season` observed values.
        """
        last = history_df[TARGET].values[-self.season:]
        # Tile the last seasonal cycle out to the horizon length
        reps = int(np.ceil(horizon / self.season))
        return np.tile(last, reps)[:horizon]


# ══════════════════════════════════════════════════════════════════════════════
#  SARIMA
# ══════════════════════════════════════════════════════════════════════════════

class SarimaForecaster:
    """
    SARIMA with daily (24h) seasonality.

    Fitting full statespace SARIMA on 30k+ hourly points is prohibitively slow,
    so we fit on the most recent `train_window_days` of history — sufficient to
    capture the daily seasonal structure — and then roll forward cheaply using
    `.append(refit=False)` during evaluation.
    """

    name = "SARIMA"

    def __init__(self, order=(2, 0, 1), seasonal_order=(1, 1, 1, 24),
                 train_window_days: int = 90):
        self.order = order
        self.seasonal_order = seasonal_order
        self.train_window_hours = train_window_days * 24
        self._fitted = None

    def fit(self, train_df: pd.DataFrame) -> "SarimaForecaster":
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        series = (train_df.set_index("datetime")[TARGET]
                  .asfreq("h").ffill())
        recent = series.iloc[-self.train_window_hours:]

        logger.info(f"  SARIMA fitting on last {len(recent)} hours …")
        model = SARIMAX(recent, order=self.order,
                        seasonal_order=self.seasonal_order,
                        enforce_stationarity=False,
                        enforce_invertibility=False)
        self._fitted = model.fit(disp=False, maxiter=50)
        self._train_end = recent.index[-1]
        return self

    def forecast(self, history_df: pd.DataFrame, horizon: int = 48) -> np.ndarray:
        """
        Forecast `horizon` hours beyond the end of the history.

        We update the fitted model's state with any observations that occurred
        after training (via append, refit=False) so the forecast is anchored to
        the most recent data without an expensive refit.
        """
        hist = history_df.set_index("datetime")[TARGET].asfreq("h").ffill()
        new_obs = hist[hist.index > self._train_end]

        if len(new_obs) > 0:
            fitted = self._fitted.append(new_obs, refit=False)
        else:
            fitted = self._fitted

        return np.asarray(fitted.forecast(horizon))


# ══════════════════════════════════════════════════════════════════════════════
#  Prophet
# ══════════════════════════════════════════════════════════════════════════════

class ProphetForecaster:
    """
    Meta Prophet with daily and weekly seasonality, refit on a trailing window.

    Prophet is non-autoregressive: a single global fit ignores recent
    observations, so its forecast drifts badly as the origin moves away from
    the training cut-off. The standard remedy for rolling forecasts is to refit
    on a trailing window at each origin, keeping the model anchored to recent
    grid behaviour. We use a 180-day window, disable the unreliable yearly
    term (only ~4 cycles available) and tighten the trend to prevent runaway
    extrapolation. Native uncertainty intervals feed the dashboard bands.
    """

    name = "Prophet"

    def __init__(self, interval_width: float = 0.80,
                 window_days: int = 180, changepoint_prior_scale: float = 0.01):
        self.interval_width = interval_width
        self.window_hours = window_days * 24
        self.changepoint_prior_scale = changepoint_prior_scale
        self._model = None  # last fitted model (for dashboard bands)

    def _fit_window(self, history_df: pd.DataFrame):
        from prophet import Prophet

        window = history_df.tail(self.window_hours)
        pdf = window[["datetime", TARGET]].rename(
            columns={"datetime": "ds", TARGET: "y"})

        model = Prophet(
            interval_width=self.interval_width,
            daily_seasonality=True,
            weekly_seasonality=True,
            yearly_seasonality=False,
            changepoint_prior_scale=self.changepoint_prior_scale,
        )
        model.fit(pdf)
        return model

    def fit(self, train_df: pd.DataFrame) -> "ProphetForecaster":
        # Fit once on the trailing window for demos / dashboard bands.
        logger.info(f"  Prophet fitting on trailing {self.window_hours//24}-day window …")
        self._model = self._fit_window(train_df)
        return self

    def forecast(self, history_df: pd.DataFrame, horizon: int = 48) -> np.ndarray:
        """Refit on the trailing window of `history_df`, then predict `horizon` hours."""
        self._model = self._fit_window(history_df)
        start = history_df["datetime"].iloc[-1] + pd.Timedelta(hours=1)
        future = pd.DataFrame({"ds": pd.date_range(start, periods=horizon, freq="h")})
        out = self._model.predict(future)
        return out["yhat"].values

    def forecast_with_bands(self, start_ts, horizon: int = 48) -> pd.DataFrame:
        """Return yhat, lower and upper bounds — used for the dashboard."""
        future = pd.DataFrame({"ds": pd.date_range(start_ts, periods=horizon, freq="h")})
        out = self._model.predict(future)
        return out[["ds", "yhat", "yhat_lower", "yhat_upper"]]


# ══════════════════════════════════════════════════════════════════════════════
#  XGBoost
# ══════════════════════════════════════════════════════════════════════════════

class XGBoostForecaster:
    """
    Gradient-boosted trees on engineered features, forecasting recursively.

    During the 48-hour forecast, the short autoregressive lags (1–48h) are
    filled with the model's own previous predictions as the horizon advances.
    The weekly lag (168h) is always observed (168 > 48). Fuel-mix lag features
    are held at their last observed value across the horizon (we forecast CI,
    not the fuel mix).
    """

    name = "XGBoost"

    def __init__(self, n_estimators=400, max_depth=6, learning_rate=0.05):
        self.params = dict(n_estimators=n_estimators, max_depth=max_depth,
                           learning_rate=learning_rate, subsample=0.8,
                           colsample_bytree=0.8, random_state=42, n_jobs=-1)
        self._model = None
        self._feat_cols = None

    def fit(self, train_df: pd.DataFrame) -> "XGBoostForecaster":
        from xgboost import XGBRegressor

        self._feat_cols = get_feature_columns(train_df)
        data = train_df.dropna(subset=self._feat_cols + [TARGET])

        X = data[self._feat_cols]
        y = data[TARGET]

        logger.info(f"  XGBoost fitting on {len(X):,} rows × {len(self._feat_cols)} features …")
        self._model = XGBRegressor(**self.params)
        self._model.fit(X, y)
        return self

    def forecast(self, history_df: pd.DataFrame, horizon: int = 48) -> np.ndarray:
        """
        Recursive multi-step forecast.

        Parameters
        ----------
        history_df : pd.DataFrame
            All rows up to and including the forecast origin, indexed by
            position, containing at least the target and the columns needed
            to rebuild features (hour_of_day, day_of_week, month, fuel lags …).
        """
        # Working series of CI values: actual history, extended with predictions
        ci = list(history_df[TARGET].values)
        last_row = history_df.iloc[-1]
        origin_ts = history_df["datetime"].iloc[-1]

        # Persist the most recent fuel-mix lag features across the horizon
        fuel_feats = {c: last_row[c] for c in
                      ["nuc_share_lag_24h", "col_share_lag_24h", "ng_share_lag_24h"]
                      if c in history_df.columns}

        preds = []
        for h in range(1, horizon + 1):
            ts = origin_ts + pd.Timedelta(hours=h)
            feat = {}

            # Autoregressive lags — use actual history or prior predictions
            for lag in LAG_HOURS:
                idx = len(ci) - lag
                feat[f"ci_lag_{lag}h"] = ci[idx] if idx >= 0 else ci[0]

            # Rolling stats from the working series (past values only)
            recent = np.array(ci[-168:])
            feat["ci_roll_mean_6h"]  = np.mean(recent[-6:])
            feat["ci_roll_std_6h"]   = np.std(recent[-6:], ddof=1) if len(recent) >= 2 else 0
            feat["ci_roll_std_24h"]  = np.std(recent[-24:], ddof=1) if len(recent) >= 2 else 0
            feat["ci_roll_std_168h"] = np.std(recent, ddof=1) if len(recent) >= 2 else 0
            feat["ci_rolling_24h"]   = np.mean(recent[-24:])
            feat["ci_rolling_7d"]    = np.mean(recent)

            # Deterministic calendar features for the future timestamp
            feat["hour_of_day"] = ts.hour
            feat["day_of_week"] = ts.dayofweek
            feat["month"]       = ts.month
            feat["is_weekend"]  = int(ts.dayofweek >= 5)
            feat["hour_sin"]  = np.sin(2 * np.pi * ts.hour / 24)
            feat["hour_cos"]  = np.cos(2 * np.pi * ts.hour / 24)
            feat["dow_sin"]   = np.sin(2 * np.pi * ts.dayofweek / 7)
            feat["dow_cos"]   = np.cos(2 * np.pi * ts.dayofweek / 7)
            feat["month_sin"] = np.sin(2 * np.pi * ts.month / 12)
            feat["month_cos"] = np.cos(2 * np.pi * ts.month / 12)

            # Persisted fuel-mix lags
            feat.update(fuel_feats)

            x = pd.DataFrame([feat])[self._feat_cols]
            yhat = float(self._model.predict(x)[0])
            preds.append(yhat)
            ci.append(yhat)  # feed prediction back for the next step

        return np.array(preds)

    def feature_importance(self) -> pd.Series:
        return pd.Series(self._model.feature_importances_,
                         index=self._feat_cols).sort_values(ascending=False)


# ══════════════════════════════════════════════════════════════════════════════
#  LSTM
# ══════════════════════════════════════════════════════════════════════════════

class LSTMForecaster:
    """
    Stacked LSTM on scaled CI sequences, forecasting recursively.

    A look-back window of `seq_len` hours is fed to the network to predict the
    next hour; predictions are fed back to roll forward to 48 hours. Inputs are
    Min-Max scaled to [0, 1] using statistics from the training set only.
    """

    name = "LSTM"

    def __init__(self, seq_len: int = 48, epochs: int = 15, batch_size: int = 256,
                 train_stride: int = 4):
        # seq_len=48 (2 days) keeps the unroll short enough to train on CPU while
        # still spanning multiple daily cycles. train_stride subsamples the
        # heavily-overlapping training sequences to cut training time. A compact
        # 32+16 network and EarlyStopping keep CPU training to a few minutes.
        self.seq_len = seq_len
        self.epochs = epochs
        self.batch_size = batch_size
        self.train_stride = train_stride
        self._model = None
        self._predict_fn = None   # compiled single-step inference function
        self._vmin = None
        self._vmax = None

    def _scale(self, x):
        return (x - self._vmin) / (self._vmax - self._vmin)

    def _unscale(self, x):
        return x * (self._vmax - self._vmin) + self._vmin

    def fit(self, train_df: pd.DataFrame) -> "LSTMForecaster":
        import tensorflow as tf
        from tensorflow.keras.models import Sequential
        from tensorflow.keras.layers import LSTM, Dense, Dropout, Input
        from tensorflow.keras.callbacks import EarlyStopping

        tf.random.set_seed(42)
        np.random.seed(42)

        series = train_df[TARGET].values.astype("float32")
        self._vmin, self._vmax = float(series.min()), float(series.max())
        scaled = self._scale(series)

        # Build supervised sequences (seq_len inputs -> 1 output), subsampled by
        # train_stride to reduce the count of heavily-overlapping windows.
        idx = range(0, len(scaled) - self.seq_len, self.train_stride)
        X = np.array([scaled[i:i + self.seq_len] for i in idx], dtype="float32")
        y = np.array([scaled[i + self.seq_len]   for i in idx], dtype="float32")
        X = X.reshape(-1, self.seq_len, 1)

        logger.info(f"  LSTM fitting on {len(X):,} sequences (seq_len={self.seq_len}, stride={self.train_stride}) …")
        model = Sequential([
            Input(shape=(self.seq_len, 1)),
            LSTM(32, return_sequences=True),
            Dropout(0.2),
            LSTM(16),
            Dropout(0.2),
            Dense(1),
        ])
        model.compile(optimizer="adam", loss="mse")
        early = EarlyStopping(monitor="val_loss", patience=3, restore_best_weights=True)
        model.fit(X, y, epochs=self.epochs, batch_size=self.batch_size,
                  verbose=0, validation_split=0.1, callbacks=[early])
        self._model = model

        # Compile a fast single-step inference function. Calling the model as a
        # tf.function avoids the heavy per-call overhead of model.predict(),
        # which matters because the recursive forecast makes thousands of
        # single-sample predictions (122 origins × 48 steps).
        self._predict_fn = tf.function(
            lambda x: model(x, training=False),
            input_signature=[tf.TensorSpec(shape=(1, self.seq_len, 1), dtype=tf.float32)],
        )
        return self

    def forecast(self, history_df: pd.DataFrame, horizon: int = 48) -> np.ndarray:
        """Recursive 48-hour forecast from the last `seq_len` observed hours."""
        import numpy as _np
        window = list(self._scale(history_df[TARGET].values[-self.seq_len:].astype(float)))
        preds = []
        for _ in range(horizon):
            x = _np.array(window[-self.seq_len:], dtype=_np.float32).reshape(1, self.seq_len, 1)
            yhat = float(self._predict_fn(x).numpy()[0, 0])
            preds.append(yhat)
            window.append(yhat)
        return self._unscale(_np.array(preds))
