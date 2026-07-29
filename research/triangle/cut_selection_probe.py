"""Does WHICH cut you keep change the exponent, or only the constant?

`docs/CERTIFIED_GAP_IS_FORMULATIONAL.md` measures the certified lower bound growing as
-22.8 + 4.67 log2(n) in the number of cuts, along the trajectory the production loop follows:
greedy cover, one arbitrary collision, one cut. The collision LP has a zero objective, so the
witness it returns is arbitrary among the feasible ones.

That leaves one question open, and it is the only place an algorithmic contribution could
still live inside this formulation: is the logarithm a property of the CUTS, or of the
ARBITRARY ORDER in which they are discovered?

Exhaustive separation already returns one collision per reject cell -- hundreds at a time --
so candidate cuts are free once the batch is paid for. This compares what a fixed budget of
cuts buys under different selection rules, all drawn from the SAME batch so the separation
cost is identical and only the choice differs:

  * `arbitrary`      -- deterministic spec order, what the loop takes today;
  * `max_min_cost`   -- the cut whose CHEAPEST separating action is most expensive, i.e. the
                        one that forces the most spending whichever action is bought;
  * `min_width`      -- the narrowest cut, i.e. the fewest ways to satisfy it;
  * `least_redundant`-- greedy max-coverage of previously-unforced actions, against the cuts
                        already kept.

For each rule and each prefix length, the EXACT hitting-set optimum over the kept cuts is a
valid global lower bound. If the informative rules reach at a hundred cuts what arbitrary
needs six hundred for, selection is worth a constant; if they reach materially higher values
that arbitrary never approaches, it may be worth an exponent. Either answer is decisive.

NON-CLAIM diagnostic. Reads committed artifacts, writes nothing.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/cut_selection_probe.py <artifact-root> \
        <candidate> <package> <workload> [warmup_cuts] [master_s]
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
    _collisions,
    _greedy_cover,
    _insert_minimal_cut,
    _solve_master,
    separating_action_cut,
)

MARGIN_K = 1e-4
FEASIBILITY_TOLERANCE = 1e-10
PREFIXES = (25, 50, 100, 200, 400)


def _order(rule: str, cuts: list, costs: np.ndarray) -> list:
    """Indices of `cuts` in the order this rule would keep them."""

    if rule == "arbitrary":
        return list(range(len(cuts)))
    if rule == "max_min_cost":
        # Cheapest separator in each cut, descending: a cut whose cheapest option is
        # expensive forces spending no matter which action is bought.
        key = [float(costs[np.flatnonzero(c)].min()) if np.any(c) else 0.0 for c in cuts]
        return sorted(range(len(cuts)), key=lambda i: -key[i])
    if rule == "min_width":
        return sorted(range(len(cuts)), key=lambda i: int(np.count_nonzero(cuts[i])))
    if rule == "least_redundant":
        # Greedy: repeatedly take the cut sharing fewest actions with the union kept so far.
        remaining = set(range(len(cuts)))
        union = np.zeros_like(cuts[0])
        order = []
        while remaining:
            best = min(
                remaining,
                key=lambda i: (float(np.dot(cuts[i], union)), int(np.count_nonzero(cuts[i]))),
            )
            order.append(best)
            remaining.discard(best)
            union = np.maximum(union, cuts[best])
        return order
    raise SystemExit(f"unknown rule {rule!r}")


def main() -> None:
    artifacts = Path(sys.argv[1])
    candidate, package, workload = sys.argv[2], sys.argv[3], sys.argv[4]
    warmup_cuts = int(sys.argv[5]) if len(sys.argv) > 5 else 200
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

    # Warm up along the production trajectory so the batch is drawn at a realistic point,
    # not from the empty selection where every action still separates everything.
    warm: list = []
    masks: list = []
    ledger = CutLedger()
    selected: tuple = ()
    started = time.monotonic()
    while len(warm) < warmup_cuts:
        witness = _collision(
            polytope, family, actions, selected, MARGIN_K, FEASIBILITY_TOLERANCE, 1
        )
        if witness is None:
            break
        cut = separating_action_cut(witness, actions, selected)
        if not np.any(cut):
            break
        _insert_minimal_cut(warm, cut, masks, ledger)
        selected = _greedy_cover(costs, warm)
    warm_seconds = round(time.monotonic() - started, 1)

    # One exhaustive batch from that selection: every reject cell at once.
    started = time.monotonic()
    batch = _collisions(
        polytope, family, actions, selected, MARGIN_K, FEASIBILITY_TOLERANCE, None
    )
    batch_seconds = round(time.monotonic() - started, 1)
    candidates = [separating_action_cut(w, actions, selected) for w in batch]
    candidates = [c for c in candidates if np.any(c)]

    print(json.dumps({
        "candidate": candidate, "package": package, "workload": workload,
        "library_actions": len(actions), "library_cost": float(costs.sum()),
        "warmup_cuts_kept": len(warm), "warmup_seconds": warm_seconds,
        "warmup_cover_cost": float(costs[list(selected)].sum()),
        "batch_witnesses": len(batch), "batch_usable_cuts": len(candidates),
        "batch_seconds": batch_seconds,
        "prefixes": list(PREFIXES),
    }, indent=2), flush=True)

    for rule in ("arbitrary", "max_min_cost", "min_width", "least_redundant"):
        order = _order(rule, candidates, costs)
        for prefix in PREFIXES:
            if prefix > len(order):
                break
            kept: list = []
            kept_masks: list = []
            for index in order[:prefix]:
                _insert_minimal_cut(kept, candidates[index], kept_masks, None)
            record = {"rule": rule, "prefix": prefix, "cuts_kept_after_antichain": len(kept)}
            started = time.monotonic()
            try:
                with budget_scope(master_s):
                    master = _solve_master(costs, kept)
                record["exact_master_lower_bound"] = float(master.lower_bound)
                record["exact_master_actions"] = len(master.selected)
            except Exception as exc:
                record["exact_master_error"] = f"{type(exc).__name__}: {exc}"[:120]
            record["master_seconds"] = round(time.monotonic() - started, 1)
            print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
