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
from concurrent.futures import ThreadPoolExecutor
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


def _gpu_backend_from_env():
    """The GPU HotSpot backend when `CERTITHERM_GPU_HOTSPOT` names its two binaries, else None.

    Same gate `CertiTherm/hotspot.py` uses, read here rather than threaded through every caller,
    because this driver's only decision is CPU-loop versus one batched solve and the answer is an
    environment fact, not an argument.
    """

    import os

    exporter = os.environ.get("CERTITHERM_GPU_HOTSPOT_EXPORTER")
    solver = os.environ.get("CERTITHERM_GPU_HOTSPOT_SOLVER")
    if not (exporter and solver):
        return None
    from CertiTherm.gpu_hotspot import GpuHotSpotBackend

    return GpuHotSpotBackend(exporter=Path(exporter), solver=Path(solver),
                             device=int(os.environ.get("CUDA_VISIBLE_DEVICES", "0").split(",")[0]))


def cell_operator(config, floorplan, blocks, model_id, work, workers: int = 1):
    """Response matrix over CELLS: one impulse per block, exactly as the block operator costs.

    THE IMPULSE LOOP IS EMBARRASSINGLY PARALLEL AND WAS RUNNING ON ONE CORE OF FIFTY-TWO. Each
    impulse is an independent invocation of the pinned HotSpot binary with its own `-p`,
    `-steady_file` and `-grid_steady_file` paths, tagged by index, so no two calls touch a shared
    file and none shares process state. HotSpot itself is single-threaded C with a ~6 MB resident
    set. Raising `workers` is therefore a SCHEDULING change and nothing else -- the binary is
    deterministic and each call sees byte-identical inputs, so the response matrix is bit-identical
    at every `workers`. That equality is checked, not asserted: see
    `docs/THE_IMPULSE_LOOP_IS_PARALLEL.md`.

    This is also why it is not a GPU question. HotSpot has no GPU build, and the endpoint has to be
    HotSpot's or the number is not comparable with `docs/CELL_ENDPOINT_RESULT.md`. The GPU path
    (`fem_batch_gpu.py`, one factorisation and a batched solve through cuDSS) is for the FEM
    reference, which is a different model answering a different question.

    A thread pool, not a process pool: the work is entirely inside `subprocess.run`, which releases
    the GIL for its whole duration.
    """

    size = int(model_id[4:].split("-")[0])
    zero = np.zeros(len(blocks))

    # GPU FIRST, and the docstring above is stale for THIS repository. It says "HotSpot has no GPU
    # build", but `CertiTherm/gpu_hotspot.build_grid_operator_gpu` exists, is wired into
    # `hotspot.py:207` behind `CERTITHERM_GPU_HOTSPOT`, and `docs/ARCHIVE_CENSUS_RUN_LOG.md:48`
    # records its parity against the pinned binary as **exactly 0.0 K/W, bit-identical**, at
    # grid128/256/512. So the endpoint is HotSpot's either way and the comparison with
    # `docs/CELL_ENDPOINT_RESULT.md` is preserved.
    #
    # What changes is the shape of the work: the loop below launches ONE HotSpot subprocess PER
    # BLOCK -- 233 of them here -- while the GPU builder solves every unit response in one batch
    # against one factorised system and, with `grid_output` set, writes the raw grid field for each
    # right-hand side. That raw field is exactly what `_cell_field` reconstructs per subprocess.
    backend = _gpu_backend_from_env()
    if backend is not None:
        from CertiTherm.gpu_hotspot import _read_grid, build_grid_operator_gpu
        from CertiTherm.hotspot import HotSpotModel

        grid_path = Path(work) / f"{model_id}-grid.bin"
        _blocks_response, _blocks_ambient, _digest, _units = build_grid_operator_gpu(
            HOTSPOT, Path(config), Path(floorplan), TEMPLATE / "example.materials",
            HotSpotModel.parse(model_id), Path(work), backend, grid_output=grid_path,
        )
        fields = _read_grid(grid_path, len(blocks) + 1)          # column 0 is the zero solve
        if fields.shape[0] != size * size:
            raise SystemExit(
                f"the GPU grid has {fields.shape[0]} nodes but {model_id} declares {size * size}; "
                "the cell operator would be assembled against the wrong lattice"
            )
        ambient = fields[:, 0].copy()
        return fields[:, 1:] - ambient[:, None], ambient

    ambient = _cell_field(config, floorplan, blocks, zero, model_id, work, f"{model_id}-amb")
    response = np.empty((size * size, len(blocks)), dtype=float)

    def one(index):
        impulse = zero.copy()
        impulse[index] = 1.0
        return index, _cell_field(config, floorplan, blocks, impulse, model_id, work,
                                  f"{model_id}-{index}")

    if workers <= 1:
        done = 0
        for index in range(len(blocks)):
            _, field = one(index)
            response[:, index] = field - ambient
            done += 1
            if index % 25 == 0:
                print(f"  {model_id}: impulse {index}/{len(blocks)}", flush=True)
        return response, ambient

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, field in pool.map(one, range(len(blocks))):
            response[:, index] = field - ambient
            done += 1
            if done % 25 == 0 or done == len(blocks):
                print(f"  {model_id}: impulse {done}/{len(blocks)} ({workers} workers)", flush=True)
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

    operator = out_path.with_suffix(".npz")
    if not operator.exists():
        started = time.monotonic()
        rows, ambient = cell_operator(config, floorplan, blocks, model_id, work)
        print("  built in %.0f s" % (time.monotonic() - started), flush=True)
        np.savez_compressed(
            operator, model_ids=np.asarray([model_id]), response_k_per_w=rows[None, :, :],
            ambient_k=ambient[None, :], block_ids=np.asarray(blocks),
            # Layer 0 only, so every row is a die cell.
            cell_endpoint=np.asarray(["tool_compatible"] * rows.shape[0]),
        )
    _report(capture, operator, out_path, model_id, span)
    return


