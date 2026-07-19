"""Adversarial tests for the corrected G2 decision and evidence path."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from unittest import mock

import numpy as np


EXACT_DIR = Path(__file__).resolve().parents[1] / "exact"
sys.path.insert(0, str(EXACT_DIR))

import linear_oracle
from decision_query import (
    CERTIFIED,
    NON_IDENTIFIABLE,
    NO_FEASIBLE_DESIGN,
    decide_architecture_query,
    replay_architecture_tuple,
)
from evidence import build_replay_artifact, replay_artifact
from linear_oracle import canonical_sha256, solve_candidate_bounds
from measurement import decide_with_extra_measurement
from run_g2_query import load_query_bundle, run_registered_query
from run_g2_physical_replay import (
    PhysicalReplayError,
    _read_registry,
    _verify_registered_files,
)


def _observation(total: float, n: int, upper: float = 10.0, lower=None):
    return {
        "per_block_power": [total / n] * n,
        "per_block_lower": [0.0] * n if lower is None else list(lower),
        "per_block_upper": [upper] * n,
    }


def _candidate(
    candidate_id,
    objective,
    rank,
    response,
    observation,
    *,
    area_mm2=1.0,
    numerical_temperature_error_k=0.0,
    decision_tolerance_k=0.0,
):
    n = np.asarray(response).shape[1]
    return {
        "candidate_id": candidate_id,
        "nonthermal_objective": objective,
        "tie_break_rank": rank,
        "response_k_per_w": response,
        "ambient_k": 0.0,
        "observation": observation,
        "block_names": [f"{candidate_id}_b{i}" for i in range(n)],
        "area_mm2": area_mm2,
        "A_budget_m2": 3e-4,
        "numerical_temperature_error_k": numerical_temperature_error_k,
        "decision_tolerance_k": decision_tolerance_k,
    }


def test_nonzero_lower_bounds_are_enforced_in_minmax_and_witness():
    result = solve_candidate_bounds(
        np.eye(2),
        0.0,
        _observation(2.0, 2, upper=2.0, lower=[1.5, 0.0]),
        ["a", "b"],
        thermal_limit_k=1.25,
    )
    assert result["status"] == "CERTIFIED_INFEASIBLE"
    assert abs(result["lower_d"] - 1.5) < 1e-8
    assert np.all(np.asarray(result["witness_lower"]) >= np.array([1.5, 0.0]) - 1e-9)


def test_explicit_observations_and_registered_inequality_are_enforced():
    observation = {
        "A_eq": [[1.0, 1.0], [1.0, 0.0]],
        "b_eq": [2.0, 1.25],
        "A_ub": [[0.0, 1.0]],
        "b_ub": [0.75],
        "per_block_lower": [0.0, 0.0],
        "per_block_upper": [2.0, 2.0],
    }
    result = solve_candidate_bounds(
        np.eye(2), 0.0, observation, ["a", "b"], thermal_limit_k=1.0
    )
    assert result["status"] == "CERTIFIED_INFEASIBLE"
    assert abs(result["lower_d"] - 1.25) < 1e-8
    assert result["lower_replay"]["valid"]


def test_missing_compact_upper_bound_is_unresolved():
    result = solve_candidate_bounds(
        np.eye(2),
        0.0,
        {"per_block_power": [0.5, 0.5], "per_block_lower": [0.0, 0.0]},
        ["a", "b"],
        thermal_limit_k=1.0,
    )
    assert result["status"] == "UNRESOLVED"
    assert result["reason"] == "UNRESOLVED_INVALID_INPUT"


def test_empty_domain_is_unresolved_not_certified():
    result = solve_candidate_bounds(
        np.eye(2),
        0.0,
        _observation(3.0, 2, upper=1.0),
        ["a", "b"],
        thermal_limit_k=1.0,
    )
    assert result["status"] == "UNRESOLVED"
    assert result["reason"] == "UNRESOLVED_EMPTY_DOMAIN"


def test_non_monotone_or_nonfinite_operator_is_unresolved():
    negative = solve_candidate_bounds(
        [[1.0, -0.1], [0.0, 1.0]],
        0.0,
        _observation(1.0, 2),
        ["a", "b"],
        thermal_limit_k=1.0,
    )
    nonfinite = solve_candidate_bounds(
        [[1.0, np.nan], [0.0, 1.0]],
        0.0,
        _observation(1.0, 2),
        ["a", "b"],
        thermal_limit_k=1.0,
    )
    assert negative["status"] == "UNRESOLVED"
    assert nonfinite["status"] == "UNRESOLVED"


def test_thermal_limit_equality_is_feasible():
    result = solve_candidate_bounds(
        [[1.0]],
        0.0,
        _observation(1.0, 1, upper=1.0),
        ["a"],
        thermal_limit_k=1.0,
    )
    assert result["status"] == "CERTIFIED_SAFE"
    assert result["can_be_feasible"] is True
    assert result["can_be_infeasible"] is False


def test_rectangular_operator_supports_more_power_variables_than_thermal_points():
    response = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 1.0]])
    result = solve_candidate_bounds(
        response,
        [0.0, 0.0],
        _observation(1.0, 3, upper=1.0),
        ["p0", "p1", "p2"],
        thermal_limit_k=0.75,
    )
    assert result["status"] == "NON_IDENTIFIABLE"
    assert abs(result["lower_d"] - 0.5) < 1e-8
    assert abs(result["upper_d"] - 1.0) < 1e-8
    assert len(result["witness_lower"]) == 3


def test_two_sided_temperature_error_band_fails_closed_near_limit():
    unresolved = solve_candidate_bounds(
        [[1.0]],
        0.0,
        _observation(1.0, 1, upper=1.0),
        ["p0"],
        thermal_limit_k=1.0,
        numerical_temperature_error_k=0.1,
    )
    safe = solve_candidate_bounds(
        [[1.0]],
        0.0,
        _observation(1.0, 1, upper=1.0),
        ["p0"],
        thermal_limit_k=1.11,
        numerical_temperature_error_k=0.1,
    )
    infeasible = solve_candidate_bounds(
        [[1.0]],
        0.0,
        _observation(1.0, 1, upper=1.0),
        ["p0"],
        thermal_limit_k=0.89,
        numerical_temperature_error_k=0.1,
    )
    assert unresolved["status"] == "UNRESOLVED"
    assert unresolved["reason"] == "UNRESOLVED_NUMERICAL_DECISION_BAND"
    assert safe["status"] == "CERTIFIED_SAFE"
    assert infeasible["status"] == "CERTIFIED_INFEASIBLE"


def test_replay_disagreement_fails_closed():
    with mock.patch.object(
        linear_oracle,
        "replay_power_witness",
        return_value={"valid": False, "reason": "forged"},
    ):
        result = solve_candidate_bounds(
            [[1.0]],
            0.0,
            _observation(1.0, 1, upper=1.0),
            ["a"],
            thermal_limit_k=1.0,
        )
    assert result["status"] == "UNRESOLVED"
    assert result["reason"] == "UNRESOLVED_CERTIFICATE_FAILURE"


def test_extra_measurement_reuses_correct_minmax_kernel():
    observation = _observation(2.0, 2)
    observation["measurement_w_p"] = ([1.0, 0.0], 1.5)
    result = decide_with_extra_measurement(
        np.eye(2), 0.0, ["a", "b"], observation, T_budget=1.25, area_mm2=1.0
    )
    assert result["status"] == "CERTIFIED_INFEASIBLE"
    assert abs(result["lower_d"] - 1.5) < 1e-8


def test_query_certifies_first_candidate_when_it_is_always_safe():
    candidate_a = _candidate("A", 1.0, 0, np.eye(2), _observation(1.0, 2, upper=1.0))
    candidate_b = _candidate("B", 2.0, 1, np.eye(2), _observation(1.0, 2, upper=1.0))
    result = decide_architecture_query(
        "certified-first", [candidate_b, candidate_a], thermal_limit_k=1.0
    )
    assert result["status"] == CERTIFIED
    assert result["certified_outcome"] == "A"
    assert result["reachable_outcomes"] == ["A"]
    assert result["tuple_replays"][0]["valid"]


def test_query_emits_two_complete_decision_changing_tuples():
    candidate_a = _candidate("A", 1.0, 0, np.eye(2), _observation(1.0, 2, upper=1.0))
    candidate_b = _candidate("B", 2.0, 1, np.zeros((2, 2)), _observation(1.0, 2, upper=1.0))
    result = decide_architecture_query(
        "flip-a-b", [candidate_a, candidate_b], thermal_limit_k=0.75
    )
    assert result["status"] == NON_IDENTIFIABLE
    assert result["reachable_outcomes"] == ["A", "B"]
    assert [item["selected_outcome"] for item in result["tuple_replays"]] == ["A", "B"]
    assert all(len(item["candidates"]) == 2 for item in result["witness_tuples"])


def test_query_can_reach_no_feasible_design():
    hot = _candidate("A", 1.0, 0, np.eye(2), _observation(1.0, 2, upper=1.0))
    half = _candidate("B", 2.0, 1, 0.5 * np.eye(2), _observation(1.0, 2, upper=1.0))
    result = decide_architecture_query(
        "b-or-none", [hot, half], thermal_limit_k=0.4
    )
    assert result["status"] == NON_IDENTIFIABLE
    assert result["reachable_outcomes"] == ["B", NO_FEASIBLE_DESIGN]


def test_query_and_tuple_replay_apply_candidate_error_margins():
    always_hot = _candidate(
        "A",
        1.0,
        0,
        [[1.0]],
        _observation(1.0, 1, upper=1.0),
        numerical_temperature_error_k=0.1,
    )
    ambiguous = _candidate(
        "B",
        2.0,
        1,
        np.eye(2),
        _observation(1.0, 2, upper=1.0),
        numerical_temperature_error_k=0.1,
    )
    result = decide_architecture_query(
        "error-aware-b-or-none", [always_hot, ambiguous], thermal_limit_k=0.75
    )
    assert result["status"] == NON_IDENTIFIABLE
    assert result["reachable_outcomes"] == ["B", NO_FEASIBLE_DESIGN]
    assert all(item["valid"] for item in result["tuple_replays"])
    assert all(
        replay["decision_margin_k"] == 0.1
        for item in result["tuple_replays"]
        for replay in item["candidate_replays"]
    )


def test_forged_or_stale_tuple_digest_is_rejected():
    candidate_a = _candidate("A", 1.0, 0, np.eye(2), _observation(1.0, 2, upper=1.0))
    candidate_b = _candidate("B", 2.0, 1, np.zeros((2, 2)), _observation(1.0, 2, upper=1.0))
    result = decide_architecture_query(
        "flip-a-b", [candidate_a, candidate_b], thermal_limit_k=0.75
    )
    forged = deepcopy(result["witness_tuples"][0])
    forged["candidates"][0]["power_w"][0] = 9.0
    replay = replay_architecture_tuple(
        [candidate_a, candidate_b], forged, thermal_limit_k=0.75
    )
    assert replay["valid"] is False
    assert "digest" in replay["reason"]


def _run_metadata():
    return {
        "source_commit": "a" * 40,
        "command": ["python3", "run_g2.py", "--registered"],
        "environment": {"python": "3.12", "solver": "HiGHS"},
        "exit_status": 0,
        "wall_time_s": 1.25,
        "peak_rss_kb": 4096,
        "input_files": [
            {"role": "thermal_operator", "path": "inputs/R.npy", "sha256": "0" * 64}
        ],
    }


def test_artifact_is_deterministic_and_replays():
    candidate_a = _candidate("A", 1.0, 0, np.eye(2), _observation(1.0, 2, upper=1.0))
    candidate_b = _candidate("B", 2.0, 1, np.zeros((2, 2)), _observation(1.0, 2, upper=1.0))
    candidates = [candidate_a, candidate_b]
    result = decide_architecture_query("artifact", candidates, thermal_limit_k=0.75)
    first = build_replay_artifact(
        query_id="artifact",
        candidates=candidates,
        thermal_limit_k=0.75,
        result=result,
        run=_run_metadata(),
    )
    second = build_replay_artifact(
        query_id="artifact",
        candidates=candidates,
        thermal_limit_k=0.75,
        result=result,
        run=_run_metadata(),
    )
    assert first == second
    assert replay_artifact(first)["status"] == "PASS"


def test_artifact_tamper_is_rejected_even_if_only_one_number_changes():
    candidate_a = _candidate("A", 1.0, 0, np.eye(2), _observation(1.0, 2, upper=1.0))
    candidate_b = _candidate("B", 2.0, 1, np.zeros((2, 2)), _observation(1.0, 2, upper=1.0))
    candidates = [candidate_a, candidate_b]
    result = decide_architecture_query("artifact", candidates, thermal_limit_k=0.75)
    artifact = build_replay_artifact(
        query_id="artifact",
        candidates=candidates,
        thermal_limit_k=0.75,
        result=result,
        run=_run_metadata(),
    )
    artifact["result"]["candidate_bounds"][0]["result"]["lower_d"] += 0.1
    assert replay_artifact(artifact)["status"] == "INVALID"


def test_sha256_is_stable_and_not_python_process_hash():
    value = {"R": np.eye(2), "names": ["a", "b"]}
    assert canonical_sha256(value) == canonical_sha256(value)
    assert len(canonical_sha256(value)) == 64
    assert canonical_sha256(value) != canonical_sha256({"R": np.zeros((2, 2)), "names": ["a", "b"]})


def _write_bundle(tmp_path: Path, *, evidence_class="synthetic_fixture", provenance=None):
    np.save(tmp_path / "R.npy", np.eye(2), allow_pickle=False)
    (tmp_path / "thermal.json").write_text(
        json.dumps({"T_ambient": 0.0, "blocks": ["a", "b"], "sys_info": [1, 1]}),
        encoding="utf-8",
    )
    observation_record = {
        "schema_version": "certitherm.placed-power-observation.v1",
        "block_names": ["a", "b"],
        "observation": _observation(1.0, 2, upper=1.0),
        "provenance": provenance or {},
    }
    (tmp_path / "observation.json").write_text(
        json.dumps(observation_record), encoding="utf-8"
    )
    spec = {
        "schema_version": "certitherm.g2-query-spec.v2",
        "query_id": "bundle-smoke",
        "thermal_limit_k": 0.75,
        "evidence_class": evidence_class,
        "candidates": [
            {
                "candidate_id": "A",
                "nonthermal_objective": 1.0,
                "tie_break_rank": 0,
                "response_npy": "R.npy",
                "thermal_metadata_json": "thermal.json",
                "observation_json": "observation.json",
                "area_mm2": 1.0,
            }
        ],
    }
    spec_path = tmp_path / "query.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return spec_path


def test_query_bundle_binds_all_input_file_hashes(tmp_path):
    spec_path = _write_bundle(tmp_path)
    query_id, limit, candidates, files = load_query_bundle(spec_path)
    assert query_id == "bundle-smoke"
    assert limit == 0.75
    assert len(candidates) == 1
    assert {entry["role"] for entry in files} == {
        "query_spec",
        "candidate_0_response",
        "candidate_0_thermal_metadata",
        "candidate_0_observation",
    }
    assert all(len(entry["sha256"]) == 64 for entry in files)


def test_physical_bundle_requires_complete_provenance(tmp_path):
    spec_path = _write_bundle(tmp_path, evidence_class="physical_placed_power")
    try:
        load_query_bundle(spec_path)
    except ValueError as exc:
        assert "provenance is missing" in str(exc)
    else:
        raise AssertionError("incomplete physical provenance was accepted")


def test_registered_runner_writes_replayable_artifact_and_receipt(tmp_path):
    spec_path = _write_bundle(tmp_path)
    artifact_path = tmp_path / "out" / "artifact.json"
    receipt_path = tmp_path / "out" / "receipt.json"
    with mock.patch("run_g2_query._git_state", return_value=("a" * 40, False)):
        artifact, receipt = run_registered_query(
            spec_path,
            artifact_path,
            receipt_path,
            repo_root=tmp_path,
            argv=["python3", "run_g2_query.py", "--registered"],
        )
    assert artifact_path.is_file()
    assert receipt_path.is_file()
    assert artifact["run"]["source_commit"] == "a" * 40
    assert receipt["status"] == "PASS"
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["status"] == "PASS"


def test_physical_registry_freezes_order_hashes_and_error_contract():
    registry_path = (
        Path(__file__).resolve().parents[1]
        / "evidence"
        / "g2_placed_power_registry.json"
    )
    registry = _read_registry(registry_path)
    assert [item["candidate_id"] for item in registry["candidates"]] == [
        "snax_gemm_m4_t8",
        "snax_gemm_m2_t8",
    ]
    assert registry["numeric_contract"]["decision_tolerance_k"] == 2e-7
    assert registry["query"]["expected_outcomes"] == [
        "snax_gemm_m2_t8",
        NO_FEASIBLE_DESIGN,
    ]
    assert all(
        len(record["sha256"]) == 64 and not Path(record["filename"]).is_absolute()
        for record in registry["files"].values()
    )


def test_physical_input_hash_mismatch_is_rejected(tmp_path):
    payload = tmp_path / "input.bin"
    payload.write_bytes(b"registered")
    registry = {
        "files": {
            "only": {
                "filename": "input.bin",
                "sha256": "0" * 64,
            }
        }
    }
    try:
        _verify_registered_files(registry, {"only": payload})
    except PhysicalReplayError as exc:
        assert "SHA-256 mismatch" in str(exc)
    else:
        raise AssertionError("tampered registered input was accepted")
