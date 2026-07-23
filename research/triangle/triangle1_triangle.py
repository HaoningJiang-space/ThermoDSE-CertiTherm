"""Primal-dual-integer triangle on one real dev candidate.

Question: is the certified lower bound of ~2 a genuinely weak LP relaxation, or
a defect in `_anytime_lower_bound`? The two are indistinguishable from the
result table but not from the cut matrix itself.

Method: reconstruct candidate 0 of resnet50/default (the candidate every dev
query stalls on), run the real constraint-generation loop under a wall budget,
snapshot the antichain the loop actually holds, then compute three numbers over
the SAME cuts and the same costs:

  primal LP optimum      -- min c.x s.t. Cx>=1, 0<=x<=1   (scipy HiGHS)
  _anytime_lower_bound   -- the method's shipped Lagrangian bound
  restricted-master MILP -- min c.x s.t. Cx>=1, x in {0,1} (scipy HiGHS MILP)

plus the support-size distribution |S_e| (row sums of C), against the ceiling
L <= C_total / s_min derived from dual feasibility.

Interpretation:
  primal LP ~= 2                         -> relaxation genuinely weak on these cuts
  primal LP large but anytime returns 2  -> the bound implementation is wrong
  MILP >> LP                             -> integrality gap is the story
  MILP ~= LP ~= 2                        -> even the integer optimum over these
                                            cuts is tiny; C* really may be small
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import linprog, milp, Bounds, LinearConstraint

sys.path.insert(0, ".")

import CertiTherm.synthesis as syn
from CertiTherm.experiments import (
    ROOT,
    _call_under_budget,
    _capture,
    _measurement_costs,
    _ordered_architectures,
    _power_space,
    _registry_split,
    _rows,
    load_family,
)
from CertiTherm.measurements import build_measurement_library

# --- config ----------------------------------------------------------------
SPLIT = "dev_v3"
OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "diag150b"
WORKLOAD = "resnet50"
BUDGET_S = float(sys.argv[2]) if len(sys.argv) > 2 else 150.0


def reconstruct_candidate_zero():
    registry_split = _registry_split(SPLIT)
    architectures = sorted(
        (r for r in _rows(ROOT / "experiments" / "architectures.tsv")
         if r["split"] == registry_split),
        key=lambda r: int(r["rank"]),
    )
    packages = _rows(ROOT / "experiments" / "packages.tsv")
    default_package = next(p for p in packages if p["package_id"] == "default")
    workloads = [r for r in _rows(ROOT / "experiments" / "workloads.tsv")
                 if r["split"] == registry_split]
    workload = next(w for w in workloads if w["workload_id"] == WORKLOAD)
    costs = _measurement_costs()

    captures = {
        (WORKLOAD, arch["architecture_id"]):
            _capture(arch, workload, default_package, OUTPUT)
        for arch in architectures
    }
    ordered = _ordered_architectures(WORKLOAD, architectures, captures)
    arch0 = ordered[0]

    from CertiTherm.core import CandidateSpace
    power, blocks, placed, floorplan = _power_space(captures[(WORKLOAD, arch0["architecture_id"])])
    operator_path = OUTPUT / "operators" / f"{arch0['architecture_id']}--default.npz"
    family, operator_blocks = load_family(operator_path)
    assert blocks == operator_blocks, "power/operator block mismatch"
    candidate = CandidateSpace(arch0["architecture_id"], power, family)
    actions = build_measurement_library(
        arch0["architecture_id"], blocks, floorplan, arch0, costs
    )
    return candidate, tuple(actions), arch0["architecture_id"]


def main():
    candidate, actions, cand_id = reconstruct_candidate_zero()
    n = len(actions)
    cost_vec = np.array([a.cost for a in actions], dtype=float)
    print(f"candidate 0 = {cand_id}: {n} local actions, "
          f"C_total = {cost_vec.sum():.0f}, dim = {candidate.power.dimension}")

    # Snapshot the antichain the real loop holds, without touching core code.
    real_insert = syn._insert_minimal_cut
    latest = {"cuts": []}

    def snapshotting_insert(cuts, cut, masks=None, ledger=None):
        result = real_insert(cuts, cut, masks, ledger)
        latest["cuts"] = [c.copy() for c in cuts]
        return result

    syn._insert_minimal_cut = snapshotting_insert
    try:
        plan, seconds, error = _call_under_budget(
            lambda: syn.synthesize_minimum_observation(
                candidate.power, candidate.thermal, actions,
            ),
            BUDGET_S,
            f"{BUDGET_S}s triangle budget exhausted",
        )
    finally:
        syn._insert_minimal_cut = real_insert

    cuts = latest["cuts"]
    status = plan.status if plan is not None else f"ESCAPED: {error}"
    print(f"ran {seconds:.1f}s -> status={status}, "
          f"reported lower_bound={getattr(plan, 'lower_bound', None)}, "
          f"antichain size = {len(cuts)}")
    if not cuts:
        print("NO CUTS -- cannot form the triangle"); return

    C = np.asarray(cuts, dtype=float)
    assert set(np.unique(C)).issubset({0.0, 1.0}), "cuts not binary"
    assert C.shape[1] == n, f"cut width {C.shape[1]} != {n} actions"
    support = C.sum(axis=1)
    assert support.min() > 0, "an empty cut escaped UNSYNTHESIZABLE"

    print("\n--- support-size distribution |S_e| (actions per cut) ---")
    print(f"  min={support.min():.0f}  mean={support.mean():.1f}  "
          f"median={np.median(support):.0f}  max={support.max():.0f}")
    s_min = support.min()
    print(f"  ceiling  L <= C_total/s_min = {cost_vec.sum()/s_min:.2f}")

    # 1. primal LP
    lp = linprog(cost_vec, A_ub=-C, b_ub=-np.ones(C.shape[0]),
                 bounds=[(0.0, 1.0)] * n, method="highs")
    print("\n--- the triangle (same cuts, same costs) ---")
    print(f"  primal LP optimum       = {lp.fun:.4f}  (success={lp.success})")

    # 2. the method's shipped bound
    ab = syn._anytime_lower_bound(cost_vec, cuts)
    print(f"  _anytime_lower_bound    = {ab}")

    # 3. restricted-master MILP
    t0 = time.perf_counter()
    m = milp(
        c=cost_vec,
        constraints=LinearConstraint(C, lb=np.ones(C.shape[0]), ub=np.inf),
        integrality=np.ones(n),
        bounds=Bounds(0, 1),
    )
    milp_s = time.perf_counter() - t0
    milp_opt = m.fun if m.success else None
    print(f"  restricted-master MILP  = {milp_opt}  "
          f"(success={m.success}, {milp_s:.1f}s)")

    print("\n--- verdict ---")
    if lp.success and ab is not None:
        if abs(lp.fun - ab) < 1e-6:
            print(f"  primal LP == anytime bound ({lp.fun:.3f}): the bound code is FAITHFUL")
        elif ab > lp.fun + 1e-6:
            print(f"  anytime ({ab}) > primal LP ({lp.fun:.3f}): INVALID -- bound bug")
        else:
            print(f"  anytime ({ab}) < primal LP ({lp.fun:.3f}): loose but valid")
    if lp.success and milp_opt is not None:
        gap = milp_opt / lp.fun if lp.fun > 0 else float("inf")
        print(f"  integrality gap MILP/LP = {gap:.1f}x  (LP={lp.fun:.3f}, MILP={milp_opt:.3f})")
    if milp_opt is not None:
        print(f"  reference: width/dual contracts ~4100-4174, full registry 5250")
        print(f"  -> integer optimum over {len(cuts)} discovered cuts = {milp_opt:.1f}")


if __name__ == "__main__":
    main()
