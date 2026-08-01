"""The uncertainty set must be narrowable, and narrowing it must never be unsound.

Peer review named the breadth of `coarse_power_space` as the strongest attack on the certified
bound: it admits every nonnegative redistribution preserving the workload total, and
`content_upper_bounds` hands each block its whole content class's power without constraining the
class aggregate at all. A certificate derived from that may describe power maps no workload can
produce.

`activity_bounded_power_space` narrows it on two axes a designer can defend. These tests pin the
property that makes a sweep over `activity_span` a robustness curve rather than a tuning knob: a
LARGER span is a strictly weaker claim, so any bound proved under it holds under every tighter set.
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.cross_grid_bound import _extreme
from CertiTherm.measurements import (
    activity_bounded_power_space,
    coarse_power_space,
    content_upper_bounds,
)

_BLOCKS = ("mtxu_0", "mtxu_1", "ubuf_0", "ubuf_1")
_PLACED = np.array([2.0, 3.0, 1.0, 4.0])


def test_a_larger_span_contains_a_smaller_one() -> None:
    """Monotone in the span, which is what makes the sweep a robustness curve.

    If the sets were not nested, a bound at span 0.3 would say nothing about span 0.1 and the sweep
    would be a search for a flattering number instead of evidence.
    """

    tight = activity_bounded_power_space(_BLOCKS, _PLACED, activity_span=0.1)
    loose = activity_bounded_power_space(_BLOCKS, _PLACED, activity_span=0.5)
    assert np.all(loose.lower_w <= tight.lower_w)
    assert np.all(loose.upper_w >= tight.upper_w)
    assert np.all(loose.b_ub >= tight.b_ub), "class caps must widen with the span too"
    assert not np.allclose(loose.upper_w, tight.upper_w), "a fixture where nothing moves proves nothing"


def test_it_is_a_genuine_subset_of_the_registered_coarse_space() -> None:
    """Comparability, not just tightness: a bound proved here must speak about the frozen set.

    Without the content cap the two boxes CROSS -- a block whose placed power is near its class
    total gets `placed * (1 + span)` above that total -- and a bound proved under a set that is
    neither larger nor smaller says nothing about the registered one. A test caught that at span 0.3.
    """

    coarse = coarse_power_space(_PLACED, content_upper_bounds(_BLOCKS, _PLACED))
    bounded = activity_bounded_power_space(_BLOCKS, _PLACED, activity_span=0.3)
    assert np.all(bounded.upper_w <= coarse.upper_w), "the new set must not exceed the frozen one"
    assert np.any(bounded.upper_w < coarse.upper_w), "and must be strictly smaller somewhere"
    assert np.all(bounded.lower_w >= coarse.lower_w)
    # Including at a span wide enough that the uncapped box would have crossed it.
    wide = activity_bounded_power_space(_BLOCKS, _PLACED, activity_span=2.0)
    assert np.all(wide.upper_w <= coarse.upper_w)
    assert bounded.a_ub.shape[0] == 2, "one aggregate row per content class"
    assert coarse.a_ub.shape[0] == 0, "the registered space constrains no class aggregate at all"


def test_the_observed_placement_is_always_admitted() -> None:
    """A set excluding the map it was built from would certify against nothing real."""

    for span in (0.05, 0.2, 1.0):
        space = activity_bounded_power_space(_BLOCKS, _PLACED, activity_span=span)
        assert np.all(space.lower_w <= _PLACED) and np.all(_PLACED <= space.upper_w)
        assert abs(float(np.sum(_PLACED)) - float(space.b_eq[0])) < 1e-12
        assert np.all(space.a_ub @ _PLACED <= space.b_ub + 1e-12)


def test_class_totals_bind_across_classes_but_not_within() -> None:
    """The point of the class rows: they stop cross-class transfer and leave blind directions alone.

    A blind direction moves power between two blocks of ONE cell, and a cell sits inside one module,
    so the class row reads the same on both sides and cannot forbid it. That is the honest behaviour
    -- the constraint must narrow what it can defend and nothing else.
    """

    space = activity_bounded_power_space(_BLOCKS, _PLACED, activity_span=0.3)
    within = np.array([0.5, -0.5, 0.0, 0.0])
    across = np.array([0.5, 0.0, -0.5, 0.0])
    assert np.allclose(space.a_ub @ within, 0.0), "a within-class move must be invisible to the rows"
    assert not np.allclose(space.a_ub @ across, 0.0), "a cross-class move must be visible"


def test_a_span_that_excludes_the_total_is_refused() -> None:
    """An empty set would make every pair vacuously unconfusable and the bound zero."""

    with pytest.raises(ValueError, match="activity_span must be finite and positive"):
        activity_bounded_power_space(_BLOCKS, _PLACED, activity_span=0.0)
    with pytest.raises(ValueError, match="activity_span must be finite and positive"):
        activity_bounded_power_space(_BLOCKS, _PLACED, activity_span=float("nan"))


def test_class_rows_can_be_switched_off_without_changing_the_box() -> None:
    """The two axes are independent, so a sweep can attribute an effect to one of them."""

    with_rows = activity_bounded_power_space(_BLOCKS, _PLACED, activity_span=0.3)
    without = activity_bounded_power_space(
        _BLOCKS, _PLACED, activity_span=0.3, constrain_class_totals=False
    )
    assert np.allclose(with_rows.lower_w, without.lower_w)
    assert np.allclose(with_rows.upper_w, without.upper_w)
    assert without.a_ub.shape[0] == 0


def test_the_class_caps_are_implied_by_the_box_so_the_LP_path_is_currently_inert() -> None:
    """Why dropping `a_ub` at the call site changed no number, and when that would stop being true.

    Peer review found that the callers passed only `lower_w`/`upper_w`, silently maximising over a
    larger set. The defect was real and is fixed. The measured effect was zero, and this test says
    why: `upper = min(placed * (1 + span), content_upper_bounds) <= placed * (1 + span)`, so each
    class's members already sum to at most `class_total * (1 + span)`, which is exactly `b_ub`.

    **This is a property of the current construction, not a theorem about the method.** If the box
    ever stops implying the caps -- a different per-block rule, a tighter class budget -- the LP path
    becomes load-bearing and the bounds move. This test failing is the signal that has happened, and
    the message is what tells the next reader which way to go.
    """

    blocks = ["core0", "core1", "core2", "mem0", "mem1", "io0"]
    placed = np.array([4.0, 3.0, 2.0, 1.5, 1.0, 0.5])
    for span in (0.05, 0.3, 1.2):
        space = activity_bounded_power_space(blocks, placed, activity_span=span)
        rows = np.asarray(space.a_ub, dtype=float)
        assert rows.size, "the declared set is supposed to carry class-total rows"
        slack = np.asarray(space.b_ub, dtype=float) - rows @ np.asarray(space.upper_w, dtype=float)
        assert np.all(slack >= -1e-9), (
            f"at span {span} a class cap is BINDING (slack {slack.min():.3e}); the LP path is now "
            "load-bearing, so every bound must be recomputed with a_ub supplied and the documents "
            "that quote them are stale"
        )


def test_the_LP_and_the_greedy_agree_on_the_activity_set() -> None:
    """Two constructions of one supremum, on the set the certificate actually uses."""

    blocks = ["core0", "core1", "core2", "mem0", "mem1", "io0"]
    placed = np.array([4.0, 3.0, 2.0, 1.5, 1.0, 0.5])
    total = float(np.sum(placed))
    space = activity_bounded_power_space(blocks, placed, activity_span=0.3)
    lower = np.asarray(space.lower_w, dtype=float)
    upper = np.asarray(space.upper_w, dtype=float)
    rng = np.random.default_rng(5)
    for _ in range(20):
        coefficients = rng.normal(size=placed.size)
        greedy = _extreme(coefficients, lower, upper, total)
        constrained = _extreme(
            coefficients, lower, upper, total,
            np.asarray(space.a_ub, dtype=float), np.asarray(space.b_ub, dtype=float),
        )
        assert abs(greedy - constrained) < 1e-6, f"{greedy} against {constrained}"
