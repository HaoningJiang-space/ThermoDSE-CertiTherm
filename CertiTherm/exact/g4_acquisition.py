"""Decision-level, witness-directed information acquisition for CertiTherm G4.

G4 is applicable only after a complete architecture-selection query is
``NON_IDENTIFIABLE``.  A registered action adds one obtainable linear power
measurement to one candidate, then re-solves the *complete* query at the two
values induced by its decision-changing witness tuples.

The result is deliberately narrow: the cheapest registered action that
confirms both witness outcomes.  This is not a proof that the action resolves
every possible measurement value, nor is it a global minimum-information
policy outside the supplied registry.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import platform
import re
import resource
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np
import scipy

try:
    from .decision_query import CERTIFIED, NON_IDENTIFIABLE, decide_architecture_query
    from .evidence import replay_artifact, sha256_file
    from .g3_full_empirical import replay_g3_suite_artifact
    from .linear_oracle import (
        UNRESOLVED,
        canonical_sha256,
        normalize_problem,
        replay_power_witness,
    )
except ImportError:  # pragma: no cover - direct script/test-path execution.
    from decision_query import CERTIFIED, NON_IDENTIFIABLE, decide_architecture_query
    from evidence import replay_artifact, sha256_file
    from g3_full_empirical import replay_g3_suite_artifact
    from linear_oracle import (
        UNRESOLVED,
        canonical_sha256,
        normalize_problem,
        replay_power_witness,
    )


REGISTRY_SCHEMA_VERSION = "certitherm.g4-measurement-registry.v1"
RESULT_SCHEMA_VERSION = "certitherm.g4-acquisition-result.v1"
ARTIFACT_SCHEMA_VERSION = "certitherm.g4-acquisition-artifact.v1"
REPLAY_SCHEMA_VERSION = "certitherm.g4-acquisition-replay.v1"

WITNESS_PAIR_CONFIRMED = "WITNESS_PAIR_CONFIRMED"
NO_REGISTERED_ACTION = "NO_REGISTERED_WITNESS_CONFIRMING_ACTION"
NOT_APPLICABLE = "NOT_APPLICABLE"

SYNTHETIC_MEASUREMENT_FAMILY = "synthetic_fixture"
PHYSICAL_MEASUREMENT_FAMILY = "physical_measurement_family"

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_CLAIM_BOUNDARY = (
    "The selected action is cheapest only within the content-bound registry "
    "under its declared cost model. Both registered witness values yield "
    "certified, distinct architecture outcomes. This does not prove resolution "
    "for every possible measurement value or global policy optimality."
)


class G4InputError(ValueError):
    """Raised when an input cannot support the frozen G4 contract."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise G4InputError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise G4InputError(f"{path.name} must contain a JSON object")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise G4InputError(f"{field} must match {_ID_RE.pattern}")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise G4InputError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise G4InputError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise G4InputError(f"{field} must be numeric") from exc
    if not np.isfinite(number) or number <= 0.0:
        raise G4InputError(f"{field} must be finite and positive")
    return number


