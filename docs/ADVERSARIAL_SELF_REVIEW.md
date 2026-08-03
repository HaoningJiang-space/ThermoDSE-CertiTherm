# Adversarial self-review: every attack I can find on this round, and its status

REVIEW 2026-08-04. Written against my own results, before external review (Codex quota-locked to
2026-08-08). Each item is an attack a reviewer can make, with either the measurement that settles it,
the experiment that would, or an explicit concession. **Concessions come first inside each group.**

## A. Attacks on the headline — "the incumbent's design fails its own envelope"

**A1. "You used the wrong limit; 330 K has no provenance."** **CONCEDED and unresolved.**
`CertiTherm/frozen_limits.py` states the limit and gives no source; ThermoDSE's own 348 K is
documented as unsupported. Every verdict is relative to a declared number. *Mitigation in place:* the
`dist` and `radius` columns are reported for every design, so a reader with a different limit can
re-derive every verdict. *What would settle it:* a citation, or restating the claim as
limit-parametric throughout. **Owed.**

**A2. "You used the wrong cap — re-run their search at 330 K."** **SETTLED**
(`THE_NOMINAL_RULE_ADMITS_WHAT_THE_ENVELOPE_REFUTES.md`). At 330 K their rule still admits 10 of 12
candidates and still picks `mtxu_h=128`, whose nominal peak is `329.973 ≤ 330` and whose supremum is
`331.558`. Seven of the ten admitted designs are refuted by the envelope. The comparison is exact —
both feasible sets are functions of numbers already measured — so it needs no optimiser and carries no
sampling noise.

**A3. "Your envelope span 0.30 is a knob you chose."** **SETTLED**
(`THE_ENVELOPE_WIDTH_IS_NOT_WHERE_THE_DISAGREEMENT_COMES_FROM.md`). Swept over seven widths: the two
rules disagree at **every** one, including `s = 0.05`, where the incumbent's own optimum already
reads `330.213` against a `329.94` ceiling. The span sets how many designs the disagreement catches
(`|F_envelope|` falls 9 → 6 → 4 → 3 → 1 → 0), not whether it exists, and the price rises monotonically
from `+1.6 %` to `+14.1 %` so a reader reads their own declaration off the curve. **Against the
method:** at `s ≥ 0.75` nothing certifies at all, so the envelope is a real declaration with
consequences rather than a free strengthening. Library hit rate on this run: **12/12**.

**A4. "No model-form band is folded in."** **MEASURED** (`E_TOTAL_AT_THE_CELL_ENDPOINT.md`), and it
splits into two answers that point opposite ways. The row-wise band at the cell endpoint is
**1.98-4.99 K**, eight to twenty times the block-row band that was standing in for it — so the
substitution was wrong by an order of magnitude in the permissive direction, and **G2's separator
window is empty for any `g <= 5 K`**, which kills that framing at the endpoint without needing any
candidate set. But the difference in the quantity a verdict actually reads is **≤ 0.071 K**, with the
FEM *cooler* on two of three cases: the cells the models disagree about are not the hot ones. The
sound a priori bound is therefore loose by a factor of **70**, and tightening it to the rows that can
attain the maximum is the named next step. **`Δ` is a measurement on three designs and must never be
used as a bound for one not measured.**

**A5. "n is small."** 6 development points, 61 archive designs × 2 workloads, 2 search seeds at the
time of writing. *In flight:* four more search seeds. **Still one package and one grid resolution.**

**A6. "One package."** All results at `default`. `experiments/packages.tsv` has `standard` and
`enhanced` and operators exist for both. *Experiment:* repeat the head-to-head at all three.
**Owed.**

## B. Attacks on the instrument

**B1. "A max of cell averages is not the pointwise peak the limit refers to."** **CONCEDED,
structurally open.** `H¹(Ω)` does not embed in `L^∞` in three dimensions, so no grid refinement
closes it, and the residual-majorant route is closed at `1.0012` after equilibration
(`GB1_THE_NAIVE_MAJORANT_IS_VACUOUS.md`). The remaining route is a comparison-principle
supersolution, which is one-sided and matches what a fail-closed certificate needs. **Not done.**

**B2. "`gridN-avg` breaks thermal reciprocity, so your `R` is not symmetric."** **ALREADY MEASURED,
and I listed it as owed — which is this project's own rule violated: grep for the ANSWER, not for a
script.** `CertiTherm/reciprocity.py`'s docstring already reports the experiment I was about to
design. Symmetrising the operator moves the certifying quantity `max_j sup_p T_j(p)` by
**+0.0142 to +0.0711 K** at `grid128-avg`, two orders of magnitude below a first estimate that
multiplied the relative asymmetry by the operator scale — that estimate is recorded there as
withdrawn. The asymmetry is entrywise while the certificate is a max over rows of a weighted sum, so
the asymmetric parts align with neither the argmax row nor the extremal power vector and largely
cancel.

