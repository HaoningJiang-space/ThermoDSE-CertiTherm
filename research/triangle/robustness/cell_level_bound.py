"""The number that decides whether the thermal half is recoverable: the CELL-level polytope bound.

`docs/WHERE_THE_THERMAL_ERROR_ACTUALLY_IS.md` establishes two things and leaves one open.

Established: the underlying temperature field converges well (per-cell change shrinks 4.8x for a 2x
refinement), while the BLOCK-AVERAGE mapping amplifies the discrepancy 3.4x, because the block
average at `gridN` and `grid2N` is taken over different cell supports and is therefore not the same
functional. And the polytope-wide bound is 2.5-5.3x a five-vector sample, so a sample cannot stand
in for it.

Open, and decisive: the polytope-wide bound at CELL level between `grid128` and `grid256`. If it is
small against the 2-8 K decision margin the thermal half is recoverable; if it is comparable, no
amount of care in the LP above it will help.

## The construction, which must cover every FINE hotspot

Peer review's condition: "die averages or matched coarse cells do not bound an unobserved fine-cell
maximum". So the predictor is not cell-to-cell -- it is every FINE cell against the COARSE cell that
contains it:

    u_c = max over fine children j of c  of   max_{p in P} [ T_fine,j(p) - T_coarse,c(p) ]

Then `T_coarse,c(p) <= L - u_c` for every coarse cell `c` implies `T_fine,j(p) <= L` for every fine
cell `j`, because each `j` has a parent and that parent's constraint carries `j`'s worst case. The
maximum is over BOUNDS, never over the temperature, so a moving argmax breaks nothing.

Each `T_fine,j - T_coarse,c` is affine in `p`, so its supremum over the box-with-total polytope is a
greedy fill -- exact, no solver, and vectorised here over all fine cells at once.

## Cost

One HotSpot solve per block per grid, which is what the block-level operator already costs: the
impulse responses are the same runs, and `-grid_steady_file` simply asks for more of each run's
output. The extra cost is memory and the greedy, not simulation.

NON-CLAIM diagnostic. Builds its own cell-level operators; writes one JSON.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/cell_level_bound.py <capture.npz> <workspace> \\
        <out.json> [coarse] [fine]
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cross_grid_bound import one_sided_containment_bounds
from CertiTherm.experiments import _power_space
from CertiTherm.measurements import content_upper_bounds
from CertiTherm.paths import HOTSPOT, TEMPLATE


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
    coarse_id = sys.argv[4] if len(sys.argv) > 4 else "grid128-avg"
    fine_id = sys.argv[5] if len(sys.argv) > 5 else "grid256-avg"

    _space, blocks, placed, floorplan_text = _power_space(capture)
    work.mkdir(parents=True, exist_ok=True)
    floorplan = work / "floorplan.flp"
    floorplan.write_text(floorplan_text, encoding="utf-8")
    config = work / "package.config"
    if not config.exists():
        raise SystemExit(
            f"{config} must exist; copy the package.config the operator build used rather than "
            "regenerating it, so any difference here is the model and nothing else"
        )

    power = np.asarray(placed, dtype=float)
    upper = content_upper_bounds(blocks, power)
    total = float(np.sum(power))
    lower = np.zeros(len(blocks))

    coarse_size = int(coarse_id[4:].split("-")[0])
    fine_size = int(fine_id[4:].split("-")[0])
    if fine_size % coarse_size:
        raise SystemExit("the fine grid must be an integer refinement of the coarse one")
    factor = fine_size // coarse_size

    coarse_rows, coarse_ambient = cell_operator(config, floorplan, blocks, coarse_id, work)
    fine_rows, fine_ambient = cell_operator(config, floorplan, blocks, fine_id, work)

    # Every FINE cell against the COARSE cell containing it. A cell-to-cell comparison at matched
    # locations would leave the fine cells between coarse centres unbounded, which is exactly the
    # hole peer review named.
    parent = np.empty(fine_size * fine_size, dtype=int)
    for row in range(fine_size):
        for col in range(fine_size):
            parent[row * fine_size + col] = (row // factor) * coarse_size + (col // factor)

    hotter, colder = one_sided_containment_bounds(
        coarse_rows[parent], fine_rows, coarse_ambient[parent], fine_ambient,
        lower, upper, total,
    )
    # Worst fine child per coarse cell: that is what the coarse row must be tightened by.
    per_coarse = np.full(coarse_size * coarse_size, -np.inf)
    np.maximum.at(per_coarse, parent, hotter)

    payload = {
        "capture": capture.name, "coarse": coarse_id, "fine": fine_id,
        "blocks": len(blocks), "coarse_cells": int(coarse_size ** 2),
        "fine_cells": int(fine_size ** 2),
        "u_max_over_cells_k": float(np.max(per_coarse)),
        "u_median_over_cells_k": float(np.median(per_coarse)),
        "u_p99_over_cells_k": float(np.percentile(per_coarse, 99)),
        "colder_max_k": float(np.max(colder)),
        "note": (
            "u is the polytope-wide amount by which the FINE grid can read hotter than the COARSE "
            "cell containing it. Tightening every coarse row by its own u certifies against the "
            "fine operator. Compare against the 2-8 K decision margin, NOT against a sample."
        ),
    }
    print(json.dumps(payload, indent=1), flush=True)
    out_path.write_text(json.dumps(payload, indent=1))


if __name__ == "__main__":
    main()
