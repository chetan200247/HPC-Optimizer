"""
Precompute daily generation-by-fuel (MWh) for the CSRD energy-mix drill-down.

Stores raw generation, not pre-computed daily percentages, deliberately:
aggregating a mix chart up to a week/month/year must sum generation first
and compute shares afterwards. Averaging pre-computed daily percentages
would silently misweight days with different total generation volumes.

Narrow and separate from build_dashboard_data.py: that script has stale KPI
placeholders that don't match the deployed kpis.json, and must not be re-run.

Usage (from project root):
    python scripts/build_fuel_mix_daily.py
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
SUPPLY = ROOT / "data" / "processed" / "supply_engineered.csv"
OUT = ROOT / "app" / "data" / "fuel_mix_daily.csv"

FUELS = ["COL", "NG", "NUC", "OIL", "OTH", "SUN", "WAT", "WND"]


def main():
    supply = pd.read_csv(SUPPLY, parse_dates=["datetime"])
    supply["date"] = supply["datetime"].dt.date

    daily_gen = supply.groupby("date")[FUELS].sum().reset_index()
    daily_gen.to_csv(OUT, index=False)
    print(f"Written -> {OUT}  ({OUT.stat().st_size // 1024 or 1}K, {len(daily_gen)} days)")
    print(daily_gen.head(3))


if __name__ == "__main__":
    main()
