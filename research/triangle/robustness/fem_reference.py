"""An INDEPENDENT-SOLVER thermal operator: the same PDE, solved by 3-D FEM instead of HotSpot.

Every band this project has measured so far is *within HotSpot*: `block` against `grid128`,
`grid128` against `grid512`. Grid refinement bounds HotSpot's own discretisation error. It cannot
bound HotSpot's **model-form** error, because every member of that family shares the same structural
assumptions -- and the whole family can agree while being wrong together in the same direction.

3D-ICE cannot supply the independent reference: `ThreeDicePassiveLayerSpec` carries no per-layer
footprint while the chip dimensions are global, so a package whose die, spreader and sink have three
different footprints cannot be represented, and truncating them inserts ~2.57 K of series copper
against a 0.095 K margin. DOLFINx can, because its `BoxRegion` carries explicit three-dimensional
bounds per region.

## Why this is cheap, and it is a property of the physics rather than an engineering trick

Steady conduction with temperature-independent conductivity and Robin cooling is **linear in the
power vector**. So the FEM map is affine, `T = R p + a`, exactly like HotSpot's -- and therefore:

* the operator is built by `n + 1` solves (ambient, then one unit impulse per block), not by
  sampling power maps;
* **the stiffness matrix does not depend on the power map**, so all `n + 1` solves share one
  factorisation. `solve_steady_heat_batch` is built for precisely this and runs it on the GPU
  through cuDSS;
* every bound already written for cross-grid comparison -- `one_sided_containment_bounds`,
  `peak_over_polytope` -- applies **unchanged**, because linearity is a property of the PDE and not
  of HotSpot. The FEM is simply another row-block of the family.

## What has to be matched, and why the first check is energy and not temperature

Any mismatch in geometry, conductivity or boundary condition shows up as a temperature difference
and would be **misattributed to model form**. So this module emits an explicit ledger of every
matched quantity, and validates energy balance first: the solver reports generated and convected
power, and if they disagree the geometry is wrong and no temperature comparison means anything.

Two matching decisions are not mechanical and are recorded as such:

* **Mesh nodes are the union of all block edges.** The material and source discontinuities must lie
  on element boundaries; `_region_indices` assigns each cell to a region by its midpoint, so a mesh
  that cuts across a block boundary silently smears the floorplan.
* **Block power is volumetric over the FULL die thickness.** That matches HotSpot's own lumped
  element, which is what makes the residual a model-form difference rather than a source-placement
  difference. Physically the sources are a thin active layer, so this is a matched-to-HotSpot
  choice, not a matched-to-reality one, and it is a declared ledger line rather than a silent one.

NON-CLAIM diagnostic. Writes one operator NPZ and one ledger JSON.

Usage (on moe-server, from the repo root):
    /data/ziheng/conda_envs/chiplet-fem-0.11/bin/python \\
        research/triangle/robustness/fem_reference.py <capture.npz> <out.npz> <ledger.json> \\
        [package] [min_lateral_cells] [fem-src-root]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.experiments import ROOT, _power_space, _rows
from CertiTherm.frozen_limits import THERMAL_LIMIT_K

# Read from the HotSpot template and materials file rather than restated here, so a package edit
# cannot leave the two solvers describing different stacks.
SILICON_K_W_PER_M_K = 130.0
COPPER_K_W_PER_M_K = 400.0
TIM_K_W_PER_M_K = 4.0
DIE_THICKNESS_M = 0.00015
# HotSpot's stack is a pile of DIFFERENTLY SIZED plates: outside the die footprint at die level, and
# outside the spreader footprint at spreader level, there is simply no material. A FEM box has to be
# tiled -- `_region_indices` raises rather than letting an unowned cell through -- so the void is
# filled with still air. Air is used instead of an arbitrarily tiny conductivity for two reasons: it
# is the physically correct filler, and a 1e-4 W/(m K) filler would put a 4e6 contrast ratio into the
# stiffness matrix for no gain. At 0.026 against silicon's 130 the lateral leak through the void is
# four orders of magnitude below the die path, so the geometry still matches HotSpot's "absent".
AIR_K_W_PER_M_K = 0.026
# Cells per layer in z. The layers span 20 um to 6.9 mm, so a single cell per layer -- which is what
# an unrefined node list gives -- would put the entire 6.9 mm sink in one element and resolve none of
# the spreading this comparison exists to measure.
Z_CELLS_PER_LAYER = {"die": 2, "tim": 1, "spreader": 4, "sink": 8}


def _floorplan_blocks(text: str):
    """`name width height xoffset yoffset`, metres. HotSpot's own floorplan format."""

    blocks = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        name, width, height, x, y = parts[0], *(float(v) for v in parts[1:5])
        blocks.append((name, x, y, x + width, y + height))
    if not blocks:
        raise SystemExit("the floorplan defined no blocks")
    return blocks


