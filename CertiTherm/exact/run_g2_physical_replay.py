"""Replay the registered placed-power G2 query against independent evidence.

Raw placed-power, native HotSpot, independent-oracle, and frontier files stay
outside Git.  Their registered SHA-256 values and semantic digests are checked
before this module constructs the rectangular CertiTherm query.  The output is
a full off-repository replay artifact plus a compact, path-private manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np
import scipy

try:
    from .decision_query import (
        NON_IDENTIFIABLE,
        TUPLE_SCHEMA_VERSION,
        decide_architecture_query,
        replay_architecture_tuple,
    )
    from .evidence import (
        build_replay_artifact,
        replay_artifact,
        sha256_file,
        write_replay_artifact,
    )
    from .linear_oracle import canonical_sha256
except ImportError:  # pragma: no cover - direct script execution.
    from decision_query import (
        NON_IDENTIFIABLE,
        TUPLE_SCHEMA_VERSION,
        decide_architecture_query,
        replay_architecture_tuple,
    )
    from evidence import (
        build_replay_artifact,
        replay_artifact,
        sha256_file,
        write_replay_artifact,
    )
    from linear_oracle import canonical_sha256


REGISTRY_SCHEMA_VERSION = "certitherm.g2-physical-input-registry.v1"
MANIFEST_SCHEMA_VERSION = "certitherm.g2-physical-replay-manifest.v1"
RECEIPT_SCHEMA_VERSION = "certitherm.g2-physical-cross-replay.v1"


class PhysicalReplayError(RuntimeError):
    """A registered physical-evidence or parity check failed."""


def _text_scalar(archive: Mapping[str, np.ndarray], name: str) -> str:
    try:
        value = archive[name]
        if value.shape != ():
            raise ValueError
        result = str(value.item())
    except (KeyError, TypeError, ValueError) as exc:
        raise PhysicalReplayError(f"{name} must be a scalar text field") from exc
    if not result:
        raise PhysicalReplayError(f"{name} must not be empty")
    return result


def _float_scalar(archive: Mapping[str, np.ndarray], name: str) -> float:
    try:
        value = archive[name]
        if value.shape != ():
            raise ValueError
        result = float(value.item())
    except (KeyError, TypeError, ValueError) as exc:
        raise PhysicalReplayError(f"{name} must be a numeric scalar") from exc
    if not np.isfinite(result):
        raise PhysicalReplayError(f"{name} must be finite")
    return result


def _archive(path: Path) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as value:
            return {name: np.array(value[name], copy=True) for name in value.files}
    except (OSError, TypeError, ValueError) as exc:
        raise PhysicalReplayError(f"invalid NPZ input {path.name}: {exc}") from exc


def _float_array(
    archive: Mapping[str, np.ndarray],
    name: str,
    *,
    ndim: int = 1,
    nonnegative: bool = False,
) -> np.ndarray:
    try:
        value = np.asarray(archive[name], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as exc:
        raise PhysicalReplayError(f"{name} must be a float array") from exc
    if value.ndim != ndim or value.size == 0 or not np.all(np.isfinite(value)):
        raise PhysicalReplayError(f"{name} must be a non-empty finite {ndim}-D array")
    if nonnegative and np.any(value < 0.0):
        raise PhysicalReplayError(f"{name} must be non-negative")
    return value


def _text_array(archive: Mapping[str, np.ndarray], name: str) -> tuple[str, ...]:
    try:
        raw = np.asarray(archive[name])
    except KeyError as exc:
        raise PhysicalReplayError(f"missing text array {name}") from exc
    if raw.ndim != 1 or len(raw) == 0:
        raise PhysicalReplayError(f"{name} must be a non-empty one-dimensional array")
    values = tuple(str(item) for item in raw.tolist())
    if any(not item for item in values) or len(values) != len(set(values)):
        raise PhysicalReplayError(f"{name} identities must be non-empty and unique")
    return values


def _array_sha256(value: np.ndarray | Sequence[float]) -> str:
    array = np.asarray(value, dtype="<f8", order="C")
    digest = hashlib.sha256()
    digest.update(b"certitherm.float64-array.v1\0")
    digest.update(json.dumps(array.shape, separators=(",", ":")).encode("ascii"))
    digest.update(b"\0")
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


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


def _read_registry(path: Path) -> Mapping[str, Any]:
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PhysicalReplayError(f"invalid registry: {exc}") from exc
    if not isinstance(registry, Mapping):
        raise PhysicalReplayError("registry must contain a JSON object")
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise PhysicalReplayError("unsupported physical-input registry schema")
    return registry


def _verify_registered_files(
    registry: Mapping[str, Any], paths: Mapping[str, Path]
) -> list[dict[str, str]]:
    records = registry.get("files")
    if not isinstance(records, Mapping) or not records:
        raise PhysicalReplayError("registry files must be a non-empty mapping")
    if set(paths) != set(records):
        missing = sorted(set(records) - set(paths))
        extra = sorted(set(paths) - set(records))
        raise PhysicalReplayError(f"input file-key mismatch: missing={missing}, extra={extra}")
    verified = []
    for key in sorted(records):
        record = records[key]
        path = paths[key]
        if not isinstance(record, Mapping) or not path.is_file():
            raise PhysicalReplayError(f"registered input {key} is missing")
        actual = sha256_file(path)
        if actual != record.get("sha256"):
            raise PhysicalReplayError(f"SHA-256 mismatch for registered input {key}")
        filename = record.get("filename")
        if not isinstance(filename, str) or not filename:
            raise PhysicalReplayError(f"registered input {key} has no logical filename")
        verified.append(
            {
                "role": key,
                "path": f"external_inputs/{filename}",
                "sha256": actual,
            }
        )
    return verified


def _replay_domain(
    domain: Mapping[str, Any], power_w: np.ndarray, tolerance_w: float
) -> dict[str, Any]:
    power = np.asarray(power_w, dtype=np.float64)
    if power.shape != domain["lower_w"].shape or not np.all(np.isfinite(power)):
        return {"valid": False, "reason": "power witness shape or finiteness mismatch"}
    lower_violation = float(np.max(np.maximum(domain["lower_w"] - power, 0.0)))
    upper_violation = float(np.max(np.maximum(power - domain["upper_w"], 0.0)))
    sums = np.bincount(
        domain["group_index"], weights=power, minlength=len(domain["group_ids"])
    )
    group_error = float(np.max(np.abs(sums - domain["observed_group_power_w"])))
    valid = max(lower_violation, upper_violation, group_error) <= tolerance_w
    return {
        "valid": bool(valid),
        "lower_bound_violation_w": lower_violation,
        "upper_bound_violation_w": upper_violation,
        "maximum_group_error_w": group_error,
    }


def _load_candidate(
    record: Mapping[str, Any],
    registry: Mapping[str, Any],
    paths: Mapping[str, Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate_id = record.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise PhysicalReplayError("candidate identity is invalid")
    domain = _archive(paths[str(record["domain_file"])])
    green = _archive(paths[str(record["green_file"])])
    oracle = _archive(paths[str(record["oracle_file"])])
    if any(
        _text_scalar(value, "design_id") != candidate_id
        for value in (domain, green, oracle)
    ):
        raise PhysicalReplayError(f"candidate identity mismatch for {candidate_id}")

    group_ids = _text_array(domain, "group_ids")
    cell_ids = _text_array(domain, "cell_ids")
    variable_ids = _text_array(domain, "variable_ids")
    try:
        group_index = np.asarray(domain["group_index"], dtype=np.int64)
        cell_index = np.asarray(domain["cell_index"], dtype=np.int64)
    except (KeyError, TypeError, ValueError) as exc:
        raise PhysicalReplayError(f"invalid domain indices for {candidate_id}") from exc
    n = len(variable_ids)
    if group_index.shape != (n,) or cell_index.shape != (n,):
        raise PhysicalReplayError(f"domain-index shape mismatch for {candidate_id}")
    if (
        np.any(group_index < 0)
        or np.any(group_index >= len(group_ids))
        or np.any(cell_index < 0)
        or np.any(cell_index >= len(cell_ids))
        or set(group_index.tolist()) != set(range(len(group_ids)))
    ):
        raise PhysicalReplayError(f"domain indices are out of range for {candidate_id}")

    lower = _float_array(domain, "lower_w", nonnegative=True)
    upper = _float_array(domain, "upper_w", nonnegative=True)
    observed = _float_array(domain, "observed_group_power_w", nonnegative=True)
    if lower.shape != (n,) or upper.shape != (n,) or observed.shape != (len(group_ids),):
        raise PhysicalReplayError(f"domain-array shape mismatch for {candidate_id}")
    if np.any(upper < lower):
        raise PhysicalReplayError(f"inverted power bounds for {candidate_id}")

    green_cells = _text_array(green, "cell_ids")
    temperature_points = _text_array(green, "temperature_point_ids")
    if green_cells != cell_ids:
        raise PhysicalReplayError(f"thermal/domain cell identities differ for {candidate_id}")
    baseline = _float_array(green, "baseline_fine_k")
    cell_response = _float_array(
        green, "response_fine_k_per_w", ndim=2, nonnegative=True
    )
    if baseline.shape != (len(temperature_points),) or cell_response.shape != (
        len(temperature_points),
        len(cell_ids),
    ):
        raise PhysicalReplayError(f"thermal-operator shape mismatch for {candidate_id}")
    response = cell_response[:, cell_index]

    domain_digest = _text_scalar(domain, "domain_digest")
    operator_digest = _text_scalar(green, "operator_digest")
    if domain_digest != record.get("domain_digest"):
        raise PhysicalReplayError(f"domain semantic digest mismatch for {candidate_id}")
    if operator_digest != record.get("operator_digest"):
        raise PhysicalReplayError(f"operator semantic digest mismatch for {candidate_id}")
    for field, expected in (
        ("domain_digest", domain_digest),
        ("operator_digest", operator_digest),
        ("bounds_digest", record.get("bounds_digest")),
        ("query_payload_digest", record.get("query_payload_digest")),
    ):
        if _text_scalar(oracle, field) != expected:
            raise PhysicalReplayError(f"oracle {field} mismatch for {candidate_id}")

    numerical_error = _float_scalar(oracle, "numerical_temperature_error_k")
    expected_error = _float_scalar(green, "numerical_error_k_per_w") * float(
        np.sum(observed)
    )
    if abs(numerical_error - expected_error) > 1e-12:
        raise PhysicalReplayError(f"temperature-error scaling mismatch for {candidate_id}")

    numeric = registry["numeric_contract"]
    power_tolerance = float(numeric["power_replay_tolerance_w"])
    temperature_tolerance = float(numeric["temperature_replay_tolerance_k"])
    reference: dict[str, Any] = {
        "candidate_id": candidate_id,
        "lower_peak_temperature_k": _float_scalar(
            oracle, "lower_peak_temperature_k"
        ),
        "upper_peak_temperature_k": _float_scalar(
            oracle, "upper_peak_temperature_k"
        ),
        "numerical_temperature_error_k": numerical_error,
        "maximum_backend_disagreement_k": _float_scalar(
            oracle, "maximum_backend_disagreement_k"
        ),
        "lower_power_w": _float_array(oracle, "lower_power_w", nonnegative=True),
        "upper_power_w": _float_array(oracle, "upper_power_w", nonnegative=True),
        "reference_power_w": _float_array(
            oracle, "reference_power_w", nonnegative=True
        ),
        "lower_temperature_k": _float_array(oracle, "lower_temperature_k"),
        "upper_temperature_k": _float_array(oracle, "upper_temperature_k"),
        "reference_temperature_k": _float_array(oracle, "reference_temperature_k"),
        "bounds_digest": record.get("bounds_digest"),
        "query_payload_digest": record.get("query_payload_digest"),
    }
    domain_view = {
        "group_ids": group_ids,
        "group_index": group_index,
        "lower_w": lower,
        "upper_w": upper,
        "observed_group_power_w": observed,
    }
    for label in ("lower", "upper", "reference"):
        power = reference[f"{label}_power_w"]
        replay = _replay_domain(domain_view, power, power_tolerance)
        if not replay["valid"]:
            raise PhysicalReplayError(
                f"external {label} power witness fails domain replay for {candidate_id}"
            )
        temperatures = baseline + response @ power
        stored_temperatures = reference[f"{label}_temperature_k"]
        if stored_temperatures.shape != temperatures.shape or float(
            np.max(np.abs(stored_temperatures - temperatures))
        ) > temperature_tolerance:
            raise PhysicalReplayError(
                f"external {label} temperature replay differs for {candidate_id}"
            )
        if label in ("lower", "upper") and abs(
            float(np.max(temperatures))
            - float(reference[f"{label}_peak_temperature_k"])
        ) > temperature_tolerance:
            raise PhysicalReplayError(
                f"external {label} peak differs for {candidate_id}"
            )

    a_eq = np.zeros((len(group_ids), n), dtype=np.float64)
    a_eq[group_index, np.arange(n)] = 1.0
    file_records = registry["files"]
    domain_file = str(record["domain_file"])
    green_file = str(record["green_file"])
    oracle_file = str(record["oracle_file"])
    candidate = {
        "candidate_id": candidate_id,
        "nonthermal_objective": float(record["nonthermal_objective"]),
        "tie_break_rank": int(record["tie_break_rank"]),
        "response_k_per_w": response,
        "ambient_k": baseline,
        "observation": {
            "A_eq": a_eq,
            "b_eq": observed,
            "per_block_lower": lower,
            "per_block_upper": upper,
        },
        "block_names": list(variable_ids),
        "area_mm2": None,
        "numerical_temperature_error_k": numerical_error,
        "decision_tolerance_k": float(numeric["decision_tolerance_k"]),
        "provenance": {
            "workload_id": "snax_gemm",
            "workload_family": "DNN-shape-derived GEMM utilization motif",
            "architecture_id": candidate_id,
            "package_id": "route-clean post-PnR G0 package",
            "power_source": "registered group-cell placed-power domain",
            "power_source_sha256": file_records[domain_file]["sha256"],
            "placement_sha256": _text_scalar(domain, "nominal_projection_digest"),
            "thermal_backend": "native HotSpot Green operator, fine mesh 128",
            "thermal_config_sha256": file_records[green_file]["sha256"],
            "independent_oracle_sha256": file_records[oracle_file]["sha256"],
            "external_source_commit": registry["external_evidence"]["audit_commit"],
        },
    }
    reference.update(
        {
            "domain": domain_view,
            "baseline_k": baseline,
            "response_k_per_w": response,
            "temperature_point_ids": temperature_points,
            "variable_count": n,
            "group_count": len(group_ids),
            "thermal_point_count": len(temperature_points),
        }
    )
    return candidate, reference


def _frontier_summary(path: Path) -> Mapping[str, str]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    except OSError as exc:
        raise PhysicalReplayError(f"cannot read frontier summary: {exc}") from exc
    if len(rows) != 1:
        raise PhysicalReplayError("frontier summary must contain exactly one data row")
    return rows[0]


def _make_external_tuple(
    outcome: str,
    ordered_candidates: Sequence[Mapping[str, Any]],
    result_by_id: Mapping[str, Mapping[str, Any]],
    power_by_id: Mapping[str, np.ndarray],
) -> dict[str, Any]:
    payload = {
        "schema_version": TUPLE_SCHEMA_VERSION,
        "expected_outcome": outcome,
        "candidates": [
            {
                "candidate_id": str(candidate["candidate_id"]),
                "candidate_input_digest": result_by_id[str(candidate["candidate_id"])][
                    "input_digest"
                ],
                "power_w": power_by_id[str(candidate["candidate_id"])].tolist(),
            }
            for candidate in ordered_candidates
        ],
    }
    payload["tuple_digest"] = canonical_sha256(payload)
    return payload


def _cross_check_frontier(
    registry: Mapping[str, Any],
    paths: Mapping[str, Path],
    candidates: Sequence[Mapping[str, Any]],
    references: Mapping[str, Mapping[str, Any]],
    query_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    frontier_record = registry["frontier"]
    frontier = _archive(paths[str(frontier_record["file"])])
    for field in ("region_digest", "witness_digest"):
        if _text_scalar(frontier, field) != frontier_record[field]:
            raise PhysicalReplayError(f"frontier {field} mismatch")
    for field in ("lower_limit_k", "upper_limit_k", "representative_limit_k"):
        if _float_scalar(frontier, field) != float(frontier_record[field]):
            raise PhysicalReplayError(f"frontier {field} mismatch")
    for field in ("lower_closed", "upper_closed"):
        try:
            value = bool(frontier[field].item())
        except (KeyError, ValueError) as exc:
            raise PhysicalReplayError(f"frontier {field} is invalid") from exc
        if value is not bool(frontier_record[field]):
            raise PhysicalReplayError(f"frontier {field} mismatch")

    summary = _frontier_summary(paths[str(frontier_record["summary_file"])])
    if (
        summary.get("witness_digest") != frontier_record["witness_digest"]
        or summary.get("frontier_digest") != frontier_record["frontier_digest"]
        or summary.get("witness_npz_sha256")
        != registry["files"][str(frontier_record["file"])]["sha256"]
        or summary.get("frontier_tsv_sha256")
        != registry["files"][str(frontier_record["table_file"])]["sha256"]
    ):
        raise PhysicalReplayError("frontier summary does not bind the registered files")

    result_by_id = {
        item["candidate_id"]: item["result"] for item in query_result["candidate_bounds"]
    }
    aliases = {
        "snax_gemm_m4_t8": "m4",
        "snax_gemm_m2_t8": "m2",
    }
    limit = float(frontier_record["representative_limit_k"])
    receipts = []
    expected_outcomes = tuple(registry["query"]["expected_outcomes"])
    for outcome_index, expected_outcome in enumerate(expected_outcomes):
        if _text_scalar(frontier, f"outcome_{outcome_index}") != expected_outcome:
            raise PhysicalReplayError("frontier outcome order mismatch")
        powers: dict[str, np.ndarray] = {}
        recorded_temperature_delta = 0.0
        for candidate in candidates:
            candidate_id = str(candidate["candidate_id"])
            alias = aliases.get(candidate_id)
            if alias is None:
                raise PhysicalReplayError(f"unregistered frontier alias for {candidate_id}")
            power = _float_array(
                frontier, f"outcome_{outcome_index}_{alias}_power_w", nonnegative=True
            )
            stored_temperature = _float_array(
                frontier, f"outcome_{outcome_index}_{alias}_temperature_k"
            )
            reference = references[candidate_id]
            replay = _replay_domain(
                reference["domain"],
                power,
                float(registry["numeric_contract"]["power_replay_tolerance_w"]),
            )
            if not replay["valid"]:
                raise PhysicalReplayError(
                    f"frontier power witness fails domain replay for {candidate_id}"
                )
            temperatures = reference["baseline_k"] + reference["response_k_per_w"] @ power
            if stored_temperature.shape != temperatures.shape:
                raise PhysicalReplayError("frontier temperature shape mismatch")
            recorded_temperature_delta = max(
                recorded_temperature_delta,
                float(np.max(np.abs(stored_temperature - temperatures))),
            )
            powers[candidate_id] = power
        if recorded_temperature_delta > float(
            registry["numeric_contract"]["temperature_replay_tolerance_k"]
        ):
            raise PhysicalReplayError("frontier stored temperatures fail direct replay")
        witness_tuple = _make_external_tuple(
            expected_outcome, candidates, result_by_id, powers
        )
        replay = replay_architecture_tuple(
            candidates, witness_tuple, thermal_limit_k=limit
        )
        if not replay.get("valid"):
            raise PhysicalReplayError(
                f"frontier decision tuple fails current replay: {replay.get('reason')}"
            )
        receipts.append(
            {
                "expected_outcome": expected_outcome,
                "selected_outcome": replay["selected_outcome"],
                "tuple_digest": witness_tuple["tuple_digest"],
                "candidate_power_sha256": {
                    candidate_id: _array_sha256(power)
                    for candidate_id, power in sorted(powers.items())
                },
                "maximum_recorded_temperature_delta_k": recorded_temperature_delta,
                "candidate_replays": replay["candidate_replays"],
            }
        )
    return receipts


def run_physical_replay(
    *,
    registry_path: Path,
    paths: Mapping[str, Path],
    output_dir: Path,
    repo_root: Path,
    argv: list[str],
) -> dict[str, Any]:
    """Execute, independently replay, and cross-check one registered G2 query."""

    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    try:
        output_dir.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise PhysicalReplayError("raw physical replay output must stay outside Git")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise PhysicalReplayError("physical replay output directory must be new or empty")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_commit, dirty = _git_state(repo_root)
    if dirty:
        raise PhysicalReplayError("claim-grade physical replay requires a clean Git worktree")
    registry = _read_registry(registry_path)
    input_files = _verify_registered_files(registry, paths)
    input_files.insert(
        0,
        {
            "role": "physical_input_registry",
            "path": "registry/g2_placed_power_registry.json",
            "sha256": sha256_file(registry_path),
        },
    )

    candidates = []
    references: dict[str, dict[str, Any]] = {}
    for candidate_record in registry["candidates"]:
        candidate, reference = _load_candidate(candidate_record, registry, paths)
        candidates.append(candidate)
        references[str(candidate["candidate_id"])] = reference

    limit = float(registry["frontier"]["representative_limit_k"])
    query_id = str(registry["query"]["query_id"])
    started = time.perf_counter()
    result = decide_architecture_query(query_id, candidates, thermal_limit_k=limit)
    solve_wall_time = time.perf_counter() - started
    if result.get("status") != registry["query"]["expected_status"]:
        raise PhysicalReplayError(
            f"current query status {result.get('status')} differs from registry"
        )
    if tuple(result.get("reachable_outcomes", ())) != tuple(
        registry["query"]["expected_outcomes"]
    ):
        raise PhysicalReplayError("current reachable outcomes differ from registry")

    parity_tolerance = float(
        registry["numeric_contract"]["bound_parity_tolerance_k"]
    )
    candidate_summaries = []
    for item in result["candidate_bounds"]:
        candidate_id = str(item["candidate_id"])
        current = item["result"]
        reference = references[candidate_id]
        record = next(
            value
            for value in registry["candidates"]
            if value["candidate_id"] == candidate_id
        )
        if current.get("status") != record["expected_state"]:
            raise PhysicalReplayError(f"candidate state mismatch for {candidate_id}")
        lower_delta = abs(
            float(current["lower_d"]) - float(reference["lower_peak_temperature_k"])
        )
        upper_delta = abs(
            float(current["upper_d"]) - float(reference["upper_peak_temperature_k"])
        )
        if max(lower_delta, upper_delta) > parity_tolerance:
            raise PhysicalReplayError(f"independent bound parity failed for {candidate_id}")
        if reference["maximum_backend_disagreement_k"] > parity_tolerance:
            raise PhysicalReplayError(
                f"external backend disagreement exceeds tolerance for {candidate_id}"
            )
        candidate_summaries.append(
            {
                "candidate_id": candidate_id,
                "variables": reference["variable_count"],
                "groups": reference["group_count"],
                "thermal_points": reference["thermal_point_count"],
                "state": current["status"],
                "lower_peak_temperature_k": current["lower_d"],
                "upper_peak_temperature_k": current["upper_d"],
                "numerical_temperature_error_k": current[
                    "numerical_temperature_error_k"
                ],
                "decision_margin_k": current["decision_margin_k"],
                "external_lower_delta_k": lower_delta,
                "external_upper_delta_k": upper_delta,
                "external_maximum_backend_disagreement_k": reference[
                    "maximum_backend_disagreement_k"
                ],
                "domain_digest": record["domain_digest"],
                "operator_digest": record["operator_digest"],
                "bounds_digest": record["bounds_digest"],
                "query_payload_digest": record["query_payload_digest"],
                "current_input_digest": current["input_digest"],
                "current_lower_witness_sha256": _array_sha256(
                    current["witness_lower"]
                ),
                "current_upper_witness_sha256": _array_sha256(
                    current["witness_upper"]
                ),
            }
        )

    external_witness_replays = _cross_check_frontier(
        registry, paths, candidates, references, result
    )
    run = {
        "source_commit": source_commit,
        "command": argv,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "hostname": platform.node(),
        },
        "exit_status": 0,
        "wall_time_s": solve_wall_time,
        "peak_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "input_files": input_files,
    }
    artifact = build_replay_artifact(
        query_id=query_id,
        candidates=candidates,
        thermal_limit_k=limit,
        result=result,
        run=run,
    )
    artifact_path = output_dir / "g2_physical_replay_artifact.json"
    write_replay_artifact(artifact_path, artifact)
    artifact_receipt = replay_artifact(artifact)
    if artifact_receipt.get("status") != "PASS":
        raise PhysicalReplayError(
            f"fresh artifact replay failed: {artifact_receipt.get('reason')}"
        )

    cross_receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "PASS",
        "artifact_replay": artifact_receipt,
        "external_witness_replays": external_witness_replays,
    }
    receipt_path = output_dir / "g2_physical_replay_receipt.json"
    receipt_path.write_text(
        json.dumps(cross_receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    scientific_payload = {
        "registry_sha256": sha256_file(registry_path),
        "external_evidence": registry["external_evidence"],
        "query_id": query_id,
        "thermal_limit_k": limit,
        "query_status": result["status"],
        "reachable_outcomes": result["reachable_outcomes"],
        "query_digest": result["query_digest"],
        "candidate_summaries": candidate_summaries,
        "external_witness_replays": external_witness_replays,
    }
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "PASS",
        "source_commit": source_commit,
        "input_files": input_files,
        "scientific_payload": scientific_payload,
        "scientific_digest": canonical_sha256(scientific_payload),
        "raw_artifact": {
            "filename": artifact_path.name,
            "sha256": sha256_file(artifact_path),
            "artifact_sha256": artifact["artifact_sha256"],
        },
        "replay_receipt": {
            "filename": receipt_path.name,
            "sha256": sha256_file(receipt_path),
        },
        "run": {
            "wall_time_s": solve_wall_time,
            "peak_rss_kb": run["peak_rss_kb"],
            "environment": run["environment"],
        },
    }
    manifest["manifest_sha256"] = canonical_sha256(manifest)
    manifest_path = output_dir / "g2_physical_replay_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _parse_inputs(values: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise PhysicalReplayError("each --input must be KEY=PATH")
        key, raw_path = value.split("=", 1)
        if not key or not raw_path or key in result:
            raise PhysicalReplayError("input keys and paths must be non-empty and unique")
        result[key] = Path(raw_path).expanduser().resolve()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--input", action="append", required=True, metavar="KEY=PATH")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args()
    try:
        manifest = run_physical_replay(
            registry_path=args.registry.resolve(),
            paths=_parse_inputs(args.input),
            output_dir=args.output,
            repo_root=args.repo_root,
            argv=[sys.executable, *sys.argv],
        )
    except Exception as exc:
        print(json.dumps({"status": "UNRESOLVED", "reason": str(exc)}, indent=2))
        return 2
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "source_commit": manifest["source_commit"],
                "scientific_digest": manifest["scientific_digest"],
                "manifest_sha256": manifest["manifest_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
