# WITHDRAWN before running: the cheap mapping-leverage probe

**The probe this file preregistered is withdrawn, and it was never run.** Two preregistration drafts
were written and both were killed by review. The reason for withdrawal is not that the drafts were
badly specified -- the second fixed every defect found in the first -- but that **neither outcome of
the probe would have changed the next action**, which makes it a decision-irrelevant experiment.

## What it was going to ask

Whether some mapping of tasks to cores, on a fixed architecture, produces a power map whose certified
peak lands between the guard band's rejection threshold and the computed certificate's acceptance
threshold. A hit would have been a separator: a design the incumbent convention rejects and this
method accepts. It would have run on the six `grid128` cell operators already on disk, with no new
solves.

## Why it cannot decide anything

**1. Both branches are trace-sensitive, because the target is a bounded window.** The second draft
claimed a witness would transfer -- that unresolved sources "can hide leverage but cannot manufacture
it". That is false. The response matrix is non-negative, so restoring any omitted source is a
monotone increase: `T' = T + Rq >= T`. A witness at 328.0 K inside `(327.0, 328.8]` can be lifted to
329.5 K by restoring DRAM, at which point the guard still rejects it **and the certificate now
rejects it too**. A spatially varying restored source also moves the hot cell, so the argmax need not
survive either. Monotonicity preserves "core placement caused a temperature difference"; it does not
preserve membership in an interval that is bounded above.

**2. The method could not produce the object it named.** A separator was defined as guard-rejected,
certificate-accepted, **and independently replayed safe**. The method only evaluated stored affine
operators. There was no replay, no legal-mapper reconstruction and no acceptance test -- so even
under the current trace the procedure could produce a number, not a separator.

**3. The inner set was not shown to be reachable.** Whole-core permutations were called
mapper-realisable because ThermoDSE's cores are identical by construction. Identical hardware gives
compatibility, not legal execution: it does not establish that every task can run on every
destination core, that the permuted aggregate corresponds to a real assignment, that utilisation and
the comparison horizon are unchanged, or that locality, precedence and capacity admit it.
`CertiTherm/phase_trace.py::ScheduleSpace` disclaims being a legal scheduler in its own docstring.

**4. Neither outcome changes the next action.** A hit still requires the honest trace, a legal mapper
and an independent replay before it means anything. A miss is uninformative, because the omitted
sources are 40.56 % of dissipated energy (DRAM) plus a NoC term spread uniformly and therefore
carrying no spatial signal. Both roads lead to the same next step, which
`docs/THERMODSE_ENDPOINT_AUDIT.md` had already established before this probe was conceived.

## Do NOT reuse these from the withdrawn drafts

* **`g = 3.0 K` as a sourced convention.** No cited work establishes 3-5 K as the incumbent guard for
  this package class, and ThermoDSE's own 348 K cap is documented as unsupported. This is the only
  item on this list that still stands.

### And one that was un-withdrawn under this document's feet

An earlier version of this section forbade reusing the **~1.9 K headroom** arithmetic
(`0.01 + 1.061 = 1.071` K of budget against a 3 K guard) on the grounds that it assumed the
boundary-realisation term was nested inside the model-form envelope, and that
`MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` had retracted the nesting.

**That retraction was itself reversed on 2026-08-02 and the arithmetic is now correct.**
`temperature_grid.c:1054` and `temperature_block.c:207` both divide `r_convec` proportional to cell
area, which is exactly the uniform Robin coefficient `h = 1 / (r_convec * s_sink^2)` the FEM adapter
already used. Neither HotSpot model imposes an isothermal sink top, so there was never a
boundary-realisation term to separate: the 0.251-1.061 K band **is** the model-form band, and
`e_total = e_linearisation + e_model-form` is the right composition after all.

Verified independently at source and in algebra while writing this correction: the two call sites
read as quoted; summing the per-cell conductances over the sink top gives exactly `1 / r_convec`
regardless of discretisation; and the six analytical-identity offsets in
`FEM_ANALYTICAL_VERIFICATION.md` reproduce to ratio 1.0000-1.0001 from `q * slab / (2 k_Cu)`.

The lesson this file should carry is therefore not the arithmetic but the pattern: **a number
withdrawn on a premise is only as withdrawn as the premise.** Two consecutive rounds treated
`r_convec`'s *name* as its specification; one grep of the assembly settled it.

## The one durable contribution, for the fixed-geometry pilot contract

Lift this paragraph; it is the only part worth carrying forward.

> **State the pilot's success criterion as a window, not as a margin or a span.** The question a
> quality claim has to answer is not "how much does the decision variable move temperature" but "is
> there a design the incumbent convention rejects and this method accepts". That is membership in
> the interval `(L - g, L - margin - e_total]`: above the guard's rejection threshold, at or below
> the computed certificate's. Three properties follow, and each is a design constraint on the pilot.
> **The window is bounded above**, so any source omitted from the trace can push a candidate out of
> it -- the pilot must therefore place and conserve compute, NoC, NoP and DRAM energy *before* a
> candidate means anything, not after. **The window's upper edge is not yet a number at the endpoint
> that certifies:** `e_total = e_linearisation + e_model-form`, and while the model-form term is now
> measured against an analytically verified independent solver, that measurement is at *block* rows
> (0.251-1.061 K) while the certificate is evaluated at *cell* rows. The pilot must therefore report
> the model-form interval over which each candidate stays inside the window, rather than a verdict at
> one assumed value, until the cell-endpoint band is measured.
> **Candidates are not separators:** the definition includes an independent replay, so the pilot
> needs a legal-mapper reconstruction and a replay path, and must not use the word until both have
> run.

## Provenance

Drafts v1 and v2 reviewed by Codex (`gpt-5.6-sol`, medium reasoning, read-only), 2026-08-02.
v1: the range formula was mathematically wrong (`max_j inf_p T_j` where `min_p max_j T_j` was
needed), the threshold double-counted twice, and there was no positive branch. v2 fixed those and was
withdrawn for the reasons above. The monotonicity defect in point 1 was reached independently and
confirmed by review. Both drafts remain in git history; neither produced a number.
