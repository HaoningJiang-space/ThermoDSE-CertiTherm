"""Closure test: is the MILP cover of the discovered cuts collision-free?

Triangle-1 established, on candidate 0 (arch_b) of resnet50 at 300 s / 3442
cuts: primal LP = _anytime_lower_bound = 20.1, restricted-master MILP = 21.0,
no integrality gap, bound faithful. The reported bound (5.0) lagged only
because of the power-of-two refresh cadence.

MILP over discovered cuts is a valid LOWER bound: C*(arch_b) >= 21. If the MILP
cover is also collision-free under full separation, it is FEASIBLE, hence
C*(arch_b) <= 21, hence C*(arch_b) = 21 exactly -- and the real algorithm's
UNRESOLVED verdict would be a closure it could have reached but its greedy
proposal never did. This script runs that separation check on both the MILP
cover and the greedy cover, and persists the antichain so the analysis can be
re-run without regenerating cuts.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint, linprog

sys.path.insert(0, ".")

import CertiTherm.synthesis as syn
from CertiTherm.experiments import (
    ROOT,
    _call_under_budget,
    _capture,
    _measurement_costs,
    _ordered_architectures,
    _power_space,
    _registry_split,
    _rows,
    load_family,
)
from CertiTherm.core import CandidateSpace
from CertiTherm.measurements import build_measurement_library

SPLIT = "dev_v3"
OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "diag150b"
WORKLOAD = "resnet50"
BUDGET_S = float(sys.argv[2]) if len(sys.argv) > 2 else 300.0
MARGIN_K, FEAS_TOL = 1e-4, 1e-10


def candidate_zero():
    reg = _registry_split(SPLIT)
    arches = sorted((r for r in _rows(ROOT / "experiments" / "architectures.tsv")
                     if r["split"] == reg), key=lambda r: int(r["rank"]))
    packages = _rows(ROOT / "experiments" / "packages.tsv")
    default_pkg = next(p for p in packages if p["package_id"] == "default")
    workloads = [r for r in _rows(ROOT / "experiments" / "workloads.tsv")
                 if r["split"] == reg]
    workload = next(w for w in workloads if w["workload_id"] == WORKLOAD)
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


def separates(cand, actions, selected):
    """True if `selected` leaves NO collision -- i.e. it is feasible."""
    batch = syn._collisions(cand.power, cand.thermal, actions, tuple(selected),
                            MARGIN_K, FEAS_TOL, None)
    return len(batch) == 0, len(batch)


def main():
    cand, actions, cid = candidate_zero()
    n = len(actions)
    cost = np.array([a.cost for a in actions], dtype=float)
    print(f"candidate 0 = {cid}: {n} actions, C_total={cost.sum():.0f}")

    real_insert = syn._insert_minimal_cut
    latest = {"cuts": []}

    def snap(cuts, cut, masks=None, ledger=None):
        r = real_insert(cuts, cut, masks, ledger)
        latest["cuts"] = [c.copy() for c in cuts]
        return r

    syn._insert_minimal_cut = snap
    try:
        plan, secs, err = _call_under_budget(
            lambda: syn.synthesize_minimum_observation(cand.power, cand.thermal, actions),
            BUDGET_S, f"{BUDGET_S}s budget")
    finally:
        syn._insert_minimal_cut = real_insert

    cuts = latest["cuts"]
    print(f"ran {secs:.1f}s status={getattr(plan,'status',err)} antichain={len(cuts)}")
    if not cuts:
        print("no cuts"); return
    C = np.asarray(cuts, dtype=float)
    np.savez_compressed(OUTPUT / "triangle_antichain.npz",
                        cuts=C, costs=cost,
                        action_ids=np.array([a.action_id for a in actions]))

    lp = linprog(cost, A_ub=-C, b_ub=-np.ones(C.shape[0]), bounds=[(0, 1)]*n, method="highs")
    m = milp(c=cost, constraints=LinearConstraint(C, lb=np.ones(C.shape[0]), ub=np.inf),
             integrality=np.ones(n), bounds=Bounds(0, 1))
    print(f"LP={lp.fun:.3f}  MILP={m.fun:.3f}")

    milp_sel = np.flatnonzero(np.round(m.x) > 0.5)
    greedy_sel = syn._greedy_cover(cost, cuts)
    print(f"MILP cover: {len(milp_sel)} actions, cost {cost[milp_sel].sum():.1f}")
    print(f"greedy cover: {len(greedy_sel)} actions, cost {cost[list(greedy_sel)].sum():.1f}")

    print("\n--- closure test: is each cover collision-free under FULL separation? ---")
    t0 = time.perf_counter()
    milp_free, milp_coll = separates(cand, actions, milp_sel)
    print(f"  MILP cover:   collision_free={milp_free}  surviving_collisions={milp_coll}  ({time.perf_counter()-t0:.1f}s)")
    t0 = time.perf_counter()
    greedy_free, greedy_coll = separates(cand, actions, greedy_sel)
    print(f"  greedy cover: collision_free={greedy_free}  surviving_collisions={greedy_coll}  ({time.perf_counter()-t0:.1f}s)")

    print("\n--- verdict ---")
    if milp_free:
        print(f"  MILP cover IS feasible -> C*(arch_b) = {m.fun:.1f} EXACTLY.")
        print(f"  The exact optimum was reachable from the discovered cuts;")
        print(f"  the run stayed UNRESOLVED because its greedy proposal kept colliding.")
    else:
        print(f"  MILP cover still collides ({milp_coll}) -> C*(arch_b) > {m.fun:.1f}; bound still climbing.")
    print(f"  reference: full candidate-0 registry cost = {cost.sum():.0f}")


if __name__ == "__main__":
    main()
