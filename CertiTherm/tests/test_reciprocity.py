"""Reciprocity is a theorem, so the check must be exact on a symmetric operator and catch any break."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.reciprocity import reciprocity_residual


def test_a_symmetric_operator_has_zero_residual() -> None:
    base = np.array([[3.0, 1.0, 0.5], [1.0, 2.0, 0.25], [0.5, 0.25, 1.5]])
    report = reciprocity_residual(base)
    assert report.max_asymmetry_k_per_w == 0.0 and report.relative == 0.0


def test_a_broken_pair_is_found_and_named() -> None:
    """The pair matters: it says WHICH two blocks disagree, which is where to look."""

    base = np.array([[3.0, 1.0, 0.5], [1.0, 2.0, 0.25], [0.5, 0.25, 1.5]])
    base[0, 2] += 0.4
    report = reciprocity_residual(base)
    assert abs(report.max_asymmetry_k_per_w - 0.4) < 1e-12
    assert set(report.worst_pair) == {0, 2}


def test_an_all_zero_operator_is_symmetric_rather_than_NaN() -> None:
    """Dividing by the scale would make a degenerate but symmetric operator report NaN."""

    report = reciprocity_residual(np.zeros((4, 4)))
    assert report.relative == 0.0


def test_a_non_square_operator_refuses_because_reciprocity_is_block_to_block() -> None:
    """A cell-row operator is not square and reciprocity does not apply to it as written."""

    with pytest.raises(ValueError, match="square"):
        reciprocity_residual(np.zeros((16, 4)))


def test_a_non_finite_entry_refuses() -> None:
    poisoned = np.eye(3)
    poisoned[1, 1] = np.nan
    with pytest.raises(ValueError, match="finite"):
        reciprocity_residual(poisoned)
