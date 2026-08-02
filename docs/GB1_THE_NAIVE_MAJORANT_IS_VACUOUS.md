# G-B step 1: the naive residual majorant is vacuous by 21-64x, and refinement will not fix it

RESULT 2026-08-02, `moe-server`, isolated worktree at pinned `7af7cb1`, clean. Load 3.19-3.23 on 52
cores, GPUs idle. NON-CLAIM diagnostic.

## What was tested and why it decides the route

`PEAKCERT_OPERATOR_PREREGISTRATION.md` registers a **symmetric residual majorant** as the primary and
only open route to a two-sided pointwise envelope: find `z >= 0` with `a(z,v) >= <|r|,v>` for all
`v >= 0`, and the weak maximum principle then gives `|u - u_h| <= z` **pointwise**, both signs at
once. A one-sided supersolution gives only the upper bound and leaves the subsolution — which the
*decision* claim needs — as a second research problem. So this construction is the whole direction.

## The prediction, and it was wrong in magnitude

`steady_heat_fem` uses **P1 Lagrange** with **DG0 coefficients**, so `grad u_h` and `k` are both
constant per tetrahedron and `div(k grad u_h) = 0` exactly inside every element. Elementwise
integration by parts therefore leaves the volume residual equal to **`f` itself** — the entire source
density. Power is non-negative so `|f| = f`, and the majorant problem carries the same volume data as
the original one. That argument predicted a vacuity factor near **1**.

**Measured: 21 to 64.** The volume term is not the dominant one. The face term is: in the true
solution the interior flux jumps cancel in sign, and `|r|` makes every one of them add. My prediction
counted only the volume term and was an order of magnitude optimistic.

## The measurement

`max(z_h) / max(u_h - ambient)`, one unit impulse at a time, 9 sources on a layered
silicon-over-copper box. **This is the favourable case**: the synthetic box has no air-filled void, so
its contrast is `3.08`, not the `1.54e4` of the real package.

| cells/axis | dofs | min | median | max |
| ---: | ---: | ---: | ---: | ---: |
| 6 | 5 341 | 47.81 | **57.95** | 63.93 |
| 12 | 18 421 | 28.10 | **33.85** | 35.39 |
| 18 | 39 349 | 21.04 | **24.82** | 25.64 |

**A certificate reading "the temperature is within +- 25 times the entire temperature rise" certifies
nothing.**

## Refinement does not rescue it, and the rate says so

The factor does fall with `h`, but as `h^0.770` — measured consistently across both refinement steps
(`alpha = 0.776` then `0.765`).

That rate is itself explicable and the explanation is why it cannot be improved: each interior flux
jump is `O(h)`, each face has area `O(h^2)`, and there are `O(h^-3)` faces, so the **total mass of the
absolute-jump measure is `O(1)`** — it does not vanish under refinement. Only the sub-linear residue
does.

Extrapolating the measured rate from the finest run:

    factor 24.82 -> 1  needs h smaller by 64.7x
    in 3D that is 2.7e5 x the cells  ->  ~1.07e10 dofs

**Infeasible by ten orders of magnitude of margin, on the favourable geometry.** The real package,
at contrast `1.54e4`, is worse.

## What this settles

**Equilibration is mandatory, not an optimisation.** The guaranteed-bound literature constructs
`sigma_h` in `H(div)` with `div sigma_h = -f` exactly, precisely so the volume term is annihilated and
only the small mismatch `sigma_h + k grad u_h` survives. This measurement is the quantitative reason
that step exists, on this geometry and this discretisation.

**But equilibration alone does not deliver what G-B needs.** It gives a guaranteed bound in the
**energy** norm. The certificate needs `L^infinity`, and `H^1` does not embed in `L^infinity` in three
dimensions, so the conversion is a separate argument requiring Green-function or max-norm machinery —
exactly the constants the preregistration already closed the max-norm-estimator route over.

**So the honest position after this gate:** the symmetric-majorant route as registered is dead in its
naive form; its repaired form (equilibrated flux + a max-norm conversion) is not an implementation
detail but the research problem itself, and it must be treated as such rather than scheduled as a
step.

## What it does NOT settle

`z_h` here is the **discrete** solution of the majorant problem, not a verified bound on `z`. It is an
*optimistic* estimate of the majorant's size — certifying `z` would need the same machinery again.
That direction of error is what makes the result decisive: if even the optimistic estimate is 25x the
signal, no verification effort layered on top recovers it.

This says nothing about whether an equilibrated majorant would be tight, nor about the real geometry,
the real floorplan, or any temperature. It tests one construction on one synthetic instance and finds
it unusable.

## Two defects this run found in itself

**The first run printed a table of zeros and did not object.** `create_box` grades `z` uniformly while
the layers span `150 um` to `6.9 mm`; a `z`-count sized for the sink put the entire die inside the
first cell, no midpoint landed in it, the source was identically zero, and every ratio printed as
`inf`. The count is now derived from the thinnest layer, and two hard checks refuse rather than
print: at least one cell midpoint inside the die, and the source integrating to `1 W` within 2 %.

**`dolfinx 0.11` requires `petsc_options_prefix` on `LinearProblem`**, which the first attempt did not
pass. Both defects were latent in code that had never been executed.
