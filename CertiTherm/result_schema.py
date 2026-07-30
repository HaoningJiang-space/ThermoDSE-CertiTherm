"""What an anytime run produces, and the exact columns it serialises to.

Two things that must not drift apart: the record `anytime_dsos` returns, and the TSV column list a
result table declares. They lived a thousand lines apart in `experiments.py`, and a column added to
one without the other is not a test failure -- it is a result table whose reader silently sees a
different schema than the writer wrote. Keeping them in one module is the cheapest way to make that
a visible edit.

`RESULT_SCHEMA_VERSION` is bumped whenever the column set changes shape, because adding or removing
a column changes what a downstream reader may assume. One column name (`milp_lower_bound`)
misdescribes its contents and is kept for compatibility; the version is how a reader tells which
meaning it has.

`QUERY_METHOD_TIMEOUT_S` is read from the environment at import. `BUDGET_IS_FROZEN` records whether
it still equals the preregistered 1800 s, so an artifact produced under a shortened budget cannot
pass as claim-grade. Both are import-time, which means a child process re-reads the environment
rather than inheriting the parent's value -- fine while the driver isolates candidates by process
and passes budgets explicitly, and worth knowing before that changes.

Layer position: depends on `core` and the `split_protocol` leaf, and on nothing else in this
package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Optional, Protocol

from .core import QueryObservationPlan
from .split_protocol import ANYTIME_SPLITS


QUERY_METHOD_TIMEOUT_S = float(os.environ.get("CERTITHERM_QUERY_BUDGET_S", "1800"))

FROZEN_QUERY_BUDGET_S = 1800.0

BUDGET_IS_FROZEN = abs(QUERY_METHOD_TIMEOUT_S - FROZEN_QUERY_BUDGET_S) < 1e-9

RESULT_SCHEMA_VERSION = 2

BASE_RESULT_FIELDS = (
    "result_schema_version",
    "freeze_id",
    "split",
    "registry_split",
    "workload",
    "package",
    "objective",
    "candidate_order",
    "exact_status",
    "exact_cost",
    "milp_lower_bound",
    "lp_relaxation_bound",
    "optimality_gap",
)

ANYTIME_RESULT_FIELDS = (
    "certified_upper_bound",
    "certified_lower_bound",
    "absolute_gap",
    "relative_gap",
    "approximation_ratio",
    "interval_violation",
    "anytime_upper_source",
    "anytime_upper_seconds",
    "anytime_lower_seconds",
    "anytime_error",
    "query_budget_s",
    "budget_is_frozen",
    "bound_provenance",
    "plan_validity",
    "cost_optimality",
)

DIAGNOSTIC_RESULT_FIELDS = (
    # Which algorithm actually produced `milp_lower_bound` for this row.
    # `milp_lower_bound` is a LEGACY NAME and is frequently NOT a MILP bound:
    # `_solve_master` runs only on the collision-free branch, so on every other
    # path the value comes from `_anytime_lower_bound`, an LP weak-duality
    # Lagrangian. The two differ by orders of magnitude in practice, so no
    # downstream reader may infer the algorithm from the column name.
    #   weak_duality           -> restricted-master LP Lagrangian
    #   solver_branch_and_bound-> restricted-master MILP asserted dual bound
    # The value is a query-level aggregate: a sum over candidate-local bounds,
    # which `exact_candidates_completed` qualifies.
    "exact_lower_bound_provenance",
    "exact_iterations",
    "exact_candidates_required",
    "exact_candidates_completed",
    "exact_candidate_at_stop",
    "exact_cuts_generated",
    "exact_cuts_accepted",
    "exact_cuts_dominated",
    "exact_cuts_evicted",
    "exact_cuts_active",
)

POLICY_RESULT_FIELDS = (
    "fixed_status",
    "fixed_cost",
    "width_status",
    "width_cost",
    "dual_status",
    "dual_cost",
    "exact_seconds",
    "fixed_seconds",
    "width_seconds",
    "dual_seconds",
    "full_registry_cost",
    "witnesses",
    "placed_robust_outcome",
    "placed_model_outcomes",
    "placed_model_disagreement",
    "false_certificate",
    "failure",
    "unexpected_failure",
)

def result_fieldnames(split: str) -> tuple[str, ...]:
    """Return the stable result-table contract for one method profile."""

    anytime = ANYTIME_RESULT_FIELDS if split in ANYTIME_SPLITS else ()
    return (
        BASE_RESULT_FIELDS
        + anytime
        + DIAGNOSTIC_RESULT_FIELDS
        + POLICY_RESULT_FIELDS
    )

@dataclass(frozen=True)
class CertifiedContract:
    """One oracle-certified upper bound and the actions that replay it."""

    source: str
    action_ids: tuple[str, ...]
    cost: float

    def __post_init__(self) -> None:
        if self.source not in ("width", "exact"):
            raise ValueError(f"unsupported contract source {self.source}")
        if self.cost < 0:
            raise ValueError("certified contract cost must be nonnegative")

@dataclass(frozen=True)
class AnytimeResult:
    """Proof state returned by one end-to-end Anytime-DSOS budget.

    `contract` is the only source of an upper bound.  Keeping its cost, action
    IDs and source in one object prevents a result row from combining a number
    from one policy with a plan from another.  `proof_search` is the exact/IHS
    phase that supplies the lower bound and, when it closes, the optimality
    proof.

    Therefore `lower_bound <= C* <= upper_bound` is a genuine interval rather
    than a pairing of two independently budgeted runs. That distinction is the
    whole point of method-freeze-v2.1's budget clause: reporting a `U` from one
    1800s run beside an `L` from another describes no single algorithm.
    """

    contract: Optional[CertifiedContract]
    proof_search: Optional[QueryObservationPlan]
    # None, not 0.0, when a phase never ran or the worker died before reporting.
    # Serialized blank (see `anytime_result_fields`): a hardcoded 0.0 on a
    # worker-death or pool-failure path reads as "ran instantly", the same
    # fabricated-timing defect `TimedResult` was fixed to avoid.
    upper_seconds: Optional[float]
    lower_seconds: Optional[float]
    errors: tuple[str, ...] = ()

    @property
    def upper_bound(self) -> Optional[float]:
        return None if self.contract is None else self.contract.cost

    @property
    def upper_action_ids(self) -> tuple[str, ...]:
        return () if self.contract is None else self.contract.action_ids

    @property
    def upper_source(self) -> str:
        return "none" if self.contract is None else self.contract.source

    @property
    def lower_bound(self) -> Optional[float]:
        if self.proof_search is None:
            return None
        if self.proof_search.bound_provenance == "solver_branch_and_bound":
            return self.proof_search.relaxation_bound
        return self.proof_search.lower_bound

    @property
    def error(self) -> str:
        return "; ".join(self.errors)

    @property
    def approximation_ratio(self) -> Optional[float]:
        """Certified multiplicative bound U/L; one means proven optimal."""
        if (
            self.upper_bound is None
            or self.lower_bound is None
            or self.interval_violation
        ):
            return None
        if self.lower_bound > 0:
            return self.upper_bound / self.lower_bound
        if self.upper_bound == 0:
            return 1.0
        return None

    @property
    def relative_gap(self) -> Optional[float]:
        """Standard lower-bound-relative gap, equal to U/L - 1."""
        ratio = self.approximation_ratio
        return None if ratio is None else max(0.0, ratio - 1.0)

    @property
    def absolute_gap(self) -> Optional[float]:
        if (
            self.upper_bound is None
            or self.lower_bound is None
            or self.interval_violation
        ):
            return None
        return max(0.0, self.upper_bound - self.lower_bound)

    @property
    def interval_violation(self) -> str:
        if (
            self.upper_bound is not None
            and self.proof_search is not None
            and self.proof_search.status == "UNSYNTHESIZABLE"
        ):
            return "certified upper plan conflicts with UNSYNTHESIZABLE result"
        if self.upper_bound is None or self.lower_bound is None:
            return ""
        slack = 1e-6 * max(1.0, abs(self.upper_bound))
        if self.lower_bound > self.upper_bound + slack:
            return f"L={self.lower_bound} exceeds U={self.upper_bound}"
        return ""

    @property
    def bound_provenance(self) -> str:
        if self.lower_bound is None or self.proof_search is None:
            return ""
        return "weak_duality"

    @property
    def plan_validity(self) -> str:
        if self.interval_violation:
            return "UNRESOLVED"
        if self.upper_bound is not None:
            return "CERTIFIED"
        if (
            self.proof_search is not None
            and self.proof_search.status == "UNSYNTHESIZABLE"
        ):
            return "UNSYNTHESIZABLE"
        return "UNRESOLVED"

    @property
    def cost_optimality(self) -> str:
        if self.interval_violation:
            return "UNKNOWN"
        if (
            self.proof_search is not None
            and self.proof_search.status == "UNSYNTHESIZABLE"
        ):
            return "NOT_APPLICABLE"
        if (
            self.proof_search is not None
            and self.proof_search.status == "OPTIMAL"
            and self.upper_source == "exact"
        ):
            return self.proof_search.cost_optimality
        if self.upper_bound is not None and self.lower_bound is not None:
            return "BOUNDED_GAP"
        return "UNKNOWN"

class TimedLike(Protocol):
    """Anything carrying a measured duration, or None when it was never measured.

    A structural type rather than an import: the concrete `TimedResult` belongs to the
    query-method concern, and naming it here would point this module at the driver. The forward
    reference that used to stand in its place was dangling -- lazy annotations kept it from
    raising, so nothing said the name was unresolvable from here.
    """

    seconds: Optional[float]


def optional_seconds(result: TimedLike) -> object:
    """Serialize an execution time, or BLANK when it was never measured.

    Blank rather than 0.0. A missing duration written as zero reads back as an instantaneous
    success, which is the one interpretation the data cannot support.
    """

    return "" if result.seconds is None else result.seconds

def diagnostic_result_fields(
    exact: Optional[QueryObservationPlan],
) -> dict[str, object]:
    """Serialize the exact method's separation diagnostics.

    Sourced from the `exact` baseline rather than the Anytime controller's
    internal proof search: `exact` runs the same constraint generation under its
    own full budget, so it is the cleanest read on separation behaviour and it
    exists in every profile that runs the exact method.

    Blank rather than zero when the method produced no plan at all -- a zero
    would assert "ran and did nothing", which is a different claim from "never
    reported".
    """

    if exact is None:
        return {field: "" for field in DIAGNOSTIC_RESULT_FIELDS}
    return {
        "exact_lower_bound_provenance": exact.bound_provenance or "",
        "exact_iterations": exact.iterations,
        "exact_candidates_required": exact.candidates_required,
        "exact_candidates_completed": exact.candidates_completed,
        "exact_candidate_at_stop": (
            "" if exact.candidate_at_stop is None else exact.candidate_at_stop
        ),
        "exact_cuts_generated": exact.cuts_generated,
        "exact_cuts_accepted": exact.cuts_accepted,
        "exact_cuts_dominated": exact.cuts_dominated,
        "exact_cuts_evicted": exact.cuts_evicted,
        "exact_cuts_active": exact.cuts_active,
    }

def anytime_result_fields(result: AnytimeResult) -> dict[str, object]:
    """Serialize every v2+ endpoint from the same Anytime-DSOS result."""

    def optional(value: Optional[float]) -> object:
        return "" if value is None else value

    return {
        "certified_upper_bound": optional(result.upper_bound),
        "certified_lower_bound": optional(result.lower_bound),
        "absolute_gap": optional(result.absolute_gap),
        "relative_gap": optional(result.relative_gap),
        "approximation_ratio": optional(result.approximation_ratio),
        "interval_violation": result.interval_violation,
        "anytime_upper_source": result.upper_source,
        "anytime_upper_seconds": optional(result.upper_seconds),
        "anytime_lower_seconds": optional(result.lower_seconds),
        "anytime_error": result.error,
        "query_budget_s": QUERY_METHOD_TIMEOUT_S,
        "budget_is_frozen": int(BUDGET_IS_FROZEN),
        "bound_provenance": result.bound_provenance,
        "plan_validity": result.plan_validity,
        "cost_optimality": result.cost_optimality,
    }
