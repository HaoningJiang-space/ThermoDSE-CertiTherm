# `g1-mapping-leverage`: can any MAPPING change flip a thermal verdict?

> **This is a mapping gate, not a scheduling gate, and the distinction is the operator.**
> `T = R p + a` is the STEADY affine map, so it answers questions about a time-averaged
> power vector. A real time-scheduling claim -- ordering, release times, transient peaks --
> needs a state recursion `x_{t+1} = A x_t + B p_t + c`, which this repository has in
> `CertiTherm/transient.py` and which is NOT what this gate uses. Every use of "schedule"
> below means "a steady mapping of tasks to cores", nothing more.

PREREGISTRATION v2, written 2026-08-02, before any number is read. NON-CLAIM tier by construction.

v1 of this document was withdrawn before running. It asked "how far can scheduling move the peak"
and compared the answer against a scalar 1.0 K threshold. Peer review (Codex, `gpt-5.6-sol`, medium)
found four defects that between them made it undecidable, and one of them was a mathematical error
in the quantity itself. What replaces them is recorded in "What v1 got wrong" at the end, because a
preregistration that hides its own revision history is not one.

## The question, in the form that has an answer

The fixed-geometry mainline (`docs/DIRECTION_FIXED_GEOMETRY.md`) needs a **separator**: a schedule
that a fixed guard band rejects, that the computed thermal constraint accepts, and that an
independent replay confirms safe. That is a statement about a *decision boundary*, not about a span.

So the gate asks the decision question directly:

> **Is there a mapper-realisable power map whose certified peak lands strictly between the
> guard band's threshold and the computed certificate's threshold?**

If yes, the separator exists and the gate has produced it rather than a proxy for it. If no
mapper-realisable map can even reach that window, the mainline has nothing to sell.

## The two boundaries, fixed before running

Write `F(p) = max_j T_j(p)`, `T_j(p) = r_j . p + a_j`, over the `grid128` cell rows already built
for `docs/CELL_ENDPOINT_RESULT.md`. `L = 330.0 K`, margin `0.05 K`.

| boundary | expression | value |
| --- | --- | --- |
| **A -- guard rejects above this** | `L - g` | **327.00 K**, at `g = 3.0 K` |
| **B -- computed certificate accepts up to this** | `L - 0.05 - e_total` | see below |

`g = 3.0 K` is the **tightest** end of the 3-5 K incumbent convention. Choosing the tightest makes
the separator window narrowest and the gate hardest to pass, which is the conservative direction for
a gate that authorises work.

`e_total` for a cell-endpoint certificate is

    e_total = e_linearisation + e_combined-discrepancy,cell

**and the second term may not be decomposed.** `MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` now
records that the bound on the boundary-realisation term -- the sink-top spread -- is
**0.345 - 1.124 K**, and that paired point by point it **equals or exceeds the model-form band on
four of the six** (ratios 1.02, 1.06, 1.38, 1.56). So the FEM-minus-HotSpot difference is a
*combined* discrepancy; calling any part of it model form is unsupported until the lumped
sink-to-ambient node is implemented directly and the two are separated by construction.

An earlier draft of this document wrote "boundary realisation (0.345 K) is nested inside the
model-form envelope, so adding it double-counts". **Both halves were wrong**: 0.345 K is the
smallest of six values, not the term, and the term is not dominated by the envelope it was assumed
to sit inside.

The magnitude is also not measured at the cell endpoint: the 0.251-1.061 K envelope is a *block-row*
result and `CELL_ENDPOINT_RESULT.md` records the cell-level refinement tail as unmeasured.

One term is explicitly NOT added: **cell-minus-block (+0.213 to +0.623 K) is an endpoint
replacement, not an error.** Stage A evaluates cell rows directly, so there is nothing to translate
and nothing to budget.

So boundary B is reported as a **curve, not a point**: the verdict is computed for
`e_combined-discrepancy,cell` swept over `[0.00, 1.124]` K -- the upper end being the largest
measured sink-top spread, since the term may not be decomposed, and the document reports at which value, if any,
the verdict changes. A gate that pretended to know an unmeasured number would be inventing the thing
it is supposed to test.

## Scope, stated before the method so it cannot be widened afterwards

