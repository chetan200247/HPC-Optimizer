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
# Representative Time-of-Use electricity price ($/MWh); modelled, see src/models/pricing.py
PRICE = window["price"].values if "price" in window.columns else np.full(len(CI), 40.0)


# ── Inline joint carbon + cost scheduler (numpy only) ─────────────────────────

def joint_schedule(ci, price, nodes, duration, deadline, priority, weight,
                   power_per_node=1.2):
    """
    Schedule a job optimising a weighted blend of carbon and cost.

    weight = 1.0 → pure carbon · 0.0 → pure cost · 0.5 → balanced.
    Carbon and price are on different scales, so each is normalised to [0, 1]
    across the forecast horizon before blending.

    Returns a dict with the chosen start hour, the CI and price at that window
    versus running now, and the carbon (kg CO₂) and cost ($) saved.
    """
    energy_kwh = nodes * power_per_node * duration
    energy_mwh = energy_kwh / 1000.0
    run_ci = float(np.mean(ci[:duration]))
    run_pr = float(np.mean(price[:duration]))

    def result(t):
        sci = float(np.mean(ci[t:t + duration]))
        spr = float(np.mean(price[t:t + duration]))
        return dict(start=t, sched_ci=sci, sched_price=spr,
                    run_ci=run_ci, run_pr=run_pr,
                    carbon_saved_kg=energy_kwh * (run_ci - sci) / 1000.0,
                    cost_saved_usd=energy_mwh * (run_pr - spr))

    if priority == "Urgent (run now)":
        return result(0)
    latest = min(deadline, len(ci)) - duration
    if latest < 0:
        return result(0)

    def norm(a):
        a = np.asarray(a, float); rng = a.max() - a.min()
        return (a - a.min()) / rng if rng > 1e-9 else np.zeros_like(a)

    ci_n, pr_n = norm(ci), norm(price)
    best_t, best_score = 0, 1e9
    for t in range(latest + 1):
        score = (weight * float(np.mean(ci_n[t:t + duration]))
                 + (1 - weight) * float(np.mean(pr_n[t:t + duration])))
        if score < best_score:
            best_score, best_t = score, t
    return result(best_t)


def zone(ci_value):
    if ci_value < 250: return GREEN, "🟢 Green"
    if ci_value < 350: return AMBER, "🟡 Amber"
    return RED, "🔴 Red"


