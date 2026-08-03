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

**A3. "Your envelope span 0.30 is a knob you chose."** **PARTLY SETTLED.** The robustness radius
reports the whole curve rather than a verdict at one span, and monotone nesting is checked at run
time. But the *search* and the feasible-set comparison were run at a single span. *Experiment:*
repeat both across spans — each certificate is 12 ms, so it is post-processing. **Owed.**

**A4. "No model-form band is folded in."** **CONCEDED, and it is the single number most likely to
overturn the round.** Folding in the measured 0.25-1.43 K band moves the found design's `+0.328 K`
slack into `UNRESOLVED`. *In flight:* `CERTITHERM_FEM_CELL_ENDPOINT=128` gives the FEM reference a
cell-granular readout so the band can be measured **at the endpoint the certificate uses**, which no
prior measurement did — every band so far is at block rows, and the cell endpoint sits 0.58-0.87 K
above the block projection.

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

**B2. "`gridN-avg` breaks thermal reciprocity, so your `R` is not symmetric."** **KNOWN, quantified
by `CertiTherm/reciprocity.py`, not folded in.** Maxwell–Betti says a physical `R` is symmetric;
HotSpot's block-average grid mapping is not. *Experiment:* report the certified peak computed from
`R` and from `(R + Rᵀ)/2` and bound the difference. **Owed.**

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
2. **B3** — the routed lowering's own freedom. It is the input every verdict now rests on.
3. **B2** — reciprocity. If `R`'s asymmetry is comparable to the margins, the certified quantity is
   not the physical one.
