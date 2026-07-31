"""The exact L1 relocation body, and the one tier that can be certified on it today.

`|p - q|_1 <= 2 b Q` with `1.p = 1.q` and `p >= 0` is the uncertainty statement a power model can
actually be held to: at most a fraction `b` of the workload's own total power ends up somewhere
other than predicted. Scale-free, and independent of how finely the design is decomposed into
blocks.

## It IS representable over p alone -- with exponentially many rows and a trivial oracle

Because the total is conserved, `sum(p - q) = 0`, so the positive and negative parts are equal and

    |p - q|_1 = 2 * sum_i (p_i - q_i)^+ = 2 * max_{S subset of [n]} sum_{i in S} (p_i - q_i)

Hence the body is EXACTLY the intersection of the `2^n` linear inequalities

    sum_{i in S} (p_i - q_i) <= b Q        for every S

and its separation oracle is one line: given `p`, take `S = {i : p_i > q_i}`. That is why the two
approximations in `CertiTherm/measurements.py` are approximations and neither is the body:

    deviation_bounded_power_space    the box |p_i - q_i| <= b Q       SUPERSET  (drops all rows)
    relocation_bounded_power_space   the box |p_i - q_i| <= 2 b Q / n SUBSET    (over-tightens)

A certified minimum-cost OBSERVATION bound needs a polytope object, and threading the exact body
through the certified path means either the lifted program `p = q + u - v` -- which changes the
variable dimension from `n` to `3n` and therefore every block-identity check, thermal row and action
vector -- or lazy constraint generation of the subset rows inside the collision LP. Both are real
changes to the certified path and NEITHER is done here. The upper tiers are open under the exact
body, and are reported as open.

## What is NOT open

The FIRST tier needs only reachability: if no admissible map is REJECT then every admissible map is
SAFE, the empty plan certifies, and no measurement is required at all. Reachability is a MAXIMISATION
of one linear form over the body, and that is solved exactly by the lifted LP below -- no polytope
object, no certified-path surgery. So the "no measurement needed" breakpoint is exact under the true
L1 relocation body, and does not inherit the inscribed box's conservatism.

The distinction is worth the paragraph because the two answers are far apart. On
`arch_a`/`default`/`resnet50` the inscribed box cannot reach a reject floor even at `b = 1.0`, which
would license "no measurement needed at any relocation budget"; the exact body reaches it at
`b = 4.1%`. The box conclusion is SOUND -- a subset reaching no floor says nothing about the
superset -- but it is sound in the useless direction, and quoting it as the relocation breakpoint
would overstate the design's robustness by more than an order of magnitude.

This file is the tracked home of `radius_l1`, which produced numbers already quoted in
`docs/THERMAL_ROBUSTNESS_RADII.md` while living only in an untracked scratch directory on the
execution host. That is a provenance hole and closing it is the reason the file exists at all.

NON-CLAIM diagnostic.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

BISECTION_STEPS = 20


def reject_reachable_l1(rows, floors, placed, relocated_fraction) -> bool:
    """Is any map within the exact L1 relocation budget REJECT?

    Lifted as `p = q + u - v`, `u, v >= 0`, with `sum(u) = sum(v)` conserving the total and
    `sum(u) + sum(v) <= 2 b Q` the transfer budget. `v - u <= q` keeps `p >= 0`. One LP per reject
    cell; the first cell that reaches its floor answers the question.
    """

    q = np.asarray(placed, dtype=float)
    n = q.size
    total = float(q.sum())
    if relocated_fraction <= 0.0:
        return bool(np.any(np.asarray(rows, dtype=float) @ q >= np.asarray(floors, dtype=float)))

    a_ub = np.vstack((np.ones((1, 2 * n)), np.hstack((-np.eye(n), np.eye(n)))))
    b_ub = np.concatenate(([2.0 * relocated_fraction * total], q))
    a_eq = np.hstack((np.ones((1, n)), -np.ones((1, n))))
    bounds = [(0.0, None)] * (2 * n)
    for row, floor in zip(np.asarray(rows, dtype=float), np.asarray(floors, dtype=float)):
        result = linprog(
            np.concatenate((-row, row)), A_ub=a_ub, b_ub=b_ub,
            A_eq=a_eq, b_eq=[0.0], bounds=bounds, method="highs",
        )
        # A solver failure is not a negative. Treating it as "not reachable" would report a larger
        # robustness radius than was established, which is the fail-open direction for this
        # quantity -- the same asymmetry that governs the blindness search in `threshold.py`.
        if result.status != 0:
            raise RuntimeError(
                f"the reachability LP did not solve (status {result.status}); a failed maximisation "
                "must not be read as an unreachable floor"
            )
        if float(row @ q) - float(result.fun) >= float(floor):
            return True
    return False


def radius_l1(rows, floors, placed, hi: float = 1.0) -> float:
    """The smallest relocated fraction at which some admissible map is REJECT.

    Returns `0.0` when the NOMINAL map already reaches a floor -- the design is infeasible before
    any uncertainty is admitted, and bisecting past that would return a small positive number and
    fabricate a safe interval below it. Returns `inf` when no floor is reachable through `hi`.
    """

    if reject_reachable_l1(rows, floors, placed, 0.0):
        return 0.0
    if not reject_reachable_l1(rows, floors, placed, hi):
        return float("inf")
    lo = 0.0
    for _ in range(BISECTION_STEPS):
        mid = 0.5 * (lo + hi)
        if reject_reachable_l1(rows, floors, placed, mid):
            hi = mid
        else:
            lo = mid
    return hi
