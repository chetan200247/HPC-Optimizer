"""
Carbon-Aware Scheduling — Streamlit Dashboard

Two stakeholder views (sidebar nav):
  • Operations Manager — live grid CI, 48h forecast, interactive job scheduler
  • CSRD Compliance    — carbon savings, audit-ready reporting

Self-contained: reads small precomputed files from app/data/ and runs a
numpy-only greedy scheduler. No heavy ML dependencies at runtime, so it
deploys cleanly on Streamlit Community Cloud.

Run locally:   streamlit run app/main.py
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
import streamlit as st

try:                                  # optional: load .env for local runs
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ── Config & palette ──────────────────────────────────────────────────────────

DATA = Path(__file__).parent / "data"

st.set_page_config(
    page_title="Carbon-Aware Scheduling",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Primary palette (extracted to match the mock design)
GREEN   = "#15803D"   # primary green — CI line, positive metrics
GREEN_L = "#16A34A"   # brighter accent (buttons)
BLUE    = "#1565C0"
RED     = "#C62828"
ORANGE  = "#E65100"
GREY    = "#607D8B"
AMBER   = "#F9A825"


# ── Global styling ────────────────────────────────────────────────────────────

st.markdown("""
<style>
  .block-container {padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1560px;}
  [data-testid="stAppViewContainer"] {background: #f5f8f6;}

  /* Sidebar — dark green */
  section[data-testid="stSidebar"] {background: #0c2a1a;}
  section[data-testid="stSidebar"] * {color: #e8f0ea;}
  section[data-testid="stSidebar"] button[kind="primary"] {
      background:#16a34a; border:none; color:#fff; font-weight:600; text-align:left;
      justify-content:flex-start; border-radius:10px;}
  section[data-testid="stSidebar"] button[kind="secondary"] {
      background:transparent; border:none; color:#bcd5c5; font-weight:500; text-align:left;
      justify-content:flex-start; border-radius:10px;}
  section[data-testid="stSidebar"] button[kind="secondary"]:hover {background:#123d27;}

  /* Green primary buttons in the main area */
  [data-testid="stAppViewContainer"] button[kind="primary"] {background:#16a34a; border-color:#16a34a;}

  /* Page header */
  .page-title {font-size:1.9rem; font-weight:800; color:#12261c; line-height:1.1;}
  .page-sub {font-size:0.95rem; color:#5b6b62; margin-top:2px;}
  .fresh {text-align:right; font-size:0.82rem; color:#5b6b62; font-weight:600;}
  .fresh-dot {height:8px; width:8px; border-radius:50%; background:#22c55e;
              display:inline-block; margin-right:6px;}

  /* Metric cards */
  .metric-card {background:#fff; border:1px solid #e6ebe8; border-radius:14px;
                padding:16px 18px; box-shadow:0 1px 3px rgba(0,0,0,0.04); height:100%;}
  .mc-label {font-size:0.82rem; color:#5b6b62; font-weight:600;
             display:flex; gap:6px; align-items:center;}
  .mc-value {font-weight:800; color:#12261c; line-height:1.1; margin-top:8px;}
  .mc-unit  {font-size:0.9rem; color:#5b6b62; font-weight:600;}
  .mc-sub   {font-size:0.78rem; color:#7a8a80; margin-top:8px;}
  .up {color:#15803d; font-weight:700;}

  .badge {display:inline-block; padding:2px 12px; border-radius:999px;
          font-size:0.74rem; font-weight:700; margin-top:10px;}
  .badge-green {background:#dcfce7; color:#15803d;}
  .badge-amber {background:#fef3c7; color:#b45309;}
  .badge-red   {background:#fee2e2; color:#b91c1c;}

  .tg-num {font-size:1.3rem; font-weight:800; color:#12261c; line-height:1.1;}
  .tg-lbl {font-size:0.72rem; color:#5b6b62; margin-top:2px;}

  /* Recommended-schedule table */
  .rec-table {width:100%; border-collapse:collapse; font-size:0.85rem;}
  .rec-table th {text-align:left; color:#5b6b62; font-weight:600;
                 padding:10px 8px; border-bottom:1px solid #e6ebe8; white-space:nowrap;}
  .rec-table td {padding:11px 8px; border-bottom:1px solid #f0f3f1; color:#22332a;}
  .status-dot {height:8px; width:8px; border-radius:50%; display:inline-block; margin-right:6px;}
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
    window = pd.read_csv(DATA / "forecast_window.csv")
    return kpis, integ, hourly, monthly, fuel, window


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


def fetch_live_window(hours=48, timeout=10):
    """
    Pull the latest TVA hourly generation-by-fuel from the EIA API, convert it to
    carbon intensity (gCO₂/kWh), and build a 48h forward window using a
    daily-persistence profile (the documented scheduling driver). Prices are the
    representative ToU tariff. Raises on any failure so the caller can fall back.
    """
    key = _eia_key()
    if not key:
        raise RuntimeError("EIA_API_KEY not configured")
    end = pd.Timestamp.now(tz="UTC").tz_localize(None).floor("h")
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
    # daily-persistence: most recent CI observed at each hour-of-day (UTC)
    by_hour = ci_series.groupby(ci_series.index.hour).last()
    now_utc_h = pd.Timestamp.now(tz="UTC").hour
    now_local = pd.Timestamp.now()
    rows = []
    for t in range(hours):
        ci_t = float(by_hour.get((now_utc_h + t) % 24, by_hour.mean()))
        ts = now_local + pd.Timedelta(hours=t)
        rows.append({"datetime": ts, "ci": ci_t, "price": _tou_price(ts)})
    return pd.DataFrame(rows)


@st.cache_data(show_spinner="Fetching live TVA grid data…")
def get_window(refresh_token):
    """Cached on the refresh timestamp: only a Refresh re-hits the network."""
    try:
        return fetch_live_window(), "live"
    except Exception as exc:
        return pd.read_csv(DATA / "forecast_window.csv"), f"static:{type(exc).__name__}"


kpis, integ, hourly, monthly, fuel, _static = load()

# Live "data as of" anchor — set on first load, re-stamped by the Refresh button.
# The 48h forecast horizon is anchored to this timestamp, so clock times (next
# green window, recommended start) read relative to the moment of refresh.
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = pd.Timestamp.now()
NOW = st.session_state.last_refresh

window, DATA_SOURCE = get_window(st.session_state.last_refresh)
CI = window["ci"].values
PRICE = window["price"].values if "price" in window.columns else np.full(len(CI), 40.0)


# ── Formatting helpers ────────────────────────────────────────────────────────

def fmt_clock(dt):
    """'Sat, 3:00 PM' — no leading zero, platform-independent."""
    return dt.strftime("%a, ") + dt.strftime("%I:%M %p").lstrip("0")


def fmt_stamp(dt):
    return dt.strftime("%d %b %Y, ") + dt.strftime("%I:%M %p").lstrip("0")


# ── Scheduler (numpy only — logic unchanged) ──────────────────────────────────

def zone(ci_value):
    if ci_value < 250: return GREEN, "🟢 Green"
    if ci_value < 350: return AMBER, "🟡 Amber"
    return RED, "🔴 Red"


def schedule_queue(jobs, ci, price, weight, total_nodes, power_per_node=1.2):
    """
    Batch scheduler. Places a whole queue — urgent first (never deferred), then
    flexible by descending energy — into the lowest blended carbon/cost window
    within each deadline, committing node capacity as it goes. A single job is a
    queue of one. Returns per-job results + the hourly node-occupancy array.
    """
    H = len(ci)
    cap = np.zeros(H)

    def norm(a):
        a = np.asarray(a, float); rng = a.max() - a.min()
        return (a - a.min()) / rng if rng > 1e-9 else np.zeros_like(a)
    ci_n, pr_n = norm(ci), norm(price)

    order = sorted(range(len(jobs)),
                   key=lambda i: (not jobs[i]["priority"].startswith("Urgent"),
                                  -(jobs[i]["nodes"] * jobs[i]["duration"])))
    results = [None] * len(jobs)
    for i in order:
        j = jobs[i]; nodes, dur, dl = j["nodes"], j["duration"], j["deadline"]
        urgent = j["priority"].startswith("Urgent")
        energy_kwh = nodes * power_per_node * dur
        run_ci = float(np.mean(ci[:dur])); run_pr = float(np.mean(price[:dur]))

        if urgent:
            start = 0
        else:
            latest = min(dl, H) - dur
            start, best, found = 0, float("inf"), False
            for t in range(0, max(latest, 0) + 1):
                if np.all(cap[t:t + dur] + nodes <= total_nodes):
                    s = weight * float(np.mean(ci_n[t:t + dur])) + \
                        (1 - weight) * float(np.mean(pr_n[t:t + dur]))
                    if s < best:
                        best, start, found = s, t, True
            if not found:
                start = 0
        cap[start:start + dur] += nodes
        sci = float(np.mean(ci[start:start + dur])); spr = float(np.mean(price[start:start + dur]))
        results[i] = dict(
            idx=i, name=j.get("name", ""), nodes=nodes, duration=dur,
            priority=j["priority"], start=start, sched_ci=sci, sched_price=spr,
            run_ci=run_ci, run_pr=run_pr,
            carbon_saved_kg=energy_kwh * (run_ci - sci) / 1000,
            cost_saved_usd=(energy_kwh / 1000) * (run_pr - spr))
    return results, cap


# ── HTML card builder ─────────────────────────────────────────────────────────

def card(label, value, unit="", sub="", badge=None, badge_cls="badge-green",
         icon="", value_size="1.9rem"):
    b = f'<div class="badge {badge_cls}">{badge}</div>' if badge else ""
    s = f'<div class="mc-sub">{sub}</div>' if sub else ""
    u = f'<span class="mc-unit">{unit}</span>' if unit else ""
    return (f'<div class="metric-card"><div class="mc-label">{icon} {label}</div>'
            f'<div class="mc-value" style="font-size:{value_size};">{value} {u}</div>'
            f'{b}{s}</div>')


# ── Sidebar navigation ────────────────────────────────────────────────────────

if "page" not in st.session_state:
    st.session_state.page = "ops"

st.sidebar.markdown(
    "<div style='display:flex;align-items:center;gap:10px;padding:6px 4px 18px 4px;'>"
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
    "<div style='color:#bcd5c5;font-size:0.85rem;margin-top:4px;'>Schedule smart. Reduce carbon.</div>"
    "<hr style='border-color:#1e5236;margin:12px 0;'>"
    "<div style='color:#9dc2ac;font-size:0.78rem;'>Sustainable. Efficient. Responsible.</div>"
    "</div>", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  OPERATIONS MANAGER VIEW
# ══════════════════════════════════════════════════════════════════════════════

if st.session_state.page == "ops":

    # ── Header ────────────────────────────────────────────────────────────────
    h1, h2 = st.columns([6, 3])
    with h1:
        st.markdown(
            "<div class='page-title'>Operations Manager</div>"
            "<div class='page-sub'>Real-time overview of grid conditions, forecasts and job scheduling</div>",
            unsafe_allow_html=True)
    with h2:
        if DATA_SOURCE == "live":
            src = "<span style='color:#15803d;font-weight:700;'>Live · EIA</span>"; dot = "background:#22c55e;"
        else:
            src = "<span style='color:#b45309;font-weight:700;'>Demo data</span>"; dot = "background:#f59e0b;"
        st.markdown(
            f"<div class='fresh'><span class='fresh-dot' style='{dot}'></span>"
            f"Data as of {fmt_stamp(NOW)} · {src}</div>", unsafe_allow_html=True)
        if st.button("🔄 Refresh", key="refresh"):
            st.session_state.last_refresh = pd.Timestamp.now()
            st.cache_data.clear(); st.rerun()

    st.write("")

    # ══════════════════════════════════════════════════════════════════════════
    #  SCHEDULE JOBS — the hero panel
    # ══════════════════════════════════════════════════════════════════════════
    with st.container(border=True):
        t1, t2 = st.columns([5, 4])
        with t1:
            st.markdown("### 🗓️ Schedule Jobs")
            st.caption("Add jobs to the queue. The system recommends the best start time to "
                       "reduce carbon without violating deadlines.")
        with t2:
            opt = st.slider("Optimise for  —  🌿 Carbon  ⟷  Cost 💲", 0, 100, 20, step=5,
                            format="%d%%",
                            help="Slide left for more carbon savings, right for more cost savings.")
            weight = (100 - opt) / 100.0   # carbon weight
            st.caption(f"⬅ More carbon savings  ·  **{100-opt}% carbon / {opt}% cost**  ·  "
                       f"More cost savings ➡")

        if "queue" not in st.session_state:
            st.session_state.queue = pd.DataFrame([
                {"Job Name": "Weather Simulations", "Nodes": 2000, "Duration (h)": 4,
                 "Deadline (h)": 12, "Priority": "Flexible"},
                {"Job Name": "ML Model Training", "Nodes": 2343, "Duration (h)": 24,
                 "Deadline (h)": 48, "Priority": "Urgent (run now)"},
            ])

        edited = st.data_editor(
            st.session_state.queue, num_rows="dynamic", use_container_width=True, key="qeditor",
            column_config={
                "Job Name": st.column_config.TextColumn(width="medium",
                                                        help="A label for the job (optional)"),
                "Nodes": st.column_config.NumberColumn("Nodes (required)", min_value=1,
                                                       max_value=kpis["total_nodes"], step=100),
                "Duration (h)": st.column_config.NumberColumn(min_value=1, max_value=24, step=1),
                "Deadline (h)": st.column_config.NumberColumn("Deadline (h)", min_value=1,
                                                              max_value=48, step=1,
                                                              help="Must finish within this many hours"),
                "Priority": st.column_config.SelectboxColumn(
                    options=["Flexible", "Urgent (run now)"], required=True),
            })
        st.caption("Use the **＋** on the last row to add another job, or the 🗑 to remove one.")

        # validate rows
        jobs = []
        for _, r in edited.iterrows():
            try:
                n = int(r["Nodes"]); d = int(r["Duration (h)"]); dl = int(r["Deadline (h)"])
                p = str(r["Priority"]); nm = str(r["Job Name"]) if pd.notna(r["Job Name"]) else ""
            except (TypeError, ValueError):
                continue
            if n >= 1 and d >= 1 and dl >= d:
                jobs.append(dict(name=nm, nodes=n, duration=d, deadline=dl, priority=p))

        # schedule
        if jobs:
            results, cap = schedule_queue(jobs, CI, PRICE, weight, kpis["total_nodes"])
        else:
            results, cap = [], np.zeros(len(CI))

        tot_kg = sum(r["carbon_saved_kg"] for r in results)
        tot_usd = sum(r["cost_saved_usd"] for r in results)
        flex = [r for r in results if not r["priority"].startswith("Urgent")]
        urgent = [r for r in results if r["priority"].startswith("Urgent")]
        deferred = sum(1 for r in flex if r["start"] > 0)
        avg_wait = np.mean([r["start"] for r in flex]) if flex else 0
        max_wait = max([r["start"] for r in flex], default=0)
        on_time = sum(1 for r in urgent if r["start"] == 0)
        on_time_rate = (on_time / len(urgent) * 100) if urgent else 100

        # summary cards
        st.write("")
        m1, m2, m3 = st.columns(3)
        m1.markdown(card("Total Carbon Saved", f"{tot_kg:,.0f}", "kg CO₂",
                         sub="<span class='up'>↑</span> vs run-now", icon="🌿"),
                    unsafe_allow_html=True)
        m2.markdown(card("Total Cost Saved", f"${tot_usd:,.0f}", "",
                         sub="<span class='up'>↑</span> vs run-now", icon="💲"),
                    unsafe_allow_html=True)
        m3.markdown(card("Urgent On-Time Rate", f"{on_time_rate:.0f}%", "",
                         sub=f"{on_time} of {len(urgent)} urgent jobs on time" if urgent
                         else "no urgent jobs queued", icon="🛡️"),
                    unsafe_allow_html=True)

        # recommended schedule table
        if results:
            st.markdown("##### Recommended Schedule")
            rows = ""
            for r in sorted(results, key=lambda r: r["idx"]):
                urg = r["priority"].startswith("Urgent")
                if r["start"] == 0:
                    start_html = "<b style='color:#b45309;'>Run Now</b>" if urg \
                        else "<b style='color:#15803d;'>Now</b>"
                else:
                    t = NOW + pd.Timedelta(hours=r["start"])
                    start_html = f"<b style='color:#15803d;'>{fmt_clock(t)}</b> (+{r['start']}h)"
                status = ("<span class='status-dot' style='background:#f59e0b;'></span>Running" if urg
                          else "<span class='status-dot' style='background:#22c55e;'></span>Scheduled")
                name = r["name"] or f"Job {r['idx']+1}"
                rows += (f"<tr><td>{name}</td><td>{r['nodes']:,}</td><td>{r['duration']}</td>"
                         f"<td>{'Urgent (run now)' if urg else 'Flexible'}</td><td>{start_html}</td>"
                         f"<td>{r['carbon_saved_kg']:,.0f} kg CO₂</td><td>${r['cost_saved_usd']:,.0f}</td>"
                         f"<td>{status}</td></tr>")
            st.markdown(
                "<div style='overflow-x:auto;'><table class='rec-table'><thead><tr>"
                "<th>Job</th><th>Nodes</th><th>Duration (h)</th><th>Priority</th>"
                "<th>Recommended Start</th><th>Carbon Saved</th><th>Cost Saved</th><th>Status</th>"
                "</tr></thead><tbody>" + rows + "</tbody></table></div>",
                unsafe_allow_html=True)
        else:
            st.info("Add at least one valid job (deadline must be ≥ duration).")

    st.write("")

    # ── Grid status snapshot ──────────────────────────────────────────────────
    current_ci = float(CI[0])
    if current_ci < 250:   z_cls, z_lab, z_sub = "badge-green", "Green", "Low carbon intensity"
    elif current_ci < 350: z_cls, z_lab, z_sub = "badge-amber", "Amber", "Moderate carbon intensity"
    else:                  z_cls, z_lab, z_sub = "badge-red", "Red", "High carbon intensity"

    price_now = float(PRICE[0])
    q1, q2 = np.quantile(PRICE, [1/3, 2/3])
    if price_now <= q1:   p_tier, p_cls, p_lab = 1, "badge-green", "Low Tier"
    elif price_now <= q2: p_tier, p_cls, p_lab = 2, "badge-amber", "Mid Tier"
    else:                 p_tier, p_cls, p_lab = 3, "badge-red", "High Tier"

    # next green window
    thr = 250 if CI.min() < 250 else float(np.percentile(CI, 20))
    green_idx = int(np.argmax(CI < thr)) if (CI < thr).any() else int(CI.argmin())
    gw_dur = 0
    for h in range(green_idx, len(CI)):
        if CI[h] < thr: gw_dur += 1
        else: break
    gw_time = NOW + pd.Timedelta(hours=green_idx)

    active = int(kpis["total_nodes"] * kpis["mean_utilisation_pct"] / 100)
    idle = kpis["total_nodes"] - active
    act_pct = round(kpis["mean_utilisation_pct"]); idle_pct = 100 - act_pct

    left, right = st.columns([1.15, 1])

    # ── 48-hour forecast (left, tall) ─────────────────────────────────────────
    with left:
        with st.container(border=True):
            st.markdown("##### 48-Hour Forecast — Carbon Intensity & Electricity Price")
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
            fig.add_vline(x=green_idx, line=dict(color=GREEN, dash="dash"),
                          annotation_text="Next green window", annotation_position="top")
            fig.update_layout(
                height=430, margin=dict(l=10, r=10, t=30, b=10),
                xaxis=dict(title="Hours ahead", dtick=6),
                yaxis=dict(title="gCO₂/kWh"),
                yaxis2=dict(title="$/MWh", overlaying="y", side="right", showgrid=False),
                legend=dict(orientation="h", y=1.12, x=0), plot_bgcolor="white")
            st.plotly_chart(fig, use_container_width=True)

    # ── Status cards (right) ──────────────────────────────────────────────────
    with right:
        a, b, c = st.columns(3)
        a.markdown(card("Current Grid CI", f"{current_ci:.0f}", "gCO₂/kWh",
                        badge=z_lab, badge_cls=z_cls, sub=z_sub, icon="☁️",
                        value_size="1.5rem"), unsafe_allow_html=True)
        b.markdown(card("Electricity Price", f"${price_now:.2f}", "/MWh",
                        badge=p_lab, badge_cls=p_cls, sub=f"Price tier: {p_tier} of 3",
                        icon="💷", value_size="1.5rem"), unsafe_allow_html=True)
        c.markdown(card("Next Green Window", fmt_clock(gw_time).split(", ")[1], "",
                        sub=f"in {green_idx}h ({gw_dur}h window)", icon="🌱",
                        value_size="1.35rem"), unsafe_allow_html=True)

        st.write("")
        d, e = st.columns([1, 1.4])
        d.markdown(
            "<div class='metric-card'><div class='mc-label'>🗄️ Cluster Capacity</div>"
            "<div style='display:flex;gap:16px;margin-top:14px;'>"
            f"<div><div class='tg-num'>{kpis['total_nodes']:,}</div><div class='tg-lbl'>Working</div></div>"
            f"<div><div class='tg-num' style='color:#15803d;'>{active:,}</div>"
            f"<div class='tg-lbl'>Active {act_pct}%</div></div>"
            f"<div><div class='tg-num'>{idle:,}</div><div class='tg-lbl'>Idle {idle_pct}%</div></div>"
            "</div></div>", unsafe_allow_html=True)
        e.markdown(
            "<div class='metric-card'><div class='mc-label'>📊 Today at a Glance</div>"
            "<div style='display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-top:14px;'>"
            f"<div><div class='tg-num'>{deferred}</div><div class='tg-lbl'>Jobs Deferred</div></div>"
            f"<div><div class='tg-num'>{avg_wait:.0f} / {max_wait} h</div><div class='tg-lbl'>Avg / Max Wait</div></div>"
            f"<div><div class='tg-num'>{on_time_rate:.0f}%</div><div class='tg-lbl'>Urgent On-Time</div></div>"
            f"<div><div class='tg-num' style='color:#15803d;'>{tot_kg:,.0f}</div><div class='tg-lbl'>Carbon Saved (kg)</div></div>"
            f"<div><div class='tg-num' style='color:#15803d;'>${tot_usd:,.0f}</div><div class='tg-lbl'>Cost Saved</div></div>"
            "</div></div>", unsafe_allow_html=True)

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    st.caption("Confidence band and Time-of-Use electricity price are representative model outputs "
               "(see src/models/pricing.py). Clean and cheap hours often but not always coincide — "
               "the optimiser balances the two via the slider above.")


# ══════════════════════════════════════════════════════════════════════════════
#  CSRD COMPLIANCE VIEW
# ══════════════════════════════════════════════════════════════════════════════

elif st.session_state.page == "csrd":
    st.markdown(
        "<div class='page-title'>CSRD Compliance</div>"
        "<div class='page-sub'>Carbon savings & audit-ready reporting</div>",
        unsafe_allow_html=True)
    st.caption("Reporting period: 5 observed ORNL Summit days · TVA grid 2019–2022 · IPCC AR5 emission factors")
    st.write("")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Projected Annual Saving", f"{kpis['annual_realistic_tco2']} tCO₂/yr",
              "realistic, forecast-driven")
    c2.metric("Scope 2 Reduction", f"{kpis['reduction_pct']:.2f}%", "5-day observed")
    c3.metric("Avg Grid CI", f"{kpis['mean_ci']:.0f} gCO₂/kWh",
              f"{kpis['ci_min']:.0f}–{kpis['ci_max']:.0f} range")
    c4.metric("Low-Carbon Share", f"{kpis['low_carbon_share']:.0f}%", "nuclear + hydro + solar")

    left, right = st.columns([3, 2])

    with left:
        st.markdown("##### Carbon Savings Hierarchy")
        st.caption("From theoretical potential to realistic achievable — each constraint reduces the saving.")
        hier = pd.DataFrame({
            "Level": ["Unconstrained potential", "Capacity-aware ceiling", "Realistic forecast-driven"],
            "tCO2": [kpis["annual_unconstrained_tco2"], kpis["annual_ceiling_tco2"], kpis["annual_realistic_tco2"]],
        })
        fig = go.Figure(go.Bar(
            x=hier["tCO2"], y=hier["Level"], orientation="h",
            marker_color=[GREY, BLUE, GREEN],
            text=[f"{v} tCO₂/yr" for v in hier["tCO2"]], textposition="outside"))
        fig.update_layout(height=240, margin=dict(l=10, r=40, t=10, b=10),
                          xaxis_title="tCO₂ / year", plot_bgcolor="white",
                          yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, use_container_width=True)

    with right:
        st.markdown("##### TVA Grid Energy Mix")
        cmap = {"Nuclear": "#1565C0", "Natural Gas": "#FB8C00", "Coal": "#6D4C41",
                "Hydro": "#00ACC1", "Solar": "#FDD835", "Wind": "#7CB342",
                "Petroleum": "#E53935", "Other": "#9E9E9E"}
        fm = fuel[fuel["share"] > 0.05]
        fig = go.Figure(go.Pie(labels=fm["fuel"], values=fm["share"], hole=0.55,
                               marker_colors=[cmap.get(f, GREY) for f in fm["fuel"]]))
        fig.update_layout(height=240, margin=dict(l=10, r=10, t=10, b=10),
                          showlegend=True, legend=dict(font=dict(size=10)))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### Baseline vs Optimised Emissions — by Hour of Day")
    byhr = integ.groupby("hour_of_day").agg(
        baseline=("baseline_carbon_kg", "mean"),
        optimised=("optimized_carbon_kg", "mean")).reset_index()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=byhr["hour_of_day"], y=byhr["baseline"],
                  name="Baseline", line=dict(color=RED, width=2),
                  fill="tozeroy", fillcolor="rgba(198,40,40,0.08)"))
    fig.add_trace(go.Scatter(x=byhr["hour_of_day"], y=byhr["optimised"],
                  name="Optimised", line=dict(color=GREEN, width=2)))
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_title="Hour of day", yaxis_title="Avg carbon (kg CO₂)",
                      plot_bgcolor="white", legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### TVA Grid Carbon Intensity — Monthly Trend (2019–2022)")
    fig = go.Figure(go.Scatter(x=monthly["ym"], y=monthly["carbon_intensity_gCO2_per_kWh"],
                    line=dict(color=BLUE, width=2), fill="tozeroy",
                    fillcolor="rgba(21,101,192,0.08)"))
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_title="Month", yaxis_title="Mean CI (gCO₂/kWh)",
                      plot_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("##### 📥 Audit-Ready Export")
    csv = integ.to_csv(index=False).encode()
    st.download_button("Download carbon audit report (CSV)", csv,
                       "csrd_carbon_audit.csv", "text/csv")
    st.caption("Methodology: IPCC AR5 lifecycle emission factors · capacity-aware load-shifting LP · "
               "30% flexible-workload assumption (sensitivity 20–40%).")


st.markdown("---")
st.caption("IS6611 Applied Research in Business Analytics · Group 11 · "
           "Data: ORNL Constellation + EIA API v2 · Built with Streamlit")
