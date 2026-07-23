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
WORKLOAD = sys.argv[4] if len(sys.argv) > 4 else "resnet50"
CAND_INDEX = int(sys.argv[5]) if len(sys.argv) > 5 else 0
MARGIN_K, FEAS_TOL, SEP_TOL = 1e-4, 1e-10, 1e-9


def candidate_zero():
    """Reconstruct the CAND_INDEX-th candidate (in EDYP order) of WORKLOAD.

    Named candidate_zero for continuity with the triangle scripts; the index is
    now parameterised so the PoC can be replicated across candidates.
    """
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
    arch0 = _ordered_architectures(WORKLOAD, arches, caps)[CAND_INDEX]
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


def _cut_from_pair(pair, actions, selected=()):
    """Cut = true separators (|v.delta| > tolerance) minus already-selected
    actions, matching the PRODUCTION rule (synthesis.py). The old `> tolerance +
    SEP_TOL` was a subset of the true separators (dropped genuine borderline
    separators) and could inflate the hitting-set bound; a selected action
    cannot separate the collision it defined, so it is excluded by index."""
    delta = pair.safe_power_w - pair.unsafe_power_w
    selected_set = set(selected)
    return np.asarray(
        [
            i not in selected_set and abs(float(a.vector @ delta)) > a.tolerance
            for i, a in enumerate(actions)
        ],
        dtype=float,
    )


def _master_dual_weights(cuts, costs):
    """Per-action dual load  w_a = Σ_{e: a separates e} λ_e  from the master LP.

    An action already carrying much dual weight is near its packing constraint
    Σ_{e sep a} y_e ≤ c_a and cannot absorb more, so EXCLUDING it from new cuts
    (a high L1 weight → its gap driven to zero) frees new cuts to load
    unsaturated actions, which is what raises the weak-duality bound. This is the
    dual-guided ("clever objective") cut selection of Codato–Fischetti /
    Magnanti–Wong, expressed as the InfoCertGain numerator (policies.py:272).
    """
    if not cuts:
        return None
    C = np.asarray(cuts, dtype=float)
    r = linprog(costs, A_ub=-C, b_ub=-np.ones(C.shape[0]),
                bounds=[(0.0, 1.0)] * costs.shape[0], method="highs")
    if not r.success or r.ineqlin is None:
        return None
    dual = np.maximum(-np.asarray(r.ineqlin.marginals, dtype=float), 0.0)
    return C.T @ dual                                    # length = n actions


def run_strong_loop(cand, actions, budget_s, weight_mode):
    costs = np.array([a.cost for a in actions], dtype=float)
    action_vectors = np.asarray([a.vector for a in actions], dtype=float)
    cuts, ledger = [], CutLedger()
    masks, selected = [], ()
    latest = {"cuts": []}
    soundness_failures = [0]

    def current_weights():
        # zero = the ORIGINAL feasibility oracle (no support penalty) run through
        # THIS identical harness, so a head-to-head isolates only the objective
        # change (addresses the confound of comparing against a literal recalled
        # from the production driver). uniform = min-cardinality proxy;
        # dual = dual-guided (falls back to uniform until cuts define a master dual).
        if weight_mode == "zero":
            return np.zeros(len(actions))
        if weight_mode == "dual":
            load = _master_dual_weights(cuts, costs)
            if load is not None and load.max() > 0:
                # 1 + normalised dual load: unsaturated actions keep weight ~1
                # (freely included), saturated actions get pushed toward
                # exclusion. The +1 floor keeps every action expressible.
                return 1.0 + load / load.max()
        return np.ones(len(actions))

    def one_pass():
        base = _base_problem(cand.power, cand.thermal, actions, selected, MARGIN_K)
        weights = current_weights()
        batch = []
        for spec in _specs(base):
            pair = strong_collision_spec(base, spec, action_vectors, weights)
            if pair is not None:
                batch.append(pair)
        return batch

    unseparable = [0]

    def step():
        nonlocal selected
        batch = one_pass()
        if not batch:
            return False
        for pair in batch:
            ledger.generated += 1
            cut = _cut_from_pair(pair, actions, selected)
            if not cut.any():
                # NOT a soundness failure of the derivation: an all-zero cut is
                # the UNSYNTHESIZABLE witness -- a pair no registered action
                # separates (production returns UNSYNTHESIZABLE here). The strong
                # objective drives pairs toward minimal separation, so it is more
                # likely to surface one; count it distinctly rather than
                # discarding it silently as a "soundness failure".
                unseparable[0] += 1
                continue
            if _insert_minimal_cut(cuts, cut, masks, ledger):
                latest["cuts"] = [c.copy() for c in cuts]
        selected = _greedy_cover(costs, cuts)
        return True

    plan, secs, err = _call_under_budget(
        lambda: [step() for _ in range(10_000)], budget_s, f"{budget_s}s budget")
    return latest["cuts"], costs, secs, err, ledger, unseparable[0]