# Two block edges closer than this are THE SAME edge. Floorplans are written at 1 um resolution, so
# a 1 nm grid is three orders below any real feature; what it removes is the 1-ulp spread produced by
# computing a mathematically identical edge two ways (`die_x0 + x0` for adjoining blocks). Left in,
# those near-duplicates survive the node set and then bisect to an interval of zero width, which the
# solver rejects as a non-increasing node list -- the symptom is far from the cause.
EDGE_QUANTUM_M = 1.0e-9


def _snap(value: float) -> float:
    """One quantisation, used by BOTH the node list and the region bounds.

    If only the nodes were snapped, a region bound would sit up to a quantum away from the node
    it is matched to by `argmin`, and the geometry and the mesh would each be self-consistent
    while describing slightly different solids.
    """

    return round(float(value) / EDGE_QUANTUM_M) * EDGE_QUANTUM_M


def _frame(box_x: float, box_y: float, inner, z0: float, z1: float):
    """The complement of a centred rectangle, as up to four DISJOINT rectangles.

    `SteadyHeatBox` validates that no two regions share a cell, so the "lay a slab down and let the
    real plates overwrite it" trick that `_region_indices` would have tolerated is rejected before
    the mesh is ever built. The complement of a rectangle in a rectangle is a frame, and a frame
    splits exactly into two full-height side strips plus two strips between them.
    """

    x0, y0, x1, y1 = inner
    pieces = (
        ("west", 0.0, 0.0, x0, box_y),
        ("east", x1, 0.0, box_x, box_y),
        ("south", x0, 0.0, x1, y0),
        ("north", x0, y1, x1, box_y),
    )
    return tuple(
        (name, (a, b, z0), (c, d, z1))
        for name, a, b, c, d in pieces
        if c - a > EDGE_QUANTUM_M and d - b > EDGE_QUANTUM_M
    )


def _axis_nodes(edges, extent: float, minimum_cells: int):
    """Every block edge is a mesh node, then subdivide until the cell count is reached.

    Assigning cells to regions by midpoint means a mesh that cuts across a block boundary puts part
    of one block's power into another. Making the edges nodes removes that failure entirely rather
    than making it small.
    """

    interior = {_snap(e) for e in edges if EDGE_QUANTUM_M < _snap(e) < extent - EDGE_QUANTUM_M}
    nodes = sorted({0.0, float(extent)} | interior)
    while len(nodes) - 1 < minimum_cells:
        refined = [nodes[0]]
        for left, right in zip(nodes, nodes[1:]):
            # Only split what is still wide enough to split. Bisecting an interval already at the
            # quantum would reintroduce exactly the zero-width pair this function exists to avoid.
            if right - left > 2.0 * EDGE_QUANTUM_M:
                refined.append(0.5 * (left + right))
            refined.append(right)
        if len(refined) == len(nodes):
            raise SystemExit(
                f"the node list cannot reach {minimum_cells} cells without intervals below the "
                f"{EDGE_QUANTUM_M} m edge quantum; the floorplan is finer than the mesh model allows"
            )
        nodes = refined
    return tuple(nodes)


