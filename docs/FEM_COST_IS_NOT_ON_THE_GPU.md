# The FEM reference is CPU-bound, and the GPU does 0.2 % of the work

MEASURED 2026-08-01, one archive design (`arxv008`, 23 blocks, 24 problems), n=192 mesh
(320 x 304 x 15 cells), one A800 through cuDSS. Instrumented via `LinearSolveReceipt`; the
postprocess figure is the unaccounted remainder inside the batch call.

| phase | seconds | share |
| --- | --- | --- |
| **per-problem postprocess** | **72.6** | **65 %** |
| **per-problem RHS assembly** | **23.0** | **21 %** |
| operator assembly | 6.6 | 6 % |
| cuDSS plan | 6.6 | 6 % |
| cuDSS factorization | 1.7 | 2 % |
| host to device | 0.4 | 0 % |
| **GPU solves** | **0.2** | **0.2 %** |

Total 111 s.

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

Estimated effect: 86 % of the run replaced by two matrix multiplies, so roughly **7x** on this
design. The argument is the same linearity that makes the operator affine in the first place -- it
is not a kernel-writing exercise.

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
