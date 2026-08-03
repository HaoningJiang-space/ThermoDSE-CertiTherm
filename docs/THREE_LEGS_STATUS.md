# The three legs, measured: one stands, one premise is refuted, one is not obtained yet

STATUS 2026-08-04, `moe-server`, `/data/ziheng/ThermoDSE-CertiTherm` at the commits named below,
clean. NON-CLAIM. **No external review** — Codex quota-locked to 2026-08-08.

The plan is: (1) an in-loop certificate that is an exact supremum over a declared activity envelope,
(2) a geometry-cached operator library plus a search loop, (3) evidence that designs produced by the
incumbent method violate the limit inside their own declared envelope. This records what each leg
actually measures, unfavourable results first.

## Leg 2 — the premise is refuted, and the repository already said so

**Reuse rate keyed by floorplan text: 0.0 %.** 61 archive designs under routed lowering induce **61
distinct augmented floorplans**. `docs/DIRECTION_FIXED_GEOMETRY.md` already reports "64 distinct
floorplan geometries with zero shared"; this confirms it on the DRAM-augmented floorplans, which is
new, and does not change the conclusion, which is not.

So the question is not whether the space factors but **along which coordinates**.
`geometry_factorisation.py` perturbs one design field at a time from `arch_a` and digests the
resulting floorplan:

| field | perturbation | `arch_a` | `arch_b` | `arch_c` |
| --- | --- | --- | --- | --- |
| `chiplet_x`, `chiplet_y`, `cut_x`, `cut_y` | +1 | **moves** | **moves** | **moves** |
| `mtxu_h`, `mtxu_w`, `ubuf`, `nop_bw`, `dram_bw` | x2 | **moves** | **moves** | **moves** |
| `interval` | +0.0003 m | *invariant* | **moves** | **moves** |

**Zero of ten, and the first measurement said one.** Measured on `arch_a` alone, `interval` left the
floorplan byte-identical and this document said so. On `arch_b` and `arch_c` it moves the floorplan like every
other field — `geometry-invariant: NONE` on both. The reason is `arch_a`'s own configuration — `cut_x = cut_y = 1`, so there are no
inter-chiplet gaps for the interval to space — and the invariance was that design's artefact, not a
property of the parameter. **A one-base measurement was generalised to the design vector and it was
wrong; the correction is measured on a second base, not argued.**

So no coordinate of this design vector is geometry-invariant, the space does not factor at all, and
the library's hit rate on a search over it is ~0.

An operator cache therefore cannot amortise a general search over this design vector, and leg 2 as
written does not exist. Two redefinitions survive and both are honest:

* **Restrict the search to a fixed geometry**, which is now the ONLY option that amortises anything,
  and which is what `DIRECTION_FIXED_GEOMETRY` already
  decided on independent grounds (cross-geometry `R` reuse costs 0.69-2.44 K against a model-form
  band of 0.25-1.06 K). The certificate is then 12 ms per candidate over the power-determining
  parameters, and the geometry is a declared input rather than a search variable.
* **Make the operator build cheap enough that per-candidate rebuild is affordable.** It is now 87 s
  for 37 blocks at 12 workers, bit-identically to serial (`THE_IMPULSE_LOOP_IS_PARALLEL.md`). That
  caps a search at hundreds of candidates, not millions.

Neither is the "geometry x power factorisation" the plan assumed. Reporting that is the point.

## Leg 3 — not obtained on this population, and the reason is the population

`frontier_census.py` produced routed traces for the 64 declared archive designs — **60 emitted, 3
excluded fail-closed** on a route-energy reconciliation failure, 1 already present — and
`thermal_robustness_radius.py` certified every one.

| quantity over 60 designs | min | median | max |
| --- | ---: | ---: | ---: |
| nominal peak | — | — | 325.00 K |
| **distance to the ceiling** | **4.937 K** | 6.903 K | 9.168 K |
| robustness radius | 0.951 | 2.000 | 2.000 |
| mean placed power | 5.51 W | 9.87 W | 18.51 W |

**Nothing failed, and nothing lies in the separator band `[0.311, 3)` — zero of 60.** Giving the
population back its missing heat did **not** move it to the frontier, and the reason is visible in the
last row: the archive's top-64 by EDYP draw **5.5-18.5 W**, against **28-57 W** for the development
split, whose transformer points sit at +0.92 K and −1.62 K. The archive census selects low-power
designs, so it is a cold population, and the routed displacement — 1.3 to 4.7 K on the development
split — does not close a 4.9 K gap.

> The hypothesis "the routed trace moves the archive population to the frontier" is **refuted**. The
> displacement is real and was measured; the gap it had to close was larger than expected because the
> population's power is a third of the development split's.

The next population to try is the same designs under `transformer`, which roughly doubles placed
power. That is a **different population**, not a re-reading of `archive-census-v1`, which froze
`resnet50`, and the driver says so at run time.

## Leg 1 — stands, and it is the one that is finished

`docs/CERTIFICATE_IN_THE_LOOP.md` states the three properties and
`CertiTherm/tests/test_certificate_in_the_loop.py` pins them, **27 tests**, each against something
independent of the implementation rather than a second copy of the same greedy:

* **Exactness** against a brute-force enumeration of the polytope's vertices — every vertex of a box
  with one equality has at most one interior coordinate, so `2^(n-1)` bound assignments visit them
  all. Agreement to `1e-9` on 12 random boxes, plus the LP oracle's `1.07e-9 K` on the development
  split.
* **One-sidedness**: the envelope nests, so widening never lowers the certified peak; and the
  certified supremum dominates the nominal point evaluation, which is the inequality the whole
  comparison against the field rests on.
* **Fail-closed**: non-finite inputs refused in all four positions, both empty-polytope directions
  refused, and the greedy's maximiser verified to satisfy the box and the total — so the number is
  attained at a feasible point rather than merely being an upper value.

**Measured cost: 0.244 s** for eight envelope widths plus a bisection to `1e-4` over 16 384 cell rows
— about **12 ms per candidate**, against 20-30 s for a HotSpot solve on this package.

## The positive result the population did yield

The radius is **not** a monotone function of the nominal peak, which is the only thermal number the
field reports.

| | Spearman rank correlation, n = 60 |
| --- | ---: |
| distance-to-ceiling vs radius | **+0.465** |
| mean power vs radius | −0.438 |
| mean power vs distance-to-ceiling | −0.470 |

The tightest design by nominal peak, `arxv031` at 4.937 K, has the **maximum** radius (2.0, certified
to the sweep's limit). The least robust design, `arxv055` at radius **0.951**, is *looser* by nominal
peak (4.971 K). Ranking by what everyone computes explains **less than half** the ordering of what
robustness actually is, and 13 of 60 designs have a finite radius inside the swept range while all 60
look equally safe by nominal peak.

That is what a certificate over a set buys that a point evaluation cannot, and it is one interpretable
scalar per design.

## Scope, and it cuts against the numbers above

* No model-form band is folded into any of these. Folding it in lowers every peak by 0.25-1.43 K.
* One workload, one package, `grid128` cells, the max-of-cell-averages endpoint — not a pointwise
  peak (`H¹ ⊄ L^∞` in 3D).
* The routed lowering keeps named modelling freedom: `io_die_aspect_ratio`, a fixed 50/50 NoC split,
  and X-then-Y routing.
* The radius sweep stops at span 2.0. `CERTIFIED_TO_MAX_SPAN` means "no smaller than 2.0", not 2.0.
