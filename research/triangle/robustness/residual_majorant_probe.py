"""G-B step 1: is the naive residual majorant vacuous? Measure the factor, do not argue it.

`PEAKCERT_OPERATOR_PREREGISTRATION.md` needs a two-sided pointwise envelope, and registers a
symmetric residual majorant as the primary route: find `z >= 0` with `a(z,v) >= <|r|,v>` for every
`v >= 0`, where `<r,v> = l(v) - a(u_h,v)` is the residual functional. Then `a(z -+ e, v) >= 0` for
`e = u - u_h`, and the weak maximum principle gives `|e| <= z` POINTWISE -- test with `w^-` and use
`a(w, w^-) = -int k |grad w^-|^2 - int h (w^-)^2 <= 0` against coercivity. Both signs at once, which
is what the decision claim needs and what a one-sided supersolution cannot give.

## The analytical objection this probe exists to quantify

`steady_heat_fem` discretises with **P1 Lagrange** and **DG0 coefficients**
(`temperature_space = fem.functionspace(domain, ("Lagrange", 1))`, `("DG", 0)` for `k`). So
`grad u_h` is constant per tetrahedron and `k` is constant per tetrahedron, hence

    div(k grad u_h) = 0   exactly, inside every element.

Integrating the stiffness term by parts elementwise therefore leaves **no element-interior
cancellation at all**:

    <r, v> = int f v  -  int_F [[k d_n u_h]] v  -  int_{Gamma_R} (k d_n u_h + h (u_h - u_amb)) v

The volume residual is `f` -- **the entire source density**, not a small quantity. Power is
non-negative, so `|f| = f`, and the majorant problem `a(z,v) = <|r|,v>` therefore carries **the same
volume data as the original problem**. That forces `z` to be of the order of the temperature rise
itself, and a certificate reading "the temperature is within +- the whole rise" certifies nothing.

**This is the standard reason the guaranteed-bound literature equilibrates the flux** -- construct
`sigma_h` in `H(div)` with `div sigma_h = -f` exactly so the volume term is annihilated and only the
small mismatch `sigma_h + k grad u_h` survives. That route gives a guaranteed ENERGY-norm bound;
converting it to `L^infinity` is a separate problem, because `H^1` does not embed in `L^infinity` in
three dimensions.

So the argument above predicts a vacuity factor near 1. **Predicting it is not measuring it**, and a
factor materially below 1 would mean the face and Robin terms cancel more of the volume term than
this reasoning expects, which would change the route. This probe measures the factor.

## What is computed

For a synthetic layered box with `grid**2` powered die regions over spreader and sink, one unit
impulse at a time:

* `u_h` -- the P1 solution;
* `z_h` -- the P1 solution of `a(z,v) = <|r|,v>` with `|r|` assembled as `f dx` plus the absolute
  interior flux jump on `dS` plus the absolute Robin residual on `ds`;
* `vacuity = max(z_h) / max(u_h - ambient)`.

**`z_h` is NOT a certificate.** It is the discrete solution of the majorant problem, so it is an
estimate of the size of `z`, not a verified bound on it -- certifying `z` itself would need the same
machinery again. That is exactly the point: if even the *optimistic discrete estimate* of the
majorant is the size of the signal, the route is dead without equilibration, and no amount of
verification effort on top would rescue it.

NON-CLAIM diagnostic. Prints a table; writes nothing.

Usage (moe-server only -- FEM is claim-adjacent native work):

    /data/ziheng/conda_envs/chiplet-fem-0.11/bin/python \\
        research/triangle/robustness/residual_majorant_probe.py [--cells N] [--grid G] [--fem-src P]
"""

from __future__ import annotations

import sys
from pathlib import Path


def _option(argv, name, default):
    return type(default)(argv[argv.index(name) + 1]) if name in argv else default


