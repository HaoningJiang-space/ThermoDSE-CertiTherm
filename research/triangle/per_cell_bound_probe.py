"""A non-enumerative lower bound: solve ONE reject cell exactly and take it as a bound.

`docs/CERTIFIED_GAP_IS_FORMULATIONAL.md` establishes that the global enumerated bound is
capped near 32 against an upper bound near 1450. Every attack on that was measured and
failed. What follows is not another attack; it is a different bound.

The observation is elementary and does not enumerate confusable pairs. A plan sufficient for
the whole instance is sufficient for any SUBSET of its reject cells, because dropping cells
only removes constraints. So for any single cell,

    C*(whole instance)  >=  C*(that cell alone),

and the right-hand side is a global lower bound obtained without discovering a single
cross-cell witness. Taking the maximum over cells strengthens it further.

Why this might be tractable where the whole instance is not: the whole instance carries
3 x 227 = 681 reject cells, and the separation oracle must clear all of them every iteration.
One cell carries one. If the per-cell problem TERMINATES, its exact optimum is a certified
bound that no amount of global cut accumulation could reach.

Two outcomes, both decisive. If a single cell already costs on the order of the global upper
bound, the certified interval collapses and the decomposition is the result. If single cells
are individually cheap, the difficulty is genuinely joint across cells and this bound is
worth no more than the enumerated one -- which would also explain, mechanistically, why the
global bound saturates.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/per_cell_bound_probe.py <artifact-root> \
        <candidate> <package> <workload> [cells] [per_cell_s] [max_iterations]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.core import ThermalFamily
from CertiTherm.experiments import _measurement_costs, _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import build_measurement_library
from CertiTherm.solver_budget import budget_scope
from CertiTherm.synthesis import synthesize_minimum_observation

MARGIN_K = 1e-4
FEASIBILITY_TOLERANCE = 1e-10


def _single_cell_family(family: ThermalFamily, model: int, point: int) -> ThermalFamily:
    """The same family restricted to one (model, point) reject cell.

    Keeps that cell's response row and its ambient and error entries unchanged, so the SAFE
    and REJECT constraints for the retained cell are bit-identical to the full instance's.
    Dropping the other cells only REMOVES constraints, which is what makes the restricted
    optimum a valid lower bound rather than an approximation.
    """

    response = np.array(family.response_k_per_w[model : model + 1, point : point + 1, :])
    ambient = np.array(family.ambient_k[model : model + 1, point : point + 1])
    return ThermalFamily(
        (family.model_ids[model],),
        response,
        ambient,
        float(family.limit_k),
        error_k=np.array(family.error_k[model : model + 1]),
    )


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    cells = int(sys.argv[5]) if len(sys.argv) > 5 else 8
    per_cell_s = float(sys.argv[6]) if len(sys.argv) > 6 else 120.0
    # The default 10 000 iteration cap, not the time budget, is what stopped the first
    # long run: it reached the cap in 266 s of an 1 800 s budget with the bound still
    # rising. The cap has to be a parameter for the time budget to mean anything here.
    max_iterations = int(sys.argv[7]) if len(sys.argv) > 7 else 10000

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
    by_id = {action.action_id: action for action in actions}
    n_models, n_points = family.response_k_per_w.shape[0], family.response_k_per_w.shape[1]

    print(json.dumps({
        "candidate": candidate, "package": package, "workload": workload,
        "models": n_models, "points": n_points, "reject_cells_total": n_models * n_points,
        "library_actions": len(actions),
        "library_cost": float(sum(a.cost for a in actions)),
        "cells_sampled": cells, "per_cell_budget_s": per_cell_s,
        "max_iterations": max_iterations,
    }, indent=2), flush=True)

    # Spread the sample across the floorplan rather than taking a contiguous prefix: adjacent
    # blocks have near-identical responses, so a prefix would sample one region.
    stride = max(1, (n_models * n_points) // cells)
    best = 0.0
    for flat in range(0, n_models * n_points, stride):
        model, point = flat // n_points, flat % n_points
        restricted = _single_cell_family(family, model, point)
        record = {"model": model, "point": point, "flat_index": flat}
        started = time.monotonic()
        try:
            with budget_scope(per_cell_s):
                plan = synthesize_minimum_observation(
                    polytope, restricted, actions, max_iterations=max_iterations
                )
            record["status"] = plan.status
            record["exact_cost"] = plan.exact_cost
            record["lower_bound"] = plan.lower_bound
            record["iterations"] = plan.iterations
            record["cuts_active"] = plan.cuts_active
            # The working cover at cutoff, and its composition by measurement class. This
            # tests the footprint prediction directly: 90% of a block's temperature comes
            # from ~190 of 227 blocks, so if separation requires resolving the footprint the
            # cover should be dominated by per-block post-route actions and cost on the order
            # of 190 x 8. A cover that is mostly coarse reads would refute that.
            record["candidate_cost"] = plan.candidate_cost
            by_class: dict = {}
            for action_id in plan.candidate_action_ids:
                action_class = action_id.split("::")[1]
                entry = by_class.setdefault(action_class, {"count": 0, "cost": 0.0})
                entry["count"] += 1
                entry["cost"] += by_id[action_id].cost
            record["candidate_cover_by_class"] = by_class
            if plan.status == "OPTIMAL" and plan.exact_cost is not None:
                best = max(best, float(plan.exact_cost))
        except Exception as exc:
            record["status"] = f"RAISED {type(exc).__name__}"
            record["message"] = str(exc)[:120]
        record["seconds"] = round(time.monotonic() - started, 1)
        record["best_certified_lower_bound_so_far"] = best
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
