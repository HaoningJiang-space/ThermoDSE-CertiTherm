# The FEM reference verified against an analytical identity, not against another solver

VERIFICATION 2026-08-02. Six development points, n=192, `default` package.

Everything else in this project compares one discrete operator with another. This does not: in steady
state every watt leaves through the sink top, and the convective law fixes the mean top temperature
exactly.

    mean(T_top)  =  T_ambient  +  r_convec * P

Neither HotSpot nor the FEM supplies that relation -- it is conservation plus the boundary
condition.

**What it verifies, stated narrowly because the first version of this document overclaimed.** It
checks the **total injected power**, the **aggregate Robin conductance** (`h` times the top area, as
one product), and the **probe's averaging semantics**. The slab residual additionally checks sink
thickness, sink conductivity and probe depth.

**What it does NOT verify.** Internal geometry, most material constants, block placement, lateral
conductivities, and every spatial error whose area-mean is zero -- which is exactly the class that
moves block and cell peaks. Coherent errors in top area and `h` cancel in it. The energy balance is
not an independent second check either: it exercises essentially the same conservation equation.
`P` here is the assembled load; an injection-scale error common to both sides would escape.

## Result

The measured mean sat consistently **above** the prediction by 3.0e-4 of the rise. That residual is
not error: the probe regions are one sink cell **thick** and DOLFINx reports a volume mean, so the
reading is offset above the face value by the mean gradient through a copper slab of that thickness,

    offset  =  q * slab / (2 k_Cu),      q = P / A_sink,   slab = t_sink / 8 = 0.8625 mm

| case | P (W) | observed residual | predicted offset | ratio |
| --- | --- | --- | --- | --- |
| `arch_a` / resnet50 | 14.215 | 4.257e-03 K | 4.257e-03 K | **1.000** |
| `arch_a` / transformer | 28.806 | 8.627e-03 K | 8.627e-03 K | **1.000** |
| `arch_b` / resnet50 | 23.151 | 6.933e-03 K | 6.933e-03 K | **1.000** |
| `arch_b` / transformer | 41.508 | 1.243e-02 K | 1.243e-02 K | **1.000** |
| `arch_c` / resnet50 | 13.682 | 4.097e-03 K | 4.097e-03 K | **1.000** |
| `arch_c` / transformer | 28.859 | 8.643e-03 K | 8.643e-03 K | **1.000** |

**The identity holds on every point and the residual is explained by a geometric fact.** Two
qualifications that the "1.000" column hides:

* **`1.000` is rounded.** It conceals a discrepancy of up to ~5e-4 relative. The unrounded pairs are
  in the table above; the ratio is computed from them, not reported independently.
* **Six points are not six independent confirmations.** The operator depends on (architecture,
  package), so the six rows are **three** spatial solutions at six power scalings. The identity is
  linear in `P`, so the power axis mostly re-tests one relation. Three geometries is the honest
  count.

The prediction `q * slab / (2 k)` was derived before the residual was inspected, from the probe
geometry alone. It shares `P`, the top area and `k_Cu` with the measurement, so it is not fully
independent of it -- an error common to both would cancel. Breaking that would need the sink
conductivity, slab depth and top area perturbed separately, which has not been done.

## Two details that would have hidden a real error

**Area weights, not cell counts.** The mesh is far finer in the centre -- 5 704 cells there against
560 in each side strip at n=64 -- so weighting the region means by cell count would weight by
*resolution* and produce a mean that is wrong by tens of percent while looking plausible.

**The slab is not the face.** Reading the volume mean as a surface mean would have left a 3.0e-4
relative discrepancy unexplained, and the natural next move -- blaming the solver, refining the mesh
-- would have found nothing, because the mesh was never the problem.

## What it does not verify

Model form. This checks that the FEM solves the problem it was given; whether that problem is the one
HotSpot solves is a separate question, guarded by `_assert_matches_hotspot_inputs` for the materials
and `_assert_convection_is_distributed` for the boundary condition.
