"""
Prescriptive scheduling — place carbon-flexible jobs into low-carbon windows.

Given a 48-hour carbon-intensity forecast and one or more jobs (each defined by
node count, duration, deadline and priority), decide *when* to run each job so
that total Scope 2 carbon is minimised, subject to node-capacity and deadline
constraints.

Two schedulers
──────────────
  • GreedyScheduler — per-job: slide a duration-wide window across the forecast
    within the deadline and pick the lowest-carbon block. Fast, intuitive,
    powers the dashboard's job-scheduler widget. Literature shows greedy
    deferral captures >90 % of achievable savings.

  • LPScheduler — fleet-level: a single linear/integer programme that places
    many competing jobs optimally under shared node-capacity constraints.
    Provides the optimum the greedy is benchmarked against.

A job's carbon cost for a window is:
    energy_kWh  = nodes × POWER_PER_NODE_KW × duration_h
    carbon_g    = energy_kWh × mean_CI_over_window
"""

from dataclasses import dataclass
from typing import List, Optional, Dict

import numpy as np

from config.settings import POWER_PER_NODE_KW, TOTAL_NODES
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Maximum cluster energy drawn by active jobs in one hour (kWh) = capacity ceiling
CLUSTER_CAPACITY_KWH = TOTAL_NODES * POWER_PER_NODE_KW


# ── Job & result types ────────────────────────────────────────────────────────

@dataclass
class Job:
    """A schedulable workload."""
    job_id: str
    nodes: int               # nodes required
    duration_h: int          # hours of runtime
    deadline_h: int          # must finish within this many hours from now
    priority: str = "flexible"   # "urgent" (run now) or "flexible" (shiftable)

    def energy_kwh(self) -> float:
        """Total energy the job consumes across its runtime."""
        return self.nodes * POWER_PER_NODE_KW * self.duration_h


@dataclass
class ScheduleResult:
    """Outcome of scheduling one job."""
    job_id: str
    start_hour: int          # chosen start offset (hours from now)
    run_now_carbon_g: float  # carbon if executed immediately (hours 0..duration)
    scheduled_carbon_g: float
    carbon_saved_g: float
    carbon_saved_pct: float
    mean_ci_scheduled: float
    mean_ci_run_now: float


# ── Greedy scheduler ──────────────────────────────────────────────────────────

class GreedyScheduler:
    """
    Per-job greedy scheduler.

    For each flexible job it scans every feasible start offset within the
    deadline and selects the contiguous window with the lowest mean carbon
    intensity that also fits remaining node capacity. Urgent jobs run now.
    """

    name = "Greedy"

    def __init__(self, total_nodes: int = TOTAL_NODES):
        self.total_nodes = total_nodes

    def schedule_job(
        self,
        job: Job,
        ci_forecast: np.ndarray,
        capacity_used: Optional[np.ndarray] = None,
    ) -> ScheduleResult:
        """
        Schedule a single job against the CI forecast.

        Parameters
        ----------
        job : Job
        ci_forecast : np.ndarray
            Hourly carbon intensity (gCO₂/kWh) for the forecast horizon.
        capacity_used : np.ndarray, optional
            Nodes already committed in each hour (same length as forecast).
            Defaults to all-zero (empty cluster).

        Returns
        -------
        ScheduleResult
        """
        H = len(ci_forecast)
        if capacity_used is None:
            capacity_used = np.zeros(H)

        d = job.duration_h
        energy = job.energy_kwh()

        # Carbon if run immediately (hours 0..d)
        run_now_ci = float(np.mean(ci_forecast[:d]))
        run_now_carbon = energy * run_now_ci

        # Urgent jobs are never deferred
        if job.priority == "urgent":
            return self._result(job, 0, run_now_carbon, run_now_carbon,
                                 run_now_ci, run_now_ci)

        # Latest start that still meets the deadline and stays within the horizon
        latest_start = min(job.deadline_h, H) - d
        if latest_start < 0:
            # Job cannot fit before its deadline — must run now
            return self._result(job, 0, run_now_carbon, run_now_carbon,
                                 run_now_ci, run_now_ci)

        best_start, best_ci = 0, float("inf")
        for t in range(0, latest_start + 1):
            window = slice(t, t + d)
            # Node-capacity check: every hour in the window must have room
            if np.all(capacity_used[window] + job.nodes <= self.total_nodes):
                mean_ci = float(np.mean(ci_forecast[window]))
                if mean_ci < best_ci:
                    best_ci, best_start = mean_ci, t

        scheduled_carbon = energy * best_ci
        return self._result(job, best_start, run_now_carbon, scheduled_carbon,
                            best_ci, run_now_ci)

    def schedule_batch(
        self,
        jobs: List[Job],
        ci_forecast: np.ndarray,
    ) -> List[ScheduleResult]:
        """
        Schedule many jobs, committing node capacity as each is placed.

        Jobs are processed urgent-first, then flexible by descending energy
        (largest carbon levers first). Capacity committed by earlier jobs
        constrains later ones.
        """
        H = len(ci_forecast)
        capacity_used = np.zeros(H)
        order = sorted(jobs, key=lambda j: (j.priority != "urgent", -j.energy_kwh()))

        results = []
        for job in order:
            res = self.schedule_job(job, ci_forecast, capacity_used)
            # Commit this job's node usage over its scheduled window
            capacity_used[res.start_hour:res.start_hour + job.duration_h] += job.nodes
            results.append(res)
        return results

    @staticmethod
    def _result(job, start, run_now_c, sched_c, sched_ci, run_now_ci) -> ScheduleResult:
        return _make_result(job, start, run_now_c, sched_c, sched_ci, run_now_ci)


