# `peakcert-operator`: can a proof-carrying pointwise thermal operator be built at all?

PREREGISTRATION v2, written 2026-08-02, before any number is read. NON-CLAIM tier by construction.

v1 was reviewed adversarially by Codex (`gpt-5.6-sol`, high reasoning) before running and is
superseded. It contained a **mathematical error in its own conservatism bound**, thresholds that were
dimensionally unsupported by a factor of 400, a kill routing that was logically invalid, and a
one-sided treatment of a two-sided problem. All are corrected below; what changed is recorded at the
end, because a preregistration that hides its revision is not one.

## What is proposed, stated so it can fail

Fixed geometry, linear steady conduction. `u(p) = u_0 + sum_i p_i w_i` with `p_i >= 0`, where `w_i` is
the unit-impulse field of power block `i`. Certify, **once and offline**, elementwise envelopes of the
CONTINUOUS fields so that for every admissible `p`

    L(p) <= ess sup_x u(p,x) <= U(p) = max_E ( upper_u0[E] + sum_i p_i upper_w[i,E] ).

The bound is correct: `p_i >= 0` preserves the pointwise inequalities and `ess sup` over `Omega` is
the max over elements. `U` is a maximum of affine functions of `p`, hence convex piecewise-linear and
LP/MILP-representable, and `sup_{p in P} U = max_E [LP over P]`. **Non-negativity of `p` is
load-bearing** and must be checked wherever a power model could emit a negative entry.

## The construction that decides everything: a SYMMETRIC residual majorant

v1 offered "a max-norm a posteriori estimator **or** a comparison-principle supersolution" as
interchangeable routes. They are not, and the choice determines whether a *decision* certificate is
reachable at all.

**The max-norm estimator route is unavailable as stated.** Residual max-norm results give reliability
up to a generic constant, often with logarithmic factors. On a 3D nonconvex polyhedron with
discontinuous coefficients, interface junctions, Robin boundaries and anisotropic thin-layer
elements, that constant *is* the problem. Using this route requires naming a specific theorem and
demonstrating every hypothesis holds — applicability to a 3D nonconvex polyhedron, fully computable
constants, shape-regularity and anisotropy assumptions, coefficient-jump/quasi-monotonicity
conditions, source-discontinuity treatment, explicit discrete Green-function stability, and verified
Robin and interface-jump residuals. **Until such a theorem is named, this route is closed.**

**The primary route is a purpose-built residual barrier.** A conforming FEM solution is not
automatically a supersolution: its distributional residual carries signed face measures from
normal-flux jumps, and a discrete maximum principle orders only *discrete* solutions. What is needed
is `z >= 0` with, in a verified weak sense,

    A z  >=  | f - A u_h |

dominating element residuals, internal-face flux jumps, coefficient-interface terms and the Robin
residual. Comparison then gives **both sides at once**:

    u_h - z  <=  u  <=  u_h + z.

**This is why the route matters and not just the result.** A separately engineered one-sided
supersolution yields `U` only, and a certified *sub*solution is then a second research problem — the
trivial subsolution (ambient) is certified and useless. **Two-sided residual domination is therefore a
PRECONDITION of the decision claim, not an extension of it.**

## The conservatism bound, corrected

v1 wrote `U_op - ess sup <= sum_i p_i (max_E w_i - w_i(x*))` "with `x*` the true maximiser inside
`E*`". **That assumes what must be proved:** the element attaining the envelope maximum need not
contain the true maximiser. It also omitted the certification surplus and the baseline.

Let `Ehat` attain `max_E`, and let `M = ess sup u`. For **any** `x in Ehat`, `M >= u(x)`, so with
`delta[i,E] = upper_w[i,E] - sup_E w_i >= 0`:

    Uhat - M  <=  delta[0,Ehat] + osc_Ehat(u_0)
                + sum_i p_i ( delta[i,Ehat] + osc_Ehat(w_i) )

