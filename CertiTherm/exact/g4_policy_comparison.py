"""Matched acquisition-policy comparison for the CertiTherm G4 empirical gate.

Three policies refine the same physical NON_IDENTIFIABLE G3 queries with the
same registered per-block placed-power channel family and the same cost unit
(one expensive physical query = one appended ``e_i^T p = p_i^placed``
equality):

1. ``fixed_uniform_refinement`` — the frozen G3-C baseline: one-shot full
   placement sensing of every undetermined block on every candidate.
2. ``uncertainty_width_refinement`` — greedy non-adaptive-to-decision policy:
   each round measures the undetermined block with the widest admissible
   per-block interval (exact LP min/max over the current domain).
3. ``decision_witness_directed_refinement`` — greedy EDA-specific policy:
   blocks are ranked by the separation between the two decision-changing
   witness power maps stored in the parent query artifact, so sensing is
   directed at the blocks that carry the architecture decision.

Every policy stops as soon as the complete cross-candidate query is
``CERTIFIED``; correctness requires the certified outcome to equal the
placed-power physical reference outcome.  The gate metric is the expensive
physical-query count at matched correctness and coverage.
"""

from __future__ import annotations

import argparse
import copy
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
from scipy.optimize import linprog

try:
    from .decision_query import CERTIFIED, NON_IDENTIFIABLE, decide_architecture_query
    from .evidence import sha256_file
    from .g3_baselines import run_fixed_uniform_refinement
    from .g3_full_empirical import load_g3_suite, replay_g3_suite_artifact
    from .linear_oracle import UNRESOLVED, canonical_sha256, normalize_problem
except ImportError:  # pragma: no cover - direct script/test-path execution.
    from decision_query import CERTIFIED, NON_IDENTIFIABLE, decide_architecture_query
    from evidence import sha256_file
    from g3_baselines import run_fixed_uniform_refinement
    from g3_full_empirical import load_g3_suite, replay_g3_suite_artifact
    from linear_oracle import UNRESOLVED, canonical_sha256, normalize_problem


COMPARISON_SCHEMA_VERSION = "certitherm.g4-policy-comparison.v1"
REPLAY_SCHEMA_VERSION = "certitherm.g4-policy-comparison-replay.v1"

FIXED_UNIFORM = "fixed_uniform_refinement"
UNCERTAINTY_WIDTH = "uncertainty_width_refinement"
WITNESS_DIRECTED = "decision_witness_directed_refinement"
POLICY_ORDER = (FIXED_UNIFORM, UNCERTAINTY_WIDTH, WITNESS_DIRECTED)

NOT_APPLICABLE = "NOT_APPLICABLE"
NO_FEASIBLE_DESIGN = "NO_FEASIBLE_DESIGN"

_CLAIM_BOUNDARY = (
    "Policy costs are compared inside one registered per-block channel family "
    "under one declared cost model on the physical NON_IDENTIFIABLE G3 "
    "strata. This is not a proof of global policy optimality, universal "
    "resolution for every measurement value, or least-information sensing "
    "outside the registered family."
)


class G4PolicyError(ValueError):
    """Raised when a policy cannot be evaluated without inventing evidence."""


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


