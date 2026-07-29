"""A certified lower bound from cuts that coarse instrumentation CANNOT hit.

The bound this probe targets is structural, not accumulated. Every coarse action's vector is a
0/1 indicator over its group (`measurements.build_measurement_library`), so for two blocks b, b'
lying in the same group of EVERY coarse action, a delta moving power from b' to b is invisible
to all of them:

    delta = t * (e_b - e_b')   =>   a . delta = t * (1 - 1) = 0  for every such coarse a

The separating set of such a collision is therefore exactly `{post_route(b), post_route(b')}` --
a TWO-element cut, the strongest constraint the hitting-set master can receive. Group the blocks
by their coarse signature (the common refinement of the module, chiplet and placement-region
partitions); within one cell every pair has this property.

Two consequences the generic search cannot reach:

1. Hitting every such cut inside a cell means the un-selected blocks form an INDEPENDENT SET of
   the cell's confusability graph, so the selected post-route actions form a VERTEX COVER. The
   bound is its minimum weight, not a log-growing accumulation.
2. Cells are disjoint and their cuts mention only their own blocks' post-route actions, so the
   per-cell minima ADD. Disjoint supports are what makes a structural bound additive where
   overlapping generic cuts are not.

Soundness. Nothing here is a new relaxation. A pair is declared confusable only when the
EXISTING oracle returns a witness for the selection "every action except post_route(b) and
post_route(b')", and that witness is then re-validated in exact rational arithmetic by
`certificate.validate_witness`, with its cut recomputed by `certificate.separator_set` and
asserted to be exactly those two actions. A pair whose search finds nothing is recorded as
`unestablished`, never as non-confusable: the reject scan is deliberately restricted (below), so
absence of a witness is absence of evidence. Restricting which pairs are tested only shrinks the
graph, and a subgraph's minimum vertex cover is a lower bound on the whole graph's -- so every
number printed is valid for the real instance.

Scan restriction. For the pair (b, b') the delta raises block b at the expense of b', so the
reject cells scanned are (m, b) and (m, b') over every model -- 2 * models LPs per pair instead
of models * points. This is a search heuristic, not an assumption: see `unestablished` above.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/indistinguishable_pair_bound_probe.py <artifact-root> \
        <candidate> <package> <workload> [max_pairs] [total_budget_s]

`max_pairs = 0` prints the structural section and stops, which is the cheapest refutation: if
the common refinement is all singletons there is no cut of this shape and the direction is dead
before a single LP runs.
"""

from __future__ import annotations

import json
import sys
import time
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.certificate import (
    CertificateError,
    CertificateUnresolved,
    separator_set,
    validate_witness,
)
from CertiTherm.experiments import _measurement_costs, _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import build_measurement_library
from CertiTherm.synthesis import _collision_search

LIMIT_MARGIN_K = 0.05
FEASIBILITY_TOLERANCE = 1e-9
POST_ROUTE_MARKER = "::post_route::"


def coarse_signature_cells(
    actions: Sequence, n_blocks: int
) -> Tuple[Dict[int, int], List[List[int]]]:
    """Group blocks by which COARSE actions observe them; also map block -> post-route index.

    Returns `(post_route_index_by_block, cells)`. A cell is a maximal set of blocks with an
    identical coarse signature, i.e. indistinguishable by every non-post-route action.
    """

    post_route_index: Dict[int, int] = {}
    coarse: List[np.ndarray] = []
    for index, action in enumerate(actions):
        if POST_ROUTE_MARKER in action.action_id:
            support = np.flatnonzero(action.vector)
            if support.size != 1:
                raise SystemExit(f"post-route action {action.action_id} is not a single block")
            post_route_index[int(support[0])] = index
        else:
            coarse.append(action.vector)
    signatures: Dict[Tuple[int, ...], List[int]] = {}
    matrix = np.asarray(coarse) if coarse else np.zeros((0, n_blocks))
    for block in range(n_blocks):
        key = tuple(int(v) for v in (matrix[:, block] != 0.0))
        signatures.setdefault(key, []).append(block)
    cells = [sorted(members) for _, members in sorted(signatures.items())]
    return post_route_index, cells


