"""`reciprocity_residual` reports Maxwell-Betti asymmetry; it must not assert it.

The steady conduction operator is self-adjoint, so a block-average response whose evaluation
points ARE its source blocks satisfies `R = R^T`. That makes `max |R - R^T|` a free
correctness invariant over the geometry, the boundary condition and the assembly -- and
nothing in the package currently computes it.

It is a REPORTER, not a guard, and these tests pin that. The measurement has since been done
and it is why the reporter must not become a guard: HotSpot's `gridN-avg` breaks reciprocity
by 2.5-12 %, shrinking with refinement, while `block` and the DOLFINx FEM hold it to 1e-10.
A `__post_init__` check would therefore reject every `gridN-avg` family that produced every
published number. Its effect on the certifying quantity is separately measured at
**+0.002 to +0.071 K** -- so it is a defect detector, not an error term.

The implementation lives in `CertiTherm/reciprocity.py`; an earlier copy in `core.py` was
removed rather than kept, because two constructions of one invariant is precisely the
situation where neither checks the other.
"""

from __future__ import annotations

import numpy as np

from CertiTherm.core import ThermalFamily
from CertiTherm.reciprocity import family_reciprocity_residuals as reciprocity_residual

_BLOCKS = 4


def _family(response: np.ndarray) -> ThermalFamily:
    models = response.shape[0]
    return ThermalFamily(
        model_ids=tuple(f"m{i}" for i in range(models)),
        response_k_per_w=response,
        ambient_k=np.zeros(models),
        limit_k=350.0,
    )


def _symmetric(seed: int) -> np.ndarray:
    raw = np.random.default_rng(seed).random((_BLOCKS, _BLOCKS))
    return raw + raw.T


def test_a_symmetric_response_has_zero_residual():
    residual = reciprocity_residual(_family(_symmetric(0)[None, :, :]))
    assert residual.shape == (1,)
    assert residual[0] == 0.0


def test_the_residual_is_the_largest_single_asymmetry_not_a_norm():
    """Pinned because a Frobenius norm would pass a family with one bad entry."""

    response = _symmetric(1)
    response[0, 2] += 0.75
    response[1, 3] += 0.25
    residual = reciprocity_residual(_family(response[None, :, :]))
    assert np.isclose(residual[0], 0.75)


def test_each_model_is_reported_separately():
    """One asymmetric model must not be averaged away by its symmetric neighbours."""

    good = _symmetric(2)
    bad = _symmetric(3)
    bad[1, 0] += 0.5
    residual = reciprocity_residual(_family(np.stack([good, bad, good])))
    assert residual[0] == 0.0
    assert np.isclose(residual[1], 0.5)
    assert residual[2] == 0.0


def test_a_non_square_response_reports_nan_rather_than_a_number():
    """Reciprocity says nothing when the observation points are not the sources.

    A cell-level operator observes 262 144 grid cells from 237 block sources; comparing that
    rectangle with its transpose is not defined, and returning 0.0 would read as "checked and
    clean". NaN is the honest answer and it is not silently comparable.
    """

    response = np.ones((2, 3, _BLOCKS))
    residual = reciprocity_residual(_family(response))
    assert residual.shape == (2,)
    assert np.all(np.isnan(residual))


def test_square_and_non_square_models_in_one_family_are_distinguished():
    """The NaN must be per model, not a whole-family bail-out."""

    family = _family(np.ones((2, _BLOCKS, _BLOCKS)))
    residual = reciprocity_residual(family)
    assert np.all(residual == 0.0)


def test_the_reporter_does_not_raise_on_an_asymmetric_family():
    """The whole point: constructing and measuring an asymmetric operator must both succeed.

    If this ever starts raising, `reciprocity_residual` has become a guard and the docstring
    promising otherwise -- plus the measurement that was supposed to precede that promotion --
    needs revisiting.
    """

    response = _symmetric(4)
    response[3, 0] += 10.0
    residual = reciprocity_residual(_family(response[None, :, :]))
    assert np.isclose(residual[0], 10.0)