**Two surpluses, not one, and they need not shrink at the same rate under refinement:**
`delta` is **certification** surplus (how loose the verified envelope is against the true sup over the
element) and `osc` is **structural superposition** surplus (the different-argmax slack). Every gate
below reports them separately.

The first-order heuristic `osc_E(w_i) ~ |grad w_i| h_E` **holds only where `w_i` is in
`W^{1,infinity}`**. At source-block edges, interface junctions, re-entrant edges of the stepped
domain, and where interfaces meet the Robin or insulated boundary, the gradient may be unbounded or
only `L^p`, giving `h^alpha` with `alpha < 1`, and anisotropic elements need directional estimates.
The rate is registered as **measured, not assumed**, outside `W^{1,infinity}` patches.

## Thresholds are derived, not chosen

v1 registered "0.5 K pass / 2 K kill" on the source element. That is dimensionally unsupported:
contrast does not set a local temperature scale. The source-curvature scale for a unit impulse spread
over area `A` and die thickness `t` at local mesh `h` is

    dT_local  ~  P h^2 / (k_Si A t)

Evaluated with this repo's own parameters (`t = 150 um`, `h_z = t/2 = 75 um`, `k_Si = 130`, `P = 1 W`):

| block area | `dT_local` |
| --- | ---: |
| 4.00 mm^2 | 0.072 K |
| 1.00 mm^2 | 0.288 K |
| 0.25 mm^2 | 1.154 K |
| 0.10 mm^2 | 2.885 K |
| 0.01 mm^2 | 28.8 K |

**A 400x range from block footprint alone.** So the threshold cannot be a constant. G-B therefore
**first measures the smallest powered block area in the development architectures**, computes
`dT_local` from it, and registers pass/kill as multiples of that scale — `pass <= 2 dT_local`,
`kill > 8 dT_local` — before any envelope is built. The multipliers are registered here; the kelvin
values are derived on the instance and recorded before the gate is read.

## Gates, in dependency order

### G-A. Stepped domain vs air-filled void — **RUN, and it is not a flag**

> **RESULT 2026-08-02 (`GA_STEPPED_DOMAIN_IS_NOT_A_FLAG.md`): not executable as registered.**
> `steady_heat_fem.py:307` refuses any mesh cell not owned by exactly one region and the domain
> builder always meshes the full box, so a domain with a hole is outside the adapter's contract.
> `dolfinx 0.11.0` does provide `create_submesh`, so it is constructible — as a **new adapter in this
> repository**, with a registered boundary condition on the newly exposed step faces, not as a
> parameter. And `CERTITHERM_FEM_VOID_K` is not a stand-in: lowering it toward adiabatic *raises* the
> contrast to `4e6` rather than removing it.
>
> **Consequence: G-A is no longer a precondition. G-B runs first, at contrast `1.54e4`.** A
> non-vacuous majorant there makes the stepped-domain build unnecessary; only a vacuous one, with the
> failure attributable to contrast rather than to re-entrant geometry or source-edge regularity,
> justifies building it.

#### As originally registered, retained for the comparison it still specifies

The FEM box is tiled, so space outside each plate is filled with still air (`0.026`) against copper
(`400`): contrast `1.54e4`, a meshing convenience rather than physics.

v1 asserted this is free to remove and helps. **Only half of that is defensible.** Removing the air
improves the coefficient ratio to `~100` and should improve conditioning — but it creates a
**nonconvex stepped domain with re-entrant edges and boundary-condition junctions**, which degrades
elliptic regularity and Green-function constants. **There is no general theorem that the net
max-norm constant improves.**

The `+0.0000 K` void sensitivity already measured is also too weak to carry a proof: it is a possibly
rounded figure for one computed peak, it does not bound the *continuous* field difference, and
removing air replaces weak conduction through the filler with boundary conditions on newly exposed
step faces.

**Do:** build the majorant `z` on BOTH domains and compare the verified envelope width and the
constants entering it. Report the unrounded peak difference, its mesh-convergence behaviour, and the
boundary conditions imposed on the step faces.

