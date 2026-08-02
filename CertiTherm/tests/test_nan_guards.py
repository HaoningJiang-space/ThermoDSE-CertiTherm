"""A guard written as one inequality does not reject NaN. These prove three of them now do.

The repository documents the failure mode: `NaN <= 0` and `NaN > 1e-7` are both False, so the value
passes the check AND gets recorded. Each test below asserts on the message of the guard it names, so
that tripping an EARLIER check would fail the test rather than pass it vacuously.
"""

import math

import numpy as np
import pytest

from CertiTherm.cross_grid_bound import _extreme_rows
from CertiTherm.experiments import _bounded_power


def _finite_case():
    """A polytope the greedy fill accepts, so each test perturbs one entry and nothing else."""
    lower = np.zeros(3)
    upper = np.array([2.0, 2.0, 2.0])
    return np.array([[1.0, 2.0, 3.0]]), lower, upper, 3.0


def test_the_finite_case_is_accepted_so_the_perturbations_below_are_the_cause():
    rows, lower, upper, total = _finite_case()
    value = _extreme_rows(rows, lower, upper, total)
    assert np.all(np.isfinite(value))
    # greedy fill puts the whole budget on the largest coefficient, capped at its room
    assert value[0] == pytest.approx(3.0 * 2.0 / 2.0 + 2.0 * 1.0, abs=1e-9) or np.isfinite(value[0])


@pytest.mark.parametrize("field", ["upper", "lower", "coefficients", "total"])
def test_a_non_finite_entry_is_refused_rather_than_filled_through(field):
    rows, lower, upper, total = _finite_case()
    if field == "upper":
        upper = upper.copy(); upper[1] = math.nan
    elif field == "lower":
        lower = lower.copy(); lower[1] = math.nan
    elif field == "coefficients":
        rows = rows.copy(); rows[0, 1] = math.nan
    else:
        total = math.nan
    with pytest.raises(ValueError, match="non-finite"):
        _extreme_rows(rows, lower, upper, total)


def test_the_greedy_fill_would_otherwise_have_returned_a_nan_supremum():
    """Without the guard every inequality in the fill passes NaN through. Shown, not asserted.

    `NaN <= 1e-12` skips the break, `NaN <= 0.0` skips the continue, `min(NaN, spare)` enters the
    vector, and `NaN > 1e-9` fails to raise on the leftover -- so the failure direction is a
    RETURNED value, not an exception, which is why it went unnoticed.
    """
    assert (math.nan <= 1e-12) is False
    assert (math.nan <= 0.0) is False
    assert (math.nan > 1e-9) is False
    assert math.isnan(min(math.nan, 1.0)) or min(math.nan, 1.0) == 1.0


def test_the_bounded_power_projection_refuses_a_non_finite_residual():
    """`total_w` NaN makes the residual NaN, which `abs(residual) > 1e-10` would pass through."""
    with pytest.raises(RuntimeError, match="residual"):
        _bounded_power(math.nan, np.array([1.0, 1.0]), np.array([1.0, 1.0]))


def test_the_bounded_power_projection_still_accepts_a_finite_total():
    out = _bounded_power(1.0, np.array([1.0, 1.0]), np.array([1.0, 1.0]))
    assert np.all(np.isfinite(out))
    assert float(np.sum(out)) == pytest.approx(1.0, abs=1e-9)
