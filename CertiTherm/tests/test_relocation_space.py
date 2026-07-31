"""The relocation geometry must be a relaxation, and must admit the map it was built from.

Measured on the dev registry, relocation radii are 0.5-4.3% of total power where uniform scaling
radii are 9-258%: redistribution is twenty to fifty times more dangerous. That is the direction
group-level power reports cannot observe, so it is the geometry a certified observation requirement
should be computed under.

The returned polytope is the box implied by the L1 budget, which CONTAINS the true L1 body. A bound
proved on a superset holds on the subset, so the direction of the approximation is the safe one --
these tests pin that, because the reverse would silently overstate every requirement.
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.measurements import relocation_bounded_power_space

_PLACED = np.array([2.0, 3.0, 1.0, 4.0])


def test_the_box_contains_the_l1_body_it_relaxes() -> None:
    """Any map relocating at most the budget must be admitted, or a bound could overstate."""

    space = relocation_bounded_power_space(_PLACED, relocated_fraction=0.1)
    budget = 0.1 * float(_PLACED.sum())
    rng = np.random.default_rng(0)
    admitted = 0
    for _ in range(300):
        z = rng.normal(0, 1, _PLACED.size)
        z -= z.mean()
        scale = 2 * budget / max(np.abs(z).sum(), 1e-12)
        p = _PLACED + z * scale * rng.uniform(0, 1)
        if np.any(p < 0):
            continue
        assert np.abs(p - _PLACED).sum() <= 2 * budget + 1e-9
        assert np.all(space.lower_w - 1e-9 <= p) and np.all(p <= space.upper_w + 1e-9)
        admitted += 1
    assert admitted > 50, "the sampler produced too few in-budget maps to test anything"


def test_the_observed_placement_is_admitted_and_the_total_is_conserved() -> None:
    for fraction in (0.01, 0.05, 0.25):
        space = relocation_bounded_power_space(_PLACED, relocated_fraction=fraction)
        assert np.all(space.lower_w <= _PLACED) and np.all(_PLACED <= space.upper_w)
        assert float(space.b_eq[0]) == pytest.approx(float(_PLACED.sum()))


def test_a_larger_budget_contains_a_smaller_one() -> None:
    """Monotone, so a sweep over the fraction is a robustness curve."""

    tight = relocation_bounded_power_space(_PLACED, relocated_fraction=0.02)
    loose = relocation_bounded_power_space(_PLACED, relocated_fraction=0.20)
    assert np.all(loose.lower_w <= tight.lower_w) and np.all(loose.upper_w >= tight.upper_w)
    assert np.any(loose.upper_w > tight.upper_w)


def test_power_never_goes_negative() -> None:
    """A budget larger than a block's own power must clamp, not admit negative dissipation."""

    space = relocation_bounded_power_space(_PLACED, relocated_fraction=0.9)
    assert np.all(space.lower_w >= 0.0)
    assert space.lower_w[2] == 0.0, "the smallest block must clamp at zero under a large budget"


def test_a_nonpositive_or_non_finite_fraction_is_refused() -> None:
    for bad in (0.0, -0.1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite and positive"):
            relocation_bounded_power_space(_PLACED, relocated_fraction=bad)
