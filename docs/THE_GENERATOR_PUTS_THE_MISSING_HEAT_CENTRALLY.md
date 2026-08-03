# Both missing sources go to the central block, and that is read from the generator

> **PARTIALLY WITHDRAWN 2026-08-03. See `docs/PER_CASE_Q_WITHDRAWS_THE_PLACEMENT_FREE_REFUSAL.md`.** The generator reading is correct and stands. The **consequence** does not: every uplift here used `dP = 0.9997 x placed power`, one architecture's audit closure applied to six, and it is the LARGEST of the six measured values. With the per-case ledger, **five of six survive** the fully corrected trace rather than three, `arch_c`/transformer **is** certified, and the *"the +32.1 % price is quoted for a destination whose feasibility is not established"* conclusion is withdrawn. The NoC over-count table, the spreading bracket and the column-order finding are unaffected.

RESULT 2026-08-03, `moe-server`, isolated worktree pinned at `e1b174c`, clean, load 4.06 on 52 cores.
NON-CLAIM: computed from committed cell operators and captures by one matrix-vector product. **No
frozen thermal input was changed and no Tier-2 action was taken.**

## What was believed, and it was half right

`NUISANCE_BOUND_IS_NOT_AN_ESCAPE.md` established from `gen_floorplan.py:325,327` that
`eblk0..3 == dram_e0..e3 == interposer_e0..e3` — the same `gen_cover_flp` call with identical
arguments. Placing the missing heat on those four frame strips, **5 of 6 rows survive** and the
`arch_b -> arch_c` headline is strengthened.

**The geometric correspondence is correct. The power on those blocks is zero.**

## The generator's own column order settles it

`ThermoDSE/core/statistic.py::gen_all_ptrace_3D` writes the header **central first**:

    str_ = 'interposer\tinterposer_e0\tinterposer_e1\tinterposer_e2\tinterposer_e3\t'
    ...
    str_ += f'{p_itp:.4f}\t{0:.4f}\t{0:.4f}\t{0:.4f}\t{0:.4f}\t'      # p_itp = sum(nop)/latency

so **NoP power goes entirely to the central `interposer`** and the four edges get zero — exactly what
`THERMODSE_ENDPOINT_AUDIT.md:138` records. And the commented-out DRAM block is the same pattern, with
its own header line confirming the same order:

    # str_ += 'dram\tdram_e0\tdram_e1\tdram_e2\tdram_e3\t'
    # for nn_name in self.nop_dict.keys():
    #     p_itp += np.sum(self.dram_dict[nn_name]) * 1e-12 / latency
    # str_ += f'{p_itp:.4f}\t{0:.4f}\t{0:.4f}\t{0:.4f}\t{0:.4f}\t'

**So the intended DRAM placement is 100 % central as well.** The frame strips were never going to
carry any of it. An earlier reading of this document's author had the column order backwards — `_e0`
first — which would have put the heat on a frame strip and preserved the favourable answer. The
header line is what settles it, and it is one line above the write.

## Where the central block actually goes, and why no Tier-2 change is needed

The central block cannot be added to `output_3D.flp`: `gen_sys_floorplan` writes `eblk0..3` and then
**tiles the entire sys area** with compute blocks, NoC fillers and IO. There is no hole.

That is the answer rather than the obstacle. `gen_cover_flp` places the central block at
`coreWidth x coreHeight` — the sys area itself — so a source covering that area, reduced to this
planar block model, **is** its power distributed over the blocks tiling it, weighted by area:

    q_i = dP * area_i / sum_{i in sys} area_i     for blocks in the sys area,   0 for eblk0..3

The uplift is `max_j (R q)_j`, one matvec against operators already built.

## Result, against the CERTIFIED quantity

`slack = 330.0 - 0.05 - 0.01 - max_j sup_p T_j(p)` at activity span 0.30, `grid128` cell operators.
The `sup_p` column reproduces `CELL_ENDPOINT_RESULT.md` to four decimals on all six points, which is
an independent cross-check of this path rather than a restatement.

| case | `sup_p` peak | slack | dP (W) | NoP only | **established (both, central)** | |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `arch_a`/resnet50 | 322.3144 | 7.6256 | 14.21 | 0.622 | **2.937** | OK |
| `arch_a`/transformer | 325.4231 | 4.5169 | 28.79 | 1.261 | **5.952** | ✗ |
| `arch_b`/resnet50 | 325.4619 | 4.4781 | 23.14 | 0.950 | **4.483** | ✗ by 0.005 |
| `arch_b`/transformer | 330.3018 | **-0.3618** | 41.49 | 1.703 | **8.038** | already refused |
| `arch_c`/resnet50 | 322.3138 | 7.6262 | 13.68 | 0.505 | **2.386** | OK |
| **`arch_c`/transformer** | 325.9070 | 4.0330 | 28.85 | 1.066 | **5.033** | **✗** |

**Two of six survive the established placement.** With the NoP share alone — the part that is
uncommented and running today — five of six survive and the headline holds; it is the DRAM share,
78.82 % of the missing energy, that decides.

## What this does to the headline

**`arch_b -> arch_c` does not reverse.** `arch_b`/transformer is refused either way and by more.

**But `arch_c`/transformer stops being certified.** Its slack is 4.0330 K against a 5.033 K uplift,
so the correct verdict under the established placement is `UNRESOLVED` — and even at the NoP-only
placement its 1.066 K uplift sits inside the 0.2997–1.4332 K cross-solver band, so the margin is not
comfortable there either.

**The `+32.1 %` price is therefore quoted for a destination whose feasibility is not established.**
That is the same conclusion `MISSING_ENERGY_SENSITIVITY.md` reached by proportional placement and
which `NUISANCE_BOUND` overturned by placing the heat on the frame. Reading the generator one line
further restores it, on a placement the generator states rather than one this project assumed.

