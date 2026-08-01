# The thermal error is local, the mapping triples it, and the max is what oscillates

RESULT 2026-08-01. Mechanism behind `docs/DISCRETISATION_ERROR_EXCEEDS_THE_DECISION_BAND.md`,
measured on `heldout_radii_11` (`6x2` cut 2x2, resnet50) at `grid64 / grid128 / grid256` through
HotSpot's `-grid_steady_file`, which exposes the raw cell field rather than the block-averaged
output the pipeline normally consumes.

Three separate findings, each of which changes what the repair should be.

## 1. The error is entirely LOCAL. The global balance is exact.

| grid | cells | mean rise over the die | peak temperature |
| --- | --- | --- | --- |
| 64 | 4 096 | 2.63342 K | 322.30 K |
| 128 | 16 384 | 2.63369 K | 322.49 K |
| 256 | 65 536 | 2.63369 K | 322.44 K |

**The mean rise moves 0.010 % across a 4x refinement; the peak moves 0.19 K, which is 4.4 % of the
4.34 K rise.** Steady-state heat out equals heat in, so the mean is fixed by the package thermal
resistance and the total power and is grid-independent by construction -- and it duly is, to four
significant figures.

Two consequences.

* **Power conservation and source rasterisation are NOT the problem.** Peer review raised the
  possibility that refining the grid changes how block power is rasterised onto cells, in which case
  a convergence study would be conflating source-representation error with discretisation error.
  A 0.010 % stable mean rules that out: the source is stable and the power is conserved.
* **Every cheap sanity check passes.** Total power, mean temperature, package balance -- all exact.
  The model resolves the quantity nothing depends on and fails to resolve the one the decision
  depends on, which is why this went unnoticed through a whole method freeze.

## 2. The underlying field converges well. The BLOCK-AVERAGE mapping triples the error.

Per-cell, comparing each `grid64` location against the mean of its children:

| comparison | max over cells | median |
| --- | --- | --- |
| `｜64 − 128｜` | 0.2150 K | 0.00500 K |
| `｜128 − 256｜` | **0.0444 K** | 0.00187 K |

The change shrinks by 4.8x on the maximum for a 2x refinement -- consistent with second order -- and
**78.4 % of cells shrink monotonically**. That is a well-behaved field.

Now the same architecture, same power map, at BLOCK level, which is what the certified operator uses:

    per-CELL   |128 - 256|  max  0.0444 K
    per-BLOCK  |128 - 256|  max  0.1491 K      3.4x worse

Averaging normally suppresses error. It amplifies here because the block average at `gridN` and at
`grid2N` is **not the same functional**: which cells fall inside a block's footprint changes with the
grid, so the two averages are taken over different supports. The mapping, not the physics,
contributes most of the error the certificate was charged for.

## 3. The max oscillates because the ARGMAX moves

| grid | peak | location (row, col as a fraction of the die) |
| --- | --- | --- |
| 64 | 322.3000 | (0.375, 0.250) |
| 128 | 322.4900 | (0.375, 0.250) |
| 256 | 322.4400 | **(0.379, 0.258)** |

The hottest cell is in the same place at 64 and 128 and moves at 256. A maximum over many smoothly
converging quantities is not itself smoothly converging when the argmax changes -- the sequence
322.30, 322.49, 322.44 is non-monotone for that reason, not because any cell's temperature is
misbehaving.

This is the "active witness" instability peer review named: a certificate depends on convergence of
the decision set and its witnesses, not of the optimum value.

## The method this prescribes

**Never verify a maximum, and never verify an average.** Verify each row, then bound the maximum by
the maximum of the per-row bounds:

    max_j T_j(p)  <=  max_j [ T_j^coarse(p) + u_j ],      u_j = max_{p in P} [ T_j^fine(p) - T_j^coarse(p) ]

Every `u_j` is a per-row quantity over a smooth field, so it is the kind of thing a refinement study
can legitimately verify. The max is taken over BOUNDS, never over the quantity being verified, so the
argmax may move freely without breaking anything. `CertiTherm/cross_grid_bound.py` computes `u_j`
exactly -- the discrepancy is affine in `p`, so its extremes over the power polytope are a greedy
fill -- and `one_sided_containment_bounds` returns the signed version that set containment needs.

The measurements above say what this buys:

* dropping the block-average mapping in favour of cell rows removes a **3.4x** amplification;
* the residual per-cell discrepancy at `128 -> 256` is **0.044 K** against a decision margin of
  2–8 K, which is 0.5–2 % rather than the 15–140 % the block-level five-vector estimate implied.

**That is the first quantitative reason to think the thermal half is recoverable**, and it was not
visible until the raw cell field was looked at instead of the pipeline's block output.

## What this does NOT establish

* One architecture, one workload, one power map. The 3.4x amplification and the 0.044 K residual are
  measurements on `heldout_radii_11`, not a general result.
* `grid256` is still not ground truth. Everything here is agreement between discrete operators.
* Cell-level rows cost `N^2` constraints instead of ~230 -- 16 384 at `grid128`, 65 536 at
  `grid256` -- and the reject enumeration scales with them. The build cost does not change (one
  HotSpot solve per block either way, just more output per solve), but the collision search does.
* The 0.044 K figure is the residual between two grids at common locations. It is not a bound over
  the polytope; `cross_grid_bound` computes that, and on adversarially concentrated power maps it
  will be larger -- measured, the most concentrated calibration vector drifts 0.319 K where the
  placed map drifts 0.149 K.
