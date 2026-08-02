# `g1-scheduling-leverage`: does the scheduling decision move temperature at all?

PREREGISTRATION, written 2026-08-02, before any number is read. NON-CLAIM tier by construction.
This gate decides whether the fixed-geometry mainline is worth building, and it is designed to be
answerable **without building any of it**.

## Why this gate exists before G1, not inside it

The direction decided 2026-08-01 (`docs/DIRECTION_FIXED_GEOMETRY.md`) is thermal-constrained
scheduling and mapping on a FIXED geometry. Its intended contribution needs a Pareto separator: a
schedule that a fixed 3-5 K guard band rejects, that a computed thermal constraint accepts, that an
independent replay confirms safe, and whose objective is better.

**A separator cannot exist unless the scheduling decision moves peak temperature by more than the
gap between the guard band and the computed band.** Nothing has measured that. Two facts found while
scoping G1 say it must be measured first:

1. **The decision variable does not exist in the current assets.**
   `CertiTherm/thermodse_bridge.py` calls `evaluator.evaluate()` once per (architecture, workload)
   and the capture format actively refuses anything else:

       if len(lines) != 2 or len(lines[0]) != len(lines[1]):
           raise RuntimeError("frozen workload capture requires exactly one aligned power sample")

   There is one `placed_power_w` vector per case. There is no schedule ensemble, and producing one
   means either reaching into the frozen `ThermoDSE` submodule's scheduler or changing a receipted,
   cached capture format. Both are real scope, and both would be spent BEFORE the gate they feed.

2. **The two power terms scheduling most affects are smeared or absent by construction.**
   From the measured energy ledger in `docs/THERMODSE_ENDPOINT_AUDIT.md`:

   | source | reaches HotSpot | columns | spatially resolved |
   | --- | ---: | ---: | --- |
   | core | **12.0756 W** | 80 | yes -- per block, schedule-sensitive |
   | NoC | 1.6064 W | 64 | **no** -- spread uniformly over `io_*`, which "destroys its spatial information by construction" |
   | NoP | 0 W | 0 | dropped by name alignment, now fail-closed with an explicit record |
   | DRAM | **0 W** | 0 | never written; 40.56 % of dissipated source energy |

   So **88.3 % of the placed power is the core term**, which is genuinely schedule-sensitive, and the
   communication term is not resolved at all. Leverage is not structurally zero, but it is
   attenuated, and the attenuation is in the generator rather than in the physics.

Running G1 on a scheduler built before this gate would measure the leverage of a defective trace,
not the leverage of scheduling.

## The claim under test (single, falsifiable)

> Over the power maps reachable by redistributing the schedule-sensitive fraction of power across
> the die at fixed total, the certified quantity `max_j sup_p T_j(p)` spans at least **1.0 K**.

**Where 1.0 K comes from, fixed before running.** A separator needs the schedule spread to exceed the
difference between the guard band it must beat and the band this method actually carries:

| term | value | source |
| --- | ---: | --- |
| linearisation | 0.01 K | frozen contract |
| model form (upper envelope) | <= 1.061 K | `MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` |
| boundary realisation, inside the above | 0.345 K | `a24d997` |
| cell-minus-block | +0.213 to +0.623 K | `CELL_ENDPOINT_RESULT.md` |
| **computed band, composed** | **~2.0 K** | sum of the above, not a new measurement |
| incumbent guard band | 3-5 K | the convention being beaten |
| **headroom a separator must fit in** | **~1-3 K** | difference |

A schedule spread below 1.0 K cannot fit a separator inside that headroom under any policy, so 1.0 K
is the smallest threshold at which the mainline could survive. It is a lower bound on viability, not
a target.

## Method -- Stage A, read-only, zero new solves

**This is the whole point of the design: the leverage upper bound is computable exactly from assets
that already exist.** The thermal operator is affine, so the extremes of `T_j` over any polytope are
attained at vertices and found by greedy fill or LP -- the machinery in
`CertiTherm/cross_grid_bound.py` (`peak_over_polytope`, `one_sided_containment_bounds`).

