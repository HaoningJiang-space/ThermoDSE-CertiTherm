# Can one thermal operator serve a whole design class?

PROBE 2026-08-01, read-only on artifacts already built. No new HotSpot or FEM runs.

The certificate is `sup_p T(p) <= limit`, and `T = R p + a` is affine, so thermal feasibility is a
set of **linear rows in the power vector**. That is what would let it move from an oracle called once
per candidate into a constraint inside a search. The whole idea rests on one question:

> `R` depends on the floorplan and the floorplan depends on the architecture. If every candidate has
> its own `R`, amortisation is impossible and the constraint costs `n + 1` solves per candidate --
> **worse** than the one solve per candidate it replaces.

## Route 1, reuse `R` unchanged within a topology: DEAD

Over the 64 archive designs of `archive-census-v1`:

| | |
| --- | --- |
| distinct floorplan geometries (exact) | **64** -- one per design |
| geometries shared by more than one design vector | **0** |
| distinct block-name lists | 19 |
| distinct `(xx, yy, cx, cy)` quadruples | 27 |
| quadruples mapping to more than one geometry | **13 of 27**, one of them to 10 geometries |

`R` is **never** reusable as-is. The topology quadruple fixes which blocks exist and how they are
arranged; the other six parameters (`h_sa`, `w_sa`, `ubuf`, the bandwidths) change block **sizes**,
and that changes the geometry every time.

## Route 2, a one-sided reuse band within a class: ALIVE, but only computed exactly

Within a block-name class the names and the arrangement match, so two members' response matrices are
directly comparable. A crude entrywise bound says the idea is hopeless; the exact bound says it is
not.

| class (blocks) | members | **exact `sup_p [T_theta(p) - T_theta0(p)]`** | median | crude `max abs(dR) x P` |
| --- | --- | --- | --- | --- |
| 23 | 14 | **0.90 K** | 0.29 K | 5.27 K |
| 23 | 12 | **2.44 K** | 1.49 K | 11.93 K |
| 45 | 6 | **1.60 K** | 0.77 K | 15.89 K |
| 33 | 5 | **0.69 K** | 0.21 K | 7.96 K |
| 67 | 5 | **1.23 K** | 0.64 K | 15.61 K |

`theta0` is the class member with the lowest nominal peak; the bound is over that member's own
activity-bounded polytope at span 0.30.

**The crude bound is 6 - 10x too loose and would have killed the idea.** The exact one is the same
`one_sided_containment_bounds` this project already uses for cross-grid and cross-solver comparison,
because the construction never cared what the two operators *were* -- only that both are affine.

## The class is free: it is a function of four integers

| predictor | groups | groups spanning more than one block-name class |
| --- | --- | --- |
| `xx, yy` | 14 | 5 |
| **`xx, yy, cx, cy`** | **27** | **0** |
| `xx, yy, cx, cy, h_sa, w_sa` | 63 | 0 |

`(xx, yy, cx, cy)` determines the class exactly, so **which operator a candidate needs is known from
its design vector without running anything**. The schedule can be computed before the first solve.

## What it buys, archive-wide

| population | designs | classes | amortisation |
| --- | --- | --- | --- |
| whole archive | 11 916 | **854** | **14x** |
| cool pool (reported peak <= 330 K) | 4 196 | **273** | **15x** |

The distribution is favourable: the largest class holds 740 designs and singletons account for 21 %
of classes but only **1.5 % of designs**. At ~30 s per FEM operator on one A800, 854 class operators
is about **7 hours**; one per design would be 99.

## What it costs, and this must not be hidden

The reuse band is **0.69 - 2.44 K** and it is charged on top of everything else. For comparison, the
measured model-form band against the independent FEM solver is 0.25 - 1.06 K. **So amortising the
operator across a class roughly doubles to triples the error budget.** Whether that is worth 14x
depends entirely on the margin in the population being searched, and on this archive's population the
margins are 5 - 10 K, so it is comfortably affordable. On the development registry, whose tightest
point has 0.31 K of slack, it is not.

## Honest scope

* One workload (`resnet50`), one package (`default`), 64 designs, `grid512-avg` rows.
* The reuse band was measured against a *chosen* `theta0` (lowest nominal peak). A different choice
  gives a different band; the right construction is the member minimising the class-wide worst case,
  which is a small optimisation not yet done.
* This says nothing about whether a search **using** these rows finds better designs. It says only
  that the rows can be built 14x more cheaply than one-per-candidate.
* Route 1's death is specific to ThermoDSE's parameterisation, where block sizes are search
  variables. A parameterisation that fixed block sizes would keep `R` constant within a topology.
