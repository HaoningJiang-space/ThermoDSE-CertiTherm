"""Strong-cut separation PoC: does minimising cut support raise the bound?

D3 pinned the slow bound growth to cut *quality*. The baseline oracle solves a
pure-feasibility LP (objective np.zeros) and takes the MAXIMAL separating set of
an arbitrary collision (support ~24 on arch_b). Dual feasibility caps the
achievable LP bound at L <= C_total / s_min, so a large s_min throttles the
bound regardless of cut count.

This module replaces the zero objective with a weighted-L1 penalty on the
projected action gaps, which drives the colliding pair toward the SAFE/REJECT
boundary where FEWER actions clear the separation tolerance -> smaller support
-> a higher ceiling. It changes only WHICH collision is returned among the
feasible ones; every returned pair is still a genuine collision, so the cut
derived from it (by the UNMODIFIED synthesis.py rule) is still a valid necessary
constraint. Soundness is asserted per cut.

Head-to-head against the baseline on candidate 0 (arch_b of resnet50). Run under
CERTITHERM_LP_WORKERS=1 and a wall budget. NON-CLAIM diagnostic.

Usage:
    python research/triangle/strong_oracle.py <dev-output-dir> <budget_s> [uniform|dual]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import linprog, milp, Bounds, LinearConstraint

sys.path.insert(0, ".")

import CertiTherm.synthesis as syn
from CertiTherm.synthesis import (
    CutLedger,
    _anytime_lower_bound,
    _greedy_cover,
    _insert_minimal_cut,
    _pair_rows,
    _robust_safe_rows,
    run_highs,
)
from CertiTherm.core import CandidateSpace, WorldPair
from CertiTherm.experiments import (
    ROOT, _call_under_budget, _capture, _measurement_costs,
    _ordered_architectures, _power_space, _registry_split, _rows, load_family,
)
from CertiTherm.measurements import build_measurement_library

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "diag150b"
BUDGET_S = float(sys.argv[2]) if len(sys.argv) > 2 else 300.0
WEIGHT_MODE = sys.argv[3] if len(sys.argv) > 3 else "uniform"
WORKLOAD = "resnet50"
MARGIN_K, FEAS_TOL, SEP_TOL = 1e-4, 1e-10, 1e-9


def candidate_zero():
    reg = _registry_split("dev_v3")
    arches = sorted((r for r in _rows(ROOT / "experiments" / "architectures.tsv")
                     if r["split"] == reg), key=lambda r: int(r["rank"]))
    packages = _rows(ROOT / "experiments" / "packages.tsv")
    default_pkg = next(p for p in packages if p["package_id"] == "default")
    workload = next(w for w in _rows(ROOT / "experiments" / "workloads.tsv")
                    if w["split"] == reg and w["workload_id"] == WORKLOAD)
    costs = _measurement_costs()
    caps = {(WORKLOAD, a["architecture_id"]): _capture(a, workload, default_pkg, OUTPUT)
            for a in arches}
    arch0 = _ordered_architectures(WORKLOAD, arches, caps)[0]
    power, blocks, placed, floor = _power_space(caps[(WORKLOAD, arch0["architecture_id"])])
    family, ob = load_family(OUTPUT / "operators" / f"{arch0['architecture_id']}--default.npz")
    assert blocks == ob
    cand = CandidateSpace(arch0["architecture_id"], power, family)
    actions = tuple(build_measurement_library(arch0["architecture_id"], blocks, floor, arch0, costs))
    return cand, actions, arch0["architecture_id"]


def _base_problem(polytope, thermal, actions, selected, margin_k):
    """The common collision-LP matrices, minus objective and reject row.

    Mirrors _collision_search up to the _CollisionProblem, so the feasible set
    is byte-identical to the baseline oracle's. Returns everything needed to
    build both the baseline (zero-objective) and the strong (L1) LP.
    """
    n = polytope.dimension
    a_eq, b_eq, base_a_ub, base_b_ub = _pair_rows(polytope)
    action_rows, action_rhs = [], []
    for index in selected:
        a = actions[index]
        delta = np.concatenate((a.vector, -a.vector))
        action_rows.extend((delta, -delta))
        action_rhs.extend((a.tolerance, a.tolerance))
    robust_rows, robust_rhs = _robust_safe_rows(thermal, margin_k)
    safe_rows = np.hstack((robust_rows, np.zeros_like(robust_rows)))
    chunks, rhs_chunks = [base_a_ub, safe_rows], [base_b_ub, robust_rhs]
    if action_rows:
        chunks.append(np.asarray(action_rows))
        rhs_chunks.append(np.asarray(action_rhs))
    return {
        "n": n,
        "a_eq": a_eq, "b_eq": b_eq,
        "common_a_ub": np.vstack(chunks),
        "common_b_ub": np.concatenate(rhs_chunks),
        "bounds": tuple(zip(polytope.lower_w, polytope.upper_w)) * 2,
        "response": thermal.response_k_per_w,
        "ambient": thermal.ambient_k,
        "error_k": thermal.error_k,
        "limit_k": thermal.limit_k,
        "margin_k": margin_k,
        "model_ids": thermal.model_ids,
    }


def _specs(base):
    r = base["response"]
    return [(m, p) for m in range(r.shape[0]) for p in range(r.shape[1])]


def _reject_row(base, spec):
    m, point = spec
    row = np.concatenate((np.zeros(base["n"]), -base["response"][m, point]))
    rhs = -(base["limit_k"] + base["margin_k"] - base["error_k"][m]
            - base["ambient"][m, point])
    return row, rhs


def strong_collision_spec(base, spec, action_vectors, weights):
    """Collision LP with slack vars s_a >= |v_a . (p_safe - p_unsafe)|,
    minimising sum_a w_a s_a. Same feasible set as baseline (project out s)."""
    n = base["n"]
    m = action_vectors.shape[0]
    reject_row, reject_rhs = _reject_row(base, spec)
    # Extend all existing rows with zero columns for the m slacks.
    a_ub_core = np.vstack((base["common_a_ub"], reject_row))
    b_ub_core = np.append(base["common_b_ub"], reject_rhs)
    a_ub_core = np.hstack((a_ub_core, np.zeros((a_ub_core.shape[0], m))))
    # Slack coupling:  v.p_safe - v.p_unsafe - s <= 0  and the negation.
    V = action_vectors                                  # (m, n)
    pos = np.hstack((V, -V, -np.eye(m)))
    neg = np.hstack((-V, V, -np.eye(m)))
    a_ub = np.vstack((a_ub_core, pos, neg))
    b_ub = np.concatenate((b_ub_core, np.zeros(2 * m)))
    a_eq = np.hstack((base["a_eq"], np.zeros((base["a_eq"].shape[0], m))))
    objective = np.concatenate((np.zeros(2 * n), weights))
    bounds = list(base["bounds"]) + [(0.0, None)] * m
    result = run_highs(
        linprog, objective, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=base["b_eq"],
        bounds=bounds, method="highs", label="strong collision LP",
        options={"primal_feasibility_tolerance": FEAS_TOL,
                 "dual_feasibility_tolerance": FEAS_TOL},
    )
    if result.status == 0:
        return WorldPair(
            safe_power_w=result.x[:n].copy(),
            unsafe_power_w=result.x[n:2 * n].copy(),
            safe_model_id="ROBUST_ENVELOPE",
            unsafe_model_id=base["model_ids"][spec[0]],
            unsafe_point=spec[1],
        )
    if result.status != 2:
        raise RuntimeError(f"strong collision LP unresolved: {result.message}")
    return None


def _cut_from_pair(pair, actions):
    delta = pair.safe_power_w - pair.unsafe_power_w
    return np.asarray(
        [abs(float(a.vector @ delta)) > a.tolerance + SEP_TOL for a in actions],
        dtype=float,
    )


def run_strong_loop(cand, actions, budget_s, weight_mode):
    costs = np.array([a.cost for a in actions], dtype=float)
    action_vectors = np.asarray([a.vector for a in actions], dtype=float)
    cuts, ledger = [], CutLedger()
    masks, selected = [], ()
    latest = {"cuts": []}
    soundness_failures = [0]

    def one_pass():
        base = _base_problem(cand.power, cand.thermal, actions, selected, MARGIN_K)
        # Uniform weights = min-cardinality proxy. Dual weights would come from
        # the master; uniform is the first, simplest test.
        weights = np.ones(len(actions))
        batch = []
        for spec in _specs(base):
            pair = strong_collision_spec(base, spec, action_vectors, weights)
            if pair is not None:
                batch.append(pair)
        return batch

    def step():
        nonlocal selected
        batch = one_pass()
        if not batch:
            return False
        for pair in batch:
            ledger.generated += 1
            cut = _cut_from_pair(pair, actions)
            # SOUNDNESS: the strong pair must yield a valid, non-empty cut under
            # the UNMODIFIED derivation rule.
            if not cut.any():
                soundness_failures[0] += 1
                continue
            if _insert_minimal_cut(cuts, cut, masks, ledger):
                latest["cuts"] = [c.copy() for c in cuts]
        selected = _greedy_cover(costs, cuts)
        return True

    plan, secs, err = _call_under_budget(
        lambda: [step() for _ in range(10_000)], budget_s, f"{budget_s}s budget")
    return latest["cuts"], costs, secs, err, ledger, soundness_failures[0]


def _lp_bound(C, cost):
    n = cost.shape[0]
    r = linprog(cost, A_ub=-C, b_ub=-np.ones(C.shape[0]), bounds=[(0, 1)] * n,
                method="highs")
    return r.fun if r.success else None


def _milp_opt(C, cost):
    n = cost.shape[0]
    m = milp(c=cost, constraints=LinearConstraint(C, lb=np.ones(C.shape[0]), ub=np.inf),
             integrality=np.ones(n), bounds=Bounds(0, 1))
    return m.fun if m.success else None


def main():
    cand, actions, cid = candidate_zero()
    cost = np.array([a.cost for a in actions], dtype=float)
    print(f"candidate 0 = {cid}: {len(actions)} actions, C_total={cost.sum():.0f}, "
          f"weight_mode={WEIGHT_MODE}, budget={BUDGET_S}s")

    cuts, cost, secs, err, ledger, sound_fail = run_strong_loop(
        cand, actions, BUDGET_S, WEIGHT_MODE)
    print(f"ran {secs:.1f}s  antichain={len(cuts)}  generated={ledger.generated}  "
          f"soundness_failures={sound_fail}  err={err[:60]!r}")
    if not cuts:
        print("no cuts"); return
    C = np.asarray(cuts, dtype=float)
    support = C.sum(axis=1)
    print("\n--- STRONG-oracle support |S_e| ---")
    print(f"  min={support.min():.0f}  mean={support.mean():.1f}  "
          f"median={np.median(support):.0f}  max={support.max():.0f}")
    print(f"  ceiling C_total/s_min = {cost.sum()/support.min():.1f}")
    lp = _lp_bound(C, cost)
    mp = _milp_opt(C, cost)
    print(f"\n--- bound over {len(cuts)} strong cuts ---")
    print(f"  LP   = {lp:.3f}")
    print(f"  MILP = {mp:.3f}")
    print(f"\n--- BASELINE reference (D3, zero-objective, 300s/3442 cuts) ---")
    print(f"  LP = 20.1, MILP = 21.0, s_min = 14")
    if lp is not None:
        print(f"\n  strong/baseline LP ratio = {lp/20.1:.2f}x  "
              f"(gate: >= 5x -> green-light freeze-v4)")


if __name__ == "__main__":
    main()
