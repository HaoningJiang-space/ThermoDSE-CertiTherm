# The certificate is a sort, not a simulation — the exactness argument and its price

METHOD 2026-08-04. States the three properties leg 1 must have for a search loop to be allowed to
call the certificate instead of a thermal simulator, and where each is proved and pinned.
**No external review** — Codex quota-locked to 2026-08-08.

## The claim

For a fixed geometry, deciding thermal feasibility of a candidate over a **declared activity
envelope** costs one matrix–vector product and one sort per row, and the answer is the **exact
supremum** — not a relaxation, not a bound, not a sample.

Measured: `radius_solve_s = 0.244 s` for eight envelope widths plus a bisection to `1e-4`, over
`16 384` cell rows and 37 blocks. That is roughly **12 ms per candidate evaluation**, against one
HotSpot invocation — measured here at 20-30 s per solve on this package — for the simulate-and-guard
approach. Three to four orders of magnitude, and it is what makes leg 2 possible at all.

## P1 — the supremum is exact, because the support function of a box with a total is a knapsack

The envelope is `P(s) = { p : l <= p <= u, sum p = T }` with `l = p_nom (1 − s)`,
`u = p_nom (1 + s)`, `T = sum p_nom` (`activity_bounded_power_space`; the class-total caps are
implied by the box and that implication is itself pinned by a test).

For a row `r` of the thermal operator, `sup_{p in P} r·p` is a linear program over a polymatroid-free
box with one equality — the **continuous knapsack**. Its optimum is attained by the greedy: sort the
coordinates by `r_i` descending, set every coordinate to `l_i`, then walk the spare budget
`T − sum l` up the order, raising each coordinate to `u_i` until the budget is exhausted and taking
the remainder at the breakpoint. Exchange argument: if an optimal `p*` has `p*_i < u_i` and
`p*_j > l_j` with `r_i > r_j`, moving `eps` from `j` to `i` preserves the total, preserves
feasibility for small `eps`, and strictly increases the objective — so no such pair exists at the
optimum, which is exactly the greedy's structure.

`cross_grid_bound._extreme_rows` computes this for every row at once as an `argsort` plus a prefix
sum, which is where the 12 ms comes from: `16 384` rows are one sorted array, not a loop.

**Independently checked, not asserted.** `docs/MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` reports
the LP and the greedy agreeing to **1.07e-9 K** across every peak and band on the development split,
at spans 0.05, 0.30 and 1.20, with the LP's own slack `b − A·upper` zero to machine precision. The
greedy is the fast path and the LP is the oracle; they are not two names for one implementation.

## P2 — one-sidedness, so a certificate can only ever be too strict

Three quantities enter the comparison and each is folded in the direction that makes certification
**harder**:

| term | value | direction |
| --- | ---: | --- |
| the limit | `330.0 K` | fixed |
| decision margin | `−0.05 K` | subtracted |
| linearisation band | `−0.01 K` | subtracted, two-sided contract applied one-sidedly |

and the objective is a supremum rather than a sample. Widening the envelope is likewise one-signed:
`P(s) ⊆ P(s′)` for `s ≤ s′`, so a verdict certified at a span holds at every narrower span. That is
what makes the sweep a robustness curve instead of a tuning knob, and it is what makes the radius
well posed.

**Monotonicity is checked at run time, not assumed.** `thermal_robustness_radius.radius` refuses to
bisect if the measured supremum ever falls as the span grows, because a non-monotone sweep would mean
the polytope construction no longer nests — the one premise the bisection rests on.

## P3 — fail-closed, with the refusals distinguished

`CERTIFIED` / `REFUTED_AT_NOMINAL` / `REFUTED_AT_MIN_SPAN` / `UNRESOLVED`, never a fabricated number.
Two refusals rather than one, because *"the point evaluation the field reports already fails"* and
*"it clears the nominal point but tolerates no variation"* are different findings and collapsing them
would report an infeasible design as a merely fragile one.

Every guard checks `math.isfinite` **first and separately**. `NaN <= ceiling` and `NaN > ceiling` are
both False, so a single inequality would let a non-finite supremum pass the check *and* be recorded —
the defect class this repository has now found in `_extreme_rows`, `load_capture_metrics`,
`CertifiedContract`, the vertex-cover weights, `anytime_dsos`'s budget and the spectral tail.

## What P1–P3 do NOT give

* **A pointwise peak.** The certified quantity is a max of cell averages. `H¹(Ω)` does not embed in
  `L^∞` in three dimensions, so no grid refinement closes the gap to the pointwise temperature the
  limit nominally refers to. The route with a prospect is a comparison-principle supersolution, which
  is one-sided and therefore matches what a fail-closed certificate needs; it is not done.
* **Cross-geometry reuse.** `R` is valid for the geometry it was built on. `DIRECTION_FIXED_GEOMETRY`
  measured reuse within a design class at 0.69-2.44 K against a model-form band of 0.25-1.06 K, so
  amortising `R` across geometries costs one to ten times the term the method exists to measure.
  Leg 2 does not reuse across geometries; it **caches per geometry** and exploits the fact that the
  design space factors into geometry × power.
* **The model-form band.** Not folded into these numbers. Folding it in lowers every slack by
  0.25-1.43 K and turns two of the development split's five certifications into `UNRESOLVED`.

## Where each property lives

| property | code | evidence |
| --- | --- | --- |
| exact supremum | `CertiTherm/cross_grid_bound._extreme_rows` | LP agreement to 1.07e-9 K |
| envelope construction | `CertiTherm/measurements.activity_bounded_power_space` | class-total implication pinned by test |
| one-sided folding | `CertiTherm/cell_certificate.certify_cells` | `docs/THERMAL_ERROR_CONTRACT.md` |
| monotone nesting | `thermal_robustness_radius.radius` | checked per run, refuses on violation |
| fail-closed status | same | four statuses, finiteness checked first |