**And at the cell endpoint the objection largely dissolves, for a reason worth stating.** The
asymmetry arises because assigning grid cells to blocks by membership is not the adjoint-consistent
`L²` projection. At the cell endpoint there is no such assignment on the output side: `R` is
`16 384 × 233`, not square, so Maxwell–Betti symmetry is not even a defined property of it. What
survives is the **input** side — a block's power spread over the cells it covers — and that is the
same non-adjoint mapping. *So the residue is real but smaller than the ≤0.07 K already measured, and
the honest statement is that it is bounded by it rather than equal to it.* **Not owed; stated.**

**B3. "Your routed lowering has its own free parameters."** **CONCEDED, named, unmeasured.**
`io_die_aspect_ratio` is labelled *"a sensitivity parameter, not a discovered fact"* at
`routed_trace.py:117`; the same-chiplet NoC split is a fixed 50/50; routing is X-then-Y rather than
ThermoDSE's own. Two of the three are matvecs on operators already built. **Owed, and it is
`ROUND_PLAN_FIXED_GEOMETRY` Step 1, still not done.**

**B4. "You dropped 3 of 64 designs."** **SETTLED as a substantive refusal, not a tolerance artefact.**
`arxv002`, `arxv051`, `arxv054` fail on **both** workloads, so it is a property of the design. The
refusal message now names the magnitude: on `arxv002`, **206 of 309 orders disagree, worst relative
`6.30e-01`** between the physical route ledger and ThermoDSE's monitor. That is a 63 % disagreement,
not rounding. What it means about `physical_nop`'s routing on those topologies is **not established**
and is the honest residue: the designs are excluded and counted, never given a fabricated trace.

**B5. "Your EDYP does not match the archive's."** **KNOWN and deliberately not mixed.** The ratio of
`E·D/Y` to the archive's stored EDYP over the declared designs is **0.0172-0.0204 and not constant**,
so it aggregates something this run does not — most likely the search's full workload suite. Both
sides of every comparison are recomputed from this run's own outputs. *What is owed:* identifying
what the archive's number is, so the paper can say rather than avoid.

## C. Attacks on the search

**C1. "Coordinate descent from one seed is a weak search."** **CONCEDED, and it is the right
concession.** The contribution is the **constraint**, not the search: `F_envelope ⊆ F_nominal` on
every candidate measured, so the certificate can only cost EDYP relative to the nominal rule, never
gain. A stronger search improves *our* number, not the finding. **A better search is nonetheless the
next piece of work.**

**C2. "The baseline was under-tuned."** Answered by A2 — the incumbent's *rule* selects the same
design at the corrected cap.

**C3. "You searched a neighbourhood you chose."** The per-field value sets come from the archive
ThermoDSE itself produced, so the search cannot leave the space its own search explored. A reviewer
can still object that coordinate moves reach a different subset than SCBO's trust region. **Owed:**
run the comparison over the archive designs directly, which is a population rather than a
neighbourhood.

## D. Attacks on the process

**D1. "No external review."** **CONCEDED.** Codex has been quota-locked since before these results;
every document carries the disclaimer. The whole round goes to review on 2026-08-08.

**D2. "G0 provenance."** **PARTLY OWED.** Runs record the SHA, the pinned binary digest and the
interpreter in their documents, and the operator library is content-addressed, but no per-run digest
manifest is written beside the artifacts.

**D3. "Three claims were withdrawn mid-round."** True, and each is recorded with the premise that
failed: a `Q` scaled from one architecture, a geometry-invariance generalised from one base design,
and a "conservative" construction that was not conservative. All three were caught by my own
measurements, each costing minutes. **The pattern is the finding**: in this project every assumption
that was declared but not measured has eventually been wrong, in the direction that flattered the
method.

## The three that would most change the paper

1. **A4** — `e_total` at the cell endpoint. It can move two of six certifications to `UNRESOLVED`.
2. **A6/A3** — one package and one envelope span. Both are repeats on existing operators.
3. **B3** — the routed lowering's own freedom, promoted here from second place because **B2 turned
   out to be already answered at ≤0.07 K**. Two of its three parameters are matvecs on operators
   already built, so the cost of settling it is minutes and the cost of not settling it is that every
   verdict rests on an unmeasured input.