def _block_average(rows, blocks, floorplan_text):
    """`integral_B T / |B|` by AREA-WEIGHTED cell overlap, which is the exact projection.

    The first version sampled cell CENTRES and averaged the cells whose centre fell inside the block.
    That is not the block average, and it is not even defined for a block smaller than a cell: the
    run died on `obuf_0 covers no grid cell centre at 128x128` -- correctly, fail-closed, but only
    after paying for 227 impulse solves.

    Overlap weights are the right construction and they are also the ADJOINT-CONSISTENT one. That is
    not incidental: `CertiTherm/reciprocity.py` measures HotSpot's own grid-to-block mapping breaking
    reciprocity by 2.5-12 %, which is exactly the signature of a membership-count mapping rather than
    an `L^2` projection. So this function does not reproduce `gridN-avg`; it computes what
    `gridN-avg` approximates, and the two differ by that artefact.
    """

    size = int(round(math.sqrt(rows.shape[0])))
    geometry = {}
    for line in floorplan_text.splitlines():
        parts = line.split("#")[0].split()
        if len(parts) >= 5:
            geometry[parts[0]] = tuple(float(v) for v in parts[1:5])
    extent_x = max(x + w for w, _h, x, _y in geometry.values())
    extent_y = max(y + h for _w, h, _x, y in geometry.values())
    edges_x = np.arange(size + 1) * extent_x / size
    edges_y = np.arange(size + 1) * extent_y / size
    out = np.empty((len(blocks), rows.shape[1]), dtype=float)
    for index, name in enumerate(blocks):
        w, h, x, y = geometry[name]
        # Overlap length of each cell interval with the block interval, per axis; the 2-D overlap is
        # the outer product because the grid is a tensor product.
        ox = np.clip(np.minimum(edges_x[1:], x + w) - np.maximum(edges_x[:-1], x), 0.0, None)
        oy = np.clip(np.minimum(edges_y[1:], y + h) - np.maximum(edges_y[:-1], y), 0.0, None)
        weights = np.outer(oy, ox).ravel()
        total = float(weights.sum())
        if total <= 0.0:
            raise SystemExit(
                f"block {name} overlaps no cell of the {size}x{size} grid; the block and the grid "
                "describe different extents"
            )
        out[index] = weights @ rows / total
    return out


def _report(capture, operator_path, out_path, model_id, span):
    """Certify from a SAVED cell operator. The impulse solves are the expensive part and they are
    already paid for; a defect in the reporting must not cost them again."""

    _space, blocks, placed, floorplan_text = _power_space(capture)
    with np.load(operator_path, allow_pickle=False) as data:
        rows = np.asarray(data["response_k_per_w"], dtype=float)[0]
        ambient = np.asarray(data["ambient_k"], dtype=float)[0]
        if tuple(str(b) for b in data["block_ids"]) != tuple(blocks):
            raise SystemExit("the saved operator resolves a different block list than its capture")
    power = np.asarray(placed, dtype=float)
    total = float(np.sum(power))
    space = activity_bounded_power_space(blocks, power, activity_span=span)
    cell = certify_cells(
        rows, ambient, ["tool_compatible"] * rows.shape[0], space, total,
        endpoint="tool_compatible", limit_k=THERMAL_LIMIT_K, margin_k=MARGIN_K,
        linearisation_k=MODEL_ERROR_LIMIT_K,
    )
    block_rows = _block_average(rows, blocks, floorplan_text)
    # The ambient field is one value per cell, so it projects exactly like a response column.
    block_ambient = _block_average(ambient[:, None], blocks, floorplan_text).ravel()
    block_peak = float(np.max(
        _extreme_rows(block_rows, np.asarray(space.lower_w, dtype=float),
                      np.asarray(space.upper_w, dtype=float), total) + block_ambient
    ))
    payload = {
        "capture": Path(capture).name, "model": model_id, "span": span,
        "blocks": len(blocks), "cells": int(rows.shape[0]),
        "endpoint": cell.endpoint,
        "worst_case_max_cell_average_k": cell.worst_case_max_cell_average_k,
        "argmax_cell": cell.argmax_cell,
        "slack_k": cell.slack_k,
        "certified": cell.certified,
        "sup_peak_over_exact_block_projection_k": block_peak,
        "cell_minus_block_k": cell.worst_case_max_cell_average_k - block_peak,
    }
    print(json.dumps(payload, indent=1), flush=True)
    Path(out_path).write_text(json.dumps(payload, indent=1))


if __name__ == "__main__":
    main()
