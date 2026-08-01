"""The endpoint is a decision, and a cell certificate must never be softer than a block one."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.cell_certificate import ENDPOINTS, certify_cells
from CertiTherm.core import PowerPolytope

_LOWER = np.array([0.0, 0.0, 0.0])
_UPPER = np.array([4.0, 3.0, 2.0])
_TOTAL = 5.0
_SPACE = PowerPolytope(
    lower_w=_LOWER, upper_w=_UPPER,
    a_eq=np.ones((1, 3)), b_eq=np.array([_TOTAL]),
    a_ub=np.empty((0, 3)), b_ub=np.empty(0),
)
# Three cells: a hot die cell, a cooler die cell, and a sink cell that is hotter than both.
_ROWS = np.array([[0.90, 0.20, 0.10], [0.30, 0.40, 0.20], [1.50, 1.40, 1.30]])
_AMB = np.array([318.15, 318.15, 318.15])
_LABELS = np.array(["tool_compatible", "active_silicon", "any_layer"])


def _certify(endpoint, **kwargs):
    return certify_cells(
        _ROWS, _AMB, _LABELS, _SPACE, _TOTAL, endpoint=endpoint,
        limit_k=330.0, margin_k=0.05, linearisation_k=0.01, **kwargs
    )


def test_a_wider_endpoint_can_only_be_hotter_because_it_admits_more_rows() -> None:
    """Containment, not equality. A die cell is also a cell of some layer.

    Selecting by `label == endpoint` would have made `any_layer` exclude the die, which is the
    direction that silently drops the hottest silicon from a certificate about silicon.
    """

    peaks = [_certify(e).sup_peak_k for e in ENDPOINTS]
    assert peaks[0] <= peaks[1] <= peaks[2], peaks
    assert [_certify(e).cells_considered for e in ENDPOINTS] == [1, 2, 3]


def test_the_sink_cell_is_excluded_from_a_junction_endpoint() -> None:
    """A heat sink at 330 K violates nothing. Including it would refuse a sound design."""

    assert _certify("any_layer").argmax_cell == 2
    assert _certify("active_silicon").argmax_cell != 2


def test_an_unknown_endpoint_refuses_rather_than_defaulting() -> None:
    with pytest.raises(ValueError, match="endpoint must be one of"):
        _certify("junction")


def test_an_endpoint_no_cell_belongs_to_refuses_instead_of_certifying_nothing() -> None:
    """A supremum over an empty row set is not a number, and would otherwise read as very safe."""

    with pytest.raises(ValueError, match="no cell is labelled"):
        certify_cells(
            _ROWS[2:], _AMB[2:], np.array(["any_layer"]), _SPACE, _TOTAL,
            endpoint="tool_compatible", limit_k=330.0, margin_k=0.05, linearisation_k=0.01,
        )


def test_a_colder_comparison_operator_cannot_add_slack() -> None:
    """One-sided. Disagreement may make certification harder; it must never make it easier."""

    alone = _certify("active_silicon")
    colder = _certify("active_silicon", comparison_rows=_ROWS - 0.5, comparison_ambient=_AMB)
    assert colder.comparison_band_k == 0.0
    assert colder.slack_k == alone.slack_k


def test_a_hotter_comparison_operator_reduces_slack_by_its_polytope_supremum() -> None:
    hotter = _certify("active_silicon", comparison_rows=_ROWS + 0.1, comparison_ambient=_AMB)
    alone = _certify("active_silicon")
    # +0.1 K/W on every entry against a 5 W total is exactly 0.5 K of band.
    assert abs(hotter.comparison_band_k - 0.5) < 1e-9
    assert abs((alone.slack_k - hotter.slack_k) - 0.5) < 1e-9


def test_a_non_finite_operator_entry_refuses() -> None:
    poisoned = _ROWS.copy()
    poisoned[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        certify_cells(
            poisoned, _AMB, _LABELS, _SPACE, _TOTAL, endpoint="active_silicon",
            limit_k=330.0, margin_k=0.05, linearisation_k=0.01,
        )


def test_a_polytope_carrying_an_equality_this_bound_cannot_see_refuses() -> None:
    """The same defect class as the dropped class-total rows, on the equality side.

    `PowerPolytope` accepts an arbitrary `a_eq`; every maximiser here builds `sum(p) = total`. A
    per-chiplet budget row would be silently dropped and the bound would describe a larger set than
    the one the certificate names. The `a_ub` version of this was found by peer review and fixed;
    this is its twin.
    """

    extra = PowerPolytope(
        lower_w=_LOWER, upper_w=_UPPER,
        a_eq=np.array([[1.0, 1.0, 1.0], [1.0, 0.0, 0.0]]), b_eq=np.array([_TOTAL, 2.0]),
        a_ub=np.empty((0, 3)), b_ub=np.empty(0),
    )
    with pytest.raises(ValueError, match="exactly one equality"):
        certify_cells(
            _ROWS, _AMB, _LABELS, extra, _TOTAL, endpoint="active_silicon",
            limit_k=330.0, margin_k=0.05, linearisation_k=0.01,
        )


def test_a_total_that_disagrees_with_the_polytope_refuses() -> None:
    """Two descriptions of one quantity that disagree is a policing problem, not a check."""

    with pytest.raises(ValueError, match="but the caller passed"):
        certify_cells(
            _ROWS, _AMB, _LABELS, _SPACE, _TOTAL + 1.0, endpoint="active_silicon",
            limit_k=330.0, margin_k=0.05, linearisation_k=0.01,
        )
