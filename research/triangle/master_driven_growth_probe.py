"""Is the logarithmic bound growth a property of the problem, or of the greedy trajectory?

Every measurement behind `docs/CERTIFIED_GAP_IS_FORMULATIONAL.md` drives separation from
`_greedy_cover`, which always buys the cheapest covering action. The selection therefore stays
cheap, and every witness it finds is one more thing a cheap plan fails to distinguish. If the
logarithm is an artifact of that, the negative result is about the implementation's search
strategy and not about the formulation, and it is overclaimed.

The alternative is the standard cutting-plane step: separate the MASTER's optimum. That plan
is the cheapest consistent with all evidence so far, so a witness against it is violated by
the current optimum by construction -- the usual reason branch-and-cut converges where greedy
enumeration does not. `synthesize_minimum_observation` never does this during ordinary
iterations; `_solve_master` is reached only on the collision-free branch.

This runs both trajectories on the same instance and reports the exact hitting-set optimum at
the same cut counts, so the curves are directly comparable. Master solves are excluded from
the accumulation clock.

Master-driven accumulation is far more expensive per cut, so both runs are capped at a cut
count where the master still solves quickly.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/master_driven_growth_probe.py <artifact-root> \
        <candidate> <package> <workload> [max_cuts] [master_s]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.experiments import _measurement_costs, _power_space, _rows, ROOT
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import build_measurement_library
from CertiTherm.solver_budget import budget_scope
from CertiTherm.synthesis import (
    CutLedger,
    _collision,
    _greedy_cover,
    _insert_minimal_cut,
    _solve_master,
    separating_action_cut,
)

MARGIN_K = 1e-4
FEASIBILITY_TOLERANCE = 1e-10
CHECKPOINTS = (125, 250, 500, 1000)


def _trajectory(driver: str, polytope, family, actions, costs, max_cuts, master_s) -> list:
    """Accumulate cuts, separating either the greedy cover or the master's optimum."""

    cuts: list = []
    masks: list = []
    ledger = CutLedger()
    selected: tuple = ()
    pending = list(CHECKPOINTS)
    records: list = []
    accumulate = 0.0

    while len(cuts) < max_cuts and pending:
        started = time.monotonic()
        witness = _collision(
            polytope, family, actions, selected, MARGIN_K, FEASIBILITY_TOLERANCE, 1
        )
        accumulate += time.monotonic() - started
        if witness is None:
            records.append({"driver": driver, "stopped": "no collision", "cuts": len(cuts)})
            break
        cut = separating_action_cut(witness, actions, selected)
        if not np.any(cut):
            records.append({"driver": driver, "stopped": "unseparable", "cuts": len(cuts)})
            break
        started = time.monotonic()
        # `generated` is incremented by the caller in production, so it is counted here too
        # rather than left at zero, which would read as "no cuts were produced".
        ledger.generated += 1
        _insert_minimal_cut(cuts, cut, masks, ledger)
        accumulate += time.monotonic() - started

        if driver == "greedy":
            selected = _greedy_cover(costs, cuts)
        else:
            try:
                with budget_scope(master_s):
                    selected = _solve_master(costs, cuts).selected
            except Exception:
                # A master that will not solve cannot drive the trajectory; fall back so the
                # run reports what it reached rather than dying, and say so.
                selected = _greedy_cover(costs, cuts)
                records.append({"driver": driver, "note": "master fell back to greedy",
                                "cuts": len(cuts)})

        if pending and len(cuts) >= pending[0]:
            checkpoint = pending.pop(0)
            record = {
                "driver": driver,
                "checkpoint": checkpoint,
                "cuts_active": len(cuts),
                "cuts_generated": ledger.generated,
                "accumulate_seconds": round(accumulate, 1),
                "current_cover_cost": float(costs[list(selected)].sum()) if len(selected) else 0.0,
            }
            started = time.monotonic()
            try:
                with budget_scope(master_s):
                    master = _solve_master(costs, cuts)
                record["exact_master_lower_bound"] = float(master.lower_bound)
                record["exact_master_actions"] = len(master.selected)
            except Exception as exc:
                record["exact_master_error"] = f"{type(exc).__name__}: {exc}"[:100]
            record["master_seconds"] = round(time.monotonic() - started, 1)
            records.append(record)
            print(json.dumps(record), flush=True)
    return records


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    max_cuts = int(sys.argv[5]) if len(sys.argv) > 5 else 1000
    master_s = float(sys.argv[6]) if len(sys.argv) > 6 else 120.0

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
    costs = np.asarray([action.cost for action in actions])
    print(json.dumps({
        "candidate": candidate, "package": package, "workload": workload,
        "library_actions": len(actions), "library_cost": float(costs.sum()),
        "max_cuts": max_cuts, "checkpoints": list(CHECKPOINTS),
    }, indent=2), flush=True)

    for driver in ("greedy", "master"):
        print(json.dumps({"trajectory": driver}), flush=True)
        _trajectory(driver, polytope, family, actions, costs, max_cuts, master_s)


if __name__ == "__main__":
    main()