Inputs, all already on disk: the six `grid128` cell operators built for
`docs/CELL_ENDPOINT_RESULT.md`, and the six captures they were built from.

For each of the six development cases:

1. Partition the placed-power vector into the **schedule-sensitive** columns (the 80 `core` columns:
   `mtxu`, `vecu`, `ubuf`, `ibuf`, `obuf` per core) and the rest (`io_*`, uniformly smeared NoC).
2. Build a polytope that holds the total core power at its placed value, holds every non-core column
   fixed at its placed value, and lets each core column range over `[0, total_core]`.
3. Compute `max_j sup_p T_j(p)` and `max_j inf_p T_j(p)` over that polytope with the existing
   affine machinery.
4. Report the span.

**This is an UPPER bound on scheduling leverage and is intended to be.** The set of power maps a real
scheduler can reach is a subset of arbitrary redistribution at fixed total, so the true span is no
larger. A gate that closes on an upper bound closes for good; a gate that passes on one has proved
nothing except that Stage B is worth its cost.

Not varied, and stated so the bound is not read as tighter than it is: per-column upper limits from
device physics, the fixed total core power, the NoC smearing, and the absent DRAM heat.

## Kill conditions, registered

* **K1.** If the span is **< 1.0 K on all six cases**, the scheduling decision cannot be separated
  from a guard band by any thermal constraint this method can compute. **Stop the fixed-geometry
  mainline.** Do not build a scheduler, do not build a schedule ensemble, do not wire
  `error_budget.py` for this purpose.
* **K2.** If the span is >= 1.0 K on some cases but the cases where it is large are exactly the
  cases already certified with several kelvin of slack, the leverage exists where it cannot matter.
  Record and re-scope rather than proceed.
* **K3.** If any case's polytope is empty, any LP returns non-optimal, or any operator fails its
  reciprocity or energy-balance check, the case is **UNRESOLVED** and counts against neither
  direction. A gate that silently drops a case is not a gate.

## Rollback

Stage A writes one document and no code on the certified path. Nothing to roll back. Stage B is a
separate preregistration and is not authorised by this one.

## What a PASS does and does not license

**Licenses:** spending Stage B's cost -- exposing a schedule ensemble, which requires an explicit
decision about the frozen `ThermoDSE` submodule and the receipted capture format.

**Does NOT license:** any statement that scheduling improves temperature, that a separator exists, or
that the mainline will produce a SOTA number. The span is an upper bound on an upper bound: it
bounds what any scheduler could do, over a trace whose communication term is smeared and whose DRAM
term is missing.

## Requested dissents (>= 3, per the round protocol)

1. **The partition is wrong.** `ibuf`/`obuf`/`ubuf` are buffers whose power may track data volume
   rather than task placement, so calling all 80 core columns "schedule-sensitive" may overstate the
   reachable set and inflate the span in the direction that passes the gate.
2. **The threshold is reverse-engineered.** 1.0 K was derived from a band composed by SUMMING terms
   that were measured separately and may not be independent -- in particular the boundary-realisation
   term sits *inside* the model-form envelope rather than beside it, so the composed ~2.0 K may
   double-count.
3. **Fixed total core power is the wrong invariant.** A schedule that changes utilisation changes
   total energy and latency, so holding the total fixed may exclude precisely the schedules with the
   most thermal leverage -- making this a bound on the wrong set.
4. **An upper bound that passes is nearly uninformative.** Arbitrary redistribution at fixed total is
   so much larger than the reachable schedule set that a PASS may be almost guaranteed, in which case
   the gate only has power in the K1 direction and should be described as a one-sided kill test
   rather than a gate.

## Status

**REGISTERED, NOT RUN.** No number in this document was produced by this gate; every figure quoted
is a citation to work already committed. The run requires a pinned revision and an isolated
worktree -- `HEAD` moved four times during the scoping of this gate, and the cell-endpoint run it
depends on is itself recorded as not having bound its starting SHA.
