"""G3-C frozen baseline comparison over the real 2x2x2 CertiTherm suite.

The research contract requires the certified spatial-equivalence path to be
compared against four frozen baselines under identical conditions:

1. ``uniform_aggregate_point`` — the original ThermoDSE aggregate/uniform
   path.  Each candidate is judged by its own ThermoDSE point estimate and
   the first thermally feasible candidate in objective order is selected.
   No uncertainty set is propagated and no physical query is issued.
2. ``k_sample_synthetic_stress`` — a corrected K-sample synthetic stress
   test.  Power vectors are sampled uniformly from each candidate's
   registered spatial domain (power-conserving: every sample satisfies the
   group-sum equalities and per-block caps by Dirichlet sampling with
   rejection).  A candidate passes stress only when no sampled peak exceeds
   the thermal limit.  Seeds and K are frozen; a finite sample maximum is
   never a bound.
3. ``interval_box_aggregate`` — the component box/interval bound.  The
   coupled group-sum observations are replaced by one obtainable aggregate
   (total power) equality while the per-block limits and the thermal
   operator are unchanged.  Decisions use the same fail-closed LP oracle,
   so this baseline is a certified but potentially conservative bound.
4. ``fixed_uniform_refinement`` — the non-adaptive acquisition baseline.
   Applicable only where the registered spatial query is NON_IDENTIFIABLE.
   Every undetermined block of every candidate is refined uniformly to its
   exact placed value in one shot (full placement sensing); cost is counted
   in sensor channels (one channel per measured block).  Blocks already
   pinned by zero-sum groups are physically determined and are not counted.

Comparison axes (contract "Primary metrics"): certification coverage,
unjustified commitments against the registered spatial oracle,
false-safe/false-infeasible selections against the placed-power physical
reference, nonthermal objective regret, expensive physical-query count,
wall time, and peak RSS.

The module emits a self-authenticating artifact and a replay receipt.  The
registered runner requires a clean Git worktree and writes raw outputs only
outside the repository, matching the claim-grade G3/G4 convention.
"""

from __future__ import annotations

import argparse
import copy
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
        CERTIFIED,
        NON_IDENTIFIABLE,
        NO_FEASIBLE_DESIGN,
        decide_architecture_query,
    )
    from .evidence import sha256_file
    from .g3_full_empirical import load_g3_suite, replay_g3_suite_artifact
    from .linear_oracle import canonical_sha256
except ImportError:  # pragma: no cover - direct script/test-path execution.
    from decision_query import (
        CERTIFIED,
        NON_IDENTIFIABLE,
        NO_FEASIBLE_DESIGN,
        decide_architecture_query,
    )
    from evidence import sha256_file
    from g3_full_empirical import load_g3_suite, replay_g3_suite_artifact
    from linear_oracle import canonical_sha256


BASELINE_SCHEMA_VERSION = "certitherm.g3-baseline-comparison.v1"
BASELINE_REPLAY_SCHEMA_VERSION = "certitherm.g3-baseline-comparison-replay.v1"

UNIFORM_POINT = "uniform_aggregate_point"
K_SAMPLE_STRESS = "k_sample_synthetic_stress"
INTERVAL_BOX = "interval_box_aggregate"
FIXED_REFINEMENT = "fixed_uniform_refinement"
BASELINE_IDS = (UNIFORM_POINT, K_SAMPLE_STRESS, INTERVAL_BOX, FIXED_REFINEMENT)

DEFAULT_K_SAMPLES = 64
DEFAULT_SEED_BASE = 20260720
MAX_REJECTION_DRAWS = 200_000
FEASIBILITY_TOL_K = 1e-7

NOT_APPLICABLE = "NOT_APPLICABLE"
UNRESOLVED = "UNRESOLVED"

_CLAIM_BOUNDARY = (
    "Baseline rows are frozen comparison procedures evaluated on the "
    "registered G3 suite. uniform_aggregate_point and k_sample_synthetic_stress "
    "commit without a certificate; only interval_box_aggregate and the "
    "registered spatial path return bounds. A finite sample maximum is never "
    "a bound, and a clean-tree baseline artifact is not itself a G3-C closure "
    "claim without the companion systems-cost table."
)


class G3BaselineError(ValueError):
    """Raised when a baseline cannot be evaluated without inventing evidence."""


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


