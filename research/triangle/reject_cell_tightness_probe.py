"""Rank reject cells by leverage OVER the gap they must close, not by leverage alone.

The scan that produced 1112.0 ranked reject cells by `|R[m,q,b] - R[m,q,c]|` -- how much the blind
direction moves the temperature at that cell. Measured against an exhaustive scan it recovered 1 of
20 candidate edges where the exhaustive one recovered 20 of 20, so it was missing 95% of what was
there. The reason is visible from the reject condition itself.

A blind-direction collision needs, at some cell (m, q):

    R[m,q] . p_safe  -  t * (R[m,q,b] - R[m,q,c])  >=  floor[m,q]

Since `p_safe` must be robustly SAFE at EVERY cell, the largest the first term can be is

    peak[m,q] = max { R[m,q] . p : p in polytope, p robustly SAFE everywhere }

which is one LP per cell and does not depend on the pair. Rearranging, the pair can reject at (m, q)
only if

    |t| * |R[m,q,b] - R[m,q,c]|  >=  floor[m,q] - peak[m,q]  =:  gap[m,q]

**The old heuristic ranked the left-hand side and ignored the right.** A cell with large leverage and
a larger gap is useless; a cell with modest leverage and a tiny gap is where collisions actually
live. The ranking that matters is `leverage / gap`, and because `gap` is a property of the cell
rather than of the pair, it is computed ONCE per instance and reused for all 1166 pairs.

This probe computes `gap` for every cell and reports whether the top-K cells under the corrected
ranking recover the edges that only an exhaustive scan found. If they do, the 711-cell scan becomes
a K-cell scan and a full dev sweep becomes affordable.

NON-CLAIM diagnostic. Reads committed artifacts; writes only the gap table it is asked for.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/reject_cell_tightness_probe.py <artifact-root> \\
        <candidate> <package> <workload> [gaps_out.json]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, ".")

from CertiTherm.experiments import _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.thermal_constraints import reject_cell_rows, robust_safe_cell_rows

LIMIT_MARGIN_K = 0.05


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    out_path = Path(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5] != "-" else None

    polytope, blocks, _placed, _floorplan = _power_space(
        artifacts / "captures" / f"{workload}--{candidate}.npz"
    )
    family, operator_blocks = load_family(
        artifacts / "operators" / f"{candidate}--{package}.npz"
    )
    if blocks != operator_blocks:
        raise SystemExit("power/operator block identity mismatch")

    safe_rows, safe_rhs = robust_safe_cell_rows(family, LIMIT_MARGIN_K)
    reject_rows, floors = reject_cell_rows(family, LIMIT_MARGIN_K)
    models, points = family.response_k_per_w.shape[:2]

    # One LP per cell: how high can this cell's temperature go while the whole map stays SAFE?
    # The SAFE rows are the same for every cell, so only the objective changes.
    a_ub = np.vstack((polytope.a_ub, safe_rows)) if polytope.a_ub.size else safe_rows
    b_ub = np.concatenate((polytope.b_ub, safe_rhs)) if polytope.b_ub.size else safe_rhs
    bounds = tuple(zip(polytope.lower_w, polytope.upper_w))

    started = time.monotonic()
    gaps, peaks, unbounded = [], [], 0
    for index in range(reject_rows.shape[0]):
        result = linprog(
            -reject_rows[index],
            A_ub=a_ub,
            b_ub=b_ub,
            A_eq=polytope.a_eq,
            b_eq=polytope.b_eq,
            bounds=bounds,
            method="highs",
        )
        if result.status != 0:
            # A cell whose SAFE-constrained maximum cannot be computed gets an infinite gap, which
            # ranks it last rather than first: an unusable number must never look attractive.
            unbounded += 1
            peaks.append(float("nan"))
            gaps.append(float("inf"))
            continue
        peak = float(-result.fun)
        peaks.append(peak)
        gaps.append(float(floors[index]) - peak)

    gap_array = np.asarray(gaps)
    finite = gap_array[np.isfinite(gap_array)]
    payload = {
        "candidate": candidate, "package": package, "workload": workload,
        "models": models, "points": points, "cells": int(reject_rows.shape[0]),
        "unsolved_cells": unbounded,
        "seconds": round(time.monotonic() - started, 1),
        "gap_min": float(finite.min()) if finite.size else None,
        "gap_median": float(np.median(finite)) if finite.size else None,
        "gap_max": float(finite.max()) if finite.size else None,
        "tightest_cells": [
            {"model": int(i // points), "point": int(i % points),
             "block": blocks[int(i % points)] if (i % points) < len(blocks) else "",
             "gap_k": float(gap_array[i])}
            for i in np.argsort(gap_array)[:12]
        ],
        "note": (
            "gap = reject floor minus the highest this cell can reach while the whole power map "
            "stays robustly SAFE. A blind direction can only reject here if its leverage times the "
            "movable power exceeds this. Ranking cells by leverage ALONE ignored it, which is why "
            "an eight-cell scan found 1 of 20 edges an exhaustive scan found 20 of 20."
        ),
    }
    if out_path is not None:
        out_path.write_text(json.dumps({"gaps": [float(g) for g in gaps], **payload}))
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
