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
free. So the honest comparison is `T_fact + (I+k) T_tri` against `T_fact + n T_tri` for `I`
verification iterations and `k` generated rows: laziness saves triangular solves whenever
`I + k < n`, and never saves the factorisation. **MILP constraint count is an additional motivation
— 262 144 rows is not solvable — but it is not the only one**, and an earlier revision of this file
wrongly said it was.

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
  `PARITY_TOL_REL` relative to the rise above ambient, with the absolute figure still reported.
  This is the gate the module's docstring declared itself provisional upon
  and which **had never been implemented**: there was no `main`, no `__main__`, and
  `solve_batch_gpu` had no callers anywhere in the repository.
* **adjoint identity** — every entry of every adjoint row against the forward impulse build,
  refusing above `ADJOINT_TOL_REL = 1e-9` relative to the response scale.

The instance is deliberately **not** the real floorplan. The identity is algebraic and
geometry-independent, so the gate uses the smallest box that exercises every path it must test —
mixed mass matrix, DG0 dof reordering, region selector, Robin boundary — and nothing it does not.

## Result, first run 2026-08-02 on `moe-server`; strengthened and re-measured at `d9d6a12`

| cells/axis | rows | parity abs | parity rel | adjoint rel | entries | factorisation share |
| --- | --- | --- | --- | --- | --- | --- |
| 24 | 9 | 1.11e-11 K | 1.72e-12 | **1.12e-13** | 81 | 94.8 % |
| 48 | 16 | 1.26e-10 K | — | **1.51e-13** | 256 | 92.2 % |
| 96 | 16 | 8.76e-10 K | — | **2.83e-13** | 256 | 98.4 % |
| 128 | 64 | 1.37e-09 K | 1.73e-10 | **1.89e-13** | 4096 | 98.1 % |
| 160 | 64 | 3.29e-09 K | 4.15e-10 | **3.85e-13** | 4096 | 97.8 % |

**Those numbers came from a WEAKER form of the gate and are kept only to show the progression.**
Written out, that version compared `G[j,i]` against `G[i,j]` for `G = S^T M^T K^-1 M S` — the
symmetry of `G`, i.e. **reciprocity**, which this project already measures at 0.00 % for the FEM.
Real content, but not independent of a result already in hand, and both sides came from the same
device arrays. The gate now takes its forward side from the **CPU oracle** and includes **unpowered**
output regions, whose `j` index the `i` index cannot reach:

| cells/axis | rows (unpowered) | entries | adjoint vs oracle | **unpowered block** | CPU/GPU parity |
| --- | --- | --- | --- | --- | --- |
| 24 | 11 (2) | 99 | 4.92e-12 | **4.92e-12** | 5.42e-12 |
| 96 | 18 (2) | 288 | 1.22e-10 | **1.22e-10** | 1.32e-10 |
| 160 | 66 (2) | 4224 | 4.25e-10 | **4.25e-10** | 4.52e-10 |

**What this establishes, and it is narrower than "Gate 0 passes".** Peer review (2026-08-02, at
`d9d6a12`) was right that the earlier heading overclaimed. Recorded per component instead:

| | |
| --- | --- |
| `GPU_FORWARD_REGION_AVERAGE_PARITY` | PASS |
| `REGION_AVERAGE_ADJOINT_REGRESSION` | PASS |
| `STIFFNESS_SYMMETRY` | PASS (now measured, see below) |
| `CELL_ROW_PAIRING` | **UNTESTED** |
| `ITERATIVE_FACTOR_REUSE` | **UNTESTED** |
| `EXACT_MAPPING_TO_POWER_MILP` | **UNRESOLVED** |
| `CERTITHERM_OPT_KILL_CONDITION` | **NOT CLEARED** |

**The decisive gap: every compared row is a REGION AVERAGE, two of them whole passive layers.**
CertiTherm-Opt generates the row of a violating **cell**. No cell covector is constructed or compared
anywhere here, so a correct spreader average says nothing about a misindexed 262 144-cell separator —
which is exactly the false-ACCEPT direction the gate was built to close. The maximum error also now
sits at the CPU-vs-GPU parity level, so the adjoint-specific discrepancy is *below the resolution of
the forward comparison*: this is a cross-implementation regression, not an independent 1e-13 result.

**`K` symmetry is now measured, not assumed.** The adjoint path solves `K lambda = c` and calls it
`K^-T c`; every argument in the module rested on `K = K^T` justified only by reading the bilinear
form. `stiffness_asymmetry_rel` is now computed from the assembled matrix and gates the run.

