# The FEM reference verified against an analytical identity, not against another solver

VERIFICATION 2026-08-02. Six development points, n=192, `default` package.

Everything else in this project compares one discrete operator with another. This does not: in steady
state every watt leaves through the sink top, and the convective law fixes the mean top temperature
exactly.

    mean(T_top)  =  T_ambient  +  r_convec * P

Neither HotSpot nor the FEM supplies that relation -- it is conservation plus the boundary condition
-- so it tests **the geometry, the materials, the boundary condition, the power injection and the
region reporting simultaneously**. Any one of them wrong and the identity breaks.

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

**The identity holds to solver precision on every point, and the whole residual is explained by a
geometric fact predicted in advance.** The energy balance independently sits at 6e-8, so nothing here
is a convergence artefact.

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
