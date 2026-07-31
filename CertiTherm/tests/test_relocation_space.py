"""The two redistribution geometries differ, and only one of them lets a bound transfer to L1.

An earlier version of this file asserted the opposite of what is true, in prose and in a test: it
said the returned box CONTAINS the L1 body and that "a bound proved on a superset holds on the
subset". Both halves were wrong for the quantity being computed. A minimum-cost OBSERVATION bound is
not a bound on a scalar objective; enlarging the uncertainty set adds SAFE/REJECT collisions and can
only raise the cost, so a lower bound proved on a superset does not lower-bound the subset's
problem. The certified 1440 was reported as an L1 statement on that reasoning.

So the two sets are now separate functions with separate names, and these tests pin the
containment direction of each -- because that direction is the entire licence to quote a number.

    deviation_bounded_power_space   L-infinity ball, half-width e * total   SUPERSET of the L1 ball
    relocation_bounded_power_space  largest box inscribed in the L1 ball    SUBSET of the L1 ball

Only the second may support a sentence containing the word "relocation".
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.measurements import (
    deviation_bounded_power_space,
    relocation_bounded_power_space,
)

_PLACED = np.array([2.0, 3.0, 1.0, 4.0])
_TOTAL = float(_PLACED.sum())


def _l1_budget(fraction: float) -> float:
    """`|p - q|_1 <= 2 * fraction * total` is the L1 body both functions are compared against."""

    return 2.0 * fraction * _TOTAL


def test_the_relocation_box_lies_INSIDE_the_l1_body() -> None:
    """The containment that licenses quoting a box-derived bound as an L1 requirement.

    Every corner of the box must satisfy the L1 budget. Corners are the extreme points, so checking
    them checks the whole box -- and the all-corners-at-once corner is exactly the case the old
    superset box failed.
    """

    fraction = 0.1
    space = relocation_bounded_power_space(_PLACED, relocated_fraction=fraction)
    half_width = float(space.upper_w[0] - _PLACED[0])
    assert half_width == pytest.approx(_l1_budget(fraction) / _PLACED.size)

    worst = float(np.abs(space.upper_w - _PLACED).sum())
    assert worst <= _l1_budget(fraction) + 1e-12, (
        f"the box's extreme corner moves {worst} which exceeds the L1 budget "
        f"{_l1_budget(fraction)}; a bound proved on it would not transfer to the L1 problem"
    )


def test_the_deviation_box_does_NOT_lie_inside_the_l1_body() -> None:
    """The counterexample that forced the split, stated as a test rather than as a comment."""

    fraction = 0.1
    space = deviation_bounded_power_space(_PLACED, deviation_fraction=fraction)
    worst = float(np.abs(space.upper_w - _PLACED).sum())
    assert worst == pytest.approx(_PLACED.size * fraction * _TOTAL)
    assert worst > _l1_budget(fraction), (
        "the deviation box was expected to escape the L1 budget by a factor of n/2; if it does "
        "not, the two geometries have been made the same and the naming is misleading"
    )


def test_the_deviation_box_strictly_contains_the_relocation_box() -> None:
    """Ordering the two, so a reader can see which number must be the larger requirement."""

    inner = relocation_bounded_power_space(_PLACED, relocated_fraction=0.1)
    outer = deviation_bounded_power_space(_PLACED, deviation_fraction=0.1)
    assert np.all(outer.lower_w <= inner.lower_w) and np.all(outer.upper_w >= inner.upper_w)
    assert np.any(outer.upper_w > inner.upper_w)


def test_every_sampled_in_budget_map_stays_within_the_l1_body() -> None:
    """The inscribed box never admits a map the L1 budget forbids."""

    fraction = 0.1
    space = relocation_bounded_power_space(_PLACED, relocated_fraction=fraction)
    rng = np.random.default_rng(0)
    checked = 0
    for _ in range(300):
        z = rng.uniform(-1.0, 1.0, _PLACED.size)
        p = _PLACED + z * (space.upper_w - _PLACED)
        p = p - (p.sum() - _TOTAL) / p.size          # project onto the total-power plane
        if np.any(p < 0):
            continue
        assert float(np.abs(p - _PLACED).sum()) <= _l1_budget(fraction) + 1e-9
        checked += 1
    assert checked > 50, "the sampler produced too few maps to test anything"


def test_the_observed_placement_is_admitted_and_the_total_is_conserved() -> None:
    for fraction in (0.01, 0.05, 0.25):
        for space in (
            relocation_bounded_power_space(_PLACED, relocated_fraction=fraction),
            deviation_bounded_power_space(_PLACED, deviation_fraction=fraction),
        ):
            assert np.all(space.lower_w <= _PLACED) and np.all(_PLACED <= space.upper_w)
            assert float(space.b_eq[0]) == pytest.approx(_TOTAL)


def test_a_larger_budget_contains_a_smaller_one() -> None:
    """Monotone, so a sweep over the fraction is a robustness curve rather than a jumble."""

    for build, key in (
        (relocation_bounded_power_space, "relocated_fraction"),
        (deviation_bounded_power_space, "deviation_fraction"),
    ):
        tight = build(_PLACED, **{key: 0.02})
        loose = build(_PLACED, **{key: 0.20})
        assert np.all(loose.lower_w <= tight.lower_w) and np.all(loose.upper_w >= tight.upper_w)
        assert np.any(loose.upper_w > tight.upper_w)


def test_power_never_goes_negative() -> None:
    """A budget larger than a block's own power must clamp, not admit negative dissipation."""

    for build, key in (
        (relocation_bounded_power_space, "relocated_fraction"),
        (deviation_bounded_power_space, "deviation_fraction"),
    ):
        space = build(_PLACED, **{key: 5.0})
        assert np.all(space.lower_w >= 0.0)


def test_a_non_positive_or_non_finite_fraction_is_refused() -> None:
    for build, key in (
        (relocation_bounded_power_space, "relocated_fraction"),
        (deviation_bounded_power_space, "deviation_fraction"),
    ):
        for bad in (0.0, -0.1, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                build(_PLACED, **{key: bad})
