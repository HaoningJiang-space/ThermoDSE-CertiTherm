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
merits: `--parity` runs the same problem through `solve_steady_heat_batch` and refuses unless the
region-average temperatures agree to a declared tolerance. The slow path stays the oracle.

NON-CLAIM diagnostic until the parity gate passes on the design being built.

Usage (on moe-server, from the repo root):
    /data/ziheng/conda_envs/chiplet-fem-0.11/bin/python \\
        research/triangle/robustness/fem_batch_gpu.py <capture.npz> <out.npz> <ledger.json> \\
        [package] [min_lateral_cells] [fem-src-root] [--parity]
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


def solve_batch_gpu(problems, *, gpu_device: int = 0):
    """`(region_average_temperature_k per problem, diagnostics)` with no per-problem assembly.

    Mirrors `solve_steady_heat_batch`'s forms exactly -- same bilinear form, same measures, same
    Robin boundaries -- because a parity check between two different weak forms would measure the
    difference in the forms rather than the difference in the implementation.
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
    timings["host_to_device_s"] = time.perf_counter() - started

    started = time.perf_counter()
    solver = nvs.DirectSolver(matrix)
    solver.plan()
    timings["plan_s"] = time.perf_counter() - started
    started = time.perf_counter()
    solver.factorize()
    timings["factorization_s"] = time.perf_counter() - started
    started = time.perf_counter()
    solutions = solver.solve(right_hand_sides)
    cp.cuda.runtime.deviceSynchronize()
    timings["solve_s"] = time.perf_counter() - started

    # POSTPROCESS AS TWO PRODUCTS, ON THE DEVICE. This is what used to be 65 % of the run.
    started = time.perf_counter()
    dof_integrals = mixed_gpu.T @ solutions              # (dg dofs x problems)
    region_integrals = selector.T @ dof_integrals[dof_of_cell]
    volumes = selector.T @ (mixed_gpu.T @ cp.ones((mixed_gpu.shape[0], 1)))[dof_of_cell]
    region_average = region_integrals / volumes
    convected = cp.asarray(np.asarray(convection.array)) @ solutions - float(
        problem.ambient_temperature_k
    ) * float(cp.asnumpy(cp.asarray(np.asarray(convection.array)).sum()))
    generated = cp.asnumpy((volumes.ravel()[:, None] * power).sum(axis=0))
    timings["postprocess_s"] = time.perf_counter() - started

    return (
        cp.asnumpy(region_average),
        {
            "generated_power_w": np.asarray(generated, dtype=float),
            "convected_power_w": cp.asnumpy(convected).astype(float),
            "region_volumes_m3": cp.asnumpy(volumes.ravel()).astype(float),
            "timings_s": timings,
        },
    )
