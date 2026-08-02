# Which mechanism, ranked by the kelvin it moves

DESIGN REVIEW 2026-08-02. NON-CLAIM. Every figure is measured and cited; none is estimated.
This exists because three review rounds verified and corrected the mechanism without anyone asking
whether it is the right mechanism.

## One budget, every lever on it

The thermal budget is **11.85 K** (330 K limit minus 318.15 K ambient, constant across all 2 580
rows of all twelve operators). Every design lever this project could pull, measured:

| lever | moves | share of budget | source |
| --- | ---: | ---: | --- |
| recover a guessed **5 K** guard band | 3.31 – 4.53 K | 28 – 38 % | plan arithmetic on the measured band |
| recover a guessed **3 K** guard band | 1.31 – 2.53 K | 11 – 21 % | same |
| optimise the **schedule** within a fixed band | 0.468 – 1.374 K | 4 – 12 % | plan kill condition (a) |
| tighten the **cross-solver band** itself | 0.2997 – 1.4332 K | 3 – 12 % | `PACKAGE_SWEEP_RESULT.md` |
| **lazy row generation** | **0 K** | 0 % | speed only; ≤ 6.4 % of a 30 s cost |

And against all of them, one defect:

| defect | costs | source |
| --- | ---: | --- |
| the trace omits ~half the dissipated heat | **8.86 K** on the tightest point | `MISSING_ENERGY_SENSITIVITY.md` |

**The input being wrong moves more kelvin than every algorithmic lever combined.**

## What the ranking forces

1. **The first deliverable is a corrected trace, not a mechanism.** Any mechanism validated on the
   present inputs is validated against headroom that does not exist. This is Tier 2 — placing DRAM
   and NoP power changes frozen thermal inputs and invalidates committed results — so it needs the
   owner's authorisation, and that authorisation is now the project's critical path.
2. **Among algorithmic levers the guard band beats the schedule by ~2.7x at the median.** The
   original framing put the contribution on scheduling and treated the band as an input. The
   measurement reverses that.
3. **Lazy generation is not a lever.** One factorisation costs 439–939 triangular solves, so the
   theoretical best case saves 3.5–6.4 % of 30 s. Its stated motivation is refuted, and the
   remaining honest one — MILP constraint count — is a different and much weaker claim.

## The mechanism this implies: a certified constraint SET, not a solver

**Do not build a scheduler.** ThermoDSE already has SCBO, SA and PPO searches. Because the whole
operator costs 30 s and every row is exact, the defensible artifact is a **small set of linear rows
`R_j p <= b_j` with a content receipt**, which any of those searches — or a MILP — consumes as a
constraint, with replay as the arbiter.

**Why this is better than CertiTherm-Opt, from the numbers:**

* it does **not** require `EXACT_MAPPING_TO_POWER_MILP`. The rows are statements about a power
  vector, not about how a search produced it, so the hyperedge and state behaviour that blocks an
  exact MILP model of the evaluator never has to be reproduced;
* it does not invent a scheduler, so it cannot lose to the incumbent on search quality;
* it composes directly with the guard-band result, which is where the measured value is:
  **1.3 – 4.5 K recovered against a 0.47 – 1.69 K cost**;
* lazy generation becomes unnecessary rather than unmotivated — with the full operator affordable,
  rows are precomputed.

**Where it is weak, stated before review rather than after.** "Valid for whatever power the search
produces" is only true if the search's power map and the certificate's power map are the same
object. Today they are not: the search ranks by `optimization_energy` (compute excluded, audit §2)
while the trace carries a different, lossy quantity. **That is the same trace defect as item 1**, and
it is the reason this framing does not escape the critical path either.

## Status

`CERTITHERM_OPT_KILL_CONDITION` — superseded rather than cleared. The mechanism it names is not the
one the numbers support. The kill condition that replaces it is sharper and cheaper to test:
**does a certified constraint set, consumed by ThermoDSE's existing search on a corrected trace,
reach operating points a guessed guard band rejects?** That is one number, it does not need a new
solver, and it is the number the plan has called the whole paper since it was written.

---

# Round-4 review outcome: the constraint set is infrastructure, not yet a mechanism

Peer review 2026-08-02 at `9d4d459`. **Verdict: abandon CertiTherm-Opt** — which this document
already concluded — **but the compiled constraint set is not a research mechanism either.** Three
findings accepted, and two mechanisms proposed that were not on my list.

## Accepted: "valid for whatever power the search produces" is only ALGEBRAICALLY true

`Rp <= b` is valid when `p` has exactly the source semantics, units, block ordering, geometry,
package boundary and endpoint used to build `R` and `b`. It is **not** valid for "whatever this
mapping really dissipates". The search produces `p_hat = F_defective(x)` while the physical object is
`p_phys = p_hat + q_DRAM + q_NoP + q_NoC-correction`. **A content receipt makes the wrong object
reproducible; it does not make it correct.**