This gate tests **iso-core-power, steady-state, average-power schedules, under the current trace
semantics**. Each qualifier excludes a real class of scheduling effect and each is load-bearing:

* **iso-core-power.** The relaxation holds total core power at its placed value. A schedule that
  changes utilisation changes total energy, so schedules outside that slice are not covered.
* **steady-state, average power.** The operator is the steady affine map. Two schedules with the
  same average per-block power can differ in transient peak, and two schedules with different
  latency need a declared comparison horizon. Neither is bounded here.
* **current trace semantics.** From `docs/THERMODSE_ENDPOINT_AUDIT.md`: of the 13.68 W reaching
  HotSpot, core is 12.0756 W over 80 spatially resolved columns; NoC is 1.6064 W spread **uniformly**
  over `io_*`, which "destroys its spatial information by construction"; NoP contributes 0 W; DRAM
  contributes 0 W while being 40.56 % of dissipated source energy. Restoring any of those as a
  spatially resolved, schedule-dependent source could add leverage this gate cannot see.

## Method

Both bounds run on assets already on disk -- the six `grid128` cell operators and the six captures.
**No new impulse solves, no ThermoDSE runs, no scheduler.**

### Outer bound `U` -- a scale, not a verdict

`P_out`: hold every non-core column at its placed value, hold the total core power at its placed
value, let each of the 80 core columns range over `[0, total_core]`.

    max_p F(p)  =  max_j [ a_j + sup_{p in P_out} r_j . p ]        -- commutes, exact by greedy fill
    min_p F(p)  =  min over (p, z) of z  s.t.  r_j . p + a_j <= z for all j,  p in P_out
                                                                  -- epigraph LP, NOT max_j inf_p

The second line is the correction v1 needed. `max_j inf_p T_j <= inf_p max_j T_j`, so v1's formula
overstated the reachable range.

`P_out` is a strict superset of the iso-core-power reachable set: it permits power to move between
`mtxu`, `vecu` and buffers, which no scheduler can do. It bounds how much spatial structure the unresolved sources would have to supply
before a mapping could reach the boundary at all. See the verdicts section for why that is a scale
and not a kill.

### Inner bound `L_reach`, for the supported branch

A schedule reassigns a task to a different **core**, and the whole per-core power profile travels
with it. ThermoDSE's cores are identical by construction -- `h_sa`, `w_sa`, `ubuf_size` are
single design-vector entries applied to every core -- so **permuting whole cores as units is
mapper-realisable by definition**, while permuting individual columns is not.

`NAME_LIST_3D = [mtxu, vecu, ubuf, ibuf, obuf, io_0..io_3]` per core, so a core-permutation moves
each core's whole tuple. Sample `K = 2000` such permutations per case, plus a hill-climb from the
placed assignment maximising `F`, and evaluate `F` at each. No LP: these are evaluations.

`L_reach` is the set of `F` values actually witnessed. It is a **lower** bound on the reachable
range, because the sample is a subset -- which is the correct direction for a branch that authorises
work.

## Verdicts -- and why only one branch of this gate transfers

**This gate is not a kill gate. Its two branches have different epistemic strength, and an earlier
draft of this document had that backwards.**

The asymmetry comes from the trace, not from the method. Of the 13.68 W reaching HotSpot, the core
term is 12.0756 W over 80 columns, **100 % in-domain and spatially resolved** -- 88.3 % of the placed
power, and the term a mapping actually moves. The other terms are not resolved at all: NoC is smeared
uniformly, NoP contributes 0 W, DRAM contributes 0 W while being 40.56 % of dissipated source energy.

* A **witness found** on the core term is real leverage, merely underestimated. Restoring the missing
  terms can only add spatial structure a mapping could exploit. **The positive branch transfers.**
* A **witness not found**, and even a clean outer-bound miss, says nothing about mapping under an
  honest trace. **The negative branch does not transfer.**

So the verdicts are:

* **`SEPARATOR-WITNESSED`** -- for at least two of the six cases, a witnessed core-permutation lands
  strictly inside the window `(L - g, L - 0.05 - e_total]`. The witness **is** a separator, exhibited
  rather than inferred, and it survives the trace defects because those defects can only have hidden
  leverage, never manufactured it. **This is the only verdict that licenses further investment.**
