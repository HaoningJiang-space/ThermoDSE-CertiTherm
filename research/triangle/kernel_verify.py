"""Production-oracle equivalence test for the thermal kernel (CertiTherm-F step 1
gate). The audit proved SAFE/REJECT rows removable using its OWN reconstruction of
P; a wrong-P / wrong-floor bug would pass every LP-level check. This closes that
boundary empirically (adversarial-review "four-variant" test).

Plan:
  1. Reconstruct the candidate; compute the kernel survivor sets (canonical order).
  2. Build a pair-collision LP REPLICA using the oracle's own `_pair_rows` and SAFE
     row / REJECT floor conventions, parameterised by a SAFE-row subset and a
     REJECT-cell subset.
  3. ANCHOR: for every tested selection, the replica with FULL SAFE + FULL REJECT
     must agree on collision EXISTENCE with the production `_collisions` oracle.
     (This proves the replica == production.)
  4. FOUR VARIANTS: full/full, kernelSAFE/fullREJECT, fullSAFE/kernelREJECT,
     kernelSAFE/kernelREJECT must all agree on existence for every selection.
     Dropping SAFE rows can only CREATE false collisions; dropping REJECT cells can
     only HIDE collisions -- testing both singly (not only combined) prevents the
     two errors cancelling.

Revealing selections (review): full registry (collision-free), empty (colliding),
full-minus-one (near the collision boundary), and random partials.

NON-CLAIM float test. Usage:
  python research/triangle/kernel_verify.py <out> <workload> <cand> [n_partial]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, ".")

import CertiTherm.synthesis as syn
from CertiTherm.synthesis import _pair_rows, _robust_safe_rows, _collisions
from CertiTherm.experiments import (
    ROOT, _capture, _measurement_costs, _ordered_architectures,
    _power_space, _registry_split, _rows, load_family,
)
from CertiTherm.core import CandidateSpace
from CertiTherm.measurements import build_measurement_library

import kernel_audit                                            # same-dir import
from kernel_audit import Polytope, safe_audit, reject_audit
# kernel_audit reads TAU from sys.argv[4] at import; here argv[4] is n_partial, so
# pin the audit margin explicitly (the greedy audits use kernel_audit.TAU).
kernel_audit.TAU = 1e-6

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "diag150b"
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
CAND = int(sys.argv[3]) if len(sys.argv) > 3 else 1
N_PARTIAL = int(sys.argv[4]) if len(sys.argv) > 4 else 12
MARGIN_K, FEAS_TOL = 1e-4, 1e-10


def candidate_full():
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
    power, blocks, placed, floor = _power_space(caps[(WORKLOAD, a0["architecture_id"])])
    fam, ob = load_family(OUTPUT / "operators" / f"{a0['architecture_id']}--default.npz")
    assert blocks == ob
    cand = CandidateSpace(a0["architecture_id"], power, fam)
    actions = tuple(build_measurement_library(a0["architecture_id"], blocks, floor, a0, costs))
    return cand, actions, a0["architecture_id"]


def reject_table(thermal):
    rows, floors = [], []
    for m in range(thermal.response_k_per_w.shape[0]):
        for q in range(thermal.response_k_per_w.shape[1]):
            rows.append(thermal.response_k_per_w[m, q])
            floors.append(thermal.limit_k + MARGIN_K - thermal.error_k[m]
                          - thermal.ambient_k[m, q])
    return np.asarray(rows, float), np.asarray(floors, float)


class Replica:
    """Faithful pair-collision LP over (p_safe, p_unsafe), parameterised by SAFE-row
    and REJECT-cell subsets. Uses the oracle's `_pair_rows` for P exactly."""
    def __init__(self, cand, actions):
        self.n = cand.power.dimension
        self.a_eq, self.b_eq, self.base_a_ub, self.base_b_ub = _pair_rows(cand.power)
        self.bounds = tuple(zip(cand.power.lower_w, cand.power.upper_w)) * 2
        self.srows, self.srhs = _robust_safe_rows(cand.thermal, MARGIN_K)
        self.rrows, self.rfloors = reject_table(cand.thermal)
        self.actions = actions

    def _common(self, selection, safe_idx):
        n = self.n
        safe = np.hstack((np.asarray(self.srows)[safe_idx], np.zeros((len(safe_idx), n))))
        chunks, rhs = [self.base_a_ub, safe], [self.base_b_ub, np.asarray(self.srhs)[safe_idx]]
        for i in selection:
            a = self.actions[i]
            delta = np.concatenate((a.vector, -a.vector))
            chunks += [delta, -delta]; rhs += [np.array([a.tolerance]), np.array([a.tolerance])]
        return np.vstack(chunks), np.concatenate([np.atleast_1d(r) for r in rhs])

    def collides(self, selection, safe_idx, reject_idx) -> bool:
        n = self.n
        a_ub_c, b_ub_c = self._common(selection, safe_idx)
        for k in reject_idx:
            reject_row = np.concatenate((np.zeros(n), -self.rrows[k]))
            a_ub = np.vstack((a_ub_c, reject_row))
            b_ub = np.append(b_ub_c, -self.rfloors[k])
            r = linprog(np.zeros(2 * n), A_ub=a_ub, b_ub=b_ub, A_eq=self.a_eq, b_eq=self.b_eq,
                        bounds=self.bounds, method="highs",
                        options={"primal_feasibility_tolerance": FEAS_TOL})
            if r.status == 0:
                return True
        return False


