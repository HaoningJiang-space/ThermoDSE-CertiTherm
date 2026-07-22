"""Small, validated data model for decision-sufficient observation synthesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

import numpy as np


def _vector(value: np.ndarray, n: int, name: str) -> np.ndarray:
    out = np.asarray(value, dtype=float)
    if out.shape != (n,) or not np.all(np.isfinite(out)):
        raise ValueError(f"{name} must be a finite ({n},) vector")
    return out


def _matrix(value: np.ndarray, n: int, name: str) -> np.ndarray:
    out = np.asarray(value, dtype=float)
    if out.ndim != 2 or out.shape[1] != n or not np.all(np.isfinite(out)):
        raise ValueError(f"{name} must be a finite matrix with {n} columns")
    return out


@dataclass(frozen=True)
class PowerPolytope:
    """Compact admissible placed-power set."""

    lower_w: np.ndarray
    upper_w: np.ndarray
    a_eq: np.ndarray
    b_eq: np.ndarray
    a_ub: np.ndarray
    b_ub: np.ndarray

    def __post_init__(self) -> None:
        lower = np.asarray(self.lower_w, dtype=float)
        if lower.ndim != 1 or not np.all(np.isfinite(lower)):
            raise ValueError("lower_w must be a finite vector")
        n = lower.size
        upper = _vector(self.upper_w, n, "upper_w")
        a_eq = _matrix(self.a_eq, n, "a_eq")
        b_eq = _vector(self.b_eq, a_eq.shape[0], "b_eq")
        a_ub = _matrix(self.a_ub, n, "a_ub")
        b_ub = _vector(self.b_ub, a_ub.shape[0], "b_ub")
        if np.any(lower < 0) or np.any(upper < lower):
            raise ValueError("power bounds must obey 0 <= lower <= upper")
        for name, value in (
            ("lower_w", lower),
            ("upper_w", upper),
            ("a_eq", a_eq),
            ("b_eq", b_eq),
            ("a_ub", a_ub),
            ("b_ub", b_ub),
        ):
            object.__setattr__(self, name, value)

    @classmethod
    def box_with_total(
        cls, lower_w: np.ndarray, upper_w: np.ndarray, total_w: float
    ) -> "PowerPolytope":
        n = np.asarray(lower_w).size
        return cls(
            lower_w=np.asarray(lower_w),
            upper_w=np.asarray(upper_w),
            a_eq=np.ones((1, n)),
            b_eq=np.array([total_w]),
            a_ub=np.empty((0, n)),
            b_ub=np.empty(0),
        )

    @property
    def dimension(self) -> int:
        return self.lower_w.size


@dataclass(frozen=True)
class ThermalFamily:
    """Registered finite family of linear HotSpot operators."""

    model_ids: Tuple[str, ...]
    response_k_per_w: np.ndarray
    ambient_k: np.ndarray
    limit_k: float
    provenance_sha256: Tuple[str, ...] = ()
    error_k: np.ndarray = field(default_factory=lambda: np.empty(0))

    def __post_init__(self) -> None:
        response = np.asarray(self.response_k_per_w, dtype=float)
        if response.ndim != 3 or min(response.shape) == 0:
            raise ValueError("response must have shape (models, thermal_points, blocks)")
        if not np.all(np.isfinite(response)) or np.any(response < -1e-10):
            raise ValueError("thermal response must be finite and nonnegative")
        response = np.maximum(response, 0.0)
        ambient = np.asarray(self.ambient_k, dtype=float)
        if ambient.shape == (response.shape[0],):
            ambient = np.repeat(ambient[:, None], response.shape[1], axis=1)
        if ambient.shape != response.shape[:2] or not np.all(np.isfinite(ambient)):
            raise ValueError("ambient must have shape (models,) or (models, thermal_points)")
        if len(self.model_ids) != response.shape[0] or len(set(self.model_ids)) != len(
            self.model_ids
        ):
            raise ValueError("model_ids must uniquely name every model")
        if not np.isfinite(self.limit_k):
            raise ValueError("limit_k must be finite")
        if self.provenance_sha256 and len(self.provenance_sha256) != response.shape[0]:
            raise ValueError("provenance must identify every model")
        error = np.asarray(self.error_k, dtype=float)
        if error.size == 0:
            error = np.zeros(response.shape[0])
        if (
            error.shape != (response.shape[0],)
            or not np.all(np.isfinite(error))
            or np.any(error < 0)
        ):
            raise ValueError("error_k must be one finite nonnegative bound per model")
        object.__setattr__(self, "response_k_per_w", response)
        object.__setattr__(self, "ambient_k", ambient)
        object.__setattr__(self, "error_k", error)

    @property
    def blocks(self) -> int:
        return self.response_k_per_w.shape[2]


@dataclass(frozen=True)
class MeasurementAction:
    """One obtainable linear power measurement."""

    action_id: str
    vector: np.ndarray
    cost: float = 1.0
    tolerance: float = 1e-8
    candidate_id: str = "candidate"

    def __post_init__(self) -> None:
        vector = np.asarray(self.vector, dtype=float)
        if vector.ndim != 1 or not np.all(np.isfinite(vector)):
            raise ValueError("measurement vector must be finite")
        if not self.action_id or not self.candidate_id:
            raise ValueError("action_id and candidate_id are required")
        if not np.isfinite(self.cost) or self.cost <= 0:
            raise ValueError("positive finite cost is required")
        if not np.isfinite(self.tolerance) or self.tolerance < 0:
            raise ValueError("measurement tolerance must be finite and nonnegative")
        object.__setattr__(self, "vector", vector)


@dataclass(frozen=True)
class CandidateSpace:
    """One ordered DSE candidate and its registered physical worlds."""

    candidate_id: str
    power: PowerPolytope
    thermal: ThermalFamily

    def __post_init__(self) -> None:
        if not self.candidate_id or self.power.dimension != self.thermal.blocks:
            raise ValueError("candidate identity and consistent dimensions are required")


@dataclass(frozen=True)
class WorldPair:
    """Safe/unsafe worlds that current observations cannot distinguish."""

    safe_power_w: np.ndarray
    unsafe_power_w: np.ndarray
    safe_model_id: str
    unsafe_model_id: str
    unsafe_point: int

    @property
    def cause(self) -> str:
        if np.allclose(self.safe_power_w, self.unsafe_power_w, atol=1e-8, rtol=0):
            return "MODEL_NON_IDENTIFIABLE"
        return "POWER_NON_IDENTIFIABLE"


@dataclass(frozen=True)
class CandidateWorldPair:
    candidate_id: str
    left_power_w: np.ndarray
    right_power_w: np.ndarray
    left_state: str
    right_state: str
    left_model_id: str
    right_model_id: str


@dataclass(frozen=True)
class QueryWorldPair:
    left_decision: str
    right_decision: str
    candidates: Tuple[CandidateWorldPair, ...]


@dataclass(frozen=True)
class ObservationPlan:
    """Result of one synthesis run.

    `selected_action_ids` is reserved for a plan the collision oracle has
    CERTIFIED collision-free. It is empty whenever no such plan was reached.

    `status` separates two independent questions. `OPTIMAL` means a certified
    plan whose minimum cost is established -- but read `bound_provenance`
    before treating that as proved. Only `weak_duality` results are verifiable
    from the returned numbers alone; `solver_branch_and_bound` results are
    conditional on the MIP solver being correct, which is cross-checked for
    consistency but not proved. Reporting both under one `OPTIMAL` status is a
    known API weakness: peer review recommends splitting plan validity from
    cost optimality into orthogonal fields, which is deferred rather than
    resolved. `CERTIFIED_PLAN` means the plan is
    oracle-certified but the budget ran out before minimum cost could be
    proven -- `lower_bound` and `optimality_gap` are then both real, since the
    certified plan supplies a genuine upper bound. `UNSYNTHESIZABLE` means no
    plan exists in the registered library. `UNRESOLVED` means nothing was
    established.

    `candidate_action_ids` / `candidate_cost` carry the last working cover
    when synthesis ended without certification. That cover hits every cut
    discovered so far but has NOT been re-checked by the oracle since it was
    last recomputed, so its cost is NOT a valid upper bound on the optimum and
    must never be reported as one. Promoting a candidate to
    `selected_action_ids` requires an oracle pass proving it collision-free.
    """

    status: str
    selected_action_ids: Tuple[str, ...]
    exact_cost: Optional[float]
    lower_bound: Optional[float]
    relaxation_bound: Optional[float]
    optimality_gap: Optional[float]
    iterations: int
    witnesses: Tuple[WorldPair, ...]
    message: str
    candidate_action_ids: Tuple[str, ...] = ()
    candidate_cost: Optional[float] = None
    upper_bound: Optional[float] = None

    @property
    def plan_validity(self) -> str:
        """Is there a plan the oracle certified? Independent of its cost.

        CERTIFIED / UNSYNTHESIZABLE / UNRESOLVED.
        """
        if self.status in ("OPTIMAL", "CERTIFIED_PLAN"):
            return "CERTIFIED"
        if self.status == "UNSYNTHESIZABLE":
            return "UNSYNTHESIZABLE"
        return "UNRESOLVED"

    @property
    def cost_optimality(self) -> str:
        """How well is the plan's COST established? Independent of validity.

        PROVEN_SELF_VERIFIABLE -- optimal, and the proof is checkable from the
            returned numbers alone.
        PROVEN_SOLVER_ATTESTED -- optimal per the MIP solver's asserted dual
            bound, cross-checked for consistency but not proved. A
            self-consistent wrong solver would not be caught.
        BOUNDED_GAP -- a certified plan with a valid lower bound but no proof
            of minimality.
        NOT_APPLICABLE -- no plan can exist, so cost optimality is meaningless.
        UNKNOWN -- nothing established.

        These two properties exist because one `status` enum cannot carry both
        questions honestly: an OPTIMAL result whose bound is solver-attested is
        simultaneously "certified" and "not proved from the artifact". Peer
        review flagged that as a semantic contradiction; splitting the
        dimensions resolves it without changing any construction site.
        """
        if self.status == "UNSYNTHESIZABLE":
            return "NOT_APPLICABLE"
        if self.status == "OPTIMAL":
            return (
                "PROVEN_SELF_VERIFIABLE"
                if self.bound_provenance == "weak_duality"
                else "PROVEN_SOLVER_ATTESTED"
            )
        if self.status == "CERTIFIED_PLAN":
            return "BOUNDED_GAP" if self.lower_bound is not None else "UNKNOWN"
        return "UNKNOWN"
    # "weak_duality": the reported bound is verifiable from the returned numbers
    # alone. "solver_branch_and_bound": optimality was closed by the MIP
    # solver's asserted dual bound, which is cross-checked for consistency but
    # not proved -- a self-consistent wrong solver could still pass. Report the
    # split rather than implying every certificate is equally self-contained.
    bound_provenance: Optional[str] = None


@dataclass(frozen=True)
class QueryObservationPlan:
    """Result of an ordered multi-candidate query.

    `selected_action_ids` is a plan certified for the WHOLE ordered query. It
    is empty unless `status == "OPTIMAL"`.

    `certified_prefix_action_ids` carries the actions from candidates that did
    complete when a later candidate did not. Those candidates are individually
    certified, but a prefix is not a plan for the full query, so it must not be
    read as one.
    """

    status: str
    selected_action_ids: Tuple[str, ...]
    exact_cost: Optional[float]
    lower_bound: Optional[float]
    relaxation_bound: Optional[float]
    optimality_gap: Optional[float]
    iterations: int
    witnesses: Tuple[QueryWorldPair, ...]
    message: str
    certified_prefix_action_ids: Tuple[str, ...] = ()
    # Weakest provenance across the candidates: a query is only as
    # self-verifiable as its least self-verifiable subproblem.
    bound_provenance: Optional[str] = None

    @property
    def plan_validity(self) -> str:
        if self.status == "OPTIMAL":
            return "CERTIFIED"
        if self.status == "UNSYNTHESIZABLE":
            return "UNSYNTHESIZABLE"
        return "UNRESOLVED"

    @property
    def cost_optimality(self) -> str:
        if self.status == "UNSYNTHESIZABLE":
            return "NOT_APPLICABLE"
        if self.status == "OPTIMAL":
            return (
                "PROVEN_SELF_VERIFIABLE"
                if self.bound_provenance == "weak_duality"
                else "PROVEN_SOLVER_ATTESTED"
            )
        return "UNKNOWN"
