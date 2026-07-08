"""
Carbon-Aware Scheduling — Streamlit Dashboard

Two stakeholder views (sidebar nav):
  • Operations Manager — live grid CI, 48h forecast, advisory recommendation
    tool for one or more flexible jobs (not connected to a real job
    scheduler — see the capacity disclaimer on that view)
  • CSRD Compliance    — carbon savings, audit-ready reporting

Self-contained: reads small precomputed files from app/data/ and runs a
numpy-only window-ranking recommender. No heavy ML dependencies at runtime,
so it deploys cleanly on Streamlit Community Cloud.

All times in the Operations Manager view are Eastern Time (America/New_York)
— the timezone of ORNL Summit and the TVA grid, matching the alignment used
throughout the rest of the project — shown explicitly labelled as "ET".

Run locally:   streamlit run app/main.py
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import plotly.io as pio
import requests
import streamlit as st

try:                                  # optional: load .env for local runs
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Slightly larger, black, Times New Roman default font for every Plotly chart
# (covers axis titles, tick labels, and legend text via inheritance)
pio.templates["big"] = go.layout.Template(layout=dict(
    font=dict(size=14, color="#000000", family='"Times New Roman", Times, serif')))
pio.templates.default = "plotly+big"

# ── Config & palette ──────────────────────────────────────────────────────────

DATA = Path(__file__).parent / "data"

st.set_page_config(
    page_title="Carbon-Aware Scheduling",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Primary palette. GREEN is the app's brand accent (buttons, sidebar, positive
# values) — distinct from any red/amber/green carbon-status classification,
# which the Operations Manager view does not use.
GREEN   = "#15803D"
GREEN_L = "#16A34A"
BLUE    = "#1565C0"
RED     = "#C62828"
GREY    = "#607D8B"
NEUTRAL = "#3B5166"   # single-hue neutral accent (confidence labels etc.)


# ── Global styling ────────────────────────────────────────────────────────────

st.markdown("""
<style>
  /* Times New Roman across the whole app — EXCLUDING Streamlit's own icon
     fonts, which must keep their icon font-family or their ligature names
     (e.g. "keyboard_double_arrow_left") render as literal text instead of a
     glyph. */
  html, body, [class*="css"], [data-testid="stAppViewContainer"] *,
  section[data-testid="stSidebar"] *, button, input, textarea, select {
      font-family: "Times New Roman", Times, serif !important;}
  /* Icon fix must OUT-SPECIFY the rules above (same ancestor scope + the
     icon's own attribute), since a bare [data-testid*="Icon"] selector is
     less specific than "section[data-testid='stSidebar'] *" and loses even
     with !important on both sides. Verified against Streamlit's own
     compiled source: the icon element's real testid is stIconMaterial and
     its font is genuinely named "Material Symbols Rounded". */
  section[data-testid="stSidebar"] [data-testid="stIconMaterial"],
  [data-testid="stAppViewContainer"] [data-testid="stIconMaterial"],
  section[data-testid="stSidebar"] [data-testid*="Icon"],
  [data-testid="stAppViewContainer"] [data-testid*="Icon"],
  [data-testid="stIconMaterial"], [data-testid*="Icon"],
  [class*="material-icons"], [class*="material-symbols"] {
      font-family: "Material Symbols Rounded", "Material Icons", sans-serif !important;}

  /* Moderate global font increase */
  html {font-size: 108%;}

  .block-container {padding-top: 3rem; padding-bottom: 2rem; max-width: 1560px;}
  [data-testid="stAppViewContainer"] {background: #f5f8f6;}

  /* Main-area body text: black (no greys) */
  [data-testid="stAppViewContainer"] p,
  [data-testid="stAppViewContainer"] label,
  [data-testid="stAppViewContainer"] li,
  [data-testid="stAppViewContainer"] span {color:#0f1f16;}
  [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {
      color:#000000 !important; font-size:0.95rem !important;}

  /* CSRD KPI tiles (st.metric): value bold + large, label dark */
  [data-testid="stMetricValue"] {color:#000000 !important; font-weight:800; font-size:2.1rem;}
  [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {
      color:#000000 !important; font-weight:700; font-size:1rem !important;}
  [data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * {color:#000000 !important;}

  /* Sidebar — dark green, shifted up, light text on dark */
  section[data-testid="stSidebar"] {background: #0c2a1a; font-size:1.05rem;}
  section[data-testid="stSidebar"] * {color: #eef5f0;}
  [data-testid="stSidebarUserContent"] {padding-top: 0.3rem;}
  section[data-testid="stSidebar"] button[kind="primary"] {
      background:#16a34a; border:none; color:#fff; font-weight:700; text-align:left;
      justify-content:flex-start; border-radius:10px;}
  section[data-testid="stSidebar"] button[kind="secondary"] {
      background:transparent; border:none; color:#f5faf7; font-weight:600; text-align:left;
      justify-content:flex-start; border-radius:10px;}
  section[data-testid="stSidebar"] button[kind="secondary"]:hover {background:#123d27;}

  /* Green primary buttons in the main area */
  [data-testid="stAppViewContainer"] button[kind="primary"] {background:#16a34a; border-color:#16a34a;}
  /* Small icon buttons (row add/delete) */
  [data-testid="stAppViewContainer"] button[kind="secondary"] {padding:0.25rem 0.6rem;}

  /* Page header */
  .page-title {font-size:2.15rem; font-weight:800; color:#000000; line-height:1.2; padding-top:2px;}
  .page-sub {font-size:1.05rem; color:#000000; margin-top:3px;}
  .fresh {text-align:right; font-size:0.9rem; color:#000000; font-weight:700;}
  .fresh-dot {height:9px; width:9px; border-radius:50%; background:#22c55e;
              display:inline-block; margin-right:6px;}

  /* Metric cards — equal height for clean alignment */
  .metric-card {background:#fff; border:1px solid #dfe6e1; border-radius:14px;
                padding:16px 18px; box-shadow:0 1px 3px rgba(0,0,0,0.05);
                height:100%; min-height:142px;}
  .metric-card.center {text-align:center;}
  .metric-card.center .mc-label {justify-content:center;}
  /* Force every wrapper around a card to fill the row height so card bottoms align */
  [data-testid="stHorizontalBlock"]:has(.metric-card) {align-items: stretch;}
  [data-testid="stColumn"]:has(.metric-card) > div,
  [data-testid="column"]:has(.metric-card) > div,
  [data-testid="stColumn"]:has(.metric-card) [data-testid="stElementContainer"],
  [data-testid="column"]:has(.metric-card) [data-testid="stElementContainer"],
  [data-testid="stMarkdown"]:has(.metric-card),
  [data-testid="stMarkdownContainer"]:has(.metric-card) {height:100%;}
  .section-h {font-size:1.35rem; font-weight:800; color:#000000; margin:3px 0 12px 0;
              display:flex; align-items:center; gap:6px;}
  .section-h .sub {font-weight:600; color:#000000; font-size:1rem;}
  .mc-info {cursor:help; color:#000000; font-size:0.9rem; margin-left:2px;}
  /* Custom hover tooltip (native title-attribute tooltips are unreliable,
     especially multi-line) -- shows/hides immediately and reliably via CSS. */
  .tooltip-wrap {position:relative; display:inline-block; cursor:help;}
  .tooltip-wrap .tooltip-body {
      visibility:hidden; opacity:0; transition:opacity .12s ease;
      position:absolute; right:0; top:135%; z-index:1000;
      background:#0a1710; color:#ffffff; padding:10px 14px; border-radius:8px;
      font-size:0.82rem; font-weight:500; line-height:1.5; white-space:nowrap;
      box-shadow:0 4px 14px rgba(0,0,0,0.25); text-align:left;}
  .tooltip-wrap:hover .tooltip-body {visibility:visible; opacity:1;}
  /* label = supporting text (smaller) */
  .mc-label {font-size:1rem; color:#000000; font-weight:600;
             display:flex; gap:6px; align-items:center;}
  /* value = the metric (bold + largest) */
  .mc-value {font-weight:800; color:#000000; line-height:1.25; margin-top:8px;}
  .mc-unit  {font-size:0.95rem; color:#000000; font-weight:700;}
  .mc-sub   {font-size:0.88rem; color:#000000; margin-top:8px;}
  .badge-neutral {display:inline-block; padding:2px 11px; border-radius:999px;
                  font-size:0.82rem; font-weight:700; background:#eaeef2; color:#3B5166;}

  /* Recommended-schedule table */
  .rec-table {width:100%; border-collapse:collapse; font-size:0.98rem;}
  .rec-table th {text-align:left; color:#000000; font-weight:800;
                 padding:11px 9px; border-bottom:2px solid #cdd8d1; white-space:nowrap;}
  .rec-table td {padding:12px 9px; border-bottom:1px solid #e6ede8; color:#000000; font-weight:500;}
</style>
""", unsafe_allow_html=True)


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data
def load():
    kpis = json.load(open(DATA / "kpis.json"))
    integ = pd.read_csv(DATA / "integrated.csv")
    hourly = pd.read_csv(DATA / "ci_hourly.csv")
    monthly = pd.read_csv(DATA / "ci_monthly.csv")
    fuel = pd.read_csv(DATA / "fuel_mix.csv")
    fuel_monthly = pd.read_csv(DATA / "fuel_mix_monthly.csv")
    window = pd.read_csv(DATA / "forecast_window.csv")
    return kpis, integ, hourly, monthly, fuel, fuel_monthly, window


# ── Live grid data via EIA API (with static fallback) ─────────────────────────

EIA_URL = "https://api.eia.gov/v2/electricity/rto/fuel-type-data/data/"
# IPCC AR5 lifecycle emission factors (gCO₂/kWh), matching config/settings.py
EMISSION_FACTORS = {"COL": 1000, "NG": 450, "OIL": 800, "NUC": 0,
                    "SUN": 0, "WAT": 0, "WND": 0, "OTH": 500}


def _eia_key():
    """API key from Streamlit secrets (deploy) or environment/.env (local)."""
    try:
        k = st.secrets.get("EIA_API_KEY", "")
    except Exception:
        k = ""
    return k or os.getenv("EIA_API_KEY", "")


def _tou_price(ts):
    """Representative Time-of-Use tariff ($/MWh) by season and local hour."""
    summer = ts.month in (6, 7, 8, 9)
    h = ts.hour
    tier = "off" if h < 7 else "peak" if 17 <= h < 22 else "shoulder"
    return {"off": 28 if summer else 25, "shoulder": 52 if summer else 45,
            "peak": 95 if summer else 75}[tier]


FACILITY_TZ = "America/New_York"   # ORNL Summit / TVA — Eastern Time, matching
                                    # the rest of the project's timezone alignment


def fetch_live_window(hours=48, timeout=10):
    """
    Pull the latest TVA hourly generation-by-fuel from the EIA API, convert it to
    carbon intensity (gCO₂/kWh), and build a 48h forward window using a
    daily-persistence profile (the documented scheduling driver). Prices are the
    representative ToU tariff. Raises on any failure so the caller can fall back.

    EIA publishes on a UTC clock, so the persistence lookup (which hour-of-day
    matches which historical CI) is correctly keyed in UTC — that is a fact
    about the data source, not a display choice. Everything the operator
    actually sees (the returned timestamps, and the ToU price, which depends
    on the *local* hour) is in Eastern Time, since ORNL Summit and TVA are
    physically in Oak Ridge, TN — the same alignment used throughout the rest
    of this project, not the viewer's browser timezone (which Streamlit has
    no way to know server-side, and which isn't the relevant stakeholder's
    timezone anyway).
    """
    key = _eia_key()
    if not key:
        raise RuntimeError("EIA_API_KEY not configured")
    now_utc = pd.Timestamp.now(tz="UTC").tz_localize(None)
    now_et = pd.Timestamp.now(tz=FACILITY_TZ).tz_localize(None)
    end = now_utc.floor("h")
    start = end - pd.Timedelta(days=6)
    params = {
        "api_key": key, "frequency": "hourly", "data[0]": "value",
        "facets[respondent][]": "TVA",
        "start": start.strftime("%Y-%m-%dT%H"), "end": end.strftime("%Y-%m-%dT%H"),
        "sort[0][column]": "period", "sort[0][direction]": "asc",
        "offset": 0, "length": 5000,
    }
    r = requests.get(EIA_URL, params=params, timeout=timeout)
    r.raise_for_status()
    recs = r.json().get("response", {}).get("data", [])
    if not recs:
        raise RuntimeError("EIA returned no data")
    df = pd.DataFrame(recs)
    df["value"] = pd.to_numeric(df["value"], errors="coerce").fillna(0).clip(lower=0)
    df["period"] = pd.to_datetime(df["period"])
    wide = df.pivot_table(index="period", columns="fueltype",
                          values="value", aggfunc="sum").fillna(0)
    ef = pd.Series(EMISSION_FACTORS)
    gen = wide.reindex(columns=ef.index, fill_value=0)
    ci_series = (gen.mul(ef, axis=1).sum(axis=1) /
                 gen.sum(axis=1).replace(0, np.nan)).dropna()
    if len(ci_series) < 24:
        raise RuntimeError("insufficient live hours")
    # daily-persistence: most recent CI observed at each hour-of-day (UTC — the
    # EIA "period" field's native timezone)
    by_hour = ci_series.groupby(ci_series.index.hour).last()
    rows = []
    for t in range(hours):
        ci_t = float(by_hour.get((now_utc.hour + t) % 24, by_hour.mean()))
        ts_et = now_et + pd.Timedelta(hours=t)
        rows.append({"datetime": ts_et, "ci": ci_t, "price": _tou_price(ts_et)})
    rows[0]["ci"] = float(ci_series.iloc[-1])          # hour 0 = true latest reading
    latest_et = (pd.Timestamp(ci_series.index[-1], tz="UTC")
                .tz_convert(FACILITY_TZ).tz_localize(None))
    return pd.DataFrame(rows), str(latest_et)


@st.cache_data(show_spinner="Fetching live TVA grid data…")
def get_window(refresh_token):
    """Cached on the refresh timestamp: only a Refresh re-hits the network."""
    try:
        df, latest_ts = fetch_live_window()
        return df, "live", latest_ts
    except Exception as exc:
        return pd.read_csv(DATA / "forecast_window.csv"), f"static:{type(exc).__name__}", None


kpis, integ, hourly, monthly, fuel, fuel_monthly, _static = load()

# Live "data as of" anchor — Eastern Time (ORNL Summit / TVA's own timezone,
# matching the rest of the project), set on first load, re-stamped by Refresh.
# The 48h forecast horizon is anchored to this timestamp, so clock times
# (recommended starts, deadlines) read relative to the moment of refresh.
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = pd.Timestamp.now(tz=FACILITY_TZ).tz_localize(None)
NOW = st.session_state.last_refresh

window, DATA_SOURCE, LATEST_TS = get_window(st.session_state.last_refresh)
CI = window["ci"].values
PRICE = window["price"].values if "price" in window.columns else np.full(len(CI), 40.0)

# Confidence-level cut points, derived once from the actual historical spread
# (P75-P25) at each hour of day — used to label each recommended window.
_spreads = (hourly["p75"] - hourly["p25"]).values
_CONF_P33, _CONF_P66 = np.percentile(_spreads, [33, 66])


# ── Formatting helpers ────────────────────────────────────────────────────────

def fmt_clock(dt):
    """'Sat, 3:00 PM' — no leading zero, platform-independent."""
    return dt.strftime("%a, ") + dt.strftime("%I:%M %p").lstrip("0")


def fmt_full(dt):
    """'09 Jul, 2:00 AM' — date and time, for headline "best option" values."""
    return dt.strftime("%d %b, ") + dt.strftime("%I:%M %p").lstrip("0")


def fmt_stamp(dt):
    return dt.strftime("%d %b %Y, ") + dt.strftime("%I:%M %p").lstrip("0")


def confidence_label(p25, p75):
    """
    Qualitative confidence in the forecast for one window, derived from how
    wide the historical (P25-P75) carbon-intensity range is at that hour of
    day: a narrow historical range means the hour behaves consistently
    day-to-day (High confidence); a wide one means it varies a lot (Low).
    Cut points are the 33rd/66th percentile of that spread across all 24
    hours of day in the historical data — not an arbitrary fixed threshold.
    """
    if p25 is None or p75 is None:
        return "—"
    spread = p75 - p25
    if spread <= _CONF_P33: return "High"
    if spread <= _CONF_P66: return "Medium"
    return "Low"


# ── Recommendation engine (numpy only, no capacity claim) ──────────────────────
#
# This tool has no connection to the real job scheduler, so it cannot see what
# else is queued or running, and cannot reserve or verify node availability.
# It therefore makes no capacity-aware placement decision — it only reports,
# for each flexible job, every start time within the deadline and how clean/
# cheap that window is versus running now. The operator picks; nothing is
# auto-submitted. "Nodes required" is used only to size the energy (and hence
# the carbon/cost impact) of the job, never to check for conflicts.

def _tier_label(ts):
    """Named ToU period for a timestamp — off-peak / shoulder / peak."""
    h = ts.hour
    if h < 7: return "Off-Peak"
    if 17 <= h < 22: return "Peak"
    return "Shoulder"


def find_recommended_windows(nodes, duration, deadline_hours, ci, price, weight,
                             hourly_stats, now, power_per_node=1.2):
    """
    Scan every feasible start hour for one flexible job within its deadline and
    return ALL viable windows, ranked best-first by the blended carbon/cost
    score. Returns (options, run_ci, run_price) — options is a list of dicts.
    """
    H = len(ci)
    latest = min(deadline_hours, H) - duration
    if latest < 0:
        return [], None, None
    energy_kwh = nodes * power_per_node * duration
    energy_mwh = energy_kwh / 1000.0
    run_ci = float(np.mean(ci[:duration]))
    run_pr = float(np.mean(price[:duration]))

    def norm(a):
        a = np.asarray(a, float); rng = a.max() - a.min()
        return (a - a.min()) / rng if rng > 1e-9 else np.zeros_like(a)
    ci_n, pr_n = norm(ci), norm(price)

    options = []
    for t in range(0, latest + 1):
        sci = float(np.mean(ci[t:t + duration]))
        spr = float(np.mean(price[t:t + duration]))
        score = weight * float(np.mean(ci_n[t:t + duration])) + \
                (1 - weight) * float(np.mean(pr_n[t:t + duration]))
        ts = now + pd.Timedelta(hours=t)
        hist = hourly_stats[hourly_stats["hour_of_day"] == ts.hour]
        p25 = float(hist["p25"].iloc[0]) if len(hist) else None
        p75 = float(hist["p75"].iloc[0]) if len(hist) else None
        options.append(dict(
            start=t, ts=ts, sched_ci=sci, sched_price=spr, score=score,
            carbon_saved_kg=energy_kwh * (run_ci - sci) / 1000.0,
            cost_saved_usd=energy_mwh * (run_pr - spr),
            hist_p25=p25, hist_p75=p75, tier_label=_tier_label(ts),
            confidence=confidence_label(p25, p75)))
    options.sort(key=lambda o: o["score"])
    return options, run_ci, run_pr


# ── HTML card builder ─────────────────────────────────────────────────────────

def card(label, value, unit="", sub="", icon="", value_size="1.9rem", info="", center=False):
    s = f'<div class="mc-sub">{sub}</div>' if sub else ""
    u = f'<span class="mc-unit">{unit}</span>' if unit else ""
    i = (f'<span class="tooltip-wrap" style="font-size:0.9rem;color:#000000;">ⓘ'
         f'<span class="tooltip-body" style="white-space:normal;max-width:240px;">{info}'
         f'</span></span>') if info else ""
    cls = "metric-card center" if center else "metric-card"
    return (f'<div class="{cls}"><div class="mc-label">{icon} {label}{i}</div>'
            f'<div class="mc-value" style="font-size:{value_size};">{value} {u}</div>'
            f'{s}</div>')


# ── Sidebar navigation ────────────────────────────────────────────────────────

if "page" not in st.session_state:
    st.session_state.page = "ops"

st.sidebar.markdown(
    "<div style='display:flex;align-items:center;gap:10px;padding:0px 4px 10px 4px;margin-top:0;'>"
    "<span style='font-size:1.6rem;'>🌿</span>"
    "<span style='font-size:1.15rem;font-weight:800;line-height:1.1;'>Carbon-Aware<br>Scheduling</span>"
    "</div>", unsafe_allow_html=True)


def nav(label, page_id):
    active = st.session_state.page == page_id
    if st.sidebar.button(label, use_container_width=True,
                         type="primary" if active else "secondary", key="nav_" + page_id):
        st.session_state.page = page_id
        st.rerun()


nav("⚙️  Operations Manager", "ops")
nav("🛡️  CSRD Compliance", "csrd")

st.sidebar.markdown(
    "<div style='background:#123d27;border-radius:12px;padding:16px;margin-top:28px;'>"
    "<div style='font-size:1.4rem;'>🌱</div>"
    "<div style='font-weight:700;margin-top:6px;'>Every decision counts.</div>"
    "<div style='color:#f5faf7;font-size:0.85rem;margin-top:4px;'>Schedule smart. Reduce carbon.</div>"
    "<hr style='border-color:#1e5236;margin:12px 0;'>"
    "<div style='color:#f5faf7;font-size:0.78rem;'>Sustainable. Efficient. Responsible.</div>"
    "</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  OPERATIONS MANAGER VIEW
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.page == "ops":

    # ── Header (title · freshness+reading · refresh) ──────────────────────────
    h1, h2, h3 = st.columns([5.5, 2.5, 2], vertical_alignment="center")
    with h1:
        st.markdown("<div class='page-title'>Operations Manager</div>", unsafe_allow_html=True)
    with h2:
        if DATA_SOURCE == "live":
            src = "<span style='color:#15803d;font-weight:700;'>Live · TVA grid</span>"; dot = "background:#22c55e;"
        else:
            src = "<span style='color:#b45309;font-weight:700;'>Demo data</span>"; dot = "background:#f59e0b;"
        st.markdown(f"<div class='fresh'><span class='fresh-dot' style='{dot}'></span>{src}</div>",
                   unsafe_allow_html=True)
    with h3:
        tooltip = f"Data as of {fmt_stamp(NOW)} ET"
        if DATA_SOURCE == "live" and LATEST_TS:
            tooltip += f"<br>Latest TVA reading: {LATEST_TS} ET"
        ic, bc = st.columns([1, 4], vertical_alignment="center")
        ic.markdown(
            "<div style='display:flex;align-items:center;justify-content:center;"
            "height:2.5rem;'>"
            f"<span class='tooltip-wrap' style='font-size:1.15rem;color:#000000;'>ⓘ"
            f"<span class='tooltip-body'>{tooltip}</span></span></div>",
            unsafe_allow_html=True)
        if bc.button("🔄 Refresh", key="refresh", use_container_width=True):
            st.session_state.last_refresh = pd.Timestamp.now(tz=FACILITY_TZ).tz_localize(None)
            st.cache_data.clear(); st.rerun()

    st.write("")

    # ══════════════════════════════════════════════════════════════════════════
    #  SECTION 1 · SCHEDULE FLEXIBLE JOBS (advisory — not connected to a scheduler)
    # ══════════════════════════════════════════════════════════════════════════
    with st.container(border=True):
        st.markdown(
            "<div class='section-h'>🗓️ Schedule Flexible Jobs"
            "<span class='tooltip-wrap' style='font-size:0.9rem;color:#000000;margin-left:2px;'>ⓘ"
            "<span class='tooltip-body' style='white-space:normal;width:320px;left:0;right:auto;"
            "font-weight:400;'>Enter one or more delay-tolerant jobs to see every viable start "
            "window before each deadline, ranked by carbon and cost saved versus running now. "
            "This is a recommendation only — it has no visibility into your job scheduler's real "
            "queue or node availability, and does not reserve or submit anything. Each job is "
            "checked independently against the grid forecast.</span></span>"
            "</div>", unsafe_allow_html=True)
        st.markdown("<div style='color:#000000;font-size:0.85rem;margin-bottom:8px;'>"
                    "All times on this page are in Eastern Time (ET) — ORNL Summit's timezone."
                    "</div>", unsafe_allow_html=True)

        # ── job entry table (data_editor — native row selection + delete icon) ──
        # num_rows="dynamic" gives Streamlit's own row-select checkboxes (left
        # edge of each row) plus a trash-icon delete control in the grid's own
        # toolbar right next to the "+" add-row control -- no custom column
        # needed; this is the built-in equivalent of "+/- icons near each other".
        # NOTE: the widget's own key ("job_editor") is the single source of
        # truth for live edits across reruns -- Streamlit manages that
        # automatically. We seed st.session_state.job_batch ONCE for the
        # widget's initial data and never write back into it; doing so
        # previously fed the editor's own output back in as its "data" prop
        # every rerun, which made the widget treat that as new external data
        # and reset its in-progress edit state -- the exact cause of typed
        # text disappearing and needing to be re-entered.
        if "job_batch" not in st.session_state:
            st.session_state.job_batch = pd.DataFrame([
                {"Job Name": "My Job", "Nodes": 2000, "Duration (hrs)": 4,
                 "Deadline (ET)": (NOW + pd.Timedelta(hours=12)).floor("h")},
            ])
        edited = st.data_editor(
            st.session_state.job_batch, num_rows="dynamic", use_container_width=True, key="job_editor",
            column_config={
                "Job Name": st.column_config.TextColumn(width="medium",
                                                        help="A label for the job (optional)"),
                "Nodes": st.column_config.NumberColumn("Nodes", min_value=1,
                                                       max_value=kpis["total_nodes"], step=100),
                "Duration (hrs)": st.column_config.NumberColumn(min_value=1, max_value=24, step=1),
                "Deadline (ET)": st.column_config.DatetimeColumn(
                    "Deadline (ET)", format="h A, D MMM YYYY", step=3600,
                    help="Date & hour (Eastern Time) the job must finish by. Optimised within "
                         "the next 48 h (the forecast horizon); later deadlines are capped to 48 h."),
            })

        # ── Optimise-for control: simple 3-way choice, no slider/percentages ───
        st.markdown("<div style='height:10px;'></div>"
                    "<div style='color:#000000;font-weight:700;font-size:1rem;'>Optimise for</div>",
                    unsafe_allow_html=True)
        choice = st.radio("Optimise for", ["🌿 Carbon First", "⚖️ Balanced", "💲 Cost First"],
                          index=0, horizontal=True, label_visibility="collapsed", key="opt_choice")
        weight = {"🌿 Carbon First": 1.0, "⚖️ Balanced": 0.5, "💲 Cost First": 0.0}[choice]
        st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)

        # ── check every job independently — no shared-capacity assumption ──────
        horizon_h = len(CI)

        def check_job(name, nodes, duration, deadline_dt):
            dl_raw = (deadline_dt - NOW).total_seconds() / 3600.0
            if dl_raw < duration:
                return None, f"deadline is sooner than the job's own {duration} h duration"
            dl_hours = int(min(dl_raw, horizon_h))
            options, run_ci, run_pr = find_recommended_windows(
                nodes, duration, dl_hours, CI, PRICE, weight, hourly, NOW)
            if not options:
                return None, "no feasible window before the deadline"
            starts = [o["start"] for o in options]
            best = options[0]
            ext_note = None
            if dl_hours < horizon_h:
                ext_opts, _, _ = find_recommended_windows(
                    nodes, duration, min(dl_hours + 6, horizon_h), CI, PRICE, weight, hourly, NOW)
                if ext_opts:
                    ext_note = (ext_opts[0]["carbon_saved_kg"] - best["carbon_saved_kg"],
                               ext_opts[0]["cost_saved_usd"] - best["cost_saved_usd"])
            return dict(name=name or "Job", nodes=nodes, duration=duration, deadline_dt=deadline_dt,
                       dl_hours=dl_hours, beyond_horizon=dl_raw > horizon_h, options=options,
                       run_ci=run_ci, run_pr=run_pr, best=best,
                       avg_wait=float(np.mean(starts)), max_wait=max(starts),
                       ext_note=ext_note), None

        results, skipped = [], []
        for _, row in edited.iterrows():
            try:
                n = int(row["Nodes"]); d = int(row["Duration (hrs)"])
                nm = str(row["Job Name"]) if pd.notna(row["Job Name"]) else ""
                if pd.isna(row["Deadline (ET)"]) or n < 1 or d < 1:
                    continue
                deadline_dt = pd.to_datetime(row["Deadline (ET)"])
            except (TypeError, ValueError):
                continue
            res, err = check_job(nm, n, d, deadline_dt)
            if res:
                results.append(res)
            elif err:
                skipped.append(f"**{nm or 'a job'}** — {err}")

        if skipped:
            st.warning("Skipped: " + "; ".join(skipped))

        if not results:
            st.info("Add at least one valid job (deadline must be after the job's own duration).")
        else:
            beyond = [r["name"] for r in results if r["beyond_horizon"]]
            if beyond:
                st.info(f"ℹ️ {', '.join(beyond)}: deadline extends beyond the {horizon_h}-hour "
                       f"forecast horizon — recommendations are computed within the visible "
                       f"{horizon_h} h only.")

            def render_detail(res, page_key):
                options, best = res["options"], res["best"]
                m1, m2, m3, m4 = st.columns(4)
                m1.markdown(card("Run-Now Baseline", f"{res['run_ci']:.0f}", "gCO₂/kWh",
                                 sub=f"${res['run_pr']:.0f}/MWh", icon="⏱️"),
                           unsafe_allow_html=True)
                best_val = "Now" if best["start"] == 0 else f"{fmt_full(best['ts'])} (+{best['start']}h)"
                m2.markdown(card("Best Option", best_val,
                                 sub=f"{best['carbon_saved_kg']:,.0f} kg CO₂ · ${best['cost_saved_usd']:,.0f} saved",
                                 icon="🌿", value_size="1.4rem"), unsafe_allow_html=True)
                m3.markdown(card("Options Found", f"{len(options)}", "",
                                 sub=f"Avg wait {res['avg_wait']:.0f} h · Max {res['max_wait']} h",
                                 icon="📋", center=True), unsafe_allow_html=True)
                if res["ext_note"]:
                    d_kg, d_usd = res["ext_note"]
                    if d_kg > 0.5 or d_usd > 0.5:
                        m4.markdown(card("+6 h Deadline Would Unlock",
                                         f"+{d_kg:,.0f} kg / +${d_usd:,.0f}",
                                         sub="vs current deadline", icon="➕"), unsafe_allow_html=True)
                    else:
                        m4.markdown(card("+6 h Deadline Would Unlock", "—",
                                         sub="No material gain from waiting longer", icon="➕"),
                                   unsafe_allow_html=True)
                else:
                    m4.markdown(card("+6 h Deadline Would Unlock", "—",
                                     sub="Already at the 48 h forecast horizon", icon="➕"),
                               unsafe_allow_html=True)

                st.markdown("<div style='height:8px;'></div>"
                            "<div class='section-h' style='font-size:1.05rem;'>Recommended Start Times</div>",
                           unsafe_allow_html=True)

                # ── pagination: 10 windows per page, state kept per page_key ────
                per_page = 10
                n_pages = max(1, (len(options) + per_page - 1) // per_page)
                pg_key = f"table_page_{page_key}"
                page = min(st.session_state.get(pg_key, 0), n_pages - 1)
                st.session_state[pg_key] = page
                start_i = page * per_page
                page_options = options[start_i:start_i + per_page]

                rows_html = ""
                for i, o in enumerate(page_options):
                    abs_i = start_i + i
                    hi_style = " style='background:#eef2f7;'" if abs_i == 0 else ""
                    start_html = ("<b style='color:#15803d;'>Now</b>" if o["start"] == 0
                                 else f"<b style='color:#15803d;'>{fmt_clock(o['ts'])}</b> (+{o['start']}h)")
                    rank_lab = "★ Best" if abs_i == 0 else f"#{abs_i+1}"
                    rows_html += (f"<tr{hi_style}><td>{rank_lab}</td><td>{start_html}</td>"
                                 f"<td>{o['sched_ci']:.0f} gCO₂/kWh</td>"
                                 f"<td>{o['carbon_saved_kg']:,.0f} kg CO₂</td>"
                                 f"<td>${o['cost_saved_usd']:,.0f}</td>"
                                 f"<td><span class='badge-neutral'>{o['confidence']}</span></td></tr>")
                st.markdown(
                    "<div style='overflow-x:auto;'><table class='rec-table'><thead><tr>"
                    "<th>Rank</th><th>Start Time</th><th>Predicted CI</th>"
                    "<th>Carbon Saved</th><th>Cost Saved</th>"
                    "<th title=\"Based on how consistent this hour of day has historically been "
                    "(P25–P75 carbon-intensity spread): a narrow historical range means High "
                    "confidence in this forecast, a wide range means Low.\">Confidence ⓘ</th>"
                    "</tr></thead><tbody>" + rows_html + "</tbody></table></div>",
                    unsafe_allow_html=True)

                if n_pages > 1:
                    pv, lbl, nx = st.columns([1, 3, 1], vertical_alignment="center")
                    if pv.button("◀ Prev", key=f"prev_{page_key}", disabled=page == 0,
                                use_container_width=True):
                        st.session_state[pg_key] = page - 1
                        st.rerun()
                    lbl.markdown(
                        f"<div style='text-align:center;color:#000000;font-size:0.88rem;'>"
                        f"Page {page+1} of {n_pages} · showing {start_i+1}–"
                        f"{min(start_i+per_page, len(options))} of {len(options)}</div>",
                        unsafe_allow_html=True)
                    if nx.button("Next ▶", key=f"next_{page_key}", disabled=page >= n_pages - 1,
                                use_container_width=True):
                        st.session_state[pg_key] = page + 1
                        st.rerun()

                opts_df = pd.DataFrame([{
                    "Rank": i + 1, "Start": "Now" if o["start"] == 0 else fmt_clock(o["ts"]),
                    "Hours from now": o["start"], "Predicted CI (gCO2/kWh)": round(o["sched_ci"], 1),
                    "Predicted Price ($/MWh)": round(o["sched_price"], 1),
                    "Price Period": o["tier_label"], "Confidence": o["confidence"],
                    "Carbon Saved (kg)": round(o["carbon_saved_kg"], 1),
                    "Cost Saved ($)": round(o["cost_saved_usd"], 2),
                } for i, o in enumerate(options)])
                st.download_button("📥 Download these windows (CSV)",
                                  opts_df.to_csv(index=False).encode(),
                                  f"{res['name']}_recommended_windows.csv", "text/csv",
                                  key="dl_detail")

            if len(results) == 1:
                st.markdown("<div style='height:2px;'></div>"
                            "<div class='section-h' style='font-size:1.05rem;'>Summary</div>",
                           unsafe_allow_html=True)
                render_detail(results[0], "single")
            else:
                # ── multi-job: compact summary table + drill-down selector ─────
                st.markdown("<div style='height:2px;'></div>"
                            "<div class='section-h' style='font-size:1.05rem;'>Job Summary "
                            f"<span class='sub'>({len(results)} jobs checked)</span></div>",
                           unsafe_allow_html=True)
                srows = ""
                for r in results:
                    b = r["best"]
                    start_html = ("<b style='color:#15803d;'>Now</b>" if b["start"] == 0
                                 else f"<b style='color:#15803d;'>{fmt_clock(b['ts'])}</b> (+{b['start']}h)")
                    srows += (f"<tr><td>{r['name']}</td><td>{r['nodes']:,}</td><td>{r['duration']}</td>"
                             f"<td>{fmt_clock(r['deadline_dt'])}</td><td>{start_html}</td>"
                             f"<td>{b['carbon_saved_kg']:,.0f} kg CO₂</td>"
                             f"<td>${b['cost_saved_usd']:,.0f}</td>"
                             f"<td>{len(r['options'])} ({r['avg_wait']:.0f}h avg / {r['max_wait']}h max)</td></tr>")
                st.markdown(
                    "<div style='overflow-x:auto;'><table class='rec-table'><thead><tr>"
                    "<th>Job</th><th>Nodes</th><th>Duration (hrs)</th><th>Deadline</th>"
                    "<th>Best Start</th><th>Carbon Saved</th><th>Cost Saved</th><th>Options (wait)</th>"
                    "</tr></thead><tbody>" + srows + "</tbody></table></div>",
                    unsafe_allow_html=True)

                tot_kg = sum(r["best"]["carbon_saved_kg"] for r in results)
                tot_usd = sum(r["best"]["cost_saved_usd"] for r in results)
                st.markdown(
                    f"<div class='mc-sub' style='margin-top:8px;'>If every job above ran at its "
                    f"<b>best</b> option: <b>{tot_kg:,.0f} kg CO₂</b> and "
                    f"<b>${tot_usd:,.0f}</b> saved in total versus running all of them now.</div>",
                    unsafe_allow_html=True)
                summary_df = pd.DataFrame([{
                    "Job": r["name"], "Nodes": r["nodes"], "Duration (hrs)": r["duration"],
                    "Deadline": fmt_clock(r["deadline_dt"]),
                    "Best Start": "Now" if r["best"]["start"] == 0 else fmt_clock(r["best"]["ts"]),
                    "Carbon Saved (kg)": round(r["best"]["carbon_saved_kg"], 1),
                    "Cost Saved ($)": round(r["best"]["cost_saved_usd"], 2),
                    "Options Found": len(r["options"]),
                } for r in results])
                st.download_button("📥 Download job summary (CSV)",
                                  summary_df.to_csv(index=False).encode(),
                                  "job_summary.csv", "text/csv")

                st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
                labels = [f"{i+1}. {r['name']}" for i, r in enumerate(results)]
                pick = st.selectbox("View full recommended windows for:", range(len(results)),
                                    format_func=lambda i: labels[i], key="job_detail_pick")
                render_detail(results[pick], f"job{pick}")

            st.markdown(
                "<div style='margin-top:10px;padding:10px 14px;background:#fef3c7;"
                "border-radius:8px;font-size:0.88rem;color:#5c3d05;'>"
                "⚠️ <b>Capacity not verified.</b> Each job is checked independently against the "
                "grid forecast only — this tool does not connect to the real job scheduler, cannot "
                "confirm nodes will actually be free at the recommended time, and does not check "
                "whether jobs above would compete for the same nodes if run together. Verify "
                "availability in your scheduler before committing.</div>",
                unsafe_allow_html=True)

    st.write("")

    # ── Grid status snapshot (compute) ────────────────────────────────────────
    current_ci = float(CI[0])
    price_now = float(PRICE[0])
    q1, q2 = np.quantile(PRICE, [1/3, 2/3])
    p_tier = 1 if price_now <= q1 else 2 if price_now <= q2 else 3

    thr = 250 if CI.min() < 250 else float(np.percentile(CI, 20))
    clean_idx = int(np.argmax(CI < thr)) if (CI < thr).any() else int(CI.argmin())
    clean_dur = 0
    for h in range(clean_idx, len(CI)):
        if CI[h] < thr: clean_dur += 1
        else: break
    clean_time = NOW + pd.Timedelta(hours=clean_idx)

    # ══════════════════════════════════════════════════════════════════════════
    #  SECTION 2 · GRID OVERVIEW & FORECAST
    # ══════════════════════════════════════════════════════════════════════════
    with st.container(border=True):
        st.markdown("<div class='section-h'>Grid Overview &amp; Forecast</div>", unsafe_allow_html=True)

        a, b, c = st.columns(3)
        a.markdown(card("Current Grid CI", f"{current_ci:.0f}", "gCO₂/kWh",
                        icon="☁️", value_size="1.95rem",
                        info="Live TVA grid carbon intensity from the EIA API"),
                   unsafe_allow_html=True)
        b.markdown(card("Electricity Price", f"${price_now:.2f}", "/MWh",
                        sub=f"Price tier: {p_tier} of 3",
                        icon="💲", value_size="1.85rem",
                        info="Representative Time-of-Use tariff (modelled)"),
                   unsafe_allow_html=True)
        c.markdown(card("Next Clean Window", fmt_clock(clean_time).split(", ")[1], "",
                        sub=f"in {clean_idx}h ({clean_dur}h window)", icon="🌱", value_size="1.7rem",
                        info="Next sustained low-carbon period in the 48h forecast"),
                   unsafe_allow_html=True)

        st.markdown("<div style='height:14px;'></div>"
                    "<div class='section-h' style='font-size:1rem;'>48-Hour Forecast — "
                    "Carbon Intensity &amp; Electricity Price</div>", unsafe_allow_html=True)
        sigma = 0.05 + 0.005 * np.arange(len(CI))          # widening 95% band
        upper, lower = CI * (1 + sigma), CI * (1 - sigma)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=list(range(len(CI))), y=upper, mode="lines",
                                 line=dict(width=0), hoverinfo="skip", showlegend=False))
        fig.add_trace(go.Scatter(x=list(range(len(CI))), y=lower, mode="lines",
                                 line=dict(width=0), fill="tonexty",
                                 fillcolor="rgba(21,128,61,0.15)", hoverinfo="skip",
                                 name="Confidence Band (95%)"))
        fig.add_trace(go.Scatter(x=list(range(len(CI))), y=CI, mode="lines",
                                 line=dict(color=GREEN, width=3),
                                 name="Carbon Intensity (gCO₂/kWh)"))
        fig.add_trace(go.Scatter(x=list(range(len(PRICE))), y=PRICE, mode="lines", yaxis="y2",
                                 line=dict(color="#9aa5a0", width=1.5, dash="dash"),
                                 name="Electricity Price ($/MWh)"))
        fig.add_vline(x=clean_idx, line=dict(color=GREEN, dash="dash"),
                      annotation_text="Next clean window", annotation_position="top",
                      annotation=dict(bgcolor="white", font=dict(size=12)))
        fig.update_layout(
            height=400, margin=dict(l=10, r=10, t=75, b=10),
            xaxis=dict(title="Hours ahead", dtick=6),
            yaxis=dict(title="gCO₂/kWh"),
            yaxis2=dict(title="$/MWh", overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", y=1.25, x=0), plot_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
#  CSRD COMPLIANCE VIEW
# ══════════════════════════════════════════════════════════════════════════════

elif st.session_state.page == "csrd":
    st.markdown("<div class='page-title'>CSRD Compliance</div>", unsafe_allow_html=True)
    st.write("")

    def note_banner(text):
        st.markdown(
            f"<div style='background:#eef2f7;color:#000000;padding:10px 14px;"
            f"border-radius:8px;border-left:4px solid #1565C0;font-size:0.9rem;"
            f"margin-bottom:14px;'>ℹ️ {text}</div>", unsafe_allow_html=True)

    # ── derived figures used below ─────────────────────────────────────────────
    node_hours_5d = kpis["total_nodes"] * 24 * 5
    intensity_g_per_nodehour = kpis["total_baseline_kg_5d"] * 1000 / node_hours_5d

    monthly2 = monthly.copy()
    monthly2["year"] = monthly2["ym"].str[:4].astype(int)
    yearly_ci = monthly2.groupby("year")["carbon_intensity_gCO2_per_kWh"].mean()
    grid_trend_abs = yearly_ci.iloc[-1] - yearly_ci.iloc[0]
    grid_trend_pct = grid_trend_abs / yearly_ci.iloc[0] * 100

    # ══════════════════════════════════════════════════════════════════════════
    #  SECTION A · ORNL SUMMIT — FACILITY SAVINGS (5-DAY SAMPLE)
    # ══════════════════════════════════════════════════════════════════════════
    with st.container(border=True):
        st.markdown("<div class='section-h'>📋 ORNL Summit — Facility Savings "
                    "<span class='sub'>(5-Day Sample)</span></div>", unsafe_allow_html=True)
        note_banner(
            "These figures come from <b>5 observed ORNL Summit snapshot days</b> "
            "(2020-01-20, 2020-08-20, 2021-02-20, 2021-08-10, 2022-01-20 — 120 node-hours "
            "of per-node telemetry), matched against TVA grid carbon intensity for the same "
            "hours and projected to an annual figure. This is the facility's own demand-side "
            "savings potential from carbon-aware scheduling.")

        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(card("Projected Annual Saving", f"{kpis['annual_realistic_tco2']}", "tCO₂/yr",
                         sub="Realistic, forecast-driven", icon="🌱"), unsafe_allow_html=True)
        m2.markdown(card("Scope 2 Reduction", f"{kpis['reduction_pct']:.2f}", "%",
                         sub="5-day observed", icon="📉"), unsafe_allow_html=True)
        m3.markdown(card("Total Carbon Emission", f"{kpis['total_baseline_kg_5d']:,.0f}", "kg CO₂",
                         sub="As-is baseline, across all 5 sample days", icon="🏭",
                         info="Sum of baseline (as-is, unscheduled) emissions across all 120 "
                              "node-hours in the 5-day sample — the reference total that the "
                              "savings figures above are measured against."),
                   unsafe_allow_html=True)
        m4.markdown(card("Baseline Emissions Intensity", f"{intensity_g_per_nodehour:.0f}", "gCO₂/node-hr",
                         sub="Normalised — comparable across time/scale", icon="⚙️",
                         info="Total baseline emissions divided by total node-hours over the "
                              "5-day sample. An intensity ratio, not an absolute total, so it "
                              "stays comparable even if the facility's size or workload changes."),
                   unsafe_allow_html=True)

        # ── interactive: carbon savings vs assumed flexible-workload share ─────
        st.markdown("<div style='height:10px;'></div>"
                    "<div class='section-h' style='font-size:1.05rem;'>Carbon Savings by "
                    "Flexibility Assumption</div>", unsafe_allow_html=True)
        st.caption("Move the slider to see projected annual savings at a different assumed "
                  "flexible-workload share. 20–40% is the range actually validated in the "
                  "underlying analysis; 30% (default) is the central assumption used elsewhere "
                  "on this page.")
        flex_pct = st.slider("Assumed flexible-workload share", 20, 40, 30, step=5,
                             format="%d%%", key="flex_slider")
        scale = flex_pct / 30.0
        adj_unconstrained = kpis["annual_unconstrained_tco2"] * scale
        adj_ceiling = kpis["annual_ceiling_tco2"] * scale
        adj_realistic = kpis["annual_realistic_tco2"] * scale
        if flex_pct == 30:
            st.markdown(f"<div style='color:#000000;font-weight:700;font-size:1.05rem;'>"
                       f"At 30% (central assumption): <span style='color:#15803d;'>"
                       f"{adj_realistic:.0f} tCO₂/yr</span> realistic saving</div>",
                       unsafe_allow_html=True)
        else:
            st.markdown(f"<div style='color:#000000;font-weight:700;font-size:1.05rem;'>"
                       f"At {flex_pct}%: <span style='color:#15803d;'>{adj_realistic:.0f} tCO₂/yr</span> "
                       f"realistic saving <span style='font-weight:400;font-size:0.85rem;'>"
                       f"(vs {kpis['annual_realistic_tco2']} tCO₂/yr at the 30% central assumption)"
                       f"</span></div>", unsafe_allow_html=True)
        hier = pd.DataFrame({
            "Level": ["Unconstrained potential", "Capacity-aware ceiling", "Realistic forecast-driven"],
            "tCO2": [adj_unconstrained, adj_ceiling, adj_realistic],
        })
        fig = go.Figure(go.Bar(
            x=hier["tCO2"], y=hier["Level"], orientation="h",
            marker_color=[GREY, BLUE, GREEN],
            text=[f"{v:.0f} tCO₂/yr" for v in hier["tCO2"]], textposition="outside"))
        fig.update_layout(height=240, margin=dict(l=10, r=60, t=10, b=10),
                          xaxis=dict(title="tCO₂ / year", range=[0, kpis["annual_unconstrained_tco2"]*1.4]),
                          plot_bgcolor="white", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)
        if flex_pct != 30:
            st.caption("The unconstrained tier is scaled exactly (verified linear in the underlying "
                      "data across 20/30/40%). The capacity-aware and realistic tiers are scaled by "
                      "the same ratio as an illustrative approximation — they were not independently "
                      "re-run at this flexibility level, since that requires re-solving the "
                      "capacity-aware optimiser and forecast simulation from scratch.")

        # ── baseline vs optimised across the 5 observed days ────────────────────
        st.markdown("<div style='height:10px;'></div>"
                    "<div class='section-h' style='font-size:1.05rem;'>Baseline vs Optimised "
                    "Carbon Emissions — 5 Observed Days</div>", unsafe_allow_html=True)
        st.caption("Total carbon emitted on each sample day, as-is vs. carbon-aware scheduled.")
        byday = integ.groupby("snapshot_date").agg(
            baseline=("baseline_carbon_kg", "sum"),
            optimised=("optimized_carbon_kg", "sum")).reset_index()
        fig = go.Figure()
        fig.add_trace(go.Bar(x=byday["snapshot_date"], y=byday["baseline"],
                             name="Baseline", marker_color=RED))
        fig.add_trace(go.Bar(x=byday["snapshot_date"], y=byday["optimised"],
                             name="Optimised", marker_color=GREEN))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), barmode="group",
                          xaxis_title="Snapshot date", yaxis_title="Total carbon (kg CO₂)",
                          plot_bgcolor="white", legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig, use_container_width=True)

    st.write("")

    # ══════════════════════════════════════════════════════════════════════════
    #  SECTION B · TVA GRID — CARBON INTENSITY CONTEXT (2019–2022)
    # ══════════════════════════════════════════════════════════════════════════
    with st.container(border=True):
        st.markdown("<div class='section-h'>⚡ TVA Grid — Carbon Intensity Context "
                    "<span class='sub'>(2019–2022)</span></div>", unsafe_allow_html=True)
        note_banner(
            "These figures describe the <b>Tennessee Valley Authority (TVA) grid itself</b> "
            "— the electricity source ORNL Summit draws from — based on <b>4 years of hourly "
            "generation-by-fuel data</b> (Jan 2019 – Dec 2022) from the EIA. This is grid "
            "context, independent of ORNL's own workload or scheduling.")

        n1, n2, n3 = st.columns(3)
        n1.markdown(card("Avg Grid CI", f"{kpis['mean_ci']:.0f}", "gCO₂/kWh",
                         sub=f"{kpis['ci_min']:.0f}–{kpis['ci_max']:.0f} observed range", icon="☁️"),
                   unsafe_allow_html=True)
        n2.markdown(card("Low-Carbon Share", f"{kpis['low_carbon_share']:.0f}", "%",
                         sub="Nuclear + hydro + solar + wind", icon="🌿"), unsafe_allow_html=True)
        trend_arrow = "↓" if grid_trend_abs < 0 else "↑"
        n3.markdown(card("Grid Trend, 2019→2022", f"{trend_arrow} {abs(grid_trend_pct):.1f}", "%",
                         sub=f"{grid_trend_abs:+.1f} gCO₂/kWh net — non-monotonic (dipped in 2020)",
                         icon="📈",
                         info="Year-average carbon intensity fell in 2020, then partially "
                              "rebounded through 2022. Shown as the honest net change, not a "
                              "smoothed trend line."), unsafe_allow_html=True)

        cC, cD = st.columns(2)
        with cC:
            st.markdown("<div class='section-h' style='font-size:1.05rem;'>TVA Grid Energy Mix</div>",
                       unsafe_allow_html=True)
            st.caption("Share of generation by fuel, averaged across the full 2019–2022 period.")
            cmap = {"Nuclear": "#1565C0", "Natural Gas": "#FB8C00", "Coal": "#6D4C41",
                    "Hydro": "#00ACC1", "Solar": "#FDD835", "Wind": "#7CB342",
                    "Petroleum": "#E53935", "Other": "#9E9E9E"}
            fm = fuel[fuel["share"] > 0.05]
            fig = go.Figure(go.Pie(labels=fm["fuel"], values=fm["share"], hole=0.55,
                                   marker_colors=[cmap.get(f, GREY) for f in fm["fuel"]]))
            fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10),
                              showlegend=True, legend=dict(font=dict(size=10)))
            st.plotly_chart(fig, use_container_width=True)
        with cD:
            st.markdown("<div class='section-h' style='font-size:1.05rem;'>Fuel Mix Over Time</div>",
                       unsafe_allow_html=True)
            st.caption("Monthly generation share by fuel — shows the grid's own transition, "
                      "not just a single snapshot.")
            sig_fuels = [f for f in cmap if fuel_monthly[f].mean() > 0.5]
            fig = go.Figure()
            for f in sig_fuels:
                fig.add_trace(go.Scatter(x=fuel_monthly["ym"], y=fuel_monthly[f], mode="lines",
                                         stackgroup="one", name=f,
                                         line=dict(width=0.5, color=cmap.get(f, GREY))))
            fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10),
                              xaxis_title="Month", yaxis_title="Share of generation (%)",
                              plot_bgcolor="white", legend=dict(font=dict(size=9)),
                              xaxis=dict(tickmode="array",
                                        tickvals=fuel_monthly["ym"][::6].tolist()))
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("<div style='height:6px;'></div>"
                    "<div class='section-h' style='font-size:1.05rem;'>TVA Grid Carbon Intensity "
                    "— Monthly Trend</div>", unsafe_allow_html=True)
        fig = go.Figure(go.Scatter(x=monthly["ym"], y=monthly["carbon_intensity_gCO2_per_kWh"],
                        line=dict(color=BLUE, width=2), fill="tozeroy",
                        fillcolor="rgba(21,101,192,0.08)"))
        fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis_title="Month", yaxis_title="Mean CI (gCO₂/kWh)",
                          plot_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True)

    st.write("")

    # ── Footnote: methodology/audit detail moved off-page into a downloadable PDF ──
    st.markdown("---")
    fn1, fn2, fn3 = st.columns([3, 1, 1])
    fn1.markdown(
        "<div style='color:#000000;font-size:0.85rem;'>"
        "Reporting boundary, emission factors, and data-quality provenance are documented in "
        "the downloadable methodology &amp; audit trail below.</div>", unsafe_allow_html=True)
    methodology_pdf = DATA.parent.parent / "docs" / "report" / "CSRD_Methodology_Audit_Trail.pdf"
    if methodology_pdf.exists():
        fn2.download_button("📄 Methodology (PDF)", methodology_pdf.read_bytes(),
                            "CSRD_Methodology_Audit_Trail.pdf", "application/pdf",
                            use_container_width=True)
    csv = integ.to_csv(index=False).encode()
    fn3.download_button("📥 Audit data (CSV)", csv, "csrd_carbon_audit.csv", "text/csv",
                        use_container_width=True)


st.markdown("---")
st.caption("IS6611 Applied Research in Business Analytics · Group 11 · "
           "Data: ORNL Constellation + EIA API v2 · Built with Streamlit")