def _candidate_map(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise G4InputError("query candidates must be a sequence")
    by_id: dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise G4InputError("query candidate must be a mapping")
        candidate_id = _identifier(candidate.get("candidate_id"), "candidate_id")
        if candidate_id in by_id:
            raise G4InputError("query candidate IDs must be unique")
        by_id[candidate_id] = candidate
    if not by_id:
        raise G4InputError("query must contain at least one candidate")
    return by_id


def validate_measurement_registry(
    registry: Mapping[str, Any],
    *,
    base_query_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and canonicalize a content-bound action registry."""

    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise G4InputError("unsupported G4 measurement-registry schema")
    evidence_class = registry.get("evidence_class")
    if evidence_class not in (
        SYNTHETIC_MEASUREMENT_FAMILY,
        PHYSICAL_MEASUREMENT_FAMILY,
    ):
        raise G4InputError(
            "evidence_class must be synthetic_fixture or physical_measurement_family"
        )
    registry_id = _identifier(registry.get("registry_id"), "registry_id")
    base_artifact_digest = _digest(
        base_query_artifact.get("artifact_sha256"), "base query artifact_sha256"
    )
    if registry.get("query_artifact_sha256") != base_artifact_digest:
        raise G4InputError("registry is not bound to the supplied query artifact")
    base_result = base_query_artifact.get("result")
    if not isinstance(base_result, Mapping):
        raise G4InputError("base query artifact has no result mapping")
    base_query_digest = _digest(base_result.get("query_digest"), "base query_digest")
    if registry.get("query_digest") != base_query_digest:
        raise G4InputError("registry query_digest does not match the supplied query")

    registration = registry.get("registration")
    if not isinstance(registration, Mapping):
        raise G4InputError("registration must be a mapping")
    normalized_registration: dict[str, str] = {}
    for field in ("measurement_family", "cost_model", "cost_unit", "obtainability_basis"):
        value = registration.get(field)
        if not isinstance(value, str) or not value.strip():
            raise G4InputError(f"registration.{field} must be non-empty text")
        normalized_registration[field] = value.strip()

    raw_source_files = registry.get("source_files")
    if not isinstance(raw_source_files, list):
        raise G4InputError("source_files must be a list")
    if evidence_class == PHYSICAL_MEASUREMENT_FAMILY and not raw_source_files:
        raise G4InputError("a physical measurement family requires source_files")
    normalized_source_files: list[dict[str, str]] = []
    source_roles: set[str] = set()
    for index, record in enumerate(raw_source_files):
        if not isinstance(record, Mapping):
            raise G4InputError(f"source_files[{index}] must be a mapping")
        role = record.get("role")
        path = record.get("path")
        normalized_role = role.strip() if isinstance(role, str) else ""
        if not normalized_role or normalized_role in source_roles:
            raise G4InputError("source file roles must be non-empty and unique")
        source_roles.add(normalized_role)
        if not isinstance(path, str) or not path or Path(path).is_absolute():
            raise G4InputError("source file paths must be non-empty and relative")
        relative = Path(path)
        if ".." in relative.parts:
            raise G4InputError("source file paths cannot escape the registry bundle")
        normalized_source_files.append(
            {
                "role": normalized_role,
                "path": relative.as_posix(),
                "sha256": _digest(record.get("sha256"), "source file sha256"),
            }
        )

    tolerance = _positive_number(
        registry.get("measurement_value_tolerance_w", 1e-9),
        "measurement_value_tolerance_w",
    )
    inputs = base_query_artifact.get("inputs")
    if not isinstance(inputs, Mapping):
        raise G4InputError("base query artifact has no inputs mapping")
    by_id = _candidate_map(inputs.get("candidates"))

    raw_actions = registry.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise G4InputError("registry actions must be a non-empty list")
    action_ids: set[str] = set()
    normalized_actions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_actions):
        if not isinstance(raw, Mapping):
            raise G4InputError(f"actions[{index}] must be a mapping")
        measurement_id = _identifier(
            raw.get("measurement_id"), f"actions[{index}].measurement_id"
        )
        if measurement_id in action_ids:
            raise G4InputError("measurement IDs must be unique")
        action_ids.add(measurement_id)
        candidate_id = _identifier(
            raw.get("candidate_id"), f"actions[{index}].candidate_id"
        )
        if candidate_id not in by_id:
            raise G4InputError(f"action {measurement_id} targets an unknown candidate")
        candidate = by_id[candidate_id]
        block_names = candidate.get("block_names")
        if not isinstance(block_names, Sequence) or isinstance(block_names, (str, bytes)):
            raise G4InputError(f"candidate {candidate_id} has invalid block identities")
        block_set = set(block_names)

        raw_coefficients = raw.get("coefficients_by_block")
        if not isinstance(raw_coefficients, Mapping) or not raw_coefficients:
            raise G4InputError(
                f"action {measurement_id} coefficients_by_block must be non-empty"
            )
        coefficients: dict[str, float] = {}
        for block_name, raw_coefficient in raw_coefficients.items():
            if not isinstance(block_name, str) or block_name not in block_set:
                raise G4InputError(
                    f"action {measurement_id} references an unknown block: {block_name}"
                )
            if isinstance(raw_coefficient, bool):
                raise G4InputError(f"action {measurement_id} has a non-numeric coefficient")
            try:
                coefficient = float(raw_coefficient)
            except (TypeError, ValueError) as exc:
                raise G4InputError(
                    f"action {measurement_id} has a non-numeric coefficient"
                ) from exc
            if not np.isfinite(coefficient) or coefficient < 0.0:
                raise G4InputError(
                    f"action {measurement_id} coefficients must be finite and non-negative"
                )
            if coefficient > 0.0:
                coefficients[block_name] = coefficient
        if not coefficients:
            raise G4InputError(f"action {measurement_id} has an all-zero linear form")
        cost = _positive_number(raw.get("cost"), f"actions[{index}].cost")
        rationale = raw.get("obtainability_record")
        if not isinstance(rationale, str) or not rationale.strip():
            raise G4InputError(
                f"action {measurement_id} obtainability_record must be non-empty text"
            )
        normalized_actions.append(
            {
                "measurement_id": measurement_id,
                "candidate_id": candidate_id,
                "coefficients_by_block": dict(sorted(coefficients.items())),
                "cost": cost,
                "obtainability_record": rationale.strip(),
            }
        )

    normalized_actions.sort(key=lambda item: (item["cost"], item["measurement_id"]))
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "registry_id": registry_id,
        "evidence_class": evidence_class,
        "query_artifact_sha256": base_artifact_digest,
        "query_digest": base_query_digest,
        "measurement_value_tolerance_w": tolerance,
        "registration": normalized_registration,
        "source_files": normalized_source_files,
        "actions": normalized_actions,
    }


def load_measurement_registry_bundle(
    registry_path: Path,
) -> tuple[Mapping[str, Any], list[dict[str, str]]]:
    """Load a registry and verify every declared source-file digest."""

    registry_path = registry_path.resolve()
    registry = _read_json(registry_path)
    source_files = registry.get("source_files")
    if not isinstance(source_files, list):
        raise G4InputError("source_files must be a list")
    input_records = [
        {
            "role": "measurement_registry",
            "path": registry_path.name,
            "sha256": sha256_file(registry_path),
        }
    ]
    for index, record in enumerate(source_files):
        if not isinstance(record, Mapping):
            raise G4InputError(f"source_files[{index}] must be a mapping")
        relative_value = record.get("path")
        if not isinstance(relative_value, str) or not relative_value:
            raise G4InputError(f"source_files[{index}].path must be relative text")
        relative = Path(relative_value)
        if relative.is_absolute():
            raise G4InputError("source file paths must be relative to the registry")
        target = (registry_path.parent / relative).resolve()
        try:
            target.relative_to(registry_path.parent.resolve())
        except ValueError as exc:
            raise G4InputError("source file escapes the registry bundle") from exc
        if not target.is_file():
            raise G4InputError(f"measurement source file does not exist: {relative}")
        expected = _digest(record.get("sha256"), "source file sha256")
        actual = sha256_file(target)
        if actual != expected:
            raise G4InputError(f"measurement source digest mismatch: {relative}")
        role = record.get("role")
        if not isinstance(role, str) or not role.strip():
            raise G4InputError("measurement source role must be non-empty text")
        input_records.append(
            {
                "role": f"measurement_source_{role.strip()}",
                "path": relative.as_posix(),
                "sha256": actual,
            }
        )
    return registry, input_records


def _measurement_vector(
    candidate: Mapping[str, Any], coefficients_by_block: Mapping[str, float]
) -> np.ndarray:
    names = candidate.get("block_names")
    if not isinstance(names, Sequence) or isinstance(names, (str, bytes)):
        raise G4InputError("candidate block_names must be a sequence")
    if any(not isinstance(name, str) or not name for name in names):
        raise G4InputError("candidate block identities must be non-empty text")
    if not isinstance(coefficients_by_block, Mapping) or not coefficients_by_block:
        raise G4InputError("measurement coefficients must be a non-empty mapping")
    unknown = set(coefficients_by_block) - set(names)
    if unknown:
        rendered = sorted(str(item) for item in unknown)
        raise G4InputError(f"measurement references unknown blocks: {rendered}")
    values = []
    for name in names:
        raw = coefficients_by_block.get(name, 0.0)
        if isinstance(raw, bool):
            raise G4InputError("measurement coefficients must be numeric")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise G4InputError("measurement coefficients must be numeric") from exc
        if not np.isfinite(value) or value < 0.0:
            raise G4InputError(
                "measurement coefficients must be finite and non-negative"
            )
        values.append(value)
    return np.asarray(values, dtype=np.float64)


def append_registered_measurement(
    candidate: Mapping[str, Any],
    coefficients_by_block: Mapping[str, float],
    measurement_value_w: float,
) -> dict[str, Any]:
    """Append one equality while preserving every existing domain constraint."""

    try:
        problem = normalize_problem(
            candidate.get("response_k_per_w", candidate.get("R")),
            candidate.get("ambient_k", candidate.get("T_ambient")),
            candidate["observation"],
            candidate["block_names"],
        )
        value = float(measurement_value_w)
    except (KeyError, TypeError, ValueError) as exc:
        raise G4InputError(f"cannot normalize candidate observation: {exc}") from exc
    if not np.isfinite(value):
        raise G4InputError("measurement value must be finite")
    weight = _measurement_vector(candidate, coefficients_by_block)
    if weight.shape != (problem.dimension,) or np.any(weight < 0.0):
        raise G4InputError("measurement weight is invalid")
    if not np.any(weight > 0.0):
        raise G4InputError("measurement weight cannot be all zero")

    observation = copy.deepcopy(dict(candidate["observation"]))
    observation.pop("per_block_power", None)
    observation["A_eq"] = np.vstack([problem.a_eq, weight]).tolist()
    observation["b_eq"] = np.concatenate([problem.b_eq, [value]]).tolist()
    observation["per_block_lower"] = problem.lower_w.tolist()
    observation["per_block_upper"] = problem.upper_w.tolist()
    if problem.a_ub.shape[0]:
        observation["A_ub"] = problem.a_ub.tolist()
        observation["b_ub"] = problem.b_ub.tolist()
    else:
        observation.pop("A_ub", None)
        observation.pop("b_ub", None)
    return observation


def _tuple_power(
    witness_tuple: Mapping[str, Any], candidate_id: str, dimension: int
) -> np.ndarray:
    entries = witness_tuple.get("candidates")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise G4InputError("witness tuple candidate entries must be a sequence")
    matches = [
        entry
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("candidate_id") == candidate_id
    ]
    if len(matches) != 1:
        raise G4InputError("witness tuple does not bind the targeted candidate exactly once")
    power = np.asarray(matches[0].get("power_w"), dtype=np.float64)
    if power.shape != (dimension,) or not np.all(np.isfinite(power)):
        raise G4InputError("targeted witness power has the wrong dimension or a non-finite value")
    return power


def _condition_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    action: Mapping[str, Any],
    measurement_value_w: float,
) -> list[dict[str, Any]]:
    conditioned: list[dict[str, Any]] = []
    found = False
    for original in candidates:
        candidate = copy.deepcopy(dict(original))
        if candidate.get("candidate_id") == action["candidate_id"]:
            candidate["observation"] = append_registered_measurement(
                candidate,
                action["coefficients_by_block"],
                measurement_value_w,
            )
            found = True
        conditioned.append(candidate)
    if not found:
        raise G4InputError("measurement target disappeared from the query")
    return conditioned


def _seal_result(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = _jsonable(payload)
    result["result_sha256"] = canonical_sha256(result)
    return result


def _unresolved_result(reason: str, detail: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "status": UNRESOLVED,
        "reason": reason,
        "detail": detail,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    payload.update(extra)
    return _seal_result(payload)


def evaluate_registered_acquisition(
    base_query_artifact: Mapping[str, Any],
    measurement_registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate the cheapest registered witness-confirming action."""

    base_receipt = replay_artifact(base_query_artifact)
    if base_receipt.get("status") != "PASS":
        raise G4InputError(
            f"base query artifact failed replay: {base_receipt.get('reason', 'unknown')}"
        )
    registry = validate_measurement_registry(
        measurement_registry, base_query_artifact=base_query_artifact
    )
    inputs = base_query_artifact["inputs"]
    candidates = inputs["candidates"]
    query_id = str(inputs["query_id"])
    thermal_limit = float(inputs["thermal_limit_k"])
    base_result = base_query_artifact["result"]
    common = {
        "base_query_artifact_sha256": base_query_artifact["artifact_sha256"],
        "base_query_digest": base_result.get("query_digest"),
        "base_query_status": base_result.get("status"),
        "registry_id": registry["registry_id"],
        "measurement_evidence_class": registry["evidence_class"],
        "measurement_value_tolerance_w": registry[
            "measurement_value_tolerance_w"
        ],
        "registry_sha256": canonical_sha256(registry),
        "registered_action_count": len(registry["actions"]),
        "registration": registry["registration"],
    }
    if base_result.get("status") != NON_IDENTIFIABLE:
        return _seal_result(
            {
                "schema_version": RESULT_SCHEMA_VERSION,
                "status": NOT_APPLICABLE,
                "reason": "BASE_QUERY_IS_NOT_NON_IDENTIFIABLE",
                "selected_action": None,
                "action_evaluations": [],
                "claim_boundary": _CLAIM_BOUNDARY,
                **common,
            }
        )

    witness_tuples = base_result.get("witness_tuples")
    if not isinstance(witness_tuples, list) or len(witness_tuples) < 2:
        return _unresolved_result(
            "UNRESOLVED_MISSING_WITNESS_PAIR",
            "NON_IDENTIFIABLE query lacks two witness tuples",
            **common,
        )
    pair = witness_tuples[:2]
    outcomes = [item.get("expected_outcome") for item in pair]
    if any(not isinstance(outcome, str) for outcome in outcomes) or outcomes[0] == outcomes[1]:
        return _unresolved_result(
            "UNRESOLVED_INVALID_WITNESS_PAIR",
            "the registered witness outcomes are absent or not decision-changing",
            **common,
        )
    candidate_by_id = _candidate_map(candidates)
    tolerance = registry["measurement_value_tolerance_w"]
    evaluations: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None

    for action in registry["actions"]:
        target = candidate_by_id[action["candidate_id"]]
        weight = _measurement_vector(target, action["coefficients_by_block"])
        values = [
            float(weight @ _tuple_power(item, action["candidate_id"], len(weight)))
            for item in pair
        ]
        evaluation: dict[str, Any] = {
            "measurement_id": action["measurement_id"],
            "candidate_id": action["candidate_id"],
            "cost": action["cost"],
            "measurement_values_w": values,
            "witness_value_separation_w": abs(values[0] - values[1]),
            "conditioned_queries": [],
        }
        if abs(values[0] - values[1]) <= tolerance:
            evaluation["status"] = "WITNESS_VALUES_INDISTINGUISHABLE"
            evaluations.append(evaluation)
            continue

        confirmed = True
        for pair_index, (witness_tuple, expected_outcome, value) in enumerate(
            zip(pair, outcomes, values)
        ):
            conditioned_candidates = _condition_candidates(
                candidates,
                action=action,
                measurement_value_w=value,
            )
            target_conditioned = next(
                item
                for item in conditioned_candidates
                if item.get("candidate_id") == action["candidate_id"]
            )
            problem = normalize_problem(
                target_conditioned.get("response_k_per_w", target_conditioned.get("R")),
                target_conditioned.get("ambient_k", target_conditioned.get("T_ambient")),
                target_conditioned["observation"],
                target_conditioned["block_names"],
            )
            target_power = _tuple_power(
                witness_tuple, action["candidate_id"], problem.dimension
            )
            membership = replay_power_witness(
                problem, target_power, feasibility_tolerance=1e-7
            )
            if not membership.get("valid"):
                return _unresolved_result(
                    "UNRESOLVED_MEASUREMENT_EXCLUDES_SOURCE_WITNESS",
                    f"action {action['measurement_id']} excludes its source witness",
                    action_evaluations=evaluations + [evaluation],
                    **common,
                )

            conditioned_result = decide_architecture_query(
                f"{query_id}::g4::{action['measurement_id']}::witness-{pair_index}",
                conditioned_candidates,
                thermal_limit_k=thermal_limit,
            )
            record = {
                "witness_tuple_digest": witness_tuple.get("tuple_digest"),
                "expected_outcome": expected_outcome,
                "measurement_value_w": value,
                "target_witness_membership": membership,
                "result": conditioned_result,
            }
            evaluation["conditioned_queries"].append(record)
            if conditioned_result.get("status") == UNRESOLVED:
                evaluation["status"] = "UNRESOLVED_CONDITIONED_QUERY"
                evaluations.append(evaluation)
                return _unresolved_result(
                    "UNRESOLVED_REGISTERED_ACTION",
                    (
                        f"action {action['measurement_id']} could be cheaper than a later "
                        "action but one conditioned query is unresolved"
                    ),
                    action_evaluations=evaluations,
                    **common,
                )
            if conditioned_result.get("status") == CERTIFIED:
                if conditioned_result.get("certified_outcome") != expected_outcome:
                    evaluation["status"] = "CERTIFICATE_CONTRADICTS_SOURCE_WITNESS"
                    evaluations.append(evaluation)
                    return _unresolved_result(
                        "UNRESOLVED_CERTIFICATE_CONTRADICTION",
                        f"action {action['measurement_id']} certifies the wrong witness outcome",
                        action_evaluations=evaluations,
                        **common,
                    )
            else:
                confirmed = False

        if confirmed:
            evaluation["status"] = WITNESS_PAIR_CONFIRMED
            evaluations.append(evaluation)
            selected = {
                **action,
                "measurement_values_w": values,
                "witness_outcomes": outcomes,
                "conditioned_queries": evaluation["conditioned_queries"],
            }
            break
        evaluation["status"] = "WITNESS_PAIR_NOT_CONFIRMED"
        evaluations.append(evaluation)

    status = WITNESS_PAIR_CONFIRMED if selected is not None else NO_REGISTERED_ACTION
    return _seal_result(
        {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": status,
            "witness_pair": {
                "tuple_digests": [item.get("tuple_digest") for item in pair],
                "outcomes": outcomes,
                "uncovered_reachable_outcomes": list(
                    base_result.get("reachable_outcomes", [])[2:]
                ),
            },
            "selected_action": selected,
            "action_evaluations": evaluations,
            "evaluated_action_count": len(evaluations),
            "unevaluated_action_count": len(registry["actions"]) - len(evaluations),
            "claim_boundary": _CLAIM_BOUNDARY,
            **common,
        }
    )


def _validate_run_metadata(run: Mapping[str, Any]) -> None:
    required = (
        "source_commit",
        "command",
        "environment",
        "exit_status",
        "wall_time_s",
        "peak_rss_kb",
        "input_files",
    )
    missing = [field for field in required if field not in run]
    if missing:
        raise G4InputError(f"run metadata is missing: {', '.join(missing)}")
    if not isinstance(run["source_commit"], str) or not re.fullmatch(
        r"[0-9a-f]{40,64}", run["source_commit"]
    ):
        raise G4InputError("source_commit must be a full lowercase Git digest")
    if not isinstance(run["command"], list) or not run["command"] or any(
        not isinstance(item, str) or not item for item in run["command"]
    ):
        raise G4InputError("command must be a non-empty argv list")
    if not isinstance(run["environment"], Mapping):
        raise G4InputError("environment must be a mapping")
    if not isinstance(run["exit_status"], int) or isinstance(run["exit_status"], bool):
        raise G4InputError("exit_status must be an integer")
    for field in ("wall_time_s", "peak_rss_kb"):
        value = float(run[field])
        if not np.isfinite(value) or value < 0.0:
            raise G4InputError(f"{field} must be finite and non-negative")
    if not isinstance(run["input_files"], list):
        raise G4InputError("input_files must be a list")
    for record in run["input_files"]:
        if not isinstance(record, Mapping):
            raise G4InputError("input file records must be mappings")
        if not isinstance(record.get("role"), str) or not record["role"]:
            raise G4InputError("input file role must be non-empty text")
        if not isinstance(record.get("path"), str) or not record["path"]:
            raise G4InputError("input file path label must be non-empty text")
        _digest(record.get("sha256"), "input file sha256")


def build_acquisition_artifact(
    *,
    base_query_artifact: Mapping[str, Any],
    measurement_registry: Mapping[str, Any],
    parent_g3: Mapping[str, Any],
    result: Mapping[str, Any],
    run: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic, self-authenticating G4 envelope."""

    _validate_run_metadata(run)
    parent = _jsonable(parent_g3)
    for field in ("suite_id", "query_id", "variant"):
        if not isinstance(parent.get(field), str) or not parent[field]:
            raise G4InputError(f"parent_g3.{field} must be non-empty text")
    _digest(parent.get("artifact_sha256"), "parent_g3.artifact_sha256")
    content = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "parent_g3": parent,
        "base_query_artifact": _jsonable(base_query_artifact),
        "measurement_registry": _jsonable(measurement_registry),
        "result": _jsonable(result),
        "run": _jsonable(run),
    }
    digests = {
        "parent_g3_sha256": canonical_sha256(content["parent_g3"]),
        "base_query_artifact_sha256": canonical_sha256(content["base_query_artifact"]),
        "measurement_registry_sha256": canonical_sha256(content["measurement_registry"]),
        "result_sha256": canonical_sha256(content["result"]),
        "run_sha256": canonical_sha256(content["run"]),
    }
    artifact = {**content, "digests": digests}
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    return artifact


def _query_semantics_match(
    stored: Mapping[str, Any], replayed: Mapping[str, Any], tolerance_k: float
) -> bool:
    for field in ("status", "query_digest", "certified_outcome", "reachable_outcomes"):
        if stored.get(field) != replayed.get(field):
            return False
    old_bounds = stored.get("candidate_bounds", [])
    new_bounds = replayed.get("candidate_bounds", [])
    if len(old_bounds) != len(new_bounds):
        return False
    for old, new in zip(old_bounds, new_bounds):
        if old.get("candidate_id") != new.get("candidate_id"):
            return False
        old_result = old.get("result", {})
        new_result = new.get("result", {})
        if old_result.get("status") != new_result.get("status"):
            return False
        if old_result.get("status") != UNRESOLVED:
            for field in ("lower_d", "upper_d"):
                if abs(float(old_result[field]) - float(new_result[field])) > tolerance_k:
                    return False
    return True


def _acquisition_semantics_match(
    stored: Mapping[str, Any], replayed: Mapping[str, Any], tolerance: float
) -> bool:
    for field in (
        "status",
        "reason",
        "base_query_artifact_sha256",
        "base_query_digest",
        "registry_id",
        "measurement_evidence_class",
        "measurement_value_tolerance_w",
        "registry_sha256",
        "registered_action_count",
        "evaluated_action_count",
        "unevaluated_action_count",
    ):
        if stored.get(field) != replayed.get(field):
            return False
    if stored.get("witness_pair") != replayed.get("witness_pair"):
        return False
    old_selected = stored.get("selected_action")
    new_selected = replayed.get("selected_action")
    if (old_selected is None) != (new_selected is None):
        return False
    if old_selected is not None:
        for field in ("measurement_id", "candidate_id", "cost", "witness_outcomes"):
            if old_selected.get(field) != new_selected.get(field):
                return False
    old_evaluations = stored.get("action_evaluations", [])
    new_evaluations = replayed.get("action_evaluations", [])
    if len(old_evaluations) != len(new_evaluations):
        return False
    for old, new in zip(old_evaluations, new_evaluations):
        for field in ("measurement_id", "candidate_id", "cost", "status"):
            if old.get(field) != new.get(field):
                return False
        old_values = old.get("measurement_values_w", [])
        new_values = new.get("measurement_values_w", [])
        if len(old_values) != len(new_values) or any(
            abs(float(a) - float(b)) > tolerance for a, b in zip(old_values, new_values)
        ):
            return False
        old_queries = old.get("conditioned_queries", [])
        new_queries = new.get("conditioned_queries", [])
        if len(old_queries) != len(new_queries):
            return False
        for old_query, new_query in zip(old_queries, new_queries):
            if old_query.get("expected_outcome") != new_query.get("expected_outcome"):
                return False
            if abs(
                float(old_query.get("measurement_value_w"))
                - float(new_query.get("measurement_value_w"))
            ) > tolerance:
                return False
            if not _query_semantics_match(
                old_query.get("result", {}), new_query.get("result", {}), tolerance
            ):
                return False
    return True


def replay_acquisition_artifact(
    artifact: Mapping[str, Any], *, numeric_tolerance: float = 1e-6
) -> dict[str, Any]:
    """Verify the envelope, replay its parent query, and rerun acquisition."""

    def invalid(reason: str) -> dict[str, Any]:
        return {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "status": "INVALID",
            "reason": reason,
        }

    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        return invalid("unsupported G4 artifact schema")
    required = (
        "parent_g3",
        "base_query_artifact",
        "measurement_registry",
        "result",
        "run",
        "digests",
        "artifact_sha256",
    )
    if any(field not in artifact for field in required):
        return invalid("G4 artifact envelope is incomplete")
    try:
        _validate_run_metadata(artifact["run"])
        parent = artifact["parent_g3"]
        if not isinstance(parent, Mapping):
            raise G4InputError("parent_g3 must be a mapping")
        for field in ("suite_id", "query_id"):
            if not isinstance(parent.get(field), str) or not parent[field]:
                raise G4InputError(f"parent_g3.{field} must be non-empty text")
        if parent.get("variant") != "spatial_equivalence":
            raise G4InputError("parent_g3 must bind the spatial_equivalence variant")
        _digest(parent.get("artifact_sha256"), "parent_g3.artifact_sha256")
    except (G4InputError, TypeError, ValueError) as exc:
        return invalid(str(exc))
    try:
        expected_digests = {
            "parent_g3_sha256": canonical_sha256(artifact["parent_g3"]),
            "base_query_artifact_sha256": canonical_sha256(
                artifact["base_query_artifact"]
            ),
            "measurement_registry_sha256": canonical_sha256(
                artifact["measurement_registry"]
            ),
            "result_sha256": canonical_sha256(artifact["result"]),
            "run_sha256": canonical_sha256(artifact["run"]),
        }
    except (TypeError, ValueError) as exc:
        return invalid(f"cannot hash G4 content: {exc}")
    if artifact["digests"] != expected_digests:
        return invalid("G4 content digest mismatch")
    envelope = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    if artifact["artifact_sha256"] != canonical_sha256(envelope):
        return invalid("G4 artifact envelope digest mismatch")
    stored_result = artifact["result"]
    if not isinstance(stored_result, Mapping):
        return invalid("G4 result must be a mapping")
    supplied_result_digest = stored_result.get("result_sha256")
    result_payload = {
        key: value for key, value in stored_result.items() if key != "result_sha256"
    }
    if supplied_result_digest != canonical_sha256(result_payload):
        return invalid("G4 result digest mismatch")
    base_receipt = replay_artifact(artifact["base_query_artifact"])
    if base_receipt.get("status") != "PASS":
        return invalid("embedded base query artifact failed replay")
    try:
        fresh = evaluate_registered_acquisition(
            artifact["base_query_artifact"], artifact["measurement_registry"]
        )
    except (G4InputError, TypeError, ValueError) as exc:
        return invalid(f"fresh G4 evaluation failed: {exc}")
    try:
        matches = _acquisition_semantics_match(
            stored_result, fresh, numeric_tolerance
        )
    except (KeyError, TypeError, ValueError) as exc:
        return invalid(f"cannot compare fresh G4 semantics: {exc}")
    if not matches:
        return invalid("fresh G4 semantics differ from stored result")
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "status": "PASS",
        "artifact_sha256": artifact["artifact_sha256"],
        "base_query_artifact_sha256": artifact["base_query_artifact"].get(
            "artifact_sha256"
        ),
        "acquisition_status": stored_result.get("status"),
        "selected_measurement_id": (
            stored_result.get("selected_action") or {}
        ).get("measurement_id"),
    }


def _select_g3_query(
    g3_artifact: Mapping[str, Any], query_id: str
) -> tuple[Mapping[str, Any], dict[str, str]]:
    receipt = replay_g3_suite_artifact(g3_artifact)
    if receipt.get("status") != "PASS":
        raise G4InputError(
            f"G3 suite artifact failed replay: {receipt.get('reason', 'unknown')}"
        )
    if g3_artifact.get("evidence_class") != "physical_placed_power":
        raise G4InputError("G4 requires a physical_placed_power G3 suite")
    entries = g3_artifact.get("entries")
    matches = [
        entry
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("query_id") == query_id
    ]
    if len(matches) != 1:
        raise G4InputError("query_id must select exactly one G3 suite entry")
    variants = matches[0].get("variants")
    if not isinstance(variants, Mapping) or not isinstance(
        variants.get("spatial_equivalence"), Mapping
    ):
        raise G4InputError("selected G3 entry lacks a spatial-equivalence artifact")
    suite_id = g3_artifact.get("suite_id")
    if not isinstance(suite_id, str) or not suite_id:
        raise G4InputError("G3 suite_id must be non-empty text")
    return variants["spatial_equivalence"], {
        "suite_id": suite_id,
        "query_id": query_id,
        "variant": "spatial_equivalence",
        "artifact_sha256": str(g3_artifact.get("artifact_sha256")),
    }


def _git_state(repo_root: Path) -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return commit, dirty


def _require_external_output(path: Path, repo_root: Path, field: str) -> None:
    try:
        path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return
    raise G4InputError(f"{field} must be outside the Git worktree")


def run_registered_acquisition(
    g3_artifact_path: Path,
    query_id: str,
    registry_path: Path,
    artifact_path: Path,
    receipt_path: Path,
    *,
    repo_root: Path,
    argv: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run G4 from a clean tree and write raw outputs only outside Git."""

    _require_external_output(artifact_path, repo_root, "artifact")
    _require_external_output(receipt_path, repo_root, "receipt")
    source_commit, dirty = _git_state(repo_root)
    if dirty:
        raise G4InputError("claim-grade G4 runner requires a clean Git worktree")
    g3_artifact = _read_json(g3_artifact_path)
    registry, registry_input_files = load_measurement_registry_bundle(registry_path)
    if registry.get("evidence_class") != PHYSICAL_MEASUREMENT_FAMILY:
        raise G4InputError(
            "claim-grade G4 execution requires physical_measurement_family evidence"
        )
    base_query, parent_g3 = _select_g3_query(g3_artifact, query_id)

    started = time.perf_counter()
    result = evaluate_registered_acquisition(base_query, registry)
    wall_time = time.perf_counter() - started
    run = {
        "source_commit": source_commit,
        "command": list(argv),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "hostname": platform.node(),
        },
        "exit_status": 0,
        "wall_time_s": wall_time,
        "peak_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "input_files": [
            {
                "role": "g3_suite_artifact",
                "path": f"external/{g3_artifact_path.name}",
                "sha256": sha256_file(g3_artifact_path),
            },
            *[
                {
                    **record,
                    "path": f"external/{registry_path.parent.name}/{record['path']}",
                }
                for record in registry_input_files
            ],
        ],
    }
    artifact = build_acquisition_artifact(
        base_query_artifact=base_query,
        measurement_registry=registry,
        parent_g3=parent_g3,
        result=result,
        run=run,
    )
    receipt = replay_acquisition_artifact(artifact)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return artifact, receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run registered cross-query CertiTherm G4 acquisition"
    )
    parser.add_argument("--g3-artifact", required=True, type=Path)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args()
    try:
        artifact, receipt = run_registered_acquisition(
            args.g3_artifact,
            args.query_id,
            args.registry,
            args.artifact,
            args.receipt,
            repo_root=args.repo_root.resolve(),
            argv=[sys.executable, *sys.argv],
        )
    except Exception as exc:
        print(json.dumps({"status": UNRESOLVED, "reason": str(exc)}, indent=2))
        return 2
    summary = {
        "artifact_sha256": artifact["artifact_sha256"],
        "acquisition_status": artifact["result"].get("status"),
        "selected_measurement_id": (
            artifact["result"].get("selected_action") or {}
        ).get("measurement_id"),
        "replay_status": receipt.get("status"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
