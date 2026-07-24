"""Formulation gate: persistent lazy branch-and-cut vs brute force vs the outer IHS loop.

The exact problem is a SEMI-INFINITE hitting set (not a surrogate):

    min c'x  over x in {0,1}^m
    s.t. sum_{i in C(z)} x_i >= 1   for every cell j and every collision world z in Q_j
         C(z) = { i : |d_i' z| > tau_i }

`C(z)` is only defined once a measurement set `S` is fixed, because `z` is produced by
solving `P_j(S)`. That is why separation may run ONLY on integral solutions -- see
`_enforce` below.

THREE-WAY AGREEMENT (the gate). On a tiny instance where 2^m enumeration is possible:
  (1) brute force over all 2^m subsets                  -- ground truth
  (2) the current OUTER loop (solve MILP, verify, restart) -- today's algorithm
  (3) persistent lazy branch-and-cut in ONE SCIP tree   -- the proposed algorithm
All three must agree on C*. (2) and (3) share the same separation oracle, so agreeing
with each other proves only wiring; agreeing with (1) is the real check.

SILENT-FAILURE REGRESSIONS. Two SCIP-specific ways to get a WRONG "optimal" with no
error at all, both of which were hit in practice:
  * `conslock` reversed -- SCIP dual-fixes every variable in presolve, fires the handler
    ZERO times, and returns status=optimal with a wrong objective. Guarded by
    `--lock-mode reversed`, which the gate requires to FAIL.
  * missing `consenfops` -- pseudo solutions (no LP) bypass enforcement entirely.

NON-CLAIM diagnostic. Usage:
    python research/triangle/tiny_lazy_bnc.py [--lock-mode correct|reversed] [--presolve on|off]
"""
from __future__ import annotations

import argparse
import itertools
import sys
from fractions import Fraction

import numpy as np
from scipy.optimize import linprog, milp, Bounds, LinearConstraint

sys.path.insert(0, ".")
from CertiTherm.certificate import exact_lagrangian, lattice_lift

# --- tiny instance (shared with farkas_bruteforce.py) ----------------------
D = 3                                   # thermal blocks; z = (p_safe, p_reject) in R^6
HI = 20.0                               # power box upper bound
SAFE_RHS, REJ_FLOOR = 9.5, 10.5         # limit -/+ margin
RESP = np.eye(D)                        # cell k responds to block k
ACT = np.array([[1., 0., 0.], [0., 1., 0.], [0., 0., 1.],
                [1., 1., 0.], [1., 1., 1.]])           # measurement vectors a_i
TAU = np.full(len(ACT), 0.1)
COST = np.array([1., 1., 1., 2., 3.])
NA, NC = len(ACT), D


# --- model ------------------------------------------------------------------
def rows_for_cell(j, selected):
    """A z <= b describing P_j(S): SAFE everywhere, REJECT at cell j, box, and
    |a_i'(p_safe - p_reject)| <= tau_i for every selected action i."""
    A, b = [], []
    for k in range(D):
        A.append(np.concatenate((RESP[k], np.zeros(D)))); b.append(SAFE_RHS)
    A.append(np.concatenate((np.zeros(D), -RESP[j])));   b.append(-REJ_FLOOR)
    for t in range(2 * D):
        e = np.zeros(2 * D); e[t] = 1.0
        A.append(e.copy()); b.append(HI)
        A.append(-e);       b.append(0.0)
    for i in selected:
        d = np.concatenate((ACT[i], -ACT[i]))
        A.append(d.copy()); b.append(TAU[i])
        A.append(-d);       b.append(TAU[i])
    return np.array(A), np.array(b)


# --- separation -------------------------------------------------------------
def separate(selected):
    """Exhaustively scan every cell for a collision world.

    Returns (cuts, witnesses, status):
      cuts       list of index tuples C(z), each a valid cover cut
      witnesses  the world pair z behind each cut, for INDEPENDENT re-derivation
      status     "OK" | "UNSYNTHESIZABLE" (a pair no action separates)
                 | "UNRESOLVED" (a cell whose LP neither solved nor proved empty)

    Fail-closed: an unresolved cell is never reported as collision-free, because
    "no collision found" is exactly what would certify a plan.
    """
    cuts, wits = [], []
    for j in range(NC):
        A, b = rows_for_cell(j, selected)
        r = linprog(np.zeros(A.shape[1]), A_ub=A, b_ub=b,
                    bounds=[(None, None)] * A.shape[1], method="highs")
        if r.status == 2:
            continue                                   # P_j(S) empty -> no collision
        if r.status != 0:
            return [], [], "UNRESOLVED"
        z = r.x
        delta = z[:D] - z[D:]
        sep = tuple(int(i) for i in range(NA) if abs(ACT[i] @ delta) > TAU[i])
        if not sep:
            return [], [], "UNSYNTHESIZABLE"
        assert not (set(sep) & set(selected)), "separator inside the selected set"
        cuts.append(sep); wits.append(z.copy())
    return cuts, wits, "OK"