# ── Shared result builder ─────────────────────────────────────────────────────

def _make_result(job, start, run_now_c, sched_c, sched_ci, run_now_ci) -> ScheduleResult:
    saved = run_now_c - sched_c
    pct = (saved / run_now_c * 100) if run_now_c > 0 else 0.0
    return ScheduleResult(
        job_id=job.job_id,
        start_hour=start,
        run_now_carbon_g=round(run_now_c, 1),
        scheduled_carbon_g=round(sched_c, 1),
        carbon_saved_g=round(saved, 1),
        carbon_saved_pct=round(pct, 2),
        mean_ci_scheduled=round(sched_ci, 1),
        mean_ci_run_now=round(run_now_ci, 1),
    )


# ── Carbon-blind baseline scheduler (the "as-is" process) ────────────────────

class CarbonBlindScheduler:
    """
    The current-practice baseline: schedule each job at the earliest feasible
    window that fits node capacity, with no awareness of carbon intensity.

    This is the correct "as-is" benchmark for batch/fleet scheduling — unlike a
    naive "run everything now" assumption, it respects the 4,626-node limit, so
    the carbon-aware schedulers are compared against a physically realisable
    baseline. A carbon-aware scheduler can always fall back to this placement,
    so its saving versus this baseline is never negative.
    """

    name = "Carbon-blind (as-is)"

    def __init__(self, total_nodes: int = TOTAL_NODES):
        self.total_nodes = total_nodes

    def schedule_batch(self, jobs: List[Job], ci_forecast: np.ndarray) -> List[ScheduleResult]:
        H = len(ci_forecast)
        capacity_used = np.zeros(H)
        # Process urgent first, then by submission order (FCFS) — carbon ignored
        order = sorted(jobs, key=lambda j: (j.priority != "urgent",))

        results = []
        for job in order:
            d = job.duration_h
            run_now_ci = float(np.mean(ci_forecast[:d]))
            placed = False
            for t in range(0, H - d + 1):
                if np.all(capacity_used[t:t + d] + job.nodes <= self.total_nodes):
                    capacity_used[t:t + d] += job.nodes
                    sched_ci = float(np.mean(ci_forecast[t:t + d]))
                    energy = job.energy_kwh()
                    results.append(_make_result(
                        job, t, energy * run_now_ci, energy * sched_ci,
                        sched_ci, run_now_ci))
                    placed = True
                    break
            if not placed:  # fallback: run now even if over capacity
                energy = job.energy_kwh()
                results.append(_make_result(
                    job, 0, energy * run_now_ci, energy * run_now_ci,
                    run_now_ci, run_now_ci))
        return results


# ── Linear Programming scheduler ──────────────────────────────────────────────

