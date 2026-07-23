"""Clean-room verifier tests (verifier-first, round-start F4/F5/F6/F7/F8).

These assert the exact-arithmetic certificate checks reject every unsound input:
a subset/superset cut, a selected-action separator, a borderline witness, a
non-collision witness, and — crucially — that a fabricated huge dual cannot
inflate the exact lower bound.
"""
from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily
from CertiTherm.certificate import (
    CertificateError, CertificateUnresolved,
    cost_lattice, exact_lagrangian, lattice_lift,
    separator_set, validate_cut, validate_witness, verify_lower_bound,
    verify_upper_bound,
)

G0 = Fraction(0)  # zero guard: exact separator classification for clean fixtures


def _actions():
    # 3 axis-aligned unit measurements, tol 0 so any nonzero projection separates
    return tuple(
        MeasurementAction(f"m{i}", np.eye(3)[i], cost=[4.0, 2.0, 1.0][i], tolerance=0.0)
        for i in range(3))


def _power():
    # box only, NO total-power equality: with response = sum, a fixed total would
    # make SAFE (load <= 30-margin) and REJECT (load >= 30+margin) jointly infeasible.
    return PowerPolytope(
        lower_w=np.zeros(3), upper_w=np.full(3, 100.0),
        a_eq=np.empty((0, 3)), b_eq=np.empty(0),
        a_ub=np.empty((0, 3)), b_ub=np.empty(0))


def _thermal():
    # 1 model, 1 point, response = identity row [1,1,1]; limit 330, ambient 300
    return ThermalFamily(
        model_ids=("m",), response_k_per_w=np.array([[[1.0, 1.0, 1.0]]]),
        ambient_k=np.array([300.0]), limit_k=330.0)


# --- separator set --------------------------------------------------------

def test_separator_set_picks_differing_blocks():
    safe = (Fraction(10), Fraction(10), Fraction(10))
    unsafe = (Fraction(10), Fraction(13), Fraction(7))  # blocks 1,2 differ
    S = separator_set(safe, unsafe, _actions(), G0)
    assert S == frozenset({1, 2})


def test_separator_ambiguous_gap_is_unresolved():
    acts = (MeasurementAction("m0", np.array([1.0, 0.0, 0.0]), tolerance=1.0),)
    safe = (Fraction(3, 2), Fraction(0), Fraction(0))
    unsafe = (Fraction(0), Fraction(0), Fraction(0))  # |v·Δ| = 1.5, tol 1.0
    with pytest.raises(CertificateUnresolved, match="not establishable"):
        separator_set(safe, unsafe, acts, Fraction(1))  # guard 1 -> [0,2] band


# --- cut validity (F4/F5) -------------------------------------------------

def test_validate_cut_accepts_exact_mask():
    safe = (Fraction(10), Fraction(10), Fraction(10))
    unsafe = (Fraction(10), Fraction(13), Fraction(7))
    assert validate_cut(frozenset({1, 2}), safe, unsafe, frozenset(), _actions(), G0) \
        == frozenset({1, 2})


def test_validate_cut_rejects_proper_subset():
    safe = (Fraction(10), Fraction(10), Fraction(10))
    unsafe = (Fraction(10), Fraction(13), Fraction(7))  # mask {1,2}
    with pytest.raises(CertificateError, match="missing"):
        validate_cut(frozenset({1}), safe, unsafe, frozenset(), _actions(), G0)


def test_validate_cut_rejects_superset():
    safe = (Fraction(10), Fraction(10), Fraction(10))
    unsafe = (Fraction(10), Fraction(13), Fraction(10))  # only block 1 differs -> mask {1}
    with pytest.raises(CertificateError, match="extra"):
        validate_cut(frozenset({0, 1}), safe, unsafe, frozenset(), _actions(), G0)


def test_validate_cut_rejects_selected_separator():
    safe = (Fraction(10), Fraction(10), Fraction(10))
    unsafe = (Fraction(10), Fraction(13), Fraction(7))  # mask {1,2}
    with pytest.raises(CertificateError, match="intersects selected"):
        validate_cut(frozenset({1, 2}), safe, unsafe, frozenset({2}), _actions(), G0)