def min_weight_vertex_cover(
    vertices: Sequence[int], edges: Sequence[Tuple[int, int]], weight: Dict[int, float]
) -> Tuple[float, Tuple[int, ...]]:
    """Exact minimum-WEIGHT vertex cover by branching on an uncovered edge.

    Exact rather than a matching lower bound because the cells here are small (tens of blocks)
    and the branching is on edges, so the recursion depth is the cover size. Weighted because
    the bound must stay correct if post-route costs ever differ per block; with equal costs it
    reduces to `cost * |cover|`.
    """

    adjacency: Dict[int, set] = {v: set() for v in vertices}
    for u, v in edges:
        adjacency[u].add(v)
        adjacency[v].add(u)
    best: List[Tuple[float, Tuple[int, ...]]] = [(float("inf"), ())]

    def recurse(chosen: Tuple[int, ...], chosen_weight: float, remaining: List[Tuple[int, int]]):
        if chosen_weight >= best[0][0]:
            return
        pending = [(u, v) for u, v in remaining if u not in chosen and v not in chosen]
        if not pending:
            best[0] = (chosen_weight, chosen)
            return
        u, v = pending[0]
        for pick in (u, v) if weight[u] <= weight[v] else (v, u):
            recurse(chosen + (pick,), chosen_weight + weight[pick], pending)

    recurse((), 0.0, list(edges))
    return best[0]


def _confusable(
    polytope,
    family,
    actions,
    pair_action_indices: Tuple[int, int],
    reject_specs: Tuple[Tuple[int, int], ...],
):
    """Ask the EXISTING oracle for a witness, then re-prove it in exact arithmetic.

    Returns the validated `WorldPair` and its exactly recomputed cut, or None when the
    restricted scan produced nothing. A witness that fails exact validation, or whose exact cut
    is not precisely the pair's two post-route actions, raises: that would mean the structural
    argument does not hold and must stop the probe rather than be averaged away.
    """

    excluded = set(pair_action_indices)
    selected = tuple(index for index in range(len(actions)) if index not in excluded)
    witnesses = _collision_search(
        polytope,
        family,
        actions,
        selected,
        LIMIT_MARGIN_K,
        FEASIBILITY_TOLERANCE,
        1,
        False,
        reject_specs,
    )
    if not witnesses:
        return None
    witness = witnesses[0]
    safe_w = tuple(Fraction(float(v)) for v in witness.safe_power_w)
    unsafe_w = tuple(Fraction(float(v)) for v in witness.unsafe_power_w)
    validate_witness(
        safe_w,
        unsafe_w,
        witness.reject_model,
        witness.reject_point,
        polytope,
        family,
        LIMIT_MARGIN_K,
        Fraction(FEASIBILITY_TOLERANCE).limit_denominator(10 ** 12),
    )
    cut = separator_set(safe_w, unsafe_w, actions, Fraction(0))
    if set(cut) != excluded:
        raise SystemExit(
            "the exact cut of a within-cell witness was not the pair's two post-route "
            f"actions: |cut|={len(cut)}; the structural argument does not hold"
        )
    return witness, cut


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
    post_route_index, cells = coarse_signature_cells(actions, len(blocks))
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
            try:
                found = _confusable(
                    polytope,
                    family,
                    actions,
                    (post_route_index[b], post_route_index[other]),
                    specs,
                )
            except (CertificateError, CertificateUnresolved) as exc:
                raise SystemExit(f"witness for ({b},{other}) failed exact validation: {exc}")
            if found is None:
                unestablished += 1
            else:
                confusable += 1
                edges_by_cell[cell_index].append((b, other))
        if stopped_early:
            break

    bound = 0.0
    per_cell = []
    for cell_index, edges in edges_by_cell.items():
        if not edges:
            continue
        cell = multi[cell_index]
        cover_weight, cover = min_weight_vertex_cover(cell, edges, weight)
        bound += cover_weight
        per_cell.append({
            "cell_size": len(cell),
            "confusable_edges": len(edges),
            "min_weight_vertex_cover": cover_weight,
            "cover_size": len(cover),
        })

    print(json.dumps({
        "pairs_tested": tested,
        "confusable": confusable,
        "unestablished": unestablished,
        "stopped_early": stopped_early,
        "elapsed_s": round(time.monotonic() - started, 1),
        "per_cell": per_cell,
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
