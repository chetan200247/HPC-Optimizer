"""
Precompute the small, self-contained data files the Streamlit dashboard reads.

Reads the full processed datasets from data/processed/ and writes compact
aggregates to app/data/ so the deployed app stays tiny and dependency-light.

Usage (from project root):
    python scripts/build_dashboard_data.py
"""

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PROC = ROOT / "data" / "processed"
OUT = ROOT / "app" / "data"
OUT.mkdir(parents=True, exist_ok=True)

FUEL_NAMES = {"NUC": "Nuclear", "NG": "Natural Gas", "COL": "Coal", "WAT": "Hydro",
              "SUN": "Solar", "WND": "Wind", "OIL": "Petroleum", "OTH": "Other"}
FUELS = list(FUEL_NAMES)


def main():
    integ = pd.read_csv(PROC / "integrated.csv", parse_dates=["local_hour"])
    supply = pd.read_csv(PROC / "supply_engineered.csv", parse_dates=["datetime"])
    demand = pd.read_csv(PROC / "demand_engineered.csv")

    # 1. integrated (small) — CSRD baseline vs optimised
    integ.to_csv(OUT / "integrated.csv", index=False)

    # 2. Hourly CI profile
    (supply.groupby("hour_of_day")["carbon_intensity_gCO2_per_kWh"]
     .agg(mean="mean", p25=lambda x: x.quantile(.25), p75=lambda x: x.quantile(.75))
     .reset_index().to_csv(OUT / "ci_hourly.csv", index=False))

    # 3. Monthly CI trend
    supply["ym"] = supply["datetime"].dt.to_period("M").astype(str)
    (supply.groupby("ym")["carbon_intensity_gCO2_per_kWh"].mean()
     .reset_index().to_csv(OUT / "ci_monthly.csv", index=False))

    # 4. Fuel mix
    tot = supply[FUELS].sum().sum()
    pd.DataFrame({"fuel": [FUEL_NAMES[f] for f in FUELS],
                  "share": [supply[f].sum() / tot * 100 for f in FUELS]}
                 ).to_csv(OUT / "fuel_mix.csv", index=False)

    # 5. Representative 48h CI window for the ops view
    win = (supply[supply["datetime"] >= "2022-11-15"]
           [["datetime", "carbon_intensity_gCO2_per_kWh"]].head(48).reset_index(drop=True))
    win.columns = ["datetime", "ci"]
    win.to_csv(OUT / "forecast_window.csv", index=False)

    # 6. KPIs
    kpis = {
        "mean_ci": round(supply["carbon_intensity_gCO2_per_kWh"].mean(), 1),
        "ci_min": round(supply["carbon_intensity_gCO2_per_kWh"].min(), 1),
        "ci_max": round(supply["carbon_intensity_gCO2_per_kWh"].max(), 1),
        "low_carbon_share": round(supply["low_carbon_share"].mean() * 100, 1),
        "total_baseline_kg_5d": round(integ["baseline_carbon_kg"].sum(), 1),
        "total_saved_kg_5d": round(integ["carbon_saved_kg"].sum(), 1),
        "reduction_pct": round(integ["carbon_saved_kg"].sum() / integ["baseline_carbon_kg"].sum() * 100, 2),
        "annual_unconstrained_tco2": 293,
        "annual_ceiling_tco2": 106,
        "annual_realistic_tco2": 51,
        "total_nodes": 4626,
        "mean_utilisation_pct": round(demand["utilization_rate"].mean() * 100, 1),
    }
    json.dump(kpis, open(OUT / "kpis.json", "w"), indent=2)

    print(f"Dashboard data written to {OUT}")
    for f in sorted(OUT.iterdir()):
        print(f"  {f.stat().st_size // 1024 or 1}K  {f.name}")


if __name__ == "__main__":
    main()
