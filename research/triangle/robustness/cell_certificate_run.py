"""Build a CELL-level operator and certify on it, under a named endpoint.

Every certificate this project issued was `max over BLOCKS of the block-average temperature`, and
the 330 K limit is not about block averages. `CertiTherm/cell_certificate.py` states the endpoints
and does the arithmetic; this driver builds the rows it needs.

## Cost, and why it is the same cost as before

One HotSpot solve per block per grid -- exactly what the block operator already costs. The impulse
responses ARE the same runs; `-grid_steady_file` only asks for more of each run's output. What
changes is memory and the greedy, and the greedy is vectorised (`_extreme_rows`), so 16 384 or
262 144 rows cost one sort rather than one Python loop.

## The endpoint these rows carry

`_cell_field` reads **layer 0 only**, which is the die. So every row here is a die cell and the
operator is labelled `tool_compatible` throughout -- the endpoint that makes this project's verdicts
comparable with ThermoDSE's own `find_hotpoint`, minus its scan over passive layers. A stacked
package would need more layers and a richer label vector; this one does not.

NON-CLAIM diagnostic. Builds a cell operator, saves it, and prints the certificate.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/cell_certificate_run.py <capture.npz> \\
        <workspace> <out.json> [model] [span]
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cell_certificate import certify_cells
from CertiTherm.cross_grid_bound import _extreme_rows
from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K
from CertiTherm.measurements import activity_bounded_power_space
from CertiTherm.thermodse_bridge import write_hotspot_config as _configure
from CertiTherm.experiments import ROOT, _power_space, _rows
from CertiTherm.paths import HOTSPOT, TEMPLATE

MARGIN_K = 0.05


def _cell_field(config: Path, floorplan: Path, blocks, power, model_id: str, work: Path, tag: str):
    """Layer-0 cell temperatures for one power map, via `-grid_steady_file`.

    Layer 0 is the die. The block-averaged `-steady_file` is requested too and discarded, because
    HotSpot writes it regardless and pointing it at a scratch path keeps the run identical to the
    one the operator build performs.
    """

    work.mkdir(parents=True, exist_ok=True)
    ptrace = work / f"{tag}.ptrace"
    ptrace.write_text(
        "\t".join(blocks) + "\n" + "\t".join(f"{v:.12g}" for v in power) + "\n", encoding="utf-8"
    )
    size = int(model_id[4:].split("-")[0])
    grid = work / f"{tag}.grid"
    result = subprocess.run(
        [
            str(HOTSPOT), "-c", str(config), "-f", str(floorplan), "-p", str(ptrace),
            "-materials_file", str(TEMPLATE / "example.materials"), "-model_type", "grid",
            "-steady_file", str(work / f"{tag}.steady"), "-grid_steady_file", str(grid),
            "-grid_rows", str(size), "-grid_cols", str(size), "-grid_map_mode", "avg",
        ],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"HotSpot {model_id} failed: {result.stderr[-400:]}")
    values, layer = [], None
    for line in grid.read_text(encoding="utf-8").splitlines():
        if line.startswith("Layer"):
            layer = int(line.split()[1].rstrip(":"))
        elif layer == 0:
            parts = line.split()
            if len(parts) >= 2:
                values.append(float(parts[1]))
    field = np.asarray(values, dtype=float)
    if field.size != size * size:
        raise RuntimeError(f"{model_id} returned {field.size} layer-0 cells, expected {size * size}")
    return field


def cell_operator(config, floorplan, blocks, model_id, work):
    """Response matrix over CELLS: one impulse per block, exactly as the block operator costs."""

    size = int(model_id[4:].split("-")[0])
    zero = np.zeros(len(blocks))
    ambient = _cell_field(config, floorplan, blocks, zero, model_id, work, f"{model_id}-amb")
    response = np.empty((size * size, len(blocks)), dtype=float)
    for index in range(len(blocks)):
        impulse = zero.copy()
        impulse[index] = 1.0
        field = _cell_field(config, floorplan, blocks, impulse, model_id, work, f"{model_id}-{index}")
        response[:, index] = field - ambient
        if index % 25 == 0:
            print(f"  {model_id}: impulse {index}/{len(blocks)}", flush=True)
    return response, ambient


def main() -> None:
    capture = Path(sys.argv[1])
    work = Path(sys.argv[2])
    out_path = Path(sys.argv[3])
    model_id = sys.argv[4] if len(sys.argv) > 4 else "grid128-avg"
    span = float(sys.argv[5]) if len(sys.argv) > 5 else 0.30

    _space, blocks, placed, floorplan_text = _power_space(capture)
    work.mkdir(parents=True, exist_ok=True)
    floorplan = work / "floorplan.flp"
    floorplan.write_text(floorplan_text, encoding="utf-8")
    config = work / "package.config"
    packages = {row["package_id"]: row for row in _rows(ROOT / "experiments" / "packages.tsv")}
    _configure(TEMPLATE / "example.config", config, packages["default"])

    power = np.asarray(placed, dtype=float)
    total = float(np.sum(power))
    started = time.monotonic()
    rows, ambient = cell_operator(config, floorplan, blocks, model_id, work)
    elapsed = time.monotonic() - started
    operator = out_path.with_suffix(".npz")
    np.savez_compressed(
        operator, model_ids=np.asarray([model_id]), response_k_per_w=rows[None, :, :],
        ambient_k=ambient[None, :], block_ids=np.asarray(blocks),
        # Layer 0 only, so every row is a die cell.
        cell_endpoint=np.asarray(["tool_compatible"] * rows.shape[0]),
    )

    space = activity_bounded_power_space(blocks, power, activity_span=span)
    cell = certify_cells(
        rows, ambient, ["tool_compatible"] * rows.shape[0], space, total,
        endpoint="tool_compatible", limit_k=THERMAL_LIMIT_K, margin_k=MARGIN_K,
        linearisation_k=MODEL_ERROR_LIMIT_K,
    )
    # The same certificate on BLOCK-average rows, which is what every earlier verdict used. The gap
    # between the two is the quantity peer review kept asking for and it is reported, not folded in.
    block_peak = float(np.max(_extreme_rows(
        _block_average(rows, blocks, floorplan_text), np.asarray(space.lower_w, dtype=float),
        np.asarray(space.upper_w, dtype=float), total,
    ) + _block_average(ambient[None, :], blocks, floorplan_text)[0]))
    payload = {
        "capture": capture.name, "model": model_id, "span": span,
        "blocks": len(blocks), "cells": int(rows.shape[0]), "operator_seconds": elapsed,
        "endpoint": cell.endpoint,
        "sup_peak_over_cells_k": cell.sup_peak_k,
        "argmax_cell": cell.argmax_cell,
        "slack_k": cell.slack_k,
        "certified": cell.certified,
        "sup_peak_over_block_averages_k": block_peak,
        "cell_minus_block_k": cell.sup_peak_k - block_peak,
    }
    print(json.dumps(payload, indent=1), flush=True)
    out_path.write_text(json.dumps(payload, indent=1))


def _block_average(rows, blocks, floorplan_text):
    """Area-weighted mean of the cell rows over each block, i.e. what `gridN-avg` reports.

    Recomputed here rather than read from the block operator so that the two endpoints come from the
    SAME solve. Comparing a cell peak from one run with a block average from another would measure
    the difference between the runs.
    """

    size = int(round(math.sqrt(rows.shape[0])))
    geometry = {}
    for line in floorplan_text.splitlines():
        parts = line.split("#")[0].split()
        if len(parts) >= 5:
            geometry[parts[0]] = tuple(float(v) for v in parts[1:5])
    extent_x = max(x + w for w, _h, x, _y in geometry.values())
    extent_y = max(y + h for _w, h, _x, y in geometry.values())
    centres_x = (np.arange(size) + 0.5) * extent_x / size
    centres_y = (np.arange(size) + 0.5) * extent_y / size
    grid_x, grid_y = np.meshgrid(centres_x, centres_y, indexing="xy")
    flat_x, flat_y = grid_x.ravel(), grid_y.ravel()
    out = np.empty((len(blocks), rows.shape[1]), dtype=float)
    for index, name in enumerate(blocks):
        w, h, x, y = geometry[name]
        inside = (flat_x >= x) & (flat_x < x + w) & (flat_y >= y) & (flat_y < y + h)
        if not inside.any():
            raise SystemExit(f"block {name} covers no grid cell centre at {size}x{size}")
        out[index] = rows[inside].mean(axis=0)
    return out


if __name__ == "__main__":
    main()
