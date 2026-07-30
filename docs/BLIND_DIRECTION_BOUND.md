# A certified lower bound from the directions coarse instrumentation cannot see

RESULT 2026-07-30. Method in `CertiTherm/blind_direction_cuts.py`, pinned by
`CertiTherm/tests/test_blind_direction_cuts.py` (17 tests). Driver:
`research/triangle/indistinguishable_pair_bound_probe.py`. Tier-2 peer reviewed before
integration.

## The number

On `arch_a` / `default` / `resnet50` (237 blocks, 251 actions):

| quantity | value |
| --- | --- |
| certified lower bound, this method | **1120.0** |
| certified lower bound, previously reported range | 22.8 – 88.3 |
| certified upper bound on the same instance | 1450 |
| structural ceiling (every within-cell pair confusable) | 1576.0 |
| pairs scanned / established | 1166 / 1029 |
| wall time for the scan | 27 min |

The gap to the upper bound closes from roughly 94% to **23%**.

The last 8.0 came from an edge the scan had missed. Its heuristic looks at the eight (model, point)
cells with the most leverage on each blind direction, and scanning the resulting cover turned up
twenty survivors that looked like two-block zero-sum pairs. Re-proving them through the exact path
admitted ONE. The other nineteen were not blind-direction pairs at all -- see the boundary discussion
below -- which is why the recovery is worth doing and worth doing this way: a survivor is a proposal,
not an edge.

Compose with any other certified bound by `max`, never by addition: both lower-bound the same
selection cost, and the generic cuts can be hit by the very single-block actions this cover
charges for.

## Why it works

An action separates two worlds only through `a . (p1 - p2)`. Two blocks whose coefficient
columns agree in every action observing more than one block are therefore invisible to all of
them along `delta = t (e_b - e_c)`:

    a . delta = t * (a_b - a_c) = 0

Such a collision can only be separated by a single-block action on b or on c. Two consequences,
and they are what make this different in kind from accumulating generic cuts:

* **Vertex cover.** Every certifying selection must instrument b or c for each confusable pair,
  so the instrumented blocks form a vertex cover of that cell's confusability graph. The bound
  is its proven minimum weight, not a quantity that grows logarithmically in cuts discovered.
* **Additivity.** Cells partition the blocks and each cell's cuts name only its own blocks'
  actions, so the per-cell minima ADD. Disjoint supports are exactly what overlapping generic
  cuts lack.

On this instance the 237 blocks fall into 40 cells, four of them holding 21 blocks with 199–209
of the 210 possible edges — near-complete confusability graphs, covered by 18–19 blocks each.

This is NOT the retracted per-cell decomposition
(`docs/PER_CELL_DECOMPOSITION_RETRACTED.md`). Nothing is dropped from the thermal problem: every
witness is validated against the full SAFE conjunction over every (model, point). What
decomposes is the hitting-set supports, not the physics.

## What makes each number trustworthy

Every counted pair is backed by a witness that is **repaired to exact rational polytope
feasibility and re-proved with zero slack**, with its cut recomputed exactly. `validate_witness`
normally tolerates a world up to the feasibility tolerance OUTSIDE the polytope, and peer review
correctly objected that such a world does not prove any selection fails on the original problem —
the thermal margin protects the SAFE/REJECT classification but repairs no domain infeasibility.
A pair whose witness cannot be repaired is dropped.

Only positives are ever used. A pair the scan does not establish is recorded as unestablished,
never as non-confusable, so restricting either the pairs or the reject cells scanned can only
LOWER the reported bound.

The one direction in which this construction could be unsound rather than merely weak is an
overstated cover, and both of its routes are guarded. The cover search runs to proven optimality
or raises `UnresolvedComputation` — an incumbent cover is an UPPER bound on the minimum and must
never be reported as a lower bound. And the additive sum refuses cells that are not pairwise
disjoint or edges filed under a cell that does not contain them, since a shared block would be
charged twice.

The load-bearing property is checked against the oracle rather than argued: on a six-block
fixture that `synthesize_minimum_observation` solves exactly, the bound is **32.0 against a true
optimum of 33.0**.

## The cover is necessary but NOT sufficient, and the reason is not what it looks like

Instrumenting a minimum cover (139 blocks, 1112.0 at the time) plus all fourteen coarse actions --
a plan costing 1138.0 -- does not certify. 432 collisions survive it. Had it certified, the interval
would have closed to about 2%, so this was worth one scan.

