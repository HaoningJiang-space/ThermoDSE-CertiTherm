# The cell endpoint breaks the tightest point, and the conclusion survives it

> **The certified object is `max_j sup_p T_j(p)` where `T_j` is a HotSpot CELL AVERAGE.** That is a
> discrete, tool-compatible quantity and **not** a bound on the pointwise temperature inside a
> cell; closing that needs a one-sided within-cell bound (a-posteriori estimate or a
> comparison-principle supersolution), which does not exist yet. Nothing here is a junction-limit
> certificate.

RESULT 2026-08-02. Development split, `grid128` cell operators (16 384 die cells each), activity span
0.30, endpoint `tool_compatible` (die cells only). HotSpot alone -- **no FEM model-form band folded
in**, so this is strictly the endpoint change.

`limit - margin - linearisation = 330.0 - 0.05 - 0.01 = 329.94 K`.

| case | `worst_case_max_cell_average` | `sup_p` over the exact block projection | gap | slack | verdict |
| --- | --- | --- | --- | --- | --- |
| `arch_b` / resnet50 | 325.4619 K | 325.0550 K | +0.4068 | **+4.4781** | CERTIFIED |
| **`arch_b` / transformer** | **330.3018 K** | 329.6787 K | **+0.6230** | **-0.3618** | **REFUSED** |
| `arch_c` / resnet50 | 322.3138 K | 322.0693 K | +0.2445 | +7.6262 | CERTIFIED |
| `arch_c` / transformer | 325.9070 K | 325.4730 K | +0.4340 | +4.0330 | CERTIFIED |

`arch_a` is still building.

## What it settles

**The provisional warning was right.** `arch_b`/transformer had 0.31 K of slack on block-average
rows; the cell endpoint takes 0.62 K and refuses it. Its cell peak is 330.30 K, **above the limit
itself**, before any error budget is applied at all.

**The cell-versus-block gap is +0.24 to +0.62 K**, which matches the +0.21 median / +0.76 max
measured independently across 64 archive designs. Nothing here is a surprise in magnitude; what is
new is that the magnitude is exactly enough to decide a point.

## What it does NOT overturn

The frontier conclusion **survives and is strengthened**. On block rows, "transformer loses
`arch_b`" required the FEM model-form band to be folded in. **At the cell endpoint it holds without
any band at all**, and `arch_c`/transformer still certifies with +4.03 K of slack. So the
`arch_b -> arch_c` switch and its **+32.1 %** EDYP price no longer rest on the block-average
assumption -- which was the reason they were marked provisional.

## The block projection here is not `gridN-avg`

`_block_average` uses **area-weighted cell overlap**, which is the exact `L^2` projection. HotSpot's
own `gridN-avg` uses cell membership, and `CertiTherm/reciprocity.py` measures that mapping breaking
thermal reciprocity by 2.5-12 %. So the "block" column above is what `gridN-avg` approximates, not
what it reports, and the two differ by that artefact. An earlier version of this driver sampled cell
centres and died on `obuf_0 covers no grid cell centre at 128x128` -- correctly, because a
centre-sampled average is undefined for a block smaller than a cell, but only after paying for 227
impulse solves.

## Scope

* Four of six development points; `arch_a` pending.
* `grid128` cells, not `grid512`. The refinement tail measured on block rows was 0.05-0.34 K and the
  cell-level tail is not measured here.
* `tool_compatible` only. On this single-die package it coincides with `active_silicon`; on a stack
  it would not.
* **No model-form band.** Adding the FEM comparison would push every slack down further, and the FEM
  band is itself currently an upper bound rather than a measurement, because a boundary-realisation
  term of about -0.73 K sits unseparated inside it.
