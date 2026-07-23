"""Thermal decision-frontier kernelization audit (CertiTherm-F step 1).

Measures the provably-removable fraction of the collision LP's SAFE rows and
REJECT cells -- rows/cells whose removal cannot change ANY collision, hence cannot
change the optimal observation cost C*. If cells shrink >=3-4x and SAFE rows
>=50%, decision-frontier kernelization is a real contribution; a weak result is
itself the finding (pivot to cooperative IHS).

Peer-reviewed design + adversarial review of the first result (2026-07-23/24).
Refinements applied:
 - REJECT redundancy via a PHASE-I LP (min t s.t. g_j>=0, g_k<=t), never a bare
   float INFEASIBLE; unreachable cells handled separately.
 - THREE-WAY numeric classification with a positive margin TAU; ambiguous kept.
 - GREEDY sequential, several deterministic orders; report survivor SETS (not just
   counts -- adversarial review: identical counts != identical sets).
 - SLACK MARGINS reported for every removal (distance to the TAU boundary), so the
   result's robustness is visible rather than assumed.
 - FINAL-SET re-audit (the decisive counterexample search): every removed row/cell
   is re-checked against the FINAL survivor set; any violation is a hard failure.
 - audit LP uses EXACTLY the oracle's P, bounds, _robust_safe_rows and REJECT floor
   convention (limit + margin - err - amb).

NON-CLAIM float audit. Exact/Farkas certs and the production-oracle four-variant
equivalence test come later; this answers "is there compressibility?" and "is it
self-consistent at the LP level?".

Usage: python research/triangle/kernel_audit.py <out> <workload> <cand> [TAU]
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, ".")

from CertiTherm.synthesis import _robust_safe_rows
from CertiTherm.experiments import (
    ROOT, _capture, _measurement_costs, _ordered_architectures,
    _power_space, _registry_split, _rows, load_family,
)
from CertiTherm.measurements import build_measurement_library

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "diag150b"
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
CAND = int(sys.argv[3]) if len(sys.argv) > 3 else 1
MARGIN_K = 1e-4
TAU = float(sys.argv[4]) if len(sys.argv) > 4 else 1e-6
ORDERS = 5


def candidate():
    reg = _registry_split("dev_v3")
    arches = sorted((r for r in _rows(ROOT / "experiments" / "architectures.tsv")
                     if r["split"] == reg), key=lambda r: int(r["rank"]))
    pkgs = _rows(ROOT / "experiments" / "packages.tsv")
    default_pkg = next(p for p in pkgs if p["package_id"] == "default")
    wl = next(w for w in _rows(ROOT / "experiments" / "workloads.tsv")
              if w["split"] == reg and w["workload_id"] == WORKLOAD)
    caps = {(WORKLOAD, a["architecture_id"]): _capture(a, wl, default_pkg, OUTPUT) for a in arches}
    a0 = _ordered_architectures(WORKLOAD, arches, caps)[CAND]
    power, blocks, placed, floor = _power_space(caps[(WORKLOAD, a0["architecture_id"])])
    fam, ob = load_family(OUTPUT / "operators" / f"{a0['architecture_id']}--default.npz")
    assert blocks == ob
    return power, fam, a0["architecture_id"]


class Polytope:
    def __init__(self, power):
        self.a_eq = np.asarray(power.a_eq, float)
        self.b_eq = np.asarray(power.b_eq, float)
        self.a_ub = np.asarray(power.a_ub, float)
        self.b_ub = np.asarray(power.b_ub, float)
        self.bounds = list(zip(np.asarray(power.lower_w, float),
                               np.asarray(power.upper_w, float)))
        self.d = power.dimension


def _max_over(P, c, extra_rows, extra_rhs):
    """max c.p over {P, extra_rows.p <= extra_rhs}, or None if not solved."""
    a_ub = P.a_ub if not len(extra_rows) else np.vstack((P.a_ub, np.asarray(extra_rows)))
    b_ub = P.b_ub if not len(extra_rows) else np.concatenate((P.b_ub, np.asarray(extra_rhs)))
    r = linprog(-np.asarray(c, float), A_ub=a_ub, b_ub=b_ub, A_eq=P.a_eq, b_eq=P.b_eq,
                bounds=P.bounds, method="highs")
    return (-r.fun) if r.status == 0 else None


def _phase1_t(P, rj, floor_j, others_rows, others_floors):
    """min t s.t. p in P, g_j(p)>=0, g_k(p)<=t for k in others. Returns t* or None."""
    d = P.d
    obj = np.concatenate((np.zeros(d), [1.0]))
    rj_row = np.concatenate((-np.asarray(rj), [0.0]))            # -r_j.p <= -floor_j
    R = np.asarray(others_rows)
    gk = np.hstack((R, -np.ones((len(others_rows), 1))))          # r_k.p - t <= floor_k
    a_ub = np.vstack((np.hstack((P.a_ub, np.zeros((P.a_ub.shape[0], 1)))), rj_row, gk))
    b_ub = np.concatenate((P.b_ub, [-floor_j], np.asarray(others_floors)))
    has_eq = P.a_eq.size > 0
    a_eq = np.hstack((P.a_eq, np.zeros((P.a_eq.shape[0], 1)))) if has_eq else None
    r = linprog(obj, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=P.b_eq if has_eq else None,
                bounds=P.bounds + [(None, None)], method="highs")
    return float(r.x[-1]) if r.status == 0 else None


def safe_audit(P, rows, rhs, order):
    """Greedy SAFE-row redundancy. Returns (survivors:set, removed_margins:list)."""
    survivors = set(range(len(rows)))
    margins = []
    for j in order:
        others = sorted(survivors - {j})
        opt = _max_over(P, rows[j], rows[others], rhs[others])
        if opt is None:
            continue
        m = rhs[j] - opt
        if m >= TAU:
            survivors.discard(j); margins.append(m)      # redundant
        # else necessary (m < -TAU) or ambiguous (|m|<=TAU): keep
    return survivors, margins


def reject_audit(P, rows, floors, order):
    """Greedy REJECT-cell redundancy. Returns
    (survivors:set, unreach_margins:list, dom_t:list)."""
    n = len(rows)
    survivors = set(range(n))
    unreach_m, dom_t = [], []
    for j in order:
        max_gj = _max_over(P, rows[j], [], [])
        if max_gj is None:
            continue
        if floors[j] - max_gj > TAU:                     # unreachable
            survivors.discard(j); unreach_m.append(floors[j] - max_gj); continue
        others = sorted(survivors - {j})
        if not others:
            continue
        t = _phase1_t(P, rows[j], floors[j], rows[others], floors[others])
        if t is None:
            continue
        if t > TAU:
            survivors.discard(j); dom_t.append(t)        # dominated
    return survivors, unreach_m, dom_t


def reaudit_final(P, srows, srhs, rrows, rfloors, safe_surv, rej_surv):
    """Decisive counterexample search (adversarial review): every REMOVED row/cell
    must still be redundant against the FINAL survivor set. Returns (safe_bad,
    rej_bad, min_safe_margin, min_rej_margin) -- any *_bad > 0 refutes the kernel."""
    safe_list = sorted(safe_surv)
    safe_bad, safe_margins = 0, []
    for j in range(len(srows)):
        if j in safe_surv:
            continue
        opt = _max_over(P, srows[j], srows[safe_list], srhs[safe_list])
        if opt is None:
            safe_bad += 1; continue
        m = srhs[j] - opt
        safe_margins.append(m)
        if m < 0:                                        # feasible p violates removed row
            safe_bad += 1
    rej_list = sorted(rej_surv)
    rej_bad, rej_margins = 0, []
    for j in range(len(rrows)):
        if j in rej_surv:
            continue
        max_gj = _max_over(P, rrows[j], [], [])
        if max_gj is not None and rfloors[j] - max_gj > 0:
            rej_margins.append(rfloors[j] - max_gj); continue   # unreachable vs final
        t = _phase1_t(P, rrows[j], rfloors[j], rrows[rej_list], rfloors[rej_list])
        if t is None or t <= 0:                          # reachable AND not dominated
            rej_bad += 1
        else:
            rej_margins.append(t)
    return (safe_bad, rej_bad,
            (min(safe_margins) if safe_margins else None),
            (min(rej_margins) if rej_margins else None))


def _orders(n, seedbase):
    orders = [list(range(n))]
    for s in range(1, ORDERS):
        rng = np.random.RandomState(seedbase + s)
        p = list(range(n)); rng.shuffle(p); orders.append(p)
    return orders


def _set_report(name, sets, total):
    counts = [len(s) for s in sets]
    inter = set.intersection(*sets); union = set.union(*sets)
    identical = all(s == sets[0] for s in sets)
    print(f"  {name}: survivors min/med/max = {min(counts)}/"
          f"{int(statistics.median(counts))}/{max(counts)}; "
          f"sets identical across orders: {identical}; "
          f"|intersection|={len(inter)} |union|={len(union)} (of {total})")
    return sets[0]


def main():
    power, thermal, cid = candidate()
    P = Polytope(power)
    srows, srhs = _robust_safe_rows(thermal, MARGIN_K)
    srows = np.asarray(srows, float); srhs = np.asarray(srhs, float)
    resp = thermal.response_k_per_w
    rrows, rfloors = [], []
    for m in range(resp.shape[0]):
        for q in range(resp.shape[1]):
            rrows.append(resp[m, q])
            rfloors.append(thermal.limit_k + MARGIN_K - thermal.error_k[m]
                           - thermal.ambient_k[m, q])
    rrows = np.asarray(rrows, float); rfloors = np.asarray(rfloors, float)

    print(f"{cid} ({WORKLOAD} c{CAND}): P dim={P.d}, SAFE rows={len(srows)}, "
          f"REJECT cells={len(rrows)}, TAU={TAU}, orders={ORDERS}", flush=True)
    t0 = time.perf_counter()

    safe_sets, safe_margins = [], []
    for order in _orders(len(srows), 1000):
        surv, m = safe_audit(P, srows, srhs, order)
        safe_sets.append(surv); safe_margins += m
    print(f"\n--- SAFE rows ({len(srows)}) ---")
    safe_canon = _set_report("SAFE", safe_sets, len(srows))
    if safe_margins:
        print(f"  removal margin (rhs-opt) K: min={min(safe_margins):.3e} "
              f"median={statistics.median(safe_margins):.3e}  (must be >= TAU={TAU})")

    rej_sets, unreach_all, dom_all = [], [], []
    for order in _orders(len(rrows), 2000):
        surv, um, dt = reject_audit(P, rrows, rfloors, order)
        rej_sets.append(surv); unreach_all += um; dom_all += dt
    print(f"\n--- REJECT cells ({len(rrows)}) ---")
    rej_canon = _set_report("REJECT", rej_sets, len(rrows))
    if unreach_all:
        print(f"  unreachable margin (floor-max) K: min={min(unreach_all):.3e} "
              f"median={statistics.median(unreach_all):.3e}")
    if dom_all:
        print(f"  dominated phase-I t* K: min={min(dom_all):.3e} "
              f"median={statistics.median(dom_all):.3e}  (must be > TAU)")

    # Structural question: is the SAFE-survivor set the SAME as the REJECT-survivor
    # set? Both are indexed over the same (model,point) grid in the same order, so a
    # set match would mean a single "decision frontier" governs both.
    inter = safe_canon & rej_canon
    print(f"\n--- SAFE-vs-REJECT survivor overlap ---")
    print(f"  |SAFE|={len(safe_canon)} |REJECT|={len(rej_canon)} |intersection|={len(inter)} "
          f"|SAFE\\REJECT|={len(safe_canon-rej_canon)} |REJECT\\SAFE|={len(rej_canon-safe_canon)}; "
          f"identical set: {safe_canon == rej_canon}")

    print(f"\n--- FINAL-SET re-audit (counterexample search, canonical order) ---")
    sb, rb, smin, rmin = reaudit_final(P, srows, srhs, rrows, rfloors, safe_canon, rej_canon)
    print(f"  SAFE removed-rows refuted by final set: {sb}  (min margin "
          f"{smin if smin is None else f'{smin:.3e}'})")
    print(f"  REJECT removed-cells refuted by final set: {rb}  (min margin "
          f"{rmin if rmin is None else f'{rmin:.3e}'})")
    verdict = "PASS" if (sb == 0 and rb == 0) else "FAIL"
    print(f"  final-set re-audit: {verdict}")

    ns, nc = len(srows), len(rrows)
    ns2, nc2 = len(safe_canon), len(rej_canon)
    print(f"\n--- summary ---")
    print(f"  SAFE {ns}->{ns2} ({1-ns2/ns:.1%} removable); REJECT {nc}->{nc2} "
          f"({nc/nc2:.2f}x); work proxy {(nc*ns)/(nc2*ns2):.1f}x; {time.perf_counter()-t0:.0f}s")


if __name__ == "__main__":
    main()