def main() -> None:
    _dry_run = os.environ.get("CERTITHERM_FEM_DRYRUN") == "1"
    capture = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    ledger_path = Path(sys.argv[3])
    package_id = sys.argv[4] if len(sys.argv) > 4 else "default"
    lateral_cells = int(sys.argv[5]) if len(sys.argv) > 5 else 64  # MINIMUM cells per lateral axis
    fem_root = Path(
        sys.argv[6] if len(sys.argv) > 6
        else ROOT.parent / "ThermoDSE" / "research" / "reachable_thermal_envelope" / "src"
    )
    sys.path.insert(0, str(fem_root))
    from steady_heat_fem import BoxRegion, SteadyHeatBox, solve_steady_heat_batch

    packages = {row["package_id"]: row for row in _rows(ROOT / "experiments" / "packages.tsv")}
    if package_id not in packages:
        raise SystemExit(f"unknown package {package_id!r}; have {sorted(packages)}")
    package = packages[package_id]
    r_convec = float(package["r_convec"])
    s_sink = float(package["s_sink"])
    t_sink = float(package["t_sink"])
    s_spreader = float(package["s_spreader"])
    t_spreader = float(package["t_spreader"])
    t_interface = float(package["t_interface"])
    ambient_k = float(package["ambient"])

    _space, block_ids, placed, floorplan_text = _power_space(capture)
    blocks = _floorplan_blocks(floorplan_text)
    if [name for name, *_ in blocks] != list(block_ids):
        raise SystemExit(
            "the floorplan block order differs from the capture's; a response matrix whose columns "
            "mean different blocks than the caller believes is undetectable downstream"
        )

    # The stack is centred: the die sits in the middle of the spreader, which sits in the middle of
    # the sink. HotSpot makes the same assumption, so a mismatch here would be a geometry difference
    # rather than a model-form one.
    die_width = max(x1 for _n, _x0, _y0, x1, _y1 in blocks)
    die_height = max(y1 for _n, _x0, _y0, _x1, y1 in blocks)
    if die_width > s_spreader or die_height > s_spreader:
        raise SystemExit("the die does not fit inside the spreader")
    # The die extent is read as the floorplan's bounding box, which is only its footprint if the
    # floorplan starts at the origin. A floorplan offset from zero would silently shift every
    # block relative to the spreader, and the residual would be read as model-form error.
    if min(x0 for _n, x0, *_ in blocks) != 0.0 or min(y0 for _n, _x0, y0, *_ in blocks) != 0.0:
        raise SystemExit("the floorplan does not start at the origin")
    box_x, box_y = s_sink, s_sink
    die_x0, die_y0 = 0.5 * (box_x - die_width), 0.5 * (box_y - die_height)
    spr_x0, spr_y0 = 0.5 * (box_x - s_spreader), 0.5 * (box_y - s_spreader)

    # z from the bottom: die, TIM, spreader, sink. The bottom face is adiabatic because the HotSpot
    # template sets `-model_secondary 0`; matching that is what makes the comparison about the model.
    z_die = (0.0, DIE_THICKNESS_M)
    z_tim = (z_die[1], z_die[1] + t_interface)
    z_spr = (z_tim[1], z_tim[1] + t_spreader)
    z_sink = (z_spr[1], z_spr[1] + t_sink)
    box_z = z_sink[1]

    x_nodes = _axis_nodes(
        [die_x0 + e for _n, x0, _y0, x1, _y1 in blocks for e in (x0, x1)]
        + [spr_x0, spr_x0 + s_spreader],
        box_x, lateral_cells,
    )
    y_nodes = _axis_nodes(
        [die_y0 + e for _n, _x0, y0, _x1, y1 in blocks for e in (y0, y1)]
        + [spr_y0, spr_y0 + s_spreader],
        box_y, lateral_cells,
    )
    z_nodes = []
    for layer, (z0, z1) in (("die", z_die), ("tim", z_tim), ("spreader", z_spr), ("sink", z_sink)):
        count = Z_CELLS_PER_LAYER[layer]
        z_nodes.extend(z0 + (z1 - z0) * step / count for step in range(count))
    z_nodes = tuple(z_nodes) + (box_z,)

    die_volume = DIE_THICKNESS_M
    # THE REGIONS ARE DISJOINT AND TILE THE BOX. `SteadyHeatBox` validates both, so the void is the
    # exact complement of each plate rather than a slab the plates are laid on top of.
    void = tuple(
        BoxRegion(f"void_die_{name}", lower, upper, AIR_K_W_PER_M_K)
        for name, lower, upper in _frame(
            box_x, box_y,
            (_snap(die_x0), _snap(die_y0), _snap(die_x0 + die_width), _snap(die_y0 + die_height)),
            z_die[0], z_die[1],
        )
    ) + tuple(
        # One slab spanning TIM and spreader together: outside the spreader footprint both layers
        # are the same void, so splitting it in z would add regions without adding geometry.
        BoxRegion(f"void_package_{name}", lower, upper, AIR_K_W_PER_M_K)
        for name, lower, upper in _frame(
            box_x, box_y,
            (_snap(spr_x0), _snap(spr_y0), _snap(spr_x0 + s_spreader), _snap(spr_y0 + s_spreader)),
            z_tim[0], z_spr[1],
        )
    )
    passive = (
        BoxRegion("tim", (_snap(spr_x0), _snap(spr_y0), z_tim[0]),
                  (_snap(spr_x0 + s_spreader), _snap(spr_y0 + s_spreader), z_tim[1]), TIM_K_W_PER_M_K),
        BoxRegion("spreader", (_snap(spr_x0), _snap(spr_y0), z_spr[0]),
                  (_snap(spr_x0 + s_spreader), _snap(spr_y0 + s_spreader), z_spr[1]), COPPER_K_W_PER_M_K),
        BoxRegion("sink", (0.0, 0.0, z_sink[0]), (box_x, box_y, z_sink[1]), COPPER_K_W_PER_M_K),
    )

    def problem(power_w: np.ndarray) -> "SteadyHeatBox":
        die_regions = []
        for index, (name, x0, y0, x1, y1) in enumerate(blocks):
            area = (x1 - x0) * (y1 - y0)
            die_regions.append(BoxRegion(
                f"die::{name}",
                (_snap(die_x0 + x0), _snap(die_y0 + y0), z_die[0]),
                (_snap(die_x0 + x1), _snap(die_y0 + y1), z_die[1]),
                SILICON_K_W_PER_M_K,
                float(power_w[index]) / (area * die_volume),
            ))
        return SteadyHeatBox(
            size_m=(box_x, box_y, box_z),
            cells=(len(x_nodes) - 1, len(y_nodes) - 1, len(z_nodes) - 1),
            regions=void + tuple(die_regions) + passive,
            ambient_temperature_k=ambient_k,
            # HotSpot's `r_convec` is a lumped sink-to-ambient resistance over the whole sink top.
            top_heat_transfer_w_per_m2_k=1.0 / (r_convec * s_sink * s_sink),
            bottom_heat_transfer_w_per_m2_k=0.0,
            x_nodes_m=x_nodes, y_nodes_m=y_nodes, z_nodes_m=z_nodes,
        )

    zero = np.zeros(len(blocks))
    # PRE-FLIGHT, and it needs no solver. `_region_indices` refuses a cell owned by no region, which
    # is the right behaviour but only reports it after the mesh is built. The ownership grid is pure
    # arithmetic on the node lists, so the tiling can be checked before any GPU time is spent -- and
    # `steady_heat_fem`'s top level imports only the standard library, so this runs anywhere.
    probe = problem(zero)
    nodes_by_axis = (np.asarray(x_nodes), np.asarray(y_nodes), np.asarray(z_nodes))
    ownership = np.full(probe.cells, -1, dtype=np.int32)
    for index, region in enumerate(probe.regions):
        span = []
        for axis, (low, high) in enumerate(zip(region.lower_m, region.upper_m)):
            axis_nodes = nodes_by_axis[axis]
            span.append((
                int(np.argmin(np.abs(axis_nodes - low))),
                int(np.argmin(np.abs(axis_nodes - high))),
            ))
        ownership[span[0][0]:span[0][1], span[1][0]:span[1][1], span[2][0]:span[2][1]] = index
    unowned = int(np.count_nonzero(ownership < 0))
    if unowned:
        raise SystemExit(
            f"{unowned} of {ownership.size} cells are owned by no region; the FEM box must be tiled "
            "and the solver would refuse after building the mesh"
        )
    owned_die = {
        probe.regions[i].region_id for i in np.unique(ownership) if
        probe.regions[i].region_id.startswith("die::")
    }
    if len(owned_die) != len(blocks):
        raise SystemExit(
            f"only {len(owned_die)} of {len(blocks)} die blocks own any cell; the lateral mesh is "
            "too coarse to resolve the floorplan and those blocks would get no power at all"
        )
    if _dry_run:
        print(json.dumps({
            "dry_run": True, "capture": capture.name,
            "mesh_cells": list(probe.cells), "total_cells": int(ownership.size),
            "die_footprint_m": [die_width, die_height], "blocks": len(blocks),
            "die_blocks_owning_cells": len(owned_die),
            "cells_per_region": {
                probe.regions[i].region_id: int(np.count_nonzero(ownership == i))
                for i in np.unique(ownership) if not probe.regions[i].region_id.startswith("die::")
            },
        }, indent=1), flush=True)
        return

    problems = [problem(zero)]
    for index in range(len(blocks)):
        impulse = zero.copy()
        impulse[index] = 1.0
        problems.append(problem(impulse))

    started = time.monotonic()
    results = solve_steady_heat_batch(tuple(problems), linear_solver="cudss", postprocess="decision")
    elapsed = time.monotonic() - started

    def die_temperatures(result) -> np.ndarray:
        by_region = dict(result.region_average_temperature_k)
        missing = [name for name, *_ in blocks if f"die::{name}" not in by_region]
        if missing:
            raise SystemExit(f"the solver returned no temperature for {len(missing)} die regions")
        return np.asarray([by_region[f"die::{name}"] for name, *_ in blocks], dtype=float)

    ambient_row = die_temperatures(results[0])
    response = np.empty((len(blocks), len(blocks)), dtype=float)
    for index in range(len(blocks)):
        response[:, index] = die_temperatures(results[index + 1]) - ambient_row

    # ENERGY FIRST. A geometry or boundary mismatch shows up as a temperature difference and would
    # be read as model-form error, so the ledger records the residual for every solve and the run
    # refuses on the worst one rather than reporting a band built on a broken stack.
    # The solver already computes this; recomputing it here would create a second definition of
    # one fact, which is a policing problem rather than a check. The zero-power solve is
    # excluded because its relative residual has no denominator.
    worst_balance = float(np.max([r.relative_energy_imbalance for r in results[1:]]))

    ledger = {
        "capture": capture.name, "package": package_id, "blocks": len(blocks),
        "solves": len(problems), "seconds": elapsed,
        "mesh_cells": [len(x_nodes) - 1, len(y_nodes) - 1, len(z_nodes) - 1],
        "z_cells_per_layer": Z_CELLS_PER_LAYER,
        "void_filler_k_w_per_m_k": AIR_K_W_PER_M_K,
        "matched": {
            "die_footprint_m": [die_width, die_height],
            "die_thickness_m": DIE_THICKNESS_M, "die_k_w_per_m_k": SILICON_K_W_PER_M_K,
            "tim_thickness_m": t_interface, "tim_k_w_per_m_k": TIM_K_W_PER_M_K,
            "spreader_side_m": s_spreader, "spreader_thickness_m": t_spreader,
            "sink_side_m": s_sink, "sink_thickness_m": t_sink,
            "spreader_sink_k_w_per_m_k": COPPER_K_W_PER_M_K,
            "ambient_k": ambient_k,
            "r_convec_k_per_w": r_convec,
            "top_h_w_per_m2_k": 1.0 / (r_convec * s_sink * s_sink),
            "bottom_h_w_per_m2_k": 0.0,
        },
        "assumed_equivalent_not_matched": [
            "block power is volumetric over the FULL die thickness, matching HotSpot's lumped "
            "element rather than the physically thin active layer",
            "the die and spreader are centred on the sink, as HotSpot assumes",
            "HotSpot's block model reports a block average; the FEM rows here are region means over "
            "the same block volumes, which is the same functional only because both are averages "
            "over identical supports",
        ],
        "energy_balance_worst_relative_residual": worst_balance,
        "nominal_peak_k": float(np.max(response @ np.asarray(placed, dtype=float) + ambient_row)),
        "thermal_limit_k": THERMAL_LIMIT_K,
    }
    print(json.dumps(ledger, indent=1), flush=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, indent=1))
    if not np.isfinite(worst_balance) or worst_balance > 1e-6:
        raise SystemExit(
            f"energy balance is off by {worst_balance:.3e}; the stack does not conserve power, so "
            "any temperature difference against HotSpot would measure the geometry, not the model"
        )

    np.savez_compressed(
        out_path,
        model_ids=np.asarray(["fem-dolfinx"]),
        response_k_per_w=response[None, :, :],
        ambient_k=ambient_row[None, :],
        limit_k=np.asarray(THERMAL_LIMIT_K),
        provenance_sha256=np.asarray(["fem-dolfinx"]),
        error_k=np.zeros((1, len(blocks))),
        block_ids=np.asarray([name for name, *_ in blocks]),
    )
    print(f"wrote {out_path} in {elapsed:.0f} s", flush=True)


if __name__ == "__main__":
    main()
