"""Pin the three properties `docs/CERTIFICATE_IN_THE_LOOP.md` requires of the in-loop certificate.

These are the properties a search loop relies on when it calls the certificate instead of a thermal
simulator. Each is tested against something INDEPENDENT of the implementation under test -- a brute
force over vertices, a reference LP, or an explicit counterexample -- rather than against a second
copy of the same greedy, which could reproduce its bug and still agree.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from CertiTherm.cross_grid_bound import _extreme_rows
from CertiTherm.measurements import activity_bounded_power_space


def _brute_force_sup(row, lower, upper, total):
    """`sup r.p` over a box with a total equality, by enumerating the vertices.

    Every vertex of `{l <= p <= u, sum p = T}` has at most ONE coordinate strictly interior; the rest
    sit on a bound. So enumerating the 2^(n-1) bound assignments of the others and solving for the
    free coordinate visits every vertex, and a linear objective attains its supremum at one. This is
    exponential and therefore only usable at small n -- which is the point: it shares no code, and no
    reasoning, with the greedy.
    """
    n = len(row)
    best = -np.inf
    for free in range(n):
        rest = [i for i in range(n) if i != free]
        for assignment in itertools.product((0, 1), repeat=n - 1):
            p = np.empty(n, dtype=float)
            for i, side in zip(rest, assignment):
                p[i] = upper[i] if side else lower[i]
            p[free] = total - sum(p[i] for i in rest)
            if lower[free] - 1e-12 <= p[free] <= upper[free] + 1e-12:
                best = max(best, float(np.dot(row, p)))
    return best


@pytest.mark.parametrize("seed", range(12))
def test_greedy_fill_is_the_exact_supremum_not_a_bound(seed):
    """P1: the greedy attains the vertex optimum, on random boxes, to machine precision."""
    rng = np.random.default_rng(seed)
    n = 6
    nominal = rng.uniform(0.5, 4.0, size=n)
    span = float(rng.uniform(0.05, 0.9))
    lower, upper = nominal * (1.0 - span), nominal * (1.0 + span)
    total = float(nominal.sum())
    rows = rng.uniform(-1.0, 3.0, size=(4, n))

    greedy = _extreme_rows(rows, lower, upper, total)
    for index, row in enumerate(rows):
        assert greedy[index] == pytest.approx(
            _brute_force_sup(row, lower, upper, total), abs=1e-9
        ), "the greedy is not the supremum; it is either a bound or wrong"


@pytest.mark.parametrize("seed", range(8))
def test_the_envelope_nests_so_the_supremum_is_monotone_in_the_span(seed):
    """P2: `P(s) subset P(s')` for `s <= s'`, so widening can never lower the certified peak."""
    rng = np.random.default_rng(seed)
    blocks = [f"core_{i}" for i in range(7)]
    nominal = rng.uniform(0.5, 3.0, size=len(blocks))
    rows = rng.uniform(0.0, 2.0, size=(5, len(blocks)))
    total = float(nominal.sum())

    peaks = []
    for span in (0.01, 0.05, 0.2, 0.5, 1.0):
        space = activity_bounded_power_space(blocks, nominal, activity_span=span)
        peaks.append(float(np.max(_extreme_rows(
            rows, np.asarray(space.lower_w, dtype=float),
            np.asarray(space.upper_w, dtype=float), total))))
    for before, after in zip(peaks, peaks[1:]):
        assert after >= before - 1e-12, (
            f"the supremum fell from {before} to {after} as the envelope widened; the sets do not "
            "nest and the robustness radius would not be well defined"
        )


def test_the_nominal_point_is_inside_every_envelope():
    """P2 corollary: the certified supremum dominates the point evaluation the field reports."""
    blocks = [f"core_{i}" for i in range(5)]
    nominal = np.array([1.0, 2.0, 0.5, 3.0, 1.5])
    rows = np.array([[1.0, 0.2, 0.1, 0.9, 0.4], [0.3, 1.7, 0.2, 0.1, 0.8]])
    total = float(nominal.sum())
    point = float(np.max(rows @ nominal))
    for span in (0.01, 0.3, 1.0):
        space = activity_bounded_power_space(blocks, nominal, activity_span=span)
        certified = float(np.max(_extreme_rows(
            rows, np.asarray(space.lower_w, dtype=float),
            np.asarray(space.upper_w, dtype=float), total)))
        assert certified >= point - 1e-12, (
            "the certificate is below the nominal evaluation; it would certify a design its own "
            "nominal power map refutes"
        )


@pytest.mark.parametrize("field", ["rows", "lower", "upper", "total"])
def test_a_non_finite_input_is_refused_rather_than_reported(field):
    """P3: `NaN <= x` and `NaN > x` are both False, so one inequality would pass it through."""
    rows = np.array([[1.0, 2.0, 3.0]])
    lower = np.array([0.5, 0.5, 0.5])
    upper = np.array([2.0, 2.0, 2.0])
    total = 3.0
    if field == "rows":
        rows = rows.copy(); rows[0, 1] = np.nan
    elif field == "lower":
        lower = lower.copy(); lower[2] = np.nan
    elif field == "upper":
        upper = upper.copy(); upper[0] = np.inf
    else:
        total = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        _extreme_rows(rows, lower, upper, total)


def test_an_empty_polytope_is_refused_not_silently_clipped():
    """P3: lower bounds above the total, and upper bounds below it, are both empty sets."""
    rows = np.array([[1.0, 1.0]])
    with pytest.raises(ValueError, match="polytope is empty"):
        _extreme_rows(rows, np.array([2.0, 2.0]), np.array([3.0, 3.0]), 1.0)
    with pytest.raises(ValueError, match="polytope is empty"):
        _extreme_rows(rows, np.array([0.0, 0.0]), np.array([0.5, 0.5]), 5.0)


def test_the_supremum_is_attained_at_a_feasible_point_not_beyond_the_box():
    """P1 sanity: the maximiser the greedy implies must itself satisfy the box and the total."""
    rng = np.random.default_rng(7)
    n = 9
    nominal = rng.uniform(1.0, 5.0, size=n)
    span = 0.35
    lower, upper = nominal * (1.0 - span), nominal * (1.0 + span)
    total = float(nominal.sum())
    row = rng.uniform(0.0, 1.0, size=n)

    order = np.argsort(-row)
    p = lower.copy()
    spare = total - float(lower.sum())
    for index in order:
        take = min(spare, upper[index] - lower[index])
        p[index] += take
        spare -= take
    assert spare == pytest.approx(0.0, abs=1e-9), "the greedy did not spend the whole budget"
    assert np.all(p >= lower - 1e-12) and np.all(p <= upper + 1e-12), "the maximiser left the box"
    assert float(p.sum()) == pytest.approx(total, abs=1e-9), "the maximiser broke the total equality"
    assert float(np.dot(row, p)) == pytest.approx(
        float(_extreme_rows(row[None, :], lower, upper, total)[0]), abs=1e-9
    )