def main():
    cand, actions, cid = candidate_full()
    n = len(actions)
    P = Polytope(cand.power)
    srows, srhs = _robust_safe_rows(cand.thermal, MARGIN_K)
    srows = np.asarray(srows, float); srhs = np.asarray(srhs, float)
    rrows, rfloors = reject_table(cand.thermal)

    safe_surv, _ = safe_audit(P, srows, srhs, list(range(len(srows))))
    rej_surv, _, _ = reject_audit(P, rrows, rfloors, list(range(len(rrows))))
    safe_full = list(range(len(srows))); safe_kern = sorted(safe_surv)
    rej_full = list(range(len(rrows))); rej_kern = sorted(rej_surv)
    print(f"{cid} ({WORKLOAD} c{CAND}): actions={n}, SAFE {len(safe_full)}->{len(safe_kern)}, "
          f"REJECT {len(rej_full)}->{len(rej_kern)}", flush=True)

    rep = Replica(cand, actions)

    rng = np.random.RandomState(7)
    selections = [("full", tuple(range(n))), ("empty", ())]
    for i in rng.choice(n, size=min(N_PARTIAL, n), replace=False):
        selections.append((f"full-minus-{i}", tuple(j for j in range(n) if j != i)))
    for s in range(6):
        k = rng.randint(1, n)
        selections.append((f"rand{s}", tuple(sorted(rng.choice(n, size=k, replace=False)))))

    anchor_fail = variant_fail = 0
    print(f"\n{'selection':22} prod  ff  kf  fk  kk   anchor  variants")
    for name, sel in selections:
        prod = len(_collisions(cand.power, cand.thermal, actions, tuple(sorted(sel)),
                               MARGIN_K, FEAS_TOL, None)) > 0
        ff = rep.collides(sel, safe_full, rej_full)
        kf = rep.collides(sel, safe_kern, rej_full)
        fk = rep.collides(sel, safe_full, rej_kern)
        kk = rep.collides(sel, safe_kern, rej_kern)
        anchor_ok = (ff == prod)
        var_ok = (ff == kf == fk == kk)
        anchor_fail += (not anchor_ok); variant_fail += (not var_ok)
        print(f"{name:22} {int(prod)}     {int(ff)}   {int(kf)}   {int(fk)}   {int(kk)}    "
              f"{'ok' if anchor_ok else 'MISMATCH'}   {'ok' if var_ok else 'MISMATCH'}")

    print(f"\nanchor (replica==oracle) failures: {anchor_fail}/{len(selections)}")
    print(f"four-variant (kernel==full) failures: {variant_fail}/{len(selections)}")
    print("VERDICT:", "PASS -- kernel preserves collision existence"
          if anchor_fail == 0 and variant_fail == 0 else "FAIL -- kernel changes collisions")


if __name__ == "__main__":
    main()
