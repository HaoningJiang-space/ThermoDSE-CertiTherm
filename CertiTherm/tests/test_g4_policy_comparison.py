"""Synthetic software tests for the G4 policy-comparison and registry builder.

These fixtures exercise policy mechanics and fail-closed behavior only.  They
are not G4 experimental evidence; the claim-grade comparison is produced by
the registered clean-tree runner on the real 2x2x2 bundle.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pytest


EXACT_DIR = Path(__file__).resolve().parents[1] / "exact"
sys.path.insert(0, str(EXACT_DIR))

from build_g4_registry import (
    G4RegistryBuildError,
    build_registry_bundle,
    undetermined_block_indices,
)
from decision_query import CERTIFIED, NON_IDENTIFIABLE, decide_architecture_query
from g3_baselines import run_fixed_uniform_refinement
from g4_acquisition import G4InputError, load_measurement_registry_bundle
from g4_policy_comparison import (
    FIXED_UNIFORM,
    NOT_APPLICABLE,
    UNCERTAINTY_WIDTH,
    WITNESS_DIRECTED,
    G4PolicyError,
    _append_block_equality,
    _classify,
    _undetermined_indices,
    run_uncertainty_width_policy,
    run_witness_directed_policy,
)
from linear_oracle import canonical_sha256


THERMAL_LIMIT = 301.62


def _spatial_candidate(candidate_id: str, objective: float, rank: int, placed, pinned=False):
    placed = np.asarray(placed, dtype=np.float64)
    blocks = [f"{candidate_id}_b{i}" for i in range(len(placed))]
    if pinned:
        lower = placed.tolist()
        upper = placed.tolist()
    else:
        lower = [0.0] * len(placed)
        upper = [0.8 * float(np.sum(placed))] * len(placed)
    return {
        "candidate_id": candidate_id,
        "nonthermal_objective": objective,
        "tie_break_rank": rank,
        "response_k_per_w": [[2.0, 1.0], [1.0, 2.0]],
        "ambient_k": [300.0, 300.0],
        "block_names": blocks,
        "sys_info": [1, 1],
        "observation": {
            "A_eq": [[1.0] * len(placed)],
            "b_eq": [float(np.sum(placed))],
            "per_block_lower": lower,
            "per_block_upper": upper,
        },
    }


def _placed_candidate(spatial):
    return {
        **{key: value for key, value in spatial.items() if key != "observation"},
        "observation": {
            "per_block_power": [
                (lo + hi) / 2.0 if hi > lo else lo
                for lo, hi in zip(
                    spatial["observation"]["per_block_lower"],
                    spatial["observation"]["per_block_upper"],
                )
            ]
        },
    }


def _fixture():
    spatial_a = _spatial_candidate("cand_a", 1.0, 0, [0.4, 0.6])
    spatial_b = _spatial_candidate("cand_b", 2.0, 1, [0.5, 0.5], pinned=True)
    # placed values must match what the policies read back.
    placed_a = dict(spatial_a)
    placed_a["observation"] = {"per_block_power": [0.4, 0.6]}
    placed_b = dict(spatial_b)
    placed_b["observation"] = {"per_block_power": [0.5, 0.5]}
    query = {
        "query_id": "synthetic_g4",
        "thermal_limit_k": THERMAL_LIMIT,
        "spatial_candidates": [spatial_a, spatial_b],
        "placed_candidates": [placed_a, placed_b],
    }
    base = decide_architecture_query(
        "synthetic_g4",
        query["spatial_candidates"],
        thermal_limit_k=THERMAL_LIMIT,
    )
    assert base["status"] == NON_IDENTIFIABLE
    assert base["reachable_outcomes"] == ["cand_a", "cand_b"]
    return query, base


def test_fixed_refinement_measures_every_undetermined_block():
    query, _base = _fixture()
    record = run_fixed_uniform_refinement(
        query["query_id"],
        query,
        THERMAL_LIMIT,
        spatial_oracle_status=NON_IDENTIFIABLE,
    )
    assert record["status"] == CERTIFIED
    assert record["selection"] == "cand_a"
    assert record["channel_cost"] == 2


def test_witness_directed_beats_fixed_on_concentrated_decision():
    query, base = _fixture()
    record = run_witness_directed_policy(
        query["query_id"],
        query,
        THERMAL_LIMIT,
        spatial_oracle_status=NON_IDENTIFIABLE,
        witness_tuples=base["witness_tuples"],
    )
    assert record["status"] == CERTIFIED
    assert record["selection"] == "cand_a"
    # one pinned block plus the group-sum row pins the whole 2-block domain
    assert record["channel_cost"] == 1
    assert len(record["rounds"]) == 1
    assert record["rounds"][0]["candidate_id"] == "cand_a"


def test_witness_directed_is_deterministic():
    query, base = _fixture()
    first = run_witness_directed_policy(
        query["query_id"],
        query,
        THERMAL_LIMIT,
        spatial_oracle_status=NON_IDENTIFIABLE,
        witness_tuples=base["witness_tuples"],
    )
    second = run_witness_directed_policy(
        query["query_id"],
        query,
        THERMAL_LIMIT,
        spatial_oracle_status=NON_IDENTIFIABLE,
        witness_tuples=base["witness_tuples"],
    )
    assert first["rounds"] == second["rounds"]
    assert first["channel_cost"] == second["channel_cost"]


def test_uncertainty_width_resolves_with_one_channel():
    query, _base = _fixture()
    record = run_uncertainty_width_policy(
        query["query_id"],
        query,
        THERMAL_LIMIT,
        spatial_oracle_status=NON_IDENTIFIABLE,
    )
    assert record["status"] == CERTIFIED
    assert record["selection"] == "cand_a"
    assert record["channel_cost"] == 1
    assert record["interval_lp_count"] == 4
    again = run_uncertainty_width_policy(
        query["query_id"],
        query,
        THERMAL_LIMIT,
        spatial_oracle_status=NON_IDENTIFIABLE,
    )
    assert again["rounds"] == record["rounds"]


def test_policies_not_applicable_on_certified_query():
    query, base = _fixture()
    for record in (
        run_fixed_uniform_refinement(
            query["query_id"], query, THERMAL_LIMIT, spatial_oracle_status=CERTIFIED
        ),
        run_uncertainty_width_policy(
            query["query_id"], query, THERMAL_LIMIT, spatial_oracle_status=CERTIFIED
        ),
        run_witness_directed_policy(
            query["query_id"],
            query,
            THERMAL_LIMIT,
            spatial_oracle_status=CERTIFIED,
            witness_tuples=base["witness_tuples"],
        ),
    ):
        assert record["status"] == NOT_APPLICABLE
        assert record["channel_cost"] == 0


def test_witness_directed_requires_witness_pair():
    query, _base = _fixture()
    with pytest.raises(G4PolicyError):
        run_witness_directed_policy(
            query["query_id"],
            query,
            THERMAL_LIMIT,
            spatial_oracle_status=NON_IDENTIFIABLE,
            witness_tuples=[],
        )


def test_append_block_equality_preserves_existing_rows():
    query, _base = _fixture()
    candidate = query["spatial_candidates"][0]
    modified = _append_block_equality(candidate, 0, 0.4)
    a_eq = np.asarray(modified["observation"]["A_eq"])
    b_eq = np.asarray(modified["observation"]["b_eq"])
    assert a_eq.shape == (2, 2)
    assert np.array_equal(a_eq[0], [1.0, 1.0])
    assert np.array_equal(a_eq[1], [1.0, 0.0])
    assert np.allclose(b_eq, [1.0, 0.4])
    again = _append_block_equality(modified, 1, 0.6)
    assert np.asarray(again["observation"]["A_eq"]).shape == (3, 2)


def test_classify_taxonomy():
    assert _classify("cand_a", True, "cand_a")["matches_placed_reference"] is True
    wrong = _classify("cand_b", True, "cand_a")
    assert wrong["matches_placed_reference"] is False
    assert wrong["error_class"] == "WRONG_ARCHITECTURE"
    none_verdict = _classify(None, False, "cand_a")
    assert none_verdict["error_class"] == "NO_COMMITMENT"
    assert none_verdict["matches_placed_reference"] is None


def test_undetermined_rule_matches_frozen_baseline():
    query, _base = _fixture()
    assert _undetermined_indices(query["spatial_candidates"][0]) == [0, 1]
    assert _undetermined_indices(query["spatial_candidates"][1]) == []


def _suite_artifact_fixture():
    query, base = _fixture()
    spatial_variant = {
        "artifact_sha256": canonical_sha256({"fixture": "spatial"}),
        "inputs": {"candidates": query["spatial_candidates"]},
        "result": {
            "status": NON_IDENTIFIABLE,
            "query_digest": canonical_sha256({"fixture": "digest"}),
        },
    }
    placed_variant = {
        "inputs": {"candidates": query["placed_candidates"]},
        "result": {"status": CERTIFIED, "certified_outcome": "cand_a"},
    }
    return {
        "entries": [
            {
                "query_id": "synthetic_g4",
                "variants": {
                    "spatial_equivalence": spatial_variant,
                    "placed_reference": placed_variant,
                },
            }
        ]
    }


def test_registry_builder_validates_and_is_deterministic(tmp_path):
    artifact = _suite_artifact_fixture()
    first = build_registry_bundle(artifact, "synthetic_g4", tmp_path / "bundle_a")
    assert len(first["actions"]) == 2
    assert len(first["source_files"]) == 2
    assert first["evidence_class"] == "physical_measurement_family"
    second = build_registry_bundle(artifact, "synthetic_g4", tmp_path / "bundle_b")
    assert canonical_sha256(first) == canonical_sha256(second)
    registry, records = load_measurement_registry_bundle(tmp_path / "bundle_a" / "registry.json")
    assert len(records) == 3
    assert len(registry["actions"]) == 2


def test_registry_builder_rejects_certified_query(tmp_path):
    artifact = _suite_artifact_fixture()
    artifact["entries"][0]["variants"]["spatial_equivalence"]["result"][
        "status"
    ] = CERTIFIED
    with pytest.raises(G4RegistryBuildError):
        build_registry_bundle(artifact, "synthetic_g4", tmp_path / "bundle")


def test_registry_bundle_fails_closed_on_tampered_source(tmp_path):
    artifact = _suite_artifact_fixture()
    build_registry_bundle(artifact, "synthetic_g4", tmp_path / "bundle")
    source = tmp_path / "bundle" / "placed_power_cand_a.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["per_block_power"][0] += 1.0
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(G4InputError):
        load_measurement_registry_bundle(tmp_path / "bundle" / "registry.json")
