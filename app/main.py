"""
Carbon-Aware Scheduling — Streamlit Dashboard

Two stakeholder views:
  • Operations Manager — live grid CI, 48h forecast, interactive job scheduler
  • CSRD Compliance    — carbon savings, audit-ready reporting

Self-contained: reads small precomputed files from app/data/ and runs a
numpy-only greedy scheduler. No heavy ML dependencies at runtime, so it
deploys cleanly on Streamlit Community Cloud.

Run locally:   streamlit run app/main.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

# ── Config & data loading ─────────────────────────────────────────────────────

DATA = Path(__file__).parent / "data"

st.set_page_config(
    page_title="Carbon-Aware Scheduling",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="collapsed",
)

GREEN = "#2E7D32"; BLUE = "#1565C0"; RED = "#C62828"
ORANGE = "#E65100"; GREY = "#607D8B"; AMBER = "#F9A825"


@st.cache_data
def load():
    kpis = json.load(open(DATA / "kpis.json"))
    integ = pd.read_csv(DATA / "integrated.csv")
    hourly = pd.read_csv(DATA / "ci_hourly.csv")
    monthly = pd.read_csv(DATA / "ci_monthly.csv")
    fuel = pd.read_csv(DATA / "fuel_mix.csv")
    window = pd.read_csv(DATA / "forecast_window.csv")
    return kpis, integ, hourly, monthly, fuel, window


kpis, integ, hourly, monthly, fuel, window = load()
CI = window["ci"].values  # representative 48h CI forecast


# ── Inline greedy scheduler (numpy only) ──────────────────────────────────────

def greedy_schedule(ci, nodes, duration, deadline, priority,
                    power_per_node=1.2, total_nodes=4626):
    """Return (start_hour, scheduled_ci, run_now_ci, carbon_saved_kg)."""
    energy = nodes * power_per_node * duration          # kWh
    run_now_ci = float(np.mean(ci[:duration]))
    if priority == "Urgent (run now)":
        return 0, run_now_ci, run_now_ci, 0.0
    latest = min(deadline, len(ci)) - duration
    if latest < 0:
        return 0, run_now_ci, run_now_ci, 0.0
    best_t, best_ci = 0, 1e9
    for t in range(0, latest + 1):
        m = float(np.mean(ci[t:t + duration]))
        if m < best_ci:
            best_ci, best_t = m, t
    saved_kg = energy * (run_now_ci - best_ci) / 1000   # g → kg
    return best_t, best_ci, run_now_ci, max(saved_kg, 0.0)


def zone(ci_value):
    if ci_value < 250: return GREEN, "🟢 Green"
    if ci_value < 350: return AMBER, "🟡 Amber"
    return RED, "🔴 Red"


# ── Header ────────────────────────────────────────────────────────────────────

st.markdown(
    f"<h1 style='margin-bottom:0;'>🌱 Carbon-Aware Scheduling for Data Centres</h1>"
    f"<p style='color:#607D8B;font-size:1.05rem;margin-top:4px;'>"
    f"Shift delay-tolerant workloads into low-carbon windows — zero hardware cost · "
    f"validated on ORNL Summit × TVA grid data</p>",
    unsafe_allow_html=True,
)

tab_ops, tab_csrd = st.tabs(["⚙️  Operations Manager", "📋  CSRD Compliance"])


# ══════════════════════════════════════════════════════════════════════════════
#  OPERATIONS MANAGER VIEW
# ══════════════════════════════════════════════════════════════════════════════

with tab_ops:
    current_ci = float(CI[0])
    forecast_low = float(CI.min())
    low_hour = int(CI.argmin())
    active_nodes = int(kpis["total_nodes"] * kpis["mean_utilisation_pct"] / 100)

    c1, c2, c3, c4 = st.columns(4)
    zc, zlabel = zone(current_ci)
    c1.metric("Current Grid CI", f"{current_ci:.0f} gCO₂/kWh", zlabel)
    c2.metric("Forecasted Low", f"{forecast_low:.0f} gCO₂/kWh", f"at hour +{low_hour}")
    c3.metric("Active Nodes", f"{active_nodes:,}", f"of {kpis['total_nodes']:,}")
    c4.metric("Mean Utilisation", f"{kpis['mean_utilisation_pct']:.0f}%", "cluster load")

    st.markdown("##### 48-Hour Carbon Intensity Forecast")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(len(CI))), y=CI, mode="lines",
        line=dict(color=BLUE, width=3), name="Forecast CI",
        fill="tozeroy", fillcolor="rgba(21,101,192,0.08)"))
    # zone bands
    fig.add_hrect(y0=0, y1=250, fillcolor=GREEN, opacity=0.06, line_width=0,
                  annotation_text="Green <250", annotation_position="top left")
    fig.add_hrect(y0=250, y1=350, fillcolor=AMBER, opacity=0.06, line_width=0,
                  annotation_text="Amber 250–350", annotation_position="top left")
    fig.add_hrect(y0=350, y1=max(CI.max()*1.05, 400), fillcolor=RED, opacity=0.06,
                  line_width=0, annotation_text="Red >350", annotation_position="top left")
    fig.add_vline(x=low_hour, line=dict(color=GREEN, dash="dash"),
                  annotation_text=f"cleanest +{low_hour}h")
    fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_title="Hours ahead", yaxis_title="gCO₂/kWh",
                      showlegend=False, plot_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True)

    # ── Interactive job scheduler ─────────────────────────────────────────────
    st.markdown("##### 🗓️  Schedule a Job")
    st.caption("Enter your workload and the optimiser returns the lowest-carbon start time within your deadline.")
    jc1, jc2, jc3, jc4 = st.columns(4)
    nodes = jc1.number_input("Nodes required", 1, kpis["total_nodes"], 2000, step=100)
    duration = jc2.number_input("Duration (hours)", 1, 24, 4)
    deadline = jc3.selectbox("Deadline", [6, 12, 24, 48], index=2,
                             format_func=lambda h: f"within {h} hours")
    priority = jc4.selectbox("Priority", ["Flexible", "Urgent (run now)"])

    start, sched_ci, run_now_ci, saved = greedy_schedule(
        CI, nodes, duration, deadline, priority)

    r1, r2, r3 = st.columns(3)
    r1.metric("Recommended Start", f"+{start} h" if start else "Now",
              f"CI {sched_ci:.0f} gCO₂/kWh")
    r2.metric("vs Running Now", f"CI {run_now_ci:.0f} gCO₂/kWh",
              f"{run_now_ci - sched_ci:.0f} cleaner", delta_color="inverse")
    r3.metric("Estimated Carbon Saved", f"{saved:,.1f} kg CO₂",
              f"{(saved*1000/(nodes*1.2*duration*run_now_ci)*100) if run_now_ci else 0:.1f}%")

    if priority == "Urgent (run now)":
        st.info("⚡ Urgent jobs run immediately and are never deferred.")
    elif saved > 0:
        st.success(f"✅ Defer this job by **{start} hours** to run in a cleaner window "
                   f"and save **{saved:,.1f} kg CO₂** with no change to the computation.")
    else:
        st.warning("This job is already in the cleanest available window — run now.")


# ══════════════════════════════════════════════════════════════════════════════
#  CSRD COMPLIANCE VIEW
# ══════════════════════════════════════════════════════════════════════════════

with tab_csrd:
    st.caption("Reporting period: 5 observed ORNL Summit days · TVA grid 2019–2022 · IPCC AR5 emission factors")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Projected Annual Saving", f"{kpis['annual_realistic_tco2']} tCO₂/yr",
              "realistic, forecast-driven")
    c2.metric("Scope 2 Reduction", f"{kpis['reduction_pct']:.2f}%", "5-day observed")
    c3.metric("Avg Grid CI", f"{kpis['mean_ci']:.0f} gCO₂/kWh",
              f"{kpis['ci_min']:.0f}–{kpis['ci_max']:.0f} range")
    c4.metric("Low-Carbon Share", f"{kpis['low_carbon_share']:.0f}%", "nuclear + hydro + solar")

    left, right = st.columns([3, 2])

    # ── Savings hierarchy ─────────────────────────────────────────────────────
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

    # ── Fuel mix donut ────────────────────────────────────────────────────────
    with right:
        st.markdown("##### TVA Grid Energy Mix")
        cmap = {"Nuclear":"#1565C0","Natural Gas":"#FB8C00","Coal":"#6D4C41",
                "Hydro":"#00ACC1","Solar":"#FDD835","Wind":"#7CB342",
                "Petroleum":"#E53935","Other":"#9E9E9E"}
        fm = fuel[fuel["share"] > 0.05]
        fig = go.Figure(go.Pie(labels=fm["fuel"], values=fm["share"], hole=0.55,
                               marker_colors=[cmap.get(f, GREY) for f in fm["fuel"]]))
        fig.update_layout(height=240, margin=dict(l=10, r=10, t=10, b=10),
                          showlegend=True, legend=dict(font=dict(size=10)))
        st.plotly_chart(fig, use_container_width=True)

    # ── Baseline vs optimised hourly ──────────────────────────────────────────
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

    # ── Monthly CI trend ──────────────────────────────────────────────────────
    st.markdown("##### TVA Grid Carbon Intensity — Monthly Trend (2019–2022)")
    fig = go.Figure(go.Scatter(x=monthly["ym"], y=monthly["carbon_intensity_gCO2_per_kWh"],
                    line=dict(color=BLUE, width=2), fill="tozeroy",
                    fillcolor="rgba(21,101,192,0.08)"))
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_title="Month", yaxis_title="Mean CI (gCO₂/kWh)",
                      plot_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True)

    # ── Audit export ──────────────────────────────────────────────────────────
    st.markdown("##### 📥 Audit-Ready Export")
    csv = integ.to_csv(index=False).encode()
    st.download_button("Download carbon audit report (CSV)", csv,
                       "csrd_carbon_audit.csv", "text/csv")
    st.caption("Methodology: IPCC AR5 lifecycle emission factors · capacity-aware load-shifting LP · "
               "30% flexible-workload assumption (sensitivity 20–40%).")


st.markdown("---")
st.caption("IS6611 Applied Research in Business Analytics · Group 11 · "
           "Data: ORNL Constellation + EIA API v2 · Built with Streamlit")
