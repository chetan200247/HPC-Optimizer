"""
EIA API fetcher — TVA hourly electricity generation by fuel type.

What this module does
─────────────────────
Fetches hourly electricity generation data (in MWh) broken down by fuel type
for the Tennessee Valley Authority (TVA) balancing authority from the U.S.
Energy Information Administration (EIA) Open Data API v2.

Why this data is needed
───────────────────────
ORNL Summit is physically located inside the TVA service territory. Every
kilowatt-hour Summit consumes comes from the TVA grid. To calculate the carbon
intensity of Summit's electricity consumption at any given hour, we need to know
what fuel mix TVA was using to generate power at that hour.

Why the EIA API specifically
─────────────────────────────
TVA is required to report hourly generation by fuel type to the EIA under FERC
Order 830 — a legal obligation. This makes the data authoritative, mandatory,
and freely available. It is the same data TVA files as a regulatory submission.

Output
──────
data/raw/supply_all_years.csv — 280,503 rows, one row per fuel type per hour,
covering January 2019 through December 2022.
"""

import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv
from pathlib import Path

from config.settings import RAW_DATA_DIR, SUPPLY_CSV_CANDIDATES
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── API configuration ─────────────────────────────────────────────────────────

# The exact EIA API v2 endpoint for hourly generation by fuel type.
# This URL never changes — it is a fixed route on the EIA's public API.
EIA_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"

# The EIA API returns a maximum of 5,000 records per request.
# One year of TVA data across 8 fuel types = 8,760 hours × 8 = 70,080 rows.
# We must paginate: keep fetching in 5,000-row pages until exhausted.
PAGE_SIZE = 5_000

# TVA is the "balancing authority" code the EIA uses for the
# Tennessee Valley Authority grid. This is the filter we apply
# so we only receive TVA data, not data for other US grids.
TVA_CODE = "TVA"

# The four years we want. We fetch 2019 as historical context for the
# forecasting models; the 5 ORNL snapshot days all fall within 2020–2022.
FETCH_YEARS = ["2019", "2020", "2021", "2022"]


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_and_save(output_path: Path = None) -> Path:
    """
    Fetch TVA supply data from the EIA API and save to CSV.

    This function is idempotent: if the output file already exists it
    returns its path immediately without making any API calls.
    The data for 2019–2022 is historical and will never change, so there
    is no need to re-download it once you have it.

    Parameters
    ----------
    output_path : Path, optional
        Where to save the CSV. Defaults to data/raw/supply_all_years.csv.

    Returns
    -------
    Path
        Path to the saved CSV file.
    """
    # ── Step 1: Check if we already have the file ─────────────────────────
    # Look in all candidate locations (data/raw/ and notebooks/ legacy path).
    # If found anywhere, skip the API call entirely.
    for candidate in SUPPLY_CSV_CANDIDATES:
        if Path(candidate).exists():
            logger.info(f"Supply CSV already exists at: {candidate}")
            logger.info("Skipping API fetch. Delete the file to re-download.")
            return Path(candidate)

    # ── Step 2: Load the API key from .env ───────────────────────────────
    # load_dotenv() reads the .env file in the project root and sets each
    # line as an environment variable. After this call, os.getenv() can
    # find EIA_API_KEY. The .env file is gitignored so the key is never
    # accidentally committed to version control.
    load_dotenv()
    api_key = os.getenv("EIA_API_KEY", "")

    # If the key is empty, stop immediately with a clear message rather
    # than sending requests that will all fail with a 403 error.
    if not api_key:
        raise ValueError(
            "EIA_API_KEY not found. Add it to your .env file:\n"
            "  EIA_API_KEY=your_key_here\n"
            "Register for free at https://www.eia.gov/opendata/"
        )

    logger.info(f"API key loaded. Starting TVA supply data fetch for years: {FETCH_YEARS}")

    # ── Step 3: Fetch each year separately ───────────────────────────────
    # We fetch year by year rather than one giant request because:
    # (a) The date range 2019–2022 contains ~280,000 rows — too many for
    #     a single call even with pagination.
    # (b) If a single year fails, we can retry just that year without
    #     losing all progress.
    yearly_frames = []

    for year in FETCH_YEARS:
        logger.info(f"\nFetching year: {year}")

        # Build the ISO-8601 start and end strings the EIA API expects.
        # Format: YYYY-MM-DDTHH  (no minutes/seconds — hourly data only)
        start = f"{year}-01-01T00"
        end   = f"{year}-12-31T23"

        df_year = _fetch_one_year(api_key, start, end)
        logger.info(f"  Year {year}: {len(df_year):,} rows fetched")
        yearly_frames.append(df_year)

    # ── Step 4: Combine all years into one DataFrame ──────────────────────
    # pd.concat stacks the 4 yearly DataFrames vertically.
    # ignore_index=True resets the row index to 0, 1, 2, ... on the combined
    # frame rather than keeping the indices from each individual year.
    combined = pd.concat(yearly_frames, ignore_index=True)
    logger.info(f"\nCombined: {len(combined):,} total rows across all years")

    # ── Step 5: Save to CSV ───────────────────────────────────────────────
    if output_path is None:
        output_path = RAW_DATA_DIR / "supply_all_years.csv"

    # mkdir(parents=True) creates data/raw/ if it does not already exist.
    # exist_ok=True means no error if the directory is already there.
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # index=False prevents pandas from writing a redundant 0,1,2,... column
    # as the first column of the CSV.
    combined.to_csv(output_path, index=False)
    logger.info(f"Saved → {output_path}")

    return Path(output_path)


