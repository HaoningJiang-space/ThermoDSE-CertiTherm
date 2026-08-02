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

* The **~1.9 K headroom** arithmetic. It assumed the boundary-realisation term is nested inside the
  model-form envelope. `MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` retracts that: the sink-top
  spread is 0.345-1.124 K and, paired point by point, **equals or exceeds the model-form band on four
  of six** (1.02, 1.06, 1.38, 1.56).
* **1.124 K as an upper bound on the combined discrepancy.** It is the largest measured value of one
  component. Once decomposition is disallowed, a component cannot bound the whole.
* **`g = 3.0 K` as a sourced convention.** No cited work establishes 3-5 K as the incumbent guard for
  this package class, and ThermoDSE's own 348 K cap is documented as unsupported.

## The one durable contribution, for the fixed-geometry pilot contract

Lift this paragraph; it is the only part worth carrying forward.

> **State the pilot's success criterion as a window, not as a margin or a span.** The question a
> quality claim has to answer is not "how much does the decision variable move temperature" but "is
> there a design the incumbent convention rejects and this method accepts". That is membership in
> the interval `(L - g, L - margin - e_total]`: above the guard's rejection threshold, at or below
> the computed certificate's. Three properties follow, and each is a design constraint on the pilot.
> **The window is bounded above**, so any source omitted from the trace can push a candidate out of
> it -- the pilot must therefore place and conserve compute, NoC, NoP and DRAM energy *before* a
> candidate means anything, not after. **The window's upper edge is not currently a number:**
> `e_total = e_linearisation + e_combined-discrepancy,cell`, and the second term is unmeasured at the
> cell endpoint and may not be decomposed, so the pilot must report the discrepancy interval over
> which each candidate stays inside the window rather than a verdict at one assumed value.
> **Candidates are not separators:** the definition includes an independent replay, so the pilot
> needs a legal-mapper reconstruction and a replay path, and must not use the word until both have
> run.

## Provenance

Drafts v1 and v2 reviewed by Codex (`gpt-5.6-sol`, medium reasoning, read-only), 2026-08-02.
v1: the range formula was mathematically wrong (`max_j inf_p T_j` where `min_p max_j T_j` was
needed), the threshold double-counted twice, and there was no positive branch. v2 fixed those and was
withdrawn for the reasons above. The monotonicity defect in point 1 was reached independently and
confirmed by review. Both drafts remain in git history; neither produced a number.
