"""Architecture-selection semantics for CertiTherm G2.

Candidate bounds alone are supporting evidence.  The G2 decision object is a
deterministically ordered architecture query over the Cartesian product of all
candidate power domains.  This module converts replayed candidate bounds into
reachable outcomes and complete decision-changing power tuples.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

try:
    from .decide import decide
    from .linear_oracle import (
        UNRESOLVED,
        canonical_sha256,
        normalize_problem,
        replay_power_witness,
    )
except ImportError:  # pragma: no cover - direct script/test-path execution.
    from decide import decide
    from linear_oracle import (
        UNRESOLVED,
        canonical_sha256,
        normalize_problem,
        replay_power_witness,
    )


QUERY_SCHEMA_VERSION = "certitherm.architecture-selection-query.v1"
QUERY_RESULT_SCHEMA_VERSION = "certitherm.architecture-selection-result.v1"
TUPLE_SCHEMA_VERSION = "certitherm.decision-witness-tuple.v1"

CERTIFIED = "CERTIFIED"
NON_IDENTIFIABLE = "NON_IDENTIFIABLE"
NO_FEASIBLE_DESIGN = "NO_FEASIBLE_DESIGN"


class QueryInputError(ValueError):
    pass


def _candidate_id(candidate: Mapping[str, Any]) -> str:
    value = candidate.get("candidate_id")
    if not isinstance(value, str) or not value.strip() or value == NO_FEASIBLE_DESIGN:
        raise QueryInputError("candidate_id must be non-empty and non-reserved")
    return value


def _objective(candidate: Mapping[str, Any]) -> float:
    try:
        value = float(candidate["nonthermal_objective"])
    except (KeyError, TypeError, ValueError) as exc:
        raise QueryInputError("nonthermal_objective must be supplied and numeric") from exc
    if not np.isfinite(value):
        raise QueryInputError("nonthermal_objective must be finite")
    return value


def _tie_rank(candidate: Mapping[str, Any]) -> int:
    value = candidate.get("tie_break_rank")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise QueryInputError("tie_break_rank must be a non-negative integer")
    return value


def _candidate_arrays(candidate: Mapping[str, Any]) -> tuple[Any, Any, Any, Sequence[str]]:
    response = candidate.get("response_k_per_w", candidate.get("R"))
    ambient = candidate.get("ambient_k", candidate.get("T_ambient"))
    observation = candidate.get("observation")
    block_names = candidate.get("block_names")
    if response is None or ambient is None or observation is None or block_names is None:
        raise QueryInputError(
            "candidate must bind response_k_per_w, ambient_k, observation, and block_names"
        )
    return response, ambient, observation, block_names


def _area_ok(candidate: Mapping[str, Any]) -> bool:
    area = candidate.get("area_mm2")
    if area is None:
        return True
    try:
        area_value = float(area)
        budget_value = float(candidate.get("A_budget_m2", 3e-4))
    except (TypeError, ValueError) as exc:
        raise QueryInputError("candidate area fields must be numeric") from exc
    if not np.isfinite(area_value) or area_value < 0 or not np.isfinite(budget_value) or budget_value < 0:
        raise QueryInputError("candidate area fields must be finite and non-negative")
    return area_value * 1e-6 <= budget_value + 1e-12


def _ordered_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)) or not candidates:
        raise QueryInputError("query must contain at least one candidate")
    if any(not isinstance(candidate, Mapping) for candidate in candidates):
        raise QueryInputError("every candidate must be a mapping")
    ids = [_candidate_id(candidate) for candidate in candidates]
    ranks = [_tie_rank(candidate) for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise QueryInputError("candidate IDs must be unique")
    if len(ranks) != len(set(ranks)):
        raise QueryInputError("tie-break ranks must be unique")
    return sorted(candidates, key=lambda item: (_objective(item), _tie_rank(item)))


def _query_unresolved(reason: str, detail: str, **extra: Any) -> dict[str, Any]:
    result = {
        "schema_version": QUERY_RESULT_SCHEMA_VERSION,
        "status": UNRESOLVED,
        "reason": reason,
        "detail": detail,
    }
    result.update(extra)
    return result


def replay_architecture_tuple(
    candidates: Sequence[Mapping[str, Any]],
    witness_tuple: Mapping[str, Any],
    *,
    thermal_limit_k: float,
    feasibility_tolerance: float = 1e-7,
    decision_tolerance_k: float = 1e-6,
) -> dict[str, Any]:
    """Replay a complete cross-candidate tuple without invoking an optimizer."""

    try:
        ordered = _ordered_candidates(candidates)
        if witness_tuple.get("schema_version") != TUPLE_SCHEMA_VERSION:
            raise QueryInputError("unsupported witness-tuple schema")
        supplied_tuple_digest = witness_tuple.get("tuple_digest")
        tuple_payload = {
            key: value for key, value in witness_tuple.items() if key != "tuple_digest"
        }
        if supplied_tuple_digest != canonical_sha256(tuple_payload):
            raise QueryInputError("witness tuple digest mismatch")
        entries = witness_tuple.get("candidates")
        if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
            raise QueryInputError("witness tuple candidates must be a sequence")
        by_id: dict[str, Mapping[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise QueryInputError("witness tuple entry must be a mapping")
            entry_id = entry.get("candidate_id")
            if not isinstance(entry_id, str) or entry_id in by_id:
                raise QueryInputError("witness tuple candidate IDs must be unique text")
            by_id[entry_id] = entry
        expected_ids = {_candidate_id(candidate) for candidate in ordered}
        if set(by_id) != expected_ids:
            raise QueryInputError("witness tuple must bind every query candidate exactly once")
        limit = float(thermal_limit_k)
        if not np.isfinite(limit):
            raise QueryInputError("thermal_limit_k must be finite")
    except (QueryInputError, TypeError, ValueError) as exc:
        return {"valid": False, "reason": str(exc)}

    selected = NO_FEASIBLE_DESIGN
    candidate_replays = []
    for candidate in ordered:
        candidate_id = _candidate_id(candidate)
        response, ambient, observation, block_names = _candidate_arrays(candidate)
        try:
            problem = normalize_problem(response, ambient, observation, block_names)
            replay = replay_power_witness(
                problem,
                by_id[candidate_id].get("power_w"),
                feasibility_tolerance=feasibility_tolerance,
            )
            if not replay.get("valid"):
                return {
                    "valid": False,
                    "reason": f"candidate {candidate_id} power replay failed",
                    "candidate_replay": replay,
                }
            entry_digest = by_id[candidate_id].get("candidate_input_digest")
            if entry_digest != problem.input_digest:
                return {
                    "valid": False,
                    "reason": f"candidate {candidate_id} digest mismatch",
                }
            thermally_feasible = float(replay["peak_temperature_k"]) <= limit + decision_tolerance_k
            feasible = bool(_area_ok(candidate) and thermally_feasible)
        except (QueryInputError, TypeError, ValueError) as exc:
            return {"valid": False, "reason": f"candidate {candidate_id}: {exc}"}
        candidate_replays.append(
            {
                "candidate_id": candidate_id,
                "peak_temperature_k": replay["peak_temperature_k"],
                "thermally_feasible": thermally_feasible,
                "nonthermal_feasible": _area_ok(candidate),
                "selected_feasible": feasible,
            }
        )
        if selected == NO_FEASIBLE_DESIGN and feasible:
            selected = candidate_id

    expected_outcome = witness_tuple.get("expected_outcome")
    valid = isinstance(expected_outcome, str) and selected == expected_outcome
    return {
        "valid": bool(valid),
        "selected_outcome": selected,
        "expected_outcome": expected_outcome,
        "candidate_replays": candidate_replays,
        "reason": None if valid else "replayed selection differs from expected outcome",
    }


def _make_tuple(
    outcome: str,
    ordered: Sequence[Mapping[str, Any]],
    candidate_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    target_index = None
    if outcome != NO_FEASIBLE_DESIGN:
        target_index = next(
            index for index, candidate in enumerate(ordered) if _candidate_id(candidate) == outcome
        )
    entries = []
    for index, (candidate, result) in enumerate(zip(ordered, candidate_results)):
        if outcome == NO_FEASIBLE_DESIGN or (target_index is not None and index < target_index):
            power = result["witness_upper"] if _area_ok(candidate) else result["witness_lower"]
        else:
            power = result["witness_lower"]
        entries.append(
            {
                "candidate_id": _candidate_id(candidate),
                "candidate_input_digest": result["input_digest"],
                "power_w": power,
            }
        )
    payload = {
        "schema_version": TUPLE_SCHEMA_VERSION,
        "expected_outcome": outcome,
        "candidates": entries,
    }
    payload["tuple_digest"] = canonical_sha256(payload)
    return payload


def decide_architecture_query(
    query_id: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    thermal_limit_k: float,
) -> dict[str, Any]:
    """Return CERTIFIED/NON_IDENTIFIABLE/UNRESOLVED for one DSE query."""

    try:
        if not isinstance(query_id, str) or not query_id.strip():
            raise QueryInputError("query_id must be non-empty text")
        limit = float(thermal_limit_k)
        if not np.isfinite(limit) or limit < 0:
            raise QueryInputError("thermal_limit_k must be finite and non-negative")
        ordered = _ordered_candidates(candidates)
    except (QueryInputError, TypeError, ValueError) as exc:
        return _query_unresolved("UNRESOLVED_INVALID_INPUT", str(exc))

    candidate_results: list[dict[str, Any]] = []
    candidate_summaries: list[dict[str, Any]] = []
    query_input_records = []
    for candidate in ordered:
        candidate_id = _candidate_id(candidate)
        try:
            response, ambient, observation, block_names = _candidate_arrays(candidate)
        except QueryInputError as exc:
            return _query_unresolved("UNRESOLVED_INVALID_INPUT", str(exc))
        result = decide(
            candidate.get("sys_info", []),
            response,
            ambient,
            observation,
            block_names,
            T_budget=limit,
            A_budget_m2=candidate.get("A_budget_m2", 3e-4),
            area_mm2=candidate.get("area_mm2"),
        )
        candidate_results.append(result)
        candidate_summaries.append(
            {
                "candidate_id": candidate_id,
                "nonthermal_objective": _objective(candidate),
                "tie_break_rank": _tie_rank(candidate),
                "result": result,
            }
        )
        if result.get("status") == UNRESOLVED:
            return _query_unresolved(
                result.get("reason", "UNRESOLVED_SOLVER_STATUS"),
                f"candidate {candidate_id}: {result.get('detail', '')}",
                candidate_bounds=candidate_summaries,
            )
        query_input_records.append(
            {
                "candidate_id": candidate_id,
                "input_digest": result["input_digest"],
                "nonthermal_objective": _objective(candidate),
                "tie_break_rank": _tie_rank(candidate),
                "area_ok": result["area_ok"],
            }
        )

    reachable: list[str] = []
    earlier_can_all_fail = True
    for candidate, result in zip(ordered, candidate_results):
        if earlier_can_all_fail and result["can_be_feasible"]:
            reachable.append(_candidate_id(candidate))
        earlier_can_all_fail = earlier_can_all_fail and result["can_be_infeasible"]
    if earlier_can_all_fail:
        reachable.append(NO_FEASIBLE_DESIGN)
    if not reachable:
        return _query_unresolved(
            "UNRESOLVED_CERTIFICATE_FAILURE",
            "no reachable selection outcome was constructed",
            candidate_bounds=candidate_summaries,
        )

    query_digest = canonical_sha256(
        {
            "schema_version": QUERY_SCHEMA_VERSION,
            "query_id": query_id,
            "thermal_limit_k": limit,
            "candidates": query_input_records,
        }
    )
    tuples = [_make_tuple(outcome, ordered, candidate_results) for outcome in reachable[:2]]
    tuple_replays = [
        replay_architecture_tuple(ordered, witness_tuple, thermal_limit_k=limit)
        for witness_tuple in tuples
    ]
    if not all(replay.get("valid") for replay in tuple_replays):
        return _query_unresolved(
            "UNRESOLVED_CERTIFICATE_FAILURE",
            "one or more architecture witness tuples failed independent direct replay",
            query_digest=query_digest,
            reachable_outcomes=reachable,
            candidate_bounds=candidate_summaries,
            witness_tuples=tuples,
            tuple_replays=tuple_replays,
        )

    status = CERTIFIED if len(reachable) == 1 else NON_IDENTIFIABLE
    return {
        "schema_version": QUERY_RESULT_SCHEMA_VERSION,
        "status": status,
        "query_id": query_id,
        "query_digest": query_digest,
        "thermal_limit_k": limit,
        "certified_outcome": reachable[0] if status == CERTIFIED else None,
        "reachable_outcomes": reachable,
        "candidate_bounds": candidate_summaries,
        "witness_tuples": tuples,
        "tuple_replays": tuple_replays,
    }
