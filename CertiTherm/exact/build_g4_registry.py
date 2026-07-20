"""Build a content-bound physical G4 measurement registry from a G3 suite artifact.

The registry family is the per-block placed-power channel: one registered
action appends one equality ``e_i^T p = p_i^placed`` to one candidate, which is
exactly the measurement family of the frozen fixed-refinement baseline.  This
keeps the G4 acquisition gate cost-comparable to fixed uniform refinement.

The builder is deterministic and self-verifying: after writing the bundle it
re-validates the registry against the selected spatial query artifact and
re-hashes every source file, so a malformed bundle fails here rather than in
the claim-grade runner.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

import numpy as np

try:
    from .evidence import sha256_file
    from .g3_baselines import _group_structure
    from .g4_acquisition import (
        PHYSICAL_MEASUREMENT_FAMILY,
        REGISTRY_SCHEMA_VERSION,
        load_measurement_registry_bundle,
        validate_measurement_registry,
    )
    from .linear_oracle import canonical_sha256
except ImportError:  # pragma: no cover - direct script/test-path execution.
    from evidence import sha256_file
    from g3_baselines import _group_structure
    from g4_acquisition import (
        PHYSICAL_MEASUREMENT_FAMILY,
        REGISTRY_SCHEMA_VERSION,
        load_measurement_registry_bundle,
        validate_measurement_registry,
    )
    from linear_oracle import canonical_sha256


SOURCE_SCHEMA_VERSION = "certitherm.g4-placed-power-source.v1"
MEASUREMENT_TOLERANCE_W = 1e-9

_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9._:/-]")


class G4RegistryBuildError(ValueError):
    """Raised when a registry cannot be built without inventing evidence."""


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


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _safe_id(text: str) -> str:
    cleaned = _ID_SAFE_RE.sub("_", str(text))
    if not cleaned or not cleaned[0].isalnum():
        cleaned = f"m{cleaned}"
    if len(cleaned) > 100:
        cleaned = f"{cleaned[:80]}-{canonical_sha256(cleaned)[:16]}"
    return cleaned


def undetermined_block_indices(candidate: Mapping[str, Any]) -> list[int]:
    """Blocks whose value is not fixed by the observation (frozen baseline rule)."""

    a_eq, b_eq, lower, _upper = _group_structure(candidate)
    undetermined: set[int] = set()
    for row in range(a_eq.shape[0]):
        indices = np.flatnonzero(a_eq[row] > 0.0)
        if float(b_eq[row]) > float(np.sum(lower[indices])) + 1e-12:
            undetermined.update(int(i) for i in indices)
    return sorted(undetermined)


def _select_spatial_query(
    g3_artifact: Mapping[str, Any], query_id: str
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    entries = g3_artifact.get("entries")
    if not isinstance(entries, list):
        raise G4RegistryBuildError("G3 artifact entries must be a list")
    matches = [
        entry
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("query_id") == query_id
    ]
    if len(matches) != 1:
        raise G4RegistryBuildError("query_id must select exactly one G3 suite entry")
    variants = matches[0].get("variants")
    if not isinstance(variants, Mapping):
        raise G4RegistryBuildError("selected entry has no variants")
    spatial = variants.get("spatial_equivalence")
    placed = variants.get("placed_reference")
    if not isinstance(spatial, Mapping) or not isinstance(placed, Mapping):
        raise G4RegistryBuildError("selected entry lacks spatial/placed variants")
    if spatial.get("result", {}).get("status") != "NON_IDENTIFIABLE":
        raise G4RegistryBuildError(
            "G4 registries only apply to NON_IDENTIFIABLE spatial queries"
        )
    if placed.get("result", {}).get("status") != "CERTIFIED":
        raise G4RegistryBuildError("placed reference is not certified for this query")
    return spatial, placed


def build_registry_bundle(
    g3_artifact: Mapping[str, Any],
    query_id: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Write source files plus registry.json; return the validated registry."""

    spatial, placed = _select_spatial_query(g3_artifact, query_id)
    spatial_candidates = spatial.get("inputs", {}).get("candidates")
    placed_candidates = placed.get("inputs", {}).get("candidates")
    if not isinstance(spatial_candidates, list) or not spatial_candidates:
        raise G4RegistryBuildError("spatial query has no candidates")
    placed_by_id = {
        str(candidate.get("candidate_id")): candidate for candidate in placed_candidates or []
    }

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_files: list[dict[str, str]] = []
    actions: list[dict[str, Any]] = []
    for candidate in sorted(spatial_candidates, key=lambda item: str(item["candidate_id"])):
        candidate_id = str(candidate["candidate_id"])
        placed = placed_by_id.get(candidate_id)
        if placed is None:
            raise G4RegistryBuildError(f"placed reference lacks candidate {candidate_id}")
        placed_observation = placed.get("observation", {})
        placed_power = np.asarray(
            placed_observation.get("per_block_power"), dtype=np.float64
        )
        block_names = list(candidate.get("block_names", []))
        if placed_power.shape != (len(block_names),):
            raise G4RegistryBuildError(f"placed power shape mismatch for {candidate_id}")
        if sorted(str(name) for name in placed.get("block_names", [])) != sorted(
            str(name) for name in block_names
        ):
            raise G4RegistryBuildError(f"placed block identities differ for {candidate_id}")

        source_name = f"placed_power_{_safe_id(candidate_id)}.json"
        source_payload = {
            "schema_version": SOURCE_SCHEMA_VERSION,
            "query_id": query_id,
            "candidate_id": candidate_id,
            "block_names": block_names,
            "per_block_power": placed_power,
            "provenance": placed.get("provenance"),
        }
        _write_json(output_dir / source_name, source_payload)
        role = f"placed_power_report_{_safe_id(candidate_id)}"
        source_files.append(
            {
                "role": role,
                "path": source_name,
                "sha256": sha256_file(output_dir / source_name),
            }
        )

        undetermined = undetermined_block_indices(candidate)
        for index in undetermined:
            block_name = str(block_names[index])
            measurement_id = _safe_id(f"ch::{candidate_id}::{block_name}")
            actions.append(
                {
                    "measurement_id": measurement_id,
                    "candidate_id": candidate_id,
                    "coefficients_by_block": {block_name: 1.0},
                    "cost": 1.0,
                    "obtainability_record": (
                        f"unit-level placed power channel on block {block_name} of "
                        f"{candidate_id}; obtainable at the early-DSE stage from the "
                        f"activity-driven per-unit power model bound to source "
                        f"{role} (post-floorplan, pre-signoff)"
                    ),
                }
            )

    if not actions:
        raise G4RegistryBuildError("no undetermined blocks: registry would be empty")

    registry = {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "registry_id": _safe_id(f"g4-per-block-channel::{query_id}"),
        "evidence_class": PHYSICAL_MEASUREMENT_FAMILY,
        "query_artifact_sha256": spatial.get("artifact_sha256"),
        "query_digest": spatial.get("result", {}).get("query_digest"),
        "measurement_value_tolerance_w": MEASUREMENT_TOLERANCE_W,
        "registration": {
            "measurement_family": "per_block_placed_power_channel",
            "cost_model": (
                "unit channel cost: one action appends one per-block equality "
                "e_i^T p = p_i^placed; policy cost is the number of appended "
                "channels, identical to the frozen fixed-refinement cost model"
            ),
            "cost_unit": "sensing_channel",
            "obtainability_basis": (
                "unit-level placed power from the activity-driven per-unit power "
                "model that produced the content-bound placed reference; source "
                "reports are SHA-256-bound inside this bundle"
            ),
        },
        "source_files": source_files,
        "actions": sorted(actions, key=lambda item: item["measurement_id"]),
    }

    registry_path = output_dir / "registry.json"
    _write_json(registry_path, registry)

    # Self-verification: validate against the base query and re-hash sources.
    validated = validate_measurement_registry(registry, base_query_artifact=spatial)
    load_measurement_registry_bundle(registry_path)
    if len(validated["actions"]) != len(actions):
        raise G4RegistryBuildError("validated registry action count mismatch")
    return validated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a physical per-block-channel G4 registry from a G3 artifact"
    )
    parser.add_argument("--g3-artifact", required=True, type=Path)
    parser.add_argument("--query-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        artifact = json.loads(args.g3_artifact.read_text(encoding="utf-8"))
        registry = build_registry_bundle(artifact, args.query_id, args.output_dir)
    except Exception as exc:
        print(f"G4 registry build failed: {exc}", file=sys.stderr)
        return 2
    summary = {
        "registry_id": registry["registry_id"],
        "registry_sha256": canonical_sha256(registry),
        "action_count": len(registry["actions"]),
        "source_file_count": len(registry["source_files"]),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
