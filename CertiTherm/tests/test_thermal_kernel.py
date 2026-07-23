"""Tests for the VerifiedThermalKernel artifact (CertiTherm-F item 3 foundation).

A synthetic thermal instance where only one (model,point) location can be hot or
rejecting; the kernel must keep it and drop the rest, bind to the instance content,
and fail closed on drift. Independent SAFE/REJECT audits (no coupling assumed).
"""
from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.core import PowerPolytope, ThermalFamily
from CertiTherm.thermal_kernel import (
    VerifiedThermalKernel, ThermalKernelError, build_kernel, binding_digest,
)


def _power():
    return PowerPolytope(
        lower_w=np.zeros(3), upper_w=np.full(3, 20.0),
        a_eq=np.empty((0, 3)), b_eq=np.empty(0),
        a_ub=np.empty((0, 3)), b_ub=np.empty(0))


def _thermal():
    # 1 model, 3 points, all respond only to block 0: point0 hot (10x), 1/2 cool.
    response = np.array([[[10.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 0.0, 0.0]]])
    return ThermalFamily(
        model_ids=("m",), response_k_per_w=response,
        ambient_k=np.array([0.0]), limit_k=100.0)


def _kernel(**over):
    kw = dict(power=_power(), thermal=_thermal(), margin_k=1.0, feas_tol=1e-10)
    kw.update(over)
    return build_kernel(**kw)


def test_build_keeps_only_the_frontier():
    # ceiling = 99, floor = 101. Only point 0 (10*p0) can exceed/reach; p0<=20.
    k = _kernel()
    assert k.safe_row_indices == (0,)          # points 1,2 SAFE-redundant
    assert k.reject_specs == ((0, 0),)         # points 1,2 REJECT-unreachable
    assert k.n_safe_full == 3 and k.n_reject_full == 3
    assert k.reject_indices == (0,)


def test_reject_specs_lexicographic_and_flat_index():
    k = _kernel()
    # (m,q) -> m*n_points + q ; with n_points=3, (0,0)->0
    assert list(k.reject_specs) == sorted(k.reject_specs)
    assert k.reject_indices == tuple(m * k.n_points + q for (m, q) in k.reject_specs)


def test_binding_matches_live_instance():
    k = _kernel()
    k.validate_binding(_power(), _thermal(), 1.0, 1e-10)   # no raise


def test_binding_fails_on_margin_change():
    k = _kernel()
    with pytest.raises(ThermalKernelError, match="binding|margin"):
        k.validate_binding(_power(), _thermal(), 2.0, 1e-10)


def test_binding_fails_on_thermal_change():
    k = _kernel()
    other = ThermalFamily(
        model_ids=("m",),
        response_k_per_w=np.array([[[11.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 0.0, 0.0]]]),
        ambient_k=np.array([0.0]), limit_k=100.0)
    with pytest.raises(ThermalKernelError, match="binding"):
        k.validate_binding(_power(), other, 1.0, 1e-10)


def test_binding_fails_on_power_change():
    k = _kernel()
    other = PowerPolytope(
        lower_w=np.zeros(3), upper_w=np.full(3, 10.0),   # was 20
        a_eq=np.empty((0, 3)), b_eq=np.empty(0),
        a_ub=np.empty((0, 3)), b_ub=np.empty(0))
    with pytest.raises(ThermalKernelError, match="binding"):
        k.validate_binding(other, _thermal(), 1.0, 1e-10)


def test_binding_digest_is_deterministic():
    assert (binding_digest(_power(), _thermal(), 1.0, 1e-10)
            == binding_digest(_power(), _thermal(), 1.0, 1e-10))


def test_artifact_rejects_unsorted_safe_indices():
    with pytest.raises(ThermalKernelError, match="sorted"):
        VerifiedThermalKernel(
            schema_version=1, safe_row_indices=(2, 1), reject_specs=((0, 0),),
            n_safe_full=3, n_reject_full=3, n_models=1, n_points=3,
            margin_k=1.0, feas_tol=1e-10, tau=1e-6, binding_digest="x")


def test_artifact_rejects_empty_reject():
    with pytest.raises(ThermalKernelError, match="empty reject"):
        VerifiedThermalKernel(
            schema_version=1, safe_row_indices=(0,), reject_specs=(),
            n_safe_full=3, n_reject_full=3, n_models=1, n_points=3,
            margin_k=1.0, feas_tol=1e-10, tau=1e-6, binding_digest="x")


def test_artifact_rejects_non_lexicographic_specs():
    with pytest.raises(ThermalKernelError, match="lexicographic"):
        VerifiedThermalKernel(
            schema_version=1, safe_row_indices=(0,), reject_specs=((0, 2), (0, 1)),
            n_safe_full=3, n_reject_full=3, n_models=1, n_points=3,
            margin_k=1.0, feas_tol=1e-10, tau=1e-6, binding_digest="x")
