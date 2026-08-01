# The band is signed, the clamp is sound for SAFE and unsound for REJECT

FINDING 2026-08-02, from peer review plus a measurement that fixes its scope.

## What the reported band actually is

`one_sided_containment_bounds` returns `u_j = sup_p [T_fine,j(p) - T_coarse,j(p)]` -- a **signed**
one-sided supremum, per row. Both `certify_over_polytope` and `certify_cells` then reduce it with
`band = max(max_j u_j, 0.0)`.

So the published `0.251 - 1.061 K` is a clamped signed one-sided bound. **It is not a symmetric
magnitude band**, which matters because the two want different schema: a magnitude band is one
non-negative number per model, a signed one-sided bound is two.

## Why the clamp is right on one side and wrong on the other

**SAFE.** `slack = limit - margin - linearisation - peak - band`. A negative band would ADD slack --
a certificate improved by the fact that two models disagree. Clamping prevents that and is pinned by
a test.

**REJECT.** `CertiTherm/thermal_constraints.py` states in its own docstring that REJECT means **not
certifiably safe**, not proven unsafe. Its bound uses the same `u_j`:
`T_coarse >= L + margin - u_j`. A negative `u_j` must **raise** that threshold. Clamping it to zero
**lowers** it and manufactures not-safe worlds that the physics does not.

For DSOS this is not cosmetic. The headline is *how many observations suffice*. An inflated REJECT
set inflates the minimum observation set, produces spurious collision witnesses and spurious
`UNSYNTHESIZABLE` verdicts. That is a safe engineering call and a **wrong scientific claim**, and
fail-closed does not license it: fail-closed forbids issuing SAFE without establishing safety, it
does not license misdescribing what a certificate says.

## Measured scope, so nothing is over- or under-stated

`u_j` over the activity set at span 0.30, per row:

| case | rows | min `u_j` | median | max `u_j` | rows with `u_j < 0` |
| --- | --- | --- | --- | --- | --- |
| `arch_a` / resnet50 | 237 | **-0.2110** | 0.2137 | 0.7030 | **20** |
| `arch_a` / transformer | 237 | **-0.3916** | 0.4854 | 1.2748 | **6** |
| `arch_b` / resnet50 | 227 | +0.1160 | 0.4264 | 0.6515 | 0 |
| `arch_b` / transformer | 227 | +0.2238 | 0.7521 | 1.1220 | 0 |
| `arch_c` / resnet50 | 181 | +0.0750 | 0.1623 | 0.2603 | 0 |
| `arch_c` / transformer | 181 | +0.1859 | 0.3673 | 0.4583 | 0 |

**Negative rows are real -- 26 of them.** But the reduction currently applied is `max_j u_j`, which
is positive on all six cases, so **the clamp has never fired and no published number changes**. The
defect is structural rather than contaminating.

It becomes live the moment per-row budgets are used, and per-row is exactly what
`cross_grid_bound` exists to provide and what the DSOS observation-count claim needs. So the schema
must be fixed **before** that step, not after.

## What has to change, and one thing that must not be forgotten

* `error_k` keeps its meaning: the **non-negative symmetric** linearisation residual.
* Add signed `model_form_upper_k` and `model_form_lower_k`. Two fields, because the measured quantity
  is signed and one-sided.
* Derive the sign convention from the **declared decision relation**; producer and verifier must both
  implement the relation being certified.
* **Rebuild every constraint-derived artefact before relaxed rows reach production.** A SAFE row
  subset proved sufficient under a scalar `max` need not remain sufficient once each row is relaxed
  by a different amount -- kernel subsets, reject specifications and collision witnesses all have to
  be re-derived. This is the step most easily mistaken for a receipt swap.
