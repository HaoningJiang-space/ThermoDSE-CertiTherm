"""Sibling kernelized oracle tests (CertiTherm-F item 3 integration).

Synthetic instance where a block-0 measurement distinguishes the safe/reject
worlds: empty selection collides, {block-0 action} is collision-free. The sibling
kernelized oracle must agree with the baseline `_collision` on existence, and
`first_collision` must degrade to baseline when the kernel does not match.
"""
from __future__ import annotations

import numpy as np
import pytest

from dataclasses import replace

from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily
from CertiTherm.synthesis import _collision, first_collision, _full_safe_satisfied
from CertiTherm.thermal_kernel import build_kernel

MARGIN, TOL = 1.0, 1e-9


def _power():
    return PowerPolytope(
        lower_w=np.zeros(3), upper_w=np.full(3, 20.0),
        a_eq=np.empty((0, 3)), b_eq=np.empty(0),
        a_ub=np.empty((0, 3)), b_ub=np.empty(0))


def _thermal():
    response = np.array([[[10.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 0.0, 0.0]]])
    return ThermalFamily(
        model_ids=("m",), response_k_per_w=response,
        ambient_k=np.array([0.0]), limit_k=100.0)


def _actions():
    return (MeasurementAction("a0", np.array([1.0, 0.0, 0.0]), tolerance=1e-6),)


def _base(sel):
    return _collision(_power(), _thermal(), _actions(), sel, MARGIN, TOL, 1)


def _kern(sel, kernel):
    return first_collision(_power(), _thermal(), _actions(), sel, MARGIN, TOL, 1, kernel)


def test_kernel_reduces_this_instance():
    k = build_kernel(_power(), _thermal(), MARGIN, TOL)
    assert k.safe_row_indices == (0,)          # points 1,2 SAFE-redundant
    assert k.reject_specs == ((0, 0),)         # points 1,2 unreachable


def test_empty_selection_collides_both():
    k = build_kernel(_power(), _thermal(), MARGIN, TOL)
    base = _base(())
    kern = _kern((), k)
    assert base is not None and kern is not None          # both find a collision
    # the kernel witness must satisfy the FULL safe rows
    assert _full_safe_satisfied(kern.safe_power_w, _thermal(), MARGIN, TOL)


def test_measured_selection_collision_free_both():
    k = build_kernel(_power(), _thermal(), MARGIN, TOL)
    assert _base((0,)) is None                 # block-0 action distinguishes
    assert _kern((0,), k) is None              # kernel agrees: no collision


def test_kernel_none_is_baseline():
    # first_collision(kernel=None) == _collision
    assert (_kern((), None) is None) == (_base(()) is None)
    assert (_kern((0,), None) is None) == (_base((0,)) is None)


def test_degrade_to_baseline_on_binding_mismatch():
    # a kernel built for a DIFFERENT margin must not be trusted; first_collision
    # falls back to the baseline and returns the correct verdict.
    stale = build_kernel(_power(), _thermal(), 2.0, TOL)   # wrong margin
    # empty selection: baseline collides, degraded result must also collide
    assert _kern((), stale) is not None
    # measured selection: baseline collision-free, degraded result also None
    assert _kern((0,), stale) is None


def test_fallback_rematerializes_selected_generator():
    """Regression (review): a sabotaged kernel that drops the binding SAFE row 0
    produces a FALSE collision on the measured selection, fails full-SAFE validation,
    and must fall back to the baseline (collision-free). With `selected` given as a
    one-shot generator, the fallback must still see the action -> None. On the old
    code the exhausted generator reached the baseline with no actions -> a collision."""
    good = build_kernel(_power(), _thermal(), MARGIN, TOL)   # safe=(0,), reject=((0,0),)
    sabotaged = replace(good, safe_row_indices=())           # drop the binding SAFE row
    res = first_collision(_power(), _thermal(), _actions(), iter([0]),
                          MARGIN, TOL, 1, sabotaged)
    assert res is None                                       # degraded to baseline verdict


def test_full_safe_satisfied_helper():
    # a world within all ceilings passes; one exceeding a ceiling fails
    ok = np.array([9.0, 0.0, 0.0])             # 10*9=90 <= 99
    bad = np.array([9.95, 0.0, 0.0])           # 10*9.95=99.5 > 99
    assert _full_safe_satisfied(ok, _thermal(), MARGIN, TOL)
    assert not _full_safe_satisfied(bad, _thermal(), MARGIN, TOL)
