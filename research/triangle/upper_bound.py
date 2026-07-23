"""Upper-bound closure by verified top-down deletion (freeze-v4 item 6).

Closes the interval [832, 1846] for candidate arch_b from above. From the full
243-action cover (exhaustively verified collision-free), delete actions and keep
only deletions that stay collision-free under exact separation. The result is an
oracle-verified feasible cover whose cost is a valid UPPER bound on C*.

Design reflects a Codex design review:
- SOUNDNESS: every accepted cover is oracle-verified collision-free; a rejected
  deletion is restored, and feasibility is monotone under adding actions, so U
  is always a genuine feasible (decision-certifying) contract. A final explicit
  re-verify is done before publishing.
- EFFICIENCY: adaptive group deletion (delta-debugging) removes redundant chunks
  in one oracle call and only splits on failure -- far fewer calls than 243
  single deletions when much of the registry is redundant.
- HEURISTIC HONESTY: cost-descending deletion yields an ORDER-DEPENDENT
  inclusion-minimal cover, NOT the minimum-cost cover (weighted hitting set has
  no such guarantee). U is a valid upper bound, not a proof of C*.
- CLOSURE: three cases -- closed (U == L within the integer cost lattice),
  bounded gap (U > L), or CONSISTENCY FAILURE (U < L, which must never happen
  and would indicate a convention mismatch, not exactness).
- For an EXACT-MINIMUM proof, the MaxHS loop (MILP candidate + oracle verify) is
  the primary method; this deletion supplies an incumbent / bounded-gap U.

NON-CLAIM diagnostic. Requires CERTITHERM_LP_WORKERS=1 (asserted).

Usage: python research/triangle/upper_bound.py <dev-output-dir> [budget_s]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

import CertiTherm.synthesis as syn
from CertiTherm.experiments import (
    ROOT, _capture, _measurement_costs, _ordered_architectures,
    _power_space, _registry_split, _rows, load_family,
)
from CertiTherm.core import CandidateSpace
from CertiTherm.measurements import build_measurement_library

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "diag150b"
BUDGET_S = float(sys.argv[2]) if len(sys.argv) > 2 else 14400.0
WORKLOAD, CAND, EXPECT_ARCH = "resnet50", 0, "arch_b"
L_STRONG = 832                      # solver-asserted MILP lower bound (D6)
MARGIN_K, FEAS_TOL = 1e-4, 1e-10


def candidate():
    assert os.environ.get("CERTITHERM_LP_WORKERS") == "1", "run with CERTITHERM_LP_WORKERS=1"
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
    assert a0["architecture_id"] == EXPECT_ARCH, (
        f"candidate {CAND} is {a0['architecture_id']}, expected {EXPECT_ARCH} "
        "-- ordering changed; the lower bound was established for arch_b")
    power, blocks, placed, floor = _power_space(caps[(WORKLOAD, a0["architecture_id"])])
    fam, ob = load_family(OUTPUT / "operators" / f"{a0['architecture_id']}--default.npz")
    assert blocks == ob
    cand = CandidateSpace(a0["architecture_id"], power, fam)
    actions = tuple(build_measurement_library(a0["architecture_id"], blocks, floor, a0, costs))
    return cand, actions, a0["architecture_id"]


def collision_free(cand, actions, cover) -> bool:
    """True iff `cover` leaves NO SAFE/REJECT collision. `_collisions` is
    exhaustive over every reject cell and raises (never returns []) on a worker
    failure, so an empty batch means genuinely no collision exists."""
    batch = syn._collisions(cand.power, cand.thermal, actions, tuple(sorted(cover)),
                            MARGIN_K, FEAS_TOL, None)
    return len(batch) == 0


def main():
    cand, actions, cid = candidate()
    cost = np.array([a.cost for a in actions], dtype=float)
    n = len(actions)
    deadline = time.perf_counter() + BUDGET_S
    calls = [0]

    def feasible(cover) -> bool:
        calls[0] += 1
        return collision_free(cand, actions, cover)

    print(f"{cid}: {n} actions, C_total={cost.sum():.0f}, budget={BUDGET_S:.0f}s", flush=True)
    t0 = time.perf_counter()
    if not feasible(set(range(n))):
        print("full registry NOT collision-free -> UNSYNTHESIZABLE"); return
    print(f"full registry collision-free ({time.perf_counter()-t0:.0f}s), U0={cost.sum():.0f}",
          flush=True)

    cover = set(range(n))
    order = sorted(range(n), key=lambda i: (-cost[i], -i))   # expensive first
    completed = True
    i, chunk = 0, min(64, n)                                 # adaptive group size
    while i < len(order):
        if time.perf_counter() > deadline:
            completed = False
            print(f"[soft budget hit at position {i}/{n}]", flush=True); break
        group = set(order[i : i + chunk])
        if feasible(cover - group):
            cover -= group                                  # whole chunk redundant
            i += len(group)
            chunk = min(chunk * 2, len(order) - i or 1)     # grow on success
            print(f"  -{len(group)} actions; cover={len(cover)} U={sum(cost[j] for j in cover):.0f} "
                  f"(calls={calls[0]})", flush=True)
        elif len(group) == 1:
            i += 1                                           # necessary, keep
        else:
            chunk = max(1, chunk // 2)                       # shrink, retry position

    # Codex F4: publish only an EXPLICITLY re-verified cover.
    if not feasible(cover):
        print("FINAL RE-VERIFY FAILED -- not publishing"); return
    U = sum(cost[j] for j in cover)

    kind = "inclusion-minimal" if completed else "partial (budget-truncated)"
    print(f"\n--- result ({kind}, {calls[0]} oracle calls) ---")
    print(f"verified feasible cover: {len(cover)} actions, U = {U:.0f}")
    # Codex F5: three-case closure on the integer cost lattice.
    if abs(U - L_STRONG) < 0.5:
        print(f"U == L ({L_STRONG}) -> interval CLOSED, C*(arch_b) = {U:.0f}")
    elif U > L_STRONG:
        print(f"bounded gap: interval [{L_STRONG}, {U:.0f}] = {U/L_STRONG:.2f}x "
              f"(down from 1846/{L_STRONG} = {1846/L_STRONG:.2f}x)")
    else:
        print(f"CONSISTENCY FAILURE: U={U:.0f} < L={L_STRONG} -- convention mismatch, "
              f"NOT a valid exactness result")

    # Codex F11: machine-readable manifest with stable action IDs.
    manifest = {
        "candidate": cid, "workload": WORKLOAD,
        "cover_action_ids": sorted(actions[j].action_id for j in cover),
        "U": U, "L_strong_solver_asserted": L_STRONG,
        "cover_size": len(cover), "completed_sweep": completed,
        "oracle_calls": calls[0], "margin_k": MARGIN_K, "feas_tol": FEAS_TOL,
        "lp_workers": os.environ.get("CERTITHERM_LP_WORKERS"),
    }
    (OUTPUT / "upper_bound_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"manifest -> {OUTPUT / 'upper_bound_manifest.json'}")


if __name__ == "__main__":
    main()
