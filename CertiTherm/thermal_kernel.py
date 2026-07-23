"""Production thermal-frontier kernel artifact (CertiTherm-F item 3 integration).

`VerifiedThermalKernel` holds INDEPENDENT SAFE-row and REJECT-cell subsets whose
removal provably preserves every collision, hence the optimal observation cost C*.

Soundness rests on two proved facts (see docs/KERNEL_AUDIT_EVIDENCE.md):
  - per-instance redundancy of the removed SAFE rows / REJECT cells over the
    admissible power polytope P (float audit here; exact-Farkas deferred);
  - MONOTONICITY: a SAFE row redundant / REJECT cell unreachable/dominated over P
    stays so over `P ∩ A` for ANY selected-action constraint set A (max over a
    subset ≤ max over P; a ∀-property over P holds on subsets). So one kernel is
    valid for EVERY selected set -- a one-time per-instance artifact.

This module does NOT touch the frozen collision oracle. It only builds and binds
the artifact; a sibling kernelized oracle (next step) consumes it, and every
kernel result is still witness-validated against the full constraints, degrading
to the authoritative baseline on any mismatch.

Float HiGHS audit. The kernel is bound to the instance CONTENT (polytope + thermal
+ margin + tolerance), not to any action registry -- by the monotonicity theorem
the frontier is action-independent.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from CertiTherm.synthesis import _robust_safe_rows
from CertiTherm.instance_receipt import _feed, _power_digest, _thermal_digest

KERNEL_SCHEMA_VERSION = 1
DEFAULT_TAU = 1e-6


class ThermalKernelError(ValueError):
    """A kernel artifact is invalid or does not match its live instance."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ThermalKernelError(msg)


# --- instance binding -----------------------------------------------------

def binding_digest(power, thermal, margin_k: float, feas_tol: float) -> str:
    """SHA-256 over the instance CONTENT the kernel depends on (not actions). A
    changed polytope, thermal family, margin, or tolerance invalidates the kernel."""
    d = hashlib.sha256()
    _feed(d, "thermal-kernel-binding")
    _feed(d, str(KERNEL_SCHEMA_VERSION))
    _feed(d, _power_digest(power))
    _feed(d, _thermal_digest(thermal))
    _feed(d, float(margin_k).hex())
    _feed(d, float(feas_tol).hex())
    return d.hexdigest()


# --- audit LPs (single-world P; same conventions as the oracle) -----------

class _P:
    def __init__(self, power):
        self.a_eq = np.asarray(power.a_eq, float)
        self.b_eq = np.asarray(power.b_eq, float)
        self.a_ub = np.asarray(power.a_ub, float)
        self.b_ub = np.asarray(power.b_ub, float)
        self.bounds = list(zip(np.asarray(power.lower_w, float),
                               np.asarray(power.upper_w, float)))
        self.d = power.dimension


def _max_over(P, c, extra_rows, extra_rhs):
    a_ub = P.a_ub if not len(extra_rows) else np.vstack((P.a_ub, np.asarray(extra_rows)))
    b_ub = P.b_ub if not len(extra_rows) else np.concatenate((P.b_ub, np.asarray(extra_rhs)))
    r = linprog(-np.asarray(c, float), A_ub=a_ub, b_ub=b_ub, A_eq=P.a_eq, b_eq=P.b_eq,
                bounds=P.bounds, method="highs")
    return (-r.fun) if r.status == 0 else None


def _safe_survivors(P, rows, rhs, tau):
    survivors = set(range(len(rows)))
    for j in range(len(rows)):
        others = sorted(survivors - {j})
        opt = _max_over(P, rows[j], rows[others], rhs[others])
        if opt is not None and opt <= rhs[j] - tau:
            survivors.discard(j)                 # redundant (proven, margin tau)
    return survivors


def _reject_survivors(P, rows, floors, tau):
    n = len(rows)
    survivors = set(range(n))
    for j in range(n):
        max_gj = _max_over(P, rows[j], [], [])
        if max_gj is not None and floors[j] - max_gj > tau:
            survivors.discard(j); continue       # unreachable
        others = sorted(survivors - {j})
        if not others:
            continue
        d = P.d
        obj = np.concatenate((np.zeros(d), [1.0]))
        rj = np.concatenate((-np.asarray(rows[j]), [0.0]))
        R = np.asarray([rows[k] for k in others])
        gk = np.hstack((R, -np.ones((len(others), 1))))
        a_ub = np.vstack((np.hstack((P.a_ub, np.zeros((P.a_ub.shape[0], 1)))), rj, gk))
        b_ub = np.concatenate((P.b_ub, [-floors[j]], np.asarray([floors[k] for k in others])))
        has_eq = P.a_eq.size > 0
        a_eq = np.hstack((P.a_eq, np.zeros((P.a_eq.shape[0], 1)))) if has_eq else None
        r = linprog(obj, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=P.b_eq if has_eq else None,
                    bounds=P.bounds + [(None, None)], method="highs")
        if r.status == 0 and float(r.x[-1]) > tau:
            survivors.discard(j)                 # dominated (collective)
    return survivors


