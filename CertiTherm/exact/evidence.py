"""Content-bound G2 artifact construction and replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import numpy as np

try:
    from .decision_query import decide_architecture_query, replay_architecture_tuple
    from .linear_oracle import canonical_sha256
except ImportError:  # pragma: no cover - direct CLI execution.
    from decision_query import decide_architecture_query, replay_architecture_tuple
    from linear_oracle import canonical_sha256


ARTIFACT_SCHEMA_VERSION = "certitherm.g2-replay-artifact.v2"
REPLAY_SCHEMA_VERSION = "certitherm.g2-replay-receipt.v2"
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


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


def sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        raise ValueError(f"run metadata is missing: {', '.join(missing)}")
    commit = run["source_commit"]
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise ValueError("source_commit must be a full lowercase Git digest")
    if not isinstance(run["command"], list) or not run["command"] or any(
        not isinstance(item, str) or not item for item in run["command"]
    ):
        raise ValueError("command must be a non-empty argv string list")
    if not isinstance(run["environment"], Mapping):
        raise ValueError("environment must be a mapping")
    if not isinstance(run["exit_status"], int) or isinstance(run["exit_status"], bool):
        raise ValueError("exit_status must be an integer")
    for name in ("wall_time_s", "peak_rss_kb"):
        value = float(run[name])
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    if not isinstance(run["input_files"], list):
        raise ValueError("input_files must be a list")
    for entry in run["input_files"]:
        if not isinstance(entry, Mapping):
            raise ValueError("each input_files entry must be a mapping")
        path = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(path, str) or not path or Path(path).is_absolute():
            raise ValueError("input file paths must be non-empty and repository-relative")
        if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
            raise ValueError("input file digest must be lowercase SHA-256")


def build_replay_artifact(
    *,
    query_id: str,
    candidates: Sequence[Mapping[str, Any]],
    thermal_limit_k: float,
    result: Mapping[str, Any],
    run: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic self-authenticating artifact envelope."""

    _validate_run_metadata(run)
    inputs = _jsonable(
        {
            "query_id": query_id,
            "thermal_limit_k": thermal_limit_k,
            "candidates": candidates,
        }
    )
    result_json = _jsonable(result)
    run_json = _jsonable(run)
    content = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "inputs": inputs,
        "result": result_json,
        "run": run_json,
    }
    digests = {
        "inputs_sha256": canonical_sha256(inputs),
        "result_sha256": canonical_sha256(result_json),
        "run_sha256": canonical_sha256(run_json),
    }
    envelope = {**content, "digests": digests}
    envelope["artifact_sha256"] = canonical_sha256(envelope)
    return envelope


def write_replay_artifact(path: Path, artifact: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(artifact), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _bounds_match(stored: Mapping[str, Any], replayed: Mapping[str, Any], tolerance_k: float) -> bool:
    if stored.get("status") != replayed.get("status"):
        return False
    if stored.get("status") == "UNRESOLVED":
        return stored.get("reason") == replayed.get("reason")
    for name in ("lower_d", "upper_d"):
        if abs(float(stored[name]) - float(replayed[name])) > tolerance_k:
            return False
    return True


def replay_artifact(
    artifact: Mapping[str, Any],
    *,
    numeric_tolerance_k: float = 1e-6,
) -> dict[str, Any]:
    """Verify hashes, direct witnesses, and a fresh query solve."""

    def invalid(reason: str) -> dict[str, Any]:
        return {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "status": "INVALID",
            "reason": reason,
        }

    if artifact.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        return invalid("unsupported artifact schema")
    required = ("inputs", "result", "run", "digests", "artifact_sha256")
    if any(field not in artifact for field in required):
        return invalid("artifact envelope is incomplete")
    try:
        _validate_run_metadata(artifact["run"])
    except (TypeError, ValueError) as exc:
        return invalid(str(exc))
    digests = artifact["digests"]
    expected_digests = {
        "inputs_sha256": canonical_sha256(artifact["inputs"]),
        "result_sha256": canonical_sha256(artifact["result"]),
        "run_sha256": canonical_sha256(artifact["run"]),
    }
    if digests != expected_digests:
        return invalid("content digest mismatch")
    without_artifact_digest = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    if artifact["artifact_sha256"] != canonical_sha256(without_artifact_digest):
        return invalid("artifact envelope digest mismatch")

    inputs = artifact["inputs"]
    stored = artifact["result"]
    try:
        query_id = inputs["query_id"]
        candidates = inputs["candidates"]
        thermal_limit = float(inputs["thermal_limit_k"])
    except (KeyError, TypeError, ValueError) as exc:
        return invalid(f"invalid embedded query: {exc}")

    direct_replays = []
    for witness_tuple in stored.get("witness_tuples", []):
        receipt = replay_architecture_tuple(
            candidates,
            witness_tuple,
            thermal_limit_k=thermal_limit,
        )
        direct_replays.append(receipt)
        if not receipt.get("valid"):
            return invalid("embedded decision witness failed direct replay")

    fresh = decide_architecture_query(query_id, candidates, thermal_limit_k=thermal_limit)
    if fresh.get("status") != stored.get("status"):
        return invalid("fresh query status differs from stored result")
    if fresh.get("query_digest") != stored.get("query_digest"):
        return invalid("fresh query digest differs from stored result")
    if fresh.get("reachable_outcomes") != stored.get("reachable_outcomes"):
        return invalid("fresh reachable outcomes differ from stored result")
    stored_bounds = stored.get("candidate_bounds", [])
    fresh_bounds = fresh.get("candidate_bounds", [])
    if len(stored_bounds) != len(fresh_bounds):
        return invalid("candidate-bound count differs on replay")
    for old, new in zip(stored_bounds, fresh_bounds):
        if old.get("candidate_id") != new.get("candidate_id") or not _bounds_match(
            old.get("result", {}), new.get("result", {}), numeric_tolerance_k
        ):
            return invalid("candidate bounds differ on replay")
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "status": "PASS",
        "artifact_sha256": artifact["artifact_sha256"],
        "query_digest": stored.get("query_digest"),
        "direct_witness_replays": direct_replays,
        "fresh_status": fresh.get("status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    receipt = replay_artifact(artifact)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if receipt.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
