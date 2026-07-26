"""Why are the reported hottest blocks tied? A geometric diagnostic, no HotSpot run.

The V6.1 evidence document carried one explanation, labelled UNTESTED: under a `max` grid
mapping a block's temperature is the maximum over the grid cells covering it, so two blocks
sharing the hottest cell get identical values. This resolves it from committed data.

HotSpot's mapping, read from the pinned submodule rather than assumed:

- `xlate_temp_g2b` (`temperature_grid.c`, `case GRID_MAX`) sets a block's reported temperature
  to `max(cuboid[layer][i][j])` over the half-open rectangle `[i1,i2) x [j1,j2)` from `g2bmap`.
  The value is COPIED from a cell, so two blocks whose maxima are the same cell receive the same
  double, bit for bit.
- The rectangle is rounded OUTWARD (`temperature_grid.c`, the `g2bmap` setup):
      i1 = rows - tolerant_ceil(top_y / cell_h)      i2 = rows - tolerant_floor(bottom_y / cell_h)
      j1 = tolerant_floor(left_x / cell_w)           j2 = tolerant_ceil(right_x / cell_w)
  so it covers every cell the block touches, including partially overlapped ones.

That does NOT mean abutting blocks always share cells. If their common boundary falls exactly on
a cell edge, `ceil` and `floor` agree there and the rectangles meet without overlapping. They
share cells only when the boundary falls INSIDE a cell.

Two consequences this script tests, and they are different mechanisms:

1. Overlapping rectangles are NECESSARY for a bit-identical pair -- `max` cannot return the same
   double from disjoint cell sets except by coincidence. They are NOT sufficient: each block may
   still have a hotter cell of its own.
2. Blocks with DISJOINT rectangles can still be near-degenerate, by floorplan symmetry. That is a
   different explanation and the document did not have it.

What this does not do: confirm that the shared cell is the argmax of both rectangles. That needs
per-cell temperatures, and HotSpot writes `dump_steady_temp_grid` at `%.2f` -- the repository's
precision patch covers the block dump, not the cell dump -- so a full-precision witness would
need an instrumented diagnostic binary, whose different hash would put it outside the canonical
instance. Recorded as the remaining step, not performed.

Usage:
    python research/triangle/v61_tie_mechanism.py <manifest.json> <floorplan.flp> [out.json]
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.triangle.v61_contract import Refuse, get, require  # noqa: E402
from research.triangle.v61_validate import build  # noqa: E402

# HotSpot/util.h: #define DELTA 1.0e-6, used by eq() inside the tolerant_* rounding.
HOTSPOT_DELTA = 1.0e-6
GRID_ROWS = GRID_COLS = 64


def _eq(a: float, b: float) -> bool:
    return abs(a - b) < HOTSPOT_DELTA


def tolerant_ceil(value: float) -> int:
    nearest = math.floor(value + 0.5)
    return int(nearest) if _eq(value, nearest) else int(math.ceil(value))


def tolerant_floor(value: float) -> int:
    nearest = math.floor(value + 0.5)
    return int(nearest) if _eq(value, nearest) else int(math.floor(value))


def read_floorplan(path: Path) -> dict:
    units = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 5 or line.lstrip().startswith("#"):
            continue
        name, w, h, x, y = fields[0], *(float(f) for f in fields[1:5])
        require(name not in units, f"duplicate floorplan unit {name!r}")
        require(w > 0 and h > 0, f"unit {name!r} has non-positive extent")
        units[name] = {"w": w, "h": h, "x": x, "y": y}
    require(bool(units), "the floorplan has no units")
    return units


def cell_rectangles(units: dict, rows: int = GRID_ROWS, cols: int = GRID_COLS) -> dict:
    """Reconstruct HotSpot's g2bmap rectangle for every unit.

    A reimplementation cannot be its own oracle. Its check is the pattern it has to reproduce:
    every bit-identical pair must overlap and every disjoint pair must not be bit-identical. A
    wrong rectangle would break that on the 233-block, 15-row set.
    """
    width = max(u["x"] + u["w"] for u in units.values())
    height = max(u["y"] + u["h"] for u in units.values())
    cw, ch = width / cols, height / rows
    out = {}
    for name, u in units.items():
        i1 = rows - tolerant_ceil((u["y"] + u["h"]) / ch)
        i2 = rows - tolerant_floor(u["y"] / ch)
        j1 = tolerant_floor(u["x"] / cw)
        j2 = tolerant_ceil((u["x"] + u["w"]) / cw)
        require(0 <= i1 < i2 <= rows and 0 <= j1 < j2 <= cols,
                f"unit {name!r} maps to an invalid rectangle ({i1},{i2},{j1},{j2}); HotSpot "
                f"would have called fatal() here")
        out[name] = (i1, i2, j1, j2)
    return {"cell_w_m": cw, "cell_h_m": ch, "chip_w_m": width, "chip_h_m": height,
            "rows": rows, "cols": cols, "rect": out}


def overlaps(a: tuple, b: tuple) -> bool:
    i1, i2, j1, j2 = a
    k1, k2, l1, l2 = b
    return not (i2 <= k1 or k2 <= i1 or j2 <= l1 or l2 <= j1)


def shared_cells(a: tuple, b: tuple) -> int:
    i1, i2, j1, j2 = a
    k1, k2, l1, l2 = b
    return max(0, min(i2, k2) - max(i1, k1)) * max(0, min(j2, l2) - max(j1, l1))


def analyse(manifest: dict, floorplan: Path) -> dict:
    v, _, _ = build(manifest)
    require(manifest["input_hashes"]["floorplan"]
            == hashlib.sha256(floorplan.read_bytes()).hexdigest(),
            f"{floorplan.name} is not the floorplan this manifest was produced from")
    units = read_floorplan(floorplan)
    require(set(units) == set(v["block_ids"]),
            f"the floorplan names {len(units)} units, the manifest {len(v['block_ids'])} blocks")
    geom = cell_rectangles(units)
    rect = geom["rect"]

    rows_out, counts = {}, {"shared_cell": 0, "symmetric": 0, "not_tied": 0, "overlap_untied": 0}
    for tag in sorted(v["rows"]):
        steady = manifest["rows"][tag]["mean_steady_block_k"]
        order = sorted(range(len(steady)), key=lambda i: (-steady[i], i))
        a, b = v["block_ids"][order[0]], v["block_ids"][order[1]]
        gap = steady[order[0]] - steady[order[1]]
        identical = steady[order[0]] == steady[order[1]]
        share = shared_cells(rect[a], rect[b])
        if identical:
            require(share > 0,
                    f"row `{tag}`: {a} and {b} report a bit-identical double from DISJOINT cell "
                    f"rectangles. `max` copies a cell value, so this should be impossible -- "
                    f"either the reconstructed geometry is wrong or the mechanism is not the "
                    f"mapping.")
            mechanism = "shared_cell"
        elif share == 0 and gap < 1e-5:
            # Disjoint rectangles cannot share a cell, so a near-degeneracy here is not the
            # mapping. Corner-symmetric blocks are the obvious candidate.
            mechanism = "symmetric"
        elif share > 0:
            mechanism = "overlap_untied"
        else:
            mechanism = "not_tied"
        counts[mechanism] += 1
        rows_out[tag] = {
            "top_two": [a, b], "steady_gap_k": gap, "bit_identical": identical,
            "periodic_gap_k": v["view"][tag]["periodic"]["gap_k"],
            "periodic_tie_set_size": len(v["view"][tag]["periodic"]["ties"]),
            "rect": {a: list(rect[a]), b: list(rect[b])}, "shared_cells": share,
            "mechanism": mechanism,
        }
    return {
        "manifest_commit": manifest["commit"], "run_id": manifest["run"]["run_id"],
        "floorplan_sha256": manifest["input_hashes"]["floorplan"],
        "grid": {k: geom[k] for k in ("rows", "cols", "cell_w_m", "cell_h_m",
                                      "chip_w_m", "chip_h_m")},
        "mechanism_counts": counts, "rows": rows_out,
        "necessary_not_sufficient": (
            "Overlapping rectangles are necessary for a bit-identical pair, not sufficient: "
            f"{counts['overlap_untied']} row(s) overlap without being bit-identical, because "
            "each block's own hottest cell lies outside the shared region."),
        "unproven": (
            "Not established here: that the shared cell IS the argmax of both rectangles. That "
            "needs per-cell temperatures, and HotSpot's cell dump is %.2f -- the repository's "
            "precision patch covers the block dump only -- so a full-precision witness would "
            "need an instrumented binary whose different hash falls outside the canonical "
            "instance."),
    }


def main() -> None:
    manifest_path, floorplan = Path(sys.argv[1]), Path(sys.argv[2])
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    try:
        result = analyse(json.loads(manifest_path.read_text()), floorplan)
    except Refuse as exc:
        print(f"REFUSING: {exc}")
        sys.exit(2)
    text = json.dumps(result, indent=2) + "\n"
    if out:
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out}")
    c = result["mechanism_counts"]
    print(f"  shared_cell     {c['shared_cell']:2d}  bit-identical, rectangles overlap")
    print(f"  symmetric       {c['symmetric']:2d}  near-degenerate, rectangles DISJOINT")
    print(f"  overlap_untied  {c['overlap_untied']:2d}  overlap but not tied")
    print(f"  not_tied        {c['not_tied']:2d}")
    for tag, r in result["rows"].items():
        print(f"    {tag:16s} {r['mechanism']:14s} gap={r['steady_gap_k']:.3e} "
              f"shared={r['shared_cells']:3d} cells  {r['top_two']}")


if __name__ == "__main__":
    main()