def certified_lower_bound(cuts):
    """INDEPENDENTLY certified L from the archived cuts, in exact rationals.

    This is deliberately NOT an attempt to re-check SCIP's dual bound. SCIP's
    branch-and-bound bound is an INTEGER bound and is generally STRONGER than
    anything exact weak duality over the cut rows can reproduce -- the two are
    different quantities, so `L_scip` can only ever be recorded as
    `solver_asserted_dual`, never "verified".

    What IS independently certifiable: for ANY y >= 0,
        L(y) = sum_k y_k + sum_i min(0, c_i - sum_{k : i in C_k} y_k)  <=  C*
    (Lagrangian relaxation of `Cx >= 1`), so a badly captured y can only WEAKEN
    the bound. A float LP supplies y; correctness does not depend on it being
    optimal or even feasible. The result is then lifted onto the cost lattice.
    """
    if not cuts:
        return None
    m = len(cuts)
    A = np.zeros((NA, m))
    for k, sep in enumerate(cuts):
        A[list(sep), k] = 1.0
    r = linprog(-np.ones(m), A_ub=A, b_ub=COST, bounds=[(0, None)] * m, method="highs")
    if r.status != 0:
        return None
    y = [Fraction(max(0.0, float(v))).limit_denominator(10 ** 6) for v in r.x]
    costs = [Fraction(c) for c in COST]
    raw = exact_lagrangian(costs, [tuple(s) for s in cuts], y)
    return raw, lattice_lift(raw, costs)


def verify_cuts(cuts, wits):
    """INDEPENDENT check: re-derive C(z) from the stored world pair alone and
    require exact equality with the archived cut. A superset would be valid but
    weaker; a strict subset would be UNSOUND. Only exact equality is accepted."""
    for sep, z in zip(cuts, wits):
        delta = z[:D] - z[D:]
        again = tuple(int(i) for i in range(NA) if abs(ACT[i] @ delta) > TAU[i])
        if again != tuple(sep):
            return False, (sep, again)
    return True, None


# --- (1) brute force --------------------------------------------------------
def brute_force():
    best = None
    for r in range(NA + 1):
        for S in itertools.combinations(range(NA), r):
            cuts, _, st = separate(S)
            if st != "OK":
                continue
            if not cuts:                                # no collision anywhere
                c = float(COST[list(S)].sum())
                if best is None or c < best[0]:
                    best = (c, S)
    return best


# --- (2) the CURRENT outer loop: solve MILP, verify, throw the solver away ---
def outer_ihs(max_rounds=200):
    cuts, wits, rounds, milp_solves = [], [], 0, 0
    while rounds < max_rounds:
        rounds += 1
        if cuts:
            C = np.zeros((len(cuts), NA))
            for r, sep in enumerate(cuts):
                C[r, list(sep)] = 1.0
            m = milp(c=COST, constraints=LinearConstraint(C, lb=np.ones(len(cuts)), ub=np.inf),
                     integrality=np.ones(NA), bounds=Bounds(0, 1),
                     options={"mip_rel_gap": 0.0})
            milp_solves += 1
            if not m.success:
                return None, rounds, milp_solves, "UNRESOLVED"
            S = tuple(np.flatnonzero(np.round(m.x) > 0.5).tolist())
        else:
            S = ()
        new, nw, st = separate(S)
        if st != "OK":
            return None, rounds, milp_solves, st
        if not new:
            return float(COST[list(S)].sum()), rounds, milp_solves, "OK"
        before = len(cuts)
        for sep, z in zip(new, nw):
            if sep not in cuts:
                cuts.append(sep); wits.append(z)
        if len(cuts) == before:
            return None, rounds, milp_solves, "UNRESOLVED"   # no progress
    return None, rounds, milp_solves, "BUDGET"


