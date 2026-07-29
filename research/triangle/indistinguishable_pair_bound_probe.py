"""Measure the blind-direction lower bound on a real dev instance.

The method itself lives in `CertiTherm.blind_direction_cuts` and is covered by
`CertiTherm/tests/test_blind_direction_cuts.py`, which pins the load-bearing property against
the certified oracle's own optimum. This file is only the driver: it loads a committed capture
and operator, groups the blocks, certifies within-cell pairs, and prints the resulting bound.

Every number printed is valid for the real instance. Pairs and reject cells are both scanned
only in part, and both restrictions can only understate the bound -- an unestablished pair is
simply an edge the graph does not have, and a subgraph's minimum vertex cover is a lower bound
on the whole graph's.

Scan restriction. Moving t of power from c to b changes point q's temperature by exactly
`t * (R[m,q,b] - R[m,q,c])`, so the reject cells with the most leverage on the blind direction
are those where that difference is largest. The scan ranks every (model, point) by it and takes
the strongest `scan_points`. Peer review noted the earlier rule -- scan only the pair's own two
points -- was leaving valid edges undiscovered. Either way this is a heuristic about WHERE TO
LOOK, never an assumption about what is not there: a pair no scanned cell establishes is
recorded as unestablished, which only ever lowers the bound.

With `seeds_out` the established cuts are written as action-ID lists so the 27-minute pair scan
does not have to be repeated to try a different synthesis budget, and with `synthesis_budget_s`
they are fed straight into `synthesize_minimum_observation` as `seed_cuts` -- the master then
starts from the structural constraints instead of from nothing.

NON-CLAIM diagnostic. Reads committed artifacts; writes only the seed file it is asked for.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/indistinguishable_pair_bound_probe.py <artifact-root> \
        <candidate> <package> <workload> [max_pairs] [total_budget_s] [scan_points] \
        [seeds_out] [synthesis_budget_s]

`max_pairs = 0` prints the structural section and stops: if the common refinement is all
singletons there is no cut of this shape and the direction dies for zero LPs.
"""

from __future__ import annotations

import json
import sys
import time
from itertools import combinations

import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, ".")

from CertiTherm.blind_direction_cuts import (
    blind_direction_cells,
    blind_direction_lower_bound,
    block_instrumentation_cost,
    certify_blind_pair,
)
from CertiTherm.experiments import _measurement_costs, _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import build_measurement_library
from CertiTherm.solver_budget import budget_scope
from CertiTherm.synthesis import synthesize_minimum_observation

LIMIT_MARGIN_K = 0.05
FEASIBILITY_TOLERANCE = 1e-9


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    max_pairs = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    budget_s = float(sys.argv[6]) if len(sys.argv) > 6 else 3600.0
    scan_points = int(sys.argv[7]) if len(sys.argv) > 7 else 8
    seeds_out = Path(sys.argv[8]) if len(sys.argv) > 8 and sys.argv[8] != "-" else None
    synthesis_budget_s = float(sys.argv[9]) if len(sys.argv) > 9 else 0.0

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
    response = family.response_k_per_w
    models, points = response.shape[:2]
    single_block_actions, cells = blind_direction_cells(actions, len(blocks))
    cost = block_instrumentation_cost(actions, single_block_actions, range(len(blocks)))

    sizes = sorted((len(cell) for cell in cells), reverse=True)
    multi = [cell for cell in cells if len(cell) >= 2]
    # A cell's cover can never need every block: leaving the most expensive one uninstrumented
    # still covers every edge. So the ceiling drops the LARGEST weight in each cell, not the
    # smallest -- peer review caught the note below claiming the opposite while the code was
    # already right, an error that equal costs would have hidden forever.
    ceiling = sum(sum(sorted(cost[b] for b in cell)[:-1]) for cell in multi)
    print(json.dumps({
        "candidate": candidate, "package": package, "workload": workload,
        "blocks": len(blocks), "library_actions": len(actions),
        "single_block_actions": len(single_block_actions),
        "models": models, "points": points, "scan_points": scan_points,
        "refinement_cells": len(cells),
        "cells_with_two_or_more": len(multi),
        "largest_cell_sizes": sizes[:12],
        "pairs_available": sum(len(c) * (len(c) - 1) // 2 for c in multi),
        "structural_ceiling": float(ceiling),
        "note": (
            "structural_ceiling is what this bound could reach if EVERY within-cell pair were "
            "confusable: sum over cells of (cell weight minus its MOST EXPENSIVE block). It is "
            "not a bound until pairs are certified below."
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
    seed_cuts: List[Tuple[str, ...]] = []
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
            # Rank every reject cell by the temperature swing the blind direction produces
            # there, and scan only the strongest few.
            leverage = abs(response[:, :, b] - response[:, :, other])
            order = np.argsort(leverage, axis=None)[::-1][:scan_points]
            specs = tuple(
                (int(i // points), int(i % points)) for i in order
            )
            tested += 1
            found = certify_blind_pair(
                polytope,
                family,
                actions,
                (b, other),
                single_block_actions,
                specs,
                LIMIT_MARGIN_K,
                FEASIBILITY_TOLERANCE,
            )
            if found is None:
                unestablished += 1
            else:
                confusable += 1
                edges_by_cell[cell_index].append((b, other))
                seed_cuts.append(found.cut_action_ids)
        if stopped_early:
            break

    bound, per_cell = blind_direction_lower_bound(multi, edges_by_cell, cost)

    if seeds_out is not None:
        seeds_out.write_text(json.dumps({
            "candidate": candidate, "package": package, "workload": workload,
            "vertex_cover_bound": float(bound),
            "cuts": [list(cut) for cut in seed_cuts],
        }))

    print(json.dumps({
        "pairs_tested": tested,
        "confusable": confusable,
        "unestablished": unestablished,
        "stopped_early": stopped_early,
        "elapsed_s": round(time.monotonic() - started, 1),
        "per_cell": list(per_cell),
        "certified_lower_bound": float(bound),
        "note": (
            "every counted pair was repaired to EXACT polytope feasibility and re-proved with "
            "zero slack, with its cut recomputed exactly; cells are disjoint so their covers "
            "add. Valid for the real instance even though only a subset of pairs and reject "
            "cells was scanned -- a subgraph's cover is a lower bound. Compose with the "
            "existing certified bound by max, never by addition."
        ),
    }, indent=2), flush=True)

    if synthesis_budget_s > 0 and seed_cuts:
        started = time.monotonic()
        record = {"seeded_cuts": len(seed_cuts), "budget_s": synthesis_budget_s}
        try:
            with budget_scope(synthesis_budget_s):
                plan = synthesize_minimum_observation(
                    polytope, family, actions,
                    max_iterations=500000,
                    seed_cuts=[list(cut) for cut in seed_cuts],
                )
            record.update(
                status=plan.status,
                exact_cost=plan.exact_cost,
                lower_bound=plan.lower_bound,
                iterations=plan.iterations,
            )
        except Exception as exc:  # noqa: BLE001 - a probe records the failure, it does not raise
            record.update(status="RAISED", detail=f"{type(exc).__name__}: {exc}")
        record["elapsed_s"] = round(time.monotonic() - started, 1)
        record["note"] = (
            "the seeded master's lower bound must be at least the vertex-cover bound above, "
            "since the seeds are exactly those cuts; anything less means a seed was dropped"
        )
        print(json.dumps(record, indent=2), flush=True)


if __name__ == "__main__":
    main()
