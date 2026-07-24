"""End-to-end break-even probe for the thermal kernel (CertiTherm-F, synthesis
review's #1 experiment). Work-proxy (N_cell*N_safe) is not wall-time; this times an
actual exhaustive collision scan on the FULL vs KERNEL instance and evaluates the
amortization gate A < Q*(L_f - L_k): audit cost A is paid once, per-query saving
(L_f - L_k) accrues over Q oracle scans (MaxHS rounds + deletion tests).

Uses kernel_verify.Replica (same pair-collision LP as production, parameterised by
SAFE-row and REJECT-cell subsets). Scans are SEQUENTIAL here (one linprog per cell),
so absolute times differ from the parallel production oracle. Whether the L_f/L_k
RATIO carries over to the parallel oracle is a HYPOTHESIS, NOT verified here -- the
authoritative number is the end-to-end deletion A/B on the real (parallel) oracle
(kernel_ab.sh). A collision-FREE selection (full registry) is timed because that is
the exhaustive worst case the deletion/MaxHS loop actually pays; colliding
selections early-stop and are not representative.

NON-CLAIM measurement. Usage: python research/triangle/kernel_timing.py <out> <wl> <cand>
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

import kernel_audit
from kernel_audit import Polytope, safe_audit, reject_audit
from kernel_verify import Replica, candidate_full, reject_table, MARGIN_K
from CertiTherm.synthesis import _robust_safe_rows

kernel_audit.TAU = 1e-6


def _time_scan(rep, selection, safe_idx, rej_idx, repeats=3):
    best = float("inf")
    res = None
    for _ in range(repeats):
        t = time.perf_counter()
        res = rep.collides(selection, safe_idx, rej_idx)
        best = min(best, time.perf_counter() - t)
    return best, res


def main():
    cand, actions, cid = candidate_full()
    P = Polytope(cand.power)
    srows, srhs = _robust_safe_rows(cand.thermal, MARGIN_K)
    srows = np.asarray(srows, float); srhs = np.asarray(srhs, float)
    rrows, rfloors = reject_table(cand.thermal)

    t0 = time.perf_counter()
    safe_surv, _ = safe_audit(P, srows, srhs, list(range(len(srows))))
    rej_surv, _, _ = reject_audit(P, rrows, rfloors, list(range(len(rrows))))
    audit_A = time.perf_counter() - t0
    safe_full = list(range(len(srows))); safe_kern = sorted(safe_surv)
    rej_full = list(range(len(rrows))); rej_kern = sorted(rej_surv)

    rep = Replica(cand, actions)
    full_sel = tuple(range(len(actions)))          # collision-free -> exhaustive scan

    Lf, rf = _time_scan(rep, full_sel, safe_full, rej_full)
    Lk, rk = _time_scan(rep, full_sel, safe_kern, rej_kern)
    assert rf == rk, "full and kernel disagree on the timed selection!"

    print(f"{cid} ({sys.argv[2]} c{sys.argv[3]}): SAFE {len(safe_full)}->{len(safe_kern)}, "
          f"REJECT {len(rej_full)}->{len(rej_kern)}")
    print(f"  full-registry selection collision-free: {not rf}")
    print(f"  L_f (full scan)   = {Lf*1000:.1f} ms")
    print(f"  L_k (kernel scan) = {Lk*1000:.1f} ms")
    print(f"  per-query speedup L_f/L_k = {Lf/Lk:.2f}x")
    print(f"  audit cost A = {audit_A:.1f} s (paid once)")
    if Lf > Lk:
        Q_be = audit_A / (Lf - Lk)
        print(f"  break-even queries Q* = A/(L_f-L_k) = {Q_be:.0f} scans")
        print(f"  (a MaxHS+deletion run does O(300) exhaustive scans/candidate -> "
              f"amortises if Q > {Q_be:.0f})")
    print("  NOTE: sequential replica. Whether the parallel oracle keeps this ratio "
          "is a HYPOTHESIS -- see the end-to-end A/B (kernel_ab.sh) for the real number.")


if __name__ == "__main__":
    main()
