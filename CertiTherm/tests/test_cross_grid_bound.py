"""A bound over the polytope must dominate any sample from it, and must be tight at a vertex.

The estimator this replaces took `max |T_N - T_2N|` over five calibration vectors and the surrounding
prose called the resulting certificate sound. Peer review pointed out the inconsistency: a maximum
over five power maps is not a bound over the set the certificate quantifies over. Because the
thermal model is linear the exact supremum is available in closed form, and these tests pin the two
properties that make it worth having -- it dominates every sample, and it is attained.
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.cross_grid_bound import row_discrepancy_bounds, sample_bound

_LOWER = np.zeros(4)
_UPPER = np.array([4.0, 4.0, 4.0, 4.0])
_TOTAL = 6.0
_COARSE = np.array([[1.0, 0.4, 0.2, 0.1], [0.5, 0.5, 0.5, 0.5]])
_FINE = np.array([[0.9, 0.4, 0.25, 0.1], [0.5, 0.5, 0.5, 0.5]])
_AMB = np.array([300.0, 300.0])


def _bounds(**kw):
    return row_discrepancy_bounds(
        _COARSE, _FINE, _AMB, _AMB, kw.get("lower", _LOWER), kw.get("upper", _UPPER),
        kw.get("total", _TOTAL),
    )


def test_the_bound_is_the_exact_supremum_for_a_row_with_a_known_answer() -> None:
    """`delta = [0.1, 0, -0.05, 0]` over `0 <= p_i <= 4`, `sum p = 6`.

    The maximum puts block 0 at its CAP of 4 -- not the whole 6 W, which the box forbids -- and the
    spare 2 W on a zero-coefficient block: `4 * 0.1 = 0.4`. The minimum puts 4 W on block 2 for
    `-0.2`. So the magnitude is 0.4.

    The first version of this test asserted 0.6 by putting all six watts on block 0 and ignoring the
    cap. Hand arithmetic is worth writing precisely because it catches that, and here it caught mine
    rather than the implementation's.
    """

    bounds = _bounds()
    assert bounds[0] == pytest.approx(0.4)
    # The second row is identical on both grids, so it costs nothing. A per-row budget that charged
    # it anyway would be the flat multiplier this module exists to replace.
    assert bounds[1] == pytest.approx(0.0)


def test_the_bound_dominates_every_sample_and_is_attained_by_one() -> None:
    rng = np.random.default_rng(3)
    bounds = _bounds()
    vectors = []
    for _ in range(200):
        raw = rng.random(4)
        vectors.append(raw / raw.sum() * _TOTAL)
    sampled = sample_bound(_COARSE, _FINE, _AMB, _AMB, vectors)
    assert np.all(sampled <= bounds + 1e-9), "a sample exceeded the supremum over the same set"

    # The maximiser itself: block 0 at its cap, the spare on a zero-coefficient block.
    vertex = np.array([4.0, 2.0, 0.0, 0.0])
    attained = sample_bound(_COARSE, _FINE, _AMB, _AMB, [vertex])
    assert attained[0] == pytest.approx(bounds[0]), "the supremum must be attained, not merely bound"


def test_a_random_sample_UNDERSTATES_the_bound_which_is_why_the_change_was_needed() -> None:
    """The number that motivates the module: how much a five-vector sample misses by."""

    rng = np.random.default_rng(11)
    five = []
    for _ in range(5):
        raw = rng.random(4)
        five.append(raw / raw.sum() * _TOTAL)
    sampled = sample_bound(_COARSE, _FINE, _AMB, _AMB, five)
    bounds = _bounds()
    assert sampled[0] < bounds[0], (
        "five random interior maps happened to reach the vertex supremum; the fixture no longer "
        "demonstrates the gap it exists to demonstrate"
    )


def test_a_sign_flipped_discrepancy_costs_the_same_as_an_unflipped_one() -> None:
    """A grid reading cold everywhere is as dangerous as one reading hot; magnitude is what counts."""

    flipped = row_discrepancy_bounds(_FINE, _COARSE, _AMB, _AMB, _LOWER, _UPPER, _TOTAL)
    assert flipped == pytest.approx(_bounds())


def test_an_ambient_offset_enters_the_bound() -> None:
    shifted = row_discrepancy_bounds(
        _COARSE, _FINE, _AMB + 0.3, _AMB, _LOWER, _UPPER, _TOTAL
    )
    assert shifted[1] == pytest.approx(0.3), "a pure ambient difference must not vanish"
    assert shifted[0] > _bounds()[0]


def test_shape_and_finiteness_violations_are_refused() -> None:
    with pytest.raises(ValueError):
        row_discrepancy_bounds(_COARSE, _FINE[:1], _AMB, _AMB, _LOWER, _UPPER, _TOTAL)
    with pytest.raises(ValueError):
        row_discrepancy_bounds(_COARSE, _FINE, _AMB[:1], _AMB, _LOWER, _UPPER, _TOTAL)
    with pytest.raises(ValueError):
        row_discrepancy_bounds(_COARSE, _FINE, _AMB, _AMB, _LOWER[:2], _UPPER, _TOTAL)
    bad = _COARSE.copy()
    bad[0, 0] = np.nan
    with pytest.raises(ValueError):
        row_discrepancy_bounds(bad, _FINE, _AMB, _AMB, _LOWER, _UPPER, _TOTAL)
    for total in (0.0, -1.0, float("nan")):
        with pytest.raises(ValueError):
            _bounds(total=total)


def test_an_empty_polytope_is_refused_rather_than_bounded() -> None:
    """`sup` over an empty set is not a number, and returning one would look like an answer."""

    with pytest.raises(ValueError):
        _bounds(lower=np.full(4, 3.0))          # lower bounds sum to 12 > total 6
    with pytest.raises(ValueError):
        _bounds(upper=np.full(4, 0.5))          # upper bounds sum to 2 < total 6


def test_an_empty_sample_is_refused_rather_than_scoring_zero() -> None:
    with pytest.raises(ValueError):
        sample_bound(_COARSE, _FINE, _AMB, _AMB, [])
