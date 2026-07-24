"""Step 1 of the Farkas co-design validation: does the reformulation actually equal C*?

Two independent checks on a TINY instance where 2^n enumeration is possible:

  (A) THEOREM   For every measurement subset S and every reject cell j:
                  P_j(S) = empty  <=>  a Farkas certificate with support in S exists.
                Checked by LP both ways (no big-M anywhere).

  (B) ENCODING  The monolithic Farkas MIP (binaries x_i, per-cell multipliers y_j,
                linked by y_meas(i) <= M x_i) recovers exactly the brute-force
                minimum cost C* = min{ c'x : S(x) certifies }.

(A) validates the mathematics; (B) validates the encoding INCLUDING the big-M, which
is where a monolithic reformulation usually goes wrong. If (A) passes but (B) fails,
the theorem is fine and the encoding/M is the problem -- exactly the distinction we
need before investing in any large-scale or GPU version.

NON-CLAIM. Usage: python research/triangle/farkas_bruteforce.py [bigM]
"""
from __future__ import annotations

import itertools
import sys

import numpy as np
from scipy.optimize import linprog, milp, Bounds, LinearConstraint

BIG_M = float(sys.argv[1]) if len(sys.argv) > 1 else 1e6

# ---- tiny instance -------------------------------------------------------
D = 3                                  # thermal blocks; z = (p_safe, p_reject) in R^6
HI = 20.0                              # power box upper bound
SAFE_RHS, REJ_FLOOR = 9.5, 10.5        # limit -/+ margin
RESP = np.eye(D)                       # cell k responds to block k
ACT = np.array([[1., 0., 0.], [0., 1., 0.], [0., 0., 1.],
                [1., 1., 0.], [1., 1., 1.]])          # measurement channels a_i
TAU = np.full(len(ACT), 0.1)
COST = np.array([1., 1., 1., 2., 3.])
NA, NC = len(ACT), D


def rows_for_cell(j, selected):
    """A z <= b for P_j(S), z = (p_safe, p_reject). All-inequality form."""
    A, b = [], []
    for k in range(D):                                   # SAFE on p_safe (all cells)
        A.append(np.concatenate((RESP[k], np.zeros(D)))); b.append(SAFE_RHS)
    A.append(np.concatenate((np.zeros(D), -RESP[j])));  b.append(-REJ_FLOOR)  # REJECT at j
    for t in range(2 * D):                               # box 0 <= z <= HI
        e = np.zeros(2 * D); e[t] = 1.0
        A.append(e.copy()); b.append(HI)
        A.append(-e); b.append(0.0)
    for i in selected:                                   # |a_i'(ps - pr)| <= tau_i
        d = np.concatenate((ACT[i], -ACT[i]))
        A.append(d.copy()); b.append(TAU[i])
        A.append(-d); b.append(TAU[i])
    return np.array(A), np.array(b)


def is_empty(A, b):
    """True iff {z : A z <= b} is empty (zero objective feasibility LP)."""
    r = linprog(np.zeros(A.shape[1]), A_ub=A, b_ub=b,
                bounds=[(None, None)] * A.shape[1], method="highs")
    return r.status == 2


def farkas_exists(A, b):
    """True iff exists y >= 0 with A'y = 0 and b'y <= -1 (Farkas infeasibility cert)."""
    m = A.shape[0]
    r = linprog(np.zeros(m), A_ub=b.reshape(1, -1), b_ub=np.array([-1.0]),
                A_eq=A.T, b_eq=np.zeros(A.shape[1]),
                bounds=[(0, None)] * m, method="highs")
    return r.status == 0


def main():
    print(f"tiny instance: D={D} blocks, {NC} cells, {NA} actions, big-M={BIG_M:g}")

    # ---- (A) theorem + brute-force C* ------------------------------------
    mismatches, certifying = 0, []
    for r in range(NA + 1):
        for S in itertools.combinations(range(NA), r):
            ok = True
            for j in range(NC):
                A, b = rows_for_cell(j, S)
                empty, cert = is_empty(A, b), farkas_exists(A, b)
                if empty != cert:
                    mismatches += 1
                    print(f"  THEOREM MISMATCH S={S} cell={j}: empty={empty} cert={cert}")
                ok &= empty
            if ok:
                certifying.append((float(COST[list(S)].sum()), S))
    c_star, best = min(certifying) if certifying else (float("inf"), None)
    print(f"(A) theorem: {mismatches} mismatches over all {2**NA} subsets x {NC} cells "
          f"-> {'PASS' if mismatches == 0 else 'FAIL'}")
    print(f"    brute-force C* = {c_star:.0f} via S={best} "
          f"({len(certifying)} certifying subsets)")

    # ---- (B) monolithic Farkas MIP ---------------------------------------
    # variables: x (NA binaries) then, per cell, y_j >= 0 over that cell's rows built
    # with ALL actions available; measurement multipliers gated by y <= M x.
    all_rows = [rows_for_cell(j, tuple(range(NA))) for j in range(NC)]
    m_j = [A.shape[0] for A, _ in all_rows]
    base = D + 1 + 4 * D                # SAFE(D) + REJECT(1) + box(4D) rows, then measurements
    offs, tot = [], NA
    for mj in m_j:
        offs.append(tot); tot += mj
    Aeq, beq, Aub, bub = [], [], [], []
    for j, (A, b) in enumerate(all_rows):
        o = offs[j]
        for col in range(2 * D):                          # stationarity A'y = 0
            row = np.zeros(tot); row[o:o + m_j[j]] = A[:, col]
            Aeq.append(row); beq.append(0.0)
        row = np.zeros(tot); row[o:o + m_j[j]] = b        # contradiction b'y <= -1
        Aub.append(row); bub.append(-1.0)
        for i in range(NA):                               # gate: y_meas(i) <= M x_i
            for t in (base + 2 * i, base + 2 * i + 1):
                row = np.zeros(tot); row[o + t] = 1.0; row[i] = -BIG_M
                Aub.append(row); bub.append(0.0)
    c = np.concatenate((COST, np.zeros(tot - NA)))
    lo = np.zeros(tot); hi = np.concatenate((np.ones(NA), np.full(tot - NA, np.inf)))
    integrality = np.concatenate((np.ones(NA), np.zeros(tot - NA)))
    cons = [LinearConstraint(np.array(Aeq), lb=np.array(beq), ub=np.array(beq)),
            LinearConstraint(np.array(Aub), lb=-np.inf, ub=np.array(bub))]
    res = milp(c=c, constraints=cons, integrality=integrality, bounds=Bounds(lo, hi),
               options={"mip_rel_gap": 0.0})
    if not res.success:
        print("(B) MIP failed:", res.message); return
    x = np.round(res.x[:NA])
    mip_cost = float(COST[x > 0.5].sum())
    print(f"(B) Farkas MIP  C* = {mip_cost:.0f} via S={tuple(np.flatnonzero(x > 0.5))} "
          f"(vars={tot}, rows={len(Aeq) + len(Aub)})")
    verdict = "PASS" if (mismatches == 0 and abs(mip_cost - c_star) < 1e-6) else "FAIL"
    print(f"\nVERDICT: theorem {'ok' if mismatches == 0 else 'BROKEN'}; "
          f"encoding {'matches' if abs(mip_cost - c_star) < 1e-6 else 'MISMATCH'} "
          f"brute force -> {verdict}")


if __name__ == "__main__":
    main()
