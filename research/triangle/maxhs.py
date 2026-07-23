"""MaxHS exact-closure loop (Codex Part B item 12 -- the exact-minimum proof).

Deletion (upper_bound.py) only gives an incumbent U; it meets the lower bound L
by luck. The MaxHS / implicit-hitting-set loop is the proof-producing method:

  1. solve the min-cost hitting set (MILP) of the discovered cuts -> candidate
     cover; its solver-asserted dual bound is a valid lower bound L on C*.
  2. verify the candidate cover with the exact separation oracle.
  3. no collision -> the cover is FEASIBLE, so C* <= cost(cover) = MILP optimum
     <= C*  =>  C* = cost(cover) EXACTLY: the interval closes.
  4. a collision -> add its minimal-support (strong) cut and repeat.

Warm-started from the persisted 431-cut strong antichain so it does not
re-discover them. Verification uses the strong (L1) oracle so each added cut is
minimal-support, which is what made L jump 20 -> 720. NON-CLAIM diagnostic;
requires CERTITHERM_LP_WORKERS=1.

Usage: python research/triangle/maxhs.py <dev-output-dir> [budget_s]
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint

sys.path.insert(0, ".")
from CertiTherm.synthesis import _insert_minimal_cut

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/diag150b")
BUDGET_S = float(sys.argv[2]) if len(sys.argv) > 2 else 7200.0
WORKLOAD = sys.argv[3] if len(sys.argv) > 3 else "resnet50"
CAND = int(sys.argv[4]) if len(sys.argv) > 4 else 0


def _load_strong_oracle():
    """Import strong_oracle.py without letting its module-level argv parsing
    consume ours; then point its OUTPUT at ours."""
    saved = sys.argv
    sys.argv = ["strong_oracle", str(OUTPUT), "0", "uniform", WORKLOAD, str(CAND)]
    try:
        spec = importlib.util.spec_from_file_location(
            "strong_oracle", "research/triangle/strong_oracle.py")
        so = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(so)
    finally:
        sys.argv = saved
    so.OUTPUT, so.WORKLOAD, so.CAND_INDEX = OUTPUT, WORKLOAD, CAND
    return so


def _milp_cover(C, cost):
    """Solve the min-cost hitting set to optimality. Returns
    (cover, dual_bound, gap, cover_cost) with integrality and coverage checked,
    or (None, ...) on failure. mip_rel_gap=0 forces a proved optimum so the
    exactness argument (OPT_cuts == cover_cost) can hold."""
    n = cost.shape[0]
    m = milp(c=cost, constraints=LinearConstraint(C, lb=np.ones(C.shape[0]), ub=np.inf),
             integrality=np.ones(n), bounds=Bounds(0, 1),
             options={"mip_rel_gap": 0.0})
    if not m.success or m.x is None:
        return None, None, None, None
    x = np.round(m.x)
    if np.max(np.abs(m.x - x)) > 1e-6:          # not integral -> untrusted
        return None, None, None, None
    if np.min(C @ x) < 1 - 1e-9:                # does not hit every cut
        return None, None, None, None
    cover = np.flatnonzero(x > 0.5)
    cover_cost = float(cost[cover].sum())
    return cover, getattr(m, "mip_dual_bound", None), getattr(m, "mip_gap", None), cover_cost


def main():
    # The verify loop uses run_highs directly (not the worker pool), so it is
    # unaffected by CERTITHERM_LP_WORKERS; no value is asserted.
    so = _load_strong_oracle()
    cand, actions, cid = so.candidate_zero()
    cost = np.array([a.cost for a in actions], dtype=float)
    av = np.asarray([a.vector for a in actions], dtype=float)
    w = np.ones(len(actions))                       # uniform L1 (strong cuts)
    full_registry = float(cost.sum())               # a valid feasible UB

    npz = OUTPUT / f"strong_antichain_uniform_{WORKLOAD}_c{CAND}.npz"
    cuts, masks = [], []
    if npz.exists():
        with np.load(npz, allow_pickle=False) as d:
            for row in d["cuts"]:
                _insert_minimal_cut(cuts, np.asarray(row, float), masks)
    print(f"{cid} ({WORKLOAD} c{CAND}): {len(actions)} actions, full-registry UB "
          f"{full_registry:.0f}, warm-start cuts={len(cuts)}, budget={BUDGET_S:.0f}s",
          flush=True)
    if not cuts:
        print("no warm-start antichain found -> regenerate with strong_oracle first"); return

    deadline = time.perf_counter() + BUDGET_S
    round_i = 0
    L = None
    seen_covers = set()
    while time.perf_counter() < deadline:
        round_i += 1
        C = np.asarray(cuts, dtype=float)
        cover, L, gap, cover_cost = _milp_cover(C, cost)
        if cover is None:
            print("MILP failed / non-integral / incomplete cover -> UNRESOLVED"); return

        fp = tuple(cover.tolist())
        if fp in seen_covers:
            print(f"round {round_i}: cover repeated -> a cut failed to eliminate it, "
                  f"UNRESOLVED (numerical inconsistency)"); return
        seen_covers.add(fp)

        # verify the candidate cover with the strong oracle; collect minimal cuts.
        # `strong_collision_spec` returns None only for a PROVED-infeasible cell
        # (status 2) and raises on any other status, so collisions==0 means every
        # cell is proved collision-free.
        base = so._base_problem(cand.power, cand.thermal, actions, tuple(cover), so.MARGIN_K)
        added = 0
        collisions = 0
        unknown = 0
        zero_w = np.zeros(len(actions))
        for spec in so._specs(base):
            # The L1 objective makes the strong LP numerically fragile on some
            # cells (HiGHS status 15). Fall back to the zero-objective solve --
            # SAME feasible set, no boundary-seeking degeneracy -- so a solver
            # hiccup on one cell degrades that cut to max-support, never crashes
            # the run. A cell is UNKNOWN only if both fail; convergence then
            # cannot be proved (tri-state, Codex F4).
            try:
                pair = so.strong_collision_spec(base, spec, av, w)
            except RuntimeError:
                try:
                    pair = so.strong_collision_spec(base, spec, av, zero_w)
                except RuntimeError:
                    unknown += 1
                    continue
            if pair is None:
                continue
            collisions += 1
            cut = so._cut_from_pair(pair, actions, cover)     # exclude selected + > tolerance
            if not cut.any():
                print(f"round {round_i}: UNSYNTHESIZABLE (a pair no action separates)"); return
            assert not (cut.astype(bool)[list(cover)]).any(), "cut overlaps the cover"
            if _insert_minimal_cut(cuts, cut, masks):
                added += 1

        if collisions == 0 and unknown > 0:
            print(f"round {round_i}: cover collision-free on solved cells but {unknown} "
                  f"cells UNRESOLVED (solver status) -> cannot PROVE feasibility. "
                  f"L(dual)={L}, not closing.")
            return
        if collisions == 0:
            # Feasible cover. EXACT only if the restricted-MILP optimum is proved
            # equal to this cover's cost (gap 0), else it is only an upper bound.
            exact = (gap is not None and gap <= 1e-12
                     and L is not None and abs(L - cover_cost) < 0.5)
            print(f"\nCONVERGED at round {round_i}: cover feasible, cost {cover_cost:.0f}.")
            if exact:
                print(f"  MILP dual {L} == cover_cost (gap {gap}) -> C*(arch_b) = "
                      f"{cover_cost:.0f} EXACTLY; interval CLOSED.")
            else:
                print(f"  MILP dual {L}, gap {gap}: feasible U = {cover_cost:.0f}, but "
                      f"optimality NOT proved (gap>0 or dual!=cover) -> interval "
                      f"[{L}, {cover_cost:.0f}], not exact.")
            return
        print(f"round {round_i}: cover_cost={cover_cost:.0f} L(dual)={L} gap={gap} "
              f"collisions={collisions} unknown={unknown} new_cuts={added} "
              f"total={len(cuts)}", flush=True)
        if added == 0:
            print("colliding cover but no new cut (cut hit by cover / dominated / "
                  "semantics disagree) -> UNRESOLVED")
            return

    print(f"\nbudget hit: not converged after {round_i} rounds.")
    print(f"  last restricted-MILP dual bound L = {L} (valid lower bound on C*)")
    print(f"  full-registry UB = {full_registry:.0f}; pair L with the deletion U.")
    if L:
        print(f"  interval [{L}, {full_registry:.0f}] = {full_registry / L:.2f}x "
              f"(tighten U with upper_bound.py)")


if __name__ == "__main__":
    main()
