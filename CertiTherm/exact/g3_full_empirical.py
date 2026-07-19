"""Registered G3 breadth runner for CertiTherm.

The former script generated eight labels by reusing an aggregate ptrace,
sharing one thermal operator across package labels, and comparing nested
uncertainty sets.  That path is intentionally removed.  This module consumes
content-bound physical bundles and evaluates complete architecture-selection
queries for three matched variants:

* the original DSE point estimate, represented by a singleton power domain;
* a placed-power reference, also represented by a singleton domain; and
* the registered spatial observation-equivalence class.

No workload trace, HotSpot configuration, or response matrix is generated or
mutated here.  Missing physical evidence is an input error, never a synthetic
fallback.
"""

from __future__ import annotations

import argparse
import itertools
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
    from .evidence import build_replay_artifact, replay_artifact, sha256_file
    from .linear_oracle import (
        canonical_sha256,
        normalize_problem,
        replay_power_witness,
    )
    from .run_g2_query import load_query_bundle
except ImportError:  # pragma: no cover - direct script/test-path execution.
    from decision_query import CERTIFIED, NON_IDENTIFIABLE, decide_architecture_query
    from evidence import build_replay_artifact, replay_artifact, sha256_file
    from linear_oracle import canonical_sha256, normalize_problem, replay_power_witness
    from run_g2_query import load_query_bundle


SUITE_SCHEMA_VERSION = "certitherm.g3-suite.v1"
SUITE_ARTIFACT_SCHEMA_VERSION = "certitherm.g3-suite-artifact.v1"
SUITE_REPLAY_SCHEMA_VERSION = "certitherm.g3-suite-replay.v1"
POINT_POWER_SEMANTICS = "original_thermodse_point_estimate"
PHYSICAL_EVIDENCE_CLASS = "physical_placed_power"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_VARIANTS = (
    "point_estimate",
    "placed_reference",
    "spatial_equivalence",
)


class G3InputError(ValueError):
    """Raised when a suite cannot support the registered G3 comparison."""


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
        raise G3InputError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise G3InputError(f"{path.name} must contain a JSON object")
    return value


