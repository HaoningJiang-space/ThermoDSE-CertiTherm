# The certified interval is limited by the formulation, not by the solver or the loop

NON-CLAIM diagnostic evidence, 2026-07-29, dev split, one candidate. Records a measured
negative that changes what an improvement would have to be.

## The symptom

Every dev query certifies `plan_validity = CERTIFIED` with `cost_optimality = BOUNDED_GAP`
and a certified interval spanning 47x to 183x:

| workload / package | certified L | certified U | U/L |
| --- | ---: | ---: | ---: |
| resnet50 / default | 88.3 | 4174 | 47.3 |
| transformer / standard | 22.8 | 4174 | 183.0 |

`exact_status` is UNRESOLVED 6/6, with 0 of 3 required candidates completed inside 1800 s.

## Two hypotheses, both tested, both wrong in the informative way

**Hypothesis 1 -- the loop harvests cuts wastefully.** The main loop called `_collisions`,
one collision per reachable reject cell: up to 681 per iteration on a 3-model 227-block
instance, measured at 623. `separation_policy="lazy"` harvests one instead, with the same
exhaustive scan still used to conclude that none remain, so the termination test is
unchanged. A/B through the production entry point, same candidate, 900 s each:

| policy | iterations | cuts active | certified L | status |
| --- | ---: | ---: | ---: | --- |
| lazy | 9 669 | 9 490 | 20.5 | UNRESOLVED |
| exhaustive | 22 | 10 745 | 10.0 | UNRESOLVED |

Lazy reaches 440x the iterations and roughly doubles the bound. **Neither terminates.** The
harvesting policy is not the bottleneck.

(An earlier probe appeared to certify this candidate with 190 cuts in under 180 s. It used a
monotone cheapest-covering greedy, not the production loop's re-solved cover. Comparing two
different loops and inferring a property of the production one was the error.)

**Hypothesis 2 -- the bound computation wastes the evidence.** `_anytime_lower_bound`
evaluates weak duality from LP dual prices used as a guess: sound by construction, loose by
construction. `_solve_master`, the exact hitting-set optimum over the discovered cuts, is
reached only on the collision-free branch, which a non-terminating loop never reaches.
Evaluating both on the SAME 3 619-cut set:

| quantity | value |
| --- | ---: |
| cuts active | 3 619 |
| weak-duality bound (what the certificate reports) | 17.96 |
| **exact hitting-set optimum over those cuts** | **32.0** |
| actions in that exact cover | **4** |
| greedy cover cost during accumulation | 51.0 |
| certified U for this candidate | ~1450 |

The exact master IS stronger -- 32 against 18, a factor of 1.8. It is also irrelevant: both
are 45x-80x below U.

## What the second measurement actually shows

**Three thousand six hundred and nineteen discovered cuts are hit by four actions costing
32.** The cuts are not being wasted; they are individually weak, and they stay weak as they
accumulate.

That is a property of the formulation. Each cut says "buy at least one of these ~32 actions",
so any discovered subset of the constraint family is cheap to hit. Driving the bound from 32
to 1450 requires discovering enough cuts that the cheap actions are exhausted -- and the
constraint family is continuous (every confusable pair in a polytope), so no attainable
number of cuts does that. Constraint generation over it converges arbitrarily slowly, and no
tuning of the loop or the master changes the exponent.

## Consequence for what would count as an improvement

The certified interval cannot be closed by:

  * a better harvesting policy (measured: 440x more iterations, bound doubles, still open);
  * solving the exact master more often (measured: 1.8x, still 45x short);
  * more compute on the same formulation (the two above are what more compute buys).

Closing it needs a lower bound that does not come from covering *enumerated* pairs -- an
argument over the continuous world set or the observation subspace directly, rather than over
a sampled subset of its confusable pairs. That is a change of method, not of implementation.

This is consistent with the two other measured negatives recorded in
`docs/THERMAL_SIGNOFF_IRREDUCIBILITY.md`: the upper bound cannot be lowered much either,
because per-block resolution is forced by the physics. Both ends of the interval are
structural.

## Scope

One candidate (`transformer` / `default` / `arch_b`), dev split, 300 s of accumulation and a
600 s master budget. The A/B is one candidate at 900 s per policy. The six-query interval
figures are from the committed `artifacts/dev/results.tsv`. Nothing here is claim-grade and
nothing here changes a frozen contract; `separation_policy` defaults to the frozen behaviour.