# --- artifact -------------------------------------------------------------

@dataclass(frozen=True)
class VerifiedThermalKernel:
    schema_version: int
    safe_row_indices: Tuple[int, ...]                 # sorted, into the SAFE rows
    reject_specs: Tuple[Tuple[int, int], ...]         # (model, point), lexicographic
    n_safe_full: int
    n_reject_full: int
    n_models: int
    n_points: int
    margin_k: float
    feas_tol: float
    tau: float
    binding_digest: str

    def __post_init__(self) -> None:
        _require(self.schema_version == KERNEL_SCHEMA_VERSION,
                 f"unsupported kernel schema {self.schema_version}")
        _require(len(set(self.safe_row_indices)) == len(self.safe_row_indices),
                 "safe_row_indices must be unique")
        _require(list(self.safe_row_indices) == sorted(self.safe_row_indices),
                 "safe_row_indices must be sorted")
        _require(all(0 <= i < self.n_safe_full for i in self.safe_row_indices),
                 "safe_row_indices out of range")
        _require(len(set(self.reject_specs)) == len(self.reject_specs),
                 "reject_specs must be unique")
        _require(list(self.reject_specs) == sorted(self.reject_specs),
                 "reject_specs must be in lexicographic order")
        _require(all(0 <= m < self.n_models and 0 <= q < self.n_points
                     for (m, q) in self.reject_specs), "reject_specs out of range")
        # the interim contract rejects an empty REJECT subset (no vacuous cert)
        _require(len(self.reject_specs) > 0, "empty reject subset is not a certificate")

    @property
    def reject_indices(self) -> Tuple[int, ...]:
        """Flat cell indices (model*n_points + point) in lexicographic order."""
        return tuple(m * self.n_points + q for (m, q) in self.reject_specs)

    def validate_binding(self, power, thermal, margin_k: float, feas_tol: float) -> None:
        """Fail closed unless the live instance reproduces the kernel's binding
        (recomputed from live inputs -- never trust a supplied digest)."""
        live = binding_digest(power, thermal, margin_k, feas_tol)
        _require(live == self.binding_digest,
                 "kernel binding does not match the live instance; use the baseline")
        _require(float(margin_k).hex() == float(self.margin_k).hex(), "margin_k drift")
        _require(float(feas_tol).hex() == float(self.feas_tol).hex(), "feas_tol drift")


def build_kernel(power, thermal, margin_k: float, feas_tol: float,
                 tau: float = DEFAULT_TAU) -> VerifiedThermalKernel:
    """Run the SAFE-row and REJECT-cell audits independently and return a bound
    artifact. Both use the oracle's exact P, SAFE builder and REJECT floor."""
    P = _P(power)
    srows, srhs = _robust_safe_rows(thermal, margin_k)
    srows = np.asarray(srows, float); srhs = np.asarray(srhs, float)
    resp = thermal.response_k_per_w
    n_models, n_points = resp.shape[0], resp.shape[1]
    rrows, rfloors = [], []
    for m in range(n_models):
        for q in range(n_points):
            rrows.append(resp[m, q])
            rfloors.append(thermal.limit_k + margin_k - thermal.error_k[m]
                           - thermal.ambient_k[m, q])
    rrows = np.asarray(rrows, float); rfloors = np.asarray(rfloors, float)

    safe_surv = _safe_survivors(P, srows, srhs, tau)
    rej_surv = _reject_survivors(P, rrows, rfloors, tau)
    reject_specs = tuple(sorted((idx // n_points, idx % n_points) for idx in rej_surv))
    return VerifiedThermalKernel(
        schema_version=KERNEL_SCHEMA_VERSION,
        safe_row_indices=tuple(sorted(safe_surv)),
        reject_specs=reject_specs,
        n_safe_full=len(srows), n_reject_full=len(rrows),
        n_models=n_models, n_points=n_points,
        margin_k=float(margin_k), feas_tol=float(feas_tol), tau=float(tau),
        binding_digest=binding_digest(power, thermal, margin_k, feas_tol),
    )
