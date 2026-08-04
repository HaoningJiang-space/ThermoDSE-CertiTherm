"""A/B the two separation policies through the PRODUCTION entry point, on real artifacts.

The dev run's exact synthesizer never completed a single candidate: 1800 s, 41 iterations,
25 532 cuts, 0 of 3 candidates done, certified lower bound 88 against upper bound 4174. A
separate first-collision probe certified one whole candidate with 190 cuts in under 180 s.

That comparison was between two DIFFERENT loops, so it proved nothing about the production
one. This driver runs `synthesize_minimum_observation` itself, twice, on the same candidate,
changing only `separation_policy`. Whatever it shows is a property of the shipped algorithm.

Both policies use the same exhaustive scan to conclude that NO collision exists, so the
termination test -- and with it `OPTIMAL` and `UNSYNTHESIZABLE` -- is identical. Only the
number of constraints harvested per iteration differs.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/separation_policy_ab.py <artifact-root> \
        <candidate> <package> <workload> [budget_s]
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


def _run(policy: str, polytope, family, actions, budget_s: float) -> dict:
    started = time.monotonic()
    try:
        with budget_scope(budget_s):
            plan = synthesize_minimum_observation(
                polytope, family, actions, separation_policy=policy
            )
        elapsed = time.monotonic() - started
        return {
            "policy": policy,
            "status": plan.status,
            "exact_cost": plan.exact_cost,
            "lower_bound": plan.lower_bound,
            "iterations": plan.iterations,
            "cuts_generated": plan.cuts_generated,
            "cuts_active": plan.cuts_active,
            "seconds": round(elapsed, 1),
            "message": (plan.message or "")[:160],
        }
    except Exception as exc:                       # a diagnostic must report, not vanish
        return {
            "policy": policy,
            "status": f"RAISED {type(exc).__name__}",
            "seconds": round(time.monotonic() - started, 1),
            "message": str(exc)[:160],
        }


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    budget_s = float(sys.argv[5]) if len(sys.argv) > 5 else 900.0

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

    header = {
        "candidate": candidate,
        "package": package,
        "workload": workload,
        "blocks": int(family.blocks),
        "models": len(family.model_ids),
        "library_actions": len(actions),
        "library_cost": sum(action.cost for action in actions),
        "budget_s": budget_s,
    }
    print(json.dumps(header, indent=2))
    # Lazy first: if the frozen policy exhausts the budget, its result is still reported.
    for policy in ("lazy", "exhaustive"):
        print(json.dumps(_run(policy, polytope, family, actions, budget_s), indent=2))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