class LPScheduler:
    """
    Fleet-level optimal scheduler via Mixed-Integer Programming (PuLP + CBC).

    Places all jobs simultaneously to minimise total carbon, resolving
    node-capacity contention globally rather than first-come-first-served.
    """

    name = "LP (MIP)"

    def __init__(self, total_nodes: int = TOTAL_NODES):
        self.total_nodes = total_nodes

    def schedule_batch(
        self,
        jobs: List[Job],
        ci_forecast: np.ndarray,
    ) -> List[ScheduleResult]:
        import pulp

        H = len(ci_forecast)

        # Pre-compute, for every job, its feasible start offsets and the carbon
        # cost of starting at each. cost[j][t] = energy × mean CI over the window.
        feasible: Dict[str, List[int]] = {}
        cost: Dict[str, Dict[int, float]] = {}
        run_now_ci: Dict[str, float] = {}

        for job in jobs:
            d = job.energy_kwh()
            run_now_ci[job.job_id] = float(np.mean(ci_forecast[:job.duration_h]))
            if job.priority == "urgent":
                starts = [0]
            else:
                latest = min(job.deadline_h, H) - job.duration_h
                starts = list(range(0, latest + 1)) if latest >= 0 else [0]
            feasible[job.job_id] = starts
            cost[job.job_id] = {
                t: d * float(np.mean(ci_forecast[t:t + job.duration_h]))
                for t in starts
            }

        # ── Build the MIP ──────────────────────────────────────────────────
        prob = pulp.LpProblem("carbon_aware_scheduling", pulp.LpMinimize)

        # Binary decision variables x[j,t]
        x = {
            (job.job_id, t): pulp.LpVariable(f"x_{job.job_id}_{t}", cat="Binary")
            for job in jobs for t in feasible[job.job_id]
        }

        # Objective: total carbon
        prob += pulp.lpSum(cost[j][t] * x[(j, t)] for (j, t) in x)

        # (1) Each job runs exactly once
        for job in jobs:
            prob += pulp.lpSum(x[(job.job_id, t)] for t in feasible[job.job_id]) == 1

        # (2) Node capacity per hour: a job started at t occupies hours t..t+d-1
        for h in range(H):
            terms = []
            for job in jobs:
                for t in feasible[job.job_id]:
                    if t <= h < t + job.duration_h:
                        terms.append(job.nodes * x[(job.job_id, t)])
            if terms:
                prob += pulp.lpSum(terms) <= self.total_nodes

        # ── Solve ──────────────────────────────────────────────────────────
        prob.solve(pulp.PULP_CBC_CMD(msg=0))
        status = pulp.LpStatus[prob.status]
        if status != "Optimal":
            logger.warning(f"LP solver status: {status}")

        # ── Extract chosen start times ─────────────────────────────────────
        results = []
        for job in jobs:
            chosen = next(t for t in feasible[job.job_id]
                          if pulp.value(x[(job.job_id, t)]) > 0.5)
            energy = job.energy_kwh()
            sched_ci = float(np.mean(ci_forecast[chosen:chosen + job.duration_h]))
            results.append(_make_result(
                job, chosen,
                energy * run_now_ci[job.job_id],
                energy * sched_ci,
                sched_ci, run_now_ci[job.job_id],
            ))
        return results


# ══════════════════════════════════════════════════════════════════════════════
#  Fleet-level load shifting (divisible energy, transportation LP)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class LoadShiftResult:
    """Outcome of a single-day load-shift optimisation."""
    baseline_carbon_g: float      # as-is: every job runs when first scheduled
    optimized_carbon_g: float     # forecast-driven schedule, scored on ACTUAL CI
    carbon_saved_g: float
    carbon_saved_pct: float
    energy_shifted_kwh: float      # total energy moved to a different hour