## The NoC over-count is real, per-architecture, and an order of magnitude too small to matter

Every `io_*` column receives `p_noc / ((cy-1)*2*cx + (cx-1)*2*cy)` and there are `4*cx*cy` of them,
so the trace carries `columns/divisor` times the NoC source. **That factor is a property of the core
grid, not a constant** — the audit's `133.41 %` is one case:

| case | core grid | divisor | columns | over-count | heat returned by fixing it |
| --- | --- | ---: | ---: | ---: | ---: |
| `arch_a`/* | 7x3 | 64 | 84 | **1.3125** | 0.190 / 0.471 K |
| `arch_b`/* | 4x5 | 62 | 80 | **1.2903** | 0.148 / 0.394 K |
| `arch_c`/* | 4x4 | 48 | 64 | **1.3333** | 0.068 / 0.217 K |

The grid is recovered from the block census, which is over-determined — `|io_0|`, `|blockX|`,
`|blockY|` and `|blockXY|` give four equations for two unknowns — so two are solved and the other two
checked, and the axis assignment is resolved by which of `blockX`/`blockY` matches rather than
assumed.

**Correcting it removes heat, so it helps — by 0.068 to 0.471 K.** Against central placements of
2.386 to 8.038 K that is an order of magnitude too small to change the picture, and it does **not**
repair the uniform spreading over `io_*`, which destroys the spatial information and whose sign the
audit calls indeterminate.

## Net, with both sources placed and the over-count removed

| case | slack | placed | `dNoC` | **NET** | |
| --- | ---: | ---: | ---: | ---: | --- |
| `arch_a`/resnet50 | 7.6256 | 2.937 | -0.190 | **2.747** | OK |
| `arch_a`/transformer | 4.5169 | 5.952 | -0.471 | **5.481** | ✗ |
| `arch_b`/resnet50 | 4.4781 | 4.483 | -0.148 | **4.335** | OK — flips on the NoC fix alone |
| `arch_b`/transformer | -0.3618 | 8.038 | -0.394 | **7.644** | already refused |
| `arch_c`/resnet50 | 7.6262 | 2.386 | -0.068 | **2.318** | OK |
| **`arch_c`/transformer** | 4.0330 | 5.033 | -0.217 | **4.816** | **✗** |

**Three of six survive a fully corrected trace**, and the headline's destination is not one of them.

## The over-count was the small NoC defect. The uniform spreading is the large one

Correcting the over-count is a **magnitude** repair and is worth 0.068-0.471 K. The uniform
spreading is a **structure** defect: every `io_*` column receives `p_noc / divisor`, identical for
all of them, so the trace carries the right total and **none** of the spatial information.
`THERMODSE_ENDPOINT_AUDIT.md` calls the direction of that bias indeterminate. The magnitude is not
indeterminate, and it is large.

Redistributing a fixed budget over a fixed support is bounded below by the uniform spread the trace
already does, and above by placing all of it on the single worst-coupled `io_*` block — a greedy
fill, exact and free because the uplift is linear:

| case | slack | central heat (NET) | **spreading upper bracket** |
| --- | ---: | ---: | ---: |
| `arch_a`/resnet50 | 7.6256 | 2.747 | **18.580** |
| `arch_a`/transformer | 4.5169 | 5.481 | **46.445** |
| `arch_b`/resnet50 | 4.4781 | 4.335 | **11.650** |
| `arch_b`/transformer | -0.3618 | 7.644 | **32.652** |
| `arch_c`/resnet50 | 7.6262 | 2.318 | **3.137** |
| `arch_c`/transformer | 4.0330 | 4.816 | **11.512** |

**Every upper bracket exceeds its own slack, on all six points.** The largest is 46.4 K against a
4.5 K margin — an order of magnitude more than the missing DRAM and NoP heat combined.

**What this establishes and what it does not.** The adversarial extreme is physically absurd: NoC
traffic is distributed across a mesh, not concentrated on one IO block, so this is a loose bound and
not an estimate. What it establishes is that **the bracket is wide enough to contain every verdict**,
so no certificate built on this trace is robust to the spreading defect. Closing it needs either the
spatial NoC information restored, or a physically justified bound tighter than adversarial —
**neither of which is a matvec**, which is why this term is the one the other corrections could not
reach.

It also reorders the trace defects. The over-count looked like the NoC problem and is worth
hundredths of a kelvin; the spreading is worth up to tens, and was the one recorded as
"indeterminate" rather than measured.

## The critical share, since the uplift is linear in `dP`

`arch_c`/transformer survives while the central share stays below **80.13 %** of the missing energy,
or **83.74 %** once the NoC over-count is also removed. NoP alone is 21.18 %, so it survives if at
most **79.4 %** of the DRAM heat lands centrally. The generator says 100 %.

## What is NOT established

* **That the generator's intent is physically right.** DRAM is off-die; whether its heat belongs on
  the die footprint at all is a modelling question the audit already refuses to settle
  (`THERMODSE_ENDPOINT_AUDIT.md` §4: "that DRAM is *physically* outside the thermal domain" is listed
  as NOT established). This document establishes what the trace would carry if the omission were
  repaired as written, not what the physics requires.
* **A stacked model.** This is a planar reduction into the same one-layer block model the executed
  HotSpot run already uses — consistent with the pipeline, not an improvement on it.
* **The NoC over-count.** The +33.41 % and its uniform spreading are untouched here.

## The one-line correction to the record

`NUISANCE_BOUND_IS_NOT_AN_ESCAPE.md`'s frame placement is geometrically established and
**thermally empty**: the generator writes zero to every block it identifies. Its "5 of 6 survive"
must not be quoted as the corrected-trace result.
