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

## What is NOT open, and the two DIFFERENT radii it needs

The first tier needs only reachability, which is a MAXIMISATION of one linear form over the body and
is solved exactly below -- no polytope object, no certified-path surgery. So its breakpoint is exact
under the true L1 relocation body and does not inherit the inscribed box's conservatism.

But there are TWO breakpoints, because SAFE is not the complement of REJECT. The registered rows
(`CertiTherm/thermal_constraints.py`) are

    SAFE     r . p <= limit - margin - error - ambient
    REJECT   r . p >= limit + margin - error - ambient

so a map landing in the `2 * margin` band between them is NEITHER, and "no REJECT map exists" does
NOT imply "every admissible map is SAFE". Peer review raised exactly this and it is true of this
implementation. The two radii answer two different questions and must not be conflated:

    beta*_reject   smallest budget at which some admissible map is REJECT.
                   Below it there is no SAFE/REJECT pair to tell apart, so the minimum-cost
                   OBSERVATION is zero -- an identifiability statement.
    beta*_safe     smallest budget at which some admissible map fails a SAFE row.
                   Below it every admissible map is certified SAFE -- a FEASIBILITY statement,
                   and the one a designer means by "this design is robustly feasible".

`beta*_safe <= beta*_reject` always, since the SAFE right-hand side is lower by `2 * margin`. Both
come from the same closed form with different floors, so reporting only one was a choice and not a
limitation; reporting `beta*_reject` while claiming feasibility was the error.

The distinction is not conservatism, it is a REVERSED IMPLICATION, and getting it wrong is the
error this file exists to make impossible. Containment transfers asymmetrically:

    on an INNER set (subset of L1)      on an OUTER set (superset of L1)
    a REJECT map exists          -> L1  no REJECT map exists         -> L1
    a coarse-blind pair exists   -> L1  coarse suffices for every map-> L1
    cost is AT LEAST c           -> L1  cost is AT MOST c            -> L1

So EXISTENCE and LOWER bounds travel up from an inner set, and UNIVERSAL safety and UPPER bounds
travel down from an outer one. "No measurement is needed" is a universal-safety claim, so it needs
the exact body or an OUTER approximation -- never the inscribed box. On
`arch_a`/`default`/`resnet50` the inscribed box reaches no reject floor even at `b = 1.0` while the
exact body reaches one at `b = 4.1%`: reading the first as "safe at any relocation budget" would
have overstated the design's robustness by more than an order of magnitude, and it would have been
unsound rather than merely loose. Peer review caught exactly that claim in an earlier draft.

The concentrated relocations the inscribed box drops -- the whole budget onto one block -- are
precisely the ones that make a hotspot, so the omission is adversarially selected against the
conclusion it was being used to support.

This file is the tracked home of `radius_l1`, which produced numbers already quoted in
`docs/THERMAL_ROBUSTNESS_RADII.md` while living only in an untracked scratch directory on the
execution host. That is a provenance hole and closing it is the reason the file exists at all.

NON-CLAIM diagnostic.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

BISECTION_STEPS = 20


def _validated(rows, floors, placed):
    """Shapes and finiteness, before anything reads them.

    `zip(rows, floors)` truncates silently when the two disagree, so a mismatched pair would have
    scanned a PREFIX of the reject cells and reported a larger radius than the instance supports --
    and the zero-budget path, which compares with NumPy broadcasting rather than `zip`, would have
    used a DIFFERENT set of cells from the positive-budget path in the same call. Peer review found
    both. Neither has any symptom other than the wrong answer, so the check is unconditional.
    """

    q = np.asarray(placed, dtype=float)
    row_array = np.atleast_2d(np.asarray(rows, dtype=float))
    floor_array = np.atleast_1d(np.asarray(floors, dtype=float))
    if q.ndim != 1 or q.size == 0:
        raise ValueError("the placed power map must be a non-empty one-dimensional vector")
    if row_array.ndim != 2 or row_array.shape[1] != q.size:
        raise ValueError(
            f"reject rows must be (cells, blocks) matching the power map: got {row_array.shape} "
            f"against {q.size} blocks"
        )
    if floor_array.ndim != 1 or floor_array.size != row_array.shape[0]:
        raise ValueError(
            f"one floor per reject cell is required: got {floor_array.size} floors for "
            f"{row_array.shape[0]} rows"
        )
    if row_array.shape[0] == 0:
        raise ValueError(
            "no reject cells were supplied; an empty family has no reachability question and "
            "returning a radius for it would assert robustness that was never computed"
        )
    if not (np.all(np.isfinite(row_array)) and np.all(np.isfinite(floor_array))):
        raise ValueError("reject rows and floors must all be finite to decide reachability")
    if not (np.all(np.isfinite(q)) and np.all(q >= 0.0)):
        raise ValueError("the placed power map must be finite and nonnegative")
    return row_array, floor_array, q


