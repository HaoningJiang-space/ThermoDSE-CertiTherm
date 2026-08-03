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

## The structural test: equilibration is the best case, and the best case is still exactly vacuous

An `H(div)`-conforming `sigma_h` with `div sigma_h = -f` annihilates the interior face measures
entirely, so **dropping the `dS` term is the optimistic limit of what equilibration can do to the
term that dominates the naive number**. Measured on the same instances:

| | min | median | max |
| --- | ---: | ---: | ---: |
| naive | 28.10 | **33.85** | 35.39 |
| **equilibrated best case** | **1.0001** | **1.0012** | **1.0016** |

Removing 97 % of the majorant leaves the factor at **1.0012**.

**This was predicted before it was run, and the prediction is the point.** For any `H(div)`
reconstruction,

    div rho = div sigma_h + div(k grad u_h) = -f + 0 = -f

so converting the gradient-form residual `int rho . grad v` back into a measure — which the comparison
principle requires, since it needs `<r,v> <= <mu,v>` for `v >= 0` — **regenerates `f` in the volume,
whatever the reconstruction**. And `z` solving `a(z,v) = int f v` is the temperature rise itself, so
the factor is 1 by construction. The measurement agrees to 0.16 %.

**A certificate reading "within +- 1.0012 times the entire rise" is exactly as useless as +- 25
times.** The failure is structural, not a matter of tightness.

## What this settles

**Equilibration is mandatory, not an optimisation.** The guaranteed-bound literature constructs
`sigma_h` in `H(div)` with `div sigma_h = -f` exactly, precisely so the volume term is annihilated and
only the small mismatch `sigma_h + k grad u_h` survives. This measurement is the quantitative reason
that step exists, on this geometry and this discretisation.

**But equilibration alone does not deliver what G-B needs.** It gives a guaranteed bound in the
**energy** norm. The certificate needs `L^infinity`, and `H^1` does not embed in `L^infinity` in three
dimensions, so the conversion is a separate argument requiring Green-function or max-norm machinery —
exactly the constants the preregistration already closed the max-norm-estimator route over.

**So the honest position after this gate:** the symmetric-majorant route is dead, and not only in its
naive form. Equilibration repairs the face term and cannot repair the volume term, because `f` is
regenerated by the integration by parts the comparison principle requires. The route is closed for
this problem independently of reconstruction quality.

**What is NOT established is that no method exists.** Two mechanisms were considered and both are
closed here — comparison-principle majorants **structurally**, by the argument above, and maximum-norm
a posteriori estimators **on their constants**, which the preregistration closed for a 3D nonconvex
polyhedron with coefficient jumps. A third mechanism is not excluded; it is unexamined. That
distinction is deliberate: this project has already once withdrawn a valid finding on a premise that
was never checked, and "these two do not work" is what was measured, not "none can".

**No external review was obtained for this conclusion.** Codex reached its usage limit (available
again 2026-08-08) on both the first attempt and the inline retry, so the analysis above is Claude's
alone and is labelled as such. The mitigating fact is that the structural claim was submitted for
adversarial attack *before* the equilibrated column was measured, and the measurement is that claim's
own falsification test: it predicted a factor of 1 and returned 1.0012.

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

---

# EQUILIBRATION IS NECESSARY AND NOWHERE NEAR SUFFICIENT — measured 2026-08-02

The failure above was attributed to the face term, and the standard remedy is an equilibrated flux
reconstruction (Braess–Schoberl, Ern–Vohralik) whose interior jumps are identically zero. Rather than
write a week of local patch problems to find out, the **best case** was measured directly: dropping
the `dS` term is an exact model of what equilibration can achieve, because it touches nothing else.

`--cells 12 --grid 3`, 9 sources, same layered box:

| | min | median | max |
| --- | ---: | ---: | ---: |
| naive | 28.0966 | **33.8451** | 35.3924 |
| equilibrated, best case | 1.0001 | **1.0012** | 1.0016 |

**The face term is 33.8x everything else, so equilibration removes 97 % of the majorant — and the
route still dies, because what is left is exactly 1.**

