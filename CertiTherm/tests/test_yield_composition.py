"""Refinement-monotonicity, executed rather than asserted, plus the guards that stop a silent zero.

The general claim this project makes about chiplet-count decisions rests on one proposition:

    An area-weighted arithmetic MEAN of a strictly decreasing per-die yield function increases
    under EVERY refinement, at EVERY parameter value.

which follows in one line -- splitting a die of area `a` into `a'` and `a''` replaces `Y(a+c)` with
two strictly larger values carrying the same total weight -- and which means such an aggregate can
never argue against cutting. The conclusion is about the AGGREGATION, so it applies to any DSE that
reports a scalar yield this way, not to one evaluator. A proposition that general should be executed
against the code that computes it rather than believed from prose, which is what these tests do.

The two standard alternatives must fail refinement-monotonicity in the opposite direction, or they
would not price count risk either: the all-dies-good product falls under refinement whenever total
silicon does not shrink, and a bonded aggregate falls geometrically in the count.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research" / "triangle" / "robustness"))

from yield_composition import BONDING_YIELD, compositions, die_yield  # noqa: E402


def test_the_registered_yield_is_strictly_decreasing_in_die_area() -> None:
    """The premise of the proposition. Everything below is vacuous without it."""

    areas = np.linspace(1e-5, 5e-4, 40)
    values = [die_yield(float(a)) for a in areas]
    assert all(later < earlier for earlier, later in zip(values, values[1:]))
    assert all(0.0 < v <= 1.0 for v in values)


def test_the_area_weighted_mean_rises_under_every_refinement() -> None:
    """One die -> two -> four, at a fixed total, with no overhead: the mean can only go up."""

    edge = 2e-2
    means = []
    for cuts in (1, 2, 4):
        heights = np.full(cuts, edge / cuts)
        widths = np.array([edge])
        means.append(compositions(heights, widths, 0.0)["yield_mean"])
    assert means[0] < means[1] < means[2], (
        f"the weighted mean did not rise under refinement ({means}); the proposition the "
        "chiplet-count argument rests on does not hold for this implementation"
    )


def test_the_product_falls_under_the_same_refinement() -> None:
    """The contrast that makes the proposition informative rather than a tautology about means."""

    edge = 2e-2
    products = []
    for cuts in (1, 2, 4):
        heights = np.full(cuts, edge / cuts)
        products.append(compositions(heights, np.array([edge]), 0.0)["yield_product"])
    assert products[0] > products[1] > products[2], (
        f"the all-dies-good product did not fall under refinement ({products}); if both "
        "compositions moved the same way the chiplet-count decision would be invariant and there "
        "would be nothing to report"
    )


def test_per_die_overhead_makes_refinement_strictly_worse_for_the_product() -> None:
    """Overhead is charged once per die, so it must widen the gap the refinement opens."""

    edge = 2e-2
    overhead = 1e-6
    without = [compositions(np.full(c, edge / c), np.array([edge]), 0.0)["yield_product"]
               for c in (1, 4)]
    with_overhead = [compositions(np.full(c, edge / c), np.array([edge]), overhead)["yield_product"]
                     for c in (1, 4)]
    assert with_overhead[1] / with_overhead[0] < without[1] / without[0]


def test_bonding_makes_the_bonded_product_fall_geometrically_in_the_count() -> None:
    edge = 2e-2
    for cuts in (1, 2, 4):
        derived = compositions(np.full(cuts, edge / cuts), np.array([edge]), 0.0)
        assert derived["yield_product_with_bonding"] == pytest.approx(
            derived["yield_product"] * BONDING_YIELD ** cuts
        )
        assert derived["bonding_penalty"] == pytest.approx(1.0 / BONDING_YIELD ** cuts - 1.0)


def test_the_mean_is_a_genuine_weighted_mean_on_unequal_dies() -> None:
    """The weights must sum to one, or none of the compositions means what it says.

    Unequal dies on purpose: with equal dies a mean, a median and a mid-range all agree, so the
    fixture would pass for an implementation that is none of them.
    """

    heights = np.array([3e-2, 2e-2])
    widths = np.array([4e-2, 1e-2])
    derived = compositions(heights, widths, 0.0)
    areas = np.outer(heights, widths).reshape(-1)
    yields = np.array([die_yield(float(a)) for a in areas])
    weights = areas / (heights.sum() * widths.sum())

    assert float(weights.sum()) == pytest.approx(1.0)
    assert derived["yield_mean"] == pytest.approx(float((weights * yields).sum()))
    assert derived["yield_mean"] > derived["yield_product"]
    assert len(set(np.round(areas, 12))) > 1, "the fixture stopped having unequal dies"


def test_a_negative_or_non_finite_nop_area_is_refused() -> None:
    """Nonnegativity as well as finiteness: a negative overhead raises every yield silently."""

    edge = np.array([2e-2])
    for bad in (-1e-6, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            compositions(edge, edge, bad)


def test_a_die_large_enough_to_underflow_its_yield_is_refused_not_composed() -> None:
    """Without the guard the log and the division produce -inf and inf with no other symptom.

    The threshold is checked rather than guessed: the first fixture written here used a 1e6 m edge,
    whose yield is 9.3e-140 -- finite, positive, and correctly NOT refused. A test that fires on an
    input the guard is right to accept would have been reporting the guard broken.
    """

    assert die_yield(1e12) > 0.0, "the accepted side of the boundary must stay accepted"
    compositions(np.array([1e6]), np.array([1e6]), 0.0)

    assert die_yield(1e32) == 0.0, "the fixture no longer underflows, so it tests nothing"
    with pytest.raises(ValueError):
        compositions(np.array([1e16]), np.array([1e16]), 0.0)


def test_degenerate_edge_lists_are_refused() -> None:
    for heights, widths in (
        (np.array([]), np.array([1e-2])),
        (np.array([0.0]), np.array([1e-2])),
        (np.array([-1e-2]), np.array([1e-2])),
        (np.array([[1e-2]]), np.array([1e-2])),
    ):
        with pytest.raises(ValueError):
            compositions(heights, widths, 0.0)
