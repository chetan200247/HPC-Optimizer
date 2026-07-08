"""
Precompute monthly fuel-mix shares for the CSRD "TVA Grid" trend chart.

Deliberately a separate, narrow script rather than an addition to
build_dashboard_data.py: that script's KPI block contains stale placeholder
values that do not match the currently-deployed app/data/kpis.json, and
re-running it would regress the dashboard's real numbers. This script reads
the full supply dataset and writes exactly one new file, touching nothing
else in app/data/.

Usage (from project root):
    python scripts/build_fuel_mix_monthly.py
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
SUPPLY = ROOT / "data" / "processed" / "supply_engineered.csv"
OUT = ROOT / "app" / "data" / "fuel_mix_monthly.csv"

FUEL_NAMES = {"NUC": "Nuclear", "NG": "Natural Gas", "COL": "Coal", "WAT": "Hydro",
              "SUN": "Solar", "WND": "Wind", "OIL": "Petroleum", "OTH": "Other"}
FUELS = list(FUEL_NAMES)


def main():
    supply = pd.read_csv(SUPPLY, parse_dates=["datetime"])
    supply["ym"] = supply["datetime"].dt.to_period("M").astype(str)

    monthly_gen = supply.groupby("ym")[FUELS].sum()
    monthly_share = monthly_gen.div(monthly_gen.sum(axis=1), axis=0) * 100
    monthly_share = monthly_share.rename(columns=FUEL_NAMES).reset_index()

    monthly_share.to_csv(OUT, index=False)
    print(f"Written -> {OUT}  ({OUT.stat().st_size // 1024 or 1}K, {len(monthly_share)} months)")
    print(monthly_share.head(3))


if __name__ == "__main__":
    main()
