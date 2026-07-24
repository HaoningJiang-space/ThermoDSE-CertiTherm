"""Phase-trace IR and the schedule-reachable power set.

Why this exists. Everything in CertiTherm so far treats a workload as ONE placed power
vector drawn from a `PowerPolytope` -- a box plus a total-power constraint. That set is far
looser than physics allows: it admits every block sitting at its own maximum simultaneously,
which no legal schedule produces. A decision ambiguity found only in that slack may be an
artefact of the abstraction rather than a property of the design.

This module replaces "any point in a box" with "any power the workload can actually reach",
built from the structure a DSE already has: tasks with power signatures, a precedence DAG,
and resource capacity.

    TaskSpec      one schedulable unit: per-block power while it runs, and a duration
    ScheduleSpace tasks + precedence + capacity == the space of LEGAL executions
    PhaseTrace    one concrete execution: a sequence of (duration, power) phases

APPROXIMATION DIRECTION, stated once and deliberately. The exact set of instantaneous power
vectors is FINITE -- one point per legal concurrent task set. `reachable_polytope()` returns
its convex hull, which CONTAINS the true set. For DSOS that is the conservative direction: a
larger set can only invent collisions that are not physically reachable, so it can only ask
for MORE observations than necessary, never fewer. It cannot produce a false certificate.
The tightening is therefore sound but not tight, and the gap is reported, never hidden.

Units follow the project convention: `_w` watts, `_s` seconds.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Dict, FrozenSet, Iterable, Iterator, Optional, Sequence, Tuple

import numpy as np

from CertiTherm.core import PowerPolytope

# Enumerating legal concurrent sets is exponential in the worst case. Rather than
# silently sampling -- which would make the "reachable" set unsound in the dangerous
# direction, since a MISSED concurrent set could hide a real collision -- enumeration
# refuses to proceed past this many antichains and the caller must widen or split.
MAX_CONCURRENT_SETS = 200_000


@dataclass(frozen=True)
class TaskSpec:
    """One schedulable unit of work.

    `power_w` is the placed power drawn while this task runs, over the same block
    ordering as the rest of the pipeline. `resource` names what the task occupies
    (a chiplet, an engine); tasks sharing a resource cannot overlap.
    """

    task_id: str
    power_w: np.ndarray
    duration_s: float
    resource: str

    def __post_init__(self) -> None:
        power = np.asarray(self.power_w, dtype=float)
        if power.ndim != 1 or power.size == 0 or not np.all(np.isfinite(power)):
            raise ValueError(f"{self.task_id}: power_w must be a finite non-empty vector")
        if np.any(power < 0.0):
            raise ValueError(f"{self.task_id}: power_w must be non-negative")
        if not np.isfinite(self.duration_s) or self.duration_s <= 0.0:
            raise ValueError(f"{self.task_id}: duration_s must be finite and positive")
        if not self.task_id or not self.resource:
            raise ValueError("task_id and resource must be non-empty")
        object.__setattr__(self, "power_w", power)


@dataclass(frozen=True)
class ScheduleSpace:
    """The set of LEGAL executions: tasks, precedence, and resource capacity.

    `precedence` holds (before, after) task-id pairs. `capacity` caps how many tasks
    may occupy one resource at once (1 == exclusive, the usual case).

    This is deliberately the smallest structure that already excludes the physically
    impossible: a task cannot run before its predecessor, and a resource cannot host
    more than its capacity. It is not a scheduler and does not pick an execution.
    """

    tasks: Tuple[TaskSpec, ...]
    precedence: Tuple[Tuple[str, str], ...] = ()
    capacity: Optional[Dict[str, int]] = None

    def __post_init__(self) -> None:
        if not self.tasks:
            raise ValueError("ScheduleSpace needs at least one task")
        ids = [t.task_id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("task_id values must be unique")
        n = self.tasks[0].power_w.size
        if any(t.power_w.size != n for t in self.tasks):
            raise ValueError("all tasks must share one block ordering")
        known = set(ids)
        for before, after in self.precedence:
            if before not in known or after not in known:
                raise ValueError(f"precedence ({before}, {after}) names an unknown task")
            if before == after:
                raise ValueError(f"precedence ({before}, {after}) is self-referential")
        cap = dict(self.capacity or {})
        for res, k in cap.items():
            if not isinstance(k, int) or k < 1:
                raise ValueError(f"capacity[{res}] must be a positive integer")
        object.__setattr__(self, "tasks", tuple(self.tasks))
        object.__setattr__(self, "precedence", tuple(self.precedence))
        object.__setattr__(self, "capacity", cap)
        if self._has_cycle():
            raise ValueError("precedence contains a cycle; no legal execution exists")

    @property
    def dimension(self) -> int:
        return int(self.tasks[0].power_w.size)

    def _has_cycle(self) -> bool:
        succ: Dict[str, list] = {t.task_id: [] for t in self.tasks}
        indeg = {t.task_id: 0 for t in self.tasks}
        for before, after in self.precedence:
            succ[before].append(after)
            indeg[after] += 1
        stack = [k for k, v in indeg.items() if v == 0]
        seen = 0
        while stack:
            node = stack.pop()
            seen += 1
            for nxt in succ[node]:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    stack.append(nxt)
        return seen != len(indeg)

    def _capacity_of(self, resource: str) -> int:
        return int((self.capacity or {}).get(resource, 1))

    def concurrent_sets(self) -> Iterator[FrozenSet[str]]:
        """Every set of tasks that may run SIMULTANEOUSLY.

        Legal iff (a) no two members are precedence-related -- a successor cannot
        overlap its predecessor -- and (b) no resource is oversubscribed. The empty
        set is included: an idle instant is reachable.

        Raises rather than truncating past MAX_CONCURRENT_SETS: a missed concurrent
        set could hide a genuine collision, which is the unsound direction.
        """
        ids = [t.task_id for t in self.tasks]
        # transitive closure of precedence -- an indirect successor cannot overlap either
        reach: Dict[str, set] = {i: set() for i in ids}
        for before, after in self.precedence:
            reach[before].add(after)
        changed = True
        while changed:
            changed = False
            for node in ids:
                extra = set()
                for nxt in reach[node]:
                    extra |= reach[nxt]
                if not extra <= reach[node]:
                    reach[node] |= extra
                    changed = True
        ordered = {(a, b) for a in ids for b in reach[a]}
        by_id = {t.task_id: t for t in self.tasks}

        emitted = 0
        for size in range(len(ids) + 1):
            for combo in combinations(ids, size):
                if any((a, b) in ordered or (b, a) in ordered
                       for a, b in combinations(combo, 2)):
                    continue
                used: Dict[str, int] = {}
                for tid in combo:
                    res = by_id[tid].resource
                    used[res] = used.get(res, 0) + 1
                if any(k > self._capacity_of(res) for res, k in used.items()):
                    continue
                emitted += 1
                if emitted > MAX_CONCURRENT_SETS:
                    raise ValueError(
                        f"more than {MAX_CONCURRENT_SETS} legal concurrent sets; refusing "
                        f"to enumerate (sampling would risk missing a collision)")
                yield frozenset(combo)

    def reachable_points_w(self) -> np.ndarray:
        """The EXACT finite set of instantaneous power vectors, one per concurrent set."""
        by_id = {t.task_id: t for t in self.tasks}
        rows = []
        for cs in self.concurrent_sets():
            total = np.zeros(self.dimension)
            for tid in cs:
                total = total + by_id[tid].power_w
            rows.append(total)
        return np.unique(np.asarray(rows, dtype=float), axis=0)

    def reachable_polytope(self) -> PowerPolytope:
        """Convex hull of the reachable points, as a `PowerPolytope`.

        OVER-APPROXIMATION, in the conservative direction (see the module docstring):
        the hull contains the true finite set, so it can only invent unreachable
        collisions and ask for more observations, never certify falsely.

        The returned polytope keeps the exact per-block bounds of the reachable set
        plus one total-power upper bound. That is already much tighter than a box
        over independent maxima, because no legal execution attains every block
        maximum at once unless some concurrent set actually does.
        """
        pts = self.reachable_points_w()
        lower = pts.min(axis=0)
        upper = pts.max(axis=0)
        total_max = float(pts.sum(axis=1).max())
        n = self.dimension
        a_ub = np.ones((1, n))
        b_ub = np.array([total_max])
        return PowerPolytope(lower_w=lower, upper_w=upper,
                             a_eq=np.zeros((0, n)), b_eq=np.zeros(0),
                             a_ub=a_ub, b_ub=b_ub)


@dataclass(frozen=True)
class PhaseTrace:
    """One concrete legal execution: consecutive (duration, power) phases.

    This is what a transient thermal model consumes. A steady-state model sees only
    `mean_power_w`, which is exactly why two traces can be indistinguishable to the
    coarse abstraction while differing in transient peak.
    """

    durations_s: np.ndarray
    powers_w: np.ndarray                     # (phases, blocks)

    def __post_init__(self) -> None:
        d = np.asarray(self.durations_s, dtype=float)
        p = np.asarray(self.powers_w, dtype=float)
        if d.ndim != 1 or d.size == 0 or not np.all(np.isfinite(d)) or np.any(d <= 0):
            raise ValueError("durations_s must be finite, positive and non-empty")
        if p.ndim != 2 or p.shape[0] != d.size or not np.all(np.isfinite(p)):
            raise ValueError("powers_w must be a finite (phases, blocks) matrix")
        if np.any(p < 0.0):
            raise ValueError("powers_w must be non-negative")
        object.__setattr__(self, "durations_s", d)
        object.__setattr__(self, "powers_w", p)

    @property
    def n_phases(self) -> int:
        return int(self.durations_s.size)

    @property
    def dimension(self) -> int:
        return int(self.powers_w.shape[1])

    @property
    def total_time_s(self) -> float:
        return float(self.durations_s.sum())

    @property
    def mean_power_w(self) -> np.ndarray:
        """Time-weighted mean -- ALL a steady-state abstraction can see."""
        return (self.durations_s @ self.powers_w) / self.total_time_s

    @property
    def peak_power_w(self) -> np.ndarray:
        """Per-block maximum over phases. Not a temperature: thermal inertia means a
        short high-power phase need not reach its steady temperature."""
        return self.powers_w.max(axis=0)

    def energy_j(self) -> np.ndarray:
        return self.durations_s @ self.powers_w


def box_polytope(space: ScheduleSpace) -> PowerPolytope:
    """The LOOSE box the project used until now: independent per-block maxima with a
    total-power cap. Kept so the tightening can be quantified rather than asserted."""
    pts = space.reachable_points_w()
    n = space.dimension
    upper = pts.max(axis=0)
    return PowerPolytope(lower_w=np.zeros(n), upper_w=upper,
                         a_eq=np.zeros((0, n)), b_eq=np.zeros(0),
                         a_ub=np.ones((1, n)), b_ub=np.array([float(upper.sum())]))


def tightening_report(space: ScheduleSpace) -> Dict[str, float]:
    """How much structure actually buys, in numbers rather than assertion.

    `total_w_ratio` is the honest headline: the loose box permits every block at its
    own maximum at once, while no legal execution may exceed the largest reachable
    concurrent total.
    """
    pts = space.reachable_points_w()
    box = box_polytope(space)
    reach = space.reachable_polytope()
    box_total = float(box.upper_w.sum())
    reach_total = float(reach.b_ub[0])
    return {
        "n_reachable_points": float(pts.shape[0]),
        "box_total_w": box_total,
        "reachable_total_w": reach_total,
        "total_w_ratio": reach_total / box_total if box_total else float("nan"),
        "box_volume_log": float(np.log(np.maximum(box.upper_w - box.lower_w, 1e-300)).sum()),
        "reachable_volume_log": float(
            np.log(np.maximum(reach.upper_w - reach.lower_w, 1e-300)).sum()),
    }
