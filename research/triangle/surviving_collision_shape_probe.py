"""What SHAPE are the collisions the blind-direction cover cannot separate?

The cover is necessary but not sufficient: 432 collisions survive it on arch_a. That is a fact about
the pairwise argument, not about the instance, and the surviving witnesses say exactly which
directions it cannot reach. This probe reads that structure rather than guessing at it.

Three questions decide what the next cut family is:

* **How wide is the delta's support?** A blind direction between two blocks is a pair. If the
  survivors are supported on three or more blocks of ONE cell with zero sum, the pairwise graph is
  simply the 2-uniform slice of a hypergraph, and the next family is the higher-arity one.
* **Does the support stay inside one cell?** If it crosses cells, a coarse action reads it and the
  cut contains something cheap, which caps what any structural argument can charge for it.
* **What is in the exact cut?** A cut of only single-block actions is chargeable at 8.0 each. A cut
  containing one coarse action is hittable for 1.0 and contributes almost nothing.

Reported as distributions, not as a headline. The point is to choose the next construction from what
the instance actually contains.

NON-CLAIM diagnostic. Reads committed artifacts and one saved cut file; writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/surviving_collision_shape_probe.py <artifact-root> \\
        <candidate> <package> <workload> <seed-cuts.json> [budget_s]
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.blind_direction_cuts import (
    blind_direction_cells,
    block_instrumentation_cost,
    minimum_weight_vertex_cover,
)
from CertiTherm.certificate import separator_set
from CertiTherm.experiments import _measurement_costs, _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import build_measurement_library
from CertiTherm.solver_budget import budget_scope
from CertiTherm.synthesis import _collision_search

LIMIT_MARGIN_K = 0.05
FEASIBILITY_TOLERANCE = 1e-9
# The LP satisfies its constraints to a residual, so a delta component below this is noise rather
# than support. Chosen two orders above the feasibility tolerance so it cannot swallow a real move.
SUPPORT_FLOOR_W = 1e-7


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    seeds_path = Path(sys.argv[5])
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
    actions = build_measurement_library(
        candidate, blocks, floorplan_text, architectures[candidate], _measurement_costs()
    )
    index_of = {action.action_id: i for i, action in enumerate(actions)}
    single_block_actions, cells = blind_direction_cells(actions, len(blocks))
    cost = block_instrumentation_cost(actions, single_block_actions, range(len(blocks)))
    # The probes below index a block by its FIRST single-block action. Peer review found that this
    # silently misclassifies a block's second single-block action as coarse, charges the cover the
    # first action's cost rather than the cheapest, and can parse a saved cut into more than two
    # endpoints. The current library happens to have exactly one per block; relying on that without
    # saying so is the defect, so it is asserted.
    multi_action_blocks = {b: v for b, v in single_block_actions.items() if len(v) != 1}
    if multi_action_blocks:
        raise SystemExit(
            f"{len(multi_action_blocks)} block(s) have more than one single-block action; the "
            "block-to-action map used here assumes exactly one and would misclassify the rest"
        )
    if len(index_of) != len(actions):
        raise SystemExit("action IDs are not unique; the id-to-index map would overwrite entries")
    block_of = {indices[0]: block for block, indices in single_block_actions.items()}
    cell_of = {block: i for i, cell in enumerate(cells) for block in cell}

    saved = json.loads(seeds_path.read_text())
    edges_by_cell: dict[int, list[tuple[int, int]]] = {}
    for cut in saved["cuts"]:
        pair = sorted(block_of[index_of[name]] for name in cut)
        edges_by_cell.setdefault(cell_of[pair[0]], []).append((pair[0], pair[1]))
    cover: list[int] = []
    for cell_index, edges in sorted(edges_by_cell.items()):
        cover.extend(minimum_weight_vertex_cover(cells[cell_index], edges, cost)[1])
    coarse = {i for i in range(len(actions)) if i not in block_of}
    selected = sorted({single_block_actions[b][0] for b in cover} | coarse)

    started = time.monotonic()
    with budget_scope(budget_s):
        witnesses = _collision_search(
            polytope, family, actions, selected, LIMIT_MARGIN_K,
            FEASIBILITY_TOLERANCE, None, True,
        )
    scan_seconds = round(time.monotonic() - started, 1)

    # How far past its tolerance does the WORST SELECTED action read? A selected action satisfies
    # |a.delta| <= tol only to the LP's feasibility slack, so a survivor whose worst selected ratio
    # sits just above 1.0 is a tolerance-boundary artifact rather than a structurally new collision.
    # 416 of 432 exact cuts contained a coarse action the plan had already selected, which is only
    # possible that way -- so this ratio decides whether the real blocker is 432 collisions or 16.
    selected_set = set(selected)
    boundary = genuine = 0
    worst_ratios: list[float] = []
    support_sizes: Counter = Counter()
    cut_sizes: Counter = Counter()
    within_one_cell = coarse_in_cut = 0
    zero_sum_within_cell = 0
    uncovered_blocks: Counter = Counter()
    for witness in witnesses:
        delta = witness.safe_power_w - witness.unsafe_power_w
        support = [i for i, value in enumerate(delta) if abs(value) > SUPPORT_FLOOR_W]
        support_sizes[len(support)] += 1
        cut = separator_set(
            tuple(Fraction(float(v)) for v in witness.safe_power_w),
            tuple(Fraction(float(v)) for v in witness.unsafe_power_w),
            actions,
            Fraction(0),
        )
        cut_sizes[len(cut)] += 1
        ratios = [
            abs(float(actions[i].vector @ delta)) / actions[i].tolerance
            for i in cut
            if i in selected_set and actions[i].tolerance > 0
        ]
        worst = max(ratios) if ratios else 0.0
        worst_ratios.append(worst)
        if set(cut) & selected_set:
            boundary += 1
        else:
            genuine += 1
        if set(cut) & coarse:
            coarse_in_cut += 1
        cells_touched = {cell_of[b] for b in support}
        if len(cells_touched) == 1:
            within_one_cell += 1
            if abs(sum(delta[b] for b in support)) <= SUPPORT_FLOOR_W:
                zero_sum_within_cell += 1
        for block in support:
            if block not in set(cover):
                uncovered_blocks[block] += 1

    print(json.dumps({
        "candidate": candidate, "workload": workload,
        "selected_actions": len(selected),
        "surviving_collisions": len(witnesses),
        "scan_seconds": scan_seconds,
        "delta_support_sizes": dict(sorted(support_sizes.items())),
        "exact_cut_sizes": dict(sorted(cut_sizes.items())),
        "supported_within_one_cell": within_one_cell,
        "within_one_cell_and_zero_sum": zero_sum_within_cell,
        "cuts_containing_a_coarse_action": coarse_in_cut,
        "cuts_meeting_the_selection_at_all": boundary,
        "cuts_disjoint_from_the_selection": genuine,
        "worst_selected_ratio_over_tolerance": {
            "max": max(worst_ratios) if worst_ratios else 0.0,
            "median": sorted(worst_ratios)[len(worst_ratios) // 2] if worst_ratios else 0.0,
            "above_10x": sum(1 for r in worst_ratios if r > 10.0),
        },
        "distinct_uncovered_blocks_touched": len(uncovered_blocks),
        "most_frequent_uncovered_blocks": [
            [blocks[b], n] for b, n in uncovered_blocks.most_common(8)
        ],
        "reading": (
            "support size 2 within one cell would mean the pair scan MISSED edges; three or more "
            "with zero sum means the pairwise graph is the 2-uniform slice of a hypergraph and the "
            "next family is higher arity; a cut containing a coarse action is hittable for 1.0 and "
            "caps what any structural argument can charge for it. A cut MEETING the selection is "
            "only possible at the LP's tolerance boundary, since a selected action is constrained "
            "to read zero; if those ratios sit near 1.0 the survivor is numerical, and the real "
            "structural blocker is the disjoint count, not the total"
        ),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
