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
matched quantity and checks what can be checked before reporting anything.

**Energy balance is a numerical check, not a physics-matching check.** Peer review was right that
a completely wrong but closed geometry conserves energy exactly, so a passing balance says the
solve converged and says nothing about whether the stack is HotSpot's. What guards the matching
is `_assert_matches_hotspot_inputs`, which parses the actual template and materials file and
refuses on any drift, plus the ledger's explicit list of what was ASSUMED equivalent rather than
matched. The remaining assumptions are falsifiable by the sensitivity runs the ledger names.

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
from CertiTherm.paths import TEMPLATE

# RESTATED HERE, AND CHECKED AGAINST THE HOTSPOT INPUTS AT RUN TIME. An earlier revision carried a
# comment claiming these were read from the template and materials file; they were not, so a template
# edit could have moved HotSpot's stack while the FEM's stayed put and the divergence would have been
# reported as model-form error. `_assert_matches_hotspot_inputs` parses the real files and refuses on
# any disagreement, which keeps the constants readable without letting them drift.
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
# THE THREE ASSUMPTIONS THE LEDGER DECLARES "EQUIVALENT, NOT MATCHED", MADE FALSIFIABLE.
# Each is a knob whose default reproduces the matched-to-HotSpot choice, so a sensitivity run is a
# single environment variable and the band's dependence on the assumption is measured rather than
# asserted. Peer review asked how one knows 1.06 K is HotSpot's error and not the FEM setup's; this
# is the answer, and it is only an answer if the runs are actually done.
#
# 1. Source depth. HotSpot's lumped die element takes the block's power over the whole thickness;
#    the physical sources are a thin active layer. A fraction < 1 puts the power in a top slice.
SOURCE_FRACTION = float(os.environ.get("CERTITHERM_FEM_SOURCE_FRACTION", "1.0"))
# 2. Void filler. HotSpot has no material outside each plate; the FEM box must be tiled. Lowering
#    this drives the void towards the adiabatic limit HotSpot actually models.
VOID_K_W_PER_M_K = float(os.environ.get("CERTITHERM_FEM_VOID_K", str(AIR_K_W_PER_M_K)))
# 3. Boundary realisation. `r_convec` is a LUMPED sink-to-ambient resistance; this adapter spreads it
#    as a uniform Robin coefficient over the sink top, which couples differently when the sink is not
#    isothermal. Scaling the sink conductivity up drives it to the isothermal limit, where the
#    distributed and lumped realisations coincide -- so a large scale factor measures the gap.
SINK_K_SCALE = float(os.environ.get("CERTITHERM_FEM_SINK_K_SCALE", "1.0"))
# Cells per layer in z. The layers span 20 um to 6.9 mm, so a single cell per layer -- which is what
# an unrefined node list gives -- would put the entire 6.9 mm sink in one element and resolve none of
# the spreading this comparison exists to measure.
Z_CELLS_PER_LAYER = {"die": 2, "tim": 1, "spreader": 4, "sink": 8}
# The sink is where a high-conductivity sensitivity run loses its energy balance: driving it towards
# the isothermal limit raises the material contrast against the void to 1e6-1e7 and 8 cells stop
# resolving the through-thickness gradient. Refining only the sink is the targeted fix, and it is a
# knob rather than a new default because the default is not the case that needs it.
Z_CELLS_PER_LAYER["sink"] = int(os.environ.get("CERTITHERM_FEM_SINK_Z_CELLS", "8"))


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


