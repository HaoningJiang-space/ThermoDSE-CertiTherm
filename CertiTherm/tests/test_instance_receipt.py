"""Fail-closed binding tests for InstanceReceipt (v4-driver audit §1).

The receipt exists so a `[L, U]` artifact cannot be trusted unless it reproduces
the exact instance it claims to describe. These tests assert that every way an
instance can drift — a changed cost, a reordered registry, a different operator
export, a changed thermal family, a changed run tolerance, a hand-edited or
stripped artifact — makes the receipt fail closed rather than pass. The added
cases (F2/F3/F4/F12/F13) cover the bypasses the round-start peer review found.
"""
from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily
from CertiTherm.instance_receipt import InstanceReceipt, InstanceReceiptError

MARGIN_K, FEAS_TOL = 1e-4, 1e-10


def _actions():
    return (
        MeasurementAction("a::m0", np.array([1.0, 0.0, 0.0]), cost=4.0, tolerance=1e-8),
        MeasurementAction("a::m1", np.array([0.0, 1.0, 0.0]), cost=2.0, tolerance=1e-8),
        MeasurementAction("a::m2", np.array([0.0, 0.0, 1.0]), cost=1.0, tolerance=1e-8),
    )


def _power():
    return PowerPolytope.box_with_total(
        lower_w=np.zeros(3), upper_w=np.full(3, 10.0), total_w=12.0)


def _thermal():
    # (2 models, 3 thermal points, 3 blocks)
    response = np.stack([np.eye(3), 2.0 * np.eye(3)])
    return ThermalFamily(
        model_ids=("hot", "cool"), response_k_per_w=response,
        ambient_k=np.array([300.0, 300.0]), limit_k=330.0)


def _operator(tmp_path, payload=b"operator-export-bytes"):
    path = tmp_path / "arch_a--default.npz"
    path.write_bytes(payload)
    return path


def _build(tmp_path, actions=None, power=None, thermal=None, operator=None,
           margin_k=MARGIN_K, feas_tol=FEAS_TOL):
    return InstanceReceipt.build(
        candidate_id="arch_a", workload="resnet50", cand_index=2,
        actions=actions if actions is not None else _actions(),
        power=power if power is not None else _power(),
        thermal=thermal if thermal is not None else _thermal(),
        operator_path=operator if operator is not None else _operator(tmp_path),
        margin_k=margin_k, feas_tol=feas_tol,
    )


def _verify(receipt, *, actions=None, power=None, thermal=None, operator,
            margin_k=MARGIN_K, feas_tol=FEAS_TOL):
    receipt.verify(
        actions=actions if actions is not None else _actions(),
        power=power if power is not None else _power(),
        thermal=thermal if thermal is not None else _thermal(),
        operator_path=operator, margin_k=margin_k, feas_tol=feas_tol)


def test_digest_is_deterministic(tmp_path):
    op = _operator(tmp_path)
    assert _build(tmp_path, operator=op).digest == _build(tmp_path, operator=op).digest
    assert len(_build(tmp_path, operator=op).digest) == 64


def test_roundtrip_preserves_digest(tmp_path):
    r = _build(tmp_path)
    back = InstanceReceipt.from_dict(r.to_dict())
    assert back.digest == r.digest
    assert back.action_ids == r.action_ids
    assert back.thermal_digest == r.thermal_digest


def test_changed_cost_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    tampered = list(_actions())
    tampered[0] = MeasurementAction("a::m0", np.array([1.0, 0.0, 0.0]),
                                    cost=8.0, tolerance=1e-8)  # was 4.0
    with pytest.raises(InstanceReceiptError, match="registry digest"):
        _verify(r, actions=tuple(tampered), operator=op)


def test_changed_vector_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    tampered = list(_actions())
    tampered[1] = MeasurementAction("a::m1", np.array([0.0, 1.0, 1e-6]),
                                    cost=2.0, tolerance=1e-8)
    with pytest.raises(InstanceReceiptError, match="registry digest"):
        _verify(r, actions=tuple(tampered), operator=op)


def test_reordered_registry_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    with pytest.raises(InstanceReceiptError, match="action-ID ordering"):
        _verify(r, actions=tuple(reversed(_actions())), operator=op)


