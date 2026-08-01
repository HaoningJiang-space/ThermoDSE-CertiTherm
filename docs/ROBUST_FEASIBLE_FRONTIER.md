# The robust-feasible frontier, and what actually determines it

RESULT 2026-08-01, **revised the same day after peer review found two errors in the first version**.
Development split (`arch_a`, `arch_b`, `arch_c`) x 2 workloads, `default` package. The three
held-out splits are untouched.

This tests the T3 proposal: replace the frozen `0.01 K` model-error band with the **measured**
cross-model discrepancy, re-certify, and publish the architectures that stay feasible together with
the EDYP price of choosing one. The deliverable exists. Two things about how it was computed were
wrong and are corrected below; one of them changes a published number.

## What was withdrawn

**A discrepancy bound is not a temperature bound.** The first version evaluated the peak at the
NOMINAL power map and then subtracted a polytope-wide *discrepancy* supremum from the resulting
headroom. That certifies nothing about the polytope: a different admissible map can be hotter under
the very same operator, and the two maxima are taken over different things. The certificate is now
`sup_p T_reference(p) <= limit - margin - linearisation`, computed by the same exact greedy fill.
**The breakpoint moves from a per-block activity span of 0.91 to 0.36.** The old figure is withdrawn.

**Two columns were reported in opposite directions.** `one_sided_containment_bounds` returns
`sup(T_fine - T_coarse)`; the nominal-map column computed `T_coarse - T_fine`. The ratio "the
polytope supremum runs 4-133x the value at the nominal map" therefore compared different quantities
and is withdrawn. The signs are now aligned and the ratio is not restated pending recomputation.

Both were found by peer review, and both corrections make the result **stricter**, not weaker.

## The certificate, over the polytope

`limit - margin - linearisation = 330.0 - 0.05 - 0.01 = 329.94 K`. The linearisation band is
**retained, not replaced**: it measures direct HotSpot replay against impulse superposition, which is
a different error source from disagreement between operators. Re-anchoring by deleting it would
leave superposition unbudgeted.

| architecture / workload | nominal peak | `sup_p T` at span 0.30 | `sup_p T` under `content_upper_bounds` |
| --- | --- | --- | --- |
| `arch_a` / resnet50 | 321.72 K | 322.19 K — CERTIFIED | 349.86 K — refused |
| `arch_a` / transformer | 324.59 K | 325.32 K — CERTIFIED | 377.97 K — refused |
| `arch_b` / resnet50 | 324.09 K | 325.04 K — CERTIFIED | 359.51 K — refused |
| **`arch_b` / transformer** | 328.26 K | **329.63 K — CERTIFIED** (0.31 K slack) | 386.15 K — refused |
| `arch_c` / resnet50 | 321.57 K | 322.10 K — CERTIFIED | 337.58 K — refused |
| `arch_c` / transformer | 324.56 K | 325.53 K — CERTIFIED | 355.48 K — refused |

**Under `content_upper_bounds` the temperature itself reaches 337-386 K, exceeding the limit by
8-56 K.** That set is not refused because of an error budget; it *contains genuinely infeasible
power maps*, because it hands every block its whole content class's power. Attributing that refusal
to model error, as the first version implicitly did, was the wrong diagnosis.

## The frontier as a curve, which is the deliverable

| per-block activity span | resnet50 | transformer | cheapest certified | price |
| --- | --- | --- | --- | --- |
| 0.10 - **0.36** | 3 of 3 | 3 of 3 | `arch_b` (the EDYP optimum) | **+0.0 %** |
| **0.38** - 1.50 and beyond | 3 of 3 | 2 of 3 | `arch_c` | **+32.1 %** |

**The breakpoint is a per-block activity span of about 0.36, and it is sharp.** At 0.34
`arch_b`/transformer reaches 329.813 K against the 329.94 K threshold — 0.127 K of slack. At 0.38 it
reaches 329.996 K and is refused by 0.056 K.

`resnet50` never breaks, through a span of 1.50. Beyond the breakpoint **nothing further changes up
to span 1.50**: the same architecture switch at the same price holds across a 4x range of declared
power-model accuracy, which is a stability the point estimate alone does not show.

### The price is a range, not a point