def _relative_file(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise G3InputError(f"{field} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute():
        raise G3InputError(f"{field} must be relative to the containing bundle")
    target = (root / relative).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise G3InputError(f"{field} escapes the containing bundle") from exc
    if not target.is_file():
        raise G3InputError(f"{field} does not exist: {relative.as_posix()}")
    return target


def _identity_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) < 2:
        raise G3InputError(f"{field} must contain at least two identities")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise G3InputError(f"{field} identities must be non-empty text")
    if len(value) != len(set(value)):
        raise G3InputError(f"{field} identities must be unique")
    return tuple(value)


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise G3InputError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _power_vector(path: Path, expected_length: int, field: str) -> np.ndarray:
    try:
        value = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise G3InputError(f"cannot load {field}: {exc}") from exc
    power = np.asarray(value, dtype=np.float64)
    if power.shape != (expected_length,):
        raise G3InputError(f"{field} must have shape ({expected_length},)")
    if not np.all(np.isfinite(power)) or np.any(power < 0.0):
        raise G3InputError(f"{field} must be finite and non-negative")
    return power


def singleton_observation(power_w: Sequence[float]) -> dict[str, Any]:
    """Return a true point domain; every component has lower == upper."""

    power = np.asarray(power_w, dtype=np.float64)
    if power.ndim != 1 or not np.all(np.isfinite(power)) or np.any(power < 0.0):
        raise G3InputError("singleton power must be a finite non-negative vector")
    values = power.tolist()
    return {
        "per_block_power": values,
        "per_block_lower": values,
        "per_block_upper": values,
    }


def _validate_member(candidate: Mapping[str, Any], power: np.ndarray, label: str) -> None:
    try:
        problem = normalize_problem(
            candidate["response_k_per_w"],
            candidate["ambient_k"],
            candidate["observation"],
            candidate["block_names"],
        )
        replay = replay_power_witness(problem, power, feasibility_tolerance=1e-7)
    except (KeyError, TypeError, ValueError) as exc:
        raise G3InputError(f"cannot validate {label}: {exc}") from exc
    if not replay.get("valid"):
        raise G3InputError(
            f"{label} is outside the registered spatial observation domain: {replay}"
        )


def _suite_relative_input_files(
    suite_root: Path,
    query_spec_path: Path,
    records: Sequence[Mapping[str, str]],
    *,
    role_prefix: str,
) -> list[dict[str, str]]:
    rebound: list[dict[str, str]] = []
    for record in records:
        source = (query_spec_path.parent / record["path"]).resolve()
        try:
            relative = source.relative_to(suite_root.resolve())
        except ValueError as exc:
            raise G3InputError("query input escapes the G3 suite bundle") from exc
        rebound.append(
            {
                "role": f"{role_prefix}_{record['role']}",
                "path": relative.as_posix(),
                "sha256": record["sha256"],
            }
        )
    return rebound


def _validate_alias_guards(
    candidate_records: Sequence[Mapping[str, str]],
    workload_families: Sequence[str],
    package_regimes: Sequence[str],
) -> None:
    by_arch_package: dict[tuple[str, str], dict[str, Mapping[str, str]]] = {}
    by_arch_package_operator: dict[tuple[str, str], set[tuple[str, str]]] = {}
    by_arch_static: dict[str, set[tuple[str, str, str, str]]] = {}

    for record in candidate_records:
        arch_id = record["architecture_id"]
        package_id = record["package_id"]
        workload_family = record["workload_family"]
        key = (arch_id, package_id)
        family_records = by_arch_package.setdefault(key, {})
        if workload_family in family_records:
            previous = family_records[workload_family]
            if (
                previous["placed_power_sha256"] != record["placed_power_sha256"]
                or previous["point_power_sha256"] != record["point_power_sha256"]
            ):
                raise G3InputError(
                    f"architecture/package/workload {key + (workload_family,)} "
                    "has inconsistent power inputs"
                )
        family_records[workload_family] = record
        by_arch_package_operator.setdefault(key, set()).add(
            (record["response_sha256"], record["thermal_config_sha256"])
        )
        by_arch_static.setdefault(arch_id, set()).add(
            (
                record["candidate_id"],
                record["architecture_family"],
                record["sys_info_sha256"],
                record["placement_sha256"],
            )
        )

    expected_families = set(workload_families)
    for key, family_records in by_arch_package.items():
        if set(family_records) != expected_families:
            raise G3InputError(f"architecture/package {key} lacks the full workload matrix")
        placed_digests = {
            record["placed_power_sha256"] for record in family_records.values()
        }
        point_digests = {
            record["point_power_sha256"] for record in family_records.values()
        }
        if len(placed_digests) != len(expected_families):
            raise G3InputError(
                f"architecture/package {key} reuses one placed-power vector "
                "under multiple workload labels"
            )
        if len(point_digests) != len(expected_families):
            raise G3InputError(
                f"architecture/package {key} reuses one point estimate "
                "under multiple workload labels"
            )
        if len(by_arch_package_operator[key]) != 1:
            raise G3InputError(
                f"architecture/package {key} changes thermal operator across workloads"
            )

    by_arch: dict[str, dict[str, tuple[str, str]]] = {}
    for (arch_id, package_id), digests in by_arch_package_operator.items():
        by_arch.setdefault(arch_id, {})[package_id] = next(iter(digests))
    expected_packages = set(package_regimes)
    for arch_id, package_records in by_arch.items():
        if len(by_arch_static[arch_id]) != 1:
            raise G3InputError(
                f"architecture {arch_id} changes identity, family, sys_info, or placement "
                "across G3 strata"
            )
        if set(package_records) != expected_packages:
            raise G3InputError(f"architecture {arch_id} lacks the full package matrix")
        response_digests = {value[0] for value in package_records.values()}
        config_digests = {value[1] for value in package_records.values()}
        if len(response_digests) != len(expected_packages):
            raise G3InputError(
                f"architecture {arch_id} reuses one thermal response across package labels"
            )
        if len(config_digests) != len(expected_packages):
            raise G3InputError(
                f"architecture {arch_id} reuses one thermal config across package labels"
            )


def load_g3_suite(suite_path: Path) -> dict[str, Any]:
    """Load and validate a complete, content-bound G3 suite."""

    suite_path = suite_path.resolve()
    suite_root = suite_path.parent
    spec = _read_json(suite_path)
    if spec.get("schema_version") != SUITE_SCHEMA_VERSION:
        raise G3InputError("unsupported G3 suite schema")
    suite_id = spec.get("suite_id")
    if not isinstance(suite_id, str) or not suite_id.strip():
        raise G3InputError("suite_id must be non-empty text")
    if spec.get("evidence_class") != PHYSICAL_EVIDENCE_CLASS:
        raise G3InputError("G3 breadth requires physical_placed_power evidence")

    workload_families = _identity_list(spec.get("workload_families"), "workload_families")
    architecture_families = _identity_list(
        spec.get("architecture_families"), "architecture_families"
    )
    package_regimes = _identity_list(spec.get("package_regimes"), "package_regimes")
    raw_queries = spec.get("queries")
    if not isinstance(raw_queries, list) or not raw_queries:
        raise G3InputError("queries must be a non-empty list")

    expected_strata = set(itertools.product(workload_families, package_regimes))
    observed_strata: set[tuple[str, str]] = set()
    workload_ids: dict[str, str] = {}
    loaded_queries: list[dict[str, Any]] = []
    alias_records: list[dict[str, str]] = []
    reference_candidate_ids: set[str] | None = None
    thermal_limits: set[float] = set()
    objective_records: dict[tuple[str, str], set[tuple[float, int]]] = {}

    for query_index, raw_query in enumerate(raw_queries):
        if not isinstance(raw_query, Mapping):
            raise G3InputError(f"query {query_index} must be an object")
        workload_family = raw_query.get("workload_family")
        workload_id = raw_query.get("workload_id")
        package_id = raw_query.get("package_id")
        if workload_family not in workload_families:
            raise G3InputError(f"query {query_index} has an unregistered workload family")
        if package_id not in package_regimes:
            raise G3InputError(f"query {query_index} has an unregistered package regime")
        if not isinstance(workload_id, str) or not workload_id.strip():
            raise G3InputError(f"query {query_index} workload_id must be non-empty text")
        stratum = (workload_family, package_id)
        if stratum in observed_strata:
            raise G3InputError(f"duplicate G3 stratum: {stratum}")
        observed_strata.add(stratum)
        previous_workload_id = workload_ids.setdefault(workload_family, workload_id)
        if previous_workload_id != workload_id:
            raise G3InputError(
                f"workload family {workload_family} changes workload_id across packages"
            )

        query_spec_path = _relative_file(
            suite_root, raw_query.get("query_spec"), f"queries[{query_index}].query_spec"
        )
        raw_query_spec = _read_json(query_spec_path)
        if raw_query_spec.get("evidence_class") != PHYSICAL_EVIDENCE_CLASS:
            raise G3InputError(f"query {query_index} is not physical placed-power evidence")
        query_id, thermal_limit, spatial_candidates, input_files = load_query_bundle(
            query_spec_path
        )
        thermal_limits.add(float(thermal_limit))
        raw_candidates = raw_query_spec.get("candidates")
        if not isinstance(raw_candidates, list) or len(raw_candidates) != len(spatial_candidates):
            raise G3InputError(f"query {query_index} candidate records are inconsistent")

        point_candidates: list[dict[str, Any]] = []
        placed_candidates: list[dict[str, Any]] = []
        query_architecture_families: set[str] = set()
        query_candidate_ids: set[str] = set()
        rebound_files = _suite_relative_input_files(
            suite_root,
            query_spec_path,
            input_files,
            role_prefix=f"stratum_{query_index}",
        )
        rebound_files.append(
            {
                "role": f"stratum_{query_index}_suite_spec",
                "path": suite_path.relative_to(suite_root).as_posix(),
                "sha256": sha256_file(suite_path),
            }
        )

        for candidate_index, (raw_candidate, spatial_candidate) in enumerate(
            zip(raw_candidates, spatial_candidates)
        ):
            if not isinstance(raw_candidate, Mapping):
                raise G3InputError(
                    f"query {query_index} candidate {candidate_index} must be an object"
                )
            provenance = spatial_candidate.get("provenance")
            if not isinstance(provenance, Mapping):
                raise G3InputError("physical candidate provenance must be a mapping")
            for field, expected in (
                ("workload_family", workload_family),
                ("workload_id", workload_id),
                ("package_id", package_id),
            ):
                if provenance.get(field) != expected:
                    raise G3InputError(
                        f"query {query_index} candidate {candidate_index} {field} "
                        "does not match its suite stratum"
                    )
            architecture_family = provenance.get("architecture_family")
            if architecture_family not in architecture_families:
                raise G3InputError(
                    f"query {query_index} candidate {candidate_index} lacks a registered "
                    "architecture_family"
                )
            architecture_id = provenance.get("architecture_id")
            if not isinstance(architecture_id, str) or not architecture_id:
                raise G3InputError("architecture_id must be non-empty text")
            candidate_id = str(spatial_candidate["candidate_id"])
            if architecture_id != candidate_id:
                raise G3InputError(
                    f"candidate {candidate_id} does not match provenance architecture_id"
                )
            query_architecture_families.add(architecture_family)
            query_candidate_ids.add(candidate_id)
            try:
                objective = float(spatial_candidate["nonthermal_objective"])
                tie_rank = spatial_candidate["tie_break_rank"]
            except (KeyError, TypeError, ValueError) as exc:
                raise G3InputError("invalid nonthermal objective or tie rank") from exc
            if not np.isfinite(objective):
                raise G3InputError("nonthermal objective must be finite")
            if not isinstance(tie_rank, int) or isinstance(tie_rank, bool) or tie_rank < 0:
                raise G3InputError("tie-break rank must be a non-negative integer")
            objective_records.setdefault((str(workload_family), candidate_id), set()).add(
                (objective, tie_rank)
            )

            response_path = _relative_file(
                query_spec_path.parent,
                raw_candidate.get("response_npy"),
                "response_npy",
            )
            response_digest = sha256_file(response_path)
            if _digest(
                provenance.get("thermal_operator_sha256"),
                "thermal_operator_sha256",
            ) != response_digest:
                raise G3InputError("thermal_operator_sha256 does not bind response_npy")
            thermal_config_digest = _digest(
                provenance.get("thermal_config_sha256"),
                "thermal_config_sha256",
            )

            if raw_candidate.get("point_power_semantics") != POINT_POWER_SEMANTICS:
                raise G3InputError(
                    f"candidate {spatial_candidate['candidate_id']} lacks the registered "
                    "ThermoDSE point-estimate semantics"
                )
            point_path = _relative_file(
                query_spec_path.parent,
                raw_candidate.get("point_power_npy"),
                "point_power_npy",
            )
            placed_path = _relative_file(
                query_spec_path.parent,
                raw_candidate.get("placed_power_npy"),
                "placed_power_npy",
            )
            point_digest = sha256_file(point_path)
            placed_digest = sha256_file(placed_path)
            if _digest(
                provenance.get("placed_power_sha256"), "placed_power_sha256"
            ) != placed_digest:
                raise G3InputError("placed_power_sha256 does not bind placed_power_npy")

            dimension = len(spatial_candidate["block_names"])
            point_power = _power_vector(point_path, dimension, "point_power_npy")
            placed_power = _power_vector(placed_path, dimension, "placed_power_npy")
            _validate_member(spatial_candidate, point_power, "point estimate")
            _validate_member(spatial_candidate, placed_power, "placed-power reference")

            point_candidate = dict(spatial_candidate)
            point_candidate["observation"] = singleton_observation(point_power)
            placed_candidate = dict(spatial_candidate)
            placed_candidate["observation"] = singleton_observation(placed_power)
            point_candidates.append(point_candidate)
            placed_candidates.append(placed_candidate)

            for role, path, digest in (
                (f"stratum_{query_index}_candidate_{candidate_index}_point_power", point_path, point_digest),
                (f"stratum_{query_index}_candidate_{candidate_index}_placed_power", placed_path, placed_digest),
            ):
                rebound_files.append(
                    {
                        "role": role,
                        "path": path.relative_to(suite_root).as_posix(),
                        "sha256": digest,
                    }
                )
            alias_records.append(
                {
                    "candidate_id": candidate_id,
                    "workload_family": str(workload_family),
                    "package_id": str(package_id),
                    "architecture_id": architecture_id,
                    "architecture_family": str(architecture_family),
                    "sys_info_sha256": canonical_sha256(spatial_candidate.get("sys_info", [])),
                    "placement_sha256": _digest(
                        provenance.get("placement_sha256"), "placement_sha256"
                    ),
                    "placed_power_sha256": placed_digest,
                    "point_power_sha256": point_digest,
                    "response_sha256": response_digest,
                    "thermal_config_sha256": thermal_config_digest,
                }
            )

        if len(query_candidate_ids) != len(spatial_candidates):
            raise G3InputError(f"query {query_id} contains duplicate candidate IDs")
        if query_architecture_families != set(architecture_families):
            raise G3InputError(
                f"query {query_id} does not cover every registered architecture family"
            )
        if reference_candidate_ids is None:
            reference_candidate_ids = query_candidate_ids
        elif query_candidate_ids != reference_candidate_ids:
            raise G3InputError("G3 strata do not use the same architecture candidate pool")

        loaded_queries.append(
            {
                "query_id": query_id,
                "workload_family": workload_family,
                "workload_id": workload_id,
                "package_id": package_id,
                "thermal_limit_k": thermal_limit,
                "spatial_candidates": spatial_candidates,
                "point_candidates": point_candidates,
                "placed_candidates": placed_candidates,
                "input_files": rebound_files,
            }
        )

    if observed_strata != expected_strata:
        missing = sorted(expected_strata - observed_strata)
        extra = sorted(observed_strata - expected_strata)
        raise G3InputError(f"G3 suite is not Cartesian: missing={missing}, extra={extra}")
    if len(thermal_limits) != 1:
        raise G3InputError("G3 strata must use one frozen thermal limit")
    for key, objective_values in objective_records.items():
        if len(objective_values) != 1:
            raise G3InputError(
                f"workload/candidate {key} changes nonthermal order across packages"
            )
    _validate_alias_guards(alias_records, workload_families, package_regimes)

    order = {
        stratum: index
        for index, stratum in enumerate(itertools.product(workload_families, package_regimes))
    }
    loaded_queries.sort(
        key=lambda item: order[(item["workload_family"], item["package_id"])]
    )
    return {
        "suite_id": suite_id,
        "evidence_class": PHYSICAL_EVIDENCE_CLASS,
        "workload_families": workload_families,
        "architecture_families": architecture_families,
        "package_regimes": package_regimes,
        "queries": loaded_queries,
    }


def _run_variant(
    *,
    query_id: str,
    candidates: Sequence[Mapping[str, Any]],
    thermal_limit_k: float,
    source_commit: str,
    argv: Sequence[str],
    environment: Mapping[str, Any],
    input_files: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    started = time.perf_counter()
    result = decide_architecture_query(
        query_id,
        candidates,
        thermal_limit_k=thermal_limit_k,
    )
    wall_time = time.perf_counter() - started
    run = {
        "source_commit": source_commit,
        "command": list(argv),
        "environment": dict(environment),
        "exit_status": 0,
        "wall_time_s": wall_time,
        "peak_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "input_files": list(input_files),
    }
    return build_replay_artifact(
        query_id=query_id,
        candidates=candidates,
        thermal_limit_k=thermal_limit_k,
        result=result,
        run=run,
    )


def _result(entry: Mapping[str, Any], variant: str) -> Mapping[str, Any]:
    return entry["variants"][variant]["result"]


def _compute_metrics(entries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    point_commitment_not_identifiable = 0
    point_placed_disagreement = 0
    unresolved_variants = 0
    for entry in entries:
        point = _result(entry, "point_estimate")
        placed = _result(entry, "placed_reference")
        spatial = _result(entry, "spatial_equivalence")
        if point.get("status") == CERTIFIED and spatial.get("status") == NON_IDENTIFIABLE:
            point_commitment_not_identifiable += 1
        if (
            point.get("status") == CERTIFIED
            and placed.get("status") == CERTIFIED
            and point.get("certified_outcome") != placed.get("certified_outcome")
        ):
            point_placed_disagreement += 1
        unresolved_variants += sum(
            1 for variant in _VARIANTS if _result(entry, variant).get("status") == "UNRESOLVED"
        )
    return {
        "query_count": len(entries),
        "point_certified_count": sum(
            _result(entry, "point_estimate").get("status") == CERTIFIED for entry in entries
        ),
        "placed_certified_count": sum(
            _result(entry, "placed_reference").get("status") == CERTIFIED for entry in entries
        ),
        "spatial_certified_count": sum(
            _result(entry, "spatial_equivalence").get("status") == CERTIFIED for entry in entries
        ),
        "spatial_non_identifiable_count": sum(
            _result(entry, "spatial_equivalence").get("status") == NON_IDENTIFIABLE
            for entry in entries
        ),
        "point_commitment_not_identifiable_count": point_commitment_not_identifiable,
        "point_placed_disagreement_count": point_placed_disagreement,
        "unresolved_variant_count": unresolved_variants,
    }


def execute_g3_suite(
    loaded_suite: Mapping[str, Any],
    *,
    source_commit: str,
    argv: Sequence[str],
    environment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute all matched variants and return a self-authenticating suite artifact."""

    run_environment = dict(
        environment
        or {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "hostname": platform.node(),
        }
    )
    entries: list[dict[str, Any]] = []
    for query in loaded_suite["queries"]:
        variants = {
            "point_estimate": _run_variant(
                query_id=f"{query['query_id']}::point-estimate",
                candidates=query["point_candidates"],
                thermal_limit_k=query["thermal_limit_k"],
                source_commit=source_commit,
                argv=argv,
                environment=run_environment,
                input_files=query["input_files"],
            ),
            "placed_reference": _run_variant(
                query_id=f"{query['query_id']}::placed-reference",
                candidates=query["placed_candidates"],
                thermal_limit_k=query["thermal_limit_k"],
                source_commit=source_commit,
                argv=argv,
                environment=run_environment,
                input_files=query["input_files"],
            ),
            "spatial_equivalence": _run_variant(
                query_id=f"{query['query_id']}::spatial-equivalence",
                candidates=query["spatial_candidates"],
                thermal_limit_k=query["thermal_limit_k"],
                source_commit=source_commit,
                argv=argv,
                environment=run_environment,
                input_files=query["input_files"],
            ),
        }
        entries.append(
            {
                "query_id": query["query_id"],
                "workload_family": query["workload_family"],
                "workload_id": query["workload_id"],
                "package_id": query["package_id"],
                "variants": variants,
            }
        )

    content = {
        "schema_version": SUITE_ARTIFACT_SCHEMA_VERSION,
        "suite_id": loaded_suite["suite_id"],
        "evidence_class": loaded_suite["evidence_class"],
        "axes": {
            "workload_families": list(loaded_suite["workload_families"]),
            "architecture_families": list(loaded_suite["architecture_families"]),
            "package_regimes": list(loaded_suite["package_regimes"]),
        },
        "claim_boundary": (
            "A valid suite measures point/placed/spatial query outcomes only. "
            "It does not by itself close G3, establish an error rate, or prove "
            "independent-backend correctness."
        ),
        "entries": entries,
        "metrics": _compute_metrics(entries),
    }
    artifact = _jsonable(content)
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    return artifact


def replay_g3_suite_artifact(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Verify the suite envelope and freshly replay every embedded G2 artifact."""

    def invalid(reason: str) -> dict[str, Any]:
        return {
            "schema_version": SUITE_REPLAY_SCHEMA_VERSION,
            "status": "INVALID",
            "reason": reason,
        }

    if artifact.get("schema_version") != SUITE_ARTIFACT_SCHEMA_VERSION:
        return invalid("unsupported G3 suite artifact schema")
    supplied_digest = artifact.get("artifact_sha256")
    content = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    if supplied_digest != canonical_sha256(content):
        return invalid("G3 suite artifact digest mismatch")
    entries = artifact.get("entries")
    if not isinstance(entries, list):
        return invalid("G3 suite entries must be a list")

    receipts: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("variants"), Mapping):
            return invalid("invalid G3 suite entry")
        for variant in _VARIANTS:
            embedded = entry["variants"].get(variant)
            if not isinstance(embedded, Mapping):
                return invalid(f"missing {variant} artifact")
            receipt = replay_artifact(embedded)
            receipts.append(
                {
                    "query_id": entry.get("query_id"),
                    "variant": variant,
                    "status": receipt.get("status"),
                    "artifact_sha256": embedded.get("artifact_sha256"),
                }
            )
            if receipt.get("status") != "PASS":
                return invalid(
                    f"embedded {variant} replay failed for {entry.get('query_id')}"
                )
    try:
        recomputed_metrics = _compute_metrics(entries)
    except (KeyError, TypeError, ValueError) as exc:
        return invalid(f"cannot recompute G3 metrics: {exc}")
    if artifact.get("metrics") != recomputed_metrics:
        return invalid("G3 suite metrics do not match embedded query results")
    return {
        "schema_version": SUITE_REPLAY_SCHEMA_VERSION,
        "status": "PASS",
        "artifact_sha256": supplied_digest,
        "embedded_replays": receipts,
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
    raise G3InputError(f"{field} must be outside the Git worktree")


def run_registered_g3_suite(
    suite_path: Path,
    artifact_path: Path,
    receipt_path: Path,
    *,
    repo_root: Path,
    argv: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run a clean-tree G3 suite and write only external raw artifacts."""

    _require_external_output(artifact_path, repo_root, "artifact")
    _require_external_output(receipt_path, repo_root, "receipt")
    source_commit, dirty = _git_state(repo_root)
    if dirty:
        raise G3InputError("claim-grade G3 runner requires a clean Git worktree")
    loaded = load_g3_suite(suite_path)
    artifact = execute_g3_suite(
        loaded,
        source_commit=source_commit,
        argv=argv,
    )
    receipt = replay_g3_suite_artifact(artifact)
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
        description="Run a registered content-bound CertiTherm G3 suite"
    )
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args()
    try:
        artifact, receipt = run_registered_g3_suite(
            args.suite,
            args.artifact,
            args.receipt,
            repo_root=args.repo_root.resolve(),
            argv=[sys.executable, *sys.argv],
        )
    except Exception as exc:
        print(f"G3 suite unresolved: {exc}", file=sys.stderr)
        return 2
    print(
        f"suite={artifact['suite_id']} replay={receipt.get('status')} "
        f"queries={artifact['metrics']['query_count']}"
    )
    return 0 if receipt.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
