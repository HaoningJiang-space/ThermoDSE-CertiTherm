# A certificate-constrained search reaches a feasible design the incumbent's own optimum is not

RESULT 2026-08-04, `moe-server`, `/data/ziheng/ThermoDSE-CertiTherm` clean, pinned HotSpot
`sha256 b0040b3e…`. NON-CLAIM. **No external review** — Codex quota-locked to 2026-08-08.
Envelope span `0.30`, `grid128-avg`, ceiling `330.0 − 0.05 − 0.01 = 329.94 K`, routed trace.

## The head-to-head

Seed: `arch_b` on `transformer` — ThermoDSE's own registry design, evaluated through exactly the same
pipeline as every candidate. Budget 40 candidates, 0 UNRESOLVED. Neighbourhood is the archive's own
per-field value sets, so the search cannot leave the space ThermoDSE's search explored.

| | EDYP | certified peak | nominal peak | slack | verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| **baseline** `arch_b` | **13.8628** | 331.558 | 329.973 | **−1.618** | **REFUTED** |
| **found** (`mtxu_h` 128 → 192) | **15.0792** | 329.612 | 328.307 | **+0.328** | **CERTIFIED** |

> **The incumbent's design is infeasible over its own declared activity envelope. A search whose
> feasibility test is the certificate reaches a feasible design at `+8.77 %` EDYP.**

One coordinate moved: `mtxu_h` from 128 to 192. Energy went *down* (17.6161 → 17.3824 mJ) and latency
up (0.7291 → 0.7858 ms), so the EDYP price is a latency and yield price (0.9265 → 0.9059), not an
energy one. Mean placed power falls 57.185 → 52.521 W over the same 233 blocks.

**The two-phase descent is what found it.** From an infeasible start, minimising EDYP searches for the
cheapest point of a region the search may not end in: the first field tried moved the peak 0.4 K while
leaving EDYP bit-identical across three values. Phase 1 minimises the certified **peak** until
something certifies — it walked `mtxu_h` 48 → 64 → … → 176 with the peak falling 331.04 → 330.07 —
and only then does phase 2 minimise EDYP among certified designs. The invariant that makes it a
constrained search rather than a penalised one is pinned by tests in both directions: an uncertified
candidate moves the search **point** and never the **incumbent**.

## The complementary half: from a FEASIBLE baseline, EDYP goes down

Seed `arch_c`/transformer, whose baseline already certifies. Same pipeline, same neighbourhood,
budget 30, 0 UNRESOLVED.

| | EDYP | certified peak | nominal peak | verdict |
| --- | ---: | ---: | ---: | --- |
| baseline `arch_c` | 18.4394 | 329.017 | 327.548 | CERTIFIED |
| **found** (`mtxu_h` 128 → 256) | **18.1737** | **329.005** | 327.526 | CERTIFIED |

**`EDYP ratio 0.9856` — 1.44 % cheaper, and the certified peak is 12 mK lower rather than higher.**
The found design **strictly dominates** the incumbent's on both axes, which is the cleanest form the
"and EDYP is not worse" half of the claim can take.

**Both magnitudes are small and must be read as such.** 1.44 % EDYP is a real improvement but a modest
one, and 12 mK of peak is two orders inside the model-form band — it is *not* worse, which is all that
is claimed, and reading it as a thermal improvement would be over-reading noise. Together with the
`arch_b` run the pair is the whole statement: **from an infeasible incumbent design the search reaches
feasibility for `+8.77 %`; from a feasible one it reaches `−1.44 %` while staying feasible.**

The search walked the whole `mtxu_h` axis here — every one of 96, 112, 128, 144, 176, 192, 208, 224,
240, 256 certified, with peak falling monotonically to 328.602 at 240 and EDYP non-monotone — so the
minimum is not at the peak-minimising end. That is exactly why the constraint has to be a **feasible
set** and not a penalty: the cheapest certified design and the coolest certified design are different
designs.

## The cost breakdown, which is leg 2's actual measurement

