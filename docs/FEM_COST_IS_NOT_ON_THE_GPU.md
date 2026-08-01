# The FEM reference is CPU-bound, and the GPU does 0.2 % of the work

MEASURED 2026-08-01, one archive design (`arxv008`, 23 blocks, 24 problems), n=192 mesh
(320 x 304 x 15 cells), one A800 through cuDSS. Instrumented via `LinearSolveReceipt`; the
postprocess figure is the unaccounted remainder inside the batch call.

**Corrected below.** The first version of this table attributed the whole 72.6 s unaccounted
remainder to the per-problem postprocess. Measuring the mesh build directly showed 39.1 s of it is
`_create_domain`, which runs inside the batch call but outside every timer the receipt exposes. The
qualitative conclusion is unchanged -- the GPU does 0.2 % -- but the target moved.

| phase | seconds | share | scaling |
| --- | --- | --- | --- |
| **mesh construction** | **39.1** | **35 %** | `O(C)`, once |
| **per-problem postprocess** | **~33.5** | **30 %** | `O(P C)` + `P` form compilations |
| **per-problem RHS assembly** | **23.0** | **21 %** | `O(P C)` |
| stiffness assembly | 6.6 | 6 % | `O(C)`, once |
| cuDSS plan | 6.6 | 6 % | once |
| cuDSS factorization | 1.7 | 2 % | once |
| host to device | 0.4 | 0 % | once |
| **GPU solves** | **0.2** | **0.2 %** | `O(nnz(L) P)` |

Total 111 s. Measured problem size: `C = 8 755 200` tetrahedra, `N = 1 566 480` P1 degrees of
freedom, `nnz(K) = 22 636 398` (14.5 per row), `nnz(M) = 35 020 800` (**exactly 4.0 per cell**, which
is the four vertices of a tetrahedron and confirms `M`'s structure).

## What this rules out

**Writing a CUDA kernel for the linear solve optimises 0.2 % of the run.** The batch design is
already right -- one factorisation serves every right-hand side, and 24 back-substitutions cost
0.2 s. There is nothing left to win there.

**It also rules out "the GPU is idle so add more GPU work".** The GPU is idle because it finished.

## Where the time actually goes, and why it should not exist

`solve_steady_heat_batch` loops over problems and, inside that loop, calls `fem.form(...)` twice --
once in `regional_integrals` and once for the convected-power functional. `fem.form` JIT-compiles a
UFL form. So a 182-problem operator build performs **364 form compilations and 364 assemblies over
a 1.4 M-cell mesh**.

Both quantities are **fixed linear functionals of the temperature field**:

* `integral_r T dx` for each region `r` -- a matrix `W` of shape `n_regions x n_dofs`;
* `integral h (T - T_inf) ds` -- one boundary covector plus a constant.

Neither depends on the problem. Assembled once, the entire per-problem postprocess becomes
`W @ solution_values`, a single GEMM on data that is **already resident in GPU memory**. The RHS
side is the same story: the right-hand side for a volumetric source is linear in the power vector,
so all `n + 1` vectors are one matrix product rather than `n + 1` DOLFINx assemblies.

## The speedup limit, derived

The two per-problem loops become one sparse-dense product each, and both use the same `M`:

* traffic per product `nnz(M) x P x 12 bytes = 35.0e6 x 24 x 12 = 10.1 GB`;
* at roughly 1.3 TB/s of usable HBM bandwidth that is **7.8 ms**, so both ends together are ~16 ms.

**That part goes from 56.5 s to 16 ms -- a factor of ~3500.** But Amdahl binds elsewhere:

    new total = 39.1 (mesh) + 6.6 (K) + 3.2 (M) + 6.6 (plan) + 1.7 (factor) + 0.2 (solve) + 0.02
              = 57.4 s   against 111 s   ->   1.93x

**So the honest ceiling for the GEMM rewrite alone is about 2x, and the new bottleneck is mesh
construction at 68 % of what remains.** Reporting "~7x" as the first version did was wrong: it
assumed the whole remainder was the per-problem loop.

Going further requires reducing `C`, and the reason `C` is large is structural rather than
necessary: **the mesh is uniform and the physics is not.** The die occupies about 10 % of the 60 mm
package footprint and every gradient of interest is inside it; the rest is far-field copper and air
carrying almost no information. A graded mesh holding the current resolution over the die and
coarsening outward should cut `C` by roughly 5x, giving mesh 8 s, `K` 1.1 s, `M` 0.6 s and a total
near 12-15 s -- **7-9x overall**, with the accuracy over the die unchanged by construction.

## The accuracy limit, derived

**The GEMM form is algebraically identical to the loop**: the same assembled objects, the same weak
forms, the same measures. Only the summation order differs. Each region integral sums about
`k = 4 C / n_regions ~ 1.46e6` terms, so the floating-point error is of order
`sqrt(k) * eps = 1209 * 2.2e-16 = 2.7e-13` relative, which on a 320 K field is **8.5e-11 K** -- five
orders below the 1e-6 tolerances this project enforces and eight below the 0.01 K linearisation
budget. **Accuracy is not the limit and the rewrite does not spend any.**

Where accuracy *is* limited is the direct solve. The CUDA HotSpot solver refused three census
designs at `residual = 1.1526e-8` against a `1.1422e-8` limit, and multiple right-hand sides do not
change conditioning. One round of iterative refinement -- solve, evaluate the residual, correct --
takes the residual to order `kappa * eps` and costs exactly one more multi-RHS back-substitution:
**0.2 s, or 0.4 % of the post-rewrite runtime.** Precision here is essentially free; what is not
free is the mesh.

## Why it was not done for `archive-census-v1`

`steady_heat_fem.py` lives in the sibling `ThermoDSE` tree, which this project pins as a frozen
read-only dependency. The fix therefore requires an adapter in this repository that reuses the
solver's assembled objects, validated against `solve_steady_heat_batch` for agreement before use --
a second implementation may not be its own oracle. That is more work than letting the current census
finish, and the census was already a third done when this was measured.

## Why it decides the next step

At 111 s per design, the 4 196-design candidate pool is **64 h on two A800s**. With the per-problem
loops replaced it is roughly **9 h**. That is the difference between the full cool pool being out of
reach and being a weekend.

## The one place a CUDA kernel would genuinely buy accuracy

Not here, and not in the FEM. **Discretisation error is set by the mesh, not by the arithmetic** --
the measured 0.6093 -> 0.6673 -> 0.6905 K band drift is a mesh effect and no floating-point format
changes it.

But the CUDA HotSpot solver refused three census designs on its own residual self-check
(`residual = 1.1526e-8` against `limit = 1.1422e-8`, 0.9 % over). That **is** a numerical-precision
failure, and the correct repair is iterative refinement -- solve, evaluate the residual at higher
precision, apply a correction, repeat -- rather than the CPU fallback used here or, worse, relaxing
the tolerance. Each refinement round costs one more back-substitution, and back-substitution is the
0.2 %.