def test_reordered_registry_changes_digest(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    r_rev = _build(tmp_path, actions=tuple(reversed(_actions())), operator=op)
    assert r.digest != r_rev.digest


def test_changed_operator_bytes_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    op.write_bytes(b"different-operator-export")  # same path, new content
    with pytest.raises(InstanceReceiptError, match="operator export SHA-256"):
        _verify(r, operator=op)


def test_changed_power_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    other = PowerPolytope.box_with_total(
        lower_w=np.zeros(3), upper_w=np.full(3, 10.0), total_w=11.0)  # was 12.0
    with pytest.raises(InstanceReceiptError, match="power-polytope digest"):
        _verify(r, power=other, operator=op)


def test_changed_thermal_family_fails_verify(tmp_path):
    """F4: a different semantic thermal family (same block dim) must be rejected
    even though the operator file bytes are identical."""
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    other = ThermalFamily(
        model_ids=("hot", "cool"),
        response_k_per_w=np.stack([np.eye(3), 3.0 * np.eye(3)]),  # 2x -> 3x
        ambient_k=np.array([300.0, 300.0]), limit_k=330.0)
    with pytest.raises(InstanceReceiptError, match="thermal-family digest"):
        _verify(r, thermal=other, operator=op)


def test_changed_thermal_limit_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    other = ThermalFamily(
        model_ids=("hot", "cool"),
        response_k_per_w=np.stack([np.eye(3), 2.0 * np.eye(3)]),
        ambient_k=np.array([300.0, 300.0]), limit_k=331.0)  # was 330.0
    with pytest.raises(InstanceReceiptError, match="thermal-family digest"):
        _verify(r, thermal=other, operator=op)


def test_changed_margin_fails_verify(tmp_path):
    """F3: a changed run margin alters collisions and [L,U]; the old receipt must
    NOT pass verification against the drifted live margin."""
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    with pytest.raises(InstanceReceiptError, match="margin_k mismatch"):
        _verify(r, operator=op, margin_k=2e-4)


def test_changed_feas_tol_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    with pytest.raises(InstanceReceiptError, match="feas_tol mismatch"):
        _verify(r, operator=op, feas_tol=1e-9)


def test_missing_operator_on_reload_is_structured(tmp_path):
    """F12: a missing operator during verify() must raise the structured
    InstanceReceiptError, not a bare FileNotFoundError."""
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    op.unlink()
    with pytest.raises(InstanceReceiptError, match="operator export not found on reload"):
        _verify(r, operator=op)


def test_clean_reload_verifies(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    _verify(r, operator=op)  # identical instance rebuilt from scratch: no raise


def test_hand_edited_artifact_digest_fails(tmp_path):
    r = _build(tmp_path)
    doc = r.to_dict()
    doc["full_registry_cost"] = 999.0  # edit a field, leave stale digest
    with pytest.raises(InstanceReceiptError, match="embedded digest"):
        InstanceReceipt.from_dict(doc)


def test_stripped_digest_artifact_fails(tmp_path):
    """F2: deleting the digest key must NOT bypass tamper detection."""
    r = _build(tmp_path)
    doc = r.to_dict()
    del doc["digest"]
    with pytest.raises(InstanceReceiptError, match="valid 64-char hex digest"):
        InstanceReceipt.from_dict(doc)


def test_none_digest_artifact_fails(tmp_path):
    r = _build(tmp_path)
    doc = r.to_dict()
    doc["digest"] = None
    with pytest.raises(InstanceReceiptError, match="valid 64-char hex digest"):
        InstanceReceipt.from_dict(doc)


def test_malformed_digest_artifact_fails(tmp_path):
    r = _build(tmp_path)
    doc = r.to_dict()
    doc["digest"] = "not-hex-and-too-short"
    with pytest.raises(InstanceReceiptError, match="valid 64-char hex digest"):
        InstanceReceipt.from_dict(doc)


def test_signed_zero_hashes_equal(tmp_path):
    """F7: -0.0 and +0.0 are semantically equal power and must not change the
    digest."""
    op = _operator(tmp_path)
    pos = _build(tmp_path, power=PowerPolytope.box_with_total(
        lower_w=np.array([0.0, 0.0, 0.0]), upper_w=np.full(3, 10.0), total_w=12.0),
        operator=op)
    neg = _build(tmp_path, power=PowerPolytope.box_with_total(
        lower_w=np.array([-0.0, -0.0, -0.0]), upper_w=np.full(3, 10.0), total_w=12.0),
        operator=op)
    assert pos.digest == neg.digest


def test_missing_operator_fails_build(tmp_path):
    with pytest.raises(InstanceReceiptError, match="operator export not found"):
        _build(tmp_path, operator=tmp_path / "does-not-exist.npz")


def test_full_registry_cost_matches_actions(tmp_path):
    r = _build(tmp_path)
    assert r.full_registry_cost == pytest.approx(4.0 + 2.0 + 1.0)
