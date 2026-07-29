"""Is the certified lower bound limited by the cuts, or by how the bound is computed?

Measured on the dev split: the loop accumulates ~9 500 active cuts and certifies a lower
bound of 20.5 against an upper bound of ~1450 for the same candidate. Two explanations,
with opposite fixes:

  A. the cuts are weak -- a hitting set over them really is cheap, and no bound computation
     could do better;
  B. the bound computation is weak -- `_anytime_lower_bound` evaluates weak duality from LP
     dual prices used as a guess, and `_solve_master`, the exact MILP over the discovered
     cuts, is reached only on the collision-free branch, which the loop never reaches.

This separates them. It accumulates cuts exactly as the production loop does, then evaluates
BOTH bounds on the SAME cut set:

  * `_anytime_lower_bound(costs, cuts)`  -- what the certificate reports today;
  * `_solve_master(costs, cuts).lower_bound` -- the exact hitting-set optimum over those cuts.

If they agree, A. If the master is far higher, B, and the certificate is leaving proof on
the floor it has already paid for.

Both are valid global lower bounds: every discovered cut is necessary for every feasible
plan, so the optimum over a subset of cuts cannot exceed the true optimum.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/bound_ceiling_probe.py <artifact-root> \
        <candidate> <package> <workload> [accumulate_s] [master_s]
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


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    accumulate_s = float(sys.argv[5]) if len(sys.argv) > 5 else 300.0
    master_s = float(sys.argv[6]) if len(sys.argv) > 6 else 600.0

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

    # Accumulate exactly as the loop does: greedy cover over the cuts so far, one collision
    # per iteration, minimal-cut insertion with domination.
    cuts: list = []
    masks: list = []
    ledger = CutLedger()
    selected: tuple = ()
    started = time.monotonic()
    stopped = "budget"
    while time.monotonic() - started < accumulate_s:
        witness = _collision(
            polytope, family, actions, selected, MARGIN_K, FEASIBILITY_TOLERANCE, 1
        )
        if witness is None:
            stopped = "no collision -- the current cover already certifies"
            break
        ledger.generated += 1
        cut = separating_action_cut(witness, actions, selected)
        if not np.any(cut):
            stopped = "UNSYNTHESIZABLE witness"
            break
        _insert_minimal_cut(cuts, cut, masks, ledger)
        selected = _greedy_cover(costs, cuts)

    accumulated = round(time.monotonic() - started, 1)
    report = {
        "candidate": candidate,
        "package": package,
        "workload": workload,
        "library_actions": len(actions),
        "library_cost": float(costs.sum()),
        "accumulate_seconds": accumulated,
        "stopped_because": stopped,
        "cuts_generated": ledger.generated,
        "cuts_active": len(cuts),
        "greedy_cover_cost": float(costs[list(selected)].sum()) if len(selected) else 0.0,
    }

    started = time.monotonic()
    report["weak_duality_bound"] = _anytime_lower_bound(costs, cuts)
    report["weak_duality_seconds"] = round(time.monotonic() - started, 1)

    started = time.monotonic()
    try:
        with budget_scope(master_s):
            master = _solve_master(costs, cuts)
        report["exact_master_cost"] = float(master.cost)
        report["exact_master_lower_bound"] = float(master.lower_bound)
        report["exact_master_actions"] = len(master.selected)
    except Exception as exc:
        report["exact_master_cost"] = None
        report["exact_master_error"] = f"{type(exc).__name__}: {exc}"[:200]
    report["exact_master_seconds"] = round(time.monotonic() - started, 1)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
