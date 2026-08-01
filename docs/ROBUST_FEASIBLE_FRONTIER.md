# The robust-feasible frontier, and what actually determines it

RESULT 2026-08-01. Development registry, 3 architectures x 2 workloads, `default` package. No new
HotSpot runs -- everything below is computed on operators the pipeline already built, in minutes.

This tests the T3 proposal: replace the frozen `0.01 K` model-error band with the **measured**
cross-model discrepancy, re-certify, and publish the architectures that stay feasible together with
the EDYP price of choosing one. The proposal is sound and the deliverable exists. What the
measurement changes is the diagnosis of what makes it exist.

## The band the frozen contract was missing

`sup_p [T_coarse(p) - T_fine(p)]` over the power polytope, per row, one-sided (`cross_grid_bound`):

| pair | at the nominal power map | over the registered coarse set | ratio to the frozen 0.01 K |
| --- | --- | --- | --- |
| `grid64` vs `grid128` | 0.08 – 0.29 K | 1.34 – 10.64 K | 134 – 1064x |
| **`block` vs `grid128`** | **0.61 – 1.08 K** | **3.11 – 14.83 K** | **311 – 1483x** |

Two things worth separating.

**The family disagrees with itself more than any member disagrees with a finer version of itself.**
`block` against `grid128` exceeds `grid64` against `grid128` at every point. No refinement study is
needed to expose the problem -- the three registered models already differ by 0.6–1.1 K on the actual
design point while the contract budgets 0.01 K.

**Most of the polytope band is the uncertainty SET, not the models.** The supremum runs 4–133x the
value at the nominal map, because `content_upper_bounds` hands every block its whole content class's
power -- a deliberately permissive set whose adversarial vertices no workload phase produces.
Quoting the supremum alone would pass a worst case off as a typical disagreement.

## The frontier, and it depends on the uncertainty set rather than on the thermal model

Feasible means `nominal peak + band <= limit - margin`, with the band folded in one-sidedly.

| uncertainty set | resnet50 | transformer | price of robustness |
| --- | --- | --- | --- |
| registered coarse (`content_upper_bounds`) | 2 of 3 | **0 of 3 — empty** | +50.3 % EDYP (resnet50) |
| activity-bounded, span 0.30 | 3 of 3 | 3 of 3 | **+0.0 %** |

Under the set the project already provides for exactly this objection, the band falls from
3.11–14.83 K to **0.25–1.07 K**, a 13–14x reduction, and **the frontier is complete and robustness is
free** -- the EDYP-optimal architecture is itself robust-feasible.

## The frontier as a curve, which is the deliverable

Sweeping the declared per-block activity span:

| span | resnet50 | transformer | cheapest robust | price |
| --- | --- | --- | --- | --- |
| 0.10 – 0.90 | 3 of 3 | 3 of 3 | `arch_b` (the EDYP optimum) | **+0.0 %** |
| **0.92 and above** | 3 of 3 | **2 of 3** | `arch_c` | **+32.1 %** |

**The breakpoint is a per-block activity span of about 0.91.** Below it every architecture in the
registry certifies against its own model's disagreement and robustness costs nothing. Above it the
transformer workload loses its EDYP-optimal architecture -- `arch_b`'s band reaches 1.72 K against
1.699 K of headroom -- and the cheapest robust alternative costs **+32.1 % EDYP**.

`resnet50` never breaks, through a span of 2.00.

### An independent cross-check

That +32.1 % is the same figure the robustness-radius analysis reported for the same architecture
switch (`arch_b -> arch_c`, transformer) when the criterion was a declared `tau*` accuracy rather
than a budgeted error band. Two different routes -- forward error budgeting and a backward
robustness radius -- give the same switch at the same price, which is a consistency check neither
produces on its own.

## So: is T3 right?

The shape is right, the reuse is real, and the deliverable exists. One correction to its premise.

T3 frames the problem as the thermal model's error and the fix as re-budgeting it. The measurement
says the model's error is **necessary but not sufficient** to explain the outcome: with the band
honestly budgeted, whether anything certifies is decided by the **power-uncertainty set**, which
moves the band by 13–14x where switching between thermal models moves it by less than 2x. The
positive framing T3 asks for is therefore available and is stronger than "the robust frontier and
its price":

> Once a thermal-aware DSE budgets its own model's disagreement, the binding constraint is the
> declared power-model accuracy, not the thermal model. The frontier is complete and robustness is
> free up to a per-block activity span of 0.91; beyond it the EDYP-optimal architecture stops
> certifying and robustness costs 32.1 % EDYP.

That is a positive, actionable, quantified statement, and it is not "everything is uncertain".

## What this does NOT establish

* **3 architectures, 2 workloads, the development registry.** A curve through 6 points.
* **This is nominal-peak feasibility under a band, not the full observation-synthesis question.**
  It asks whether a design certifies, not what must be measured to certify it. The `beta*` machinery
  and the instrumentation tiers are a different quantity and remain withdrawn
  (`docs/BUDGETED_REGISTRY_DOES_NOT_CERTIFY.md`).
* **The activity span is declared, not measured.** The breakpoint at 0.91 is meaningful only against
  a power model somebody is willing to be held to at that accuracy. Nothing here establishes what a
  real architecture-stage power model achieves.
* **`grid128` is treated as the reference and is not ground truth.** The bands measure disagreement
  between discrete operators. A `128 -> 256` term is not included here and would add to them.
* **The block-average mapping understates the physical peak** by a further 0.18 K on the one
  architecture where it was measured (`docs/WHERE_THE_THERMAL_ERROR_ACTUALLY_IS.md`), which this
  feasibility test does not correct for.
