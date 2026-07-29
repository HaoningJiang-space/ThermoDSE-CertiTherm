"""At what instance size does exact DSOS synthesis actually terminate?

Every run in this project's records is UNRESOLVED. The dev split's candidates are all 227-237
blocks, so the question "how large an instance can this method prove optimal" has no answer
here -- and any statement about the method needs one. A method that never returns OPTIMAL is
not characterised by its bounds; it is characterised by where it stops working.

This builds well-formed DSOS instances of increasing size from the SAME committed operator by
restricting to the first k blocks: the response submatrix, the power polytope on those blocks,
and the actions whose support lies inside them. The result is a smaller real instance, not the
real problem -- the physics of a 16-block restriction is not the physics of the chip. What it
measures is the ALGORITHM's frontier, which is what a scaling claim needs and what no
measurement in this repository currently provides.

Reports, per size: status, exact cost when OPTIMAL, certified lower bound, iterations, and
seconds. The interesting number is the largest k that returns OPTIMAL.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/tractability_frontier_probe.py <artifact-root> \
        <candidate> <package> <workload> [sizes] [per_size_s]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily
from CertiTherm.experiments import _measurement_costs, _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import build_measurement_library
from CertiTherm.solver_budget import budget_scope
from CertiTherm.synthesis import synthesize_minimum_observation

MARGIN_K = 1e-4
FEASIBILITY_TOLERANCE = 1e-10
DEFAULT_SIZES = (4, 6, 8, 12, 16, 24, 32, 48, 64)


def _restrict(polytope: PowerPolytope, family: ThermalFamily, actions, blocks: int):
    """A well-formed DSOS instance on the first `blocks` blocks of a real operator.

    The polytope keeps its per-block bounds and is given a total-power cap scaled by the
    retained fraction, so the restricted instance is feasible and non-degenerate rather than
    inheriting a cap that the smaller box cannot reach.

    Actions are kept only when their support lies entirely inside the retained blocks: a
    truncated action would measure something the restricted instance does not contain, which
    would be a different observation, not a smaller one.
    """

    lower = polytope.lower_w[:blocks]
    upper = polytope.upper_w[:blocks]
    total = float(upper.sum()) * 0.5
    small_polytope = PowerPolytope.box_with_total(np.array(lower), np.array(upper), total)

    response = np.array(family.response_k_per_w[:, :blocks, :blocks])
    ambient = np.array(family.ambient_k[:, :blocks])
    small_family = ThermalFamily(
        family.model_ids,
        response,
        ambient,
        float(family.limit_k),
        error_k=np.array(family.error_k),
    )

    kept = []
    for action in actions:
        vector = action.vector
        if vector.shape[0] < blocks or np.any(vector[blocks:] != 0.0):
            continue
        kept.append(
            MeasurementAction(
                action.action_id,
                np.array(vector[:blocks]),
                float(action.cost),
                float(action.tolerance),
                action.candidate_id,
            )
        )
    return small_polytope, small_family, tuple(kept)


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    sizes = (
        tuple(int(v) for v in sys.argv[5].split(","))
        if len(sys.argv) > 5
        else DEFAULT_SIZES
    )
    per_size_s = float(sys.argv[6]) if len(sys.argv) > 6 else 300.0

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

    print(json.dumps({
        "candidate": candidate, "package": package, "workload": workload,
        "full_blocks": int(family.blocks), "full_actions": len(actions),
        "sizes": list(sizes), "per_size_budget_s": per_size_s,
    }, indent=2), flush=True)

    largest_optimal = None
    for size in sizes:
        if size > family.blocks:
            break
        small_polytope, small_family, kept = _restrict(polytope, family, actions, size)
        record = {"blocks": size, "actions": len(kept)}
        if not kept:
            record["status"] = "SKIPPED: no action supported inside this restriction"
            print(json.dumps(record), flush=True)
            continue
        started = time.monotonic()
        try:
            with budget_scope(per_size_s):
                plan = synthesize_minimum_observation(
                    small_polytope, small_family, kept, max_iterations=500000
                )
            record["status"] = plan.status
            record["exact_cost"] = plan.exact_cost
            record["lower_bound"] = plan.lower_bound
            record["iterations"] = plan.iterations
            record["cuts_active"] = plan.cuts_active
            if plan.status == "OPTIMAL":
                largest_optimal = size
        except Exception as exc:
            record["status"] = f"RAISED {type(exc).__name__}"
            record["message"] = str(exc)[:140]
        record["seconds"] = round(time.monotonic() - started, 1)
        record["largest_optimal_so_far"] = largest_optimal
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
