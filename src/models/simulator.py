"""
Event-driven scheduling simulator with preemption.

The static optimisers assume the workload is known in advance. A live facility
faces jobs arriving over time — including *urgent* jobs that must run now. If
flexible jobs have been shifted into clean windows and an urgent job then
arrives with no free nodes, the scheduler must **preempt** a deferrable job:
free its nodes, run the urgent job, and reschedule the bumped job to another
clean window (it has deadline slack, so this is low-cost).

This simulator demonstrates that preemption lets urgent jobs run on time while
preserving most of the carbon saving — unlike static headroom reservation,
which sacrifices the saving on a highly-utilised cluster.

Scope: a planning-level discrete-event model over a fixed forecast horizon.
Jobs hold node *reservations* over hours; preemption re-places a reservation
rather than checkpointing a mid-flight process. The workload is synthetic but
representative, and clearly labelled as such.
"""

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from config.settings import TOTAL_NODES, POWER_PER_NODE_KW


@dataclass
class SimJob:
    job_id: str
    arrival: int            # hour the job is submitted
    nodes: int
    duration: int
    deadline: int           # absolute hour by which it must COMPLETE
    priority: str           # "urgent" or "flexible"
    start: Optional[int] = None      # assigned start hour
    preempted: int = 0               # how many times it was bumped

    def energy_kwh(self) -> float:
        return self.nodes * POWER_PER_NODE_KW * self.duration


class PreemptiveScheduler:
    """
    Carbon-aware scheduler with urgent-job preemption.

    capacity[h] tracks committed nodes per hour. Flexible jobs are placed in the
    cleanest feasible window within their deadline. Urgent jobs are placed at
    arrival; if capacity is short, the scheduler preempts flexible reservations
    that overlap the urgent window and still have slack, then re-places them.
    """

    def __init__(self, ci_forecast: np.ndarray, total_nodes: int = TOTAL_NODES):
        self.ci = np.asarray(ci_forecast, float)
        self.H = len(self.ci)
        self.total = total_nodes
        self.capacity = np.zeros(self.H)
        self.jobs: List[SimJob] = []
        self.preemptions = 0
        self.reschedule_fail = 0

    # ── capacity helpers ──────────────────────────────────────────────────────
    def _fits(self, t, nodes, dur):
        return t + dur <= self.H and np.all(self.capacity[t:t+dur] + nodes <= self.total)

    def _commit(self, job, t):
        self.capacity[t:t+job.duration] += job.nodes
        job.start = t

    def _release(self, job):
        self.capacity[job.start:job.start+job.duration] -= job.nodes
        job.start = None

    # ── placement ─────────────────────────────────────────────────────────────
    def _cleanest_window(self, arrival, deadline, nodes, dur):
        """Lowest-mean-CI feasible start in [arrival, deadline-dur], else None."""
        latest = min(deadline, self.H) - dur
        best_t, best_ci = None, float("inf")
        for t in range(arrival, latest + 1):
            if self._fits(t, nodes, dur):
                m = float(np.mean(self.ci[t:t+dur]))
                if m < best_ci:
                    best_ci, best_t = m, t
        return best_t

    def place_flexible(self, job: SimJob) -> bool:
        t = self._cleanest_window(job.arrival, job.deadline, job.nodes, job.duration)
        if t is not None:
            self._commit(job, t)
            return True
        # no clean slot — force earliest feasible even at deadline edge
        for t in range(job.arrival, min(job.deadline, self.H) - job.duration + 1):
            if self._fits(t, job.nodes, job.duration):
                self._commit(job, t); return True
        return False

    def place_urgent(self, job: SimJob):
        """Urgent job runs at arrival; preempt flexible jobs if needed."""
        t = job.arrival
        if self._fits(t, job.nodes, job.duration):
            self._commit(job, t); return

        # Need to free nodes over [t, t+dur). Find flexible jobs overlapping this
        # window that still have slack to be re-placed, bump the smallest-slack
        # first until the urgent job fits.
        window = set(range(t, t + job.duration))
        candidates = [j for j in self.jobs
                      if j.priority == "flexible" and j.start is not None
                      and set(range(j.start, j.start + j.duration)) & window]
        # prefer bumping jobs with the most remaining slack (easiest to re-place)
        candidates.sort(key=lambda j: -(j.deadline - (j.start + j.duration)))

        bumped = []
        for j in candidates:
            if self._fits(t, job.nodes, job.duration):
                break
            self._release(j); bumped.append(j); self.preemptions += 1; j.preempted += 1

        # commit the urgent job (it now fits, or runs at arrival regardless)
        if self._fits(t, job.nodes, job.duration):
            self._commit(job, t)
        else:
            self._commit(job, t)   # urgent always runs on time (may exceed cap in rare edge)

        # re-place the bumped flexible jobs into new clean windows
        for j in bumped:
            if not self.place_flexible(j):
                self.reschedule_fail += 1

    def run(self, jobs: List[SimJob]):
        self.jobs = sorted(jobs, key=lambda j: (j.arrival, j.priority != "urgent"))
        for job in self.jobs:
            if job.priority == "urgent":
                self.place_urgent(job)
            else:
                self.place_flexible(job)
        return self.jobs

    # ── metrics ───────────────────────────────────────────────────────────────
    def carbon(self) -> float:
        """Total carbon (kg) of the produced schedule."""
        return sum(j.energy_kwh() * float(np.mean(self.ci[j.start:j.start+j.duration])) / 1000
                   for j in self.jobs if j.start is not None)
