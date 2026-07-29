"""How fast does the certified lower bound grow with the number of discovered cuts?

`docs/CERTIFIED_GAP_IS_FORMULATIONAL.md` asserts that constraint generation over enumerated
confusable pairs "converges arbitrarily slowly" here. That is an assertion. This measures it.

Accumulate cuts exactly as the production loop does, and at geometric checkpoints evaluate
the EXACT hitting-set optimum over the cuts held so far. Both quantities are valid global
lower bounds -- every discovered cut is necessary for every sufficient plan, so an optimum
over a subset cannot exceed the true optimum.

The output is a growth curve. If the exact bound grows logarithmically in the cut count, the
number of cuts required to reach the certified upper bound can be extrapolated, and the
claim becomes a number rather than an adjective. If it grows linearly, the formulation is
fine and the budget is the problem -- the opposite conclusion, and the reason this is worth
measuring rather than arguing.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/bound_growth_probe.py <artifact-root> \
        <candidate> <package> <workload> [total_s] [master_s]
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
    _anytime_lower_bound,
    _collision,
    _greedy_cover,
    _insert_minimal_cut,
    _solve_master,
    separating_action_cut,
)

MARGIN_K = 1e-4
FEASIBILITY_TOLERANCE = 1e-10
CHECKPOINTS = (125, 250, 500, 1000, 2000, 4000, 8000, 16000)


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    total_s = float(sys.argv[5]) if len(sys.argv) > 5 else 1800.0
    master_s = float(sys.argv[6]) if len(sys.argv) > 6 else 300.0

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
        "total_s": total_s, "checkpoints": list(CHECKPOINTS),
    }, indent=2), flush=True)

    cuts: list = []
    masks: list = []
    ledger = CutLedger()
    selected: tuple = ()
    pending = list(CHECKPOINTS)
    started = time.monotonic()
    stopped = "budget"

    while time.monotonic() - started < total_s:
        witness = _collision(
            polytope, family, actions, selected, MARGIN_K, FEASIBILITY_TOLERANCE, 1
        )
        if witness is None:
            stopped = "no collision -- the cover certifies"
            break
        ledger.generated += 1
        cut = separating_action_cut(witness, actions, selected)
        if not np.any(cut):
            stopped = "UNSYNTHESIZABLE witness"
            break
        _insert_minimal_cut(cuts, cut, masks, ledger)
        selected = _greedy_cover(costs, cuts)

        if pending and len(cuts) >= pending[0]:
            checkpoint = pending.pop(0)
            record = {
                "checkpoint": checkpoint,
                "cuts_active": len(cuts),
                "cuts_generated": ledger.generated,
                "accumulate_seconds": round(time.monotonic() - started, 1),
                "greedy_cover_cost": float(costs[list(selected)].sum()),
                "weak_duality_bound": _anytime_lower_bound(costs, cuts),
            }
            master_started = time.monotonic()
            try:
                with budget_scope(master_s):
                    master = _solve_master(costs, cuts)
                record["exact_master_lower_bound"] = float(master.lower_bound)
                record["exact_master_cost"] = float(master.cost)
                record["exact_master_actions"] = len(master.selected)
            except Exception as exc:
                record["exact_master_error"] = f"{type(exc).__name__}: {exc}"[:120]
            record["master_seconds"] = round(time.monotonic() - master_started, 1)
            print(json.dumps(record), flush=True)
            # The master solve consumes wall clock that is not accumulation; extend so the
            # curve is measured against cuts, not against a budget the probe itself spent.
            started += time.monotonic() - master_started

    print(json.dumps({
        "stopped_because": stopped,
        "final_cuts_active": len(cuts),
        "final_cuts_generated": ledger.generated,
        "checkpoints_not_reached": pending,
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
