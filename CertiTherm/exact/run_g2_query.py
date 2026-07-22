"""Run one registered CertiTherm G2 architecture query and emit a replay artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
from typing import Any, Mapping

import numpy as np
import scipy

try:
    from .decision_query import decide_architecture_query
    from .evidence import (
        build_replay_artifact,
        replay_artifact,
        sha256_file,
        write_replay_artifact,
    )
except ImportError:  # pragma: no cover - direct CLI execution.
    from decision_query import decide_architecture_query
    from evidence import (
        build_replay_artifact,
        replay_artifact,
        sha256_file,
        write_replay_artifact,
    )


QUERY_SPEC_SCHEMA_VERSION = "certitherm.g2-query-spec.v2"
OBSERVATION_SCHEMA_VERSION = "certitherm.placed-power-observation.v1"

_PHYSICAL_PROVENANCE_FIELDS = (
    "workload_id",
    "workload_family",
    "architecture_id",
    "package_id",
    "power_source",
    "power_source_sha256",
    "placement_sha256",
    "thermal_backend",
    "thermal_config_sha256",
)


def _relative_bundle_file(bundle_root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{field} must be relative to the query bundle")
    target = (bundle_root / relative).resolve()
    try:
        target.relative_to(bundle_root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field} escapes the query bundle") from exc
    if not target.is_file():
        raise ValueError(f"{field} does not exist: {relative.as_posix()}")
    return target


def _read_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _validate_physical_provenance(provenance: Any) -> None:
    if not isinstance(provenance, Mapping):
        raise ValueError("physical observation provenance must be a mapping")
    missing = [field for field in _PHYSICAL_PROVENANCE_FIELDS if not provenance.get(field)]
    if missing:
        raise ValueError(f"physical observation provenance is missing: {', '.join(missing)}")
    for field in ("power_source_sha256", "placement_sha256", "thermal_config_sha256"):
        digest = provenance[field]
        if not isinstance(digest, str) or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")


def load_query_bundle(spec_path: Path) -> tuple[str, float, list[dict[str, Any]], list[dict[str, str]]]:
    """Load and content-bind a query bundle without running an optimizer."""

    spec_path = spec_path.resolve()
    bundle_root = spec_path.parent
    spec = _read_json(spec_path)
    if spec.get("schema_version") != QUERY_SPEC_SCHEMA_VERSION:
        raise ValueError("unsupported G2 query-spec schema")
    query_id = spec.get("query_id")
    if not isinstance(query_id, str) or not query_id.strip():
        raise ValueError("query_id must be non-empty text")
    thermal_limit = float(spec["thermal_limit_k"])
    if not np.isfinite(thermal_limit) or thermal_limit < 0:
        raise ValueError("thermal_limit_k must be finite and non-negative")
    evidence_class = spec.get("evidence_class")
    if evidence_class not in ("synthetic_fixture", "physical_placed_power"):
        raise ValueError("evidence_class must be synthetic_fixture or physical_placed_power")
    raw_candidates = spec.get("candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError("query spec must contain candidate records")

    input_files = [
        {
            "role": "query_spec",
            "path": spec_path.name,
            "sha256": sha256_file(spec_path),
        }
    ]
    candidates: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_candidates):
        if not isinstance(raw, Mapping):
            raise ValueError(f"candidate {index} must be an object")
        response_path = _relative_bundle_file(bundle_root, raw.get("response_npy"), "response_npy")
        metadata_path = _relative_bundle_file(
            bundle_root, raw.get("thermal_metadata_json"), "thermal_metadata_json"
        )
        observation_path = _relative_bundle_file(
            bundle_root, raw.get("observation_json"), "observation_json"
        )
        response = np.load(response_path, allow_pickle=False)
        metadata = _read_json(metadata_path)
        observation_record = _read_json(observation_path)
        if observation_record.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
            raise ValueError(f"candidate {index} has an unsupported observation schema")
        blocks = metadata.get("blocks")
        if not isinstance(blocks, list) or blocks != observation_record.get("block_names"):
            raise ValueError(f"candidate {index} thermal and observation block identities disagree")
        if response.ndim != 2 or response.shape[0] == 0 or response.shape[1] != len(blocks):
            raise ValueError(
                f"candidate {index} response columns disagree with block identities"
            )
        temperature_points = metadata.get("temperature_points")
        if temperature_points is not None and (
            not isinstance(temperature_points, list)
            or len(temperature_points) != response.shape[0]
            or len(temperature_points) != len(set(temperature_points))
        ):
            raise ValueError(
                f"candidate {index} temperature-point identities disagree with response rows"
            )
        if evidence_class == "physical_placed_power":
            _validate_physical_provenance(observation_record.get("provenance"))

        candidate = {
            "candidate_id": raw.get("candidate_id"),
            "nonthermal_objective": raw.get("nonthermal_objective"),
            "tie_break_rank": raw.get("tie_break_rank"),
            "response_k_per_w": response,
            "ambient_k": metadata.get("T_ambient", metadata.get("ambient_k")),
            "observation": observation_record.get("observation"),
            "block_names": blocks,
            "area_mm2": raw.get("area_mm2"),
            "A_budget_m2": raw.get("A_budget_m2", 3e-4),
            "sys_info": metadata.get("sys_info", []),
            "numerical_temperature_error_k": raw.get(
                "numerical_temperature_error_k",
                metadata.get("numerical_temperature_error_k", 0.0),
            ),
            "decision_tolerance_k": raw.get(
                "decision_tolerance_k", metadata.get("decision_tolerance_k", 0.0)
            ),
            "provenance": observation_record.get("provenance", {}),
            "evidence_class": evidence_class,
        }
        candidates.append(candidate)
        for role, path in (
            (f"candidate_{index}_response", response_path),
            (f"candidate_{index}_thermal_metadata", metadata_path),
            (f"candidate_{index}_observation", observation_path),
        ):
            input_files.append(
                {
                    "role": role,
                    "path": path.relative_to(bundle_root).as_posix(),
                    "sha256": sha256_file(path),
                }
            )
    return query_id, thermal_limit, candidates, input_files


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


def run_registered_query(
    spec_path: Path,
    artifact_path: Path,
    receipt_path: Path,
    *,
    repo_root: Path,
    argv: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute a clean-tree query and immediately replay its artifact."""

    commit, dirty = _git_state(repo_root)
    if dirty:
        raise RuntimeError("claim-grade G2 runner requires a clean Git worktree")
    query_id, thermal_limit, candidates, input_files = load_query_bundle(spec_path)
    started = time.perf_counter()
    result = decide_architecture_query(query_id, candidates, thermal_limit_k=thermal_limit)
    wall_time = time.perf_counter() - started
    peak_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    run = {
        "source_commit": commit,
        "command": argv,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "hostname": platform.node(),
        },
        "exit_status": 0,
        "wall_time_s": wall_time,
        "peak_rss_kb": peak_rss,
        "input_files": input_files,
    }
    artifact = build_replay_artifact(
        query_id=query_id,
        candidates=candidates,
        thermal_limit_k=thermal_limit,
        result=result,
        run=run,
    )
    write_replay_artifact(artifact_path, artifact)
    receipt = replay_artifact(artifact)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return artifact, receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        artifact, receipt = run_registered_query(
            args.spec,
            args.artifact,
            args.receipt,
            repo_root=args.repo_root.resolve(),
            argv=[sys.executable, *sys.argv],
        )
    except Exception as exc:
        print(json.dumps({"status": "UNRESOLVED", "reason": str(exc)}, indent=2))
        return 2
    summary = {
        "artifact_sha256": artifact["artifact_sha256"],
        "query_status": artifact["result"].get("status"),
        "reachable_outcomes": artifact["result"].get("reachable_outcomes"),
        "replay_status": receipt.get("status"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if receipt.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
