# A severe measured convergence bottleneck in greedy constraint generation

> **Retitled and substantially corrected 2026-07-29 after adversarial peer review.** This
> document previously claimed the certified interval was limited BY THE FORMULATION and could
> not be improved AT ANY BUDGET. That claim is withdrawn. The reviewer was asked to refute it
> and did, on several independent grounds recorded in "What the review overturned" below. What
> survives is a measured practical bottleneck on one instance, which is a weaker and different
> statement.

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

## Measured: the bound grows logarithmically in the cut count

"Converges arbitrarily slowly" was an adjective resting on two points. `bound_growth_probe.py`
accumulates cuts exactly as the loop does and evaluates the EXACT hitting-set optimum over the
cuts held so far, at geometric checkpoints:

| cuts held | exact hitting-set optimum | actions in it | fit | residual | master solve |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 125 | 9.0 | 2 | 9.8 | -0.8 | 0.0 s |
| 250 | 16.0 | 2 | 14.4 | +1.6 | 0.7 s |
| 500 | 18.0 | 3 | 19.1 | -1.1 | 2.8 s |
| 1 000 | 24.0 | 3 | 23.8 | +0.2 | 13.1 s |
| 2 000 | 29.0 | 5 | 28.5 | +0.5 | 25.2 s |
| 4 000 | 32.0 | 4 | 32.8 | -0.8 | 72.7 s |

Least squares over these six points from one trajectory, spanning a 32x range in cut count:

    L(n) = -21.94 + 4.57 * log2(n)       R^2 = 0.985, every residual within 1.5

An independent run reached 3 619 cuts and measured 32.0 against a predicted 32.5, so the fit
holds across runs as well as across the range.

Doubling the number of discovered cuts buys about **4.7** of certified lower bound. The
certified upper bound for this candidate is about 1450. Extrapolating:

