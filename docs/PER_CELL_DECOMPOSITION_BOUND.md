# A decomposition that raises the certified lower bound 6.7x

**On the title.** An earlier version of this file was called "A certified lower bound that
does not enumerate confusable pairs". That overstated it, and the distinction matters:

  * the DECOMPOSITION step is non-enumerative -- `C*(whole) >= C*(cell)` is a one-line subset
    argument that discovers nothing and depends on no property of the separation oracle;
  * the per-cell BOUND is still obtained by enumeration, just confined to one cell.

So this is a better-conditioned instance of the same machinery, not a different kind of
bound. A genuinely non-enumerative bound -- a semi-infinite dual over the difference sets, or
a dimension argument -- remains unbuilt.

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

The inequality is elementary and enumerates nothing; what it bounds is still computed by
enumeration inside the cell.

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
| (model 0, point 170) | 191.5 | UNRESOLVED | 6 017 | 5 615 |
| (model 1, point 28) | 101.2 | UNRESOLVED | 7 498 | 5 997 |
| (model 1, point 113) | 69.8 | UNRESOLVED | 7 698 | 7 208 |
| (model 1, point 198) | 79.2 | UNRESOLVED | 7 813 | 6 837 |
| (model 2, point 56) | 129.9 | UNRESOLVED | 7 237 | 6 058 |

The spread matters as much as the maximum. Cells differ by 3x -- 69.8 to 215.0 -- so the
bound is carried by the hardest cell, not by a typical one. A decomposition that averaged
cells, or that sampled one arbitrarily, would throw most of it away.

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

## The naive dimension bound is too weak to be worth building

`docs/CERTIFIED_GAP_CONVERGENCE.md` lists a dimension argument as one of two shapes a
genuinely non-enumerative bound could take. Worked out on paper before writing any code, the
naive form is not worth it, and recording why saves the next reader from implementing it.

Ignoring tolerances, a plan `S` separates a cell exactly when `ker(M_S)` misses the difference
set `D`, which holds exactly when the row space of `M_S` contains a linear functional of
constant sign on `D`. For a single action that is decidable with two LPs -- minimise and
maximise `v_a . delta` over `D` -- and if no single action has constant sign, then `|S| >= 2`
and `C*(cell) >=` the two cheapest action costs.

On this instance the two cheapest actions are module reads at 1.0 each, so the bound is **2**,
against the **215** the per-cell enumeration already certifies. Two orders of magnitude
weaker. Extending it to `k`-subsets costs O(|A|^k) LPs and still bounds by the k cheapest
costs, which grows far too slowly to matter.

A useful non-enumerative bound has to use both things the naive form discards: the per-action
tolerances, so the object is a slab intersection rather than a kernel, and the cost structure,
so the statement is "every action set of cost at most C leaves a collision" rather than "every
set of cardinality at most k does". That is the semi-infinite dual, and it is research work
rather than an afternoon's instrumentation.

## Scope

One candidate, one package, one workload, dev split, three sampled cells, 120 s each. Nothing
here is claim-grade, nothing changes a frozen contract, and the production path is unmodified
-- this is measured with `research/triangle/per_cell_bound_probe.py`, which only restricts a
`ThermalFamily` to one (model, point) and calls the unmodified
`synthesize_minimum_observation`.
