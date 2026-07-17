"""
Decomposed carbon-intensity forecasting: forecast each fuel source's
generation separately, then compute CI from the forecasted mix -- compared
directly against the existing aggregate-CI XGBoost forecaster.

Motivation
──────────
Carbon intensity is not a primary signal — it is a generation-weighted
average of emission factors across the fuel mix:

    CI(t) = Σ_f  generation_f(t) × EF_f  /  Σ_f  generation_f(t)

The aggregate approach (src/models/forecaster.py::XGBoostForecaster) forecasts
CI(t) directly as one series. This script instead forecasts each fuel's own
generation series (COL, NG, NUC, OIL, OTH, SUN, WAT, WND) — each with its own
lags/rolling stats — and only computes CI from the forecasted mix at the end.
This is the architecture used by CarbonCast (Maji, Suresh & Irwin, ACM
e-Energy 2022) for the same underlying problem.

To isolate the effect of decomposition itself (not confound it with a model
change), every per-fuel forecaster uses the SAME model family and
hyperparameters as the existing aggregate XGBoostForecaster, and evaluation
reuses the project's own rolling_origin_eval() with identical origins,
horizon, and TEST_START — so the two MAE/RMSE/MAPE figures are directly
comparable, not just similar in spirit.

Usage (from project root):
    python scripts/run_decomposed_forecast.py
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from config.settings import ALL_FUELS, EMISSION_FACTORS               # noqa: E402
from src.models.evaluation import TEST_START, time_split, compute_metrics  # noqa: E402

SUPPLY = ROOT / "data" / "processed" / "supply_engineered.csv"
OUT_DIR = ROOT / "data" / "processed"

LAG_HOURS = [1, 2, 3, 6, 12, 24, 48, 168]      # identical to src/models/features.py
XGB_PARAMS = dict(n_estimators=400, max_depth=6, learning_rate=0.05,
                  subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=-1)

# The original aggregate-CI XGBoost benchmark (data/processed/forecast_comparison_all.csv),
# reported here for direct side-by-side comparison without re-running it.
AGGREGATE_XGB = {"MAE": 17.953, "RMSE": 23.805, "MAPE": 6.804}


# ── Per-fuel feature engineering (mirrors src/models/features.py, parametrised) ─

def add_fuel_features(df: pd.DataFrame, fuel: str) -> pd.DataFrame:
    for lag in LAG_HOURS:
        df[f"{fuel}_lag_{lag}h"] = df[fuel].shift(lag)
    shifted = df[fuel].shift(1)
    df[f"{fuel}_roll_mean_6h"] = shifted.rolling(6, min_periods=1).mean()
    df[f"{fuel}_roll_std_6h"] = shifted.rolling(6, min_periods=1).std()
    df[f"{fuel}_roll_std_24h"] = shifted.rolling(24, min_periods=1).std()
    return df


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    df["hour_sin"] = np.sin(2 * np.pi * df["hour_of_day"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour_of_day"] / 24)
    df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    return df


def fuel_feature_cols(fuel: str) -> list:
    return ([f"{fuel}_lag_{lag}h" for lag in LAG_HOURS] +
           [f"{fuel}_roll_mean_6h", f"{fuel}_roll_std_6h", f"{fuel}_roll_std_24h"] +
           ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
            "hour_of_day", "day_of_week", "month", "is_weekend"])


# ── Per-fuel recursive forecaster (mirrors XGBoostForecaster.forecast exactly) ──

class FuelForecaster:
    def __init__(self, fuel):
        self.fuel = fuel
        self.feat_cols = None
        self.model = None

    def fit(self, train_df):
        from xgboost import XGBRegressor
        self.feat_cols = fuel_feature_cols(self.fuel)
        data = train_df.dropna(subset=self.feat_cols + [self.fuel])
        self.model = XGBRegressor(**XGB_PARAMS)
        self.model.fit(data[self.feat_cols], data[self.fuel])
        return self

    def forecast(self, history_df, horizon=48):
        series = list(history_df[self.fuel].values)
        last_row = history_df.iloc[-1]
        origin_ts = history_df["datetime"].iloc[-1]
        preds = []
        for h in range(1, horizon + 1):
            ts = origin_ts + pd.Timedelta(hours=h)
            feat = {}
            for lag in LAG_HOURS:
                idx = len(series) - lag
                feat[f"{self.fuel}_lag_{lag}h"] = series[idx] if idx >= 0 else series[0]
            recent = np.array(series[-168:])
            feat[f"{self.fuel}_roll_mean_6h"] = np.mean(recent[-6:])
            feat[f"{self.fuel}_roll_std_6h"] = np.std(recent[-6:], ddof=1) if len(recent) >= 2 else 0
            feat[f"{self.fuel}_roll_std_24h"] = np.std(recent[-24:], ddof=1) if len(recent) >= 2 else 0
            feat["hour_of_day"] = ts.hour
            feat["day_of_week"] = ts.dayofweek
            feat["month"] = ts.month
            feat["is_weekend"] = int(ts.dayofweek >= 5)
            feat["hour_sin"] = np.sin(2 * np.pi * ts.hour / 24)
            feat["hour_cos"] = np.cos(2 * np.pi * ts.hour / 24)
            feat["dow_sin"] = np.sin(2 * np.pi * ts.dayofweek / 7)
            feat["dow_cos"] = np.cos(2 * np.pi * ts.dayofweek / 7)
            feat["month_sin"] = np.sin(2 * np.pi * ts.month / 12)
            feat["month_cos"] = np.cos(2 * np.pi * ts.month / 12)
            x = pd.DataFrame([feat])[self.feat_cols].values
            yhat = max(0.0, float(self.model.predict(x)[0]))   # generation can't be negative
            preds.append(yhat)
            series.append(yhat)
        return np.array(preds)


# ── Combine forecasted fuel mix into CI ─────────────────────────────────────────

def mix_to_ci(fuel_preds: dict, horizon: int) -> np.ndarray:
    ef = np.array([EMISSION_FACTORS[f] for f in ALL_FUELS])
    gen = np.stack([fuel_preds[f] for f in ALL_FUELS], axis=1)   # (horizon, n_fuels)
    gen = np.clip(gen, 0, None)
    total = gen.sum(axis=1)
    total_safe = np.where(total > 0, total, np.nan)
    ci = (gen * ef).sum(axis=1) / total_safe
    return ci


# ── Main: fit 8 per-fuel models, run rolling-origin eval, compare to aggregate ──

def main():
    print(f"Loading {SUPPLY} …")
    df = pd.read_csv(SUPPLY, parse_dates=["datetime"]).sort_values("datetime").reset_index(drop=True)
    df = add_calendar_features(df)
    for fuel in ALL_FUELS:
        df = add_fuel_features(df, fuel)

    train_df, test_df = time_split(df, test_start=TEST_START)

    print(f"\nFitting {len(ALL_FUELS)} per-fuel XGBoost models "
         f"(same hyperparameters as the aggregate benchmark) …")
    models = {}
    for fuel in ALL_FUELS:
        models[fuel] = FuelForecaster(fuel).fit(train_df)
        print(f"  {fuel} fitted on {len(train_df):,} rows")

    # rolling-origin evaluation: same origins/horizon/step as the aggregate benchmark
    horizon, step = 48, 24
    cut = pd.Timestamp(TEST_START)
    test_idx = df.index[df["datetime"] >= cut].tolist()
    origins = test_idx[::step]
    print(f"\nRunning rolling-origin evaluation: {len(origins)} origins, "
         f"{horizon}h horizon, {step}h step …")

    ci_records = []
    fuel_records = {f: [] for f in ALL_FUELS}
    for oi, origin_pos in enumerate(origins):
        history_df = df.iloc[:origin_pos]
        if len(history_df) < horizon:
            continue
        actual_window = df.iloc[origin_pos:origin_pos + horizon]
        h = len(actual_window)
        if h == 0:
            continue

        fuel_preds = {}
        for fuel in ALL_FUELS:
            preds = models[fuel].forecast(history_df, horizon=horizon)[:h]
            fuel_preds[fuel] = preds
            for k in range(h):
                fuel_records[fuel].append({
                    "actual": actual_window[fuel].iloc[k],
                    "predicted": preds[k],
                })

        ci_pred = mix_to_ci(fuel_preds, h)
        for k in range(h):
            ci_records.append({
                "origin": history_df["datetime"].iloc[-1],
                "horizon_h": k + 1,
                "datetime": actual_window["datetime"].iloc[k],
                "actual": actual_window["carbon_intensity_gCO2_per_kWh"].iloc[k],
                "predicted": ci_pred[k],
            })
        if (oi + 1) % 20 == 0 or oi == len(origins) - 1:
            print(f"  origin {oi+1}/{len(origins)} done")

    ci_df = pd.DataFrame(ci_records)
    decomposed_metrics = compute_metrics(ci_df["actual"], ci_df["predicted"], label="Decomposed (per-fuel XGBoost)")

    print("\n" + "=" * 78)
    print("RESULT — decomposed vs aggregate CI forecast (identical evaluation protocol)")
    print("=" * 78)
    print(f"{'Model':38s} {'MAE':>8s} {'RMSE':>8s} {'MAPE':>8s}  n")
    print(f"{'Aggregate XGBoost (direct CI target)':38s} "
         f"{AGGREGATE_XGB['MAE']:8.3f} {AGGREGATE_XGB['RMSE']:8.3f} {AGGREGATE_XGB['MAPE']:8.3f}%")
    print(f"{'Decomposed (8 per-fuel XGBoost models)':38s} "
         f"{decomposed_metrics['MAE']:8.3f} {decomposed_metrics['RMSE']:8.3f} "
         f"{decomposed_metrics['MAPE']:8.3f}%  n={decomposed_metrics['n']}")
    delta_mae_pct = (decomposed_metrics["MAE"] - AGGREGATE_XGB["MAE"]) / AGGREGATE_XGB["MAE"] * 100
    verdict = "WORSE" if delta_mae_pct > 0 else "BETTER"
    print(f"\nDecomposed MAE is {delta_mae_pct:+.1f}% vs aggregate -> decomposition is {verdict} "
         f"on this grid/dataset.")

    print("\n--- per-fuel forecast accuracy (diagnostic) ---")
    print(f"{'Fuel':6s} {'MAE (MWh)':>12s} {'Mean gen (MWh)':>16s} {'MAE % of mean':>15s}")
    fuel_diag = []
    for fuel in ALL_FUELS:
        fr = pd.DataFrame(fuel_records[fuel])
        m = compute_metrics(fr["actual"], fr["predicted"], label=fuel)
        mean_gen = fr["actual"].mean()
        pct = m["MAE"] / mean_gen * 100 if mean_gen > 0 else float("nan")
        fuel_diag.append({"fuel": fuel, "MAE_MWh": m["MAE"], "mean_gen_MWh": round(mean_gen, 1),
                          "MAE_pct_of_mean": round(pct, 1), "emission_factor": EMISSION_FACTORS[fuel]})
        print(f"{fuel:6s} {m['MAE']:12.1f} {mean_gen:16.1f} {pct:14.1f}%")

    # save outputs for the report / dashboard
    ci_df.to_csv(OUT_DIR / "decomposed_ci_forecast_results.csv", index=False)
    pd.DataFrame(fuel_diag).to_csv(OUT_DIR / "decomposed_per_fuel_accuracy.csv", index=False)
    summary = pd.DataFrame([
        {"model": "Aggregate XGBoost (direct CI)", **AGGREGATE_XGB, "n": decomposed_metrics["n"]},
        {"model": "Decomposed (per-fuel XGBoost)", "MAE": decomposed_metrics["MAE"],
         "RMSE": decomposed_metrics["RMSE"], "MAPE": decomposed_metrics["MAPE"], "n": decomposed_metrics["n"]},
    ])
    summary.to_csv(OUT_DIR / "decomposed_vs_aggregate_summary.csv", index=False)
    print(f"\nSaved -> {OUT_DIR}/decomposed_ci_forecast_results.csv")
    print(f"Saved -> {OUT_DIR}/decomposed_per_fuel_accuracy.csv")
    print(f"Saved -> {OUT_DIR}/decomposed_vs_aggregate_summary.csv")


if __name__ == "__main__":
    main()
