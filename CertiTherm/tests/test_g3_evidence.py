"""Adversarial tests for the registered G3 evidence path.

These fixtures are synthetic software tests only.  They exercise fail-closed
input binding and query semantics; they are not G3 experimental evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np


EXACT_DIR = Path(__file__).resolve().parents[1] / "exact"
sys.path.insert(0, str(EXACT_DIR))

from decision_query import CERTIFIED, NON_IDENTIFIABLE
from evidence import sha256_file
from g3_full_empirical import (
    G3InputError,
    execute_g3_suite,
    load_g3_suite,
    replay_g3_suite_artifact,
    singleton_observation,
)


WORKLOADS = {
    "cnn": "resnet50",
    "attention": "transformer",
}
PACKAGES = ("standard", "enhanced")
ARCHITECTURES = {
    "mesh_family": "arch_a",
    "square_family": "arch_b",
}


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _powers(workload_family: str, architecture_id: str):
    if workload_family == "cnn":
        point = np.asarray([0.45, 0.55])
        placed = np.asarray([0.20, 0.80])
    else:
        point = np.asarray([0.52, 0.48])
        placed = np.asarray([0.85, 0.15])
    if architecture_id == "arch_b":
        point = point[::-1].copy()
        placed = placed[::-1].copy()
    return point, placed


def _build_suite(
    root: Path,
    *,
    reuse_workload_power: bool = False,
    reuse_package_operator: bool = False,
    omit_last_stratum: bool = False,
) -> Path:
    query_records = []
    for workload_family, workload_id in WORKLOADS.items():
        for package_id in PACKAGES:
            query_dir = root / f"{workload_family}_{package_id}"
            query_dir.mkdir()
            candidates = []
            for architecture_family, architecture_id in ARCHITECTURES.items():
                blocks = [f"{architecture_id}_b0", f"{architecture_id}_b1"]
                if architecture_id == "arch_a":
                    scale = 1.0 if package_id == "standard" else 1.1
                else:
                    scale = 0.10 if package_id == "standard" else 0.12
                if reuse_package_operator and package_id == "enhanced":
                    scale = 1.0 if architecture_id == "arch_a" else 0.10
                response = scale * np.eye(2)
                response_path = query_dir / f"{architecture_id}_R.npy"
                np.save(response_path, response, allow_pickle=False)

                point, placed = _powers(workload_family, architecture_id)
                if reuse_workload_power and workload_family == "attention":
                    _, placed = _powers("cnn", architecture_id)
                point_path = query_dir / f"{architecture_id}_point.npy"
                placed_path = query_dir / f"{architecture_id}_placed.npy"
                np.save(point_path, point, allow_pickle=False)
                np.save(placed_path, placed, allow_pickle=False)

                config_label = package_id
                if reuse_package_operator and package_id == "enhanced":
                    config_label = "standard"
                provenance = {
                    "workload_id": workload_id,
                    "workload_family": workload_family,
                    "architecture_id": architecture_id,
                    "architecture_family": architecture_family,
                    "package_id": package_id,
                    "power_source": placed_path.name,
                    "power_source_sha256": sha256_file(placed_path),
                    "placed_power_sha256": sha256_file(placed_path),
                    "placement_sha256": _digest(f"placement-{architecture_id}"),
                    "thermal_backend": "synthetic-test-operator",
                    "thermal_config_sha256": _digest(f"thermal-config-{config_label}"),
                    "thermal_operator_sha256": sha256_file(response_path),
                }
                observation_path = query_dir / f"{architecture_id}_observation.json"
                _write_json(
                    observation_path,
                    {
                        "schema_version": "certitherm.placed-power-observation.v1",
                        "block_names": blocks,
                        "observation": {
                            "A_eq": [[1.0, 1.0]],
                            "b_eq": [1.0],
                            "per_block_lower": [0.0, 0.0],
                            "per_block_upper": [1.0, 1.0],
                        },
                        "provenance": provenance,
                    },
                )
                metadata_path = query_dir / f"{architecture_id}_thermal.json"
                _write_json(
                    metadata_path,
                    {
                        "T_ambient": 0.0,
                        "blocks": blocks,
                        "temperature_points": blocks,
                        "sys_info": [2, 1],
                    },
                )
                candidates.append(
                    {
                        "candidate_id": architecture_id,
                        "nonthermal_objective": 0.0 if architecture_id == "arch_a" else 1.0,
                        "tie_break_rank": 0 if architecture_id == "arch_a" else 1,
                        "response_npy": response_path.name,
                        "thermal_metadata_json": metadata_path.name,
                        "observation_json": observation_path.name,
                        "point_power_npy": point_path.name,
                        "placed_power_npy": placed_path.name,
                        "point_power_semantics": "original_thermodse_point_estimate",
                        "area_mm2": 1.0,
                    }
                )
            query_path = query_dir / "query.json"
            _write_json(
                query_path,
                {
                    "schema_version": "certitherm.g2-query-spec.v2",
                    "query_id": f"{workload_family}-{package_id}",
                    "thermal_limit_k": 0.75,
                    "evidence_class": "physical_placed_power",
                    "candidates": candidates,
                },
            )
            query_records.append(
                {
                    "workload_family": workload_family,
                    "workload_id": workload_id,
                    "package_id": package_id,
                    "query_spec": query_path.relative_to(root).as_posix(),
                }
            )
    if omit_last_stratum:
        query_records.pop()
    suite_path = root / "suite.json"
    _write_json(
        suite_path,
        {
            "schema_version": "certitherm.g3-suite.v1",
            "suite_id": "synthetic-software-test-only",
            "evidence_class": "physical_placed_power",
            "workload_families": list(WORKLOADS),
            "architecture_families": list(ARCHITECTURES),
            "package_regimes": list(PACKAGES),
            "queries": query_records,
        },
    )
    return suite_path


def test_singleton_baseline_fixes_every_component():
    observation = singleton_observation([0.25, 0.75])
    assert observation["per_block_power"] == [0.25, 0.75]
    assert observation["per_block_lower"] == [0.25, 0.75]
    assert observation["per_block_upper"] == [0.25, 0.75]


def test_full_suite_runs_cross_candidate_point_placed_and_spatial_queries(tmp_path):
    suite_path = _build_suite(tmp_path)
    loaded = load_g3_suite(suite_path)
    artifact = execute_g3_suite(
        loaded,
        source_commit="a" * 40,
        argv=["python", "-m", "CertiTherm.exact.g3_full_empirical"],
        environment={"test_fixture": True},
    )
    receipt = replay_g3_suite_artifact(artifact)

    assert receipt["status"] == "PASS"
    assert artifact["metrics"] == {
        "query_count": 4,
        "point_certified_count": 4,
        "placed_certified_count": 4,
        "spatial_certified_count": 0,
        "spatial_non_identifiable_count": 4,
        "point_commitment_not_identifiable_count": 4,
        "point_placed_disagreement_count": 4,
        "unresolved_variant_count": 0,
    }
    for entry in artifact["entries"]:
        assert entry["variants"]["point_estimate"]["result"]["status"] == CERTIFIED
        assert entry["variants"]["placed_reference"]["result"]["status"] == CERTIFIED
        assert (
            entry["variants"]["spatial_equivalence"]["result"]["status"]
            == NON_IDENTIFIABLE
        )
        assert entry["variants"]["point_estimate"]["result"]["certified_outcome"] == "arch_a"
        assert entry["variants"]["placed_reference"]["result"]["certified_outcome"] == "arch_b"
        assert entry["variants"]["spatial_equivalence"]["result"]["reachable_outcomes"] == [
            "arch_a",
            "arch_b",
        ]


def test_reused_placed_power_under_two_workload_labels_is_rejected(tmp_path):
    suite_path = _build_suite(tmp_path, reuse_workload_power=True)
    try:
        load_g3_suite(suite_path)
    except G3InputError as exc:
        assert "reuses one placed-power vector" in str(exc)
    else:
        raise AssertionError("workload relabeling was accepted")


def test_reused_operator_and_config_under_two_package_labels_is_rejected(tmp_path):
    suite_path = _build_suite(tmp_path, reuse_package_operator=True)
    try:
        load_g3_suite(suite_path)
    except G3InputError as exc:
        assert "reuses one thermal response" in str(exc)
    else:
        raise AssertionError("package operator aliasing was accepted")


def test_missing_cartesian_stratum_is_rejected(tmp_path):
    suite_path = _build_suite(tmp_path, omit_last_stratum=True)
    try:
        load_g3_suite(suite_path)
    except G3InputError as exc:
        assert "not Cartesian" in str(exc)
    else:
        raise AssertionError("an incomplete G3 matrix was accepted")


def test_suite_artifact_tampering_is_rejected(tmp_path):
    suite_path = _build_suite(tmp_path)
    artifact = execute_g3_suite(
        load_g3_suite(suite_path),
        source_commit="a" * 40,
        argv=["python", "g3_full_empirical.py"],
        environment={"test_fixture": True},
    )
    artifact["metrics"]["query_count"] = 99
    assert replay_g3_suite_artifact(artifact)["status"] == "INVALID"