def _objective_order(candidates: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        candidates,
        key=lambda item: (float(item["nonthermal_objective"]), int(item["tie_break_rank"])),
    )


def _group_structure(candidate: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (A_eq, b_eq, lower, upper) after verifying the partition contract."""

    observation = candidate.get("observation")
    if not isinstance(observation, Mapping):
        raise G3BaselineError("candidate observation must be a mapping")
    n = len(candidate["block_names"])
    a_eq = np.asarray(observation.get("A_eq"), dtype=np.float64)
    b_eq = np.asarray(observation.get("b_eq"), dtype=np.float64)
    lower = np.asarray(observation.get("per_block_lower"), dtype=np.float64)
    upper = np.asarray(observation.get("per_block_upper"), dtype=np.float64)
    if a_eq.ndim != 2 or a_eq.shape[1] != n or b_eq.shape != (a_eq.shape[0],):
        raise G3BaselineError("spatial observation equality shape mismatch")
    if lower.shape != (n,) or upper.shape != (n,):
        raise G3BaselineError("spatial observation bound shape mismatch")
    if not np.all((a_eq == 0.0) | (a_eq == 1.0)):
        raise G3BaselineError("k-sample stress requires 0/1 group observations")
    if not np.all(a_eq.sum(axis=0) == 1.0):
        raise G3BaselineError("k-sample stress requires a block partition")
    if np.any(lower < 0.0) or np.any(upper < lower):
        raise G3BaselineError("invalid per-block limits")
    return a_eq, b_eq, lower, upper


def _seed_for(suite_id: str, query_id: str, candidate_id: str, k_samples: int, seed_base: int) -> int:
    label = f"certitherm-g3c-ksample|{suite_id}|{query_id}|{candidate_id}|K={k_samples}|base={seed_base}"
    return int.from_bytes(hashlib.sha256(label.encode("utf-8")).digest()[:8], "big")


def _sample_domain(
    candidate: Mapping[str, Any],
    k_samples: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Uniform samples from the registered domain via capped-simplex rejection."""

    a_eq, b_eq, lower, upper = _group_structure(candidate)
    n = a_eq.shape[1]
    samples = np.zeros((k_samples, n), dtype=np.float64)
    draws = 0
    for row in range(a_eq.shape[0]):
        indices = np.flatnonzero(a_eq[row] > 0.0)
        total = float(b_eq[row])
        floor = lower[indices]
        if total < float(np.sum(floor)) - 1e-9:
            raise G3BaselineError("group sum is below the registered block floors")
        if total <= float(np.sum(floor)) + 1e-12:
            # Zero-sum (or floor-pinned) group: physically determined.
            samples[:, indices] = floor
            continue
        span = total - float(np.sum(floor))
        caps = upper[indices] - floor
        accepted = 0
        while accepted < k_samples:
            draws += 1
            if draws > MAX_REJECTION_DRAWS:
                raise G3BaselineError(
                    "rejection sampler exceeded the frozen draw budget "
                    f"({MAX_REJECTION_DRAWS}) on group row {row}"
                )
            proposal = rng.dirichlet(np.ones(len(indices))) * span
            if np.all(proposal <= caps + 1e-9):
                samples[accepted, indices] = floor + proposal
                accepted += 1
    return samples


def _peak_temperature(candidate: Mapping[str, Any], power: np.ndarray) -> float:
    response = np.asarray(candidate.get("response_k_per_w", candidate.get("R")), dtype=np.float64)
    ambient = np.asarray(candidate.get("ambient_k", candidate.get("T_ambient")), dtype=np.float64)
    return float(np.max(ambient + response @ power))


def run_uniform_aggregate_point(
    query_id: str,
    query: Mapping[str, Any],
    thermal_limit_k: float,
) -> dict[str, Any]:
    """Baseline 1: the deployed ThermoDSE point-estimate path."""

    per_candidate = []
    selection = NO_FEASIBLE_DESIGN
    for candidate in _objective_order(query["point_candidates"]):
        point = np.asarray(candidate["observation"]["per_block_power"], dtype=np.float64)
        peak = _peak_temperature(candidate, point)
        feasible = bool(peak <= thermal_limit_k + FEASIBILITY_TOL_K)
        per_candidate.append(
            {
                "candidate_id": candidate["candidate_id"],
                "point_peak_temperature_k": peak,
                "distance_to_limit_k": thermal_limit_k - peak,
                "declared_feasible": feasible,
            }
        )
        if selection == NO_FEASIBLE_DESIGN and feasible:
            selection = str(candidate["candidate_id"])
    return {
        "baseline_id": UNIFORM_POINT,
        "query_id": f"{query_id}::{UNIFORM_POINT}",
        "selection": selection,
        "commits": True,
        "certified": False,
        "physical_query_count": 0,
        "per_candidate": per_candidate,
    }


def run_k_sample_synthetic_stress(
    query_id: str,
    query: Mapping[str, Any],
    thermal_limit_k: float,
    *,
    suite_id: str,
    k_samples: int,
    seed_base: int,
) -> dict[str, Any]:
    """Baseline 2: corrected power-conserving K-sample stress (never a bound)."""

    per_candidate = []
    selection = NO_FEASIBLE_DESIGN
    for candidate in _objective_order(query["spatial_candidates"]):
        candidate_id = str(candidate["candidate_id"])
        seed = _seed_for(suite_id, query_id, candidate_id, k_samples, seed_base)
        rng = np.random.default_rng(seed)
        samples = _sample_domain(candidate, k_samples, rng)
        peaks = np.asarray([_peak_temperature(candidate, row) for row in samples])
        violations = int(np.count_nonzero(peaks > thermal_limit_k + FEASIBILITY_TOL_K))
        stress_pass = violations == 0
        per_candidate.append(
            {
                "candidate_id": candidate_id,
                "seed": seed,
                "samples": int(k_samples),
                "violation_count": violations,
                "max_sampled_peak_k": float(np.max(peaks)),
                "distance_to_limit_k": thermal_limit_k - float(np.max(peaks)),
                "stress_pass": bool(stress_pass),
            }
        )
        if selection == NO_FEASIBLE_DESIGN and stress_pass:
            selection = candidate_id
    return {
        "baseline_id": K_SAMPLE_STRESS,
        "query_id": f"{query_id}::{K_SAMPLE_STRESS}",
        "selection": selection,
        "commits": True,
        "certified": False,
        "physical_query_count": 0,
        "synthetic_sample_count": int(k_samples) * len(query["spatial_candidates"]),
        "k_samples": int(k_samples),
        "per_candidate": per_candidate,
    }


def run_interval_box_aggregate(
    query_id: str,
    query: Mapping[str, Any],
    thermal_limit_k: float,
) -> dict[str, Any]:
    """Baseline 3: certified box/interval bound with one aggregate sum row."""

    boxed: list[dict[str, Any]] = []
    for candidate in query["spatial_candidates"]:
        a_eq, b_eq, lower, upper = _group_structure(candidate)
        modified = copy.deepcopy(dict(candidate))
        modified["observation"] = {
            "A_eq": np.ones((1, a_eq.shape[1]), dtype=np.float64).tolist(),
            "b_eq": [float(np.sum(b_eq))],
            "per_block_lower": lower.tolist(),
            "per_block_upper": upper.tolist(),
        }
        boxed.append(modified)
    result = decide_architecture_query(
        f"{query_id}::{INTERVAL_BOX}", boxed, thermal_limit_k=thermal_limit_k
    )
    per_candidate = []
    for bound in result.get("candidate_bounds", []):
        candidate_result = bound.get("result", {})
        width = None
        if candidate_result.get("lower_d") is not None and candidate_result.get("upper_d") is not None:
            width = float(candidate_result["upper_d"]) - float(candidate_result["lower_d"])
        per_candidate.append(
            {
                "candidate_id": bound.get("candidate_id"),
                "status": candidate_result.get("status"),
                "lower_d": candidate_result.get("lower_d"),
                "upper_d": candidate_result.get("upper_d"),
                "interval_width_k": width,
            }
        )
    return {
        "baseline_id": INTERVAL_BOX,
        "query_id": f"{query_id}::{INTERVAL_BOX}",
        "status": result.get("status"),
        "selection": result.get("certified_outcome") if result.get("status") == CERTIFIED else None,
        "reachable_outcomes": result.get("reachable_outcomes"),
        "commits": result.get("status") == CERTIFIED,
        "certified": result.get("status") == CERTIFIED,
        "physical_query_count": 0,
        "per_candidate": per_candidate,
    }


def run_fixed_uniform_refinement(
    query_id: str,
    query: Mapping[str, Any],
    thermal_limit_k: float,
    *,
    spatial_oracle_status: str,
) -> dict[str, Any]:
    """Baseline 4: one-shot uniform refinement to full placement sensing."""

    if spatial_oracle_status != NON_IDENTIFIABLE:
        return {
            "baseline_id": FIXED_REFINEMENT,
            "query_id": f"{query_id}::{FIXED_REFINEMENT}",
            "status": NOT_APPLICABLE,
            "selection": None,
            "commits": False,
            "certified": False,
            "physical_query_count": 0,
            "channel_cost": 0,
            "per_candidate": [],
        }

    placed_by_id = {
        str(candidate["candidate_id"]): np.asarray(
            candidate["observation"]["per_block_power"], dtype=np.float64
        )
        for candidate in query["placed_candidates"]
    }
    refined: list[dict[str, Any]] = []
    per_candidate = []
    channel_cost = 0
    for candidate in query["spatial_candidates"]:
        candidate_id = str(candidate["candidate_id"])
        a_eq, b_eq, lower, upper = _group_structure(candidate)
        placed = placed_by_id.get(candidate_id)
        if placed is None or placed.shape != (a_eq.shape[1],):
            raise G3BaselineError(f"placed power missing for {candidate_id}")
        undetermined: list[int] = []
        for row in range(a_eq.shape[0]):
            indices = np.flatnonzero(a_eq[row] > 0.0)
            if float(b_eq[row]) > float(np.sum(lower[indices])) + 1e-12:
                undetermined.extend(int(i) for i in indices)
        new_a = [row.tolist() for row in a_eq]
        new_b = [float(v) for v in b_eq]
        for index in sorted(undetermined):
            row = np.zeros(a_eq.shape[1], dtype=np.float64)
            row[index] = 1.0
            new_a.append(row.tolist())
            new_b.append(float(placed[index]))
        modified = copy.deepcopy(dict(candidate))
        modified["observation"] = {
            "A_eq": new_a,
            "b_eq": new_b,
            "per_block_lower": lower.tolist(),
            "per_block_upper": upper.tolist(),
        }
        refined.append(modified)
        channel_cost += len(undetermined)
        per_candidate.append(
            {
                "candidate_id": candidate_id,
                "measured_blocks": len(undetermined),
            }
        )
    result = decide_architecture_query(
        f"{query_id}::{FIXED_REFINEMENT}", refined, thermal_limit_k=thermal_limit_k
    )
    return {
        "baseline_id": FIXED_REFINEMENT,
        "query_id": f"{query_id}::{FIXED_REFINEMENT}",
        "status": result.get("status"),
        "selection": result.get("certified_outcome") if result.get("status") == CERTIFIED else None,
        "reachable_outcomes": result.get("reachable_outcomes"),
        "commits": result.get("status") == CERTIFIED,
        "certified": result.get("status") == CERTIFIED,
        "physical_query_count": int(channel_cost),
        "channel_cost": int(channel_cost),
        "per_candidate": per_candidate,
    }


def _classify_vs_placed(selection: str | None, commits: bool, placed_outcome: str) -> dict[str, Any]:
    """False-safe / false-infeasible / regret against the physical reference."""

    if not commits or selection is None:
        return {
            "matches_placed_reference": None,
            "error_class": None,
            "objective_regret": None,
        }
    if selection == placed_outcome:
        return {
            "matches_placed_reference": True,
            "error_class": None,
            "objective_regret": 0.0,
        }
    if selection == NO_FEASIBLE_DESIGN:
        error_class = "FALSE_INFEASIBLE"
    elif placed_outcome == NO_FEASIBLE_DESIGN:
        error_class = "FALSE_SAFE"
    else:
        error_class = "WRONG_ARCHITECTURE"
    return {
        "matches_placed_reference": False,
        "error_class": error_class,
        "objective_regret": None,
    }


def evaluate_g3_baselines(
    suite_path: Path,
    suite_artifact: Mapping[str, Any],
    *,
    k_samples: int = DEFAULT_K_SAMPLES,
    seed_base: int = DEFAULT_SEED_BASE,
) -> dict[str, Any]:
    """Run every frozen baseline over every registered stratum."""

    suite_path = suite_path.resolve()
    receipt = replay_g3_suite_artifact(suite_artifact)
    if receipt.get("status") != "PASS":
        raise G3BaselineError(
            f"registered suite artifact failed replay: {receipt.get('reason', 'unknown')}"
        )
    loaded = load_g3_suite(suite_path)
    if loaded["suite_id"] != suite_artifact.get("suite_id"):
        raise G3BaselineError("suite artifact does not bind the supplied suite")

    artifact_entries = {
        entry["query_id"]: entry for entry in suite_artifact.get("entries", [])
    }
    strata: list[dict[str, Any]] = []
    for query in loaded["queries"]:
        query_id = query["query_id"]
        entry = artifact_entries.get(query_id)
        if entry is None:
            raise G3BaselineError(f"suite artifact lacks query {query_id}")
        spatial_result = entry["variants"]["spatial_equivalence"]["result"]
        placed_result = entry["variants"]["placed_reference"]["result"]
        point_result = entry["variants"]["point_estimate"]["result"]
        oracle_status = spatial_result.get("status")
        placed_outcome = placed_result.get("certified_outcome")
        if placed_result.get("status") != CERTIFIED or not isinstance(placed_outcome, str):
            raise G3BaselineError(
                f"placed-power reference is not certified for {query_id}; "
                "no physical reference outcome is available"
            )

        started = time.perf_counter()
        uniform = run_uniform_aggregate_point(query_id, query, query["thermal_limit_k"])
        uniform_wall = time.perf_counter() - started

        started = time.perf_counter()
        ksample = run_k_sample_synthetic_stress(
            query_id,
            query,
            query["thermal_limit_k"],
            suite_id=loaded["suite_id"],
            k_samples=k_samples,
            seed_base=seed_base,
        )
        ksample_wall = time.perf_counter() - started

        started = time.perf_counter()
        interval = run_interval_box_aggregate(query_id, query, query["thermal_limit_k"])
        interval_wall = time.perf_counter() - started

        started = time.perf_counter()
        refinement = run_fixed_uniform_refinement(
            query_id,
            query,
            query["thermal_limit_k"],
            spatial_oracle_status=str(oracle_status),
        )
        refinement_wall = time.perf_counter() - started

        # Fairness cross-check: the recomputed deployed path must reproduce the
        # registered point-estimate variant (identical arch set, objectives,
        # thermal limit, and backend operator).
        point_outcome = point_result.get("certified_outcome")
        fairness_point_matches = bool(
            point_result.get("status") == CERTIFIED and uniform["selection"] == point_outcome
        )

        baselines: dict[str, Any] = {}
        for record, wall in (
            (uniform, uniform_wall),
            (ksample, ksample_wall),
            (interval, interval_wall),
            (refinement, refinement_wall),
        ):
            selection = record.get("selection")
            commits = bool(record.get("commits"))
            verdict = _classify_vs_placed(selection, commits, placed_outcome)
            if (
                verdict["matches_placed_reference"] is False
                and verdict["error_class"] == "WRONG_ARCHITECTURE"
                and selection is not None
            ):
                objectives = {
                    str(candidate["candidate_id"]): float(candidate["nonthermal_objective"])
                    for candidate in query["spatial_candidates"]
                }
                verdict["objective_regret"] = objectives[selection] - objectives[placed_outcome]
            unjustified = bool(commits and oracle_status == NON_IDENTIFIABLE)
            baselines[record["baseline_id"]] = {
                **record,
                "wall_time_s": wall,
                "unjustified_commitment_vs_spatial_oracle": unjustified,
                **verdict,
            }

        spatial_widths = {}
        for bound in spatial_result.get("candidate_bounds", []):
            candidate_result = bound.get("result", {})
            if candidate_result.get("lower_d") is not None and candidate_result.get("upper_d") is not None:
                spatial_widths[bound.get("candidate_id")] = float(
                    candidate_result["upper_d"]
                ) - float(candidate_result["lower_d"])
        strata.append(
            {
                "query_id": query_id,
                "workload_family": query["workload_family"],
                "package_id": query["package_id"],
                "thermal_limit_k": query["thermal_limit_k"],
                "spatial_oracle": {
                    "status": oracle_status,
                    "reachable_outcomes": spatial_result.get("reachable_outcomes"),
                    "certified_outcome": spatial_result.get("certified_outcome"),
                    "interval_width_k": spatial_widths,
                },
                "placed_power_reference": {
                    "status": placed_result.get("status"),
                    "certified_outcome": placed_outcome,
                },
                "point_estimate_variant": {
                    "status": point_result.get("status"),
                    "certified_outcome": point_outcome,
                },
                "fairness_point_path_matches_registered_variant": fairness_point_matches,
                "baselines": baselines,
            }
        )

    aggregate: dict[str, Any] = {}
    for baseline_id in BASELINE_IDS:
        rows = [stratum["baselines"][baseline_id] for stratum in strata]
        applicable = [row for row in rows if row.get("status") != NOT_APPLICABLE]
        committed = [row for row in rows if row.get("commits")]
        errors = [
            row["error_class"] for row in rows if row.get("error_class") is not None
        ]
        regrets = [
            float(row["objective_regret"])
            for row in rows
            if row.get("objective_regret") is not None
        ]
        aggregate[baseline_id] = {
            "stratum_count": len(rows),
            "applicable_count": len(applicable),
            "commit_count": len(committed),
            "certified_commit_count": sum(1 for row in rows if row.get("certified")),
            "unjustified_commitment_count": sum(
                1 for row in rows if row.get("unjustified_commitment_vs_spatial_oracle")
            ),
            "false_safe_count": errors.count("FALSE_SAFE"),
            "false_infeasible_count": errors.count("FALSE_INFEASIBLE"),
            "wrong_architecture_count": errors.count("WRONG_ARCHITECTURE"),
            "placed_reference_agreement_count": sum(
                1 for row in rows if row.get("matches_placed_reference") is True
            ),
            "total_objective_regret": float(np.sum(regrets)) if regrets else 0.0,
            "physical_query_count": sum(int(row.get("physical_query_count", 0)) for row in rows),
            "synthetic_sample_count": sum(
                int(row.get("synthetic_sample_count", 0)) for row in rows
            ),
            "wall_time_s": float(np.sum([row["wall_time_s"] for row in rows])),
        }

    content = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "suite_id": loaded["suite_id"],
        "parameters": {
            "k_samples": int(k_samples),
            "seed_base": int(seed_base),
            "max_rejection_draws": MAX_REJECTION_DRAWS,
            "feasibility_tolerance_k": FEASIBILITY_TOL_K,
        },
        "suite_input": {
            "path": None,  # filled by the registered runner
            "sha256": sha256_file(suite_path),
        },
        "suite_artifact_sha256": suite_artifact.get("artifact_sha256"),
        "suite_artifact_replay_status": receipt.get("status"),
        "baseline_ids": list(BASELINE_IDS),
        "strata": strata,
        "aggregate": aggregate,
        "claim_boundary": _CLAIM_BOUNDARY,
    }
    return _jsonable(content)