def _assert_matches_hotspot_inputs(template_config, materials) -> dict:
    """Parse the real HotSpot inputs and refuse if any constant above has drifted from them."""

    config = {}
    for line in template_config.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line.startswith("-") and len(line.split()) >= 2:
            key, value = line.split()[:2]
            config[key[1:]] = value
    words = [
        w for w in materials.read_text(encoding="utf-8").splitlines()
        if w.strip() and not w.strip().startswith("#")
    ]
    conductivity = {}
    for index, word in enumerate(words):
        if word.strip() in {"silicon", "copper", "aluminum"} and index + 2 < len(words):
            conductivity[word.strip()] = float(words[index + 2])
    expected = {
        "t_chip": DIE_THICKNESS_M, "k_interface": TIM_K_W_PER_M_K,
        "silicon": SILICON_K_W_PER_M_K, "copper": COPPER_K_W_PER_M_K,
    }
    found = {
        "t_chip": float(config["t_chip"]), "k_interface": float(config["k_interface"]),
        "silicon": conductivity["silicon"], "copper": conductivity["copper"],
    }
    drifted = {k: (found[k], v) for k, v in expected.items() if found[k] != v}
    if drifted:
        raise SystemExit(
            f"the HotSpot inputs no longer match this adapter's constants: {drifted}; the two "
            "solvers would describe different stacks and the difference would be read as model form"
        )
    if config.get("model_secondary", "0") != "0":
        raise SystemExit(
            "the HotSpot template enables the secondary heat path, but this adapter models an "
            "adiabatic bottom; the comparison would be between different boundary conditions"
        )
    return found


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

    hotspot_inputs = _assert_matches_hotspot_inputs(
        TEMPLATE / "example.config", TEMPLATE / "example.materials"
    )

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
    # The source slab sits at the TOP of the die, which is where the active layer is. At
    # SOURCE_FRACTION = 1 it is the whole thickness and the geometry is unchanged.
    source_z0 = z_die[1] - SOURCE_FRACTION * DIE_THICKNESS_M

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
    die_layers = (("die", (z_die[0], source_z0)), ("die", (source_z0, z_die[1]))) \
        if SOURCE_FRACTION < 1.0 else (("die", z_die),)
    for layer, (z0, z1) in die_layers + (("tim", z_tim), ("spreader", z_spr), ("sink", z_sink)):
        count = Z_CELLS_PER_LAYER[layer]
        z_nodes.extend(z0 + (z1 - z0) * step / count for step in range(count))
    z_nodes = tuple(z_nodes) + (box_z,)

    die_volume = SOURCE_FRACTION * DIE_THICKNESS_M
    # THE REGIONS ARE DISJOINT AND TILE THE BOX. `SteadyHeatBox` validates both, so the void is the
    # exact complement of each plate rather than a slab the plates are laid on top of.
    die_box = (_snap(die_x0), _snap(die_y0), _snap(die_x0 + die_width), _snap(die_y0 + die_height))
    spr_box = (_snap(spr_x0), _snap(spr_y0), _snap(spr_x0 + s_spreader), _snap(spr_y0 + s_spreader))
    void = tuple(
        # The die AND the TIM share the die footprint, so their voids are one slab. THE TIM FOLLOWS
        # THE DIE, NOT THE SPREADER: `temperature_block.c` builds one interface node per floorplan
        # unit from `flp->units[i].width/height`, so HotSpot's interface layer is exactly the die
        # footprint. Sizing it to the spreader would lay a 20 um k=4 sheet under the whole overhang,
        # changing the spreading path -- and that difference would have been read as HotSpot's
        # model-form error, which is the one thing this comparison must not manufacture.
        BoxRegion(f"void_die_{name}", lower, upper, VOID_K_W_PER_M_K)
        for name, lower, upper in _frame(box_x, box_y, die_box, z_die[0], z_tim[1])
    ) + tuple(
        BoxRegion(f"void_spreader_{name}", lower, upper, VOID_K_W_PER_M_K)
        for name, lower, upper in _frame(box_x, box_y, spr_box, z_spr[0], z_spr[1])
    )
    # The unpowered silicon under the source slab, present only when the source is thinner than the
    # die. At SOURCE_FRACTION = 1 this region has zero thickness and is omitted.
    bulk = (
        (BoxRegion("die_bulk", (die_box[0], die_box[1], z_die[0]),
                   (die_box[2], die_box[3], source_z0), SILICON_K_W_PER_M_K),)
        if SOURCE_FRACTION < 1.0 else ()
    )
    passive = bulk + (
        BoxRegion("tim", (die_box[0], die_box[1], z_tim[0]), (die_box[2], die_box[3], z_tim[1]),
                  TIM_K_W_PER_M_K),
        BoxRegion("spreader", (spr_box[0], spr_box[1], z_spr[0]),
                  (spr_box[2], spr_box[3], z_spr[1]), COPPER_K_W_PER_M_K),
        BoxRegion("sink", (0.0, 0.0, z_sink[0]), (box_x, box_y, z_sink[1]),
                  COPPER_K_W_PER_M_K * SINK_K_SCALE),
    )

    def problem(power_w: np.ndarray) -> "SteadyHeatBox":
        die_regions = []
        for index, (name, x0, y0, x1, y1) in enumerate(blocks):
            area = (x1 - x0) * (y1 - y0)
            die_regions.append(BoxRegion(
                f"die::{name}",
                (_snap(die_x0 + x0), _snap(die_y0 + y0), source_z0),
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
    # What the columns MEAN, checked rather than assumed: each impulse must actually dissipate
    # one watt, and the zero solve must actually sit at ambient. Either failing would leave the
    # response matrix scaled or offset wrongly while every other diagnostic looked healthy.
    worst_impulse_w = float(np.max([abs(r.generated_power_w - 1.0) for r in results[1:]]))
    zero_offset_k = float(np.max(np.abs(ambient_row - ambient_k)))

    ledger = {
        "capture": capture.name, "package": package_id, "blocks": len(blocks),
        "solves": len(problems), "seconds": elapsed,
        "mesh_cells": [len(x_nodes) - 1, len(y_nodes) - 1, len(z_nodes) - 1],
        "z_cells_per_layer": Z_CELLS_PER_LAYER,
        "void_filler_k_w_per_m_k": VOID_K_W_PER_M_K,
        "source_fraction_of_die_thickness": SOURCE_FRACTION,
        "sink_conductivity_scale": SINK_K_SCALE,
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
        "worst_impulse_power_error_w": worst_impulse_w,
        "zero_solve_offset_from_ambient_k": zero_offset_k,
        "hotspot_inputs_checked": hotspot_inputs,
        # The FEM's OWN block-average-versus-continuum gap, which is the independent-solver
        # analogue of the 0.18 K understatement measured inside HotSpot. Reported, not folded in:
        # a certificate over block averages does not imply one over the physical peak.
        "nominal_peak_over_block_averages_k": float(
            np.max(response @ np.asarray(placed, dtype=float) + ambient_row)
        ),
        "impulse_max_anywhere_minus_block_average_k": float(np.max([
            r.maximum_temperature_k - max(v for n, v in r.region_average_temperature_k
                                          if n.startswith("die::"))
            for r in results[1:]
        ])),
        "thermal_limit_k": THERMAL_LIMIT_K,
    }
    # THE GATE RUNS BEFORE THE LEDGER IS WRITTEN. It used to run after, so a solve that FAILED its
    # tolerances still left a normal-looking ledger carrying a plausible `nominal_peak_...` -- and
    # that is not hypothetical: the isothermal-sink sensitivity run failed at 5.34e-06 and its
    # ledger was read as a result. A failed run now writes an explicitly failed receipt.
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    breaches = []
    for name, value, limit in (
        ("energy balance", worst_balance, 1e-6),
        ("impulse power error (W)", worst_impulse_w, 1e-6),
        ("zero-solve offset from ambient (K)", zero_offset_k, 1e-6),
    ):
        # `math.isfinite` first and separately: `NaN > limit` is False, so a single inequality
        # would let a NaN pass the guard AND get recorded.
        if not np.isfinite(value) or value > limit:
            breaches.append(f"{name} is {value:.3e} against a {limit:.0e} tolerance")
    if breaches:
        ledger_path.write_text(json.dumps(
            {"status": "FAILED", "breaches": breaches, "capture": capture.name,
             "note": "no temperature from this run is admissible; the diagnostics are kept so the "
                     "failure can be understood, and every result field is deliberately absent"},
            indent=1))
        raise SystemExit(
            "; ".join(breaches) + " -- the solve is not sound enough for its response matrix to "
            "mean what the columns claim, and the ledger records the failure rather than a number"
        )
    print(json.dumps(ledger, indent=1), flush=True)
    ledger_path.write_text(json.dumps(ledger, indent=1))

    np.savez_compressed(
        out_path,
        model_ids=np.asarray(["fem-dolfinx"]),
        response_k_per_w=response[None, :, :],
        ambient_k=ambient_row[None, :],
        limit_k=np.asarray(THERMAL_LIMIT_K),
        provenance_sha256=np.asarray(["fem-dolfinx"]),
        # NOT ZERO. FEM discretisation, source placement and boundary realisation are all
        # unmeasured here, and a zero would let the containment machinery treat this as a
        # certified reference. NaN is the fail-closed value: every guard in this project checks
        # `isfinite` first, so a consumer that tries to certify against it refuses instead of
        # quietly succeeding.
        error_k=np.full((1, len(blocks)), np.nan),
        block_ids=np.asarray([name for name, *_ in blocks]),
    )
    print(f"wrote {out_path} in {elapsed:.0f} s", flush=True)


if __name__ == "__main__":
    main()