The composition of those survivors is the useful part:

| | count | what it means |
| --- | --- | --- |
| exact cut MEETS the selection | 425 | the LP returned a point violating a selected action's tolerance by a fraction of a part per million: worst `|a.delta|/tol` = 1.000016, median 1.00000008 |
| exact cut disjoint from the selection | 7 | structurally distinct collisions the pairwise argument does not reach |

A selected action is constrained to read zero on the delta, so a cut containing one is only possible
at the solver's feasibility boundary. Those 425 are **conservative refusals -- the fail-closed
behaviour working** -- not missing structure. The real structural blocker is seven.

**A fail-open fix was considered and rejected.** Tightening the collision LP's right-hand side from
`tol` to `tol - feasibility_slack` would make every returned point genuinely satisfy the constraint
and would remove all 425 blockers at a stroke. It is unsound in the dangerous direction: a smaller
right-hand side means a smaller collision set, so the oracle could certify a plan that has a real
collision sitting just inside the boundary. Making certification EASIER is never the safe direction
here, and a change that removes 98% of the obstacles to certifying is exactly the shape of change
that deserves that suspicion.

What this leaves is an honest limit rather than a defect: at the registered action tolerance of
1e-8, with the collision LP solved to 1e-9, certification of a plan this tight is below the
resolution the pair (tolerance, feasibility tolerance) can express. Raising the resolution means
declaring a different action tolerance, which is a method change and a new freeze ID -- not
something to slip into a probe.

## Feeding the cuts back into the master

`synthesize_minimum_observation` accepts `seed_cuts` as action-ID lists. Seeding is sound but is
NOT how the headline number is obtained, and the measurement says why.

| run | status | bound | iterations |
| --- | --- | --- | --- |
| unseeded, 2 iterations | UNRESOLVED | 5.0 | 2 |
| seeded with all 1028 cuts, 600 s | UNRESOLVED | 715.1 | 12 |
| structural computation | — | **1112.0** | — |

Seeding raises the master's anytime bound from 5.0 to 715.1, a 143x improvement, and it still
falls short of the structural computation. That is expected and is the point: the anytime bound
is an LP relaxation of the hitting set, which on a clique pays 1/2 per vertex and so recovers at
best half of the true cover. The structural computation solves each cell's cover exactly and adds
across disjoint supports, which the generic relaxation cannot see. **The decomposition is not
only a better way to find cuts; it is a strictly stronger way to evaluate them.**

Both seeded runs above end UNRESOLVED on a solver time limit, which is the fail-closed budget
path and not a defect.

## Two errors found by running it

Recorded because both were caught by guards rather than by inspection, and one of them was mine
twice over.

**The delta's shape must be constrained, not hoped for.** The first implementation merely dropped
the pair's two actions from the selection. An action constraint is `|a . delta| <= tol_a`, not an
equality, so the LP spread the delta across every block: the first witness's exactly recomputed
cut had NINE actions, seven of them coarse. One coarse action in the cut collapses the bound,
because the master can hit it for 1.0 instead of two single-block actions for 8.0.

**Seeding initially made the instance WORSE, and the seeds were not at fault.** The selection
stays empty until the first master refresh, which is correct only when the ledger starts empty.
With 1028 narrow two-action seeds present, separating against the empty selection returns generic
collisions whose cuts are wide; every wide cut is a superset of some seed, the antichain rejects
them all as dominated, and the loop's "no new cut" guard fires at iteration one — reporting a
tolerance inconsistency for what was a modelling mistake. The result was UNRESOLVED with no bound
at all, worse than not seeding. Two other explanations were tested and discarded first: the
feasibility tolerance (1e-9 and 1e-10 behave identically) and domination by the exact
two-element cuts (impossible, since `separating_action_cut` already excludes selected actions by
index).

Separately, the cover search's original edge-branching exhausted a two-million-node budget on the
near-complete 21-block cells and refused — correctly, but a bound that cannot be computed is
still no bound. Branching on a max-degree vertex decides twenty vertices at once on the excluding
side and solves the same graph in under a second, returning the same 144.0 the earlier completed
run measured.

## Scope

One candidate, one package, one workload. Nothing here establishes that the ratio transfers to
other instances; the cell structure is a property of the measurement library and floorplan and
must be measured per candidate. The scan restricts reject cells to the eight (model, point) pairs
with the largest `|R[m,q,b] - R[m,q,c]|`, and restricts nothing else; both restrictions can only
lower the bound.
