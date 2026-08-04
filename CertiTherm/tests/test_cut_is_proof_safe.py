"""The separator cut must be a superset of the true separators, in REAL arithmetic.

Theorem 1 lets the hitting-set master use each cut as a necessary constraint. That is only
valid if the cut contains every action that genuinely separates the witness: a cut missing
one is a SUBSET, a too-strong constraint, and it can push the master optimum above C* and
inflate the certified lower bound.

`abs(v @ delta)` is a single binary64 dot product. At the boundary it can round to just
below `tolerance` while the exact real value is just above -- excluding a genuine separator.
A differential against a previous implementation cannot detect this, because every
implementation used the same dot product and they round together; peer review named it and
these tests construct it.

The rule is therefore stated over an outward upper bound: an action is dropped only when
`outward_abs_dot_upper` PROVES it cannot exceed its tolerance. The uncertain case falls on
the include side, where an extra action is merely a weaker constraint.
"""

from __future__ import annotations

import fractions

import numpy as np

from CertiTherm.collision_proof import outward_abs_dot_upper
from CertiTherm.core import MeasurementAction, WorldPair
from CertiTherm.synthesis import separating_action_cut


def _exact_abs_dot(left: np.ndarray, right: np.ndarray) -> fractions.Fraction:
    """Exact |left . right| in rationals -- the ground truth binary64 can only approximate."""

    return abs(
        sum(
            fractions.Fraction(float(a)) * fractions.Fraction(float(b))
            for a, b in zip(left, right)
        )
    )


def _witness(delta: np.ndarray) -> WorldPair:
    zero = np.zeros_like(delta)
    return WorldPair(delta, zero, "safe", "unsafe", zero)


def test_outward_bound_never_falls_below_the_exact_magnitude() -> None:
    """The property the whole guard rests on, checked against rational arithmetic."""

    rng = np.random.default_rng(11)
    for _ in range(120):
        n = int(rng.integers(2, 40))
        rows = rng.normal(0, 10 ** rng.uniform(-3, 3), (3, n))
        vector = rng.normal(0, 10 ** rng.uniform(-3, 3), n)
        bounds = outward_abs_dot_upper(rows, vector)
        for row, bound in zip(rows, bounds):
            assert fractions.Fraction(float(bound)) >= _exact_abs_dot(row, vector)


def test_a_separator_at_one_ulp_below_its_tolerance_stays_in_the_cut() -> None:
    """The constructed defect: binary64 says "not a separator", real arithmetic disagrees.

    `tolerance` is placed exactly one ulp above the computed dot product, so the old
    `abs(float(v @ delta)) > tolerance` test is false and the action would be dropped.
    """

    rng = np.random.default_rng(3)
    found = 0
    for _ in range(4000):
        vector = rng.normal(0, 1, 8)
        delta = rng.normal(0, 1, 8)
        computed = abs(float(vector @ delta))
        tolerance = float(np.nextafter(computed, np.inf))
        if tolerance <= computed:
            continue
        action = MeasurementAction("a", vector, 1.0, tolerance, "c")
        cut = separating_action_cut(_witness(delta), (action,), ())
        assert not computed > tolerance, "fixture must sit below the threshold in binary64"
        assert cut[0] == 1.0, "an unprovable non-separator must stay in the cut"
        found += 1
        if found >= 25:
            break
    assert found >= 25, "could not construct the boundary case; the fixture is not testing it"


def test_the_cut_is_a_superset_of_the_plain_binary64_rule() -> None:
    """Whatever the old rule included, the new rule must still include."""

    rng = np.random.default_rng(9)
    for _ in range(400):
        n, count = int(rng.integers(2, 30)), int(rng.integers(1, 10))
        delta = rng.normal(0, 1, n)
        actions = tuple(
            MeasurementAction(
                f"a{i}", rng.normal(0, 1, n), 1.0, float(10 ** rng.uniform(-9, -1)), "c"
            )
            for i in range(count)
        )
        selected = tuple(
            sorted(rng.choice(count, int(rng.integers(0, count + 1)), replace=False).tolist())
        )
        new = separating_action_cut(_witness(delta), actions, selected)
        old = np.asarray(
            [
                index not in set(selected)
                and abs(float(action.vector @ delta)) > action.tolerance
                for index, action in enumerate(actions)
            ],
            dtype=float,
        )
        assert np.all(new >= old), "the proof-safe cut dropped an action the plain rule kept"


def test_a_clear_non_separator_is_still_excluded() -> None:
    """Non-vacuity: widening the rule must not make every action a separator."""

    delta = np.array([1.0, 0.0, 0.0])
    orthogonal = MeasurementAction("a", np.array([0.0, 1.0, 0.0]), 1.0, 1e-8, "c")
    aligned = MeasurementAction("b", np.array([1.0, 0.0, 0.0]), 1.0, 1e-8, "c")
    cut = separating_action_cut(_witness(delta), (orthogonal, aligned), ())
    assert cut[0] == 0.0, "an exactly orthogonal action separates nothing"
    assert cut[1] == 1.0, "an aligned action separates and must be in the cut"


def test_a_selected_action_is_still_excluded_by_index() -> None:
    """The index exclusion is independent of the numerical rule and must survive it."""

    delta = np.array([1.0, 0.0])
    action = MeasurementAction("a", np.array([1.0, 0.0]), 1.0, 1e-8, "c")
    assert separating_action_cut(_witness(delta), (action,), ())[0] == 1.0
    assert separating_action_cut(_witness(delta), (action,), (0,))[0] == 0.0


def test_an_empty_action_library_yields_an_empty_cut() -> None:
    """The matrix stack has no rows to build; it must not raise."""

    assert separating_action_cut(_witness(np.ones(3)), (), ()).shape == (0,)


def test_single_polytope_synthesis_refuses_actions_from_several_candidates() -> None:
    """A plan for ONE candidate must not be assembled from another candidate's instruments.

    The API took the whole action list on trust: peer review found that three different
    candidate labels produced an OPTIMAL plan selecting one action from each -- a
    certificate resting on observations that are not obtainable where the decision is made.
    A contract violation surfaces as UNRESOLVED rather than raising, which is the
    fail-closed conversion the rest of the module uses.
    """

    from CertiTherm.core import PowerPolytope, ThermalFamily
    from CertiTherm.synthesis import synthesize_minimum_observation

    n = 4
    polytope = PowerPolytope.box_with_total(np.zeros(n), np.ones(n), 1.0)
    thermal = ThermalFamily(
        ("b",),
        np.array([[np.eye(n)[i] * 2.0 for i in range(n)]]),
        np.array([0.0]),
        1.0,
    )

    def actions(labels):
        return tuple(
            MeasurementAction(f"p{i}", np.eye(n)[i], 1.0, 1e-8, label)
            for i, label in enumerate(labels)
        )

    one = synthesize_minimum_observation(polytope, thermal, actions(["c0"] * n))
    assert one.status == "OPTIMAL", "a single-candidate library must still synthesize"

    mixed = synthesize_minimum_observation(
        polytope, thermal, actions(["c0", "c1", "c2", "c0"])
    )
    assert mixed.status == "UNRESOLVED"
    assert mixed.selected_action_ids == ()
    assert mixed.exact_cost is None
