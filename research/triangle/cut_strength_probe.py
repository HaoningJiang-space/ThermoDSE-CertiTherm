"""Why do 23 309 accumulated cuts certify a lower bound of only 88 against U = 4174?

A hitting-set cut is a disjunction -- "buy at least one action from this set" -- so its
strength as a constraint is inverse to its WIDTH. A cut naming 200 actions is satisfied by
the cheapest one of them and constrains the optimum almost not at all. Accumulating more
such cuts cannot help: the dev run generated 25 532 of them across 41 iterations, kept
23 309 after domination, and still bounded the optimum at 88 while the width baseline
certified a plan costing 4174.

The suspicion this probe tests is structural, not numerical. The collision LP is built with
`objective = zeros(2n)` -- a pure feasibility problem. It therefore returns AN arbitrary
collision, never the one whose cut is hardest to cover, so nothing in the loop steers
separation toward constraints that would actually raise the bound.

Measures, on one real committed operator:
  * the width of each discovered cut, absolutely and as a fraction of the library;
  * the cost of the cheapest action in each cut, which is what a fractional cover pays;
  * the resulting greedy cover cost, for scale against the certified U.

NON-CLAIM diagnostic. Reads committed artifacts only and writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/cut_strength_probe.py <artifact-root> <candidate> \
        <package> <workload> [seconds]
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
from CertiTherm.synthesis import _collision, separating_action_cut

MARGIN_K = 1e-4
FEASIBILITY_TOLERANCE = 1e-10


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    seconds = float(sys.argv[5]) if len(sys.argv) > 5 else 180.0

    power, blocks, _placed, floorplan_text = _power_space(
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
    library_cost = sum(action.cost for action in actions)

    widths: list[int] = []
    cheapest: list[float] = []
    selected: list[int] = []
    started = time.monotonic()
    stop = "budget"
    while time.monotonic() - started < seconds:
        witness = _collision(
            power, family, actions, tuple(selected), MARGIN_K, FEASIBILITY_TOLERANCE, 1
        )
        if witness is None:
            stop = "no further collision -- the current selection already certifies"
            break
        cut = separating_action_cut(witness, actions, tuple(selected))
        covering = np.flatnonzero(cut)
        if covering.size == 0:
            stop = "an unseparable witness -- UNSYNTHESIZABLE"
            break
        widths.append(int(covering.size))
        costs = [actions[int(i)].cost for i in covering]
        cheapest.append(float(min(costs)))
        # Greedy: buy the cheapest action that covers this cut, exactly as _greedy_cover
        # does, so the accumulated cost is comparable with the reported policy costs.
        selected.append(int(covering[int(np.argmin(costs))]))

    widths_array = np.asarray(widths, dtype=float)
    print(
        json.dumps(
            {
                "candidate": candidate,
                "package": package,
                "workload": workload,
                "blocks": int(family.blocks),
                "models": len(family.model_ids),
                "library_actions": len(actions),
                "library_cost": library_cost,
                "cuts_discovered": int(widths_array.size),
                "stopped_because": stop,
                "cut_width_min": int(widths_array.min()) if widths_array.size else None,
                "cut_width_median": float(np.median(widths_array))
                if widths_array.size
                else None,
                "cut_width_max": int(widths_array.max()) if widths_array.size else None,
                "median_width_as_fraction_of_library": float(
                    np.median(widths_array) / len(actions)
                )
                if widths_array.size
                else None,
                "median_cheapest_action_in_cut": float(np.median(cheapest))
                if cheapest
                else None,
                "greedy_cover_cost": float(
                    sum(actions[index].cost for index in selected)
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