`k0_ranking_margin` measures the top of ThermoDSE's space as a 0.5-5 % EDYP plateau, inside the
evaluator's own error band, so a price quoted against a single argmin can move because of evaluator
noise rather than robustness. The denominator here is the whole set of designs within 5 % of the
best. On this registry the set is a singleton, so the range collapses and `+32.1 %` is both bounds;
on the archive it will not, and the reported price is `[vs worst indistinguishable, vs best]`.

## The error ledger, and where the error actually is

Polytope-wide, per row, one-sided, at activity span 0.30 — all four terms, same direction:

| term | range over the 6 points | what it is |
| --- | --- | --- |
| `block` vs `grid128` | **0.25 - 1.07 K** | model-family disagreement (block-average vs grid mapping) |
| `grid64` vs `grid128` | 0.09 - 0.41 K | one refinement step |
| `grid128` vs `grid256` | 0.07 - 0.26 K | one refinement step |
| `grid256` vs `grid512` | 0.05 - 0.14 K | one refinement step |
| **`grid128` vs `grid512`, direct** | **0.05 - 0.34 K** | the whole refinement tail |
| frozen linearisation band | 0.01 K | superposition residual, retained separately |

**The dominant term is not discretisation.** The complete refinement tail from `grid128` to
`grid512` is 0.05-0.34 K, while the `block`-vs-`grid128` model-family disagreement is 0.25-1.07 K —
2 to 7 times larger. Refining the grid is not where the error is; choosing between the family's
members is.

**The refinement contracts, so the tail beyond `grid512` is bounded.** Under
`content_upper_bounds`, the successive ratios are 2.03, 2.01, 2.00, 1.82, 2.77, 2.47 for a
factor-2 refinement — an observed order `p ~ 1`, which is what a finite-volume scheme with
discontinuous material and source boundaries should give. A first-order sequence contracting by 2
per doubling has a geometric remainder bounded by its own last term, so the tail past `grid512` is
no larger than the `grid256`-to-`grid512` step already measured. This closes the "is there a
defensible refinement tail" gate that peer review raised.

**Measuring the tail directly is materially tighter than summing the steps.** For
`arch_a`/resnet50 the direct `grid128`-to-`grid512` bound is 0.0512 K against 0.1475 K for the sum
of the two steps — 2.9x looser — because the successive suprema are attained at different rows and
vertices.

## An incidental receipt: the GPU and CPU operators are identical

`grid128` was built by the CPU registry and again by the CUDA backend; `grid256` was built twice by
the CUDA backend in separate runs. The maximum absolute difference in the response matrices is
**exactly 0.0 K/W** in both cases. Every band above therefore measures the grid and not the backend.
The check is not optional decoration: it is enforced in `_merged_models`, which refuses rather than
preferring whichever operator loaded first.

## What this does NOT establish

* **3 architectures, 2 workloads.** A curve through 6 points. The other nine architectures in the
  registry are the three frozen held-out splits and are deliberately not run; they are out of scope,
  not unresolved.
* **`grid512` is a reference, not ground truth, and every band on this page is *within HotSpot*.**
  Grid refinement bounds HotSpot's own discretisation error; it does not bound its model-form error.
  **That gap has since been closed**: `docs/MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` measures
  HotSpot against a DOLFINx FEM reference and finds model form is 1.4-11.8x the complete refinement
  tail, one-signed (HotSpot underestimates), and that the frontier survives it at 5 of 6 points with
  the same +32.1 % price. 3D-ICE could not have supplied that reference: its layer spec carries no
  per-layer footprint while the chip dimensions are global, so this package's three distinct
  footprints cannot coexist; truncating them inserts ~2.57 K of series copper against a 0.095 K
  margin.
* **The rows are block averages, and the block-average peak understates the cell peak** by 0.18 K on
  the one architecture where it was measured (`docs/WHERE_THE_THERMAL_ERROR_ACTUALLY_IS.md`). A
  certificate over block averages does not imply one over the physical peak. The cell-level
  construction exists (`cell_level_bound.py`, 3.10 K max over `content_upper_bounds` on one
  architecture) but has not been run under the activity-bounded set or across architectures.
* **The activity span is declared, not measured.** The breakpoint at 0.36 is meaningful only against
  a power model somebody is willing to be held to at that accuracy.
* **This is feasibility under a polytope, not the observation-synthesis question.** It asks whether
  a design certifies, not what must be measured to certify it. The `beta*` machinery remains
  withdrawn (`docs/BUDGETED_REGISTRY_DOES_NOT_CERTIFY.md`).
