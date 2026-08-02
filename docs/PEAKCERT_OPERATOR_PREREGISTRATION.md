# `peakcert-operator`: can a proof-carrying pointwise thermal operator be built at all?

PREREGISTRATION, written 2026-08-02, before any number is read. NON-CLAIM tier by construction.

## What is being proposed, stated so it can fail

Fixed geometry, linear steady conduction. `u(p) = u_0 + sum_i p_i w_i` with `p_i >= 0`, where `w_i`
is the unit-impulse field of power block `i`. The proposal is to certify, **once, offline**,
elementwise envelopes of the CONTINUOUS fields

    lower_w[i,q] <= w_i(q)   at points q,        w_i(x) <= upper_w[i,E]   for all x in E

so that for every admissible `p`

    L(p) = max_q ( lower_u0[q] + sum_i p_i lower_w[i,q] )  <=  ess sup_x u(p,x)
         <=  U(p) = max_E ( upper_u0[E] + sum_i p_i upper_w[i,E] ).

**The bounds are correct** -- both directions follow from `p_i >= 0` preserving the pointwise
inequalities, and `ess sup` over `Omega` being the max over elements. `U` is a maximum of affine
functions of `p`, so it is convex piecewise-linear and goes into an LP/MILP directly, and
`sup_{p in P} U = max_E [ LP over P ]`. Non-negativity of `p` is load-bearing and must be checked
wherever a power model could produce a negative entry.

If this works, one offline certification covers **every** legal power allocation, at the **pointwise**
endpoint rather than the cell average -- which is a level above precomputing the response matrix `R`.

## The conservatism is structural, and that changes what to measure first

Let `E*` be the element attaining `max_E`, `x*` the true maximiser inside it. Then

    U_op(p) - ess sup u(p)  <=  sum_i p_i ( max_E w_i - w_i(x*) )  <=  sum_i p_i osc_E(w_i)

with `osc_E(w_i) = max_E w_i - min_E w_i ~ |grad w_i|_E * diam(E)`.

**Two consequences are predictions, not hopes.** `w_i` is the Green's response of block `i`, so on an
element far from block `i` it is nearly constant and `osc` is small: **the slack should localise to
the few sources near the hot element, not accumulate over all `n`.** And it is first order in element
size, so refinement provably closes it at a rate set by the local gradient.

Together: **the method and its risk are the same object.** Decision-driven refinement can repair the
conservatism precisely because the conservatism sits on the elements refinement would target. That is
the claim this gate exists to falsify.

## The gates, in dependency order

An earlier sketch put the superposition-tightness experiment first. That is backwards: if a single
certified envelope is vacuous, the tightness of `n` of them superposed is not a question.

### G-A. Remove the void. Half a day, and it is the highest-leverage change available

The FEM box is tiled, so the space outside each plate is filled with **still air** at
`0.026 W/(m K)` against copper at `400` -- a contrast of **1.54e4** that is a *meshing convenience*,
not physics: the real package has no material there.

Max-norm a posteriori constants degrade with the ellipticity ratio, so this contrast is the most
likely single cause of a vacuous bound. And it is already measured to be free to remove:
**the void filler moves the peak by `+0.0000 K`** (`MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md`,
which states the alternative in those words -- "still air rather than a **stepped domain**").

**Do:** run the stepped domain (exclude the void rather than fill it) and confirm the peak is
unchanged to the tolerance already used. Contrast then drops to copper/TIM `= 100`.

**Bar:** peak unchanged within the existing energy-balance tolerance; contrast reported before and
after. **Kill:** if excluding the void moves the peak by more than the linearisation contract
(`0.01 K`), the void is not a convenience and every later gate must carry `1.54e4`.

### G-B. `n = 1`. Can ONE certified envelope be non-trivial near its own source?

**This is the only real kill point of the whole direction.** `upper_w[i,E]` must bound the
**continuous** field, not the discrete one, which needs either a max-norm a posteriori bound or a
comparison-principle supersolution -- and the hardest place for both is exactly where the source is,
because that is where regularity is worst.

**Do:** one block, one impulse, on the stepped domain from G-A. Produce a verified `upper_w[E]` for
every element, by whichever of the two routes is constructible, with every term entering the
verification: element residual, interface flux jump, Robin boundary residual, quadrature, and
algebraic solver error.

**Bar:** the envelope is non-vacuous, meaning `max_E upper_w[E]` exceeds the computed peak by less
than **0.5 K** on the source-containing element at the mesh already in use.

