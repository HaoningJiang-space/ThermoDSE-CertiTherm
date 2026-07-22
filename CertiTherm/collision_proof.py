"""Independent CPU verification for approximate collision-LP proposals.

Accelerators may propose a feasible point or a Farkas-style infeasibility
ray.  Neither proposal is trusted: this module rechecks it with conservative
binary64 intervals.  An inconclusive check is ``UNKNOWN`` and must fall back
to the frozen HiGHS path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence, Tuple

import numpy as np


class ProposalKind(str, Enum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class LinearFeasibilitySystem:
    """Canonical LP feasibility data, with finite box bounds."""

    a_ub: np.ndarray
    b_ub: np.ndarray
    a_eq: np.ndarray
    b_eq: np.ndarray
    lower: np.ndarray
    upper: np.ndarray

    def __post_init__(self) -> None:
        n = np.asarray(self.lower).size
        arrays = (
            np.asarray(self.a_ub, dtype=float),
            np.asarray(self.b_ub, dtype=float),
            np.asarray(self.a_eq, dtype=float),
            np.asarray(self.b_eq, dtype=float),
            np.asarray(self.lower, dtype=float),
            np.asarray(self.upper, dtype=float),
        )
        a_ub, b_ub, a_eq, b_eq, lower, upper = arrays
        if a_ub.shape != (b_ub.size, n) or a_eq.shape != (b_eq.size, n):
            raise ValueError("constraint matrix dimensions are inconsistent")
        if lower.shape != (n,) or upper.shape != (n,):
            raise ValueError("bounds must be one-dimensional")
        if not all(np.all(np.isfinite(value)) for value in arrays):
            raise ValueError("proof inputs must be finite")
        if np.any(lower > upper):
            raise ValueError("lower bound exceeds upper bound")
        for name, value in zip(
            ("a_ub", "b_ub", "a_eq", "b_eq", "lower", "upper"), arrays
        ):
            value = value.copy()
            value.flags.writeable = False
            object.__setattr__(self, name, value)

    @property
    def variables(self) -> int:
        return self.lower.size

    def certificate_inequalities(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return ``A x <= b`` rows used by the ray verifier.

        Equalities are represented by their two inequality orientations.
        Bounds remain a box domain; keeping them separate enables a
        residual-aware certificate instead of requiring ``A.T @ y == 0``.
        """

        return (
            np.vstack((self.a_ub, self.a_eq, -self.a_eq)),
            np.concatenate((self.b_ub, self.b_eq, -self.b_eq)),
        )


@dataclass(frozen=True)
class CollisionProposal:
    kind: ProposalKind
    primal: Optional[np.ndarray] = None
    ray: Optional[np.ndarray] = None


@dataclass(frozen=True)
class ProofCheck:
    accepted: bool
    kind: ProposalKind
    reason: str
    certified_slack: Optional[float] = None


def _outward_dot(left: Sequence[float], right: Sequence[float]) -> Tuple[float, float]:
    """Enclose a binary64 dot product without changing the rounding mode."""

    products = [float(a) * float(b) for a, b in zip(left, right)]
    if not all(math.isfinite(value) for value in products):
        raise ValueError("non-finite dot product")
    center = math.fsum(products)
    magnitude = math.fsum(abs(value) for value in products)
    unit = np.finfo(float).eps / 2.0
    product_error = unit / (1.0 - unit) * magnitude
    rounding_error = abs(np.nextafter(center, math.inf) - center)
    radius = product_error + rounding_error
    return (
        float(np.nextafter(center - radius, -math.inf)),
        float(np.nextafter(center + radius, math.inf)),
    )


def _outward_sum_lower(values: Sequence[float]) -> float:
    if not all(math.isfinite(value) for value in values):
        raise ValueError("non-finite interval sum")
    center = math.fsum(values)
    return float(np.nextafter(center, -math.inf))


def _expanded(value: float, tolerance: float, direction: float) -> float:
    return float(np.nextafter(value + direction * tolerance, direction * math.inf))


