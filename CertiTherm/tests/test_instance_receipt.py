"""Fail-closed binding tests for InstanceReceipt (v4-driver audit §1).

The receipt exists so a `[L, U]` artifact cannot be trusted unless it reproduces
the exact instance it claims to describe. These tests assert that every way an
instance can drift — a changed cost, a reordered registry, a different operator
export, a hand-edited artifact — makes the receipt fail closed rather than pass.
"""
from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.core import MeasurementAction, PowerPolytope
from CertiTherm.instance_receipt import InstanceReceipt, InstanceReceiptError


def _actions():
    return (
        MeasurementAction("a::m0", np.array([1.0, 0.0, 0.0]), cost=4.0, tolerance=1e-8),
        MeasurementAction("a::m1", np.array([0.0, 1.0, 0.0]), cost=2.0, tolerance=1e-8),
        MeasurementAction("a::m2", np.array([0.0, 0.0, 1.0]), cost=1.0, tolerance=1e-8),
    )


def _power():
    return PowerPolytope.box_with_total(
        lower_w=np.zeros(3), upper_w=np.full(3, 10.0), total_w=12.0)


def _operator(tmp_path, payload=b"operator-export-bytes"):
    path = tmp_path / "arch_a--default.npz"
    path.write_bytes(payload)
    return path


def _build(tmp_path, actions=None, operator=None):
    return InstanceReceipt.build(
        candidate_id="arch_a", workload="resnet50", cand_index=2,
        actions=actions if actions is not None else _actions(),
        power=_power(),
        operator_path=operator if operator is not None else _operator(tmp_path),
        margin_k=1e-4, feas_tol=1e-10,
    )


def test_digest_is_deterministic(tmp_path):
    op = _operator(tmp_path)
    r1 = _build(tmp_path, operator=op)
    r2 = _build(tmp_path, operator=op)
    assert r1.digest == r2.digest
    assert len(r1.digest) == 64


def test_roundtrip_preserves_digest(tmp_path):
    r = _build(tmp_path)
    back = InstanceReceipt.from_dict(r.to_dict())
    assert back.digest == r.digest
    assert back.action_ids == r.action_ids


def test_changed_cost_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    tampered = list(_actions())
    tampered[0] = MeasurementAction("a::m0", np.array([1.0, 0.0, 0.0]),
                                    cost=8.0, tolerance=1e-8)  # was 4.0
    with pytest.raises(InstanceReceiptError, match="registry digest"):
        r.verify(actions=tuple(tampered), power=_power(), operator_path=op)


def test_changed_vector_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    tampered = list(_actions())
    tampered[1] = MeasurementAction("a::m1", np.array([0.0, 1.0, 1e-6]),
                                    cost=2.0, tolerance=1e-8)
    with pytest.raises(InstanceReceiptError, match="registry digest"):
        r.verify(actions=tuple(tampered), power=_power(), operator_path=op)


def test_reordered_registry_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    reordered = tuple(reversed(_actions()))
    with pytest.raises(InstanceReceiptError, match="action-ID ordering"):
        r.verify(actions=reordered, power=_power(), operator_path=op)


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
        r.verify(actions=_actions(), power=_power(), operator_path=op)


def test_changed_power_fails_verify(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    other_power = PowerPolytope.box_with_total(
        lower_w=np.zeros(3), upper_w=np.full(3, 10.0), total_w=11.0)  # was 12.0
    with pytest.raises(InstanceReceiptError, match="power-polytope digest"):
        r.verify(actions=_actions(), power=other_power, operator_path=op)


def test_clean_reload_verifies(tmp_path):
    op = _operator(tmp_path)
    r = _build(tmp_path, operator=op)
    # identical instance rebuilt from scratch verifies without raising
    r.verify(actions=_actions(), power=_power(), operator_path=op)


def test_hand_edited_artifact_digest_fails(tmp_path):
    r = _build(tmp_path)
    doc = r.to_dict()
    doc["full_registry_cost"] = 999.0  # edit a field, leave stale digest
    with pytest.raises(InstanceReceiptError, match="embedded digest"):
        InstanceReceipt.from_dict(doc)


def test_missing_operator_fails_build(tmp_path):
    with pytest.raises(InstanceReceiptError, match="operator export not found"):
        _build(tmp_path, operator=tmp_path / "does-not-exist.npz")


def test_full_registry_cost_matches_actions(tmp_path):
    r = _build(tmp_path)
    assert r.full_registry_cost == pytest.approx(4.0 + 2.0 + 1.0)