**Bar:** the verified width on the stepped domain is no larger than on the air-filled one.
**Kill:** if the re-entrant geometry costs more than the contrast reduction buys, keep the air-filled
domain and carry `1.54e4` into G-B explicitly.

### G-B. `n = 1`, two-sided, on every singularity class — the only real kill point, and now FIRST

**Do:** one block, one impulse, on an **interface- and source-fitted** mesh — every material
interface and every source-block boundary exactly aligned with element faces, because a source
boundary cutting elements makes both the residual interpretation and verified quadrature much harder.
Construct `z` with `A z >= |f - A u_h|` verified, and report `u_h ± z`.

**Inspect every singularity class, not the source interior.** A bounded volumetric source is *locally
regular* inside a fitted region, so the worst case is more likely at source-block **edges** where the
right-hand side jumps, at silicon/TIM/copper interface junctions, at re-entrant edges of the stepped
domain, and where interfaces meet Robin or insulated boundaries. v1's "the element containing the
source" is replaced by "all elements intersecting the source support, plus one representative of each
singularity class".

**Quadrature and arithmetic are part of the proof, not a footnote.** Use exact integration where
coefficients, sources and elements are piecewise polynomial and fitted; otherwise certified quadrature
remainders under interval arithmetic. Verify the algebraic residual with directed rounding or a
rigorous enclosure. Geometry snapping and decimal conductivities enter the sign of the inequality.

**Bar:** two-sided, non-vacuous, verified width `<= 2 dT_local` as derived above.
**Kill:** width `> 8 dT_local`, or no verified construction obtainable.

**The certificate width is `max_E upper_w[E] - Mlow`, where `Mlow` is a certified LOWER bound on the
true maximum.** v1 compared the certified upper bound against the *computed* peak, which mixes
envelope excess with FEM error, algebraic error and within-element variation and is not a certificate
width at all. If no lower bound exists, the upper excess against the numerical solution is a
**diagnostic only** and cannot decide the gate.

Point samples are not a workaround for the lower bound: in 3D, point evaluation is not bounded on
`H^1`, and a goal-oriented estimator for a point value has a singular Green-function adjoint and
returns to the same difficulty. If the two-sided barrier is unavailable, the lower endpoint must be
redefined as a certified average over a small positive-volume region.

### G-C. Does the slack localise? Measure the weighted certified contribution, not distance

v1 measured `osc_E(w_i)` against Euclidean distance. **Distance is the wrong explanatory variable in
a layered heterogeneous package** — thermal-resistance paths, interface crossings and proximity to
insulated steps can dominate it, and the slack is `p_i` times *both* surpluses, not unweighted `osc`.

**Do:** on the envelope-active element, measure

    p_i ( delta[i,E] + osc_E(w_i) )

against three candidate explanatory variables separately — Euclidean distance, effective thermal
resistance, and raw source power. For a decision guarantee the relevant quantity is the **worst case
over `P`**, so formulate each source's worst-case contribution as an LP over the polytope rather than
evaluating at hand-picked power vectors. Use at least 16 sources if the claim is to concern 16.

**Bar:** a preregistered concentration statistic on the LP worst case — at most 4 sources carry 90 %
of the slack. **Kill:** slack roughly uniform across sources; refinement cannot target it.

### G-D. Break-even, derived from the mechanism

Gate 0 measured factorisation at **92-98 %** of linear-algebra cost with the share *growing* with mesh
size, so `n` impulse *solves* are nearly free. **Whether `n` max-norm certifications are also nearly
free is unknown and is the only variable that sets break-even.**

**Do:** separate shared work (mesh, assembly, factorisation) from per-field work (residual evaluation,
barrier construction, envelope assembly) and report break-even as a derived number with its mechanism.
v1's "~32 candidates" had no derivation; if per-field cost dominates, break-even is near
`n = 181-237`.