def _observation_arrays(
    candidate: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Read (A_eq, b_eq, lower, upper); tolerates appended per-block rows."""

    observation = candidate.get("observation")
    if not isinstance(observation, Mapping):
        raise G4PolicyError("candidate observation must be a mapping")
    n = len(candidate["block_names"])
    a_eq = np.asarray(observation.get("A_eq"), dtype=np.float64)
    b_eq = np.asarray(observation.get("b_eq"), dtype=np.float64)
    lower = np.asarray(observation.get("per_block_lower"), dtype=np.float64)
    upper = np.asarray(observation.get("per_block_upper"), dtype=np.float64)
    if a_eq.ndim != 2 or a_eq.shape[1] != n or b_eq.shape != (a_eq.shape[0],):
        raise G4PolicyError("observation equality shape mismatch")
    if lower.shape != (n,) or upper.shape != (n,):
        raise G4PolicyError("observation bound shape mismatch")
    if np.any(lower < 0.0) or np.any(upper < lower):
        raise G4PolicyError("invalid per-block limits")
    return a_eq, b_eq, lower, upper


def _undetermined_indices(candidate: Mapping[str, Any]) -> list[int]:
    """Frozen baseline rule: blocks in equality rows not pinned by lower bounds."""

    a_eq, b_eq, lower, _upper = _observation_arrays(candidate)
    undetermined: set[int] = set()
    for row in range(a_eq.shape[0]):
        indices = np.flatnonzero(a_eq[row] > 0.0)
        if float(b_eq[row]) > float(np.sum(lower[indices])) + 1e-12:
            undetermined.update(int(i) for i in indices)
    return sorted(undetermined)


def _placed_power_by_id(query: Mapping[str, Any]) -> dict[str, np.ndarray]:
    placed: dict[str, np.ndarray] = {}
    for candidate in query["placed_candidates"]:
        placed[str(candidate["candidate_id"])] = np.asarray(
            candidate["observation"]["per_block_power"], dtype=np.float64
        )
    return placed


def _append_block_equality(
    candidate: Mapping[str, Any], index: int, value: float
) -> dict[str, Any]:
    """Return a candidate copy with one ``e_i^T p = value`` equality appended."""

    a_eq, b_eq, lower, upper = _observation_arrays(candidate)
    row = np.zeros(a_eq.shape[1], dtype=np.float64)
    row[int(index)] = 1.0
    modified = copy.deepcopy(dict(candidate))
    modified["observation"] = {
        "A_eq": np.vstack([a_eq, row]).tolist(),
        "b_eq": np.concatenate([b_eq, [float(value)]]).tolist(),
        "per_block_lower": lower.tolist(),
        "per_block_upper": upper.tolist(),
    }
    return modified


def _query_state(
    query_id: str, candidates: Sequence[Mapping[str, Any]], thermal_limit_k: float
) -> tuple[str, str | None, Mapping[str, Any]]:
    result = decide_architecture_query(query_id, candidates, thermal_limit_k=thermal_limit_k)
    status = str(result.get("status"))
    outcome = result.get("certified_outcome") if status == CERTIFIED else None
    return status, outcome if isinstance(outcome, str) else None, result


def _block_intervals(
    candidate: Mapping[str, Any], indices: Sequence[int]
) -> dict[int, tuple[float, float]]:
    """Exact per-block admissible intervals over the current domain (LP pairs)."""

    problem = normalize_problem(
        candidate.get("response_k_per_w", candidate.get("R")),
        candidate.get("ambient_k", candidate.get("T_ambient")),
        candidate["observation"],
        candidate["block_names"],
    )
    bounds = list(zip(problem.lower_w.tolist(), problem.upper_w.tolist()))
    a_ub = problem.a_ub if problem.a_ub.shape[0] else None
    b_ub = problem.b_ub if problem.a_ub.shape[0] else None
    intervals: dict[int, tuple[float, float]] = {}
    for index in indices:
        direction = np.zeros(problem.dimension, dtype=np.float64)
        direction[int(index)] = 1.0
        values = []
        for sign in (1.0, -1.0):
            try:
                solution = linprog(
                    sign * direction,
                    A_ub=a_ub,
                    b_ub=b_ub,
                    A_eq=problem.a_eq,
                    b_eq=problem.b_eq,
                    bounds=bounds,
                    method="highs",
                )
            except Exception as exc:  # SciPy input/backend failures are fail-closed.
                raise G4PolicyError(f"interval LP failed: {exc}") from exc
            if not solution.success:
                raise G4PolicyError(
                    f"interval LP failed for block {int(index)}: {solution.message}"
                )
            values.append(sign * float(solution.fun))
        intervals[int(index)] = (values[0], values[1])
    return intervals


def _iterative_policy(
    policy_id: str,
    query_id: str,
    query: Mapping[str, Any],
    thermal_limit_k: float,
    *,
    rank_unmeasured: Any,
    spatial_oracle_status: str,
) -> dict[str, Any]:
    """Shared loop for the two greedy per-channel policies."""

    base_record = {
        "policy_id": policy_id,
        "query_id": f"{query_id}::{policy_id}",
        "status": NOT_APPLICABLE,
        "selection": None,
        "commits": False,
        "channel_cost": 0,
        "decide_query_calls": 0,
        "interval_lp_count": 0,
        "rounds": [],
        "failure_reason": None,
    }
    if spatial_oracle_status != NON_IDENTIFIABLE:
        return base_record

    placed_by_id = _placed_power_by_id(query)
    candidates = [copy.deepcopy(dict(c)) for c in query["spatial_candidates"]]
    by_id = {str(c["candidate_id"]): c for c in candidates}
    undetermined = {
        str(c["candidate_id"]): _undetermined_indices(c) for c in query["spatial_candidates"]
    }
    measured: dict[str, set[int]] = {cid: set() for cid in undetermined}
    decide_calls = 1

    status, outcome, _result = _query_state(base_record["query_id"], candidates, thermal_limit_k)

    rounds: list[dict[str, Any]] = []
    while status != CERTIFIED:
        if status == UNRESOLVED:
            return {
                **base_record,
                "status": UNRESOLVED,
                "channel_cost": sum(len(s) for s in measured.values()),
                "decide_query_calls": decide_calls,
                "rounds": rounds,
                "failure_reason": "conditioned query unresolved",
            }
        ranking = rank_unmeasured(by_id, undetermined, measured)
        if not ranking:
            return {
                **base_record,
                "status": status,
                "channel_cost": sum(len(s) for s in measured.values()),
                "decide_query_calls": decide_calls,
                "rounds": rounds,
                "failure_reason": "no further measurable undetermined blocks",
            }
        candidate_id, index, rank_metric = ranking[0]
        placed = placed_by_id.get(candidate_id)
        if placed is None or index >= placed.shape[0]:
            raise G4PolicyError(f"placed power missing for {candidate_id}")
        candidates = [
            _append_block_equality(c, index, placed[index])
            if str(c["candidate_id"]) == candidate_id
            else c
            for c in candidates
        ]
        by_id = {str(c["candidate_id"]): c for c in candidates}
        measured[candidate_id].add(index)
        block_name = str(by_id[candidate_id]["block_names"][index])
        rounds.append(
            {
                "round": len(rounds),
                "candidate_id": candidate_id,
                "block_name": block_name,
                "rank_metric": float(rank_metric),
                "measured_value_w": float(placed[index]),
            }
        )
        status, outcome, _result = _query_state(
            base_record["query_id"], candidates, thermal_limit_k
        )
        decide_calls += 1

    channel_cost = sum(len(s) for s in measured.values())
    return {
        **base_record,
        "status": status,
        "selection": outcome,
        "reachable_outcomes": _result.get("reachable_outcomes"),
        "commits": True,
        "certified": True,
        "channel_cost": int(channel_cost),
        "decide_query_calls": int(decide_calls),
        "rounds": rounds,
        "failure_reason": None,
    }


def run_uncertainty_width_policy(
    query_id: str,
    query: Mapping[str, Any],
    thermal_limit_k: float,
    *,
    spatial_oracle_status: str,
) -> dict[str, Any]:
    """Greedy: measure the widest admissible per-block interval each round."""

    interval_lp_count = 0

    def rank(by_id, undetermined, measured):
        nonlocal interval_lp_count
        best: list[tuple[str, int, float]] = []
        for candidate_id in sorted(by_id):
            remaining = [
                index
                for index in undetermined[candidate_id]
                if index not in measured[candidate_id]
            ]
            if not remaining:
                continue
            intervals = _block_intervals(by_id[candidate_id], remaining)
            interval_lp_count += 2 * len(remaining)
            widths = {
                index: intervals[index][1] - intervals[index][0] for index in remaining
            }
            widest = max(widths.values())
            for index in remaining:
                if widths[index] == widest:
                    block_name = str(by_id[candidate_id]["block_names"][index])
                    best.append((candidate_id, index, widest, block_name))
        if not best:
            return []
        best.sort(key=lambda item: (-item[2], item[0], item[3]))
        first = best[0]
        return [(first[0], first[1], first[2])]

    record = _iterative_policy(
        UNCERTAINTY_WIDTH,
        query_id,
        query,
        thermal_limit_k,
        rank_unmeasured=rank,
        spatial_oracle_status=spatial_oracle_status,
    )
    record["interval_lp_count"] = int(interval_lp_count)
    return record


def run_witness_directed_policy(
    query_id: str,
    query: Mapping[str, Any],
    thermal_limit_k: float,
    *,
    spatial_oracle_status: str,
    witness_tuples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Greedy: measure blocks in decreasing decision-witness separation order."""

    if spatial_oracle_status == NON_IDENTIFIABLE:
        if not isinstance(witness_tuples, Sequence) or len(witness_tuples) < 2:
            raise G4PolicyError("witness-directed policy requires two witness tuples")
        pair = witness_tuples[:2]
        separation: dict[str, np.ndarray] = {}
        for candidate in query["spatial_candidates"]:
            candidate_id = str(candidate["candidate_id"])
            powers = []
            for witness_tuple in pair:
                matches = [
                    entry
                    for entry in witness_tuple.get("candidates", [])
                    if entry.get("candidate_id") == candidate_id
                ]
                if len(matches) != 1:
                    raise G4PolicyError(
                        f"witness pair does not bind {candidate_id} exactly once"
                    )
                powers.append(np.asarray(matches[0]["power_w"], dtype=np.float64))
            separation[candidate_id] = np.abs(powers[0] - powers[1])

        def rank(by_id, undetermined, measured):
            best: list[tuple[str, int, float, str]] = []
            for candidate_id in sorted(by_id):
                for index in undetermined[candidate_id]:
                    if index in measured[candidate_id]:
                        continue
                    block_name = str(by_id[candidate_id]["block_names"][index])
                    best.append(
                        (candidate_id, index, float(separation[candidate_id][index]), block_name)
                    )
            best.sort(key=lambda item: (-item[2], item[0], item[3]))
            return [(item[0], item[1], item[2]) for item in best]

        return _iterative_policy(
            WITNESS_DIRECTED,
            query_id,
            query,
            thermal_limit_k,
            rank_unmeasured=rank,
            spatial_oracle_status=spatial_oracle_status,
        )

    return _iterative_policy(
        WITNESS_DIRECTED,
        query_id,
        query,
        thermal_limit_k,
        rank_unmeasured=lambda by_id, undetermined, measured: [],
        spatial_oracle_status=spatial_oracle_status,
    )


def _classify(selection: str | None, commits: bool, placed_outcome: str) -> dict[str, Any]:
    if not commits or selection is None:
        return {
            "error_class": "NO_COMMITMENT",
            "matches_placed_reference": None,
        }
    if selection == placed_outcome:
        return {"error_class": None, "matches_placed_reference": True}
    return {
        "error_class": (
            "FALSE_INFEASIBLE" if placed_outcome == NO_FEASIBLE_DESIGN else "WRONG_ARCHITECTURE"
        ),
        "matches_placed_reference": False,
    }


def evaluate_g4_policies(
    suite_path: Path,
    suite_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Run all three policies over every NON_IDENTIFIABLE physical stratum."""

    suite_path = suite_path.resolve()
    receipt = replay_g3_suite_artifact(suite_artifact)
    if receipt.get("status") != "PASS":
        raise G4PolicyError(
            f"registered suite artifact failed replay: {receipt.get('reason', 'unknown')}"
        )
    loaded = load_g3_suite(suite_path)
    if loaded["suite_id"] != suite_artifact.get("suite_id"):
        raise G4PolicyError("suite artifact does not bind the supplied suite")

    artifact_entries = {
        entry["query_id"]: entry for entry in suite_artifact.get("entries", [])
    }
    strata: list[dict[str, Any]] = []
    for query in loaded["queries"]:
        query_id = query["query_id"]
        entry = artifact_entries.get(query_id)
        if entry is None:
            raise G4PolicyError(f"suite artifact lacks query {query_id}")
        spatial_result = entry["variants"]["spatial_equivalence"]["result"]
        placed_result = entry["variants"]["placed_reference"]["result"]
        oracle_status = str(spatial_result.get("status"))
        placed_outcome = placed_result.get("certified_outcome")
        if placed_result.get("status") != CERTIFIED or not isinstance(placed_outcome, str):
            raise G4PolicyError(
                f"placed-power reference is not certified for {query_id}"
            )

        started = time.perf_counter()
        fixed = run_fixed_uniform_refinement(
            query_id,
            query,
            query["thermal_limit_k"],
            spatial_oracle_status=oracle_status,
        )
        fixed_wall = time.perf_counter() - started
        fixed["policy_id"] = FIXED_UNIFORM
        fixed["decide_query_calls"] = 1 if fixed.get("status") != NOT_APPLICABLE else 0
        fixed["interval_lp_count"] = 0
        fixed["failure_reason"] = None

        started = time.perf_counter()
        width = run_uncertainty_width_policy(
            query_id,
            query,
            query["thermal_limit_k"],
            spatial_oracle_status=oracle_status,
        )
        width_wall = time.perf_counter() - started

        started = time.perf_counter()
        witness = run_witness_directed_policy(
            query_id,
            query,
            query["thermal_limit_k"],
            spatial_oracle_status=oracle_status,
            witness_tuples=spatial_result.get("witness_tuples", []),
        )
        witness_wall = time.perf_counter() - started

        policies: dict[str, Any] = {}
        for record, wall in (
            (fixed, fixed_wall),
            (width, width_wall),
            (witness, witness_wall),
        ):
            verdict = _classify(
                record.get("selection"), bool(record.get("commits")), placed_outcome
            )
            policies[record["policy_id"]] = {
                **record,
                "wall_time_s": wall,
                **verdict,
            }

        strata.append(
            {
                "query_id": query_id,
                "workload_id": entry.get("workload_id"),
                "package_id": entry.get("package_id"),
                "spatial_oracle_status": oracle_status,
                "placed_power_reference": {
                    "status": placed_result.get("status"),
                    "certified_outcome": placed_outcome,
                },
                "policies": policies,
            }
        )

    applicable = [s for s in strata if s["spatial_oracle_status"] == NON_IDENTIFIABLE]
    matched_correctness = bool(applicable) and all(
        all(
            policies[policy_id].get("matches_placed_reference") is True
            for policy_id in POLICY_ORDER
        )
        for policies in (s["policies"] for s in applicable)
    )
    channel_costs = {
        policy_id: sum(
            int(s["policies"][policy_id].get("channel_cost") or 0) for s in applicable
        )
        for policy_id in POLICY_ORDER
    }
    return _jsonable(
        {
            "schema_version": COMPARISON_SCHEMA_VERSION,
            "suite_id": loaded["suite_id"],
            "suite_artifact_sha256": suite_artifact.get("artifact_sha256"),
            "policy_order": list(POLICY_ORDER),
            "strata": strata,
            "summary": {
                "applicable_strata": len(applicable),
                "matched_correctness_coverage": matched_correctness,
                "channel_cost_totals": channel_costs,
                "claim_boundary": _CLAIM_BOUNDARY,
            },
        }
    )


def _comparison_fields(artifact: Mapping[str, Any]) -> dict[str, Any]:
    def strip_runtime(record: Any) -> Any:
        if isinstance(record, Mapping):
            return {
                key: strip_runtime(value)
                for key, value in record.items()
                if key not in ("wall_time_s", "peak_rss_kb")
            }
        if isinstance(record, list):
            return [strip_runtime(item) for item in record]
        return record

    return {
        key: strip_runtime(value)
        for key, value in artifact.items()
        if key not in ("run", "artifact_sha256", "suite_input")
    }


def replay_policy_comparison(
    artifact: Mapping[str, Any],
    *,
    suite_path: Path,
    suite_artifact: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute the full comparison and fail closed on any semantic drift."""

    def invalid(reason: str) -> dict[str, Any]:
        return {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "status": "INVALID",
            "reason": reason,
        }

    if artifact.get("schema_version") != COMPARISON_SCHEMA_VERSION:
        return invalid("unsupported G4 policy-comparison schema")
    try:
        fresh = evaluate_g4_policies(suite_path, suite_artifact)
    except Exception as exc:
        return invalid(f"fresh G4 policy evaluation failed: {exc}")
    if _comparison_fields(fresh) != _comparison_fields(artifact):
        return invalid("fresh G4 policy semantics differ from the stored artifact")
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "status": "PASS",
        "suite_id": artifact.get("suite_id"),
        "artifact_sha256": artifact.get("artifact_sha256"),
        "applicable_strata": artifact.get("summary", {}).get("applicable_strata"),
        "matched_correctness_coverage": artifact.get("summary", {}).get(
            "matched_correctness_coverage"
        ),
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
    raise G4PolicyError(f"{field} must be outside the Git worktree")


def run_registered_policy_comparison(
    suite_path: Path,
    suite_artifact_path: Path,
    artifact_path: Path,
    receipt_path: Path,
    *,
    repo_root: Path,
    argv: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the G4 policy comparison from a clean tree; external outputs only."""

    _require_external_output(artifact_path, repo_root, "artifact")
    _require_external_output(receipt_path, repo_root, "receipt")
    source_commit, dirty = _git_state(repo_root)
    if dirty:
        raise G4PolicyError("claim-grade G4 runner requires a clean Git worktree")
    suite_path = suite_path.resolve()
    suite_artifact_path = suite_artifact_path.resolve()
    try:
        suite_relative = suite_path.relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise G4PolicyError("suite must live inside the Git worktree") from exc
    suite_artifact = json.loads(suite_artifact_path.read_text(encoding="utf-8"))

    started = time.perf_counter()
    artifact = evaluate_g4_policies(suite_path, suite_artifact)
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
    receipt = replay_policy_comparison(
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
        description="Run the matched G4 acquisition-policy comparison on a registered suite"
    )
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--suite-artifact", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args()
    try:
        artifact, receipt = run_registered_policy_comparison(
            args.suite,
            args.suite_artifact,
            args.artifact,
            args.receipt,
            repo_root=args.repo_root.resolve(),
            argv=[sys.executable, *sys.argv],
        )
    except Exception as exc:
        print(f"G4 policy comparison unresolved: {exc}", file=sys.stderr)
        return 2
    summary = artifact.get("summary", {})
    print(
        f"suite={artifact['suite_id']} replay={receipt.get('status')} "
        f"applicable_strata={summary.get('applicable_strata')} "
        f"matched_coverage={summary.get('matched_correctness_coverage')} "
        f"channels={json.dumps(summary.get('channel_cost_totals'), sort_keys=True)}"
    )
    return 0 if receipt.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
