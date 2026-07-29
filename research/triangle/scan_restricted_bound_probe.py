"""A certified lower bound from a RELAXED instance: full SAFE rows, restricted reject scan.

An earlier attempt restricted the ThermalFamily to a few reject cells and reported the result
as a lower bound on the whole instance. That was wrong and is retracted
(`docs/PER_CELL_DECOMPOSITION_RETRACTED.md`): restricting the family also drops those cells'
SAFE rows, and SAFE is a conjunction over every (model, point), so the safe set GROWS and the
restricted problem is not a relaxation. Measured counterexample: a four-cell instance
certifying at 0.0 whose one-cell restriction costs 6.0.

`reject_specs` restricts only which cells the separation oracle SCANS. Every SAFE row still
binds, so the safe set is unchanged and fewer reject options can only make separation easier:

    C*(whole)  >=  C*(scan-restricted)

That property is checked in `CertiTherm/tests/test_cell_subset_bound.py` -- restricting the
scan never raises the optimum, widening it is monotone, and scanning every cell reproduces the
unrestricted optimum exactly -- BEFORE any number is reported from it here. Skipping that
check is what invalidated the previous attempt.

Reports, per scan width: certified lower bound, status, iterations, and seconds. Any bound
reported is a valid bound on the real instance.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/scan_restricted_bound_probe.py <artifact-root> \
        <candidate> <package> <workload> [widths] [per_width_s]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.experiments import _measurement_costs, _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import build_measurement_library
from CertiTherm.solver_budget import budget_scope
from CertiTherm.synthesis import synthesize_minimum_observation

DEFAULT_WIDTHS = (1, 2, 4, 8)


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    widths = (
        tuple(int(v) for v in sys.argv[5].split(","))
        if len(sys.argv) > 5
        else DEFAULT_WIDTHS
    )
    per_width_s = float(sys.argv[6]) if len(sys.argv) > 6 else 600.0

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
    models, points = family.response_k_per_w.shape[0], family.response_k_per_w.shape[1]

    print(json.dumps({
        "candidate": candidate, "package": package, "workload": workload,
        "models": models, "points": points, "reject_cells_total": models * points,
        "library_actions": len(actions),
        "widths": list(widths), "per_width_budget_s": per_width_s,
        "note": "every SAFE row binds; only the reject scan is restricted",
    }, indent=2), flush=True)

    best = 0.0
    for width in widths:
        count = min(width, points)
        chosen = (
            [(0, round(i * (points - 1) / max(1, count - 1))) for i in range(count)]
            if count > 1
            else [(0, 0)]
        )
        chosen = sorted(set(chosen))
        record = {"scan_width": len(chosen)}
        started = time.monotonic()
        try:
            with budget_scope(per_width_s):
                plan = synthesize_minimum_observation(
                    polytope,
                    family,
                    actions,
                    max_iterations=500000,
                    reject_specs=tuple(chosen),
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
        record["best_valid_global_lower_bound"] = round(best, 2)
        print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
