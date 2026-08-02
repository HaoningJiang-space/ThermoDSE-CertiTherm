"""Move the FEM operator build off the CPU: one assembly, one factorisation, then GEMMs on the GPU.

`docs/FEM_COST_IS_NOT_ON_THE_GPU.md` profiled the reference build. The GPU solve is **0.2 %** of it.
The cost is two CPU loops inside `solve_steady_heat_batch`: it calls `fem.form(...)` once per problem
in `regional_integrals` and once per problem for the convected-power functional, so a 182-problem
operator build performs 364 UFL form compilations and assemblies over a 1.4 M-cell mesh.

Writing a CUDA kernel for the linear solve would optimise 0.2 %. The work that must move is the
per-problem assembly, and the reason it *can* move is the same linearity that makes the whole project
work: every per-problem quantity is a fixed linear functional of the temperature field, so the loop
is a matrix product.

## The identity that makes one assembly serve both ends

Let `M[i, c] = integral over cell c of phi_i dx` -- the mixed mass matrix between P1 (test) and DG0
(trial) -- and let `S[c, r] = 1` when cell `c` belongs to region `r`. Then for a piecewise-constant
volumetric source `q` given per region:

* **right-hand side**  `b_i = integral q phi_i dx = sum_c q_c integral_c phi_i dx = (M S q)_i`
* **region integral**  `integral_r T dx = sum_{c in r} sum_i T_i integral_c phi_i dx = (S^T M^T T)_r`

**The same assembled `M` builds every right-hand side and reads back every region average.** So the
whole build is: assemble the stiffness matrix and `M` once, form `B = M S Q` for all problems at
once, factorise once, solve, and evaluate `S^T M^T Solutions` as a single product on the device where
the solutions already live.

The boundary contribution `h T_inf v ds` does not depend on the problem at all, so it is one vector
added to every column.

## Parity, because a second implementation cannot be its own oracle

This is a second construction of an operator the project already has, so it is not trusted on its own
merits: `--gate` runs the same problems through `solve_steady_heat_batch` and refuses unless the
region-average temperatures agree to `PARITY_TOL_K`. The slow path stays the oracle.

An earlier revision of this docstring promised a `--parity` flag and a capture-driven CLI. **Neither
existed**: the module had no `main`, no `__main__`, and `solve_batch_gpu` had no callers anywhere in
the repository, so the gate it declared itself provisional upon could never have run. Both are
implemented now, and the flag is `--gate`.

## The adjoint row identity

`adjoint_rows` computes rows of the response operator the other way round -- `r_j = (K^-T c_j)^T F`
instead of reading row `j` out of `n` forward impulse columns. The two are the same object by
algebra, so any disagreement is an implementation defect in the dual pairing between the region
average functional and the source map. `--gate` checks every entry.

It also measures the cost claim that motivates lazy row generation, and refutes it: `K` here is
symmetric, so an adjoint solve is one more right-hand side against a factorisation that already
exists. Generating rows lazily cannot avoid the factorisation, only additional triangular solves.

NON-CLAIM diagnostic. Both gates must pass before either path is used for anything quotable.

Usage (on moe-server, from the repo root):
    /data/ziheng/conda_envs/chiplet-fem-0.11/bin/python \\
        research/triangle/robustness/fem_batch_gpu.py --gate [--cells N] [--grid G] [--fem-src P]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "research/triangle/robustness")

PARITY_TOL_K = 1e-9


class Assembled:
    """The device-side operators, assembled and factorised ONCE.

    Held as one object because the forward operator build and the adjoint row gate must share the
    same `K`, the same `M`, the same `S` and above all the same FACTORISATION -- comparing a forward
    row against an adjoint row computed from a separately assembled operator would measure the
    difference between two assemblies rather than the identity under test.
    """

    __slots__ = ("stiffness", "mixed", "selector", "dof_of_cell", "right_hand_sides",
                 "boundary_load", "convection", "power", "volumes", "problem", "timings")

    def __init__(self, **fields):
        for name in self.__slots__:
            setattr(self, name, fields[name])


def assemble_batch(problems, *, gpu_device: int = 0) -> "Assembled":
    """Assemble and factorise once; return the operators, not the answer.

    Mirrors `solve_steady_heat_batch`'s forms exactly -- same bilinear form, same measures, same
    Robin boundaries -- because a parity check between two different weak forms would measure the
    difference in the forms rather than the difference in the implementation.

    Split out from `solve_batch_gpu` so the adjoint row gate can reuse the SAME factorisation. That
    reuse is the point: `K` is symmetric here, so an adjoint solve is another right-hand side against
    a factorisation that already exists, and lazy row generation therefore cannot save the cost that
    dominates the build.
    """

    import cupy as cp
    import cupyx.scipy.sparse as csp
    import dolfinx
    import nvmath.sparse.advanced as nvs
    import ufl
    from dolfinx import fem, mesh
    from dolfinx.fem import petsc as fem_petsc
    from mpi4py import MPI
    from petsc4py import PETSc

    import steady_heat_fem as shf

    problem = problems[0]
    if any(shf._batch_signature(p) != shf._batch_signature(problem) for p in problems[1:]):
        raise ValueError("batched problems may differ only in volumetric power")
    comm = MPI.COMM_WORLD
    if comm.size != 1:
        raise ValueError("this path is serial by construction; cuDSS requires one rank")

    timings = {}
    started = time.perf_counter()
    domain = shf._create_domain(problem, comm, np, mesh)
    topological_dimension = domain.topology.dim
    facet_dimension = topological_dimension - 1
    cell_map = domain.topology.index_map(topological_dimension)
    local_cells = cell_map.size_local
    all_cells = np.arange(local_cells + cell_map.num_ghosts, dtype=np.int32)
    midpoints = mesh.compute_midpoints(domain, topological_dimension, all_cells)
    region_indices = shf._region_indices(problem, midpoints, np)

    coefficient_space = fem.functionspace(domain, ("DG", 0))
    coefficient_dofs = np.asarray(coefficient_space.dofmap.list).reshape(-1)
    conductivity_components = []
    for axis in range(3):
        function = fem.Function(coefficient_space)
        by_region = np.asarray([r.conductivity_xyz[axis] for r in problem.regions])
        function.x.array[coefficient_dofs] = by_region[region_indices]
        conductivity_components.append(function)
    conductivity_tensor = ufl.diag(ufl.as_vector(conductivity_components))

    top_facets = mesh.locate_entities_boundary(
        domain, facet_dimension, lambda x: np.isclose(x[2], problem.size_m[2])
    )
    bottom_facets = mesh.locate_entities_boundary(
        domain, facet_dimension, lambda x: np.isclose(x[2], 0.0)
    )
    entities = np.concatenate((top_facets, bottom_facets))
    values = np.concatenate((
        np.ones(len(top_facets), dtype=np.int32),
        np.full(len(bottom_facets), 2, dtype=np.int32),
    ))
    order = np.argsort(entities)
    tags = mesh.meshtags(domain, facet_dimension, entities[order], values[order])
    ds = ufl.Measure("ds", domain=domain, subdomain_data=tags)
    dx = ufl.Measure("dx", domain=domain)

    space = fem.functionspace(domain, ("Lagrange", 1))
    trial, test = ufl.TrialFunction(space), ufl.TestFunction(space)
    h_top = fem.Constant(domain, dolfinx.default_scalar_type(problem.top_heat_transfer_w_per_m2_k))
    h_bottom = fem.Constant(
        domain, dolfinx.default_scalar_type(problem.bottom_heat_transfer_w_per_m2_k)
    )
    ambient = fem.Constant(domain, dolfinx.default_scalar_type(problem.ambient_temperature_k))
    bilinear = (
        ufl.inner(conductivity_tensor * ufl.grad(trial), ufl.grad(test)) * dx
        + h_top * trial * test * ds(1)
        + h_bottom * trial * test * ds(2)
    )
    stiffness = fem_petsc.assemble_matrix(fem.form(bilinear))
    stiffness.assemble()

    # THE ONE ASSEMBLY THAT SERVES BOTH ENDS: `M[i, c] = integral_c phi_i dx`, P1 test against DG0
    # trial. Every right-hand side is `M S q` and every region integral is `S^T M^T T`, so no form is
    # ever compiled per problem.
    dg_trial = ufl.TrialFunction(coefficient_space)
    mixed = fem_petsc.assemble_matrix(fem.form(dg_trial * test * dx))
    mixed.assemble()
    # The boundary load is identical for every problem: it depends only on the ambient and the film
    # coefficients, neither of which varies across a batch.
    boundary_load = fem_petsc.assemble_vector(
        fem.form(h_top * ambient * test * ds(1) + h_bottom * ambient * test * ds(2))
    )
    boundary_load.ghostUpdate(addv=PETSc.InsertMode.ADD, mode=PETSc.ScatterMode.REVERSE)
    # The convected-power covector, also problem-independent.
    convection = fem_petsc.assemble_vector(
        fem.form(h_top * test * ds(1) + h_bottom * test * ds(2))
    )
    convection.ghostUpdate(addv=PETSc.InsertMode.ADD, mode=PETSc.ScatterMode.REVERSE)
    timings["assembly_s"] = time.perf_counter() - started

    cp.cuda.Device(gpu_device).use()
    started = time.perf_counter()
    indptr, indices, data = stiffness.getValuesCSR()
    rows, columns = stiffness.getSize()
    matrix = csp.csr_matrix(
        (cp.asarray(data), cp.asarray(indices), cp.asarray(indptr)), shape=(rows, columns)
    )
    m_indptr, m_indices, m_data = mixed.getValuesCSR()
    mixed_gpu = csp.csr_matrix(
        (cp.asarray(m_data), cp.asarray(m_indices), cp.asarray(m_indptr)), shape=mixed.getSize()
    )
    # `S` as a sparse cell-to-region selector. Built once; the region of a cell never changes.
    n_regions = len(problem.regions)
    owned = coefficient_dofs[:local_cells]
    selector = csp.csr_matrix(
        (
            cp.ones(local_cells, dtype=cp.float64),
            cp.asarray(region_indices[:local_cells].astype(np.int32)),
            cp.arange(local_cells + 1, dtype=cp.int32),
        ),
        shape=(local_cells, n_regions),
    )
    # Column `p` of `Q` is problem `p`'s volumetric power per region.
    power = cp.asarray(np.asarray(
        [[r.volumetric_power_w_per_m3 for r in p.regions] for p in problems], dtype=float
    ).T)
    # DG0 dof ordering is not cell ordering, so the mixed matrix's columns are indexed by dof.
    dof_of_cell = cp.asarray(owned.astype(np.int32))
    cell_source = selector @ power                       # (cells x problems)
    dof_source = cp.zeros((mixed_gpu.shape[1], power.shape[1]), dtype=cp.float64)
    dof_source[dof_of_cell] = cell_source
    right_hand_sides = mixed_gpu @ dof_source            # (dofs x problems)
    right_hand_sides += cp.asarray(np.asarray(boundary_load.array))[:, None]
    # Volume per region, independent of any solution, so it belongs to the assembly and not to a
    # postprocess that would recompute it per consumer.
    volumes = selector.T @ (mixed_gpu.T @ cp.ones((mixed_gpu.shape[0], 1)))[dof_of_cell]
    timings["host_to_device_s"] = time.perf_counter() - started

    return Assembled(
        stiffness=matrix, mixed=mixed_gpu, selector=selector,
        dof_of_cell=dof_of_cell, right_hand_sides=right_hand_sides,
        boundary_load=np.asarray(boundary_load.array).copy(),
        convection=np.asarray(convection.array).copy(),
        power=power, volumes=volumes, problem=problem, timings=timings,
    )


def factorise_and_solve(built: "Assembled", right_hand_sides):
    """One plan, one factorisation, one multi-RHS solve. Times each separately.

    `nvmath`'s `DirectSolver` takes the right-hand side at construction, so the columns must be known
    before the factorisation exists. That is why the gate CONCATENATES the forward loads and the
    adjoint covectors into a single `b`: it makes "the adjoint reuses the factorisation" a measured
    fact rather than a comment, since there is demonstrably only one.
    """

    import cupy as cp
    import nvmath.sparse.advanced as nvs

    timings = {}
    started = time.perf_counter()
    solver = nvs.DirectSolver(built.stiffness, right_hand_sides)
    solver.plan()
    timings["plan_s"] = time.perf_counter() - started
    started = time.perf_counter()
    solver.factorize()
    timings["factorization_s"] = time.perf_counter() - started
    started = time.perf_counter()
    solutions = solver.solve()
    cp.cuda.runtime.deviceSynchronize()
    timings["solve_s"] = time.perf_counter() - started
    return solutions, timings


def solve_batch_gpu(problems, *, gpu_device: int = 0):
    """`(region_average_temperature_k per problem, diagnostics)` with no per-problem assembly."""

    import cupy as cp

    built = assemble_batch(problems, gpu_device=gpu_device)
    timings, problem = built.timings, built.problem
    solutions, solve_timings = factorise_and_solve(built, built.right_hand_sides)
    timings.update(solve_timings)

    # POSTPROCESS AS TWO PRODUCTS, ON THE DEVICE. This is what used to be 65 % of the run.
    started = time.perf_counter()
    dof_integrals = built.mixed.T @ solutions             # (dg dofs x problems)
    region_integrals = built.selector.T @ dof_integrals[built.dof_of_cell]
    region_average = region_integrals / built.volumes
    convection_gpu = cp.asarray(built.convection)
    convected = convection_gpu @ solutions - float(
        problem.ambient_temperature_k
    ) * float(cp.asnumpy(convection_gpu.sum()))
    generated = cp.asnumpy((built.volumes.ravel()[:, None] * built.power).sum(axis=0))
    timings["postprocess_s"] = time.perf_counter() - started

    # `(problems x regions)`, matching this function's documented contract and
    # `solve_steady_heat_batch`'s one-result-per-problem convention. The device-side product is
    # naturally `(regions x problems)`; returning it untransposed contradicted the docstring, which
    # nothing caught because the function had no callers.
    return (
        cp.asnumpy(region_average).T,
        {
            "generated_power_w": np.asarray(generated, dtype=float),
            "convected_power_w": cp.asnumpy(convected).astype(float),
            "region_volumes_m3": cp.asnumpy(built.volumes.ravel()).astype(float),
            "timings_s": timings,
        },
    )


def adjoint_covectors(built: "Assembled", rows):
    """`c_j` for each requested region, as columns of a dense right-hand side.

    The output functional for region `j` is the volume average `T_j = (S^T M^T u)_j / vol_j`, so its
    covector is `c_j = M S e_j / vol_j` -- routed through the DG0 dof ordering by exactly the same
    `dof_of_cell` indirection the forward load uses, because a mismatch there is precisely the
    false-ACCEPT defect this gate exists to catch.
    """

    import cupy as cp

    indicator = cp.zeros((built.selector.shape[1], len(rows)), dtype=cp.float64)
    for column, region in enumerate(rows):
        indicator[int(region), column] = 1.0
    dof_side = cp.zeros((built.mixed.shape[1], len(rows)), dtype=cp.float64)
    dof_side[built.dof_of_cell] = built.selector @ indicator
    covectors = built.mixed @ dof_side                           # (dofs x rows)
    covectors /= built.volumes.ravel()[cp.asarray([int(r) for r in rows])][None, :]
    return covectors


def adjoint_rows_from_duals(built: "Assembled", duals):
    """`r_j = lambda_j^T F` given the dual fields `lambda_j = K^-T c_j`.

    `K` is symmetric here -- the bilinear form is `inner(k grad u, grad v) dx + h u v ds` -- so the
    dual solve is another right-hand side against the same factorisation, which is the whole
    economic finding. `F`'s column for region `i` is `M S e_i`, the same product transposed, so the
    read-back is one more pair of sparse products and no new form.

    Returns `(rows x regions)` in K per unit VOLUMETRIC source, matching `assemble_batch`'s `power`
    convention. Ambient is excluded: this is the linear part only.
    """

    import cupy as cp

    dof_integrals = built.mixed.T @ duals                        # (dg dofs x rows)
    return cp.asnumpy((built.selector.T @ dof_integrals[built.dof_of_cell]).T)


ADJOINT_TOL_REL = 1e-9


def _synthetic(cells_per_axis: int, grid: int, shf):
    """A tiled layered box with `grid**2` powered die regions.

    Deliberately NOT the real floorplan. The identity under test -- that an adjoint solve returns
    the same response row the forward impulse build does -- is algebraic and geometry-independent,
    so the gate uses the smallest instance that exercises every code path (mixed mass matrix, DG0
    dof reordering, region selector, Robin boundary) and none of the ones it does not test.
    """

    box_x = box_y = 8.0e-3
    z_die, z_spr, z_sink = 1.5e-4, 1.0e-3, 6.9e-3
    total_z = z_die + z_spr + z_sink
    silicon, copper = 130.0, 400.0

    regions, powered = [], []
    step_x, step_y = box_x / grid, box_y / grid
    for iy in range(grid):
        for ix in range(grid):
            regions.append(shf.BoxRegion(
                f"die::b{ix}_{iy}",
                (ix * step_x, iy * step_y, 0.0), ((ix + 1) * step_x, (iy + 1) * step_y, z_die),
                silicon, 0.0,
            ))
            powered.append(len(regions) - 1)
    regions.append(shf.BoxRegion("spreader", (0.0, 0.0, z_die), (box_x, box_y, z_die + z_spr),
                                 copper, 0.0))
    regions.append(shf.BoxRegion("sink", (0.0, 0.0, z_die + z_spr), (box_x, box_y, total_z),
                                 copper, 0.0))

    z_nodes = sorted({0.0, z_die, z_die + z_spr, total_z} | {
        z_die * k / 2 for k in range(3)
    } | {z_die + z_spr * k / 2 for k in range(3)} | {
        z_die + z_spr + z_sink * k / 3 for k in range(4)
    })
    lateral = [i * box_x / cells_per_axis for i in range(cells_per_axis + 1)]
    for edge in (step_x * i for i in range(grid + 1)):
        if not any(abs(edge - v) < 1e-15 for v in lateral):
            raise SystemExit(
                f"region edge {edge!r} is not a mesh node; choose cells_per_axis a multiple of grid"
            )

    def build(volumetric):
        return shf.SteadyHeatBox(
            size_m=(box_x, box_y, total_z),
            cells=(cells_per_axis, cells_per_axis, len(z_nodes) - 1),
            regions=tuple(
                shf.BoxRegion(r.region_id, r.lower_m, r.upper_m, r.conductivity_xyz[0],
                              float(volumetric[i]))
                for i, r in enumerate(regions)
            ),
            ambient_temperature_k=318.15,
            top_heat_transfer_w_per_m2_k=1.0 / (0.1 * 0.06 * 0.06),
            bottom_heat_transfer_w_per_m2_k=0.0,
            x_nodes_m=lateral, y_nodes_m=list(lateral), z_nodes_m=z_nodes,
        )

    volumes = [
        (r.upper_m[0] - r.lower_m[0]) * (r.upper_m[1] - r.lower_m[1])
        * (r.upper_m[2] - r.lower_m[2]) for r in regions
    ]
    return build, powered, volumes, len(regions)


def main() -> None:
    argv = sys.argv[1:]
    if "--gate" not in argv:
        raise SystemExit(
            "usage: fem_batch_gpu.py --gate [--cells N] [--grid G] [--fem-src PATH]\n"
            "  --gate  run BOTH gates: forward parity against the slow oracle, and the adjoint\n"
            "          row identity against the forward impulse build."
        )

    def option(name, default):
        return type(default)(argv[argv.index(name) + 1]) if name in argv else default

    cells = option("--cells", 32)
    grid = option("--grid", 3)
    fem_src = Path(option("--fem-src", str(
        Path(__file__).resolve().parents[3].parent / "ThermoDSE"
        / "research" / "reachable_thermal_envelope" / "src"
    )))
    sys.path.insert(0, str(fem_src))
    import steady_heat_fem as shf

    build, powered, volumes, n_regions = _synthetic(cells, grid, shf)

    zero = [0.0] * n_regions
    problems = [build(zero)]
    for region in powered:
        impulse = list(zero)
        impulse[region] = 1.0 / volumes[region]          # exactly one watt
        problems.append(build(impulse))
    problems = tuple(problems)

    report = {"cells_per_axis": cells, "grid": grid, "powered_regions": len(powered),
              "total_regions": n_regions, "mesh_cells": list(problems[0].cells)}

    # GATE 1 -- forward parity. The slow path is the oracle; this is the check the module's own
    # docstring promised and never implemented.
    started = time.perf_counter()
    fast, diagnostics = solve_batch_gpu(problems)
    report["gpu_seconds"] = time.perf_counter() - started
    started = time.perf_counter()
    oracle = shf.solve_steady_heat_batch(problems)
    report["oracle_seconds"] = time.perf_counter() - started
    by_name = [dict(r.region_average_temperature_k) for r in oracle]
    names = [r.region_id for r in problems[0].regions]
    reference = np.asarray([[row[n] for n in names] for row in by_name], dtype=float)
    parity = float(np.max(np.abs(fast - reference)))
    report["forward_parity_max_abs_k"] = parity
    report["forward_parity_tol_k"] = PARITY_TOL_K
    report["forward_parity_pass"] = bool(np.isfinite(parity) and parity <= PARITY_TOL_K)

    # GATE 2 -- the adjoint row identity, which is the whole point. Forward loads and adjoint
    # covectors go into ONE right-hand side, so there is demonstrably one factorisation for both.
    import cupy as cp

    built = assemble_batch(problems)
    covectors = adjoint_covectors(built, powered)
    combined = cp.concatenate((built.right_hand_sides, covectors), axis=1)
    solutions, combined_timings = factorise_and_solve(built, combined)
    duals = solutions[:, built.right_hand_sides.shape[1]:]

    dof_integrals = built.mixed.T @ solutions[:, : built.right_hand_sides.shape[1]]
    combined_average = cp.asnumpy(
        (built.selector.T @ dof_integrals[built.dof_of_cell]) / built.volumes
    ).T
    forward_rows = np.asarray([
        (combined_average[i + 1] - combined_average[0]) for i in range(len(powered))
    ], dtype=float).T                                     # (regions_out x impulses), K per watt
    adjoint = adjoint_rows_from_duals(built, duals)       # (rows x regions), K per volumetric
    predicted = np.asarray([
        [adjoint[r, region] / volumes[region] for region in powered]
        for r in range(len(powered))
    ], dtype=float)
    observed = forward_rows[powered, :]
    scale = float(np.max(np.abs(observed)))
    delta = float(np.max(np.abs(predicted - observed)))
    report["adjoint_rows_compared"] = len(powered)
    report["adjoint_entries_compared"] = int(predicted.size)
    report["response_scale_k_per_w"] = scale
    report["adjoint_max_abs_k_per_w"] = delta
    report["adjoint_max_rel"] = delta / scale if scale > 0 else float("inf")
    report["adjoint_tol_rel"] = ADJOINT_TOL_REL
    report["adjoint_pass"] = bool(
        np.isfinite(delta) and scale > 0 and delta / scale <= ADJOINT_TOL_REL
    )

    # THE ECONOMIC CLAIM UNDER TEST, measured rather than argued. `forward_only` factorised for the
    # impulse loads alone; `combined` factorised once for the impulse loads AND the adjoint
    # covectors. If lazy row generation saved the dominant cost, these would differ.
    forward_only = diagnostics["timings_s"]
    report["timings_s"] = {"forward_only": forward_only, "combined": combined_timings}
    def _factor(t):
        return float(t.get("plan_s", 0.0) + t.get("factorization_s", 0.0))
    report["factorisation_s_forward_only"] = _factor(forward_only)
    report["factorisation_s_with_adjoint"] = _factor(combined_timings)
    report["solve_s_forward_only"] = float(forward_only.get("solve_s", 0.0))
    report["solve_s_with_adjoint"] = float(combined_timings.get("solve_s", 0.0))
    report["rhs_columns_forward_only"] = int(built.right_hand_sides.shape[1])
    report["rhs_columns_with_adjoint"] = int(combined.shape[1])
    report["factorisation_share_forward_only"] = (
        _factor(forward_only) / max(_factor(forward_only) + float(forward_only.get("solve_s", 0.0)),
                                    1e-30)
    )
    report["adjoint_avoids_factorisation"] = False      # K is symmetric; the factorisation is reused
    report["note"] = (
        "K is symmetric, so an adjoint row is one more right-hand side against the SAME "
        "factorisation. Lazy row generation cannot avoid the factorisation, which is the cost "
        "that dominates; it can only avoid additional triangular solves. Compare "
        "factorisation_share_forward_only against any claimed speedup."
    )

    print(json.dumps(report, indent=1), flush=True)
    if not (report["forward_parity_pass"] and report["adjoint_pass"]):
        raise SystemExit("GATE FAILED")


if __name__ == "__main__":
    main()
