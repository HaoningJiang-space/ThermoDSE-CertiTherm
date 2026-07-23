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
L_FULL_REGISTRY_UB = 1846


def _load_strong_oracle():
    """Import strong_oracle.py without letting its module-level argv parsing
    consume ours; then point its OUTPUT at ours."""
    saved = sys.argv
    sys.argv = ["strong_oracle", str(OUTPUT)]
    try:
        spec = importlib.util.spec_from_file_location(
            "strong_oracle", "research/triangle/strong_oracle.py")
        so = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(so)
    finally:
        sys.argv = saved
    so.OUTPUT = OUTPUT
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
    assert os.environ.get("CERTITHERM_LP_WORKERS") == "1", "run with CERTITHERM_LP_WORKERS=1"
    so = _load_strong_oracle()
    cand, actions, cid = so.candidate_zero()
    cost = np.array([a.cost for a in actions], dtype=float)
    av = np.asarray([a.vector for a in actions], dtype=float)
    w = np.ones(len(actions))                       # uniform L1 (strong cuts)

    npz = OUTPUT / "strong_antichain_uniform_resnet50_c0.npz"
    cuts, masks = [], []
    if npz.exists():
        with np.load(npz, allow_pickle=False) as d:
            for row in d["cuts"]:
                _insert_minimal_cut(cuts, np.asarray(row, float), masks)
    print(f"{cid}: {len(actions)} actions, warm-start cuts={len(cuts)}, budget={BUDGET_S:.0f}s",
          flush=True)

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
        for spec in so._specs(base):
            pair = so.strong_collision_spec(base, spec, av, w)
            if pair is None:
                continue
            collisions += 1
            cut = so._cut_from_pair(pair, actions, cover)     # exclude selected + > tolerance
            if not cut.any():
                print(f"round {round_i}: UNSYNTHESIZABLE (a pair no action separates)"); return
            assert not (cut.astype(bool)[list(cover)]).any(), "cut overlaps the cover"
            if _insert_minimal_cut(cuts, cut, masks):
                added += 1

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
              f"collisions={collisions} new_cuts={added} total={len(cuts)}", flush=True)
        if added == 0:
            print("colliding cover but no new cut (cut hit by cover / dominated / "
                  "semantics disagree) -> UNRESOLVED")
            return

    print(f"\nbudget hit: not converged after {round_i} rounds.")
    print(f"  last restricted-MILP dual bound L = {L} (valid lower bound on C*)")
    print(f"  U = 1846 (full-registry cover, verified collision-free in triangle3/upper_bound)")
    if L:
        print(f"  interval [{L}, {L_FULL_REGISTRY_UB}] = {L_FULL_REGISTRY_UB / L:.2f}x")


if __name__ == "__main__":
    main()
