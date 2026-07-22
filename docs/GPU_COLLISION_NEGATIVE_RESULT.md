# GPU collision proposal gate — negative result

Date: 2026-07-22. Decision: **REJECT from method-freeze-v3.1**.

The evaluated method is an FP64 batched PDHG proposal engine over one shared
constraint matrix and one reject row per cell. A persistent process owns the
CUDA context. Feasible points and residual-aware Farkas rays are admitted only
after an independent conservative CPU interval check; all other cells fall
back to HiGHS.

Synthetic boundary batches (1, 7, 31, 32, 33, 127, 128, 129, 541 cells)
produced zero incorrectly accepted cells and zero fallback. The 541-cell
solver-only run reached roughly 3.4–5.1x over sequential HiGHS depending on
system load. The 33-cell partial-warp case passed CUDA memcheck with zero
errors. The reduction kernel uses 18 registers, 64 bytes shared memory after
warp-shuffle reduction, and no spills on sm_80.

The decisive registered dev case used the existing `arch_b` / `standard`
HotSpot operator: 227 blocks, 243 selected actions, 681 rejecting model/point
cells. CPU HiGHS and the proof-gated GPU+fallback path both concluded that no
SAFE/REJECT collision exists. The fixed iteration ladder was:

| PDHG iterations | Infeasible rays accepted | Fallback | Fallback rate | GPU proposal wall |
|---:|---:|---:|---:|---:|
| 1,000 | 131/681 | 550 | 80.8% | 0.884 s |
| 2,000 | 200/681 | 481 | 70.6% | 0.973 s |
| 5,000 | 278/681 | 403 | 59.2% | 2.747 s |
| 10,000 | 315/681 | 366 | 53.7% | 5.298 s |

At 1,000 iterations, end-to-end GPU+fallback took 45.37 s versus 54.79 s for
CPU-only (`1.21x`), far below the 3x DSOS target and far above the 10%
fallback ceiling. The 10,000-iteration endpoint still failed decisively, so
the preregistered stop rule was applied rather than tuning further.

This does not show that GPU optimization is unsuitable. It shows that a
first-order approximate feasibility method is weak at producing checkable
infeasibility rays for the highly constrained, near-degenerate negative tail
that dominates exact DSOS. The production v3.1 path therefore uses the
15-worker CPU method scheduler and the unchanged HiGHS separation oracle.
The CUDA code remains isolated for reproducibility and future work on a GPU
simplex/IPM or verified homogeneous self-dual embedding.