def load(csv_path: Path = None) -> pd.DataFrame:
    """
    Load the supply CSV from disk and return as a DataFrame.

    Searches the candidate locations defined in config/settings.py.
    Raises FileNotFoundError if not found anywhere.
    """
    if csv_path and Path(csv_path).exists():
        return pd.read_csv(csv_path)

    for candidate in SUPPLY_CSV_CANDIDATES:
        if Path(candidate).exists():
            logger.info(f"Loading supply data from: {candidate}")
            return pd.read_csv(candidate)

    raise FileNotFoundError(
        "supply_all_years.csv not found. Run fetch_and_save() first."
    )


def inspect(df: pd.DataFrame) -> None:
    """
    Print a structured summary of the raw supply DataFrame.

    This is the data validation step that follows every data load.
    It confirms: shape, date range, fuel types present, null counts,
    and value ranges. Any unexpected values here indicate a data quality
    issue that must be resolved before processing.
    """
    logger.info("\n── Supply Data Inspection ──────────────────────────────────")

    # Shape tells us total rows and columns at a glance.
    logger.info(f"  Shape        : {df.shape[0]:,} rows × {df.shape[1]} columns")

    # Columns tells us what fields the API returned.
    logger.info(f"  Columns      : {df.columns.tolist()}")

    # Date range confirms we have the full 2019–2022 period.
    # If the range is shorter, the fetch may have been interrupted.
    logger.info(f"  Date range   : {df['period'].min()}  →  {df['period'].max()}")

    # Fuel types confirms all 8 expected types are present.
    # If any are missing, the API may have returned incomplete data.
    fuels = sorted(df["fueltype"].unique())
    logger.info(f"  Fuel types   : {fuels}")

    # Hours per fuel type should all be the same (~35,040 for 4 full years).
    # If any fuel type has significantly fewer rows, there are gaps.
    logger.info("  Rows per fuel type:")
    for fuel, count in df.groupby("fueltype").size().items():
        logger.info(f"    {fuel:6s}: {count:,}")

    # Null counts — the EIA data has ~1,160 nulls in the value column.
    # These are concentrated in Solar (SUN) for early 2019 when TVA had
    # negligible solar capacity. We handle them in the supply processor
    # using forward/backward fill per fuel type.
    null_count = df["value"].isna().sum()
    logger.info(f"  Null values  : {null_count:,}  (in 'value' column)")

    # Negative values — Solar occasionally reports −2 MWh due to a net
    # metering measurement artefact where exported power is counted negative.
    # We clip these to 0 in the supply processor.
    neg_count = (df["value"] < 0).sum()
    logger.info(f"  Negative values: {neg_count:,}  (expected small number for SUN)")

    # Value range gives us a sanity check on magnitudes.
    logger.info(
        f"  Value range  : {df['value'].min():.1f}  –  {df['value'].max():.1f} MWh"
    )

    logger.info("────────────────────────────────────────────────────────────")


# ── Private helper ────────────────────────────────────────────────────────────

def _fetch_one_year(api_key: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetch all TVA hourly records for a single date range using pagination.

    The EIA API caps each response at PAGE_SIZE (5,000) records. This
    function sends repeated requests, increasing the offset by PAGE_SIZE
    each time, until the API returns fewer records than PAGE_SIZE — which
    signals we have reached the last page.

    Parameters
    ----------
    api_key : str
        EIA API key loaded from .env.
    start : str
        Start datetime in EIA format, e.g. "2020-01-01T00".
    end : str
        End datetime in EIA format, e.g. "2020-12-31T23".

    Returns
    -------
    pd.DataFrame
        Raw long-format DataFrame for the requested date range.
    """
    all_records = []   # Accumulates all JSON records across all pages
    offset = 0         # Tracks how many records we have already fetched

    while True:
        # Build the query parameters for this page request.
        # Each parameter is documented in the EIA API v2 specification.
        params = {
            "api_key":                  api_key,
            "frequency":                "hourly",       # We want hourly data
            "data[0]":                  "value",        # Return the MWh value column
            "facets[respondent][]":     TVA_CODE,       # TVA grid only
            "start":                    start,
            "end":                      end,
            "sort[0][column]":          "period",       # Sort by timestamp
            "sort[0][direction]":       "asc",          # Oldest records first
            "offset":                   offset,         # Skip this many records
            "length":                   PAGE_SIZE,      # Return this many records
        }

        # requests.get() sends an HTTP GET request to the EIA URL with the
        # parameters appended as a query string. The response comes back as JSON.
        response = requests.get(EIA_URL, params=params, timeout=30)

        # raise_for_status() checks the HTTP status code. If the API returned
        # a 4xx (bad request / unauthorized) or 5xx (server error) code, it
        # raises an exception immediately rather than silently returning empty data.
        response.raise_for_status()

        # Parse the JSON response body. The EIA wraps its data inside a nested
        # structure: response.json()["response"]["data"] is the actual list of records.
        records = response.json().get("response", {}).get("data", [])

        # If the API returned an empty list, we have gone past the end of the
        # dataset. Break out of the loop.
        if not records:
            break

        # Add this page's records to our accumulator.
        all_records.extend(records)
        logger.info(f"  Fetched {len(all_records):,} records so far ...")

        # If this page had fewer records than PAGE_SIZE, it was the last page.
        # Break out of the loop — there is nothing left to fetch.
        if len(records) < PAGE_SIZE:
            break

        # Advance the offset to the next page.
        offset += PAGE_SIZE

        # Pause briefly between pages. The EIA API is a free public service.
        # A 0.5-second pause prevents us from sending too many requests per
        # second and reduces the risk of being rate-limited or blocked.
        time.sleep(0.5)

    # Convert the accumulated list of JSON dicts into a pandas DataFrame.
    # Each dict is one row; the keys become column names.
    return pd.DataFrame(all_records)
