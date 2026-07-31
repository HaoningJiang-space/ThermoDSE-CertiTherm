"""The exact L1 relocation radius, checked against a closed form and against both approximations.

Three uncertainty sets are in play and their radii must come out in a fixed order, because the sets
nest:

    deviation box  |p_i - q_i| <= b Q          CONTAINS the L1 body   -> reaches a floor SOONEST
    L1 body        |p - q|_1   <= 2 b Q        the physical statement
    inscribed box  |p_i - q_i| <= b Q/floor(n/2) CONTAINED in it      -> reaches a floor LATEST

so `radius_deviation <= radius_L1 <= radius_inscribed`. That ordering is the whole reason the three
were separated, and the measured values on `arch_a`/`default`/`resnet50` obey it by a wide margin
(2.637%, 4.1%, unreachable through 100%). A regression that collapsed two of the sets, or that got a
containment backwards, would break this test rather than silently relabel a headline number -- which
is exactly what happened before the split.

`reject_reachable_l1` is also checked against a CLOSED FORM rather than against itself: for a single
reject row the optimum is greedy -- fill the largest coefficient, drain the smallest -- so the LP has
an answer that can be written down independently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research" / "triangle" / "robustness"))

from l1_body import (  # noqa: E402
    radii_l1,
    radius_l1,
    radius_l1_closed_form,
    reject_reachable_l1,
)

from CertiTherm.measurements import (  # noqa: E402
    deviation_bounded_power_space,
    relocation_bounded_power_space,
)

_Q = np.array([4.0, 3.0, 2.0, 1.0])
_TOTAL = float(_Q.sum())


def _closed_form_max(row: np.ndarray, q: np.ndarray, fraction: float) -> float:
    """Greedy optimum of `max r.p` over the L1 body: move budget from coldest blocks to the hottest.

    Draining is capped by each block's own power, since `p >= 0`. Written independently of the LP so
    that agreement is evidence rather than a tautology.
    """

    budget = fraction * float(q.sum())
    order = np.argsort(row)                       # ascending coefficient: drain these first
    hottest = int(np.argmax(row))
    moved = 0.0
    gain = 0.0
    for index in order:
        if index == hottest or moved >= budget:
            continue
        take = min(float(q[index]), budget - moved)
        gain += take * (float(row[hottest]) - float(row[index]))
        moved += take
    return float(row @ q) + gain


def _box_reachable(space, rows, floors) -> bool:
    """Greedy exact maximisation over a box with the total conserved, for the ordering test."""

    lower = np.asarray(space.lower_w, dtype=float)
    upper = np.asarray(space.upper_w, dtype=float)
    for row, floor in zip(np.asarray(rows, dtype=float), np.asarray(floors, dtype=float)):
        p = lower.copy()
        spare = _TOTAL - float(p.sum())
        for i in np.argsort(-row):
            add = min(upper[i] - p[i], spare)
            p[i] += add
            spare -= add
            if spare <= 1e-12:
                break
        if float(row @ p) >= float(floor):
            return True
    return False


def _box_radius(build, key, rows, floors) -> float:
    lo, hi = 0.0, 1.0
    if not _box_reachable(build(_Q, **{key: hi}), rows, floors):
        return float("inf")
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        if _box_reachable(build(_Q, **{key: mid}), rows, floors):
            hi = mid
        else:
            lo = mid
    return hi


def test_the_lifted_lp_reproduces_the_closed_form_optimum() -> None:
    """Agreement with an independently written greedy, at several budgets."""

    row = np.array([1.0, 0.4, 0.2, 0.1])
    for fraction in (0.02, 0.1, 0.3):
        target = _closed_form_max(row, _Q, fraction)
        # Bracketing the floor around the closed-form optimum turns the boolean LP into a
        # measurement of that optimum: just below it must be reachable, just above must not.
        assert reject_reachable_l1([row], [target - 1e-6], _Q, fraction)
        assert not reject_reachable_l1([row], [target + 1e-6], _Q, fraction)


def test_a_nominally_rejecting_design_has_radius_zero_not_a_small_positive_number() -> None:
    """Bisection without this test returns 2^-20 and fabricates a safe interval below it."""

    row = np.array([1.0, 1.0, 1.0, 1.0])
    floor = float(row @ _Q) - 1.0                 # the nominal map already exceeds it
    assert radius_l1([row], [floor], _Q) == 0.0


def test_an_unreachable_floor_gives_an_infinite_radius() -> None:
    row = np.array([1.0, 0.4, 0.2, 0.1])
    unreachable = _closed_form_max(row, _Q, 1.0) + 1.0
    assert radius_l1([row], [unreachable], _Q) == float("inf")


def test_the_radius_is_monotone_in_the_floor() -> None:
    """A tighter floor must be reached at a smaller budget, or a sweep is not a robustness curve."""

    row = np.array([1.0, 0.4, 0.2, 0.1])
    nominal = float(row @ _Q)
    radii = [radius_l1([row], [nominal + gap], _Q) for gap in (0.2, 0.5, 1.0)]
    assert radii[0] < radii[1] < radii[2], radii


def test_the_three_geometries_reach_a_floor_in_the_order_their_containments_force() -> None:
    """deviation <= L1 <= inscribed, because deviation contains L1 contains inscribed."""

    row = np.array([1.0, 0.4, 0.2, 0.1])
    floor = float(row @ _Q) + 0.5
    rows, floors = [row], [floor]

    deviation = _box_radius(deviation_bounded_power_space, "deviation_fraction", rows, floors)
    exact = radius_l1(rows, floors, _Q)
    inscribed = _box_radius(relocation_bounded_power_space, "relocated_fraction", rows, floors)

    assert deviation <= exact + 1e-6, (
        f"the deviation box is a SUPERSET of the L1 body so it cannot need a larger radius: "
        f"{deviation} against {exact}"
    )
    assert exact <= inscribed + 1e-6, (
        f"the inscribed box is a SUBSET of the L1 body so it cannot need a smaller radius: "
        f"{exact} against {inscribed}"
    )
    assert deviation < inscribed, (
        "the two boxes came out equal, so the split that this ordering exists to protect has "
        "collapsed and a bound could again be quoted under the wrong geometry"
    )


def test_a_solver_failure_is_raised_rather_than_read_as_unreachable() -> None:
    """Fail-closed: an unsolved maximisation must not be reported as a larger robustness radius."""

    with pytest.raises(Exception):
        # A non-finite floor makes the comparison meaningless; the guard must not return False.
        reject_reachable_l1([np.array([1.0, 0.4, 0.2, 0.1])], [float("nan")], _Q, 0.1)


def test_the_closed_form_radius_agrees_with_the_lp_oracle() -> None:
    """The accelerator must not be its own oracle: it is checked against the lifted LP.

    A second implementation can reproduce the first's bug and still agree, so the two here are
    deliberately unlike -- one inverts a sorted greedy, the other solves a lifted linear program --
    and the LP stays the definition.
    """

    rng = np.random.default_rng(7)
    for trial in range(12):
        n = int(rng.integers(3, 9))
        q = np.round(rng.uniform(0.2, 5.0, n), 3)
        rows = np.round(rng.uniform(0.05, 2.0, (2, n)), 3)
        nominal = rows @ q
        floors = nominal + rng.uniform(0.05, 1.5, 2)

        fast = radius_l1_closed_form(rows, floors, q)
        slow = radius_l1(rows, floors, q)
        if not np.isfinite(fast) and not np.isfinite(slow):
            continue
        assert abs(fast - slow) < 2e-5, (
            f"trial {trial}: closed form {fast} disagrees with the LP bisection {slow}"
        )
        # And the closed form must actually be a radius: just above it reachable, just below not.
        assert reject_reachable_l1(rows, floors, q, fast + 1e-6)
        assert not reject_reachable_l1(rows, floors, q, max(fast - 1e-4, 0.0))


def test_the_closed_form_returns_zero_for_a_nominally_rejecting_design() -> None:
    row = np.ones(4)
    assert radius_l1_closed_form([row], [float(row @ _Q) - 1.0], _Q) == 0.0


def test_the_closed_form_returns_infinity_when_no_transfer_reaches_a_floor() -> None:
    """Donor power is finite, so a high enough floor is out of reach at ANY budget."""

    row = np.array([1.0, 0.4, 0.2, 0.1])
    unreachable = _closed_form_max(row, _Q, 1.0) + 1.0
    assert radius_l1_closed_form([row], [unreachable], _Q) == float("inf")


def test_the_safe_radius_never_exceeds_the_reject_radius() -> None:
    """SAFE is not the complement of REJECT, and conflating the two overstates feasibility.

    The registered rows put SAFE at `limit - margin - error - ambient` and REJECT at
    `limit + margin - error - ambient`, so a map in the `2*margin` band is neither. A design can
    therefore stop being certifiably SAFE strictly before any map becomes REJECT, and quoting the
    REJECT radius as a feasibility radius claims robustness the rows do not support.
    """

    row = np.array([1.0, 0.4, 0.2, 0.1])
    nominal = float(row @ _Q)
    margin = 0.05
    reject_floor = nominal + 0.5 + margin
    safe_rhs = nominal + 0.5 - margin

    both = radii_l1([row], [reject_floor], [safe_rhs], _Q)
    assert both["beta_star_safe"] <= both["beta_star_reject"]
    assert both["beta_star_safe"] < both["beta_star_reject"], (
        "the two radii came out equal, so the fixture no longer has a band between the rows and "
        "the property it exists to protect is untested"
    )


def test_mismatched_rows_are_refused_rather_than_reported_as_a_wider_safe_radius() -> None:
    """A SAFE radius above the REJECT radius is impossible; it means the inputs were swapped."""

    row = np.array([1.0, 0.4, 0.2, 0.1])
    nominal = float(row @ _Q)
    with pytest.raises(RuntimeError):
        radii_l1([row], [nominal + 0.2], [nominal + 0.8], _Q)   # rhs swapped on purpose
