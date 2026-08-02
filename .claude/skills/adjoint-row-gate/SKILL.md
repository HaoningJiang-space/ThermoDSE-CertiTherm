---
name: adjoint-row-gate
description: Run the Gate 0 adjoint-row verification for CertiTherm-Opt on moe-server — checks that an adjoint thermal response row equals the forward impulse-built row entry for entry, and measures whether lazy row generation can actually save anything. Use before writing any MILP that depends on adjoint-generated thermal constraints.
---

# Gate 0: does an adjoint response row equal the forward one?

## What this decides, and why it is worth one run

A proposed direction (**CertiTherm-Opt**) puts a mapping MILP in a master problem with few thermal
rows, solves it, replays the winner at high fidelity, and when a cell violates the limit generates
that cell's **exact** response row by an adjoint solve `K^T λ_j = c_j`, `r_j = λ_j^T F`, adds it, and
repeats. The optimality argument is sound: the master is always a relaxation, so a master optimum
that survives full-field verification attains the relaxation bound and is therefore the global
optimum of the full problem.

**Two things must be true before any of that is worth building, and both are cheap to check.**

1. **`r_j` must actually equal row `j` of the operator this project already builds.** It does by
   algebra — `(K^{-T}c_j)^T F = c_j^T K^{-1} F = R_{j,:}` for any `K`, no symmetry needed — so any
   disagreement is an **implementation** defect in the dual pairing between the region-average
   functional and the source map. That is precisely the false-ACCEPT direction: a certificate built
   from a mis-indexed row is internally consistent and wrong.
2. **The claimed saving must exist.** It is asserted as "compute only the active hotspot rows
   instead of all `n + 1` responses". Measure it instead of believing it.

## The answer to (2) is already visible in the code, and it is negative

The bilinear form is `inner(k grad u, grad v) dx + h u v ds` — **symmetric**. So `K^T = K` and an
adjoint solve is *one more right-hand side against a factorisation that already exists*. Lazy
generation cannot avoid the factorisation, which dominates the build; it can only avoid extra
triangular solves.

The direction also matters and it runs against the proposal at this scale:

| | one solve buys | count here |
| --- | --- | --- |
| forward impulse | a **column** — all temperature points | `n` = 181–237 power blocks |
| adjoint | a **row** — all power blocks | `m` = 262 144 `grid512` cells |

The full operator costs **182 solves in 30 s sharing one factorisation** and returns every cell row
free. Adjoint generation wins only when the active row count is below `n`, against a total that is
already 30 s. **The real motivation for laziness is MILP constraint count (262 144 rows is not
solvable), not thermal solve count** — a defensible reason, but a different one, and it must be
stated as such.

## Run it

Never locally — FEM + cuDSS + GPU is claim-adjacent native work and the execution mandate sends it
to `moe-server`.

```bash
.claude/skills/moe-server-remote/scripts/remote_exec.sh \
  '/data/ziheng/conda_envs/chiplet-fem-0.11/bin/python \
     research/triangle/robustness/fem_batch_gpu.py --gate --cells 24 --grid 3'
```

Options: `--cells N` lateral cells per axis (must be a multiple of `--grid`), `--grid G` gives
`G**2` powered die regions, `--fem-src PATH` for the `steady_heat_fem` source root.

## What it runs

Both gates in one process, against one synthetic layered box:

* **forward parity** — `solve_batch_gpu` against `solve_steady_heat_batch`, refusing above
  `PARITY_TOL_K = 1e-9`. This is the gate the module's docstring declared itself provisional upon
  and which **had never been implemented**: there was no `main`, no `__main__`, and
  `solve_batch_gpu` had no callers anywhere in the repository.
* **adjoint identity** — every entry of every adjoint row against the forward impulse build,
  refusing above `ADJOINT_TOL_REL = 1e-9` relative to the response scale.

The instance is deliberately **not** the real floorplan. The identity is algebraic and
geometry-independent, so the gate uses the smallest box that exercises every path it must test —
mixed mass matrix, DG0 dof reordering, region selector, Robin boundary — and nothing it does not.

## Result, first run 2026-08-02 on `moe-server` at `d29e8ac`+

| cells/axis | rows | parity abs | parity rel | adjoint rel | entries | factorisation share |
| --- | --- | --- | --- | --- | --- | --- |
| 24 | 9 | 1.11e-11 K | 1.72e-12 | **1.12e-13** | 81 | 94.8 % |
| 48 | 16 | 1.26e-10 K | — | **1.51e-13** | 256 | 92.2 % |
| 96 | 16 | 8.76e-10 K | — | **2.83e-13** | 256 | 98.4 % |
| 128 | 64 | 1.37e-09 K | 1.73e-10 | **1.89e-13** | 4096 | 98.1 % |
| 160 | 64 | 3.29e-09 K | 4.15e-10 | **3.85e-13** | 4096 | 97.8 % |

**Gate 0 PASSES.** The adjoint row equals the forward row to 1e-13 relative — machine precision, and
flat across a 7x mesh refinement and a 64x growth in entries compared. The dual pairing is correct,
so the CertiTherm-Opt mechanism is not blocked by an implementation defect.

**And the economics are refuted, measured rather than argued.** The factorisation is **92–98 % of
the linear-algebra cost**, and the share *grows* with mesh size because factorisation is superlinear
while triangular solves are linear. Doubling the right-hand sides from 65 to 129 columns to carry
64 adjoint rows changed the solve from 0.027 s to 0.077 s against a 1.45 s factorisation. **Lazy row
generation cannot save the cost that dominates.**

Three defects were found in `fem_batch_gpu.py` by running it for the first time, all latent in code
that had no callers: `nvs.DirectSolver(matrix)` against an API that requires `(a, b)`; a return
shaped `(regions x problems)` while the docstring promised per problem; and a C-order right-hand
side where cuDSS requires column-major. A fourth was in the gate's own definition — see below.

**The absolute parity tolerance was wrong and was corrected, not loosened to fit.** Two
implementations of one weak form, both solved directly, diverge with floating-point accumulation:
1.07e-11 → 1.26e-10 → 8.76e-10 → 1.37e-9 K as the mesh refines. A fixed absolute bound is therefore
a mesh-size threshold in disguise and refused the 128 case for being large. The criterion is now
relative to the rise above ambient; the absolute figure is still reported so the growth stays visible.

## Reading the result

`adjoint_pass: false` **kills the CertiTherm-Opt mechanism** until the dual pairing is fixed; do not
write the MILP. `forward_parity_pass: false` invalidates the GPU batch path, which is upstream of it.

`shared_factorisation_s` versus `forward_solve_s` is the economic answer: if the factorisation
dominates, laziness cannot pay for itself on solve count and the direction must be justified on MILP
tractability instead.

## Scope

This gate does **not** test the thermal result, the floorplan, the power model, or `p(x) = Bx + d`.
That last one is the separate live risk: NoC/NoP energy depends on whether two tasks share a
chiplet, i.e. on `x_u ⊗ x_v`, so `p(x)` is **bilinear**, not linear. It is linearisable with pair
variables at real cost in MILP size, and it is the same obstruction that closed the architecture-DSE
direction. Gate 0 passing does not retire it.
