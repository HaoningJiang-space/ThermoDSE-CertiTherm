"""Adversarial software tests for G4 (authored, not executed on 2026-07-20).

These synthetic fixtures test decision semantics and artifact plumbing only.
They are not physical evidence and do not establish a G4 paper result.
"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np


EXACT_DIR = Path(__file__).resolve().parents[1] / "exact"
sys.path.insert(0, str(EXACT_DIR))

from decision_query import CERTIFIED, NON_IDENTIFIABLE, decide_architecture_query
from evidence import build_replay_artifact
from g4_acquisition import (
    G4InputError,
    NO_REGISTERED_ACTION,
    NOT_APPLICABLE,
    WITNESS_PAIR_CONFIRMED,
    append_registered_measurement,
    build_acquisition_artifact,
    evaluate_registered_acquisition,
    replay_acquisition_artifact,
    validate_measurement_registry,
)


def _candidates(dimension: int, thermal_limit_k: float):
    names_a = [f"a{index}" for index in range(dimension)]
    names_b = [f"b{index}" for index in range(dimension)]
    observation = {
        "A_eq": [[1.0] * dimension],
        "b_eq": [1.0],
        "per_block_lower": [0.0] * dimension,
        "per_block_upper": [1.0] * dimension,
    }
    return [
        {
            "candidate_id": "arch_a",
            "nonthermal_objective": 0.0,
            "tie_break_rank": 0,
            "response_k_per_w": np.eye(dimension),
            "ambient_k": 0.0,
            "observation": observation,
            "block_names": names_a,
            "area_mm2": 1.0,
        },
        {
            "candidate_id": "arch_b",
            "nonthermal_objective": 1.0,
            "tie_break_rank": 1,
            "response_k_per_w": np.zeros((dimension, dimension)),
            "ambient_k": 0.0,
            "observation": observation,
            "block_names": names_b,
            "area_mm2": 1.0,
        },
    ]


def _base_artifact(dimension: int = 2, thermal_limit_k: float = 0.75):
    candidates = _candidates(dimension, thermal_limit_k)
    result = decide_architecture_query(
        "synthetic-g4-query", candidates, thermal_limit_k=thermal_limit_k
    )
    assert result["status"] == NON_IDENTIFIABLE
    run = {
        "source_commit": "a" * 40,
        "command": ["pytest", "synthetic-g4-fixture"],
        "environment": {"fixture": True},
        "exit_status": 0,
        "wall_time_s": 0.0,
        "peak_rss_kb": 0,
        "input_files": [],
    }
    return build_replay_artifact(
        query_id="synthetic-g4-query",
        candidates=candidates,
        thermal_limit_k=thermal_limit_k,
        result=result,
        run=run,
    )


def _separating_block(base_artifact):
    tuples = base_artifact["result"]["witness_tuples"][:2]
    powers = []
    for witness_tuple in tuples:
        entry = next(
            item
            for item in witness_tuple["candidates"]
            if item["candidate_id"] == "arch_a"
        )
        powers.append(np.asarray(entry["power_w"], dtype=float))
    index = int(np.argmax(np.abs(powers[0] - powers[1])))
    assert abs(powers[0][index] - powers[1][index]) > 1e-9
    return f"a{index}"


def _registry(base_artifact, actions):
    return {
        "schema_version": "certitherm.g4-measurement-registry.v1",
        "registry_id": "synthetic-test-registry",
        "evidence_class": "synthetic_fixture",
        "query_artifact_sha256": base_artifact["artifact_sha256"],
        "query_digest": base_artifact["result"]["query_digest"],
        "measurement_value_tolerance_w": 1e-9,
        "registration": {
            "measurement_family": "synthetic explicit linear forms",
            "cost_model": "declared scalar fixture cost",
            "cost_unit": "fixture-channel",
            "obtainability_basis": "software-test fixture only",
        },
        "source_files": [],
        "actions": actions,
    }


def _coordinate_action(block: str, *, cost: float = 1.0, name: str = "measure-a"):
    return {
        "measurement_id": name,
        "candidate_id": "arch_a",
        "coefficients_by_block": {block: 1.0},
        "cost": cost,
        "obtainability_record": "synthetic direct coordinate",
    }


def test_append_preserves_all_existing_constraints():
    candidate = {
        "response_k_per_w": np.eye(3),
        "ambient_k": 0.0,
        "block_names": ["x", "y", "z"],
        "observation": {
            "A_eq": [[1.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            "b_eq": [1.0, 0.25],
            "A_ub": [[1.0, 0.0, 0.0]],
            "b_ub": [0.8],
            "per_block_lower": [0.0, 0.0, 0.25],
            "per_block_upper": [0.8, 1.0, 0.25],
        },
    }
    augmented = append_registered_measurement(candidate, {"y": 1.0}, 0.4)
    assert augmented["A_eq"] == [
        [1.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0],
    ]
    assert augmented["b_eq"] == [1.0, 0.25, 0.4]
    assert augmented["A_ub"] == [[1.0, 0.0, 0.0]]
    assert augmented["b_ub"] == [0.8]
    assert augmented["per_block_lower"] == [0.0, 0.0, 0.25]
    assert augmented["per_block_upper"] == [0.8, 1.0, 0.25]


def test_complete_query_confirms_both_distinct_witness_outcomes():
    base = _base_artifact()
    block = _separating_block(base)
    registry = _registry(
        base,
        [
            {
                "measurement_id": "total-power-again",
                "candidate_id": "arch_a",
                "coefficients_by_block": {"a0": 1.0, "a1": 1.0},
                "cost": 0.5,
                "obtainability_record": "synthetic redundant aggregate",
            },
            _coordinate_action(block),
        ],
    )
    result = evaluate_registered_acquisition(base, registry)
    assert result["status"] == WITNESS_PAIR_CONFIRMED
    assert result["selected_action"]["measurement_id"] == "measure-a"
    assert result["action_evaluations"][0]["status"] == (
        "WITNESS_VALUES_INDISTINGUISHABLE"
    )
    conditioned = result["selected_action"]["conditioned_queries"]
    assert len(conditioned) == 2
    assert all(item["result"]["status"] == CERTIFIED for item in conditioned)
    assert [item["result"]["certified_outcome"] for item in conditioned] == [
        item["expected_outcome"] for item in conditioned
    ]
    assert conditioned[0]["expected_outcome"] != conditioned[1]["expected_outcome"]


def test_one_direction_only_is_not_reported_as_resolution():
    base = _base_artifact(dimension=3, thermal_limit_k=0.6)
    block = _separating_block(base)
    result = evaluate_registered_acquisition(
        base, _registry(base, [_coordinate_action(block)])
    )
    assert result["status"] == NO_REGISTERED_ACTION
    assert result["selected_action"] is None
    assert result["action_evaluations"][0]["status"] == "WITNESS_PAIR_NOT_CONFIRMED"
    statuses = [
        item["result"]["status"]
        for item in result["action_evaluations"][0]["conditioned_queries"]
    ]
    assert CERTIFIED in statuses
    assert NON_IDENTIFIABLE in statuses


def test_explicit_coefficients_do_not_depend_on_measurement_name_parsing():
    base = _base_artifact()
    block = _separating_block(base)
    registry = _registry(
        base,
        [_coordinate_action(block, name="interposer_eblk")],
    )
    result = evaluate_registered_acquisition(base, registry)
    assert result["status"] == WITNESS_PAIR_CONFIRMED
    assert result["selected_action"]["measurement_id"] == "interposer_eblk"


def test_unknown_block_is_rejected_before_any_solve():
    base = _base_artifact()
    registry = _registry(base, [_coordinate_action("not-a-block")])
    try:
        validate_measurement_registry(registry, base_query_artifact=base)
    except G4InputError as exc:
        assert "unknown block" in str(exc)
    else:
        raise AssertionError("an unbound measurement coefficient was accepted")


def test_certified_base_query_is_not_mislabeled_as_acquisition_success():
    candidates = _candidates(2, 1.1)
    result = decide_architecture_query(
        "already-certified", candidates, thermal_limit_k=1.1
    )
    assert result["status"] == CERTIFIED
    base = build_replay_artifact(
        query_id="already-certified",
        candidates=candidates,
        thermal_limit_k=1.1,
        result=result,
        run={
            "source_commit": "a" * 40,
            "command": ["pytest", "certified-fixture"],
            "environment": {"fixture": True},
            "exit_status": 0,
            "wall_time_s": 0.0,
            "peak_rss_kb": 0,
            "input_files": [],
        },
    )
    registry = _registry(base, [_coordinate_action("a0")])
    acquisition = evaluate_registered_acquisition(base, registry)
    assert acquisition["status"] == NOT_APPLICABLE
    assert acquisition["reason"] == "BASE_QUERY_IS_NOT_NON_IDENTIFIABLE"


def test_artifact_replay_detects_tampering():
    base = _base_artifact()
    registry = _registry(base, [_coordinate_action(_separating_block(base))])
    result = evaluate_registered_acquisition(base, registry)
    artifact = build_acquisition_artifact(
        base_query_artifact=base,
        measurement_registry=registry,
        parent_g3={
            "suite_id": "synthetic-suite",
            "query_id": "synthetic-g4-query",
            "variant": "spatial_equivalence",
            "artifact_sha256": "b" * 64,
        },
        result=result,
        run={
            "source_commit": "a" * 40,
            "command": ["pytest", "artifact-fixture"],
            "environment": {"fixture": True},
            "exit_status": 0,
            "wall_time_s": 0.0,
            "peak_rss_kb": 0,
            "input_files": [],
        },
    )
    assert replay_acquisition_artifact(artifact)["status"] == "PASS"
    artifact["result"]["selected_action"]["cost"] = 999.0
    assert replay_acquisition_artifact(artifact)["status"] == "INVALID"