### G-E. Superposition tightness — only after G-B and G-C

**Do:** 16 sources, 100 preregistered mixed non-negative power maps; compare `U_op(p)` against a
per-candidate certified `U_direct(p)`.

**Bar:** zero false-SAFE; median and P95 of `U_op - U_direct` reported against `dT_local`, not against
invented kelvin constants.

**A pass here means the mechanism works, not that it is decision-useful.** The measured
cell-versus-block gap is 0.21-0.62 K and the tightest development point has **0.31 K** of slack, so
decision-usefulness requires the width below the margin of the population it is applied to — a
separate and stricter question than tightness against `U_direct`.

## Kill routing, corrected

v1 said "fall back to per-candidate certification" for every failure. **That is invalid when G-B fails
for existence reasons:** a per-candidate continuous field needs the *same* pointwise certification
method. Four distinct outcomes:

| what failed | consequence |
| --- | --- |
| no continuous two-sided certification method exists at all | **abandon the pointwise claim entirely**; the cell-average certificate is what remains |
| certification exists, but impulse envelopes superpose poorly (G-C/G-E) | fall back to **per-candidate continuous** certification |
| only an upper certificate exists (no subsolution, no symmetric majorant) | retain **safety-only**; the decision-operator direction terminates |
| neither continuous route exists | retain only the existing cell-average certificate |

## An assumption that must be sourced before publication

`THERMAL_LIMIT_K = 330.0` is frozen in `CertiTherm/frozen_limits.py` with **no stated convention**.
If it is a tool-convention limit defined on block or cell averages, then certifying the pointwise peak
is **stricter than the specification** and would reject designs that meet it. Certifying something
nobody asked for is a different problem, not more rigour. Find the source of the convention and record
whether it is a junction limit; if it is not, the contribution must be restated as "a certificate for
the junction limit, which the tool convention does not bound", with the gap between conventions
measured.

## Out of scope, recorded so it is not re-derived

Lazy adjoint row generation: Gate 0 verified the identity (max error on unpowered rows, `4.9e-12` to
`4.3e-10`, tracking CPU/GPU parity) and **refuted its economics by measurement** — 64 adjoint rows
moved the solve from `0.027 s` to `0.077 s` against a `1.45 s` factorisation. It survives only as an
optional backend justified on MILP constraint count, never on thermal solve count.

Cross-geometry reuse, the archive's 8 K mechanism, transient scheduling and enlarging the held-out
split remain out of scope for the reasons in `ROUND_PLAN_FIXED_GEOMETRY.md`.

## What v1 got wrong

1. **The conservatism bound assumed its conclusion** — that the envelope-maximising element contains
   the true maximiser — and omitted both the certification surplus and the baseline term.
2. **The 0.5 K / 2 K thresholds were dimensionally unsupported**, varying 400x with block footprint
   alone. Replaced by multipliers of a derived `dT_local`.
3. **Kill routing was logically invalid**: "fall back to per-candidate" does not answer a failure of
   existence, because per-candidate needs the same method.
4. **The two routes were presented as interchangeable.** They are not: only a symmetric residual
   majorant gives both signs, so the decision claim depends on the route, not just the result.
5. **G-A asserted only the favourable half** — contrast down — and ignored that a re-entrant stepped
   domain degrades the regularity the same constants depend on.
6. **The gate width compared a certified bound against an uncertified peak.**
7. **G-C used distance** where thermal resistance is the physically relevant variable, and used
   unweighted `osc` where the slack is `p_i` times both surpluses.

## Execution

Every gate is FEM/GPU work, runs on `moe-server` from an isolated worktree at a pinned SHA per
`.claude/skills/moe-server-remote/`, and nothing here may be run locally. `/data` is at 95 %
(~170 G free) and the host is shared — record contention alongside any timing.

## Status

**REGISTERED, NOT RUN.** No number here was produced by this gate; every figure is a citation to
committed work or a derivation stated in full.
