# With the discretisation error budgeted, the registry stops certifying

RESULT 2026-08-01, `method-freeze-radii-v2`. The development sweep re-run with the grid-convergence
budget applied to every operator. This is the terminal finding of the round and it withdraws the
thermal half of the work rather than qualifying it.

## The measurement

18 architectures x 2 workloads, `matched` grid, gate active, `block` charged.

| outcome | count |
| --- | --- |
| refused — budget at least the whole headroom to 330 K | **4 architectures** (`6x4` cut 2x1 and 2x2, `8x4` cut 2x1, `6x6` cut 2x2) |
| refused — pre-existing 0.01 K linearisation contract | 1 architecture (`8x6` cut 1x1) |
| certified | 11 architectures, 22 points |

Of the 22 points that certified:

| workload | points | with `beta* = 0` | peak range | best `beta*` |
| --- | --- | --- | --- | --- |
| resnet50 | 11 | 2 | 322.47 – 322.79 K | **1.72 %** |
| transformer | 11 | **11 — all of them** | 325.90 – 327.85 K | **0.00 %** |

A radius of exactly zero is not a small radius. It means the **nominal** power map already reaches
the reject floor once the operator's own error is subtracted: the design is infeasible before any
uncertainty is admitted. **Every transformer point in the development registry is in that state.**

Against the previously published values on the same geometries, `resnet50`: `tau*` falls from
150–175 % to 0–44 %, `beta*` from 3–4 % to 0–1.72 %.

## Why, in one line of arithmetic

    peak-temperature margin to the 330 K limit, this registry:   2 – 8 K
    the thermal operator's own discretisation error:           0.5 – 3 K

**The decision is being made at a resolution the model does not have.** Everything else in this
round follows from that ratio. The `0.01 K` linearisation band that the certificate does budget is
two to three orders of magnitude smaller than the error it does not.

## What this withdraws

Every thermal claim in this repository, on this registry:

* the relocation and deviation radii as reported — `beta*_safe`, `beta*_reject`, `epsilon*`, `tau*`;
* the instrumentation bracket and every tier verdict built from them;
* the certified observation bounds, including the already-withdrawn 1312 and 1440;
* the held-out P5 result, which pairs a cost choice against a `beta*` choice, since on the budgeted
  operators most `beta*` values are zero and the comparison has no content.

These are not "smaller than reported". For the transformer workload they do not exist: there is no
robustness radius around a design that is already infeasible at nominal power.

## What survives, unchanged

The claims that never touch the thermal operator, all validated on the preregistered held-out split
and all independent of this finding:

* **the refinement-monotonicity proposition** — an area-weighted arithmetic mean of a strictly
  decreasing per-die yield rises under every refinement at every parameter value, so such an
  aggregate cannot price chiplet count; executed as a test, not argued;
* **the composition comparison** — the all-dies-good product prefers `n = 1` in 8 of 8 held-out
  groups, the transcribed organic-substrate recurring cost in 8 of 8;
* **no cut owns the joint cost-parameter box** in any group, under a six-factor sweep;
* **the `n=1`/`n=2` crossover lies outside `(0, 1]`** in 8 of 8;
* **the transcription's term-by-term conformance** against the upstream published program, frozen as
  a fixture at a pinned commit.

That is a coherent result on its own: the chiplet-count decision is not determined by the objective
under any composition or cost parameterisation tried, and the proposition says why a whole class of
yield aggregates cannot determine it.

## What it would take to recover the thermal half

Not more experiments on this registry — the instrument is the problem.

1. **A resolution at which the operator error is small against the margin.** `grid256` is not
   validated either; `grid512` and a convergence study would be the first honest step, and the
   `gridN-avg` vocabulary cannot express the anisotropic grid the `6x2`-versus-`2x6` asymmetry points
   at.
2. **Or a decision problem with a larger margin.** A 2–8 K margin against a 0.5–3 K model error is
   not certifiable by any amount of care in the LP above it.
3. **Or a different thermal model.** The independent-simulator route is recorded as geometrically
   blocked for this package (`docs/GRID_CONVERGENCE_FINDING.md`), which is itself now a more serious
   gap than when it was written.

## Provenance

The sweep hung after 16 of 18 architectures — main thread in `futex_wait`, fourteen idle children,
no HotSpot running, no log output for three hours — and was killed. The 22 certified points and 5
refusals above are read from its log, which is complete for those architectures; `8x6` cuts 2x1 and
2x2 were never reached and are absent rather than passing. The hang is not diagnosed and is recorded
as an execution failure, not a result.
