"""Witness-carrying cut ledger: the bridge from the strong-cut producer to the
clean-room verifier (`CertiTherm.certificate`).

Two gates, per the round-start plan:

  * `WitnessLedger` (LedgerSchema) — the on-disk structure. Each cut binds the
    `InstanceReceipt` digest, the selection it was a collision under (as an action
    mask), its reject cell, the SAFE/REJECT world-pair, its exact separator set
    (the cut support), and the LP feasibility slack. Serialised pickle-free so a
    fresh clone can load it with `allow_pickle=False`.

  * `replay` (LedgerReplay) — reload and, for EVERY cut, re-validate the witness
    and re-derive the separator set in exact arithmetic (`certificate.py`), then
    recompute the certified lower bound `L` from the RECORDED dual. Any single
    failure returns a structured `UNRESOLVED` (never a partial certificate).

This is what replaces the hand-stitched D7/D8 intervals: a bare `[L, U]` becomes
untrustworthy the moment one cut fails to reproduce its witness.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

from CertiTherm.certificate import (
    CertificateError, CertificateUnresolved,
    validate_cut, validate_witness, verify_lower_bound,
)

LEDGER_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WitnessLedger:
    """K cuts over n actions, each bound to its generating witness. Every array is
    plain (no object arrays), so `from_npz` loads with `allow_pickle=False`."""

    receipt_digest: str            # binds the whole ledger to one InstanceReceipt
    action_ids: Tuple[str, ...]    # (n,) stable IDs, order = registry order
    costs: np.ndarray              # (n,)
    cut_masks: np.ndarray          # (K, n) 0/1 -- the separator set (cut support)
    safe_w: np.ndarray             # (K, n) SAFE world of the witness
    unsafe_w: np.ndarray           # (K, n) REJECT world of the witness
    reject_model: np.ndarray       # (K,) int model index
    reject_point: np.ndarray       # (K,) int thermal point
    selected_masks: np.ndarray     # (K, n) 0/1 selection the cut was a collision under
    dual: np.ndarray               # (K,) recorded non-negative master dual for L
    lp_slack: float                # feasibility tolerance the witnesses satisfy to

    def __post_init__(self) -> None:
        # F2 (review): worlds live in POWER space (dimension d), cuts/costs/
        # selection live in ACTION space (n_actions). These are independent -- the
        # old schema conflated them by tying safe_w to n_actions, which crashes
        # whenever d != n_actions. Derive d from the worlds and n from the cuts.
        k, n = self.cut_masks.shape
        d = self.safe_w.shape[1] if self.safe_w.ndim == 2 else -1
        for name, arr, shape in (
            ("safe_w", self.safe_w, (k, d)), ("unsafe_w", self.unsafe_w, (k, d)),
            ("selected_masks", self.selected_masks, (k, n)),
            ("reject_model", self.reject_model, (k,)),
            ("reject_point", self.reject_point, (k,)), ("dual", self.dual, (k,)),
            ("costs", self.costs, (n,)),
        ):
            if arr.shape != shape:
                raise ValueError(f"{name} shape {arr.shape} != {shape}")
        if len(self.action_ids) != n:
            raise ValueError("action_ids length must equal n_actions")
        if len(set(self.action_ids)) != n:
            raise ValueError("action_ids must be unique")
        if not np.all((self.cut_masks == 0) | (self.cut_masks == 1)):
            raise ValueError("cut_masks must be 0/1")
        if not np.all((self.selected_masks == 0) | (self.selected_masks == 1)):
            raise ValueError("selected_masks must be 0/1")
        # F7 (review): finite checks BEFORE the sign check -- `NaN < 0` is False,
        # so a NaN dual would slip past and later raise on Fraction() conversion.
        for name, arr in (("costs", self.costs), ("safe_w", self.safe_w),
                          ("unsafe_w", self.unsafe_w), ("dual", self.dual)):
            if not np.all(np.isfinite(arr)):
                raise ValueError(f"{name} must be finite")
        if not np.isfinite(self.lp_slack) or self.lp_slack < 0:
            raise ValueError("lp_slack must be finite and non-negative")
        if np.any(self.dual < 0):
            raise ValueError("recorded dual must be non-negative (project first)")

    @property
    def n_cuts(self) -> int:
        return self.cut_masks.shape[0]

    def to_npz(self, path: Path) -> None:
        np.savez_compressed(
            path,
            schema_version=np.array(LEDGER_SCHEMA_VERSION),
            receipt_digest=np.array(self.receipt_digest),
            action_ids=np.array(self.action_ids),
            costs=np.asarray(self.costs, float),
            cut_masks=np.asarray(self.cut_masks, float),
            safe_w=np.asarray(self.safe_w, float),
            unsafe_w=np.asarray(self.unsafe_w, float),
            reject_model=np.asarray(self.reject_model, np.int64),
            reject_point=np.asarray(self.reject_point, np.int64),
            selected_masks=np.asarray(self.selected_masks, float),
            dual=np.asarray(self.dual, float),
            lp_slack=np.array(float(self.lp_slack)),
        )

    @classmethod
    def from_npz(cls, path: Path) -> "WitnessLedger":
        with np.load(path, allow_pickle=False) as d:
            if int(d["schema_version"]) != LEDGER_SCHEMA_VERSION:
                raise ValueError(f"unsupported ledger schema {int(d['schema_version'])}")
            return cls(
                receipt_digest=str(d["receipt_digest"]),
                action_ids=tuple(str(a) for a in d["action_ids"]),
                costs=d["costs"], cut_masks=d["cut_masks"],
                safe_w=d["safe_w"], unsafe_w=d["unsafe_w"],
                reject_model=d["reject_model"], reject_point=d["reject_point"],
                selected_masks=d["selected_masks"], dual=d["dual"],
                lp_slack=float(d["lp_slack"]),
            )


@dataclass(frozen=True)
class ReplayResult:
    """Outcome of a LedgerReplay. `status` is CERTIFIED only if every cut validated
    and `L` was computed; otherwise UNRESOLVED with the per-cut reasons."""
    status: str                       # "CERTIFIED" | "UNRESOLVED"
    n_cuts: int
    n_valid: int
    L: Optional[Fraction]
    raw_lagrangian: Optional[Fraction]
    failures: Tuple[str, ...]


def replay(
    ledger: WitnessLedger,
    *,
    receipt_digest: str,
    actions: Sequence,
    power,
    thermal,
    margin_k: float,
    guard: Fraction,
) -> ReplayResult:
    """Re-validate every cut against its witness in exact arithmetic and recompute
    `L` from the recorded dual. Fail closed: the FIRST structural mismatch (wrong
    receipt digest, misaligned registry) raises; per-cut validation failures are
    collected and, if any occurred, the result is UNRESOLVED with `L=None`.

    `guard` and `ledger.lp_slack` are the two robustness parameters (review F6):
    `guard` bands the separator classification, `lp_slack` the witness feasibility.
    Both are explicit -- the caller must choose them, not inherit a silent default."""
    if ledger.n_cuts == 0:
        # F8 (review): an empty ledger proves nothing; fail closed rather than
        # returning CERTIFIED with L=0 (that would certify "measure nothing").
        return ReplayResult("UNRESOLVED", 0, 0, None, None,
                            ("empty ledger: no cuts to certify",))
    if receipt_digest != ledger.receipt_digest:
        raise CertificateError(
            "ledger is bound to a different InstanceReceipt digest than the live "
            "instance; refusing to replay a foreign ledger")
    live_ids = tuple(a.action_id for a in actions)
    if live_ids != ledger.action_ids:
        raise CertificateError("ledger action_ids do not match the live registry order")
    # F1 (review, DEFERRED): replay still trusts `receipt_digest` as a passed
    # string and `ledger.costs` are not yet re-bound to the live registry costs. A
    # complete fix recomputes the InstanceReceipt digest from live inputs and
    # asserts ledger.costs == live action costs. This lands with the exact-witness
    # rework (F3) when the ledger is resumed; until then the ledger is NOT a
    # standalone certificate and must run inside a driver that already verified the
    # receipt against live inputs.
    live_costs = np.asarray([float(a.cost) for a in actions], dtype=float)
    if ledger.costs.shape == live_costs.shape and not np.allclose(
            ledger.costs, live_costs, rtol=0, atol=0):
        raise CertificateError("ledger costs differ from live registry costs")

    slack = Fraction(ledger.lp_slack)
    failures: List[str] = []
    valid = 0
    for k in range(ledger.n_cuts):
        safe = tuple(Fraction(float(v)) for v in ledger.safe_w[k])
        unsafe = tuple(Fraction(float(v)) for v in ledger.unsafe_w[k])
        selected = frozenset(int(i) for i in np.flatnonzero(ledger.selected_masks[k]))
        cut = frozenset(int(i) for i in np.flatnonzero(ledger.cut_masks[k]))
        try:
            validate_witness(safe, unsafe, int(ledger.reject_model[k]),
                             int(ledger.reject_point[k]), power, thermal,
                             margin_k, slack)
            validate_cut(cut, safe, unsafe, selected, actions, guard)
            valid += 1
        except (CertificateError, CertificateUnresolved) as exc:
            failures.append(f"cut {k}: {exc}")

    if failures:
        return ReplayResult("UNRESOLVED", ledger.n_cuts, valid, None, None,
                            tuple(failures))

    costs = [Fraction(float(c)) for c in ledger.costs]
    cut_rows = [tuple(int(i) for i in np.flatnonzero(ledger.cut_masks[k]))
                for k in range(ledger.n_cuts)]
    dual = [Fraction(float(y)) for y in ledger.dual]
    try:
        cert = verify_lower_bound(costs, cut_rows, dual)
    except (CertificateError, CertificateUnresolved) as exc:
        return ReplayResult("UNRESOLVED", ledger.n_cuts, valid, None, None,
                            (f"lower bound: {exc}",))
    return ReplayResult("CERTIFIED", ledger.n_cuts, valid, cert.L,
                        cert.raw_lagrangian, ())
