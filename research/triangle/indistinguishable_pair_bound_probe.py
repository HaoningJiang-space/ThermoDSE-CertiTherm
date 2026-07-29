"""Measure the blind-direction lower bound on a real dev instance.

The method itself lives in `CertiTherm.blind_direction_cuts` and is covered by
`CertiTherm/tests/test_blind_direction_cuts.py`, which pins the load-bearing property against
the certified oracle's own optimum. This file is only the driver: it loads a committed capture
and operator, groups the blocks, certifies within-cell pairs, and prints the resulting bound.

Every number printed is valid for the real instance. Pairs and reject cells are both scanned
only in part, and both restrictions can only understate the bound -- an unestablished pair is
simply an edge the graph does not have, and a subgraph's minimum vertex cover is a lower bound
on the whole graph's.

Scan restriction. For the pair (b, c) the blind direction raises b at the expense of c, so the
reject cells scanned are (m, b) and (m, c) over every model -- 2 * models LPs per pair instead of
models * points. A heuristic on where to look, never an assumption about what is not there.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/indistinguishable_pair_bound_probe.py <artifact-root> \
        <candidate> <package> <workload> [max_pairs] [total_budget_s]

`max_pairs = 0` prints the structural section and stops: if the common refinement is all
singletons there is no cut of this shape and the direction dies for zero LPs.
"""

from __future__ import annotations

import json
import sys
import time
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, ".")

from CertiTherm.blind_direction_cuts import (
    blind_direction_lower_bound,
    certify_blind_pair,
    coarse_indistinguishability_cells,
)
from CertiTherm.experiments import _measurement_costs, _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import build_measurement_library

LIMIT_MARGIN_K = 0.05
FEASIBILITY_TOLERANCE = 1e-9


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    max_pairs = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    budget_s = float(sys.argv[6]) if len(sys.argv) > 6 else 3600.0

    polytope, blocks, _placed, floorplan_text = _power_space(
        artifacts / "captures" / f"{workload}--{candidate}.npz"
    )
    family, operator_blocks = load_family(
        artifacts / "operators" / f"{candidate}--{package}.npz"
    )
    if blocks != operator_blocks:
        raise SystemExit("power/operator block identity mismatch")
    architectures = {
        row["architecture_id"]: row
        for row in _rows(ROOT / "experiments" / "architectures.tsv")
    }
    costs = _measurement_costs()
    actions = build_measurement_library(
        candidate, blocks, floorplan_text, architectures[candidate], costs
    )
    models, points = family.response_k_per_w.shape[:2]
    post_route_index, cells = coarse_indistinguishability_cells(actions, len(blocks))
    weight = {
        block: float(actions[index].cost) for block, index in post_route_index.items()
    }

    sizes = sorted((len(cell) for cell in cells), reverse=True)
    multi = [cell for cell in cells if len(cell) >= 2]
    ceiling = sum(
        sum(sorted(weight[b] for b in cell)[:-1]) for cell in multi
    )
    print(json.dumps({
        "candidate": candidate, "package": package, "workload": workload,
        "blocks": len(blocks), "library_actions": len(actions),
        "coarse_actions": len(actions) - len(post_route_index),
        "models": models, "points": points,
        "refinement_cells": len(cells),
        "cells_with_two_or_more": len(multi),
        "largest_cell_sizes": sizes[:12],
        "pairs_available": sum(len(c) * (len(c) - 1) // 2 for c in multi),
        "structural_ceiling": ceiling,
        "note": (
            "structural_ceiling is what this bound could reach if EVERY within-cell pair were "
            "confusable: sum over cells of (cell weight minus its cheapest block). It is not a "
            "bound until pairs are certified below."
        ),
    }, indent=2), flush=True)

    if not multi:
        print(json.dumps({
            "verdict": "DEAD",
            "why": "the common refinement is all singletons; no two-element cut of this shape "
                   "exists and no LP was run",
        }, indent=2), flush=True)
        return
    if max_pairs <= 0:
        print(json.dumps({"verdict": "STRUCTURE_ONLY", "pairs_tested": 0}, indent=2), flush=True)
        return

    tested = confusable = unestablished = 0
    edges_by_cell: Dict[int, List[Tuple[int, int]]] = {}
    started = time.monotonic()
    stopped_early = None
    for cell_index, cell in enumerate(multi):
        edges_by_cell.setdefault(cell_index, [])
        for b, other in combinations(cell, 2):
            if tested >= max_pairs:
                stopped_early = "max_pairs"
                break
            if time.monotonic() - started > budget_s:
                stopped_early = "budget_s"
                break
            specs = tuple(
                (m, q) for m in range(models) for q in (b, other) if q < points
            )
            tested += 1
            found = certify_blind_pair(
                polytope,
                family,
                actions,
                (b, other),
                (post_route_index[b], post_route_index[other]),
                specs,
                LIMIT_MARGIN_K,
                FEASIBILITY_TOLERANCE,
            )
            if found is None:
                unestablished += 1
            else:
                confusable += 1
                edges_by_cell[cell_index].append((b, other))
        if stopped_early:
            break

    bound, per_cell = blind_direction_lower_bound(multi, edges_by_cell, weight)

    print(json.dumps({
        "pairs_tested": tested,
        "confusable": confusable,
        "unestablished": unestablished,
        "stopped_early": stopped_early,
        "elapsed_s": round(time.monotonic() - started, 1),
        "per_cell": list(per_cell),
        "certified_lower_bound": bound,
        "note": (
            "every confusable pair was re-proved in exact rational arithmetic and its cut "
            "confirmed to be exactly two post-route actions; cells are disjoint so their "
            "covers add. Valid for the real instance even though only a subset of pairs and "
            "reject cells was scanned -- a subgraph's cover is a lower bound."
        ),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