* **`NO-WITNESS-UNDER-CURRENT-TRACE`** -- no witness, whether or not the outer bound reaches the
  window. **This does NOT kill the fixed-geometry mainline.** It says the cheap route did not find a
  separator on the 88 % of power that is resolved, and therefore that the binding next step is the
  honest trace -- placing and conserving compute, NoC, NoP and DRAM energy -- not more search over a
  defective one.
* **`UNRESOLVED`** -- any case whose polytope is empty, whose LP returns non-optimal, or whose
  operator fails its reciprocity or energy-balance check. Counts against neither branch. A gate that
  silently drops a case is not a gate.

Two of six, not one: a single existential hit under a sampled search is a weak escalation rule, and
the six cases are three architectures at two workloads, not a population.

## What this gate is for, stated plainly

**Half a day, zero new solves, and the only thing it can do is hand over a separator early.** It is
run because that outcome would shortcut the expensive experiment, not because its silence would
settle anything. Nothing in this document authorises abandoning fixed-geometry thermal mapping.

The outer bound `U` is retained for one narrow purpose: if it misses the window by a wide margin, it
quantifies **how much** spatial structure the missing sources would have to supply before a mapping
could reach the boundary at all -- which is a number the honest-trace work can be designed against.
It is a scale, not a verdict.

**K3.** A case whose polytope is empty, whose LP returns non-optimal, or whose operator fails its
reciprocity or energy-balance check is **UNRESOLVED** and counts against neither branch. A gate that
silently drops a case is not a gate.

## Rollback

One document, no code on the certified path, no new artifacts. Nothing to roll back.

## Requested dissents (>= 3)

1. **The core-permutation model is still too generous.** Real schedules are constrained by data
   locality and dependence; the permutations that maximise `F` may be exactly the ones a
   reuse-maximising scheduler would never emit, so `L_reach` may witness a separator no scheduler
   reaches.
2. **`g = 3.0 K` is asserted, not sourced.** No cited work states that 3-5 K is the incumbent guard
   convention for this package class; ThermoDSE's own 348 K cap is documented as *unsupported*. If
   the real convention is looser, the window widens and the gate becomes easy.
3. **Sweeping `e_combined-discrepancy,cell` reports a curve where a decision is needed.** If the verdict flips
   inside the swept range, the gate has produced a conditional answer and the mainline decision still
   waits on a measurement nobody has scheduled.
4. **Iso-core-power may exclude the mappings with the most leverage.** If utilisation is what moves
   temperature, this gate is bounded away from the effect it is trying to detect, and a
   `NO-WITNESS-UNDER-CURRENT-TRACE` result would be an artefact of the slice rather than evidence
   about mapping at all.

## What v1 got wrong

Recorded because the same errors are easy to reintroduce.

1. **The span formula was wrong.** v1 used `max_j sup_p T_j - max_j inf_p T_j`. The range of
   `F = max_j T_j` needs `max_p F - min_p F`, and the minimum requires an epigraph LP.
2. **The 1.0 K threshold double-counted twice** -- boundary realisation is nested inside the
   model-form envelope, and cell-minus-block is an endpoint replacement rather than an error. With
   correct nesting the implied headroom is ~1.9 K at a 3 K guard, not 1.0 K.
3. **The gate had no positive branch.** An outer relaxation can only kill. v1 called a non-kill a
   PASS and let it authorise Stage B.
4. **"A gate that closes on an upper bound closes for good" was false**, and the repair went further
   than the sentence: the gate has no kill branch at all. Only the witness branch transfers, because
   the unresolved sources can hide leverage but cannot manufacture it.
5. **K2 was not operational** -- "several kelvin", "exactly the cases", "cannot matter" were
   undefined. It is replaced by the window test, which is defined per case.
6. **The error composition was wrong twice** -- boundary realisation was quoted at 0.345 K (the
   smallest of six values, 0.345-1.124 K) and assumed nested inside the model-form envelope, when
   paired point by point it equals or exceeds that envelope on four of six. The term may not be
   decomposed at all; see the boundaries section.

## Status

**REGISTERED, NOT RUN.** Every figure quoted is a citation to committed work; none was produced by
this gate. The run requires a pinned revision and an isolated worktree: `HEAD` moved five times
during the scoping of this document, and the cell-endpoint run it depends on is itself recorded as
not having bound its starting SHA.
