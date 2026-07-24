"""Margin audit: how FRAGILE are our verified observation contracts?

For a verified (collision-free) cover S, the decision-separation margin is

    Gamma(S) = min_j  min_{z in Q_j}  sum_{i in S} [ |d_i' z| - tau_i ]_+

where Q_j is the SAFE/REJECT pair polytope for cell j WITHOUT the measurement rows,
and d_i' z = a_i'(p_safe - p_unsafe). Validated on a tiny instance:
Gamma(S) > 0  <=>  S is decision-identifying.

Gamma is what the certificate does NOT tell us today. A cover can be certified
collision-free and still sit on a knife edge: if Gamma ~ 1e-12, any model error,
power-capture error or tolerance drift flips the decision. If Gamma is a stable
physical margin (tenths of a Kelvin-equivalent), the contract is robust.

This audit computes Gamma_j for every cell on a REAL verified cover, so we learn
whether the existing [L,U] certificates are engineering-meaningful or razor-thin.
Each Gamma_j is one LP (hinges linearise), so the cost is ~one full oracle scan.

NON-CLAIM measurement.
Usage: python research/triangle/margin_audit.py <out> <workload> <cand> [max_cells]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, ".")

from CertiTherm.synthesis import _pair_rows, _robust_safe_rows
from CertiTherm.experiments import (
    ROOT, _capture, _measurement_costs, _ordered_architectures,
    _power_space, _registry_split, _rows, load_family,
)
from CertiTherm.measurements import build_measurement_library

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/diag150b")
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
CAND = int(sys.argv[3]) if len(sys.argv) > 3 else 1
MAXCELLS = int(sys.argv[4]) if len(sys.argv) > 4 else 0        # 0 = all cells
MARGIN_K = 1e-4


def candidate():
    reg = _registry_split("dev_v3")
    arches = sorted((r for r in _rows(ROOT / "experiments" / "architectures.tsv")
                     if r["split"] == reg), key=lambda r: int(r["rank"]))
    pkgs = _rows(ROOT / "experiments" / "packages.tsv")
    default_pkg = next(p for p in pkgs if p["package_id"] == "default")
    wl = next(w for w in _rows(ROOT / "experiments" / "workloads.tsv")
              if w["split"] == reg and w["workload_id"] == WORKLOAD)
    costs = _measurement_costs()
    caps = {(WORKLOAD, a["architecture_id"]): _capture(a, wl, default_pkg, OUTPUT) for a in arches}
    a0 = _ordered_architectures(WORKLOAD, arches, caps)[CAND]
    power, blocks, placed, floor = _power_space(caps[(WORKLOAD, a0["architecture_id"])])
    fam, ob = load_family(OUTPUT / "operators" / f"{a0['architecture_id']}--default.npz")
    actions = tuple(build_measurement_library(a0["architecture_id"], blocks, floor, a0, costs))
    return power, fam, actions, a0["architecture_id"]


def main():
    power, thermal, actions, cid = candidate()
    n = power.dimension

    man = OUTPUT / f"upper_bound_{WORKLOAD}_c{CAND}.json"
    if not man.exists():
        print(f"no verified cover manifest at {man}"); return
    ids = set(json.loads(man.read_text())["cover_action_ids"])
    S = [i for i, a in enumerate(actions) if a.action_id in ids]
    print(f"{cid} ({WORKLOAD} c{CAND}): verified cover = {len(S)} actions of {len(actions)}",
          flush=True)

    a_eq, b_eq, base_a_ub, base_b_ub = _pair_rows(power)
    srows, srhs = _robust_safe_rows(thermal, MARGIN_K)
    safe = np.hstack((np.asarray(srows), np.zeros_like(np.asarray(srows))))
    q_a_ub = np.vstack((base_a_ub, safe))                    # Q_j: NO measurement rows
    q_b_ub = np.concatenate((base_b_ub, np.asarray(srhs)))
    bounds_z = list(zip(power.lower_w, power.upper_w)) * 2
    resp = thermal.response_k_per_w

    # hinge epigraph rows for the cover: s_i >= +-d_i'z - tau_i
    ns = len(S)
    hinge, hrhs = [], []
    for t, i in enumerate(S):
        d = np.concatenate((actions[i].vector, -actions[i].vector))
        e = np.zeros(ns); e[t] = -1.0
        hinge.append(np.concatenate((d, e)));  hrhs.append(actions[i].tolerance)
        hinge.append(np.concatenate((-d, e))); hrhs.append(actions[i].tolerance)
    hinge = np.asarray(hinge); hrhs = np.asarray(hrhs)
    obj = np.concatenate((np.zeros(2 * n), np.ones(ns)))
    bnds = bounds_z + [(0, None)] * ns

    specs = [(m, q) for m in range(resp.shape[0]) for q in range(resp.shape[1])]
    if MAXCELLS:
        specs = specs[:MAXCELLS]
    gammas, unreachable = [], 0
    t0 = time.perf_counter()
    for (m, q) in specs:
        rrow = np.concatenate((np.zeros(n), -resp[m, q]))
        rrhs = -(thermal.limit_k + MARGIN_K - thermal.error_k[m] - thermal.ambient_k[m, q])
        A = np.vstack((np.hstack((q_a_ub, np.zeros((q_a_ub.shape[0], ns)))),
                       np.concatenate((rrow, np.zeros(ns))).reshape(1, -1),
                       hinge))
        b = np.concatenate((q_b_ub, [rrhs], hrhs))
        r = linprog(obj, A_ub=A, b_ub=b,
                    A_eq=np.hstack((a_eq, np.zeros((a_eq.shape[0], ns)))), b_eq=b_eq,
                    bounds=bnds, method="highs")
        if r.status == 2:
            unreachable += 1                                  # Q_j empty: cell can't reject
        elif r.status == 0:
            gammas.append(float(r.fun))
    dt = time.perf_counter() - t0

    if not gammas:
        print("every cell unreachable -> margin undefined"); return
    g = np.array(gammas)
    print(f"cells: {len(specs)} total, {unreachable} unreachable, {len(g)} with a margin "
          f"({dt:.0f}s)")
    print(f"  Gamma_j : min={g.min():.3e}  p1={np.percentile(g,1):.3e}  "
          f"median={np.median(g):.3e}  max={g.max():.3e}")
    print(f"  Gamma(S) = min_j Gamma_j = {g.min():.6e}")
    tiny = (g < 1e-9).mean()
    print(f"  fraction of cells with Gamma_j < 1e-9: {tiny:.1%}")
    if g.min() < 1e-9:
        print("\nVERDICT: KNIFE EDGE -- the verified contract is numerically fragile; "
              "certification survives only because the LP tolerance says so.")
    elif g.min() < 1e-3:
        print("\nVERDICT: THIN -- a real but small margin; a rho-margin contract would "
              "materially change the problem.")
    else:
        print("\nVERDICT: ROBUST -- the contract has genuine decision-separation margin.")


if __name__ == "__main__":
    main()
