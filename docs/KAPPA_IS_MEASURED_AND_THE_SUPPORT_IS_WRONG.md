# The non-uniformity is measured, and it is the smaller of two findings

RESULT 2026-08-03, `moe-server`. NON-CLAIM: read from routed traces already committed by the V6.1
factorial (`artifacts/v61/complete_trace_transformer_arch_b_*.npz`). No frozen input changed, no new
run.

## Why `kappa` was asked for

`split_missing_heat.py` caps the nuisance placement at `q_i <= Q * A_i / A(S)` with `sum q_i = Q`.
That pair is a **singleton** — summing the caps gives exactly `Q`, so every `q_i` is forced to its
bound. The "placement spread" it reports is the value at the uniform-density placement, not a
supremum over placements, so the certificate it supports certifies uniform density rather than every
admissible spreading. `kappa` reopens the set: `q_i <= kappa * Q * A_i / A(S)`.

The critical values, from the sweep, are the non-uniformity at which each case stops certifying:

| case | slack | `kappa*` |
| --- | ---: | ---: |
| `arch_a`/resnet50 | 6.675 | **inf** |
| `arch_a`/transformer | 2.137 | **2.869** |
| `arch_b`/resnet50 | 3.343 | **4.980** |
| `arch_b`/transformer | -3.096 | **0** (refuted before placement) |
| `arch_c`/resnet50 | 7.063 | **inf** |
| `arch_c`/transformer | 2.746 | **4.303** |

## `kappa` does not need a literature source: the routed lowering already places the heat

`CertiTherm/routed_trace.py` puts every source where its route says it goes, and the V6.1 factorial
already ran it. Reading the duration-weighted mean of each single-component trace on
`transformer`/`arch_b`, and taking each component's non-uniformity **within its own support**:

| component | power | live blocks (of 233) | where | `kappa` |
| --- | ---: | ---: | --- | ---: |
| DRAM | 13.7042 W | **4** | `dram_x0_y0`, `dram_x0_y4`, `dram_x5_y0`, `dram_x5_y4` | **1.000** |
| NoP | 3.0750 W | **5** | `blockX_1/5/13/17/…` | **2.140** |
| NoC | 8.9349 W | 52 | `io_*` | **1.869** |

**Measured `kappa` is 1.000 to 2.140**, below the critical value on three of the four conditional
cases (`4.980`, `4.303`, `inf`, `inf`) and above it on one (`arch_a`/transformer at `2.869`, against a
NoP `kappa` of `2.140` — under it, but not by much).

## The larger finding: the support is wrong, not just its uniformity

`split_missing_heat.py` places **all** the missing heat on the compute die, split between the frame
(`eblk0..3`) and the centre. The routed lowering says otherwise:

**DRAM is 13.7042 of the 16.78 W of missing heat — 81.7 % — and it lands on four separate DRAM dies,
not on the compute die at all.** NoP's 3.075 W lands on five `blockX_*` inter-chiplet fillers, which
are in the die area but are five specific blocks rather than an area-weighted spread.

So both terms of the decomposition are computed over a support the lowering contradicts:

* the **guaranteed rise** `Q * min_{i in S} R_ji` uses `Q` = the whole centre share. If 81.7 % of it
  is on separate dies, `Q` over the compute support is far smaller and the guarantee is **overstated**;
* the **placement spread** is bounded over the die blocks, when the actual support is 4 DRAM dies plus
  5 filler blocks.

**This puts the round's hardest result in question.** `arch_b`/transformer was refuted under *every*
placement by `peak + guaranteed = 330.749 > 330`, which needed no placement evidence — and that is
still sound *given its support*. What this measurement challenges is the support, not the logic.
`Q * m` remains a true lower bound; the question is what `Q` and `S` are.

## What settles it, and it is running

A cell operator on the 233-block augmented floorplan, then the certificate from the routed trace
directly, through `research/triangle/robustness/routed_cell_certificate.py` — which reuses
`cell_operator`, `certify_cells` and `_block_average` unchanged so the number is comparable with
`CELL_ENDPOINT_RESULT.md` rather than being a new convention. The trace's own source and route
reconciliation receipts are enforced at load and pass (`57.1847 W` mean over a `4.05e-4 s` horizon).

HotSpot was built in the pinned worktree for this, from the patched export, both patches applied,
`sha256 b0040b3ecb82897e4f95dc827de643d9b545ef6cca9a2e5c1bdc8a6d7a1c68f4`.

## Scope

One case — `transformer`/`arch_b`, the point already refused. The **structural** finding (DRAM to its
own dies, NoP to `blockX_*`, NoC to `io_*`) is a property of the lowering and not of the case, but the
`kappa` values are that case's and must not be quoted for the other five until their routed traces
exist. The V6.1 factorial ran one architecture-workload pair; the other five would each need a
`complete_trace_probe.py` run.
