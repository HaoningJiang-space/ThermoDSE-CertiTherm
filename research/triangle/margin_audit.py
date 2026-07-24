"""Decision-separation margin audit (N0, corrected).

Reports the DUPLICATE-INVARIANT min-max margin of a verified observation contract:

    Gamma_inf(S) = min_j  min_{z in Q_j}  max_{i in S} ( |d_i' z| - tau_i ) / w_i

where Q_j is the SAFE/REJECT pair polytope for cell j WITHOUT measurement rows and
d_i' z = a_i'(p_safe - p_unsafe). Equivalence (validated on a tiny instance by full
2^n enumeration): Gamma(S) > 0  <=>  S is decision-identifying.

WHY min-max and not the sum. The sum-hinge  sum_i [ |d_i'z| - tau_i ]_+  rewards
duplicated or highly correlated channels: adding a redundant measurement raises it
without improving physical robustness. The min-max is invariant to duplication and
has a direct reading -- it is the smallest TOLERANCE INFLATION that would destroy
identifiability. The sum form remains useful as an optimisation surrogate (it
dualises to a fixed LP); it must NOT be reported as physical robustness.

UNITS. d_i'z is a POWER projection (the measurement vector applied to a power
difference), NOT a temperature. With `--norm rel` the margin is divided by tau_i and
is DIMENSIONLESS ("how many tolerances of separation"), which is also invariant to
row scaling. `--norm abs` leaves raw units; it is scaling-sensitive, so any
cross-instance comparison should use `rel`.

FAIL-CLOSED. Every cell must resolve to optimal (a margin) or infeasible (Q_j empty
=> the cell can never reject, so it imposes no constraint). ANY other solver status
is UNRESOLVED and fails the audit: silently skipping a hard cell would OVERSTATE the
global minimum, which is exactly the wrong direction for a safety claim. The cover's
action IDs must also match the live registry exactly.

No verdict thresholds are hard-coded: a robustness verdict requires a rho derived
from the frozen measurement-error contract, which this script does not invent. It
reports the distribution, the worst cell, and the adversarial world pair.

NON-CLAIM measurement.
Usage: python research/triangle/margin_audit.py <out> <workload> <cand> [rel|abs] [max_cells]
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
NORM = sys.argv[4] if len(sys.argv) > 4 else "rel"
MAXCELLS = int(sys.argv[5]) if len(sys.argv) > 5 else 0
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
        print(f"FAIL: no verified cover manifest at {man}"); sys.exit(2)
    want = list(json.loads(man.read_text())["cover_action_ids"])
    by_id = {a.action_id: i for i, a in enumerate(actions)}
    missing = [aid for aid in want if aid not in by_id]
    if missing:                                        # registry drift -> fail closed
        print(f"FAIL: {len(missing)} manifest action IDs absent from the live registry "
              f"(e.g. {missing[:3]}) -- refusing to audit a different cover"); sys.exit(2)
    S = sorted(by_id[aid] for aid in want)
    print(f"{cid} ({WORKLOAD} c{CAND}): cover {len(S)}/{len(actions)} actions, norm={NORM}")

    w = np.array([actions[i].tolerance if NORM == "rel" else 1.0 for i in S], dtype=float)
    if NORM == "rel" and not np.all(w > 0):
        bad = int((w <= 0).sum())
        print(f"FAIL: {bad} selected actions have tolerance <= 0; 'rel' normalisation "
              f"undefined -- rerun with 'abs' and treat results as scaling-sensitive")
        sys.exit(2)

    a_eq, b_eq, base_a_ub, base_b_ub = _pair_rows(power)
    srows, srhs = _robust_safe_rows(thermal, MARGIN_K)
    safe = np.hstack((np.asarray(srows), np.zeros_like(np.asarray(srows))))
    q_a_ub = np.vstack((base_a_ub, safe))
    q_b_ub = np.concatenate((base_b_ub, np.asarray(srhs)))
    resp = thermal.response_k_per_w

    # min-max epigraph: variables (z, t); t >= (+-d_i'z - tau_i)/w_i for every i in S
    epi, erhs = [], []
    for k, i in enumerate(S):
        d = np.concatenate((actions[i].vector, -actions[i].vector)) / w[k]
        epi.append(np.concatenate((d, [-1.0])));  erhs.append(actions[i].tolerance / w[k])
        epi.append(np.concatenate((-d, [-1.0]))); erhs.append(actions[i].tolerance / w[k])
    epi = np.asarray(epi); erhs = np.asarray(erhs)
    obj = np.concatenate((np.zeros(2 * n), [1.0]))                     # minimise t
    bnds = list(zip(power.lower_w, power.upper_w)) * 2 + [(None, None)]

    specs = [(m, q) for m in range(resp.shape[0]) for q in range(resp.shape[1])]
    partial = bool(MAXCELLS) and MAXCELLS < len(specs)
    if MAXCELLS:
        specs = specs[:MAXCELLS]

    gam, unreachable, unresolved, worst = [], 0, [], None
    t0 = time.perf_counter()
    for (m, q) in specs:
        rrow = np.concatenate((np.zeros(n), -resp[m, q]))
        rrhs = -(thermal.limit_k + MARGIN_K - thermal.error_k[m] - thermal.ambient_k[m, q])
        A = np.vstack((np.hstack((q_a_ub, np.zeros((q_a_ub.shape[0], 1)))),
                       np.append(rrow, 0.0).reshape(1, -1), epi))
        b = np.concatenate((q_b_ub, [rrhs], erhs))
        r = linprog(obj, A_ub=A, b_ub=b,
                    A_eq=np.hstack((a_eq, np.zeros((a_eq.shape[0], 1)))), b_eq=b_eq,
                    bounds=bnds, method="highs")
        if r.status == 2:
            unreachable += 1                       # Q_j empty: cell can never reject
        elif r.status == 0:
            g = float(r.fun)
            gam.append(g)
            if worst is None or g < worst[0]:
                worst = (g, (m, q), r.x[:n].copy(), r.x[n:2 * n].copy())
        else:
            unresolved.append(((m, q), r.status))   # FAIL CLOSED -- never skip silently
    dt = time.perf_counter() - t0

    print(f"cells: {len(specs)}{' (PARTIAL SCAN)' if partial else ''}, "
          f"{unreachable} unreachable, {len(gam)} with a margin, "
          f"{len(unresolved)} UNRESOLVED  ({dt:.0f}s)")
    if unresolved:
        print(f"FAIL: {len(unresolved)} cells did not resolve (e.g. {unresolved[:3]}). "
              f"Skipping them would OVERSTATE the global minimum margin."); sys.exit(2)
    if not gam:
        print("every scanned cell unreachable -> margin undefined for this scan"); return
    g = np.array(gam)
    unit = "tolerances (dimensionless)" if NORM == "rel" else "raw power units"
    print(f"  Gamma_inf : min={g.min():.4e}  p1={np.percentile(g,1):.4e}  "
          f"median={np.median(g):.4e}  max={g.max():.4e}   [{unit}]")
    scope = "scanned cells (PARTIAL)" if partial else "all cells"
    print(f"  Gamma_inf(S) over {scope} = {g.min():.6e}")
    if worst is not None:
        print(f"  worst cell = model/point {worst[1]}; adversarial pair saved")
        np.savez_compressed(OUTPUT / f"margin_worst_{WORKLOAD}_c{CAND}.npz",
                            gamma=worst[0], cell=np.array(worst[1]),
                            p_safe=worst[2], p_unsafe=worst[3], norm=np.array(NORM))
    print("\nNOTE: no robustness verdict is issued. Calling this contract robust or "
          "fragile requires a rho derived from the frozen measurement-error contract; "
          "this audit deliberately does not invent one.")


if __name__ == "__main__":
    main()