## Why 1.0 is not a near miss but the structural floor

A factor of 1 says the certificate is `|u - u_h| <= z` with `max z = max(u_h - ambient)`: **the bound
is the entire signal**. And it is exactly 1 for a reason this document's own opening already stated
without drawing the consequence:

> "The volume residual is `f` — **the entire source density**, not a small quantity."

With P1 Lagrange over DG0 coefficients, `grad u_h` and `k` are both constant per tetrahedron, so
`div(k grad u_h) = 0` exactly inside every element and the volume residual reduces to `f` itself.
The majorant problem `a(z,v) = <|f|,v>` is then **the forward problem**, with the same load and the
same operator, so `z = u_h - ambient` and the factor is identically 1. Measured 1.0001–1.0016; the
excess is the Robin residual.

**So the residual-majorant route cannot certify anything under P1+DG0 at any mesh, with or without
equilibration.** Refinement does not help either: the ratio is 1 independently of `h`.

## What this kills and what it leaves

**Killed:** equilibration as *the* fix. It is necessary — 97 % of the naive majorant is the face term
— but it converts a 34x vacuity into a 1.0x vacuity, and 1.0x certifies nothing.

**Left, and it is a different piece of work:** the volume residual has to become a genuinely small
quantity, which requires a discretisation where `div(k grad u_h)` is not identically zero — **P2 or
higher**. Then the volume residual is `f + div(k grad u_h)`, which vanishes under refinement, and
equilibration is still needed to kill the face term. **Both, not either.**

That is a substantially larger change than was scoped: it replaces the element family in
`steady_heat_fem`, which every operator, parity result and cross-solver band in this repository was
built on.

## The preregistered consequence

`PEAKCERT_OPERATOR_PREREGISTRATION.md` registers the symmetric residual majorant as "the primary and
only open route to a two-sided pointwise envelope", and says so explicitly: *"this construction is the
whole direction."* Under P1+DG0 that construction is now measured to be structurally vacuous.

**The route is not refuted — the element family is.** Re-running it on P1 in any form, equilibrated
or not, would reproduce a known negative result.

---

# P2 CROSSES BELOW 1 — AND THE ROUTE IS STILL DEAD

**READ THE VERDICT AT THE END.** The framing in this section borrowed a SUPERSEDED threshold and led
with a median where a certificate needs a maximum. Both were caught by review and both made the
result look better than it is. The corrected verdict is a KILL of the pointwise-majorant route at
every degree, not just at P1.

# P2 crosses below 1 for the first time — measured 2026-08-02

The section above concluded that the element family, not the route, is what P1+DG0 refutes: the
volume residual is `f` itself because `div(k grad u_h) = 0` inside every element, so the majorant
problem IS the forward problem and the factor is identically 1 whatever the mesh. The probe now takes
`--degree`, and the volume residual is written honestly as `f + div(k grad u_h)`.

`--cells 12 --grid 3`, 9 sources, same layered box:

| degree | naive median | **equilibrated median** | equilibrated max |
| ---: | ---: | ---: | ---: |
| 1 | 33.8451 | **1.0012** | 1.0016 |
| **2** | **5.4873** | **0.8545** | 1.0790 |

**The prediction holds.** With P2 the divergence term is a genuine cancellation rather than an
identity, so the naive factor falls 6.2x and the equilibrated one falls below 1 for the first time —
**40x end to end** against the P1 naive baseline. The face term also shrinks from 33.8x of the rest
to 6.4x, so equilibration matters less at P2 and the volume term is no longer the floor.

## But this is "the route is alive", not "the route works"

The rise is ~6.4 K and the factor is 0.8545, so the certificate half-width is **~5.5 K**. The
preregistered threshold in `PEAKCERT_OPERATOR_PREREGISTRATION.md` is a **median <= 0.5 K**, so the
construction is still **~11x** away at this mesh, and `equilibrated max = 1.0790` means one source is
still above 1.

