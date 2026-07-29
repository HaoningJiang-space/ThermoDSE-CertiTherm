# A certified lower bound that does not enumerate confusable pairs

MEASURED 2026-07-29, dev split, one candidate. NON-CLAIM. Supersedes nothing; it is the
first bound in this project that improves on the enumerated one, and it improves on it by
6.7x at a fifteenth of the budget.

## Why a different bound was needed

`docs/CERTIFIED_GAP_IS_FORMULATIONAL.md` measures the enumerated hitting-set bound saturating
near **32** against a certified upper bound near **1450** for this candidate, and shows the
saturation is structural: logarithmic growth extrapolating to ~10^92 cuts, a second wall
where the master stops solving past 4 000 cuts, and three failed attacks -- harvesting policy,
cut selection, and separating the master's optimum instead of the greedy cover.

None of those attacks changed the bound because they all stayed inside the same object: a
hitting set over confusable pairs discovered one at a time from the whole instance.

## The bound

Elementary, and it enumerates nothing:

> A plan sufficient for the whole instance is sufficient for any SUBSET of its reject cells,
> because dropping cells only removes constraints. Hence the set of globally sufficient plans
> is contained in the set of plans sufficient for one cell, and minimising cost over a subset
> cannot give less than minimising over the superset:
>
>     C*(whole instance)  >=  C*(cell)   for every reject cell,
>
> so `max over cells of C*(cell)` is a valid global lower bound.

Any valid lower bound on a per-cell optimum inherits this, so a budget-truncated per-cell run
still contributes.

## Measured

`transformer` / `default` / `arch_b`: 227 blocks, 3 models, 681 reject cells, 243 actions,
library cost 1846, certified upper bound ~1450. Cells sampled with a stride rather than a
prefix, because adjacent blocks have near-identical responses. **120 s per cell.**

| reject cell | certified lower bound | status at cutoff | iterations | active cuts |
| --- | ---: | --- | ---: | ---: |
| (model 0, point 0) | **215.0** | UNRESOLVED | 6 150 | 5 742 |
| (model 0, point 85) | 87.5 | UNRESOLVED | 8 209 | 6 455 |
| (model 0, point 170) | 191.5 | UNRESOLVED | 6 067 | 5 659 |

Against the global enumerated bound of 32.0 obtained from 1 800 s:

| | certified lower bound | budget |
| --- | ---: | ---: |
| whole instance, enumerated | 32.0 | 1 800 s |
| **best single cell** | **215.0** | **120 s** |

**6.7x the bound at a fifteenth of the budget**, and the certified interval for this candidate
narrows from 45x to 6.7x. Every per-cell run was still UNRESOLVED at its cutoff, so each
number is itself a lower bound on that cell's optimum -- the true values are higher.

## Why it works

In the whole instance a witness from cell A is very often separated by an action that also
separates witnesses from many other cells, so the discovered cuts overlap heavily and their
hitting set stays cheap -- measured directly: 3 619 global cuts were hit by four actions
costing 32. Restricted to one cell, every witness comes from the same place, the cuts
concentrate on the actions that distinguish THAT cell, and the hitting set is forced up.

The global problem is not hard because each cell is hard. It is weak because pooling cells
lets one cheap action discharge evidence from all of them at once.

## What this does and does not establish

Establishes: a bound obtained without enumerating cross-cell witnesses beats the enumerated
one by 6.7x here, and does so inside a per-cell budget an order of magnitude smaller. The
soundness argument is one line and does not depend on any property of the separation oracle.

Does not establish: that the per-cell problems terminate -- none of the three did within
120 s; that the maximum over all 681 cells is materially higher than over three sampled ones;
that this closes the interval, which stands at 6.7x rather than 45x but is not tight; or
anything about candidates other than this one.

Open and worth measuring next: whether a per-cell run terminates at a larger budget, giving a
certified per-cell OPTIMUM rather than a bound; how the maximum grows with the number of
cells sampled; and whether the same decomposition applied to pairs or small groups of cells
is stronger still without returning to the pooled regime.

## Scope

One candidate, one package, one workload, dev split, three sampled cells, 120 s each. Nothing
here is claim-grade, nothing changes a frozen contract, and the production path is unmodified
-- this is measured with `research/triangle/per_cell_bound_probe.py`, which only restricts a
`ThermalFamily` to one (model, point) and calls the unmodified
`synthesize_minimum_observation`.