| target | cuts the fit projects |
| --- | ---: |
| 1370 (the `dual` baseline's cost, per candidate) | ~2^305 ~ 10^92 |
| 1450 (this candidate's certified U) | ~2^322 ~ 10^97 |

(These were printed as 2^298 and 2^315 before review, carried over from an earlier fit and
never recomputed when the coefficients changed. The reviewer caught the inconsistency.)

**And the projection refutes itself.** The library has 243 actions, so there are 2^243 ~
1.4 x 10^73 possible selections in total, and Theorem 3's finite-termination argument is that
each new collision prevents the queried selection from recurring. A projection needing 10^97
cuts therefore exceeds the entire selection space by twenty-four orders of magnitude. The
fitted logarithm **cannot** hold to 1450. Since the true optimum is above 32, a rise steeper
than the fit is not merely possible somewhere in the tail -- it is mathematically necessary.

For scale, the observable universe holds on the order of 10^80 atoms. The master solve time
also grows superlinearly -- 0.0, 0.7, 2.8, 13.1, 25.2, 72.7 seconds -- and past 4 000 cuts it
stops finishing at all.

### The second wall: past ~4 000 cuts the bound cannot even be computed

The same run continued to 22 583 cuts. At 8 000 and at 16 000 the exact master hit the
300 s HiGHS limit and returned no bound:

| cuts held | exact hitting-set optimum | weak-duality bound |
| ---: | ---: | ---: |
| 4 000 | **32.0** | 18.1 |
| 8 000 | timeout | 20.3 |
| 16 000 | timeout | 21.6 |

So beyond about four thousand cuts the only bound that still finishes is weak duality, and at
sixteen thousand cuts it reads 21.6 -- lower than the 32.0 the exact master returned at four
thousand.

An earlier version of this section said that "accumulating more evidence makes the reportable
bound worse". **That was wrong**, and review caught it: `_refresh_bound` keeps the maximum
bound seen and never lowers it, so a weaker later evaluation does not retract the 32.0. What
is true is narrower -- past about four thousand cuts, further accumulation stops CONTRIBUTING
to the bound in this configuration, because the evaluation that could use it no longer
finishes within 300 s.

That is a practical wall for this solver at this size, not a proof about the formulation.

This is what makes the conclusion structural rather than a matter of budget. No separation
speed-up, no master frequency, no amount of compute, and no spatial pruning of reject cells
changes a logarithm into what would be needed.

### Measured: the standard cutting-plane trajectory is WORSE, not better

The strongest objection to everything above is that all of it drives separation from
`_greedy_cover`, which always buys the cheapest covering action. The selection therefore
stays cheap and every witness is one more thing a cheap plan fails to distinguish. If the
logarithm came from that, this result would be about the implementation's search strategy and
not about the formulation.

The textbook alternative is to separate the MASTER's optimum -- the cheapest plan consistent
with all evidence so far, so a witness against it is violated by the current optimum by
construction. That is the usual reason branch-and-cut converges where greedy enumeration does
not, and `synthesize_minimum_observation` never does it during ordinary iterations.

Both trajectories, same instance, exact hitting-set optimum at the same cut counts:

| cuts | greedy-driven bound | master-driven bound | greedy cover cost | master cover cost |
| ---: | ---: | ---: | ---: | ---: |
| 125 | **9.0** | 8.0 | 23 | 8 |
| 250 | **16.0** | 11.0 | 37 | 11 |
| 500 | **18.0** | 13.0 | 31 | 13 |
| 1 000 | **24.0** | 15.0 | 42 | 15 |

The master-driven trajectory is worse at every checkpoint and the margin widens -- 1.13x,
1.45x, 1.38x, 1.60x. The cover-cost columns say why. The
master returns the CHEAPEST cover consistent with the evidence, so it stays at 8, 11, 13;
separating a cheap plan yields witnesses that are cheap to fix. Greedy's cover is more
expensive, so its witnesses are correspondingly more informative.

The objection is therefore refuted by measurement rather than argued away, and the negative
result survives its strongest available attack.

### Measured: cut selection does not change it either

The curve above is measured along the trajectory the loop follows, and the collision LP has a
zero objective, so its witness is arbitrary among the feasible ones. Whether the logarithm
belonged to the CUTS or to that ARBITRARY ORDER was the last opening inside this formulation.

`cut_selection_probe.py` settles it. After warming up 200 cuts along the production
trajectory, one exhaustive batch yields 677 usable candidate cuts from the same selection, so
the separation cost is identical across rules and only the choice differs. Exact hitting-set
optimum over each prefix:

| cuts kept | arbitrary (spec order) | max cheapest-separator cost | narrowest | least redundant |
| ---: | ---: | ---: | ---: | ---: |
| 25 | 8.0 | 8.0 | 8.0 | 8.0 |
| 50 | 8.0 | 8.0 | 8.0 | 8.0 |
| 100 | 8.0 | 8.0 | 8.0 | 8.0 |
| 200 | **16.0** | 12.0 | 8.0 | 8.0 |
| 400 | **16.0** | 16.0 | 12.0 | 12.0 |

Arbitrary spec order is the BEST of the four. Every heuristic designed to pick more
informative cuts performed the same or worse.

The reason is instructive rather than disappointing. Selecting by cheapest-separator cost or
by narrowness picks cuts that name the same few expensive or rare actions, so they are highly
correlated and the antichain and master see little new. Deterministic spec order sweeps
across the floorplan, which is already a diversity heuristic -- and on a problem whose
structure is spatial, diversity is what a cut set needs.

So the logarithm is a property of the cuts, not of the order. Within this formulation there
is no cut-selection policy left to try that would plausibly change the exponent; three of the
obvious ones were tried and all lost to doing nothing.

## What the review overturned

The document was written to be refuted and was. Each item below is the reviewer's, verified
against the code or arithmetic before being accepted.

1. **"At any computational budget" is not established and contradicts this project's own
   theorem.** Theorem 3 says the formulation terminates with the true finite-library optimum
   or `UNSYNTHESIZABLE` under exact master and oracle assumptions. An impossibility claim
   needs an analytic lower bound on convergence, not a longer timeout. No finite curve can
   prove it.
2. **The extrapolation is not evidence of a ceiling.** Six correlated points over 125-4 000
   cuts support a description on that interval, not an asymptotic law forty doublings away.
   The 3 619-cut replicate lies INSIDE the fitted range, so it is interpolation, not
   validation of the tail. And the projection exceeds the 2^243 selection space, so the law
   must break -- a knee is necessary, not merely possible.
3. **The arithmetic was internally inconsistent**, as recorded above.
4. **The "bound gets worse" claim was false**: the caller keeps the maximum.
5. **The master values are HiGHS-reported optima with self-checks, not independently certified
   ones.** `_solve_master` requests a zero relative gap, rejects an unsuccessful MILP, and
   verifies coverage, objective and dual bound; a native time limit becomes `TimeoutError`
   rather than a partial answer. But the probes record neither `bound_provenance` nor solver
   status, so which checkpoints were weak-duality-certified and which were solver-attested is
   not recoverable from the output. "HiGHS-reported exact restricted-master optimum" is
   accurate; "independently certified" is not.
6. **The cut-selection comparison has an experimental defect.** Each evaluated master is built
   from the batch prefix ALONE, not from `warm-up cuts + prefix`, and the least-redundant
   score measures redundancy only within the batch. Prefixes also survive domination at
   different rates, so equal "cuts processed" is not equal evidence. The comparison is
   therefore weaker than presented -- it shows three scalar per-cut rankings did not beat spec
   order on one fixed batch at one selection, not that selection cannot matter.
7. **A materially different policy was not tried.** All three heuristics score cuts
   individually. A joint bundle selection -- choose the set of k cuts maximising the resulting
   master optimum, rather than ranking cuts one at a time -- is a different object, and an
   adaptive version feeding each round's master solution back through separation could behave
   differently again.

One item the reviewer raised was already measured, from a file added after the review was
sent: `master_driven_growth_probe.py` implements exactly the branch-and-cut trajectory item 1
asks for -- solve the restricted master, separate ITS optimum, repeat -- and it is WORSE than
greedy at every checkpoint (8.0/11.0/13.0/15.0 against 9.0/16.0/18.0/24.0). That does not
rescue the ceiling claim, but it does answer the specific "you never tested branch-and-cut"
objection.

## What is and is not established

Established, on one candidate of one development instance:

  * along a greedy-driven trajectory the exact restricted-master value rose 9 -> 32 over
    125 -> 4 000 active cuts, well described by a logarithm on that interval;
  * this HiGHS configuration did not finish 8 000- and 16 000-cut masters in 300 s;
  * three per-cut rankings on one fixed batch did not beat deterministic spec order;
  * separating the master's optimum instead of the greedy cover was worse at four checkpoints;
  * lazy and exhaustive harvesting both remained unresolved after 900 s each, with lazy
    reaching roughly twice the bound -- a finite-budget policy effect, not policy irrelevance.

NOT established: an asymptotic rate; any analytic bound on cuts or time; that 32 is the best
obtainable bound; that the true optimum is near 1450; impossibility at arbitrary budget; or
anything beyond this candidate.

The defensible verdict is the reviewer's: **greedy constraint generation exhibits a severe,
measured practical convergence bottleneck on this instance. The evidence does not show a
formulation-level ceiling.**

## What would settle it

  * Exact restricted-master values well beyond 4 000 cuts by an incremental or
    proof-producing MIP route, with log, piecewise-log and staircase models preregistered and
    the tail checkpoints held out.
  * `bound_provenance` and solver status recorded at every checkpoint, and each optimum
    reproduced by a second exact solver.
  * The cut-selection comparison rerun over `warm-up + prefix` with equal surviving
    antichains, and each policy's master solution fed back through separation for several
    rounds.
  * Joint bundle selection, as the materially different fourth policy.

## Consequence for what would count as an improvement

On this instance, the certified interval was not closed by:

  * a better harvesting policy (measured: 440x more iterations, bound roughly doubles, still
    open);
  * solving the exact master more often (measured: 1.8x, still far short);
  * separating the master's optimum rather than the greedy cover (measured: worse).

Closing it needs a lower bound that does not come from covering *enumerated* pairs -- an
argument over the continuous world set or the observation subspace directly, rather than over
a sampled subset of its confusable pairs. That is a change of method, not of implementation.

Two shapes such an argument could take, neither implemented:

  * **Semi-infinite dual.** Identifiability is `D_{m,r} ∩ {δ : |M_S δ| ≤ η} = ∅` for every
    reject cell, where `D_{m,r}` is the polyhedral set of differences between a SAFE and a
    REJECT power map. The present cut relaxes that to "separate this one δ". A bound taken
    over measures on `D_{m,r}` rather than over sampled points of it does not enumerate.
  * **Dimension.** If `D_{m,r}` contains a ball of radius r in some subspace, any `S` whose
    kernel meets that ball fails. That yields a lower bound on how many independent
    directions `S` must observe, and hence on cost, without discovering a single pair.

Both are stated here as directions, not results. What the measurements establish is only
that the enumerative route is closed.

This is consistent with the two other measured negatives recorded in
`docs/COARSE_INSTRUMENTATION_OBSERVATIONS.md`: the upper bound cannot be lowered much either,
because per-block resolution is forced by the physics. Both ends of the interval are
structural.

## Scope

One candidate (`transformer` / `default` / `arch_b`), dev split, 300 s of accumulation and a
600 s master budget. The A/B is one candidate at 900 s per policy. The six-query interval
figures are from the committed `artifacts/dev/results.tsv`. Nothing here is claim-grade and
nothing here changes a frozen contract; `separation_policy` defaults to the frozen behaviour.