**Kill:** if the envelope on the source element exceeds the peak by more than **2 K**, or if no
certified route can be constructed at all, **the operator certificate is dead and PeakCert falls back
to per-candidate certification.** Do not proceed to G-C.

**Registered in advance because it is the likely failure mode:** a supersolution gives only the
**upper** bound `U`. Rejecting better-performing candidates -- which is what makes this a *decision*
certificate rather than a safety certificate -- needs `L`, i.e. a certified **sub**solution or a
two-sided max-norm bound. G-B must attempt both directions and report them separately. **A one-sided
result is a safety certificate only, and the decision claim must then be dropped, not weakened.**

### G-C. Does the conservatism localise, as the theory says?

**Do:** measure `osc_E(w_i)` as a function of the distance from element `E` to source `i`, over the
elements that carry the maximum, for at least 8 sources.

**Bar:** `osc` decays with distance fast enough that at most **4** sources contribute 90 % of the
slack on the hot element -- which is what makes decision-driven refinement able to repair it.

**Kill:** if the slack is spread roughly uniformly over all `n` sources, refinement cannot target it
and the superposition is conservative by construction. Fall back to per-candidate certification.

### G-D. What is the real break-even? Measure the mechanism, do not assume a number

Gate 0 measured that **factorisation is 92-98 % of the linear-algebra cost** and its share *grows*
with mesh size, so `n` impulse *solves* are nearly free. **Whether `n` max-norm *certifications* are
also nearly free is unknown and is the only variable that sets break-even.**

**Do:** measure certification cost per right-hand side, separating shared work (mesh, assembly,
factorisation) from per-field work (residual evaluation, estimator, envelope assembly).

**Bar:** report break-even as a derived number with its mechanism, not as a target. If per-field cost
dominates, break-even is near `n = 181-237` candidates, not the ~32 an earlier sketch asserted with
no derivation.

### G-E. Only now: superposition tightness

**Do:** 16 sources, 100 preregistered mixed non-negative power maps. Compare `U_op(p)` against
`U_direct(p)` built per candidate.

**Bar:** zero false-SAFE; median `U_op - U_direct` <= 0.5 K; P95 <= 1 K.

**Kill:** median above 1 K kills the unified-operator claim and falls back to per-candidate PeakCert.

**Note the bar is barely useful and that is deliberate:** the measured cell-versus-block gap is
0.21-0.62 K and the tightest development point has **0.31 K** of slack, so a certificate of median
width 0.5 K **cannot decide that point**. A pass at this bar means the mechanism works, not that it
is decision-useful; decision-usefulness needs the width below the margin of the population it is
applied to, which is a separate and stricter question.

## An assumption that must be sourced before any of this is published

The whole direction asserts that the **pointwise junction peak** is the right endpoint. `330.0 K` is
frozen in `CertiTherm/frozen_limits.py` with no stated convention. **If the limit is a
tool-convention limit defined on block or cell averages, then certifying the pointwise peak is
stricter than the specification and would reject designs that meet it.** Certifying something nobody
asked for is not rigour, it is a different problem.

**Do (cheap, and it gates the framing not the mechanism):** find the source of the 330 K convention
and record whether it is a junction limit. If it is not, the contribution must be restated as "a
certificate for the junction limit, which the tool convention does not bound", with the gap between
the two conventions measured.

## Not in scope, recorded so it is not re-derived

Lazy adjoint row generation is **not** part of this. Gate 0 verified the adjoint identity (max error
on the unpowered rows, `4.9e-12` to `4.3e-10`, tracking CPU/GPU parity) and **refuted its economics
by measurement**: carrying 64 adjoint rows moved the solve from 0.027 s to 0.077 s against a 1.45 s
factorisation. It survives only as an optional backend justified on MILP constraint count, never on
thermal solve count.

Cross-geometry reuse, the archive's 8 K mechanism, transient scheduling, and enlarging the held-out
split all remain out of scope for the reasons already recorded in `ROUND_PLAN_FIXED_GEOMETRY.md`.

## Execution

Every gate here is FEM/GPU work and runs on `moe-server` from an isolated worktree at a pinned SHA,
per `.claude/skills/moe-server-remote/`. Nothing in this document may be run locally. `/data` is at
95 % (~170 G free) and the host is shared -- record contention alongside any timing, because a
previous runtime comparison in this repo was made uninterpretable by 9 competing jobs.

## Status

**REGISTERED, NOT RUN.** No number in this document was produced by it; every figure is a citation to
committed work.
