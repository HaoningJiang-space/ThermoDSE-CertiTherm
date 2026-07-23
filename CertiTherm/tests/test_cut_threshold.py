"""The cut must be a SUPERSET of the true separator set, minus selected actions.

Theorem 1: action a separates a world pair iff |v_a . delta| > tolerance. The
cut used to test `> tolerance + separation_tolerance`, dropping genuine
separators whose gap fell in the (tolerance, tolerance + sep] window. A cut that
omits a true separator is a subset -- a too-strong necessary constraint -- and
can push the hitting-set optimum ABOVE C*, inflating the certified lower bound.

The fix uses the exact threshold `> tolerance` and excludes ALREADY-SELECTED
actions by index (a selected action provably cannot separate the collision it
helped define). These tests pin that a borderline separator is included and a
selected separator is excluded; the first fails against the pre-fix `+` code.
"""
from __future__ import annotations

import numpy as np

from CertiTherm.core import MeasurementAction, WorldPair
from CertiTherm.policies import _cut


def _actions(tol: float):
    return tuple(
        MeasurementAction(f"a{i}", np.eye(3)[i], cost=1.0, tolerance=tol, candidate_id="c")
        for i in range(3)
    )


def _witness(delta: np.ndarray) -> WorldPair:
    return WorldPair(
        safe_power_w=delta.astype(float),
        unsafe_power_w=np.zeros(3),
        safe_model_id="ROBUST_ENVELOPE",
        unsafe_model_id="m",
        unsafe_point=0,
    )


def test_borderline_separator_is_included_not_dropped() -> None:
    tol, sep = 1e-8, 1e-9
    actions = _actions(tol)
    # axis 0: gap in the (tol, tol+sep] danger zone -> a TRUE separator the old
    # `> tol + sep` code dropped. axis 1: clearly separating. axis 2: not.
    delta = np.array([tol + sep / 2, tol * 10, tol / 2])
    cut = _cut("c", _witness(delta), actions, selected=())

    assert cut[0] == 1.0, "borderline separator (gap in (tol, tol+sep]) was dropped"
    assert cut[1] == 1.0, "clear separator missing"
    assert cut[2] == 0.0, "gap tol/2 <= tolerance is not a separator"


def test_selected_action_is_excluded_by_index() -> None:
    tol = 1e-8
    actions = _actions(tol)
    # axis 0 clearly separates, but it is already selected -> must NOT be in the
    # cut (a selected action cannot separate a collision found under it).
    delta = np.array([tol * 10, tol * 10, 0.0])
    cut = _cut("c", _witness(delta), actions, selected=(0,))
    assert cut[0] == 0.0, "already-selected separator leaked into the cut"
    assert cut[1] == 1.0, "unselected separator missing"


def test_clear_nonseparator_stays_out() -> None:
    tol = 1e-8
    actions = _actions(tol)
    delta = np.array([tol / 2, tol / 4, 0.0])          # all gaps <= tolerance
    cut = _cut("c", _witness(delta), actions, selected=())
    assert cut.sum() == 0.0


def test_cut_excludes_other_candidates() -> None:
    tol = 1e-8
    actions = _actions(tol)
    delta = np.array([tol * 10, 0.0, 0.0])
    cut = _cut("other", _witness(delta), actions, selected=())
    assert cut.sum() == 0.0