# --- (3) persistent lazy branch-and-cut -------------------------------------
def lazy_bnc(lock_mode="correct", presolve=True):
    from pyscipopt import Model, Conshdlr, SCIP_RESULT, SCIP_PARAMSETTING

    stats = {"enfolp": 0, "enfops": 0, "check": 0, "sep": 0, "cached": 0,
             "cuts": 0, "status": "OK"}
    cuts, wits = [], []
    # SCIP presents the same assignment through several callbacks (enfolp,
    # enfops, conscheck, heuristics). Separation is deterministic in S, so cache
    # it -- otherwise the same hundreds of physical LPs are re-solved per node.
    memo = {}
    added_to_model = set()

    model = Model()
    model.hideOutput()
    xs = [model.addVar(vtype="B", obj=float(COST[i]), name="x%d" % i) for i in range(NA)]
    model.setMinimize()
    if not presolve:
        model.setPresolve(SCIP_PARAMSETTING.OFF)

    def selected_of(sol, tol=1e-6):
        """Integral selection, or None if the solution is fractional.

        Separation is DEFINED only for an integral x: C(z) comes from solving
        P_j(S), and S = {i : x_i = 1} does not exist for a fractional x. A
        fractional node must therefore be left to branching, never separated by
        rounding x to a set and calling the oracle on it."""
        vals = [model.getSolVal(sol, v) for v in xs]
        if any(min(abs(v), abs(1.0 - v)) > tol for v in vals):
            return None
        return tuple(i for i, v in enumerate(vals) if v > 0.5)

    class CollisionConshdlr(Conshdlr):
        def _run(self, sol):
            """-> (status, found, fresh). `found` is every collision separator of
            this assignment; `fresh` is the subset not already in the ledger."""
            S = selected_of(sol)
            if S is None:
                return None, [], []                   # fractional -> branch, do not separate
            if S in memo:
                stats["cached"] += 1
                st, found = memo[S]
            else:
                stats["sep"] += 1
                found, wit, st = separate(S)
                memo[S] = (st, found)
                if st != "OK":
                    stats["status"] = st
                    return st, [], []
                for sep, z in zip(found, wit):
                    if sep not in cuts:
                        cuts.append(sep); wits.append(z)
            if st != "OK":
                stats["status"] = st
                return st, [], []
            fresh = [sep for sep in found if sep not in added_to_model]
            return "OK", found, fresh

        def _enforce(self, key):
            stats[key] += 1
            st, found, fresh = self._run(None)        # None = current LP/pseudo solution
            if st is None:
                return {"result": SCIP_RESULT.FEASIBLE}      # fractional: let SCIP branch
            if st != "OK":
                self.model.interruptSolve()                  # fail closed, never certify
                return {"result": SCIP_RESULT.CUTOFF}
            if not found:
                return {"result": SCIP_RESULT.FEASIBLE}
            if not fresh:
                # Progress premise of the finite-termination proof: an infeasible
                # assignment must either violate an ALREADY ACTIVE cut (so SCIP
                # would not have offered it) or yield a NEW one. Neither holding
                # means the model and the oracle disagree -> stop, never loop.
                stats["status"] = "UNRESOLVED"
                self.model.interruptSolve()
                return {"result": SCIP_RESULT.CUTOFF}
            for sep in fresh:
                self.model.addCons(sum(xs[i] for i in sep) >= 1)
                added_to_model.add(sep)
                stats["cuts"] += 1
            return {"result": SCIP_RESULT.CONSADDED}

        def consenfolp(self, constraints, nusefulconss, solinfeasible):
            return self._enforce("enfolp")

        def consenfops(self, constraints, nusefulconss, solinfeasible, objinfeasible):
            # Pseudo solutions carry no LP. Omitting this lets SCIP accept a
            # solution that separation never saw -- the same silent class of bug
            # as a reversed conslock.
            return self._enforce("enfops")

        def conscheck(self, constraints, solution, checkintegrality, checklprows,
                      printreason, completely, **kw):
            # EVERY integral solution reaching this callback is checked -- never
            # only "improving" ones. Returning FEASIBLE for an unexamined point
            # would be a false feasibility answer and can corrupt fathoming;
            # SCIP's own objective cutoff is what keeps irrelevant nodes away.
            stats["check"] += 1
            st, found, _ = self._run(solution)
            if st is None:
                return {"result": SCIP_RESULT.INFEASIBLE}    # fractional is never a solution
            if st != "OK" or found:
                return {"result": SCIP_RESULT.INFEASIBLE}
            return {"result": SCIP_RESULT.FEASIBLE}

        def conslock(self, constraint, locktype, nlockspos, nlocksneg):
            # For a covering row sum_i x_i >= 1, DECREASING x_i can break
            # feasibility -> down-lock. Every action variable must be locked,
            # because any of them may appear in a cut that does not exist yet.
            for v in xs:
                if lock_mode == "reversed":
                    self.model.addVarLocks(v, nlocksneg, nlockspos)   # deliberately wrong
                else:
                    self.model.addVarLocks(v, nlockspos, nlocksneg)

    hdlr = CollisionConshdlr()
    model.includeConshdlr(hdlr, "collision", "lazy thermal collision cover cuts",
                          enfopriority=-1000, chckpriority=-1000, needscons=False)
    model.optimize()

    status = model.getStatus()
    # SOLVER-ASSERTED, not verified: SCIP's branch-and-bound dual is an integer
    # bound that exact weak duality over the cut rows cannot reproduce. It is
    # recorded, never published as the certified L.
    stats["solver_asserted_dual"] = model.getDualbound()
    if stats["status"] != "OK" or status not in ("optimal", "bestsollimit"):
        return None, stats, status, cuts, wits
    if model.getNSols() == 0:
        return None, stats, status, cuts, wits
    sol = model.getBestSol()
    S = tuple(i for i, v in enumerate(xs) if model.getSolVal(sol, v) > 0.5)
    return (float(COST[list(S)].sum()), S), stats, status, cuts, wits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock-mode", choices=("correct", "reversed"), default="correct")
    ap.add_argument("--presolve", choices=("on", "off"), default="on")
    args = ap.parse_args()

    print("tiny instance: D=%d blocks, %d cells, %d actions" % (D, NC, NA))
    print("mode: lock=%s presolve=%s" % (args.lock_mode, args.presolve))

    bf = brute_force()
    print("(1) brute force      C* = %.0f via S=%s" % bf)

    ihs_cost, rounds, solves, ihs_st = outer_ihs()
    print("(2) outer IHS loop   C* = %s  (%d rounds, %d MILP solves, %s)"
          % ("%.0f" % ihs_cost if ihs_cost is not None else "None", rounds, solves, ihs_st))

    res, stats, scip_status, cuts, wits = lazy_bnc(args.lock_mode, args.presolve == "on")
    bnc_cost = res[0] if res else None
    print("(3) lazy B&C (SCIP)  C* = %s via S=%s  [scip status=%s]"
          % ("%.0f" % bnc_cost if bnc_cost is not None else "None",
             res[1] if res else None, scip_status))
    print("    enfolp=%(enfolp)d enfops=%(enfops)d check=%(check)d "
          "separations=%(sep)d cached=%(cached)d cuts_added=%(cuts)d" % stats)

    ok_cuts, bad = verify_cuts(cuts, wits)
    print("    independent cut re-derivation from stored witnesses: %s"
          % ("PASS" if ok_cuts else "FAIL %s" % (bad,)))

    # --- the two lower bounds are DIFFERENT QUANTITIES -----------------------
    lb = certified_lower_bound(cuts)
    sad = stats.get("solver_asserted_dual")
    print("    solver_asserted_dual (SCIP B&B, NOT verified) = %s"
          % ("%.4f" % sad if sad is not None else "n/a"))
    if lb is None:
        print("    certified_lower_bound (exact weak duality)    = n/a")
        lb_ok = False
    else:
        raw, lifted = lb
        print("    certified_lower_bound (exact weak duality)    = %s "
              "-> lattice-lifted %s" % (raw, lifted))
        lb_ok = float(lifted) <= bf[0] + 1e-12       # must never exceed the truth

    # --- gate ---------------------------------------------------------------
    fired = stats["sep"] > 0 and stats["cuts"] > 0
    agree = (bnc_cost is not None and ihs_cost is not None
             and abs(bnc_cost - bf[0]) < 1e-6 and abs(ihs_cost - bf[0]) < 1e-6)
    print("\n  three-way agreement : %s" % ("PASS" if agree else "FAIL"))
    print("  separation fired    : %s (sep=%d cuts=%d)"
          % ("PASS" if fired else "FAIL", stats["sep"], stats["cuts"]))
    print("  cut ledger verified : %s" % ("PASS" if ok_cuts else "FAIL"))
    print("  certified L <= C*   : %s" % ("PASS" if lb_ok else "FAIL"))

    passed = agree and fired and ok_cuts and lb_ok
    if args.lock_mode == "reversed":
        # The whole point of this mode: a reversed lock MUST break something.
        # If it silently passes, our regression cannot detect the real bug.
        print("\nREVERSED-LOCK EXPECTATION: the gate must NOT pass -> %s"
              % ("OK (it failed, as required)" if not passed
                 else "PROBLEM: reversed locks passed; this regression is blind"))
        sys.exit(0 if not passed else 1)

    print("\nVERDICT: %s" % ("PASS" if passed else "FAIL"))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