**On the economics, narrowed after review.** On these synthetic instances the factorisation is
**92–98 % of measured linear-algebra time**, so laziness cannot eliminate that shared cost. Doubling
the right-hand sides from 65 to 129 columns to carry 64 adjoint rows changed the solve from 0.027 s
to 0.077 s against a 1.45 s factorisation.

**Two things previously claimed here are withdrawn.** The share does **not** grow monotonically with
the mesh — measured 94.8, 92.2, 98.4, 98.1, 97.8 % — and mesh size, region count and RHS count move
together, so no scaling exponent is identified. And "constraint count is the only defensible
motivation" ignores the real comparison, which is `T_fact + (I+k) T_tri` against `T_fact + n T_tri`:
if `I + k < n`, laziness *does* save triangular solves even when the wall-time saving is small. What
survives is only that it cannot save the factorisation. Settling it needs the real 1.4 M-cell matrix
with synchronised timers and a solver object demonstrably reused across iterations; `factorise_and_solve`
currently discards its solver and the gate knows every adjoint column in advance, so cross-iteration
reuse is not demonstrated.

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

This gate tests one thing: that a response row obtained by an adjoint solve is the row the forward
build produces. It does **not** test the thermal result, the floorplan, the power model, or the host
MILP.

## The `p(x) = Bx + d` kill condition — RESOLVED, and it does not fire

**`p(x)` really is bilinear, confirmed from source.** `ThermoDSE/core/nop.py:73`
`move_between_core(src, dst, volume)` calls `unicast(src_cidx, dst_cidx, size)`, which calls
`NoP_link_calc(src_cidx, dst_cidx)`. The hop count is a function of **both** placements, so for a
binary assignment `x[t,c]`:

    hops(u,v) = sum over c,c' of  x[u,c] * x[v,c'] * hop(c,c')

**Two reasons it does not kill the thermal contribution.**

1. **The optimality proof survives, because the variables are binary.** McCormick on a product of
   binaries — `z <= x[u,c]`, `z <= x[v,c']`, `z >= x[u,c] + x[v,c'] - 1`, `z >= 0` — is an **exact
   reformulation**, not a relaxation. The linearised model is still the full problem, so "master is
   a relaxation of it" is untouched.
2. **The thermal rows never see the blow-up.** Power is dissipated **per chiplet**, not per task, so
   the bilinear terms reaching `p(x)` aggregate to `y[c,c'] = sum over edges of volume_uv x[u,c]
   x[v,c']` — that is `C**2` terms, **16 for 4 chiplets and 256 for 16**, *independent of task
   count*. The `edges * C**2` explosion (208 896 z-variables at 256 tasks and 8 chiplets) lands in
   the latency/ordering part of the mapping MILP, which is the host problem's difficulty and not the
   certificate's.

**What this does NOT settle, and peer review was right to press it.** Three things:

* **The `C**2` aggregation does not remove the edge variables.** `y[c,c']` is *defined* by
  `sum_e w_e y[e,c,c']` with `sum_c' y[e,c,c'] = x[u,c]`, so the `O(|E| C**2)` transport variables
  still have to exist in the MILP; only the *thermal rows* reference the `C**2` aggregate. The claim
  "the thermal rows never see the blow-up" holds; "the bilinearity is cheap" does not.
* **Average power contains a RATIO that McCormick cannot linearise.** ThermoDSE divides energy by
  total mapping-dependent latency (`core/statistic.py:230,287`), and latency itself contains maxima
  and bandwidth effects (`core/evaluator.py:59`). `E(x)/L(x)` is not a bilinear form. This is a
  harder obstruction than the pair products and was missed in the first analysis.
* **The evaluator does more than fixed DAG-edge unicast** — grouped multicast, placement-dependent
  reuse-source selection, buffer retention/eviction, DRAM fallback (`core/evaluator.py:81`). A
  compact chiplet-pair energy model would be a **new abstraction**, not an exact reformulation of
  this evaluator, and if the master used it while replay used ThermoDSE, the generated thermal cuts
  would not be globally valid in the master's variables.

So the relaxation-bound theorem stays correct, but only under conditions not yet discharged: every
feasible design must remain in the master, the objective must be represented identically, and every
generated cut must be globally valid. **Gate 1 must therefore begin with a component-by-component
equality test between the MILP's power and ThermoDSE's on adversarial mappings**, before any solver
work. `ThermoDSE/core/schedule.py` is also greedy and provides no bound, so the host must be written
from scratch regardless.