def _lp_bound(C, cost):
    """Raw primal linprog.fun -- NOT a certified lower bound (solver tolerance
    can put it above the true optimum). Kept only to show it next to the
    certified bound."""
    n = cost.shape[0]
    r = linprog(cost, A_ub=-C, b_ub=-np.ones(C.shape[0]), bounds=[(0, 1)] * n,
                method="highs")
    return r.fun if r.success else None


def _certified_lp_bound(cuts, cost):
    """Certified weak-duality lower bound, NOT raw linprog.fun.

    `_anytime_lower_bound` evaluates L(y) in exact rational arithmetic with
    directed-downward rounding, so it is valid under solver error; the raw primal
    objective can sit slightly ABOVE the true LP optimum and is not a lower bound
    (synthesis.py documents this). Reused verbatim from production.
    """
    return _anytime_lower_bound(np.asarray(cost, float), list(cuts))


def _milp_lower_bound(C, cost):
    """Return (solver_asserted_milp_dual, gap) -- the HiGHS branch-and-bound DUAL
    bound. This is a SOLVER-ASSERTED diagnostic, NOT a certificate (review F3): the
    v4 certified lower bound comes from the exact-Fraction Lagrangian path
    (`_integer_lagrangian_bound` lattice-lifted), never from this scalar. Uses the
    dual, never the incumbent (`m.fun` can sit ABOVE the true optimum), and returns
    None if the solver did not expose a dual bound -- the incumbent must NOT be
    substituted for a lower bound."""
    n = cost.shape[0]
    m = milp(c=cost, constraints=LinearConstraint(C, lb=np.ones(C.shape[0]), ub=np.inf),
             integrality=np.ones(n), bounds=Bounds(0, 1))
    if not m.success:
        return None, None
    dual = getattr(m, "mip_dual_bound", None)
    if dual is None:
        return None, None            # no dual exposed -> no lower bound (never m.fun)
    return dual, getattr(m, "mip_gap", None)


def main():
    cand, actions, cid = candidate_zero()
    cost = np.array([a.cost for a in actions], dtype=float)
    print(f"candidate 0 = {cid}: {len(actions)} actions, C_total={cost.sum():.0f}, "
          f"weight_mode={WEIGHT_MODE}, budget={BUDGET_S}s")

    cuts, cost, secs, err, ledger, unseparable = run_strong_loop(
        cand, actions, BUDGET_S, WEIGHT_MODE)
    print(f"ran {secs:.1f}s  antichain={len(cuts)}  generated={ledger.generated}  "
          f"unseparable_witnesses={unseparable}  err={err[:60]!r}")
    if unseparable:
        print(f"  NOTE: {unseparable} pairs no action separates (UNSYNTHESIZABLE "
              f"at tolerance) -- the upper bound may not be finite for this candidate.")
    if not cuts:
        print("no cuts"); return
    C = np.asarray(cuts, dtype=float)
    # Persist BEFORE computing bounds, so a bound-side bug never wastes the run.
    np.savez_compressed(OUTPUT / f"strong_antichain_{WEIGHT_MODE}_{WORKLOAD}_c{CAND_INDEX}.npz",
                        cuts=C, costs=np.asarray(cost, float))
    support = C.sum(axis=1)
    print("\n--- support |S_e| ---")
    print(f"  min={support.min():.0f}  mean={support.mean():.1f}  "
          f"median={np.median(support):.0f}  max={support.max():.0f}")
    print(f"  ceiling C_total/s_min = {cost.sum()/support.min():.1f}")
    lp = _certified_lp_bound(cuts, cost)
    milp_lb, gap = _milp_lower_bound(C, cost)
    raw_lp = _lp_bound(C, cost)          # uncertified primal, for reference only
    print(f"\n--- certified bounds over {len(cuts)} cuts (mode={WEIGHT_MODE}) ---")
    print(f"  certified LP lower bound (weak duality) = {lp}")
    print(f"  solver-asserted MILP dual (diagnostic, gap={gap}) = {milp_lb}")
    print(f"  [raw primal linprog.fun, NOT a bound]    = {raw_lp:.3f}")


if __name__ == "__main__":
    main()