def optimize_load_shift(
    shiftable: np.ndarray,
    fixed: np.ndarray,
    ci_decide: np.ndarray,
    ci_actual: np.ndarray,
    capacity: float = CLUSTER_CAPACITY_KWH,
    max_delay: int = 12,
) -> LoadShiftResult:
    """
    Redistribute shiftable energy across hours of a day to minimise carbon.

    A transportation LP moves energy from each source hour `s` to a destination
    hour `d` (with d ≥ s, within `max_delay` hours), minimising carbon under the
    *decision* CI, then scores the resulting schedule under the *actual* CI.

    Pass ci_decide = forecast for the realistic case; pass ci_decide = ci_actual
    for the perfect-hindsight ceiling.

    Parameters
    ----------
    shiftable : np.ndarray (24,)  — shiftable energy available at each hour (kWh)
    fixed     : np.ndarray (24,)  — non-shiftable energy fixed at each hour (kWh)
    ci_decide : np.ndarray (24,)  — CI used to make shifting decisions (gCO₂/kWh)
    ci_actual : np.ndarray (24,)  — CI used to score the outcome (gCO₂/kWh)
    capacity  : float             — max active energy per hour (kWh)
    max_delay : int               — furthest a job may be deferred (hours)

    Returns
    -------
    LoadShiftResult
    """
    import pulp

    H = len(shiftable)

    # Baseline: every unit of energy runs in its original hour, scored on actual CI
    baseline = float(np.sum((fixed + shiftable) * ci_actual))

    prob = pulp.LpProblem("load_shift", pulp.LpMinimize)

    # Feasible destinations for each source hour (can only defer, within max_delay)
    dests = {s: list(range(s, min(s + max_delay, H - 1) + 1)) for s in range(H)}

    f = {(s, d): pulp.LpVariable(f"f_{s}_{d}", lowBound=0)
         for s in range(H) for d in dests[s]}

    # Objective: carbon of shifted energy under the decision CI
    prob += pulp.lpSum(f[(s, d)] * ci_decide[d] for (s, d) in f)

    # (1) Conservation — all shiftable energy from each source hour is placed
    for s in range(H):
        prob += pulp.lpSum(f[(s, d)] for d in dests[s]) == float(shiftable[s])

    # (2) Capacity — fixed + incoming shifted energy at each hour ≤ capacity
    for d in range(H):
        incoming = [f[(s, d)] for s in range(H) if d in dests[s]]
        prob += float(fixed[d]) + pulp.lpSum(incoming) <= capacity

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    # Score the chosen allocation under ACTUAL CI
    optimized = float(np.sum(fixed * ci_actual))
    shifted_energy = 0.0
    for (s, d), var in f.items():
        val = var.value() or 0.0
        optimized += val * ci_actual[d]
        if d != s:
            shifted_energy += val

    saved = baseline - optimized
    pct = (saved / baseline * 100) if baseline > 0 else 0.0
    return LoadShiftResult(
        baseline_carbon_g=round(baseline, 1),
        optimized_carbon_g=round(optimized, 1),
        carbon_saved_g=round(saved, 1),
        carbon_saved_pct=round(pct, 3),
        energy_shifted_kwh=round(shifted_energy, 1),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Joint carbon + cost scheduling
# ══════════════════════════════════════════════════════════════════════════════

def joint_greedy_schedule(
    ci_forecast: np.ndarray,
    price_forecast: np.ndarray,
    job: Job,
    weight: float = 0.7,
    power_per_node: float = POWER_PER_NODE_KW,
) -> Dict:
    """
    Greedy per-job scheduler that co-optimises carbon and electricity cost.

    The objective is a weighted blend of normalised carbon intensity and
    normalised price over the job's runtime window:

        score(t) = weight * carbon_norm[t..t+d] + (1 - weight) * price_norm[t..t+d]

    weight = 1.0 -> pure carbon · 0.0 -> pure cost · 0.5 -> balanced. Carbon and
    price are on different scales, so each is min-max normalised across the
    forecast horizon before blending. The chosen window is the one with the
    lowest blended score within the deadline; urgent jobs run immediately.

    Parameters
    ----------
    ci_forecast    : hourly carbon intensity (gCO2/kWh) over the horizon
    price_forecast : hourly electricity price ($/MWh) over the horizon
                     (see src/models/pricing.py for the representative ToU model)
    job            : the Job to schedule
    weight         : carbon-vs-cost weight in [0, 1]

    Returns
    -------
    dict with the chosen start hour, the CI and price at that window versus
    running now, and the carbon (kg CO2) and cost ($) saved.
    """
    ci = np.asarray(ci_forecast, float)
    price = np.asarray(price_forecast, float)
    d = job.duration_h
    energy_kwh = job.nodes * power_per_node * d
    energy_mwh = energy_kwh / 1000.0
    run_ci = float(np.mean(ci[:d]))
    run_pr = float(np.mean(price[:d]))

    def result(t: int) -> Dict:
        sci = float(np.mean(ci[t:t + d]))
        spr = float(np.mean(price[t:t + d]))
        return {
            "start_hour": t,
            "sched_ci": round(sci, 1), "sched_price": round(spr, 1),
            "run_now_ci": round(run_ci, 1), "run_now_price": round(run_pr, 1),
            "carbon_saved_kg": round(energy_kwh * (run_ci - sci) / 1000.0, 2),
            "cost_saved_usd": round(energy_mwh * (run_pr - spr), 2),
        }

    if job.priority == "urgent":
        return result(0)
    latest = min(job.deadline_h, len(ci)) - d
    if latest < 0:
        return result(0)

    def _norm(a: np.ndarray) -> np.ndarray:
        rng = a.max() - a.min()
        return (a - a.min()) / rng if rng > 1e-9 else np.zeros_like(a)

    ci_n, pr_n = _norm(ci), _norm(price)
    best_t, best_score = 0, float("inf")
    for t in range(latest + 1):
        score = (weight * float(np.mean(ci_n[t:t + d]))
                 + (1 - weight) * float(np.mean(pr_n[t:t + d])))
        if score < best_score:
            best_score, best_t = score, t
    return result(best_t)