def test_validate_cut_rejects_empty_mask():
    safe = (Fraction(5), Fraction(5), Fraction(5))
    with pytest.raises(CertificateError, match="UNSYNTHESIZABLE"):
        validate_cut(frozenset(), safe, safe, frozenset(), _actions(), G0)


# --- witness validity (F6) ------------------------------------------------

def _feasible_pair():
    # response = sum; margin 1e-2 -> SAFE ceiling 29.99, REJECT floor 30.01.
    safe = (Fraction(10), Fraction(10), Fraction(9))     # load 29 <= 29.99
    unsafe = (Fraction(10), Fraction(10), Fraction(11))  # load 31 >= 30.01
    return safe, unsafe


def test_validate_witness_accepts_robust_collision():
    safe, unsafe = _feasible_pair()
    validate_witness(safe, unsafe, 0, 0, _power(), _thermal(),
                     margin_k=1e-2, slack=Fraction(1, 100000))


def test_validate_witness_rejects_safe_over_ceiling():
    # safe world loads 33 -> above SAFE ceiling 29.99
    safe = (Fraction(11), Fraction(11), Fraction(11))   # load 33
    unsafe = (Fraction(10), Fraction(10), Fraction(11))  # load 31
    with pytest.raises(CertificateError, match="SAFE ceiling"):
        validate_witness(safe, unsafe, 0, 0, _power(), _thermal(),
                         margin_k=1e-2, slack=Fraction(1, 100000))


def test_validate_witness_slack_ge_margin_unresolved():
    safe, unsafe = _feasible_pair()
    with pytest.raises(CertificateUnresolved, match="not robustly separable"):
        validate_witness(safe, unsafe, 0, 0, _power(), _thermal(),
                         margin_k=1e-4, slack=Fraction(1, 1000))  # slack > margin


# --- exact lower bound (F8) ----------------------------------------------

def test_lagrangian_valid_for_fabricated_huge_dual():
    # costs 1 each; one cut over action 0. A huge fabricated dual must NOT inflate
    # the bound past the true optimum (=1): min(0, c0 - y0) cancels the +y0.
    costs = [Fraction(1), Fraction(1)]
    cut_rows = [[0]]
    small = exact_lagrangian(costs, cut_rows, [Fraction(1)])
    huge = exact_lagrangian(costs, cut_rows, [Fraction(10**6)])
    assert small == Fraction(1)
    assert huge == Fraction(1)          # y=1e6: 1e6 + min(0, 1-1e6) = 1
    assert huge <= Fraction(1)


def test_lagrangian_rejects_negative_dual():
    with pytest.raises(CertificateError, match="negative"):
        exact_lagrangian([Fraction(1)], [[0]], [Fraction(-1)])


def test_lagrangian_length_mismatch():
    with pytest.raises(CertificateError, match="dual length"):
        exact_lagrangian([Fraction(1)], [[0]], [Fraction(1), Fraction(1)])


def test_cost_lattice_and_lift():
    costs = [Fraction(1), Fraction(2), Fraction(4), Fraction(8)]
    assert cost_lattice(costs) == Fraction(1)
    assert lattice_lift(Fraction(15, 2), costs) == Fraction(8)   # ceil(7.5)
    assert lattice_lift(Fraction(8), costs) == Fraction(8)       # already on lattice


def test_lift_respects_fractional_lattice():
    costs = [Fraction(1, 2), Fraction(3, 2)]      # lattice 1/2
    assert cost_lattice(costs) == Fraction(1, 2)
    assert lattice_lift(Fraction(7, 10), costs) == Fraction(1)   # ceil(0.7/0.5)=2 -> 1.0


def test_verify_lower_bound_end_to_end():
    costs = [Fraction(4), Fraction(2), Fraction(1)]
    cut_rows = [[0, 1], [1, 2]]         # both cuts must be hit
    cert = verify_lower_bound(costs, cut_rows, [Fraction(2), Fraction(1)])
    assert cert.L >= cert.raw_lagrangian
    assert cert.lattice == Fraction(1)


def test_upper_bound_fails_closed():
    with pytest.raises(CertificateUnresolved, match="not yet implemented"):
        verify_upper_bound()