def reject_reachable_l1(rows, floors, placed, relocated_fraction) -> bool:
    """Is any map within the exact L1 relocation budget REJECT?

    Lifted as `p = q + u - v`, `u, v >= 0`, with `sum(u) = sum(v)` conserving the total and
    `sum(u) + sum(v) <= 2 b Q` the transfer budget. `v - u <= q` keeps `p >= 0`. One LP per reject
    cell; the first cell that reaches its floor answers the question.
    """

    # Finiteness is checked BEFORE any comparison and separately, because `x >= nan` is False: a
    # non-finite floor would read as "this cell is not reachable" and the radius would be reported
    # LARGER than was established, which is the fail-open direction for a robustness radius.
    row_array, floor_array, q = _validated(rows, floors, placed)
    if not np.isfinite(relocated_fraction):
        raise ValueError(f"relocated_fraction must be finite, got {relocated_fraction}")
    n = q.size
    total = float(q.sum())
    if relocated_fraction <= 0.0:
        return bool(np.any(row_array @ q >= floor_array))

    a_ub = np.vstack((np.ones((1, 2 * n)), np.hstack((-np.eye(n), np.eye(n)))))
    b_ub = np.concatenate(([2.0 * relocated_fraction * total], q))
    a_eq = np.hstack((np.ones((1, n)), -np.ones((1, n))))
    bounds = [(0.0, None)] * (2 * n)
    for row, floor in zip(row_array, floor_array):
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


def radius_l1_closed_form(rows, floors, placed) -> float:
    """The exact relocation radius with no solver at all, by inverting the transfer greedy.

    No INDEPENDENT per-block upper bound applies inside this body -- conservation and nonnegativity
    already imply `p_i <= Q`, so "nothing bounds `p` from above" would be literally false -- and that
    is enough for all received power to go to the single largest-coefficient block. Donations are
    taken from the smallest coefficients first, each capped by that block's own power. The gain is
    therefore

        gain(t) = sum over donors in ascending r of min(q_i, remaining) * (r_max - r_i)

    which is NONDECREASING, concave and piecewise linear in the transferred amount `t` -- flat once
    the useful donors are exhausted, and flat throughout for a constant row -- so the smallest `t`
    reaching a floor is read off directly instead of bisected. "Exact" here means analytically exact
    up to floating-point evaluation, not exact arithmetic. That makes the radius `O(cells *
    n log n)` and exact, where the lifted LP is `O(cells * bisection)` solves of `2n` variables --
    the difference between seconds and hours on a 273-block instance, which is why the sweep grew a
    closed form rather than a faster bisection.

    `test_l1_relocation_body.py` checks this against `reject_reachable_l1`, so the LP remains the
    oracle and this remains the accelerator; if they ever disagree the tests fail rather than the
    faster one silently winning.
    """

    row_array, floor_array, q = _validated(rows, floors, placed)
    total = float(q.sum())
    if total <= 0.0:
        raise ValueError("the placed power map must have a positive total")

    best = float("inf")
    for row, floor in zip(row_array, floor_array):
        needed = float(floor) - float(row @ q)
        if needed <= 0.0:
            return 0.0                      # the nominal map already reaches this floor
        receiver = int(np.argmax(row))
        gains = float(row[receiver]) - row  # per unit donated, by block
        order = np.argsort(row)             # cheapest donors first
        moved = 0.0
        gained = 0.0
        for index in order:
            index = int(index)
            if index == receiver or gains[index] <= 0.0:
                continue
            capacity = float(q[index])
            if gained + capacity * gains[index] >= needed:
                moved += (needed - gained) / gains[index]
                gained = needed
                break
            moved += capacity
            gained += capacity * gains[index]
        if gained < needed:
            continue                        # this floor is out of reach at any budget
        # `moved` is the transferred amount t; the registered parameter is t / total.
        best = min(best, moved / total)
    return best


def radii_l1(thermal_rows, reject_floors, safe_rhs, placed):
    """Both breakpoints at once: identifiability (`beta*_reject`) and feasibility (`beta*_safe`).

    Same closed form, different right-hand sides. Returned together so a caller cannot quote one
    while meaning the other -- which is the mistake this pair exists to prevent.
    """

    reject = radius_l1_closed_form(thermal_rows, reject_floors, placed)
    safe = radius_l1_closed_form(thermal_rows, safe_rhs, placed)
    if safe > reject + 1e-12:
        raise RuntimeError(
            f"the SAFE radius {safe} exceeds the REJECT radius {reject}, which the 2*margin gap "
            "between the two right-hand sides makes impossible; the rows or floors are mismatched"
        )
    return {"beta_star_safe": safe, "beta_star_reject": reject}


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