def main() -> None:
    argv = sys.argv[1:]
    cells = _option(argv, "--cells", 24)
    grid = _option(argv, "--grid", 3)
    # `--no-faces` drops the interior-jump term, which is the BEST CASE an equilibrated flux could
    # achieve for it: a normal-trace-continuous sigma_h annihilates the face measures entirely. What
    # survives is the volume term, and the structural claim under test is that it cannot be removed --
    # div(sigma_h + k grad u_h) = -f for ANY H(div) reconstruction, so f reappears whatever is done.
    no_faces = "--no-faces" in argv
    # THE ELEMENT FAMILY IS THE VARIABLE NOW. With P1 over DG0 coefficients `grad u_h` and `k` are
    # both constant per tetrahedron, so `div(k grad u_h) = 0` exactly and the volume residual is the
    # SOURCE ITSELF -- which is why the equilibrated factor measured exactly 1.0012 and certified
    # nothing. Degree >= 2 is the only way that term becomes a genuine small quantity, so this
    # option is the falsification of the whole pointwise route rather than a tuning knob.
    degree = _option(argv, "--degree", 1)
    fem_src = Path(_option(argv, "--fem-src", str(
        Path("/data/ziheng/ThermoDSE/research/reachable_thermal_envelope/src")
    )))
    if cells % grid:
        raise SystemExit(f"--cells {cells} must be a multiple of --grid {grid}")
    sys.path.insert(0, str(fem_src))

    import numpy as np
    import ufl
    from dolfinx import fem, mesh as dmesh
    from dolfinx.fem.petsc import LinearProblem
    from mpi4py import MPI

    # ---- geometry: the same layered stack the adjoint gate uses, so the two are comparable ----
    box_xy = 8.0e-3
    z_die, z_spr, z_sink = 1.5e-4, 1.0e-3, 6.9e-3
    total_z = z_die + z_spr + z_sink
    k_si, k_cu = 130.0, 400.0
    ambient = 318.15
    h_top = 1.0 / (0.1 * 0.06 * 0.06)          # the distributed Robin coefficient, as HotSpot assembles it

    # `create_box` grades z UNIFORMLY, and the layers span 150 um to 6.9 mm. A z-count chosen for the
    # sink puts the entire die inside the first cell, no midpoint lands in it, the source becomes
    # identically zero and the probe prints a table of zeros -- which is what the first run did. The
    # count is therefore derived from the THINNEST layer and the outcome is asserted below, not hoped.
    nz = int(np.ceil(total_z / (z_die / 2)))
    domain = dmesh.create_box(
        MPI.COMM_WORLD,
        [np.zeros(3), np.array([box_xy, box_xy, total_z])],
        [cells, cells, nz],
        cell_type=dmesh.CellType.tetrahedron,
    )

    V = fem.functionspace(domain, ("Lagrange", degree))
    Q = fem.functionspace(domain, ("DG", 0))

    midpoints = dmesh.compute_midpoints(
        domain, domain.topology.dim,
        np.arange(domain.topology.index_map(domain.topology.dim).size_local, dtype=np.int32),
    )
    zc = midpoints[:, 2]

    if not np.any(zc < z_die):
        raise SystemExit(
            f"no cell midpoint lies in the {z_die * 1e6:.0f} um die at nz={nz}: the source would be "
            "identically zero and every number below would be a silent zero"
        )

    kappa = fem.Function(Q)
    kappa.x.array[:] = np.where(zc < z_die, k_si, k_cu)

    # powered die regions: a grid x grid tiling of the die layer
    step = box_xy / grid
    ix = np.clip((midpoints[:, 0] / step).astype(int), 0, grid - 1)
    iy = np.clip((midpoints[:, 1] / step).astype(int), 0, grid - 1)
    in_die = zc < z_die
    region = np.where(in_die, iy * grid + ix, -1)

    # Robin on the top face only
    def top(x):
        return np.isclose(x[2], total_z)

    facets = dmesh.locate_entities_boundary(domain, domain.topology.dim - 1, top)
    tags = dmesh.meshtags(
        domain, domain.topology.dim - 1, np.sort(facets),
        np.full(len(facets), 1, dtype=np.int32),
    )
    ds = ufl.Measure("ds", domain=domain, subdomain_data=tags)
    dS, dx = ufl.dS, ufl.dx
    n = ufl.FacetNormal(domain)

    u, v = ufl.TrialFunction(V), ufl.TestFunction(V)
    bilinear = (
        ufl.inner(kappa * ufl.grad(u), ufl.grad(v)) * dx
        + h_top * ufl.inner(u, v) * ds(1)
    )

    print(f"cells/axis={cells} grid={grid} degree={degree}  dofs={V.dofmap.index_map.size_global}  "
          f"contrast={k_cu / k_si:.3g} (NO void: favourable)  faces={'DROPPED' if no_faces else 'included'}")
    print(f"{'source':>8s} {'max rise (K)':>14s} {'max z_h (K)':>14s} {'vacuity':>10s} "
          f"{'equilibrated':>12s} {'volume':>10s} {'robin':>9s} {'face':>9s}")

    factors, equilibrated_factors = [], []
    volume_factors, robin_factors, face_factors = [], [], []
    for src in range(grid * grid):
        source = fem.Function(Q)
        volume = float(step * step * z_die)
        source.x.array[:] = np.where(region == src, 1.0 / volume, 0.0)   # one watt, spread over the block
        injected = fem.assemble_scalar(fem.form(source * dx))
        if not np.isclose(injected, 1.0, rtol=2e-2):
            raise SystemExit(
                f"source {src} integrates to {injected:.6g} W, not 1 W: the block does not tile the "
                "cells it is assigned from, so every ratio below would be scaled by an unknown factor"
            )

        forward = LinearProblem(
            bilinear,
            source * v * dx + h_top * ambient * v * ds(1),
            petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
            petsc_options_prefix=f"fwd{src}_",
        )
        uh = forward.solve()

        # |r| as a measure: volume source, absolute interior flux jump, absolute Robin residual.
        # VOLUME RESIDUAL, honestly. `r_vol = f + div(k grad u_h)`. At degree 1 the divergence is
        # identically zero and this reduces to `f`; at degree >= 2 it is a real cancellation, and
        # whether it cancels ENOUGH is the question this probe exists to answer.
        volume_residual = source + ufl.div(kappa * ufl.grad(uh)) if degree > 1 else source
        flux_jump = ufl.jump(kappa * ufl.grad(uh), n)
        robin_residual = ufl.dot(kappa * ufl.grad(uh), n) + h_top * (uh - ambient)
        majorant_load = (
            abs(volume_residual) * v * dx
            + abs(flux_jump) * ufl.avg(v) * dS
            + abs(robin_residual) * v * ds(1)
        )
        majorant = LinearProblem(
            bilinear,                       # THE SAME operator; only the load differs
            majorant_load,
            petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
            petsc_options_prefix=f"maj{src}_",
        )
        zh = majorant.solve()

        # WHAT EQUILIBRATION WOULD BUY, measured before implementing it. An equilibrated flux
        # reconstruction (Braess-Schoberl, Ern-Vohralik) builds an H(div)-conforming flux whose
        # interior jumps are IDENTICALLY ZERO, so the `dS` term vanishes and nothing else changes.
        # Dropping that one term is therefore an exact model of equilibration's BEST CASE -- it
        # cannot do better, because the volume and Robin terms are untouched by it.
        #
        # This is the gate that decides whether equilibration is worth implementing at all. The
        # naive factor is already measured at 21-64x; if the volume-only factor is still above 1,
        # the face term was not the whole problem and the pointwise route dies here instead of
        # after a week of patch-problem code.
        equilibrated_load = abs(volume_residual) * v * dx + abs(robin_residual) * v * ds(1)
        equilibrated = LinearProblem(
            bilinear,
            equilibrated_load,
            petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
            petsc_options_prefix=f"eq{src}_",
        )
        zq = equilibrated.solve()

        # WHICH TERM SETS THE RATE, once the faces are gone. The equilibrated load has NO `dS` term,
        # so attributing its convergence to the face term -- as an earlier revision of
        # `GB1_THE_NAIVE_MAJORANT_IS_VACUOUS.md` did -- is simply wrong. The two surviving terms are
        # separated here and solved independently against the same operator, because "the face term
        # is O(1)" and "removing it leaves something that converges slowly" are different claims and
        # only one of them was measured.
        zv = LinearProblem(
            bilinear, abs(volume_residual) * v * dx,
            petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
            petsc_options_prefix=f"vol{src}_",
        ).solve()
        zr = LinearProblem(
            bilinear, abs(robin_residual) * v * ds(1),
            petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
            petsc_options_prefix=f"rob{src}_",
        ).solve()
        zf = LinearProblem(
            bilinear, abs(flux_jump) * ufl.avg(v) * dS,
            petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
            petsc_options_prefix=f"fac{src}_",
        ).solve()

        rise = float(np.max(uh.x.array) - ambient)
        zmax = float(np.max(zh.x.array))
        qmax = float(np.max(zq.x.array))
        factors.append(zmax / rise if rise > 0 else float("inf"))
        equilibrated_factors.append(qmax / rise if rise > 0 else float("inf"))
        volume_factors.append(float(np.max(zv.x.array)) / rise if rise > 0 else float("inf"))
        robin_factors.append(float(np.max(zr.x.array)) / rise if rise > 0 else float("inf"))
        face_factors.append(float(np.max(zf.x.array)) / rise if rise > 0 else float("inf"))
        print(f"{src:8d} {rise:14.6f} {zmax:14.6f} {factors[-1]:10.4f} {equilibrated_factors[-1]:12.4f}"
              f" {volume_factors[-1]:10.4f} {robin_factors[-1]:9.4f} {face_factors[-1]:9.4f}")

    def _stats(values):
        return min(values), sorted(values)[len(values) // 2], max(values)

    naive = _stats(factors)
    equil = _stats(equilibrated_factors)
    print()
    print(f"NAIVE          min={naive[0]:.4f}  median={naive[1]:.4f}  max={naive[2]:.4f}")
    for name, values in (("VOLUME only", volume_factors), ("ROBIN only", robin_factors),
                         ("FACE only", face_factors)):
        lo, mid, hi = _stats(values)
        print(f"{name:<14s} min={lo:.4f}  median={mid:.4f}  max={hi:.4f}")
    print(f"EQUILIBRATED   min={equil[0]:.4f}  median={equil[1]:.4f}  max={equil[2]:.4f}   "
          f"(best case: the dS term removed exactly)")
    print(f"the face term is {naive[1] / equil[1]:.1f}x of the rest, at the median")
    print()
    print("A factor near or above 1 means the majorant is the size of the signal. The naive route is")
    print("already known vacuous at 21-64x; the EQUILIBRATED column is the decision. Above 1 kills the")
    print("pointwise route now; near or below 1 makes a Braess-Schoberl reconstruction worth writing.")


if __name__ == "__main__":
    main()
