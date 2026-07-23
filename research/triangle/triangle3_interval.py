"""Bound the interval for candidate 0: synthesizable at all, and how fast the
bound scales with discovered cuts.

Triangle-2: at 300 s / 3442 cuts the cheapest cover of discovered cuts (21)
still leaves 638 collisions, so C*(arch_b) > 21 and is unknown within (21, 1846].
Two questions decide whether that interval can ever close:

1. Does the FULL 243-action library separate candidate 0? If it collides, no
   plan exists (UNSYNTHESIZABLE) and the minimum-cost question is moot. If it
   is collision-free, 1846 is a valid upper bound and a finite C* exists.

2. How does the LP bound scale with the number of cuts? Computed over nested
   random subsets of the persisted antichain -- not chronological, so read as
   scaling-with-count, not a time series.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, ".")

import CertiTherm.synthesis as syn
from CertiTherm.experiments import (
    ROOT, _capture, _measurement_costs, _ordered_architectures,
    _power_space, _registry_split, _rows, load_family,
)
from CertiTherm.core import CandidateSpace
from CertiTherm.measurements import build_measurement_library

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "diag150b"
WORKLOAD = "resnet50"
MARGIN_K, FEAS_TOL = 1e-4, 1e-10


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


def lp_bound(C, cost):
    n = cost.shape[0]
    r = linprog(cost, A_ub=-C, b_ub=-np.ones(C.shape[0]), bounds=[(0, 1)]*n, method="highs")
    return r.fun if r.success else None


def main():
    cand, actions, cid = candidate_zero()
    n = len(actions)
    cost = np.array([a.cost for a in actions], dtype=float)

    print(f"candidate 0 = {cid}: {n} actions, C_total={cost.sum():.0f}")
    print("\n--- Q1: does the FULL library separate candidate 0? ---")
    t0 = time.perf_counter()
    batch = syn._collisions(cand.power, cand.thermal, actions, tuple(range(n)),
                            MARGIN_K, FEAS_TOL, None)
    if len(batch) == 0:
        print(f"  collision_free=True -> SYNTHESIZABLE; C*(arch_b) <= {cost.sum():.0f} "
              f"({time.perf_counter()-t0:.1f}s)")
    else:
        print(f"  collision_free=False, {len(batch)} collisions -> UNSYNTHESIZABLE: "
              f"no plan exists even with every action ({time.perf_counter()-t0:.1f}s)")

    npz = OUTPUT / "triangle_antichain.npz"
    if npz.is_file():
        with np.load(npz, allow_pickle=False) as d:
            C = d["cuts"]
        print(f"\n--- Q2: LP bound vs cut count (random nested subsets of {C.shape[0]}) ---")
        rng = np.random.default_rng(0)
        order = rng.permutation(C.shape[0])
        for k in [100, 250, 500, 1000, 2000, 3000, C.shape[0]]:
            if k > C.shape[0]:
                continue
            sub = C[order[:k]]
            print(f"  {k:>5} cuts -> LP {lp_bound(sub, cost):.2f}")
    else:
        print("\n  (no persisted antichain; run triangle2 first)")


if __name__ == "__main__":
    main()
