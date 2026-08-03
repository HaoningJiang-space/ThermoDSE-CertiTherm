# G2 repair: the window collapses to one dimension, and the current population cannot fill it

> **PARTIALLY WITHDRAWN 2026-08-03. See `docs/PER_CASE_Q_WITHDRAWS_THE_PLACEMENT_FREE_REFUSAL.md`.** The one-dimensional window `margin + e_total <= dist < g` is exact and stands. The **population table does not**: its `dist` column inherits the scaled `Q`. Recomputed per case, `arch_b`/resnet50 (`dist` 0.994) and `arch_c`/transformer (`dist` 1.464) **do** lie in the band at the optimistic `e_total`, and none does at the pessimistic one. So *"not one of the six can be a separator"* is withdrawn: G2 is undecided, and measuring `e_total` at the cell endpoint is now the binding action rather than a caveat.

REPAIR 2026-08-03. NON-CLAIM, arithmetic on committed numbers. Replaces the G2 section of
`ROUND_PLAN_FIXED_GEOMETRY.md`, which as written can return neither GO nor STOP.

## Three defects, not one

`ROUND_PLAN_FIXED_GEOMETRY.md` G2 decides by membership in `(L - g, L - margin - e_total]`.

1. **The upper edge does not exist.** The same paragraph concedes it: *"the upper edge is not yet a
   number at the certifying endpoint, because the model-form band is measured at block rows while the
   certificate is evaluated at cell rows"*. `e_total` appears in **no source file in this
   repository** — only in that paragraph.
2. **The lower edge is unsourced.** `PEAKCERT_OPERATOR_PREREGISTRATION.md` already registers this
   against itself: *"`g = 3.0 K` is asserted, not sourced. No cited work establishes that 3-5 K is
   the incumbent guard convention for this package class, and ThermoDSE's own 348 K cap is documented
   as unsupported."*
3. **The population is invalid, and this is new.** G2 names `arch_b`/resnet50 as the *slack negative
   control*. Under the corrected trace
   (`THE_GENERATOR_PUTS_THE_MISSING_HEAT_CENTRALLY.md`) its net margin is **0.143 K** — it is the
   **tightest surviving case**, not a control.

## The repair: the window is one-dimensional

Write `dist = L - T` for a candidate whose certified peak is `T`. Then

    the guard REJECTS it   <=>  T > L - g                  <=>  dist < g
    the method ACCEPTS it  <=>  T <= L - margin - e_total   <=>  dist >= margin + e_total

so a candidate is a separator **iff**

    margin + e_total  <=  dist  <  g

Two consequences, and they separate the two things G2 was conflating.

**The window's non-emptiness is candidate-independent arithmetic.** `g > margin + e_total` involves
neither the population nor any experiment. If the honest `e_total` ever exceeded `g - margin`, **no
candidate could be a separator at all** and the method would be strictly more conservative than the
convention it is trying to beat. That is a kill available for the cost of two numbers.

**It is not the binding constraint today.** Using the measured block-row band as a stand-in
(`0.251 - 1.4332 K` across three packages, plus `0.01 K` linearisation, `margin = 0.05`):

| `e_total` | window at `g = 3` | window at `g = 5` |
| ---: | ---: | ---: |
| 0.261 | `[0.311, 3)` — 2.689 K wide | 4.689 K wide |
| 0.750 | `[0.800, 3)` — 2.200 K wide | 4.200 K wide |
| 1.443 | `[1.493, 3)` — 1.507 K wide | 3.507 K wide |

**So the missing `e_total` does not block G2.** It moves the lower edge over a 1.2 K range and the
window stays open by 1.5 K or more. What G2 must report is each candidate's `dist`, from which the
verdict follows for any `(g, e_total)` a reader supplies — which is the interval-not-verdict discipline
the plan already asked for, made exact.

## The population, and it fails before the pilot runs

`dist` under the corrected trace, `L = 330`:

| case | `sup_p` peak | NET uplift | effective peak | **`dist`** | in `[0.311, 3)`? |
| --- | ---: | ---: | ---: | ---: | --- |
| `arch_a`/resnet50 | 322.3144 | 2.747 | 325.061 | **4.939** | no — accepted by both |
| `arch_a`/transformer | 325.4231 | 5.481 | 330.904 | **-0.904** | no — over the limit |
| `arch_b`/resnet50 | 325.4619 | 4.335 | 329.797 | **0.203** | no — below the lower edge |
| `arch_b`/transformer | 330.3018 | 7.644 | 337.946 | **-7.946** | no — over the limit |
| `arch_c`/resnet50 | 322.3138 | 2.318 | 324.632 | **5.368** | no — accepted by both |
| `arch_c`/transformer | 325.9070 | 4.816 | 330.723 | **-0.723** | no — over the limit |

**Not one of the six can be a separator, for any `(g, e_total)` in the plausible range.** The
population is bimodal — two points comfortably safe at ~5 K, four over the limit — with **nothing in
the band a separator must occupy**.

This is `archive-census-v1`'s failure repeating: *"the candidate set was chosen so far from the limit
that the certificate could not bind"*. The difference is that it is now visible **before** the pilot
runs, for the cost of one subtraction per case.

## What G2 becomes

**`G2a` — screening, and it is now the whole difficulty.** Find candidates with
`dist in [margin + e_total, g)`. The screen is one HotSpot solve per design under the corrected
trace, and the target band is roughly `0.3 - 3.0 K` from the limit. **The development split does not
contain such a design**, so G2a is a search over a wider population, not a re-run on these six.

**`G2b` — the separator test**, unchanged in substance and now decidable: for each screened
candidate, report `dist`, the legal-mapper reconstruction and the independent replay. A candidate is
a separator for exactly those `(g, e_total)` with `margin + e_total <= dist < g`, reported as that
region rather than as a verdict at assumed constants.

**STOP** fires when G2a cannot populate the band — which is a statement about the design space, not
about the method, and must be written up as such.

## What this repair does not fix

* **`g` still has no source.** Reporting the region defers the question; it does not answer it.
  Publishing a separator still requires establishing what the incumbent convention actually is.
* **`e_total` at the cell endpoint is still unmeasured.** The block-row band stands in for it above,
  and the two are not the same quantity — `CELL_ENDPOINT_RESULT.md` records the cell-level refinement
  tail as unmeasured.
* **The population's `dist` values inherit the trace correction**, whose DRAM placement is the
  generator's stated intent rather than an established physical fact
  (`THE_GENERATOR_PUTS_THE_MISSING_HEAT_CENTRALLY.md`, "What is NOT established").
