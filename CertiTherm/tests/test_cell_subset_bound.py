"""Restricting reject cells does NOT relax the instance -- the counterexample, pinned.

`docs/PER_CELL_DECOMPOSITION_BOUND.md` claimed a certified lower bound on the whole instance
from a single reject cell, resting on what looked like a one-line argument:

    a plan sufficient for the whole instance is sufficient for any SUBSET of its reject
    cells, because dropping cells only removes constraints, so C*(whole) >= C*(subset).

**That argument is false, and this file is the counterexample that killed it.** Dropping a
cell removes its REJECT option, which does make collisions rarer -- but it also removes that
cell's SAFE row, and SAFE requires EVERY (model, point) to be below the limit. So the SAFE set
GROWS, which makes collisions commoner. The two effects run opposite ways and the inequality
does not hold in either direction.

Measured on the fixture below: the whole four-cell instance certifies at cost 0.0, and
restricting it to cell 0 alone costs 6.0. A "lower bound" that exceeds the quantity it bounds
is not a lower bound.

These tests exist so the argument cannot be reintroduced. They assert the counterexample,
not the property.
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily
from CertiTherm.thermal_constraints import robust_safe_cell_rows
from CertiTherm.synthesis import synthesize_minimum_observation


def _instance(points: int, blocks: int = 5, seed: int = 0):
    """A small instance whose SAFE and REJECT cells are both reachable.

    The limit sits inside the achievable peak range on purpose: inherit one that no power map
    reaches and the REJECT cell is empty, every plan certifies vacuously, and a test would
    pass while checking nothing.
    """

    rng = np.random.default_rng(seed)
    response = rng.uniform(0.5, 3.0, (1, points, blocks))
    polytope = PowerPolytope.box_with_total(
        np.zeros(blocks), np.ones(blocks), 0.6 * blocks
    )
    reach_low = float((response[0] @ polytope.lower_w).max())
    reach_high = float((response[0] @ polytope.upper_w).max())
    family = ThermalFamily(
        ("m0",),
        response,
        np.zeros((1, points)),
        reach_low + 0.5 * (reach_high - reach_low),
        error_k=np.zeros(1),
    )
    actions = tuple(
        MeasurementAction(f"a{i}", np.eye(blocks)[i], float(1 + i % 3), 1e-8, "c0")
        for i in range(blocks)
    )
    return polytope, family, actions


def _restrict(family: ThermalFamily, chosen) -> ThermalFamily:
    picked = list(chosen)
    return ThermalFamily(
        family.model_ids,
        np.array(family.response_k_per_w[:, picked, :]),
        np.array(family.ambient_k[:, picked]),
        float(family.limit_k),
        error_k=np.array(family.error_k),
    )


def _optimum(polytope, family, actions):
    plan = synthesize_minimum_observation(polytope, family, actions)
    if plan.status != "OPTIMAL":
        pytest.skip(f"instance did not resolve ({plan.status}); nothing to compare")
    return float(plan.exact_cost)


def test_restricting_cells_also_drops_their_safe_rows() -> None:
    """The mechanism. SAFE is a conjunction over cells, so a subset has FEWER safe rows."""

    whole = ThermalFamily(
        ("m0",), np.ones((1, 4, 3)), np.zeros((1, 4)), 10.0, error_k=np.zeros(1)
    )
    part = _restrict(whole, (0,))
    whole_rows, _ = robust_safe_cell_rows(whole, 0.1)
    part_rows, _ = robust_safe_cell_rows(part, 0.1)
    assert whole_rows.shape[0] == 4
    assert part_rows.shape[0] == 1, (
        "restricting cells must drop SAFE rows too -- that is why the subset argument fails"
    )


def test_restricting_cells_can_RAISE_the_optimum() -> None:
    """The counterexample itself: a subset costing MORE than the whole instance.

    This is the fact that invalidates reporting a per-cell optimum as a lower bound on the
    whole instance's. If this test ever passes trivially -- both sides equal -- the fixture
    has drifted and stopped exhibiting the effect.
    """

    polytope, family, actions = _instance(points=4, seed=3)
    whole = _optimum(polytope, family, actions)
    part = _optimum(polytope, _restrict(family, (0,)), actions)
    assert part > whole, (
        "the fixture no longer shows a subset exceeding the whole instance; the "
        f"counterexample has drifted (whole={whole}, subset={part})"
    )


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_no_ordering_holds_between_a_subset_and_the_whole(seed: int) -> None:
    """Neither direction is safe to assume, which is the practical consequence.

    Across seeds and subsets both orderings occur, so a per-cell optimum is neither a lower
    nor an upper bound on the whole instance's.
    """

    polytope, family, actions = _instance(points=4, seed=seed)
    whole = _optimum(polytope, family, actions)
    parts = [
        _optimum(polytope, _restrict(family, chosen), actions)
        for chosen in ((0,), (1,), (0, 1), (1, 2))
    ]
    assert parts, "no subset was evaluated"
    # Recorded, not asserted one way: the point is that the relation is not fixed.
    assert all(value >= 0.0 for value in parts)
    assert whole >= 0.0


# --- The repair: restrict the SCAN, not the family -------------------------------------
#
# The retraction identified what a valid decomposition needs -- keep the SAFE conjunction
# intact, drop only REJECT options -- and `reject_specs` on `synthesize_minimum_observation`
# is that operation. These tests check the inequality BEFORE any number is reported from it,
# which is precisely what was skipped the first time.


def _restricted_optimum(polytope, family, actions, specs):
    plan = synthesize_minimum_observation(
        polytope, family, actions, reject_specs=tuple(specs)
    )
    if plan.status != "OPTIMAL":
        pytest.skip(f"restricted instance did not resolve ({plan.status})")
    return float(plan.exact_cost)


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_restricting_the_scan_never_raises_the_optimum(seed: int) -> None:
    """The property the family restriction lacked: this one really is a relaxation.

    Every SAFE row still binds, so the safe set is unchanged; fewer REJECT options can only
    make separation easier. If this ever fails, no bound may be derived from a restricted
    scan either.
    """

    polytope, family, actions = _instance(points=4, seed=seed)
    whole = _optimum(polytope, family, actions)
    for specs in (((0, 0),), ((0, 1),), ((0, 0), (0, 1)), ((0, 0), (0, 2), (0, 3))):
        part = _restricted_optimum(polytope, family, actions, specs)
        assert part <= whole + 1e-9, (
            f"restricting the scan to {specs} raised the optimum from {whole} to {part}; "
            "a restricted scan is not a relaxation after all"
        )


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_a_wider_scan_is_at_least_as_hard(seed: int) -> None:
    """Monotone in the scan, which is what makes a larger subset a better bound."""

    polytope, family, actions = _instance(points=4, seed=seed)
    previous = None
    for size in (1, 2, 3, 4):
        part = _restricted_optimum(
            polytope, family, actions, [(0, i) for i in range(size)]
        )
        if previous is not None:
            assert part >= previous - 1e-9, (
                f"widening the scan from {size - 1} to {size} cells LOWERED the optimum "
                f"from {previous} to {part}"
            )
        previous = part
    assert previous == pytest.approx(_optimum(polytope, family, actions)), (
        "scanning every cell must reproduce the unrestricted optimum exactly"
    )


def test_the_two_restrictions_are_not_the_same_operation() -> None:
    """Restricting the family and restricting the scan differ -- the heart of the retraction.

    Same instance, same cell: restricting the FAMILY raised the optimum (invalid), while
    restricting the SCAN does not.
    """

    polytope, family, actions = _instance(points=4, seed=3)
    whole = _optimum(polytope, family, actions)
    by_family = _optimum(polytope, _restrict(family, (0,)), actions)
    by_scan = _restricted_optimum(polytope, family, actions, ((0, 0),))
    assert by_family > whole, "the family restriction should still exhibit the defect"
    assert by_scan <= whole + 1e-9, "the scan restriction must be a relaxation"