def verify_feasible_point(
    system: LinearFeasibilitySystem,
    point: Sequence[float],
    tolerance: float,
) -> ProofCheck:
    """Conservatively verify every row and bound of a proposed feasible point."""

    x = np.asarray(point, dtype=float)
    if tolerance < 0 or not math.isfinite(tolerance):
        raise ValueError("tolerance must be finite and non-negative")
    if x.shape != (system.variables,) or not np.all(np.isfinite(x)):
        return ProofCheck(False, ProposalKind.UNKNOWN, "invalid primal proposal")
    lower = np.array(
        [_expanded(float(value), tolerance, -1.0) for value in system.lower]
    )
    upper = np.array(
        [_expanded(float(value), tolerance, 1.0) for value in system.upper]
    )
    if np.any(x < lower) or np.any(x > upper):
        return ProofCheck(False, ProposalKind.UNKNOWN, "bound violation")
    for row, rhs in zip(system.a_ub, system.b_ub):
        if _outward_dot(row, x)[1] > _expanded(float(rhs), tolerance, 1.0):
            return ProofCheck(False, ProposalKind.UNKNOWN, "inequality violation")
    for row, rhs in zip(system.a_eq, system.b_eq):
        lower, upper = _outward_dot(row, x)
        if lower < _expanded(float(rhs), tolerance, -1.0) or upper > _expanded(
            float(rhs), tolerance, 1.0
        ):
            return ProofCheck(False, ProposalKind.UNKNOWN, "equality violation")
    return ProofCheck(True, ProposalKind.FEASIBLE, "all primal constraints verified")


def verify_infeasible_ray(
    system: LinearFeasibilitySystem,
    ray: Sequence[float],
) -> ProofCheck:
    """Verify a residual-aware Farkas contradiction over the finite box.

    For ``y >= 0``, every feasible ``x`` obeys ``(A.T y).T x <= b.T y``.
    Therefore ``min_{x in [l,u]} (A.T y).T x > b.T y`` proves infeasibility,
    even when the proposed ray has a non-zero dual residual.
    """

    matrix, rhs = system.certificate_inequalities()
    y = np.asarray(ray, dtype=float)
    if y.shape != (rhs.size,) or not np.all(np.isfinite(y)):
        return ProofCheck(False, ProposalKind.UNKNOWN, "invalid ray proposal")
    if np.any(y < 0.0) or not np.any(y > 0.0):
        return ProofCheck(False, ProposalKind.UNKNOWN, "ray is not non-negative")
    y = y / float(np.max(y))

    residual_intervals = [
        _outward_dot(matrix[:, column], y)
        for column in range(system.variables)
    ]
    coordinate_lowers = []
    for (r_lower, r_upper), x_lower, x_upper in zip(
        residual_intervals, system.lower, system.upper
    ):
        products = (
            r_lower * x_lower,
            r_lower * x_upper,
            r_upper * x_lower,
            r_upper * x_upper,
        )
        coordinate_lowers.append(float(np.nextafter(min(products), -math.inf)))
    left_lower = _outward_sum_lower(coordinate_lowers)
    right_upper = _outward_dot(rhs, y)[1]
    slack = left_lower - right_upper
    if math.isfinite(slack) and left_lower > right_upper:
        return ProofCheck(
            True,
            ProposalKind.INFEASIBLE,
            "residual-aware Farkas inequality verified",
            slack,
        )
    return ProofCheck(False, ProposalKind.UNKNOWN, "ray contradiction is not strict")


def verify_proposal(
    system: LinearFeasibilitySystem,
    proposal: CollisionProposal,
    feasibility_tolerance: float,
) -> ProofCheck:
    """Apply the only trusted transition from a proposal to a verdict."""

    if proposal.kind == ProposalKind.FEASIBLE and proposal.primal is not None:
        return verify_feasible_point(system, proposal.primal, feasibility_tolerance)
    if proposal.kind == ProposalKind.INFEASIBLE and proposal.ray is not None:
        return verify_infeasible_ray(system, proposal.ray)
    return ProofCheck(False, ProposalKind.UNKNOWN, "no checkable proposal")
