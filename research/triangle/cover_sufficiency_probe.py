"""Is the blind-direction vertex cover, plus the coarse library, already a CERTIFYING plan?

The cover is NECESSARY: every certifying selection must instrument one endpoint of each confusable
pair, which is what makes it a lower bound. Whether it is also SUFFICIENT is a different question
and the answer decides how much of the remaining gap is real.

On arch_a/default/resnet50 the certified interval is L = 1112.0 against U = 1450. If the cover plus
the fourteen coarse actions separates every collision, then a plan of cost
`8 * |cover| + sum(coarse costs)` is CERTIFIED, U drops to about that, and the interval nearly
closes -- an exact minimum observation cost on a 237-block instance that exact synthesis has never
resolved. If collisions survive, the surviving witnesses say precisely which blocks the pairwise
argument cannot reach, and that is the next structural cut rather than a dead end.

Either outcome is informative, which is why this is worth one scan. It is one separation pass over
a FIXED selection -- no master, no iteration.

Soundness. The selection is built from the cuts saved by `indistinguishable_pair_bound_probe`,
which are action IDs, so the cover is recomputed here rather than trusted. A surviving collision is
reported with its exact separating set; absence of a collision under an exhaustive scan is a real
`CERTIFIED_PLAN` for this instance, and the cost is computed from the action library rather than
assumed.

NON-CLAIM diagnostic. Reads committed artifacts and one saved cut file; writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/cover_sufficiency_probe.py <artifact-root> \\
        <candidate> <package> <workload> <seed-cuts.json> [budget_s]
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
    minimum_weight_vertex_cover,
)
from CertiTherm.experiments import _measurement_costs, _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import build_measurement_library
from CertiTherm.solver_budget import budget_scope
from CertiTherm.synthesis import _collision_search

LIMIT_MARGIN_K = 0.05
FEASIBILITY_TOLERANCE = 1e-9


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
    block_of = {
        indices[0]: block for block, indices in single_block_actions.items()
    }

    # Rebuild the confusability graph from the saved cuts, then recompute each cell's cover here
    # rather than trusting a number carried in the file.
    saved = json.loads(seeds_path.read_text())
    edges_by_cell: dict[int, list[tuple[int, int]]] = {}
    cell_of = {block: i for i, cell in enumerate(cells) for block in cell}
    for cut in saved["cuts"]:
        pair = sorted(block_of[index_of[name]] for name in cut)
        if len(pair) != 2 or cell_of[pair[0]] != cell_of[pair[1]]:
            raise SystemExit(f"saved cut {cut} is not a within-cell pair")
        edges_by_cell.setdefault(cell_of[pair[0]], []).append((pair[0], pair[1]))

    cover: list[int] = []
    total = Fraction(0)
    for cell_index, edges in sorted(edges_by_cell.items()):
        weight, chosen = minimum_weight_vertex_cover(cells[cell_index], edges, cost)
        total += weight
        cover.extend(chosen)

    coarse = [i for i, action in enumerate(actions) if i not in block_of]
    selected = sorted({single_block_actions[b][0] for b in cover} | set(coarse))
    plan_cost = float(sum(Fraction(float(actions[i].cost)) for i in selected))

    print(json.dumps({
        "candidate": candidate, "package": package, "workload": workload,
        "cover_blocks": len(cover),
        "cover_cost": float(total),
        "coarse_actions": len(coarse),
        "selected_actions": len(selected),
        "plan_cost": plan_cost,
        "recomputed_lower_bound": float(total),
        "saved_lower_bound": saved["vertex_cover_bound"],
        "note": (
            "the cover is necessary, so plan_cost is an upper bound ONLY if the scan below finds "
            "no collision; recomputed_lower_bound must equal saved_lower_bound or the graph was "
            "rebuilt wrongly"
        ),
    }, indent=2), flush=True)
    if float(total) != saved["vertex_cover_bound"]:
        raise SystemExit("recomputed cover disagrees with the saved bound")

    started = time.monotonic()
    record: dict = {"scan": "exhaustive", "budget_s": budget_s}
    try:
        with budget_scope(budget_s):
            witnesses = _collision_search(
                polytope,
                family,
                actions,
                selected,
                LIMIT_MARGIN_K,
                FEASIBILITY_TOLERANCE,
                None,
                True,
            )
        record["surviving_collisions"] = len(witnesses)
        if witnesses:
            record["verdict"] = "COVER_IS_NOT_SUFFICIENT"
            sample = witnesses[0]
            record["example_reject_point"] = int(sample.unsafe_point)
            record["example_reject_model"] = sample.unsafe_model_id
        else:
            record["verdict"] = "COVER_PLUS_COARSE_CERTIFIES"
            record["certified_upper_bound"] = plan_cost
            record["interval"] = [float(total), plan_cost]
    except Exception as exc:  # noqa: BLE001 - a probe records the failure, it does not raise
        record["verdict"] = "UNRESOLVED"
        record["detail"] = f"{type(exc).__name__}: {exc}"
    record["elapsed_s"] = round(time.monotonic() - started, 1)
    print(json.dumps(record, indent=2), flush=True)


if __name__ == "__main__":
    main()