def schedule_queue(jobs, ci, price, weight, total_nodes, power_per_node=1.2):
    """
    Batch scheduler (numpy). Places a whole queue of jobs — urgent first (never
    deferred), then flexible by descending energy — into the lowest blended
    carbon/cost window within each deadline, committing node capacity as it goes.
    A single job is simply a queue of one. Returns per-job results + the hourly
    node-occupancy array.
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
            start, best = 0, float("inf")
            found = False
            for t in range(0, max(latest, 0) + 1):
                if np.all(cap[t:t + dur] + nodes <= total_nodes):
                    s = weight * float(np.mean(ci_n[t:t + dur])) + \
                        (1 - weight) * float(np.mean(pr_n[t:t + dur]))
                    if s < best:
                        best, start, found = s, t, True
            if not found:      # no capacity-feasible slot → run now
                start = 0
        cap[start:start + dur] += nodes
        sci = float(np.mean(ci[start:start + dur])); spr = float(np.mean(price[start:start + dur]))
        results[i] = dict(
            idx=i, nodes=nodes, duration=dur, priority=j["priority"], start=start,
            sched_ci=sci, sched_price=spr, run_ci=run_ci, run_pr=run_pr,
            carbon_saved_kg=energy_kwh * (run_ci - sci) / 1000,
            cost_saved_usd=(energy_kwh / 1000) * (run_pr - spr))
    return results, cap


def build_timeline(results, ci):
    """Gantt-style timeline: CI green/amber/red bands with each job drawn on top."""
    H = len(ci)
    fig = go.Figure()
    # background CI zone bands (one soft rectangle per hour)
    for h in range(H):
        z = GREEN if ci[h] < 250 else (AMBER if ci[h] < 350 else RED)
        fig.add_vrect(x0=h, x1=h + 1, fillcolor=z, opacity=0.10, line_width=0, layer="below")
    # one horizontal bar per job
    ordered = sorted(results, key=lambda r: r["start"])
    labels = [f"J{r['idx']+1} · {r['nodes']:,}n" for r in ordered]
    starts = [r["start"] for r in ordered]
    durs   = [r["duration"] for r in ordered]
    colors = [ORANGE if r["priority"].startswith("Urgent") else GREEN for r in ordered]
    fig.add_trace(go.Bar(
        y=labels, x=durs, base=starts, orientation="h",
        marker=dict(color=colors, line=dict(color="white", width=1)),
        hovertemplate="%{y}<br>start +%{base}h · %{x}h long<extra></extra>", showlegend=False))
    fig.update_layout(
        height=max(180, 26 * len(results) + 80), margin=dict(l=10, r=10, t=10, b=10),
        barmode="overlay", plot_bgcolor="white",
        xaxis=dict(title="Hours ahead", range=[0, H], dtick=6),
        yaxis=dict(autorange="reversed"))
    return fig


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

    st.markdown("##### 48-Hour Forecast — Carbon Intensity & Electricity Price")
    fig = go.Figure()
    # Carbon intensity (left axis)
    fig.add_trace(go.Scatter(
        x=list(range(len(CI))), y=CI, mode="lines",
        line=dict(color=BLUE, width=3), name="Carbon intensity (gCO₂/kWh)",
        fill="tozeroy", fillcolor="rgba(21,101,192,0.08)"))
    # Electricity price (right axis)
    fig.add_trace(go.Scatter(
        x=list(range(len(PRICE))), y=PRICE, mode="lines", yaxis="y2",
        line=dict(color=ORANGE, width=2, dash="dot"), name="Electricity price ($/MWh)"))
    fig.add_vline(x=low_hour, line=dict(color=GREEN, dash="dash"),
                  annotation_text=f"cleanest +{low_hour}h")
    fig.update_layout(
        height=340, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Hours ahead", yaxis=dict(title="gCO₂/kWh"),
        yaxis2=dict(title="$/MWh", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", y=1.12), plot_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Electricity price is a representative Time-of-Use tariff (cheap overnight, "
               "expensive on-peak) — see src/models/pricing.py. Clean hours and cheap hours "
               "often but not always coincide, which is what the optimiser balances.")

    # ── Unified scheduler: one job → quick answer, many jobs → queue + timeline ─
    st.markdown("##### 🗓️  Schedule Jobs")
    st.caption("Start with one job for a quick recommendation, or **add rows to plan your whole "
               "queue**. Urgent jobs run now; flexible jobs are shifted into the cleanest window "
               "within their deadline, respecting the cluster's node capacity.")

    if "queue" not in st.session_state:
        st.session_state.queue = pd.DataFrame(
            [{"Nodes": 2000, "Duration (h)": 4, "Deadline (h)": 24, "Priority": "Flexible"}])

    carbon_priority = st.slider(
        "Optimise for  —  ⬅ Cost  ·  Carbon ➡", 0, 100, 70, step=5,
        help="0 = minimise electricity cost only · 100 = minimise carbon only · "
             "in between = balance the two.")
    weight = carbon_priority / 100.0
    st.caption(f"Weighting: **{carbon_priority}% carbon / {100-carbon_priority}% cost**  ·  "
               f"use the **＋** on the last row to add jobs, or the trash icon to remove them.")

    edited = st.data_editor(
        st.session_state.queue, num_rows="dynamic", use_container_width=True, key="qeditor",
        column_config={
            "Nodes": st.column_config.NumberColumn(min_value=1, max_value=kpis["total_nodes"],
                                                   step=100, help="Nodes the job needs"),
            "Duration (h)": st.column_config.NumberColumn(min_value=1, max_value=24, step=1),
            "Deadline (h)": st.column_config.NumberColumn(min_value=1, max_value=48, step=1,
                                                          help="Must finish within this many hours"),
            "Priority": st.column_config.SelectboxColumn(
                options=["Flexible", "Urgent (run now)"], required=True),
        })

    # validate rows
    jobs = []
    for _, r in edited.iterrows():
        try:
            n = int(r["Nodes"]); d = int(r["Duration (h)"]); dl = int(r["Deadline (h)"])
            p = str(r["Priority"])
        except (TypeError, ValueError):
            continue
        if n >= 1 and d >= 1 and dl >= d:
            jobs.append(dict(nodes=n, duration=d, deadline=dl, priority=p))

    if not jobs:
        st.info("Add at least one valid job (deadline must be ≥ duration).")
    else:
        results, cap = schedule_queue(jobs, CI, PRICE, weight, kpis["total_nodes"])

        if len(jobs) == 1:
            # ── quick single-job answer (prominent) ──────────────────────────
            r = results[0]
            saved_kg, saved_usd = r["carbon_saved_kg"], r["cost_saved_usd"]
            m1, m2, m3 = st.columns(3)
            m1.metric("Recommended Start", "Now" if r["start"] == 0 else f"+{r['start']} h",
                      f"CI {r['sched_ci']:.0f} · ${r['sched_price']:.0f}/MWh")
            m2.metric("Carbon Saved", f"{saved_kg:,.1f} kg CO₂",
                      f"{r['run_ci'] - r['sched_ci']:+.0f} gCO₂/kWh vs now")
            m3.metric("Cost Saved", f"${saved_usd:,.2f}",
                      f"{r['run_pr'] - r['sched_price']:+.0f} $/MWh vs now")
            if r["priority"].startswith("Urgent"):
                st.info("⚡ Urgent job runs immediately and is never deferred.")
            elif r["start"] == 0:
                st.warning("Already in the best available window for your chosen balance — run now.")
            else:
                bits = []
                if saved_kg > 0.05: bits.append(f"**{saved_kg:,.1f} kg CO₂**")
                if saved_usd > 0.005: bits.append(f"**${saved_usd:,.2f}**")
                gain = " and ".join(bits) if bits else "carbon/cost"
                st.success(f"✅ Defer this job by **{r['start']} hours** to save {gain}, "
                           f"with no change to the computation.")
        else:
            # ── batch view: summary tiles + table + timeline ─────────────────
            tot_kg = sum(r["carbon_saved_kg"] for r in results)
            tot_usd = sum(r["cost_saved_usd"] for r in results)
            flex = [r for r in results if not r["priority"].startswith("Urgent")]
            urgent = [r for r in results if r["priority"].startswith("Urgent")]
            avg_wait = np.mean([r["start"] for r in flex]) if flex else 0
            max_wait = max([r["start"] for r in flex], default=0)
            on_time = sum(1 for r in urgent if r["start"] == 0)
            peak = cap.max() / kpis["total_nodes"] * 100

            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Total Carbon Saved", f"{tot_kg:,.0f} kg CO₂", f"{len(jobs)} jobs")
            s2.metric("Total Cost Saved", f"${tot_usd:,.0f}")
            s3.metric("Avg / Max Wait", f"{avg_wait:.0f} / {max_wait} h", "flexible jobs")
            s4.metric("Urgent On-Time", f"{on_time}/{len(urgent)}" if urgent else "—",
                      f"peak load {peak:.0f}%")

            st.markdown("**Cluster schedule** — jobs placed on the 48-hour carbon forecast "
                        "(🟢 clean · 🟡 medium · 🔴 dirty). Orange = urgent, green = flexible.")
            st.plotly_chart(build_timeline(results, CI), use_container_width=True)

            tbl = pd.DataFrame([{
                "Job": f"J{r['idx']+1}", "Nodes": r["nodes"], "Dur (h)": r["duration"],
                "Priority": "Urgent" if r["priority"].startswith("Urgent") else "Flexible",
                "Start": "Now" if r["start"] == 0 else f"+{r['start']}h",
                "Window CI": f"{r['sched_ci']:.0f}", "Carbon saved (kg)": round(r["carbon_saved_kg"], 1),
                "Cost saved ($)": round(r["cost_saved_usd"], 2),
            } for r in sorted(results, key=lambda r: r["idx"])])
            st.dataframe(tbl, use_container_width=True, hide_index=True)


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
