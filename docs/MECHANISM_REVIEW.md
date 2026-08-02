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
