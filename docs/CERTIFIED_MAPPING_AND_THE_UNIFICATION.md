# The unification: architecture to SCBO, mapping to the certificate — with an exact bound

RESULT 2026-08-04, `moe-server`. NON-CLAIM. Routed traces, `grid128-avg` cell operators, span `0.30`,
`default` package. **No external review** — Codex quota-locked to 2026-08-08.

## Where the certificate is free, and it is not the architecture level

`THREE_LEGS_STATUS.md` measured that **zero of ThermoDSE's ten architecture fields leaves the
floorplan invariant**, so an operator cache cannot amortise an architecture search. That is a fact
about the architecture *vector*, not about the design space: **an architecture decides the geometry,
a mapping decides only the power vector.** Permuting which task runs on which core leaves the
floorplan byte-identical, so `R` is fixed and a mapping candidate costs **0.79–2.9 ms** — measured,
16 384 cells, 16–21 cores.

So the division of labour writes itself:

| level | who | why | cost per candidate |
| --- | --- | --- | ---: |
| architecture | **ThermoDSE's SCBO** | mixed 10-D space, each candidate genuinely costs an operator, trust-region BO is well suited | ~100 s (operator) |
| mapping | **the certificate** | `R` fixed, exact supremum, and an exact lower bound exists | **~1 ms** |

## What ThermoDSE does, and how far from optimal it is — which nobody could say before

`ThermoDSE/core/schedule.py:386` sorts cores by `sum over other cores of squared euclidean distance`
and greedily gives the highest-energy task to the largest factor. It is a **geometric proxy for
cooling**: it never consults the thermal operator, the package, or the other tasks' power.

The exact lower bound over **all** mappings is a per-cell **linear assignment problem** — a mapping
moves a core's whole power profile to another core's blocks, so cell `j`'s cost of putting profile
`k` at position `m` is `sum_r R[j, pos_m[r]] * p[pos_k[r]]`, and `min_pi sum_m C_j[m, pi(m)]` is
solved exactly per cell. One pass, no solver call beyond `linear_sum_assignment`, 16 cores.

| case | cores | ThermoDSE | best found | **exact lower bound** | **ThermoDSE's excess** | search gap |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `arch_a`/resnet50 | 21 | 325.6499 | 325.5774 | 325.4273 | **0.2226** | 0.1501 |
| `arch_a`/transformer | 21 | 327.1950 | 327.1753 | 327.1077 | **0.0873** | 0.0676 |
| `arch_b`/resnet50 | 20 | 327.4570 | 327.3457 | 327.2117 | **0.2454** | 0.1340 |
| **`arch_b`/transformer** | 20 | **329.9732** | **329.5358** | **328.3191** | **1.6541** | 1.2167 |
| `arch_c`/resnet50 | 16 | 325.1430 | 325.0683 | 324.9761 | **0.1669** | 0.0922 |
| `arch_c`/transformer | 16 | 327.5475 | 327.5280 | 327.4682 | **0.0794** | 0.0598 |

> **On five of six designs ThermoDSE's geometric heuristic is within 0.08–0.25 K of the exact optimum
> over all 16!–21! mappings. On the sixth — the one design that fails — it is 1.65 K away.**

That is the finding, and it cuts both ways. It **retires an open question in the incumbent's favour**:
the distance proxy is essentially optimal wherever there is thermal slack, and no one could
demonstrate that before because there was no bound. And it says **the heuristic degrades exactly where
a thermal method is needed** — on the thermally tight design, which is the only regime a feasibility
certificate is for.

## What remapping buys on the certified quantity

| case | ThermoDSE certified | best certified | **recovered** |
| --- | ---: | ---: | ---: |
| `arch_a`/resnet50 | 326.9768 | 326.9117 | 0.0651 |
| `arch_a`/transformer | 328.5463 | 328.5298 | 0.0165 |
| `arch_b`/resnet50 | 328.8711 | 328.7471 | 0.1240 |
| **`arch_b`/transformer** | 331.5584 | **331.0423** | **0.5160** |
| `arch_c`/resnet50 | 326.3818 | 326.3087 | 0.0731 |
| `arch_c`/transformer | 329.0170 | 328.9961 | 0.0210 |

**Remapping alone does not rescue `arch_b`/transformer**: 331.04 is still above the 329.94 ceiling.
It is **free** — a permutation costs no area, no energy and no latency — so it composes with the
architecture change that does rescue it (`mtxu_h` 128 → 192, certified 329.612 at `+8.77 %` EDYP,
`CERTIFIED_SEARCH_RESULT.md`). The two levels are independent and their gains add: the architecture
level buys feasibility at an EDYP price, the mapping level buys **0.02–0.52 K at no price at all**.

## The composition, measured on all four corners

`composed_result.py` runs both levels end to end on `arch_b`/transformer — the design the incumbent
refuses — and reports every corner rather than the favourable one.

| architecture | mapping | EDYP | certified peak | slack | |
| --- | --- | ---: | ---: | ---: | --- |
| ThermoDSE | ThermoDSE | 13.8628 | 331.5584 | **−1.6184** | **REFUTED** — the incumbent |
| ThermoDSE | certified | 13.8628 | 331.0423 | −1.1023 | REFUTED |
| certified | ThermoDSE | 15.0792 | 329.6121 | +0.3279 | CERTIFIED |
| **certified** | **certified** | **15.0792** | **329.1662** | **+0.7738** | **CERTIFIED** |

| | gain |
| --- | ---: |
| mapping level alone (free) | **0.5160 K** |
| architecture level alone (`+8.77 %` EDYP) | **1.9462 K** |
| both | **2.3921 K** |
| **additivity residual** | **−0.0701 K** |

> **The two levels are additive to 70 mK — sub-additive by 3 %.** Composing them takes the design
> from `−1.618 K` (refused) to `+0.774 K` of slack, and **more than doubles** the slack the
> architecture change alone buys, at **no additional EDYP**: the last `0.446 K` is a permutation.

That residual is the quantitative form of the independence claim. It is small but **negative**, so the
gains do not quite add — the architecture change moves the argmax cell, and the mapping optimised for
the old geometry is not quite the one the new geometry wants. Reporting it is what distinguishes a
measured composition from an assumed one.

## The lower bound was wrong first, in the direction that would have flattered the incumbent

The first version applied the rearrangement inequality to per-group column **sums** paired with
per-group power totals. Summing a group's columns is the response to one watt on *every* block of it,
so the contribution was inflated by the group size and the "lower bound" came out at **345.32 K
against an attained 327.55 K**. A bound above an attained value is not a bound — and had it been only
slightly too high instead of absurdly so, it would have made *any* heuristic look optimal, which is
the conclusion this document reaches and would have reached for the wrong reason.

It was caught because the **gap is reported, not just the bound**, and a negative gap is impossible.
The run now checks the bound against every mapping it evaluates rather than trusting the derivation.

## What is NOT claimed

* **Not a mapping optimum.** The search is steepest descent over pair swaps with four restarts; the
  gap column says how much it could still be missing (0.06–1.22 K). The **bound** is exact; the
  **search** is not.
* **Not that mapping is the lever.** On five of six it is worth less than 0.25 K. The honest reading
  is the opposite of a sales pitch: the incumbent's heuristic is good, and the value of certifying the
  mapping level is that it can now be *shown* to be good, and that the one case where it is not is
  identified rather than assumed.
* **The bound uses the nominal objective.** The envelope's box is built *from* the power vector, so a
  permutation moves the set as well as the point; certified peaks are reported for every mapping and
  the two are never mixed.
* Six designs, one workload each, one package.