| | seconds | share |
| --- | ---: | ---: |
| operator builds (12 misses) | **1526** | 91.8 % |
| ThermoDSE evaluations (40) | 134 | 8.1 % |
| **the certificate itself (40)** | **2.786** | **0.17 %** |

and on the `arch_c` run, independently: 1898 s of operator builds, 154 s of ThermoDSE, **2.669 s of
certificate — 0.13 %**.

**The certificate is 0.17 % of a certificate-constrained search.** That is the whole point of leg 1
and it is now measured end to end rather than in isolation: the thermal *feasibility test* is free and
the thermal *operator* is the cost. Library hit rate 1/12 — the single hit was the baseline operator,
re-read across a restart after the algorithm changed, which is the reuse the library exists for even
though zero design fields are geometry-invariant.

## The same failure on a second, independent population

The 61 archive designs under `transformer` — ThermoDSE's own top-64 by EDYP, every one selected on a
**reported peak ≤ 330 K** — certified with the same instrument:

| | value |
| --- | --- |
| `CERTIFIED_TO_MAX_SPAN` (radius ≥ 2.0) | 35 |
| finite radius | 25 |
| **`REFUTED_AT_NOMINAL`** | **1** |
| in the separator band `dist ∈ [0.311, 3)` | 1 |
| distance to ceiling | −0.041 to +8.940 K |

| design | archive-reported peak | our nominal | `dist` | **radius** |
| --- | ---: | ---: | ---: | ---: |
| **`arxv034`** | 327.7 K | 329.9807 | **−0.041** | **0.000** |
| **`arxv031`** | 328.9 K | 329.2174 | +0.723 | **0.0897** |
| `arxv046` | 328.4 K | 326.3820 | +3.558 | 0.578 |

**`arxv031` is the load-bearing row, not `arxv034`.** `arxv034`'s refusal is by **41 mK**, which is
two orders of magnitude inside the 0.25-1.43 K model-form band — that is `UNRESOLVED`-grade, and
calling it a refutation would be exactly the over-reading this project keeps catching. `arxv031`
certifies comfortably at nominal (+0.723 K) and **stops certifying once block activity varies by
9 %**. A 9 % activity swing is not an adversarial assumption; it is less than the difference between
two layers of the same network.

So the finding repeats on a population the development split does not contain: **a design selected by
the incumbent's own criterion, on its own reported peak, is feasible at its nominal power map and
fragile to ordinary workload variation** — and the incumbent has no number that says so.

Under `resnet50` the same 60 designs give `dist` 4.94-9.17 K, radius 0.951-2.000, zero refusals. The
population is the same; the operating point is not. **The frontier is a property of the workload, and
both populations are reported.**

## Rank correlation, and it separates the two populations

| | `resnet50` (n = 60) | `transformer` (n = 61) |
| --- | ---: | ---: |
| Spearman(dist, radius) | **+0.465** | **+0.982** |
| Spearman(power, radius) | −0.438 | −0.491 |

Far from the limit the nominal peak explains **less than half** the robustness ordering; near it the
two nearly coincide. That is the honest reading and it cuts against the metric: the radius earns its
keep on the **cold** population, where it separates designs a peak cannot, and adds little on the hot
one, where being close to the limit already implies fragility.

## What is NOT claimed

* **Not a better optimiser.** `+8.77 %` EDYP is the price of feasibility under this envelope, not a
  win over ThermoDSE's objective. ThermoDSE was not asked this question and its own cap is 348 K.
* **Not a global optimum.** Coordinate descent, first improvement, 40 candidates, one seed. A better
  certified design may exist and the search does not claim otherwise.
* **One workload, one package, `grid128` cells, max-of-cell-averages** — not a pointwise peak
  (`H¹ ⊄ L^∞` in 3D).
* **No model-form band folded in.** It would lower every peak by 0.25-1.43 K, which moves the found
  design's `+0.328 K` slack into `UNRESOLVED`. **Stated because it is the single number most likely to
  overturn this table**, and measuring `e_total` at the cell endpoint remains the binding action.
* **The envelope is declared.** `±30 %` per block with the total preserved is a specific uncertainty
  model, and the radius is reported so a reader can substitute their own.