**Whether refinement closes an 11x gap is the whole question, and one mesh cannot answer it.** At P1
the naive factor decayed only as `h^0.770`, for a structural reason: the total mass of the
absolute-jump measure is `O(1)`. At P2 that argument does not bind the volume term, which should
converge at the element's own rate — but it is unchanged for the face term, which is now 6.4x of the
rest rather than 33.8x. A refinement sweep is running on `moe-server`.

**Settled either way:** equilibration alone was never going to be enough (P1 equilibrated is 1.0012),
and the element family really was the binding constraint. **Not settled:** whether P2 plus
equilibration reaches a decision-useful width or merely a smaller useless one.

**Cost, stated up front.** Moving `steady_heat_fem` to P2 changes the element family every operator,
parity result and cross-solver band in this repository was built on. That is a Tier-2 change and it
is not authorised by this probe — the probe exists to say whether it would be worth asking.


---

# VERDICT: the route is dead at every degree, and refinement cannot save it

Two independent results, both after the section above was written.

## 1. The decay rate is unchanged by the element degree

| cells/axis | dofs | equilibrated median |
| ---: | ---: | ---: |
| 6 | 36 673 | 1.4380 |
| 12 | 135 625 | **0.8545** |
| 18 | — | timed out at 4 000 s |

The measured rate is **`h^0.751`** — statistically the same as P1's naive **`h^0.770`**. That is
exactly what the structural argument predicts and nobody drew the consequence: the `O(1)` mass of the
absolute-jump measure is a statement about **faces**, and it does not depend on the element degree.
P2 replaces the volume term; **the face term still sets the rate.**

Extrapolating on the measured rate, reaching the registered bar from `cells = 12` needs **24.2x**
refinement in `h`, i.e. **~290 cells per axis** and **~1.9e9 dofs in 3-D** — on a synthetic box of
contrast 3.08, against a real package at 1.54e4. That is not a resource problem to be solved, it is a
refutation.

## 2. The threshold I compared against was the SUPERSEDED one, and the error flattered the result

`PEAKCERT_OPERATOR_PREREGISTRATION.md` v2 **explicitly repudiates** the flat `0.5 K` bar this
document quoted — it calls it dimensionally unsupported, "a 400x range from block footprint alone"
— and registers instead **pass at `<= 2 dT_local`, kill at `> 8 dT_local`**. For this probe's
geometry (`8 mm` box, `3x3` grid, so `7.11 mm^2` per block) the preregistration's own inverse-area
scaling gives `dT_local ~ 0.04 K`, hence

| | registered bar |
| --- | ---: |
| pass | **~0.08 K** |
| kill | **~0.32 K** |
| **measured half-width** | **~5.5 K** |

**That is ~17x past the KILL bar, not "11x from the pass bar".** The earlier framing borrowed a
stale threshold and understated the failure by a factor of 6–17. Corrected here rather than left
standing.

## 3. The headline used a median where a certificate needs a maximum

`equilibrated max = 1.0790`. A certificate must hold for **every** source, and by this document's own
P1 standard a factor above 1 is vacuous — so the P2 construction is **still vacuous for at least one
of the nine sources** before any threshold is applied. "Crosses below 1" was true of the median and
false of the object being certified.

## What this kills, and what survives

**Killed: the symmetric residual majorant as a route to a two-sided pointwise envelope, at any
element degree.** The preregistration calls this construction "the whole direction"; it fails its own
registered kill bar by ~17x, its convergence rate is set by a face term that no degree change
touches, and it is vacuous for at least one source even at the median-friendly reading.

**Survives, and is worth keeping:** the measurement chain itself. The probe now takes `--degree`, the
volume residual is written honestly as `f + div(k grad u_h)`, and the P1-versus-P2 comparison isolates
which term sets the rate — which is the fact that closes the route.

**Two defects in the probe, recorded rather than fixed** (they do not affect any committed number,
which used the default path): `--no-faces` is parsed and never used, so its banner lies when passed;
and the P2 section reports only summary factors, not the per-source rises the P1 table showed, so the
"~6.4 K rise" behind the "~5.5 K half-width" is not independently checkable from what is committed.

**Not established:** that no pointwise route exists. What is established is that *this* one does not,
and that the next candidate must break the face term's `O(1)` mass rather than change the element.