def _comparison_fields(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic fields that a fresh replay must reproduce exactly."""

    def strip_runtime(record: Any) -> Any:
        if isinstance(record, Mapping):
            return {
                key: strip_runtime(value)
                for key, value in record.items()
                if key not in ("wall_time_s",)
            }
        if isinstance(record, list):
            return [strip_runtime(item) for item in record]
        return record

    return {
        "suite_id": artifact.get("suite_id"),
        "parameters": artifact.get("parameters"),
        "suite_input": artifact.get("suite_input"),
        "suite_artifact_sha256": artifact.get("suite_artifact_sha256"),
        "suite_artifact_replay_status": artifact.get("suite_artifact_replay_status"),
        "baseline_ids": artifact.get("baseline_ids"),
        "strata": strip_runtime(artifact.get("strata")),
        "aggregate": strip_runtime(artifact.get("aggregate")),
    }


def replay_baseline_comparison(
    artifact: Mapping[str, Any],
    *,
    suite_path: Path,
    suite_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute every baseline from the content-bound bundle and compare."""

    def invalid(reason: str) -> dict[str, Any]:
        return {
            "schema_version": BASELINE_REPLAY_SCHEMA_VERSION,
            "status": "INVALID",
            "reason": reason,
        }

    if artifact.get("schema_version") != BASELINE_SCHEMA_VERSION:
        return invalid("unsupported G3 baseline-comparison schema")
    if artifact.get("artifact_sha256") != canonical_sha256(
        {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    ):
        return invalid("baseline artifact digest mismatch")
    suite_path = suite_path.resolve()
    if sha256_file(suite_path) != artifact.get("suite_input", {}).get("sha256"):
        return invalid("suite input digest mismatch")
    parameters = artifact.get("parameters", {})
    try:
        fresh = evaluate_g3_baselines(
            suite_path,
            suite_artifact,
            k_samples=int(parameters.get("k_samples", DEFAULT_K_SAMPLES)),
            seed_base=int(parameters.get("seed_base", DEFAULT_SEED_BASE)),
        )
    except (G3BaselineError, KeyError, TypeError, ValueError) as exc:
        return invalid(f"fresh baseline evaluation failed: {exc}")
    fresh["suite_input"] = artifact.get("suite_input")
    if _comparison_fields(fresh) != _comparison_fields(artifact):
        return invalid("fresh baseline semantics differ from the stored artifact")
    return {
        "schema_version": BASELINE_REPLAY_SCHEMA_VERSION,
        "status": "PASS",
        "artifact_sha256": artifact.get("artifact_sha256"),
        "stratum_count": len(artifact.get("strata", [])),
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
    raise G3BaselineError(f"{field} must be outside the Git worktree")


def run_registered_baselines(
    suite_path: Path,
    suite_artifact_path: Path,
    artifact_path: Path,
    receipt_path: Path,
    *,
    repo_root: Path,
    argv: Sequence[str],
    k_samples: int = DEFAULT_K_SAMPLES,
    seed_base: int = DEFAULT_SEED_BASE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the frozen baselines from a clean tree; write only external outputs."""

    _require_external_output(artifact_path, repo_root, "artifact")
    _require_external_output(receipt_path, repo_root, "receipt")
    source_commit, dirty = _git_state(repo_root)
    if dirty:
        raise G3BaselineError("claim-grade G3-C runner requires a clean Git worktree")
    suite_path = suite_path.resolve()
    suite_artifact_path = suite_artifact_path.resolve()
    try:
        suite_relative = suite_path.relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise G3BaselineError("suite must live inside the Git worktree") from exc
    suite_artifact = json.loads(suite_artifact_path.read_text(encoding="utf-8"))

    started = time.perf_counter()
    artifact = evaluate_g3_baselines(
        suite_path,
        suite_artifact,
        k_samples=k_samples,
        seed_base=seed_base,
    )
    wall_time = time.perf_counter() - started
    artifact["suite_input"] = {
        "path": suite_relative,
        "sha256": sha256_file(suite_path),
    }
    artifact["run"] = {
        "source_commit": source_commit,
        "command": list(argv),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "hostname": platform.node(),
        },
        "exit_status": 0,
        "wall_time_s": wall_time,
        "peak_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        "input_files": [
            {
                "role": "g3_suite",
                "path": suite_relative,
                "sha256": sha256_file(suite_path),
            },
            {
                "role": "g3_suite_artifact",
                "path": f"external/{suite_artifact_path.name}",
                "sha256": sha256_file(suite_artifact_path),
            },
        ],
    }
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    receipt = replay_baseline_comparison(
        artifact,
        suite_path=suite_path,
        suite_artifact=suite_artifact,
    )
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
        description="Run the frozen G3-C baseline comparison on a registered suite"
    )
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--suite-artifact", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--k-samples", type=int, default=DEFAULT_K_SAMPLES)
    parser.add_argument("--seed-base", type=int, default=DEFAULT_SEED_BASE)
    args = parser.parse_args()
    if args.k_samples <= 0:
        print("G3-C baselines unresolved: --k-samples must be positive", file=sys.stderr)
        return 2
    try:
        artifact, receipt = run_registered_baselines(
            args.suite,
            args.suite_artifact,
            args.artifact,
            args.receipt,
            repo_root=args.repo_root.resolve(),
            argv=[sys.executable, *sys.argv],
            k_samples=args.k_samples,
            seed_base=args.seed_base,
        )
    except Exception as exc:
        print(f"G3-C baselines unresolved: {exc}", file=sys.stderr)
        return 2
    print(
        f"suite={artifact['suite_id']} replay={receipt.get('status')} "
        f"strata={len(artifact['strata'])}"
    )
    return 0 if receipt.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
