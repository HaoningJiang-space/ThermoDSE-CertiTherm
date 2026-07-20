"""Synthetic software tests for the G3-C frozen baseline module.

These fixtures exercise baseline mechanics and fail-closed behavior only.
They are not G3-C experimental evidence; the claim-grade comparison is
produced by the registered clean-tree runner on the real 2x2x2 bundle.
"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pytest


EXACT_DIR = Path(__file__).resolve().parents[1] / "exact"
sys.path.insert(0, str(EXACT_DIR))

from decision_query import CERTIFIED, NON_IDENTIFIABLE, NO_FEASIBLE_DESIGN
from g3_baselines import (
    FIXED_REFINEMENT,
    G3BaselineError,
    INTERVAL_BOX,
    K_SAMPLE_STRESS,
    UNIFORM_POINT,
    _classify_vs_placed,
    _comparison_fields,
    _sample_domain,
    _seed_for,
    run_fixed_uniform_refinement,
    run_interval_box_aggregate,
    run_k_sample_synthetic_stress,
    run_uniform_aggregate_point,
)


THERMAL_LIMIT = 301.62


def _candidate(candidate_id: str, objective: float, rank: int, placed):
    blocks = [f"{candidate_id}_b0", f"{candidate_id}_b1"]
    placed = np.asarray(placed, dtype=np.float64)
    point = np.full(2, float(np.sum(placed)) / 2.0)
    observation = {
        "A_eq": [[1.0, 1.0]],
        "b_eq": [float(np.sum(placed))],
        "per_block_power": point.tolist(),
        "per_block_lower": [0.0, 0.0],
        "per_block_upper": [0.8 * float(np.sum(placed))] * 2,
    }
    base = {
        "candidate_id": candidate_id,
        "nonthermal_objective": objective,
        "tie_break_rank": rank,
        "response_k_per_w": [[2.0, 1.0], [1.0, 2.0]],
        "ambient_k": [300.0, 300.0],
        "block_names": blocks,
        "sys_info": [1, 1],
    }
    spatial = dict(base, observation=observation)
    point_obs = {
        "per_block_power": point.tolist(),
        "per_block_lower": point.tolist(),
        "per_block_upper": point.tolist(),
    }
    placed_obs = {
        "per_block_power": placed.tolist(),
        "per_block_lower": placed.tolist(),
        "per_block_upper": placed.tolist(),
    }
    return spatial, dict(base, observation=point_obs), dict(base, observation=placed_obs)


def _query():
    spatial_a, point_a, placed_a = _candidate("cand_a", 1.0, 0, [0.4, 0.6])
    spatial_b, point_b, placed_b = _candidate("cand_b", 2.0, 1, [0.5, 0.5])
    return {
        "query_id": "synthetic_q",
        "thermal_limit_k": THERMAL_LIMIT,
        "spatial_candidates": [spatial_a, spatial_b],
        "point_candidates": [point_a, point_b],
        "placed_candidates": [placed_a, placed_b],
    }


def test_sampler_is_power_conserving_and_deterministic():
    query = _query()
    candidate = query["spatial_candidates"][0]
    seed = _seed_for("suite", "q", "cand_a", 8, 123)
    samples = _sample_domain(candidate, 8, np.random.default_rng(seed))
    assert samples.shape == (8, 2)
    assert np.allclose(samples.sum(axis=1), 1.0, atol=1e-9)
    assert np.all(samples >= -1e-12)
    assert np.all(samples <= 0.8 + 1e-9)
    again = _sample_domain(candidate, 8, np.random.default_rng(seed))
    assert np.array_equal(samples, again)
    other = _sample_domain(candidate, 8, np.random.default_rng(seed + 1))
    assert not np.array_equal(samples, other)


def test_sampler_fails_closed_on_non_partition_observation():
    query = _query()
    candidate = query["spatial_candidates"][0]
    broken = dict(candidate)
    broken["observation"] = dict(candidate["observation"])
    broken["observation"]["A_eq"] = [[0.5, 0.5]]
    with pytest.raises(G3BaselineError):
        _sample_domain(broken, 4, np.random.default_rng(0))


def test_uniform_point_selects_first_feasible_in_objective_order():
    query = _query()
    result = run_uniform_aggregate_point("synthetic_q", query, THERMAL_LIMIT)
    assert result["baseline_id"] == UNIFORM_POINT
    assert result["selection"] == "cand_a"
    assert result["commits"] and not result["certified"]
    assert result["physical_query_count"] == 0
    margins = {row["candidate_id"]: row["distance_to_limit_k"] for row in result["per_candidate"]}
    assert margins["cand_a"] > 0.0


def test_k_sample_stress_is_seed_frozen():
    query = _query()
    first = run_k_sample_synthetic_stress(
        "synthetic_q", query, THERMAL_LIMIT, suite_id="suite", k_samples=8, seed_base=7
    )
    second = run_k_sample_synthetic_stress(
        "synthetic_q", query, THERMAL_LIMIT, suite_id="suite", k_samples=8, seed_base=7
    )
    assert first == second
    assert first["baseline_id"] == K_SAMPLE_STRESS
    assert first["synthetic_sample_count"] == 16
    for row in first["per_candidate"]:
        assert row["samples"] == 8
        assert row["violation_count"] <= 8


def test_interval_box_uses_exact_oracle():
    query = _query()
    result = run_interval_box_aggregate("synthetic_q", query, THERMAL_LIMIT)
    assert result["baseline_id"] == INTERVAL_BOX
    assert result["status"] == NON_IDENTIFIABLE
    assert result["selection"] is None
    assert not result["commits"]
    for row in result["per_candidate"]:
        assert row["interval_width_k"] > 0.0


def test_fixed_refinement_not_applicable_when_oracle_certified():
    query = _query()
    result = run_fixed_uniform_refinement(
        "synthetic_q", query, THERMAL_LIMIT, spatial_oracle_status=CERTIFIED
    )
    assert result["status"] == "NOT_APPLICABLE"
    assert result["channel_cost"] == 0


def test_fixed_refinement_certifies_against_placed_outcome():
    query = _query()
    result = run_fixed_uniform_refinement(
        "synthetic_q", query, THERMAL_LIMIT, spatial_oracle_status=NON_IDENTIFIABLE
    )
    assert result["baseline_id"] == FIXED_REFINEMENT
    assert result["status"] == CERTIFIED
    assert result["selection"] == "cand_a"
    assert result["channel_cost"] == 4  # two undetermined blocks per candidate


def test_classify_vs_placed_error_taxonomy():
    assert _classify_vs_placed("cand_a", True, "cand_a")["matches_placed_reference"] is True
    false_safe = _classify_vs_placed("cand_a", True, NO_FEASIBLE_DESIGN)
    assert false_safe["error_class"] == "FALSE_SAFE"
    false_infeasible = _classify_vs_placed(NO_FEASIBLE_DESIGN, True, "cand_a")
    assert false_infeasible["error_class"] == "FALSE_INFEASIBLE"
    wrong_arch = _classify_vs_placed("cand_b", True, "cand_a")
    assert wrong_arch["error_class"] == "WRONG_ARCHITECTURE"
    abstain = _classify_vs_placed(None, False, "cand_a")
    assert abstain["matches_placed_reference"] is None


def test_comparison_fields_strip_runtime_only():
    artifact = {
        "suite_id": "s",
        "parameters": {"k_samples": 4},
        "suite_input": {"path": "x", "sha256": "y"},
        "suite_artifact_sha256": "z",
        "suite_artifact_replay_status": "PASS",
        "baseline_ids": [UNIFORM_POINT],
        "strata": [{"baselines": {UNIFORM_POINT: {"wall_time_s": 1.0, "selection": "a"}}}],
        "aggregate": {UNIFORM_POINT: {"wall_time_s": 1.0, "commit_count": 1}},
    }
    fields = _comparison_fields(artifact)
    assert fields["strata"][0]["baselines"][UNIFORM_POINT] == {"selection": "a"}
    assert fields["aggregate"][UNIFORM_POINT] == {"commit_count": 1}
