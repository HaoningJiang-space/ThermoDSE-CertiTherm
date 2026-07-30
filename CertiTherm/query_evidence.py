"""Everything a finished query leaves on disk, produced together so it cannot disagree.

Archiving is not table formatting. It replays an UNSYNTHESIZABLE witness through HotSpot and can
CHANGE the reported exact status as a result, it writes NPZ witness evidence, it emits several
coordinated tables, and it contributes gate-visible failures. Those outputs have to move as one
unit or the invariant between them lives in two modules -- peer review's reason for extracting this
whole concern rather than only the 167-line formatter.

Runtime resources are injected, domain rules are not. The HotSpot binary, the template directory
and the effective query budget arrive as arguments, because the driver owns them and the row must
record the budget the driver actually validated rather than an import-time environment read. Outcome
ordering and the result-schema serialisers are imported directly: injecting every helper would turn
this into a hand-wired copy of the module it came from.

Layer position: depends on `core`, `hotspot`, `paths`, `policies`, `result_schema`, `split_protocol`
and `tabular`. It has no dependency on `experiments`, which is why no cycle had to be broken to get
it out.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Iterable, Mapping, Optional, TypeVar

import numpy as np

from .core import CandidateSpace, MeasurementAction, QueryObservationPlan
from .hotspot import load_family, replay_power
from .policies import PolicyResult
from .result_schema import (
    RESULT_SCHEMA_VERSION,
    AnytimeResult,
    anytime_result_fields,
    diagnostic_result_fields,
    optional_seconds,
)
from .split_protocol import FREEZE_ID, registry_split

_T = TypeVar("_T")


@dataclass(frozen=True)
class TimedResult(Generic[_T]):
    """One independently budgeted method result and its execution receipt.

    `seconds` is None when the elapsed time is genuinely unknown -- a worker
    that died before reporting. It must never be filled with 0.0 in that case:
    a run that consumed its whole budget was once recorded as
    `width_seconds = 0.0`, which reads as "returned instantly" in the evidence
    table. An unmeasured quantity is reported as missing, not as zero.
    """

    value: Optional[_T]
    seconds: Optional[float]
    error: str

@dataclass(frozen=True)
class QueryMethodResults:
    """All methods evaluated for one ordered DSE query."""

    exact: TimedResult[QueryObservationPlan]
    fixed: TimedResult[PolicyResult]
    width: TimedResult[PolicyResult]
    dual: TimedResult[PolicyResult]
    anytime: Optional[AnytimeResult]
    query_error: str = ""

    @property
    def errors(self) -> dict[str, str]:
        if self.query_error:
            return {"query_worker": self.query_error}
        methods = (
            ("exact_dsos", self.exact),
            ("fixed_early_stop", self.fixed),
            ("uncertainty_width", self.width),
            ("dual_price", self.dual),
        )
        return {name: run.error for name, run in methods if run.error}

@dataclass(frozen=True)
class PreparedQuery:
    """Immutable handoff from physical preparation to method evaluation."""

    query_id: str
    workload_id: str
    package_id: str
    candidates: tuple[CandidateSpace, ...]
    actions: tuple[MeasurementAction, ...]
    fixed_order: tuple[int, ...]
    placed_by_candidate: Mapping[str, np.ndarray]

@dataclass(frozen=True)
class QueryEvidence:
    """Deterministic, serializable evidence emitted for one prepared query."""

    result: dict[str, object]
    plans: tuple[dict[str, object], ...]
    witnesses: tuple[dict[str, object], ...]
    witness_replays: tuple[dict[str, object], ...]
    failures: tuple[dict[str, object], ...]

def ordered_outcome(
    candidates: tuple[CandidateSpace, ...], states: Iterable[str]
) -> str:
    for candidate, state in zip(candidates, states):
        if state == "SAFE":
            return candidate.candidate_id
        if state == "NUMERICAL_GAP":
            return "UNRESOLVED"
    return "NO_FEASIBLE_CANDIDATE"

def failed_query_methods(
    error: str,
    *,
    include_anytime: bool,
) -> QueryMethodResults:
    """Represent an infrastructure failure without losing the query row."""

    # Timing is unknown, not zero: a pool failure says nothing about whether or
    # how long the individual methods ran before it.
    failed_exact: TimedResult[QueryObservationPlan] = TimedResult(None, None, "")
    failed_policy: TimedResult[PolicyResult] = TimedResult(None, None, "")
    anytime = (
        AnytimeResult(None, None, None, None, errors=(error,))
        if include_anytime
        else None
    )
    return QueryMethodResults(
        exact=failed_exact,
        fixed=failed_policy,
        width=failed_policy,
        dual=failed_policy,
        anytime=anytime,
        query_error=error,
    )

def unexpected_method_failures(
    errors: Mapping[str, str],
) -> dict[str, str]:
    """Return failures that cannot be explained by the frozen time budget."""

    return {
        method: error
        for method, error in errors.items()
        if error.partition(":")[0] != "TimeoutError"
    }

def anytime_plan_row(query_id: str, result: AnytimeResult) -> dict[str, object]:
    """Serialize the replayable contract without duplicating field logic."""

    return {
        "query_id": query_id,
        "policy": "anytime_dsos",
        "status": result.plan_validity,
        "cost": result.upper_bound if result.upper_bound is not None else "",
        "selected_count": len(result.upper_action_ids),
        "selected_action_ids": ";".join(result.upper_action_ids),
        "lower_bound": result.lower_bound if result.lower_bound is not None else "",
        "cost_optimality": result.cost_optimality,
    }

def placed_evidence(
    candidates: Iterable[CandidateSpace],
    placed_by_candidate: Mapping[str, np.ndarray],
    margin_k: float = 1e-4,
) -> dict[str, object]:
    candidates = tuple(candidates)
    model_ids = candidates[0].thermal.model_ids
    if any(candidate.thermal.model_ids != model_ids for candidate in candidates):
        raise ValueError("ordered candidates must share one thermal model registry")
    per_model_states = {model_id: [] for model_id in model_ids}
    robust_states = []
    for candidate in candidates:
        power = placed_by_candidate[candidate.candidate_id]
        thermal = candidate.thermal
        upper_peaks = []
        for model_index, model_id in enumerate(model_ids):
            peak = float(
                np.max(
                    thermal.ambient_k[model_index]
                    + thermal.response_k_per_w[model_index] @ power
                )
                + thermal.error_k[model_index]
            )
            upper_peaks.append(peak)
            per_model_states[model_id].append(
                "SAFE"
                if peak <= thermal.limit_k - margin_k
                else "REJECT"
                if peak >= thermal.limit_k + margin_k
                else "NUMERICAL_GAP"
            )
        robust_peak = max(upper_peaks)
        robust_states.append(
            "SAFE"
            if robust_peak <= thermal.limit_k - margin_k
            else "REJECT"
            if robust_peak >= thermal.limit_k + margin_k
            else "NUMERICAL_GAP"
        )
    model_outcomes = tuple(
        (model_id, ordered_outcome(candidates, states))
        for model_id, states in per_model_states.items()
    )
    return {
        "robust_outcome": ordered_outcome(candidates, robust_states),
        "model_outcomes": model_outcomes,
        "model_disagreement": int(len({outcome for _, outcome in model_outcomes}) > 1),
    }

def save_unsynth_witness(path: Path, plan) -> bool:
    if plan.status != "UNSYNTHESIZABLE" or not plan.witnesses:
        return False
    witness = plan.witnesses[-1]
    payload: dict[str, np.ndarray] = {
        "left_decision": np.asarray(witness.left_decision),
        "right_decision": np.asarray(witness.right_decision),
    }
    for index, pair in enumerate(witness.candidates):
        prefix = f"candidate_{index}"
        payload[f"{prefix}_id"] = np.asarray(pair.candidate_id)
        payload[f"{prefix}_left_power_w"] = pair.left_power_w
        payload[f"{prefix}_right_power_w"] = pair.right_power_w
        payload[f"{prefix}_left_state"] = np.asarray(pair.left_state)
        payload[f"{prefix}_right_state"] = np.asarray(pair.right_state)
        payload[f"{prefix}_left_model"] = np.asarray(pair.left_model_id)
        payload[f"{prefix}_right_model"] = np.asarray(pair.right_model_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **payload)
    return True

def replay_unsynth_witness(
    query_id: str,
    plan,
    candidates: Iterable[CandidateSpace],
    operators: Mapping[tuple[str, str], Path],
    package_id: str,
    output: Path,
    *,
    hotspot_binary: Path,
    template_dir: Path,
) -> tuple[list[dict[str, object]], bool]:
    """Re-run an UNSYNTHESIZABLE witness through HotSpot, and say whether it held up.

    This is the one place archiving can CHANGE a reported status, so the binary and the material
    template are arguments: a replay against a different HotSpot than the run used would either
    reject a valid witness or accept an invalid one, and either way the row would not say so.
    They were module globals in the driver, and a blanket rename during extraction left them as
    free names here -- a NameError reachable only on a real UNSYNTHESIZABLE plan, which is to say
    only in a claim-grade run. Named parameters make that unrepeatable.
    """

    if plan.status != "UNSYNTHESIZABLE" or not plan.witnesses:
        return [], True
    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    rows, payload, accepted = [], {}, True
    for pair in plan.witnesses[-1].candidates:
        candidate = candidate_map[pair.candidate_id]
        family, blocks = load_family(operators[(pair.candidate_id, package_id)])
        for side, power, state, model_id in (
            ("left", pair.left_power_w, pair.left_state, pair.left_model_id),
            ("right", pair.right_power_w, pair.right_state, pair.right_model_id),
        ):
            if model_id == "UNCONSTRAINED":
                continue
            replay_models = (
                family.model_ids if model_id == "ROBUST_ENVELOPE" else (model_id,)
            )
            for replay_model in replay_models:
                model_index = family.model_ids.index(replay_model)
                work = (
                    output
                    / "work"
                    / f"operator--{pair.candidate_id}--{package_id}"
                )
                direct = replay_power(
                    hotspot_binary,
                    work / "package.config",
                    work / "floorplan.flp",
                    template_dir / "example.materials",
                    replay_model,
                    blocks,
                    power,
                    output
                    / "work"
                    / "witness-replay"
                    / query_id
                    / pair.candidate_id
                    / side
                    / replay_model,
                )
                predicted = (
                    family.ambient_k[model_index]
                    + family.response_k_per_w[model_index] @ power
                )
                error = float(np.max(np.abs(direct - predicted)))
                current_pass = error <= float(family.error_k[model_index])
                accepted &= current_pass
                key = f"{pair.candidate_id}--{side}--{replay_model}"
                payload[f"{key}--direct_temperature_k"] = direct
                payload[f"{key}--predicted_temperature_k"] = predicted
                rows.append(
                    {
                        "query_id": query_id,
                        "candidate": pair.candidate_id,
                        "side": side,
                        "registered_state": state,
                        "model_role": model_id,
                        "model_id": replay_model,
                        "predicted_peak_k": float(np.max(predicted)),
                        "direct_peak_k": float(np.max(direct)),
                        "max_abs_error_k": error,
                        "registered_error_k": float(family.error_k[model_index]),
                        "replay_status": "PASS" if current_pass else "REJECT",
                    }
                )
    if payload:
        replay_path = output / "witness_replays" / f"{query_id}.npz"
        replay_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(replay_path, **payload)
    return rows, accepted

def archive_query_evidence(
    query: PreparedQuery,
    methods: QueryMethodResults,
    *,
    split: str,
    operators: Mapping[tuple[str, str], Path],
    output: Path,
    hotspot_binary: Path,
    template_dir: Path,
    query_budget_s: float,
    budget_is_frozen: bool,
) -> QueryEvidence:
    """Replay and serialize one query after its method evaluation completes.

    The last four are the driver's runtime resources, injected rather than read from module globals:
    the row must record the budget the driver actually validated, and the physical replay must use
    the binary and template the driver chose. Keyword-only and without defaults, so a caller cannot
    silently fall back to a different HotSpot or a different budget than the run was validated for.
    """

    exact = methods.exact.value
    fixed = methods.fixed.value
    width = methods.width.value
    dual = methods.dual.value
    anytime = methods.anytime
    # `QueryMethodResults.errors` is a property that builds a fresh dict on every access, so the
    # replay error added below is already local -- but relying on that is exactly the kind of
    # implementation detail a caller should not depend on, and archiving must not be able to alter
    # the evaluated result. Peer review flagged the bare assignment; the copy makes it explicit.
    method_errors = dict(methods.errors)
    failures = [
        {
            "stage": method,
            "workload": query.workload_id,
            "architecture": "ORDERED_SET",
            "package": query.package_id,
            "failure_type": error.split(":", 1)[0],
            "message": error,
        }
        for method, error in method_errors.items()
    ]

    witness_rows: list[dict[str, object]] = []
    witness_replay_rows: list[dict[str, object]] = []
    witness_path = output / "witnesses" / f"{query.query_id}.npz"
    exact_status = exact.status if exact else "UNRESOLVED"
    if exact is not None and save_unsynth_witness(witness_path, exact):
        witness_rows.append(
            {
                "query_id": query.query_id,
                "status": exact.status,
                "left_decision": exact.witnesses[-1].left_decision,
                "right_decision": exact.witnesses[-1].right_decision,
                "path": str(witness_path.relative_to(output)),
            }
        )
        replay_rows, replay_pass = replay_unsynth_witness(
            query.query_id,
            exact,
            query.candidates,
            operators,
            query.package_id,
            output,
            hotspot_binary=hotspot_binary,
            template_dir=template_dir,
        )
        witness_replay_rows.extend(replay_rows)
        witness_rows[-1]["physical_replay_status"] = (
            "PASS" if replay_pass else "REJECT"
        )
        if not replay_pass:
            exact_status = "UNRESOLVED"
            error = "witness direct replay violates frozen error contract"
            method_errors["exact_dsos_replay"] = error
            failures.append(
                {
                    "stage": "exact_dsos_replay",
                    "workload": query.workload_id,
                    "architecture": "ORDERED_SET",
                    "package": query.package_id,
                    "failure_type": "ErrorContractViolation",
                    "message": error,
                }
            )

    plan_rows = []
    for policy_name, policy in (
        ("exact_dsos", exact),
        ("fixed_early_stop", fixed),
        ("uncertainty_width", width),
        ("dual_price", dual),
    ):
        if policy is None:
            continue
        selected = policy.selected_action_ids
        plan_rows.append(
            {
                "query_id": query.query_id,
                "policy": policy_name,
                "status": exact_status if policy_name == "exact_dsos" else policy.status,
                "cost": (
                    policy.exact_cost if policy_name == "exact_dsos" else policy.cost
                ),
                "selected_count": len(selected),
                "selected_action_ids": ";".join(selected),
            }
        )
    if anytime is not None:
        plan_rows.append(anytime_plan_row(query.query_id, anytime))

    placed = placed_evidence(query.candidates, query.placed_by_candidate)
    unexpected_failures = unexpected_method_failures(method_errors)
    result = {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "freeze_id": FREEZE_ID[split],
        "split": split,
        "registry_split": registry_split(split),
        "workload": query.workload_id,
        "package": query.package_id,
        "objective": "EDYP_ASCENDING",
        "candidate_order": ";".join(
            candidate.candidate_id for candidate in query.candidates
        ),
        "exact_status": exact_status,
        "exact_cost": exact.exact_cost if exact else "",
        "milp_lower_bound": exact.lower_bound if exact else "",
        "lp_relaxation_bound": exact.relaxation_bound if exact else "",
        "optimality_gap": exact.optimality_gap if exact else "",
        # v1 does not silently acquire the later Anytime method.
        **(
            anytime_result_fields(
                anytime,
                query_budget_s=query_budget_s,
                budget_is_frozen=budget_is_frozen,
            )
            if anytime is not None
            else {}
        ),
        **diagnostic_result_fields(exact),
        "fixed_status": fixed.status if fixed else "UNRESOLVED",
        "fixed_cost": fixed.cost if fixed else "",
        "width_status": width.status if width else "UNRESOLVED",
        "width_cost": width.cost if width else "",
        "dual_status": dual.status if dual else "UNRESOLVED",
        "dual_cost": dual.cost if dual else "",
        # Blank, never 0.0, when the elapsed time was never measured.
        "exact_seconds": optional_seconds(methods.exact),
        "fixed_seconds": optional_seconds(methods.fixed),
        "width_seconds": optional_seconds(methods.width),
        "dual_seconds": optional_seconds(methods.dual),
        "full_registry_cost": sum(action.cost for action in query.actions),
        "witnesses": len(exact.witnesses) if exact else 0,
        "placed_robust_outcome": placed["robust_outcome"],
        "placed_model_outcomes": ";".join(
            f"{model}={outcome}" for model, outcome in placed["model_outcomes"]
        ),
        "placed_model_disagreement": placed["model_disagreement"],
        "false_certificate": (
            int(bool(anytime.interval_violation))
            if anytime is not None
            else 0
            if exact is not None and exact.status == "OPTIMAL"
            else ""
        ),
        "failure": "; ".join(
            f"{method}={error}" for method, error in method_errors.items()
        ),
        "unexpected_failure": "; ".join(
            f"{method}={error}"
            for method, error in unexpected_failures.items()
        ),
    }
    return QueryEvidence(
        result=result,
        plans=tuple(plan_rows),
        witnesses=tuple(witness_rows),
        witness_replays=tuple(witness_replay_rows),
        failures=tuple(failures),
    )
