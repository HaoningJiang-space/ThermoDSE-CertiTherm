"""Witness-carrying ledger tests: LedgerSchema round-trip and LedgerReplay.

A genuine collision replays to CERTIFIED with an exact L; a tampered witness, a
subset cut, a foreign receipt digest, or a misaligned registry all fail closed to
a structured UNRESOLVED (or a raise for the structural mismatches).
"""
from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily
from CertiTherm.certificate import CertificateError
from CertiTherm.ledger import WitnessLedger, replay

DIGEST = "a" * 64
MARGIN_K = 1e-2
GUARD = Fraction(0)


def _actions():
    return tuple(
        MeasurementAction(f"m{i}", np.eye(3)[i], cost=[4.0, 2.0, 1.0][i], tolerance=0.0)
        for i in range(3))


def _power():
    return PowerPolytope(
        lower_w=np.zeros(3), upper_w=np.full(3, 100.0),
        a_eq=np.empty((0, 3)), b_eq=np.empty(0),
        a_ub=np.empty((0, 3)), b_ub=np.empty(0))


def _thermal():
    return ThermalFamily(
        model_ids=("m",), response_k_per_w=np.array([[[1.0, 1.0, 1.0]]]),
        ambient_k=np.array([300.0]), limit_k=330.0)


def _valid_ledger(**over):
    # collision: safe load 29 (<= 29.99), unsafe load 31 (>= 30.01); only block 2
    # differs so the separator set is {m2}; cut mask = [0,0,1].
    base = dict(
        receipt_digest=DIGEST,
        action_ids=("m0", "m1", "m2"),
        costs=np.array([4.0, 2.0, 1.0]),
        cut_masks=np.array([[0.0, 0.0, 1.0]]),
        safe_w=np.array([[10.0, 10.0, 9.0]]),
        unsafe_w=np.array([[10.0, 10.0, 11.0]]),
        reject_model=np.array([0]),
        reject_point=np.array([0]),
        selected_masks=np.array([[0.0, 0.0, 0.0]]),
        dual=np.array([1.0]),
        lp_slack=1e-5,
    )
    base.update(over)
    return WitnessLedger(**base)


def _replay(ledger, **over):
    kw = dict(receipt_digest=DIGEST, actions=_actions(), power=_power(),
              thermal=_thermal(), margin_k=MARGIN_K, guard=GUARD)
    kw.update(over)
    return replay(ledger, **kw)


# --- schema round-trip ----------------------------------------------------

def test_npz_roundtrip(tmp_path):
    led = _valid_ledger()
    p = tmp_path / "ledger.npz"
    led.to_npz(p)
    back = WitnessLedger.from_npz(p)
    assert back.receipt_digest == led.receipt_digest
    assert back.action_ids == led.action_ids
    np.testing.assert_array_equal(back.cut_masks, led.cut_masks)
    np.testing.assert_array_equal(back.safe_w, led.safe_w)
    assert back.lp_slack == led.lp_slack


def test_schema_rejects_bad_shapes():
    with pytest.raises(ValueError, match="dual shape"):
        _valid_ledger(dual=np.array([1.0, 2.0]))


def test_schema_rejects_negative_dual():
    with pytest.raises(ValueError, match="non-negative"):
        _valid_ledger(dual=np.array([-1.0]))


# --- replay: happy path ---------------------------------------------------

def test_replay_certifies_valid_ledger():
    r = _replay(_valid_ledger())
    assert r.status == "CERTIFIED"
    assert r.n_valid == 1 and r.n_cuts == 1
    assert r.L == Fraction(1)          # y=1: 1 + min(0, 1-1) = 1, lattice 1
    assert r.failures == ()


# --- replay: fail closed --------------------------------------------------

def test_replay_unresolved_on_bad_witness():
    # safe world loads 33 -> above SAFE ceiling
    r = _replay(_valid_ledger(safe_w=np.array([[11.0, 11.0, 11.0]])))
    assert r.status == "UNRESOLVED"
    assert r.L is None
    assert any("SAFE ceiling" in f for f in r.failures)


def test_replay_unresolved_on_subset_cut():
    # true separator set is {2}; declare an empty cut -> mismatch
    r = _replay(_valid_ledger(cut_masks=np.array([[0.0, 0.0, 0.0]])))
    assert r.status == "UNRESOLVED"
    assert any("cut" in f for f in r.failures)


def test_replay_unresolved_on_superset_cut():
    # declare {0,2}; true separator set is {2} -> exact-equality invariant rejects
    r = _replay(_valid_ledger(cut_masks=np.array([[1.0, 0.0, 1.0]])))
    assert r.status == "UNRESOLVED"
    assert any("extra" in f for f in r.failures)


def test_replay_raises_on_foreign_receipt():
    with pytest.raises(CertificateError, match="different InstanceReceipt"):
        _replay(_valid_ledger(), receipt_digest="b" * 64)


def test_replay_raises_on_misaligned_registry():
    bad = _actions()[::-1]  # reversed registry order
    with pytest.raises(CertificateError, match="action_ids do not match"):
        _replay(_valid_ledger(), actions=bad)


def test_replay_selected_separator_is_unresolved():
    # mark action 2 as selected: it IS the separator, so the pair is not a
    # collision under that selection -> validate_cut rejects it.
    r = _replay(_valid_ledger(selected_masks=np.array([[0.0, 0.0, 1.0]])))
    assert r.status == "UNRESOLVED"
    assert any("selected" in f for f in r.failures)
