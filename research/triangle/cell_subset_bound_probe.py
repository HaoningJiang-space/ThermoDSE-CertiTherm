"""Does a SUBSET of reject cells bound better than the best single cell?

`docs/PER_CELL_DECOMPOSITION_BOUND.md` uses `C*(whole) >= C*(one cell)` and takes the maximum
over cells. The same subset argument holds for any subset, and a subset is strictly stronger
than the maximum over its members: one plan must separate all of them at once, so

    C*(whole)  >=  C*(subset)  >=  max over members of C*(cell).

`docs/TRACTABILITY_FRONTIER.md` supplies the reason not to simply take the whole thing: cost
explodes with problem size, and the full 681-cell instance is far past where the method
returns anything. A k-cell restriction has k reject cells rather than 681, so there may be a
size at which the bound is much stronger than a single cell's and the instance is still
solvable. That trade is what this measures.

Cells are drawn from ONE model so the per-model error band stays well defined; mixing models
into a synthetic family would silently pick one model's error for another's response row.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/cell_subset_bound_probe.py <artifact-root> \
        <candidate> <package> <workload> [subset_sizes] [per_size_s]
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
DEFAULT_SIZES = (1, 2, 4, 8, 16, 32)


def _cell_subset_family(family: ThermalFamily, model: int, points) -> ThermalFamily:
    """The family restricted to one model and the given evaluation points.

    Dropping cells only removes constraints, so the restricted optimum lower-bounds the
    whole instance's -- the same one-line argument the single-cell bound rests on, applied to
    a set instead of a singleton.
    """

    chosen = list(points)
    response = np.array(family.response_k_per_w[model : model + 1, chosen, :])
    ambient = np.array(family.ambient_k[model : model + 1, chosen])
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
    sizes = (
        tuple(int(v) for v in sys.argv[5].split(","))
        if len(sys.argv) > 5
        else DEFAULT_SIZES
    )
    per_size_s = float(sys.argv[6]) if len(sys.argv) > 6 else 600.0

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
    n_points = family.response_k_per_w.shape[1]

    print(json.dumps({
        "candidate": candidate, "package": package, "workload": workload,
        "model": 0, "points_available": n_points,
        "library_actions": len(actions),
        "subset_sizes": list(sizes), "per_size_budget_s": per_size_s,
    }, indent=2), flush=True)

    best = 0.0
    for size in sizes:
        if size > n_points:
            break
        # Point 0 is in every subset, so each size strictly contains the previous one and the
        # bounds are directly comparable: a larger subset can only be harder to separate.
        count = min(size, n_points)
        chosen = [round(i * (n_points - 1) / max(1, count - 1)) for i in range(count)] \
            if count > 1 else [0]
        chosen = sorted(set(chosen))
        restricted = _cell_subset_family(family, 0, chosen)
        record = {"subset_size": len(chosen), "requested": size}
        started = time.monotonic()
        try:
            with budget_scope(per_size_s):
                plan = synthesize_minimum_observation(
                    polytope, restricted, actions, max_iterations=500000
                )
            record["status"] = plan.status
            record["exact_cost"] = plan.exact_cost
            record["lower_bound"] = plan.lower_bound
            record["iterations"] = plan.iterations
            record["cuts_active"] = plan.cuts_active
            if plan.lower_bound is not None:
                best = max(best, float(plan.lower_bound))
        except Exception as exc:
            record["status"] = f"RAISED {type(exc).__name__}"
            record["message"] = str(exc)[:140]
        record["seconds"] = round(time.monotonic() - started, 1)
        record["best_global_lower_bound_so_far"] = round(best, 2)
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
