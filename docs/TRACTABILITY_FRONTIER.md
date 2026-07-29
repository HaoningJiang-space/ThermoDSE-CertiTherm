# Where exact synthesis works, and what it says about the certified gap

MEASURED 2026-07-29, dev split, one candidate. NON-CLAIM.

Every DSOS run recorded in this project is UNRESOLVED. The dev candidates are all 227-237
blocks, so "how large an instance can this method prove optimal" had no answer, and a method
that never returns OPTIMAL is characterised by where it stops working rather than by its
bounds. These are the first OPTIMAL results in the project's records.

## Construction

Well-formed DSOS instances of increasing size, built from the same committed operator
(`arch_b` / `default` / `transformer`) by restricting to the first k blocks: the response
submatrix, the power polytope on those blocks, and the actions whose support lies entirely
inside them. An action whose support crosses the boundary is dropped rather than truncated --
a truncated action measures something the restricted instance does not contain, which is a
different observation and not a smaller one.

**The thermal limit is rescaled**, to the midpoint of the achievable peak range. It has to be:
the first run inherited the full instance's limit, no admissible power map on 8 blocks reached
it, the REJECT cell was empty, and synthesis returned OPTIMAL at cost 0 after one iteration.
That is not a tractability result; it is a vacuous one, and it was measured before being
noticed.

So these are real instances of the algorithm's problem, not restrictions of the chip's
physics. The 16-block case is not a 16-block chip.

## Measured

| blocks | actions | rescaled limit (K) | status | exact cost | cost / block | iterations | seconds |
| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 8 | 9 | 332.45 | OPTIMAL | 24 | 3.00 | 10 | 0.2 |
| 12 | 13 | 359.47 | OPTIMAL | 56 | 4.67 | 40 | 1.2 |
| 16 | 17 | 361.39 | OPTIMAL | 64 | 4.00 | 50 | 2.1 |
| 20 | 21 | 363.59 | OPTIMAL | 88 | 4.40 | 49 | 2.8 |
| 24 | 25 | 369.12 | OPTIMAL | 128 | 5.33 | 165 | 16.9 |
| 32 | 33 | 372.07 | OPTIMAL | 168 | 5.25 | 218 | 35.7 |
| 40 | 41 | 376.24 | OPTIMAL | 208 | 5.20 | 852 | 273.4 |

Every one returns OPTIMAL with `lower_bound == exact_cost`, so each is a proof and not a
bound. The method works; the full instance is simply out of its reach.

## Two trends, pointing opposite ways

**Time explodes.** 32 to 40 blocks is a 1.25x increase in size and a **7.7x** increase in
time. Extrapolating that rate to 227 blocks puts the full instance far beyond any budget,
which is consistent with every recorded run being UNRESOLVED and is the same wall the
convergence document measures from inside.

**Cost per block settles.** From 24 blocks on it is 5.33, 5.25, 5.20 -- flat. A linear fit
over those points gives

    cost = 8.0 + 5.00 * blocks

and extrapolating to the real 227 blocks gives **1143**, against the candidate's certified
upper bound of about **1450** -- a ratio of **1.27**.

## What that would mean, if the extrapolation holds

The certified interval on this candidate is 32 to 1450, a factor of 45. If the true optimum
is near 1143, then almost all of that gap is inability to PROVE rather than genuine
suboptimality: the plan the method already produces would be within about 27% of optimal, and
the 45x interval would be an artifact of the proving machinery.

That is consistent with the three independent measurements in
`COARSE_INSTRUMENTATION_OBSERVATIONS.md` and `PER_CELL_DECOMPOSITION_BOUND.md`: the thermal
kernel is delocalised (90% of a block's temperature comes from ~190 of 227 blocks), the peak
functional does not compress spectrally (20.7 K worst-case error at 98.3% retained energy),
and a single cell's cover exhausts every coarse read and still needs dozens of per-block
extractions. All four point the same way -- per-block resolution is forced, and the existing
plan is close to what is required.

## What it does not establish

The restricted instances differ from the real one in three ways that all matter:

  * the limit is rescaled, so the decision being certified is not the registered 330 K one;
  * the action library is n+1 actions against the real 243, so the combinatorial structure is
    far simpler and the coarse hierarchy is largely absent;
  * the extrapolation spans 5.7x beyond the largest measured point, and this project already
    had to withdraw one extrapolation after review -- a fitted trend over seven points is a
    description, not a law.

So 1143 is an estimate of what the method would prove if it could, not a bound on the real
instance. It cannot be used to claim the existing plan is near-optimal; it can be used to
decide that establishing so is worth attempting, which is what a diagnostic is for.

## Scope

One candidate, one package, one workload, dev split, seven sizes, 600 s per size. Nothing
here is claim-grade and nothing changes a frozen contract. Produced by
`research/triangle/tractability_frontier_probe.py`, which calls the unmodified
`synthesize_minimum_observation`.
