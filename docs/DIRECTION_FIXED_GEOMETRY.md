# Direction: thermal-constrained scheduling on a FIXED geometry, not architecture DSE

DECISION 2026-08-01, after peer review and a measurement that reached the same wall from the other
side. This supersedes the "put the certificate inside an architecture search" framing.

## What was proposed, and why it is blocked

The attractive idea: because `T = R p + a` is affine, thermal feasibility is a set of **linear rows**
in the power vector, so it could be a constraint *inside* a search rather than an oracle called once
per candidate. That would change the contribution from a verifier -- which only ever refuses -- into
an optimiser, which is the category that can produce a headline number.

It needs `R` to be reusable across the designs being searched. It is not, and the obstruction is
mathematical rather than practical.

**The measurement.** Over the 64 archive designs: **64 distinct floorplan geometries, zero shared**.
The topology quadruple `(xx, yy, cx, cy)` fixes which blocks exist and how they are arranged, but the
remaining six parameters change block **sizes**, and that changes the geometry every time
(`CAN_THE_OPERATOR_BE_AMORTISED.md`).

**The theorem.** Pulling a perturbed domain back to a reference one turns geometry into coefficients,
`A_theta = (k . Phi_theta)(det J) J^-1 J^-T`, and Lax-Milgram perturbation then bounds
`|u_theta - u_0|` by `|A_theta - A_0|_inf`. But **a small geometric displacement does not give a
small coefficient perturbation**: if a material interface moves and the map is not
material-following, `|k_theta - k_0|_Linf` is the full material jump for *any* nonzero displacement
and does not scale with the geometric distance at all. Silicon against copper against air is a jump
of four orders. The argument needs `Phi_theta` to carry every material subdomain and interface onto
its counterpart, which is far stronger than bi-Lipschitz.

Two independent routes, one conclusion. A third supports it: the exact reuse band measured within a
design class is **0.69 - 2.44 K**, against a model-form band of 0.25 - 1.06 K -- so amortising across
geometry costs one to ten times the term the whole method exists to measure.

## What the pivot removes

On a **fixed** architecture, with scheduling, workload mapping and power allocation as the decision
variables:

| obstruction | status after the pivot |
| --- | --- |
| `R` reusable across geometry | **not needed** -- the geometry is fixed, `R` is built once |
| `p = Psi(theta)` non-linear through partition/schedule/map | **does not arise** -- the decision variable *is* the power allocation, so the constraint really is linear in it |
| robust LP dualisation gives design-variable times dual-variable products | **vanishes**, because the uncertainty set no longer moves with the design |
| the design space must first be decomposed into topology classes | **unnecessary** |

What it does **not** remove is the `L^infinity` gap: the limit constrains `ess sup u` while the
certificate controls block averages, and `H^1` does not embed in `L^infinity` in three dimensions, so
no amount of refinement closes it. That is tracked separately and is now the top open item.

## Why the comparison surface is also better

Fixed-architecture scheduling and mapping is where the literature actually is -- SoMa, Stream, CoSA
-- so the baselines exist and are the right ones. Thermal-aware chiplet **architecture** DSE has, by
contrast, either no thermal constraint at all or one solve per candidate, with nothing in between.

## The claim shape this permits

> On a fixed chiplet architecture, thermal feasibility over a declared power-uncertainty set is a set
> of linear rows, exactly computable from `n + 1` impulse solves. A schedule search constrained by
> those rows performs **zero thermal solves online**, against one HotSpot call per candidate for the
> incumbent, and reaches designs a guessed guard band rejects.

The speed half is structural and does not depend on any unproved reuse. The quality half is the
number that does not exist yet.

## What remains open, honestly

* **`L^infinity` versus `L^2`.** Four routes: interface regularity (fails here -- multi-material
  jumps generally give `s < 1/2`), De Giorgi-Nash-Moser (constant depends on `k_max/k_min ~ 1e4` and
  is likely vacuous, though that must be evaluated rather than asserted), pointwise a-posteriori
  estimation, and **certified supersolutions via the comparison principle**, which is one-sided and
  therefore the right shape for a fail-closed certificate. The last is preferred.
* **The reference is still discrete.** `grid512` against FEM against a finer FEM are all operators.
  A residual-type a-posteriori bound is the exit, and it needs a computable coercivity constant --
  the Successive Constraint Method, cited not reinvented -- plus interface-fitted meshes, data
  oscillation and quadrature terms. The abstract inequality is not itself computable.
* **`gridN-avg` breaks reciprocity** by 2.5 - 7.9 %, shrinking with refinement
  (`CertiTherm/reciprocity.py`). Any band computed on `gridN-avg` rows therefore contains a mapping
  artefact. `block` and the FEM are symmetric to machine precision, so a `block`-versus-FEM band does
  not carry it.
* **`ThermalFamily.error_k` is one non-negative scalar per model** and cannot hold the signed
  per-row bands the polytope machinery produces. The certified path and the frontier path are
  therefore still separate, and joining them needs a schema change under a new freeze.

## Explicitly demoted

Architecture-level DSE with an internalised thermal constraint is **future work with a named
obstruction**, not an unlucky engineering problem. Reviving it requires a material-following
`Phi_theta`, which means a parameterisation whose block sizes are fixed within a topology -- a change
to the design space, not to this method.
