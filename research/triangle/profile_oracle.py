"""Where does per-cell collision-LP time actually go?

Decides the next perf lever. Each cell's LP differs from the others by ONE row, but
`_solve_collision_spec` rebuilds the whole constraint matrix per cell
(`np.vstack((common_a_ub, reject_row))`) AND scipy.linprog rebuilds a fresh HiGHS
model from those arrays on every call. Only the first is fixable without adding a
dependency (highspy is absent from the pinned env).

Splits per-cell wall into:
  assembly  -- vstack/append of the augmented matrix
  solve     -- the linprog(method="highs") call
so we know whether buffer reuse is worth anything, or whether the solve (i.e. the
scipy model rebuild + simplex) dominates and only highspy can help.

NON-CLAIM measurement.
Usage: python research/triangle/profile_oracle.py <out> <workload> <cand> [cells]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, ".")

from CertiTherm.synthesis import _pair_rows, _robust_safe_rows
from CertiTherm.experiments import (
    ROOT, _capture, _measurement_costs, _ordered_architectures,
    _power_space, _registry_split, _rows, load_family,
)
from CertiTherm.measurements import build_measurement_library

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "diag150b"
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "transformer"
CAND = int(sys.argv[3]) if len(sys.argv) > 3 else 0
NCELLS = int(sys.argv[4]) if len(sys.argv) > 4 else 60
MARGIN_K, FEAS_TOL = 1e-4, 1e-10


def candidate():
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
    actions = tuple(build_measurement_library(a0["architecture_id"], blocks, floor, a0, costs))
    return power, fam, actions, a0["architecture_id"]


def main():
    power, thermal, actions, cid = candidate()
    n = power.dimension
    a_eq, b_eq, base_a_ub, base_b_ub = _pair_rows(power)
    srows, srhs = _robust_safe_rows(thermal, MARGIN_K)
    safe = np.hstack((np.asarray(srows), np.zeros_like(np.asarray(srows))))
    rows, rhs = [base_a_ub, safe], [base_b_ub, np.asarray(srhs)]
    for a in actions:                                   # full registry = collision-free
        d = np.concatenate((a.vector, -a.vector))
        rows += [d, -d]; rhs += [np.array([a.tolerance]), np.array([a.tolerance])]
    common_a_ub = np.vstack(rows)
    common_b_ub = np.concatenate([np.atleast_1d(r) for r in rhs])
    bounds = tuple(zip(power.lower_w, power.upper_w)) * 2
    obj = np.zeros(2 * n)
    resp = thermal.response_k_per_w
    specs = [(m, q) for m in range(resp.shape[0]) for q in range(resp.shape[1])][:NCELLS]

    print(f"{cid} ({WORKLOAD} c{CAND}): common_a_ub={common_a_ub.shape} "
          f"({common_a_ub.nbytes/1e6:.1f} MB), cells profiled={len(specs)}", flush=True)

    t_asm = t_solve = 0.0
    for (m, q) in specs:
        t0 = time.perf_counter()
        rrow = np.concatenate((np.zeros(n), -resp[m, q]))
        rrhs = -(thermal.limit_k + MARGIN_K - thermal.error_k[m] - thermal.ambient_k[m, q])
        A = np.vstack((common_a_ub, rrow))
        b = np.append(common_b_ub, rrhs)
        t1 = time.perf_counter()
        linprog(obj, A_ub=A, b_ub=b, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs",
                options={"primal_feasibility_tolerance": FEAS_TOL,
                         "dual_feasibility_tolerance": FEAS_TOL})
        t2 = time.perf_counter()
        t_asm += t1 - t0
        t_solve += t2 - t1

    tot = t_asm + t_solve
    print(f"  assembly (vstack/append) : {t_asm:.2f}s  ({t_asm/tot:6.1%})")
    print(f"  solve    (linprog/HiGHS) : {t_solve:.2f}s  ({t_solve/tot:6.1%})")
    print(f"  per cell: {tot/len(specs)*1000:.1f} ms  "
          f"(asm {t_asm/len(specs)*1000:.1f} ms, solve {t_solve/len(specs)*1000:.1f} ms)")

    # --- SPARSE: the matrix is stored dense, but is it? scipy re-converts every
    # entry per call, so if the structure is sparse, handing linprog a CSR matrix
    # removes that work. Compression-INDEPENDENT and needs no new dependency.
    from scipy.sparse import csr_matrix
    nnz = int(np.count_nonzero(common_a_ub))
    dens = nnz / common_a_ub.size
    print(f"\n  common_a_ub density: {nnz}/{common_a_ub.size} = {dens:.1%} nonzero")
    sp_common = csr_matrix(common_a_ub)
    t_sp = 0.0
    for (m, q) in specs:
        rrow = np.concatenate((np.zeros(n), -resp[m, q]))
        rrhs = -(thermal.limit_k + MARGIN_K - thermal.error_k[m] - thermal.ambient_k[m, q])
        from scipy.sparse import vstack as spvstack
        A = spvstack([sp_common, csr_matrix(rrow)], format="csr")
        b = np.append(common_b_ub, rrhs)
        t0 = time.perf_counter()
        linprog(obj, A_ub=A, b_ub=b, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs",
                options={"primal_feasibility_tolerance": FEAS_TOL,
                         "dual_feasibility_tolerance": FEAS_TOL})
        t_sp += time.perf_counter() - t0
    print(f"  solve (SPARSE A_ub)      : {t_sp:.2f}s  "
          f"({t_sp/len(specs)*1000:.1f} ms/cell)  speedup vs dense: {t_solve/t_sp:.2f}x")
    print(f"\nVERDICT: assembly is only {t_asm/tot:.1%}; the lever is the SOLVE. "
          f"Sparse A_ub gives {t_solve/t_sp:.2f}x on the solve with no new dependency.")


if __name__ == "__main__":
    main()
