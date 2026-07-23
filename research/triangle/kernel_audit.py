"""Thermal decision-frontier kernelization audit (CertiTherm-F step 1).

Measures the provably-removable fraction of the collision LP's SAFE rows and
REJECT cells -- rows/cells whose removal cannot change ANY collision, hence cannot
change the optimal observation cost C*. If cells shrink >=3-4x and SAFE rows
>=50%, decision-frontier kernelization is a real contribution; a weak result is
itself the finding (pivot to cooperative IHS).

Peer-reviewed design (2026-07-23). Review refinements applied:
 - REJECT redundancy proven by a PHASE-I LP (min t s.t. g_j>=0, g_k<=t), never a
   bare float "INFEASIBLE"; unreachable cells handled separately.
 - THREE-WAY numeric classification everywhere: redundant / necessary / AMBIGUOUS
   (retained). A positive margin TAU guards every removal; ambiguous items are
   counted and kept.
 - GREEDY sequential is sound but order-dependent, so the audit runs several
   deterministic orders and reports min/median/max survivors; a go decision needs
   the threshold to hold across orders.
 - the audit LP uses EXACTLY the oracle's P, bounds, SAFE rows (_robust_safe_rows)
   and REJECT floor convention (limit + margin - err - amb).

NON-CLAIM measurement, float HiGHS. Exact-rational / Farkas certificates for the
actual certified kernel come later; this only answers "is there compressibility?".

Usage: python research/triangle/kernel_audit.py <out-dir> <workload> <cand-index>
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
from CertiTherm.core import CandidateSpace
from CertiTherm.measurements import build_measurement_library

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "diag150b"
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
CAND = int(sys.argv[3]) if len(sys.argv) > 3 else 1
MARGIN_K = 1e-4
TAU = 1e-6                       # removal margin, >> HiGHS feas tol, << physical K scale
ORDERS = 5                      # canonical + (ORDERS-1) deterministic shuffles


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
    """The single-world admissible power set P, exactly as the oracle uses it."""
    def __init__(self, power):
        self.a_eq = np.asarray(power.a_eq, float)
        self.b_eq = np.asarray(power.b_eq, float)
        self.a_ub = np.asarray(power.a_ub, float)
        self.b_ub = np.asarray(power.b_ub, float)
        self.bounds = list(zip(np.asarray(power.lower_w, float),
                               np.asarray(power.upper_w, float)))
        self.d = power.dimension


def _max_over(P, c, extra_rows, extra_rhs):
    """max c.p over {P, extra_rows.p <= extra_rhs}. Returns the optimum, or None if
    the LP did not solve to optimality (treated conservatively by the caller)."""
    a_ub = P.a_ub if not len(extra_rows) else np.vstack((P.a_ub, np.asarray(extra_rows)))
    b_ub = P.b_ub if not len(extra_rows) else np.concatenate((P.b_ub, np.asarray(extra_rhs)))
    r = linprog(-np.asarray(c, float), A_ub=a_ub, b_ub=b_ub, A_eq=P.a_eq, b_eq=P.b_eq,
                bounds=P.bounds, method="highs")
    return (-r.fun) if r.status == 0 else None


def safe_audit(P, rows, rhs, order):
    """Greedy SAFE-row redundancy under `order`. Returns (removed, ambiguous,
    survivors). Row j redundant iff max r_j.p over {P, other survivors} <= rhs_j - TAU."""
    survivors = set(range(len(rows)))
    removed, ambiguous = 0, 0
    for j in order:
        others = sorted(survivors - {j})
        opt = _max_over(P, rows[j], rows[others], rhs[others])
        if opt is None:
            ambiguous += 1                       # solver trouble -> keep
            continue
        if opt <= rhs[j] - TAU:
            survivors.discard(j); removed += 1   # redundant (proven)
        elif opt > rhs[j] + TAU:
            pass                                 # necessary
        else:
            ambiguous += 1                       # within margin -> keep
    return removed, ambiguous, len(survivors)


def reject_audit(P, rows, floors, order):
    """Greedy REJECT-cell redundancy under `order`, via the phase-I test
    min t s.t. p in P, g_j(p) >= 0, g_k(p) <= t for retained k != j.
    - unreachable cell (max g_j < -TAU): removable;
    - t* > TAU: redundant (every j-rejecting world exceeds a retained floor);
    - t* <= 0: necessary; otherwise ambiguous -> keep."""
    n = len(rows)
    survivors = set(range(n))
    removed_unreachable, removed_dominated, ambiguous = 0, 0, 0
    for j in order:
        # reachability: can any admissible world reject at j?
        max_gj = _max_over(P, rows[j], [], [])
        if max_gj is None:
            ambiguous += 1; continue
        if max_gj < floors[j] - TAU:
            survivors.discard(j); removed_unreachable += 1; continue
        others = sorted(survivors - {j})
        if not others:
            continue                              # last cell: necessary by definition
        # phase-I over [p (d), t]: min t
        d = P.d
        obj = np.concatenate((np.zeros(d), [1.0]))
        # g_j(p) >= 0  ->  -r_j.p <= -floor_j     (t column 0)
        rj = np.concatenate((-rows[j], [0.0]))
        # g_k(p) - t <= 0  ->  r_k.p - t <= floor_k
        R = np.asarray(rows[others])
        gk = np.hstack((R, -np.ones((len(others), 1))))
        a_ub = np.vstack((np.hstack((P.a_ub, np.zeros((P.a_ub.shape[0], 1)))), rj, gk))
        b_ub = np.concatenate((P.b_ub, [-floors[j]], np.asarray(floors)[others]))
        a_eq = np.hstack((P.a_eq, np.zeros((P.a_eq.shape[0], 1)))) if P.a_eq.size else P.a_eq
        bnds = P.bounds + [(None, None)]
        r = linprog(obj, A_ub=a_ub, b_ub=b_ub,
                    A_eq=a_eq if (P.a_eq.size) else None,
                    b_eq=P.b_eq if (P.a_eq.size) else None,
                    bounds=bnds, method="highs")
        if r.status != 0:
            ambiguous += 1; continue              # incl. infeasible {P, g_j>=0} edge: keep
        t = float(r.x[-1])
        if t > TAU:
            survivors.discard(j); removed_dominated += 1
        elif t <= 0.0:
            pass                                  # necessary
        else:
            ambiguous += 1
    return removed_unreachable, removed_dominated, ambiguous, len(survivors)


def _orders(n, seedbase):
    orders = [list(range(n))]                     # canonical
    for s in range(1, ORDERS):
        rng = np.random.RandomState(seedbase + s)
        p = list(range(n)); rng.shuffle(p); orders.append(p)
    return orders


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
    safe_surv, safe_amb = [], []
    for order in _orders(len(srows), 1000):
        rem, amb, surv = safe_audit(P, srows, srhs, order)
        safe_surv.append(surv); safe_amb.append(amb)
    print(f"\n--- SAFE rows ({len(srows)}) ---")
    print(f"  survivors across {ORDERS} orders: min={min(safe_surv)} "
          f"median={int(statistics.median(safe_surv))} max={max(safe_surv)}")
    print(f"  removable fraction: {1 - max(safe_surv)/len(srows):.1%} (worst) .. "
          f"{1 - min(safe_surv)/len(srows):.1%} (best); ambiguous~{int(statistics.median(safe_amb))}")

    rej_surv, rej_unreach, rej_dom, rej_amb = [], [], [], []
    for order in _orders(len(rrows), 2000):
        unreach, dom, amb, surv = reject_audit(P, rrows, rfloors, order)
        rej_surv.append(surv); rej_unreach.append(unreach)
        rej_dom.append(dom); rej_amb.append(amb)
    print(f"\n--- REJECT cells ({len(rrows)}) ---")
    print(f"  survivors across {ORDERS} orders: min={min(rej_surv)} "
          f"median={int(statistics.median(rej_surv))} max={max(rej_surv)}")
    print(f"  removed: unreachable~{int(statistics.median(rej_unreach))} "
          f"dominated~{int(statistics.median(rej_dom))} ambiguous~{int(statistics.median(rej_amb))}")
    print(f"  cell compression: {len(rrows)/max(rej_surv):.2f}x (worst) .. "
          f"{len(rrows)/min(rej_surv):.2f}x (best)")

    ns, nc = len(srows), len(rrows)
    ns2, nc2 = statistics.median(safe_surv), statistics.median(rej_surv)
    print(f"\n--- structural work proxy (N_cells*N_safe) ---")
    print(f"  {nc}*{ns}={nc*ns}  ->  {nc2}*{ns2}={int(nc2*ns2)}  "
          f"= {(nc*ns)/(nc2*ns2):.2f}x fewer constraint-solves (median order)")
    print(f"\ngo/no-go: SAFE >=50%? cells >=3x?  |  audited in {time.perf_counter()-t0:.0f}s")


if __name__ == "__main__":
    main()
