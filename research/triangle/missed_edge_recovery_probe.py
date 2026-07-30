"""Recover the within-cell edges the restricted reject scan missed, and re-cover.

The pair scan looks at the eight (model, point) cells with the most leverage on each blind
direction. That is a search heuristic, and a heuristic misses things: scanning the cover plus the
coarse library turned up 36 surviving collisions whose delta is supported on exactly two blocks of
ONE cell with zero sum -- which is the definition of a confusable pair the graph does not contain.

A missing edge is a missing vertex-cover constraint, so the reported bound is an UNDERSTATEMENT.
Recovering them can only raise it, and the recovered pairs come with their own witnesses, so nothing
has to be re-searched: each is re-proved here through the same exact path as the original edges --
repaired to exact polytope feasibility, validated with zero slack, cut recomputed -- and only then
added.

This is a sound gain, unlike the other 425 survivors. Those have a cut MEETING the current selection
with a worst |a.delta|/tolerance of 1.000016, so they sit on the LP's feasibility boundary: the
solver returned points that violate an action's tolerance by a fraction of a part per million, which
means the returned point is not a valid collision for this plan and refusing to certify on it is
fail-closed. It does NOT mean no valid collision is nearby -- the same LP cell may hold a genuine one
the solver could not return accurately -- so they are *numerically unresolved*, not dismissed.

The tempting fix, tightening the LP's right-hand side to `tol - slack`, is FAIL-OPEN: it shrinks the
collision set, so the oracle could certify a plan that has a real collision just inside the boundary.
They are left alone deliberately.

NON-CLAIM diagnostic. Reads committed artifacts and one saved cut file; writes an updated cut file
only when asked.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/missed_edge_recovery_probe.py <artifact-root> \\
        <candidate> <package> <workload> <seed-cuts.json> [out.json] [budget_s]
"""

from __future__ import annotations

import json
import sys
import time
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.blind_direction_cuts import (
    blind_direction_cells,
    block_instrumentation_cost,
    certify_blind_pair,
    minimum_weight_vertex_cover,
)
from CertiTherm.experiments import _measurement_costs, _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import build_measurement_library
from CertiTherm.solver_budget import budget_scope
from CertiTherm.synthesis import _collision_search

LIMIT_MARGIN_K = 0.05
FEASIBILITY_TOLERANCE = 1e-9
SUPPORT_FLOOR_W = 1e-7


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    seeds_path = Path(sys.argv[5])
    out_path = Path(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6] != "-" else None
    budget_s = float(sys.argv[7]) if len(sys.argv) > 7 else 3600.0

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
    actions = build_measurement_library(
        candidate, blocks, floorplan_text, architectures[candidate], _measurement_costs()
    )
    index_of = {action.action_id: i for i, action in enumerate(actions)}
    single_block_actions, cells = blind_direction_cells(actions, len(blocks))
    cost = block_instrumentation_cost(actions, single_block_actions, range(len(blocks)))
    block_of = {indices[0]: block for block, indices in single_block_actions.items()}
    cell_of = {block: i for i, cell in enumerate(cells) for block in cell}
    models, points = family.response_k_per_w.shape[:2]

    saved = json.loads(seeds_path.read_text())
    known: set[tuple[int, int]] = set()
    edges_by_cell: dict[int, list[tuple[int, int]]] = {}
    for cut in saved["cuts"]:
        pair = tuple(sorted(block_of[index_of[name]] for name in cut))
        known.add(pair)
        edges_by_cell.setdefault(cell_of[pair[0]], []).append(pair)

    def cover_bound(edges: dict) -> tuple[Fraction, list[int]]:
        total, chosen = Fraction(0), []
        for cell_index, cell_edges in sorted(edges.items()):
            weight, cover = minimum_weight_vertex_cover(cells[cell_index], cell_edges, cost)
            total += weight
            chosen.extend(cover)
        return total, chosen

    before, cover = cover_bound(edges_by_cell)
    if float(before) != saved["vertex_cover_bound"]:
        raise SystemExit("recomputed cover disagrees with the saved bound")
    selected = sorted(
        {single_block_actions[b][0] for b in cover}
        | {i for i in range(len(actions)) if i not in block_of}
    )

    started = time.monotonic()
    with budget_scope(budget_s):
        witnesses = _collision_search(
            polytope, family, actions, selected, LIMIT_MARGIN_K,
            FEASIBILITY_TOLERANCE, None, True,
        )

    # Candidate pairs: a survivor supported on exactly two blocks of one cell, with zero sum.
    candidates: set[tuple[int, int]] = set()
    for witness in witnesses:
        delta = witness.safe_power_w - witness.unsafe_power_w
        support = [i for i, v in enumerate(delta) if abs(v) > SUPPORT_FLOOR_W]
        if len(support) != 2:
            continue
        left, right = sorted(support)
        if cell_of[left] != cell_of[right]:
            continue
        if abs(delta[left] + delta[right]) > SUPPORT_FLOOR_W:
            continue
        if (left, right) not in known:
            candidates.add((left, right))

    # Re-prove each through the SAME exact path the original edges used. A survivor is a proposal;
    # nothing is added on the strength of the LP alone.
    recovered: list[tuple[int, int]] = []
    unproved = 0
    for left, right in sorted(candidates):
        # EXHAUSTIVE over every reject cell. The first version fell back to the pair's own two
        # points whenever `points > 8`, which is weaker than even the original eight-point leverage
        # scan -- so "could not be re-proved" meant only "not found in two of 237 points", and peer
        # review was right that the conclusion drawn from it was unsupported. With twenty candidates
        # the full scan is affordable, and it is the only version whose negatives mean anything.
        specs = tuple((m, q) for m in range(models) for q in range(points))
        witness = certify_blind_pair(
            polytope, family, actions, (left, right), single_block_actions,
            specs, LIMIT_MARGIN_K, FEASIBILITY_TOLERANCE,
        )
        if witness is None:
            unproved += 1
            continue
        recovered.append((left, right))
        edges_by_cell.setdefault(cell_of[left], []).append((left, right))
        saved["cuts"].append(list(witness.cut_action_ids))

    after, _ = cover_bound(edges_by_cell)
    if out_path is not None and recovered:
        saved["vertex_cover_bound"] = float(after)
        out_path.write_text(json.dumps(saved))

    print(json.dumps({
        "candidate": candidate, "workload": workload,
        "surviving_collisions": len(witnesses),
        "two_block_within_cell_candidates": len(candidates),
        "recovered_edges": len(recovered),
        "candidates_not_reprovable": unproved,
        "reject_cells_scanned_per_candidate": models * points,
        "lower_bound_before": float(before),
        "lower_bound_after": float(after),
        "gain": float(after - before),
        "elapsed_s": round(time.monotonic() - started, 1),
        "note": (
            "every recovered edge was re-proved through the exact path -- repaired to exact "
            "polytope feasibility, validated with zero slack, cut recomputed -- so the new bound "
            "rests on the same evidence as the old one. A candidate that could not be re-proved is "
            "simply not added -- and since the scan is exhaustive over every reject cell, that "
            "negative now means the pair admits no exactly-shaped, exactly-feasible witness at all, "
            "rather than merely none at the points that were looked at."
        ),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
