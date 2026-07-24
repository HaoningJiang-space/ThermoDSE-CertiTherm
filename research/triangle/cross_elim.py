"""Shadow experiment: the CROSS-ELIMINATION matrix (cooperative-IHS go/no-go).

The review's decisive question before building any multi-cover machinery:

    when a physical witness cut is found while verifying one exact-face cover,
    how many OTHER exact-face covers does that same cut already invalidate?

Interpretation (review):
  * high cross-elimination  -> cooperative PRUNING pays (drop queued candidates with
    no oracle call); but verifying all K concurrently would waste LPs.
  * cross-elimination ~= 1  -> batching cannot reduce oracle work at all; it is only
    a parallelism trick, and the plateau is a conflict-STRENGTH problem.
  * enumeration time ~ oracle time -> abandon no-good enumeration entirely.

Soundness notes (review):
  * Temporary no-goods are SEARCH ONLY. They never enter a bound or a ledger. This
    script never publishes L or a cut; it only measures.
  * Uses the EXACT binary-assignment no-good
        sum_{a in x} x_a - sum_{a not in x} x_a <= |x| - 1
    (the one-sided form would also exclude every SUPERSET of x).
  * Costs here are 1/2/4/8, i.e. integral, so the exact optimum face c'x == L_t is
    well defined without an epsilon.

A cut is the index set S of actions separating a witness; a cover x FAILS to hit it
iff x ∩ S = {} -- that is exactly what "this cut invalidates that cover" means.

NON-CLAIM measurement.
Usage: python research/triangle/cross_elim.py <out> <workload> <cand> [K]
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
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
CAND = int(sys.argv[3]) if len(sys.argv) > 3 else 1
K = int(sys.argv[4]) if len(sys.argv) > 4 else 8


def _load_strong_oracle():
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


def _solve_master(C, cost, extra_rows, extra_ub, face_cost=None):
    """Min-cost hitting set over cuts C, plus TEMPORARY no-good rows and (optionally)
    the exact-face equality c'x == face_cost. Returns (cover_indices, optimum)."""
    n = cost.shape[0]
    rows = [C]
    lb = [np.ones(C.shape[0])]
    ub = [np.full(C.shape[0], np.inf)]
    if extra_rows:
        rows.append(np.asarray(extra_rows))
        lb.append(np.full(len(extra_rows), -np.inf))
        ub.append(np.asarray(extra_ub, dtype=float))
    if face_cost is not None:
        rows.append(cost.reshape(1, -1))
        lb.append(np.array([face_cost]))
        ub.append(np.array([face_cost]))
    cons = LinearConstraint(np.vstack(rows), lb=np.concatenate(lb), ub=np.concatenate(ub))
    m = milp(c=cost, constraints=cons, integrality=np.ones(n), bounds=Bounds(0, 1),
             options={"mip_rel_gap": 0.0})
    if not m.success or m.x is None:
        return None, None
    x = np.round(m.x)
    return np.flatnonzero(x > 0.5), float(cost[x > 0.5].sum())


def main():
    so = _load_strong_oracle()
    cand, actions, cid = so.candidate_zero()
    cost = np.array([a.cost for a in actions], dtype=float)
    av = np.asarray([a.vector for a in actions], dtype=float)
    w = np.ones(len(actions))
    n = len(actions)

    npz = OUTPUT / f"strong_antichain_uniform_{WORKLOAD}_c{CAND}.npz"
    cuts, masks = [], []
    if npz.exists():
        with np.load(npz, allow_pickle=False) as d:
            for row in d["cuts"]:
                _insert_minimal_cut(cuts, np.asarray(row, float), masks)
    if not cuts:
        print("no warm-start antichain -> run strong_oracle first"); return
    C = np.asarray(cuts, dtype=float)
    print(f"{cid} ({WORKLOAD} c{CAND}): {n} actions, {len(cuts)} warm-start cuts, K={K}",
          flush=True)

    base_cover, L_t = _solve_master(C, cost, [], [])
    if base_cover is None:
        print("master failed"); return
    print(f"master optimum L_t = {L_t:.0f}, |cover| = {len(base_cover)}", flush=True)

    # --- enumerate K distinct covers on the EXACT face c'x == L_t -----------
    t_enum0 = time.perf_counter()
    pool, nogood_rows, nogood_ub = [], [], []
    for _ in range(K):
        cov, val = _solve_master(C, cost, nogood_rows, nogood_ub, face_cost=L_t)
        if cov is None:
            break
        pool.append(frozenset(int(i) for i in cov))
        row = -np.ones(n); row[list(cov)] = 1.0          # EXACT assignment no-good
        nogood_rows.append(row); nogood_ub.append(len(cov) - 1.0)
    t_enum = time.perf_counter() - t_enum0
    print(f"enumerated {len(pool)} distinct exact-face covers in {t_enum:.1f}s", flush=True)
    if len(pool) < 2:
        print("fewer than 2 covers on the face -> batching is moot"); return

    # --- verify each cover, collect its witness cuts ------------------------
    t_ora0 = time.perf_counter()
    per_cover_cuts = []
    for idx, cov in enumerate(pool):
        base = so._base_problem(cand.power, cand.thermal, actions, tuple(sorted(cov)),
                                so.MARGIN_K)
        found = []
        for spec in so._specs(base):
            try:
                pair = so.strong_collision_spec(base, spec, av, w)
            except RuntimeError:
                continue
            if pair is None:
                continue
            cut = so._cut_from_pair(pair, actions, tuple(sorted(cov)))
            S = frozenset(int(i) for i in np.flatnonzero(cut))
            if S:
                found.append(S)
        per_cover_cuts.append(found)
        print(f"  cover {idx}: {len(found)} witness cuts", flush=True)
    t_oracle = time.perf_counter() - t_ora0

    # --- CROSS-ELIMINATION: cut from cover i vs every other pool cover ------
    elim_counts = []
    for i, found in enumerate(per_cover_cuts):
        for S in found:
            killed = sum(1 for j, cov in enumerate(pool) if j != i and not (cov & S))
            elim_counts.append(killed)
    if not elim_counts:
        print("no cuts found -> covers were collision-free"); return
    arr = np.array(elim_counts, dtype=float)
    others = len(pool) - 1
    print(f"\n--- CROSS-ELIMINATION ({len(arr)} cuts vs {others} other covers) ---")
    print(f"  covers invalidated per cut: mean={arr.mean():.2f} median={np.median(arr):.0f} "
          f"max={arr.max():.0f} of {others}")
    print(f"  cuts killing 0 others: {(arr == 0).mean():.1%}; "
          f"killing >= half: {(arr >= others / 2).mean():.1%}")
    print(f"  enumeration {t_enum:.1f}s vs oracle {t_oracle:.1f}s "
          f"(ratio {t_enum / max(t_oracle, 1e-9):.2f})")
    print(f"\nVERDICT: mean cross-elimination {arr.mean():.2f}/{others}. "
          f"{'HIGH -> cooperative pruning pays' if arr.mean() >= others / 2 else 'LOW -> batching cannot reduce oracle work; the plateau is a conflict-STRENGTH problem'}")


if __name__ == "__main__":
    main()
