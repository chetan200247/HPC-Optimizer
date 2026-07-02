"""
Electricity price model — representative Time-of-Use (ToU) tariff.

TVA is a vertically integrated utility, not a wholesale market, so there is no
public hourly locational price. Large customers are instead billed on a
Time-of-Use tariff: cheap overnight, expensive in the afternoon/evening peak,
with a higher summer season. This module produces a representative ToU price in
US$/MWh for any hour, so the scheduler can optimise for cost alongside carbon.

The rates below are representative of US commercial/industrial ToU energy
charges and are clearly a MODEL — a real deployment would substitute the
facility's actual tariff. They are documented and centralised here so they can
be audited and changed in one place.
"""

import numpy as np
import pandas as pd

# Representative ToU energy charges (US$/MWh).  1 US$/MWh = 0.1 cent/kWh.
# Winter (Oct–May) and Summer (Jun–Sep) differ mainly in the on-peak rate.
_RATES = {
    "winter": {"off": 25.0, "shoulder": 45.0, "peak": 75.0},
    "summer": {"off": 28.0, "shoulder": 52.0, "peak": 95.0},
}

# Hour-of-day → period.  On-peak afternoon/evening, shoulder morning/late,
# off-peak overnight.
def _period(hour: int) -> str:
    if 13 <= hour < 19:                 # 1pm–7pm afternoon/evening peak
        return "peak"
    if 6 <= hour < 13 or 19 <= hour < 22:  # morning + late-evening shoulder
        return "shoulder"
    return "off"                        # 10pm–6am overnight off-peak


def _season(month: int) -> str:
    return "summer" if 6 <= month <= 9 else "winter"


def tou_price(dt) -> float:
    """Return the representative ToU price (US$/MWh) for a single timestamp."""
    dt = pd.Timestamp(dt)
    return _RATES[_season(dt.month)][_period(dt.hour)]


def price_series(datetimes) -> np.ndarray:
    """Return an array of ToU prices (US$/MWh) for a sequence of timestamps."""
    dts = pd.to_datetime(pd.Series(datetimes))
    return np.array([_RATES[_season(d.month)][_period(d.hour)] for d in dts])