The sharpening I did not have: **replaying the same defective `p` through `grid512` or FEM is not an
independent arbiter of power semantics.** It tests the thermal operator *given* `p`, never whether
`p` is the heat the mapping generates. So replay-as-arbiter does not rescue this framing.

Also accepted: the searches do not consume rows in one sense — a MILP needs a valid mapping-to-power
formulation, SCBO can take a black-box scalar constraint, and SA/PPO need rejection, penalties or
repair, **none of which guarantees feasibility during search**. And NoC being both non-conservative
and spatially flattened means the *mapping dependence* of `p_hat` is defective, not just its total.

The artifact is therefore a **fixed-geometry thermal feasibility kernel**, not a universally valid
constraint set, and it needs a receipt binding corrected energy accounting, source placement,
geometry, operator, endpoint and error budget.

## Accepted, and it weakens this document's own headline: guard-band recovery is a WINDOW, not a result

Four independent objections, all correct:

* **3–5 K is unsourced.** This repository states so itself. A computed number cannot beat an
  unsourced comparator.
* **Recovered kelvin is not recovered objective.** Schedule-reachable movement is 0.468–1.374 K; if
  no legal candidate lies in the acceptance window, usable recovery is **zero**.
* **The 0.47–1.69 K covers thermal-model disagreement only** — not trace error, source placement,
  endpoint mismatch, transient error or uncertainty-set misspecification. A crude 3–5 K engineering
  guard may implicitly cover several of those.
* It is cross-solver disagreement, **not a certified distance to physical truth**.

So the publishable form is not "we recover 1.3–4.5 K" but: *a **sourced** baseline rejects mapping
`x`; the complete computed budget accepts it; an independently constructed trace and replay confirm
it; and `x` improves the objective by Y %.* **Until that separator exists, guard-band recovery is a
hypothesis and a window width.** The ranking table above stands as a ranking of *levers*; it must not
be read as a claim that the top lever has been realised.

## Two mechanisms I had not considered, taken from the review

**Rank 1 — legal mapping-space thermal repair with exact separation.** Let an existing SA/SCBO/PPO
search propose a legal mapping `x`; evaluate its corrected conserved power; find the most violated
row; **repair using only legal mapping moves priced by that row's coefficients**; repeat.

The insight I lacked: this is *not* projecting `p` onto `Rp <= b`. **Naive power-space projection
returns a vector no schedule can realise.** Repair stays inside the legal mapping space, so its
output is always a real design. Online thermal cost is ~439–939 rows x 181 variables, i.e. 0.08–0.17
M multiply-adds per candidate — the dominant online cost is ThermoDSE re-evaluation, not thermal
work. No global optimality proof, but the final candidate carries a replayable certificate, and
**it produces a repaired better feasible mapping, which a refusal-only certificate never can.**

**Rank 2 — robust decomposition into controllable plus nuisance heat.** Write
`p = p_map(x) + q`, `q in Q_{DRAM,NoP,NoC}`, and compile robust rows
`r_j p_map(x) <= b_j - h_Q(r_j)` with `h_Q(r) = sup_{q in Q} r q`. This **stops pretending the mapper
controls DRAM and NoP placement** and avoids assuming one distribution — which is exactly the
weakness of the proportional placement in `MISSING_ENERGY_SENSITIVITY.md`. The support function is
the polytope machinery this project already has.

Its danger is already measured here: unrestricted adversarial placement gives 37.8–208.5 K, so a weak
`Q` makes every row useless. **It lives or dies on defensible regional source bounds; if those cannot
be measured, stop rather than tune them.**

Explicitly deprioritised by the review, and I agree: reduced bases and learned certified surrogates.
The exact operator costs 30 s and is reused indefinitely; approximating something already cheap and
linear only buys residual-bound and abstention machinery.

## The blunt answer to "is anything defensible before the trace is fixed"

**No physical-feasibility, absolute-temperature, safe-mapping, recovered-budget or
thermal-optimisation claim is defensible.** What survives, worded conditionally: the steady linearity
and operator-reuse mathematics; measured construction costs; cross-solver disagreement *for the
declared inputs*; the fact that the trace omits enough energy to invalidate downstream verdicts;
row-evaluation soundness *given a correctly defined `p`*; and explicitly labelled sensitivities under
assumed nuisance placements — **including `MISSING_ENERGY_SENSITIVITY.md` itself, which is a
non-claim sensitivity under an assumed placement and not a corrected verdict.**

**The next thermal result must start after the trace correction, not merely list it as a limitation.**
