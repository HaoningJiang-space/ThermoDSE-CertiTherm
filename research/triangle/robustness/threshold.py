"""The instrumentation tier a decision needs is a STEP function of the power-model accuracy.

The question DSOS asks is "which observations are decision-sufficient". Answered per instance that
is a number, and a number is not a method. This probe measures the thing that IS one: the answer is
a step function of a single physically meaningful parameter, with two computable breakpoints.

Let `U(b)` be the relocation-bounded uncertainty set -- every power map reachable from the placed
map by relocating at most a fraction `b` of the workload's own total power. The sets are NESTED, so
anything measured on them is monotone in `b`, and two breakpoints separate three tiers:

    b < b_reach              NO measurement is needed.        Every admissible map is SAFE, so the
                                                              empty plan certifies. This direction is
                                                              a proof, not a measurement.
    b_reach <= b < b_blind   COARSE reports suffice.          Some admissible map is REJECT, so
                                                              something must be observed -- but the
                                                              module/chiplet/region library separates
                                                              every SAFE/REJECT pair.
    b >= b_blind             PER-BLOCK extraction is REQUIRED. A SAFE/REJECT pair exists that the
                                                              entire coarse library reads identically;
                                                              no plan built from it can certify, at
                                                              any price.

`b_reach` is the robustness radius `beta*` already reported in `docs/THERMAL_ROBUSTNESS_RADII.md`.
That it is ALSO the point at which observation becomes necessary is not a coincidence and needs no
experiment: below it the REJECT set is empty, so there is nothing to distinguish. `b_blind` is the
new quantity, and it is the one that decides whether a designer needs post-route per-block power
extraction or can stop at the reports an architecture-stage flow already produces.

`b_reach <= b_blind` holds by construction: a blind pair contains a REJECT map, so it cannot exist
before REJECT maps do. The gap between them is the range of power-model accuracy over which cheap
instrumentation is provably enough, and it is what a designer actually wants to know.

## What makes a blindness witness count

A collision LP returns a point, and a point near the feasibility boundary is not a proof -- the
same failure that produced 425 numerically unresolved survivors in `docs/BLIND_DIRECTION_BOUND.md`.
So a witness is counted only when its cut, recomputed exactly from the returned delta, contains NO
coarse action: that is what "the coarse library reads them identically" means, and it is checked
rather than assumed. A witness that fails the check is recorded as unresolved and the bisection
treats the step as NOT blind, which can only push `b_blind` UP -- the conservative direction, since
a larger `b_blind` claims a wider range over which coarse reports suffice...

...which is the DANGEROUS direction, not the safe one. So it is reported both ways: `b_blind` is the
smallest radius at which blindness was ESTABLISHED, and `b_blind_unresolved` is the smallest radius
at which the LP proposed a blind pair that could not be exactly confirmed. The true breakpoint lies
in between, and a designer must use the lower one.

NON-CLAIM diagnostic. Reads committed artifacts; writes one JSON.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/threshold.py <artifact-root> <out.json> \\
        [candidate:package:workload,...]
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
from CertiTherm.measurements import build_measurement_library, relocation_bounded_power_space
from CertiTherm.solver_budget import budget_scope
from CertiTherm.synthesis import UnresolvedComputation, _collision_search
from CertiTherm.thermal_constraints import reject_cell_rows

MARGIN_K = 0.05
FEASIBILITY_TOLERANCE = 1e-9
BISECTION_STEPS = 14
COLLISION_BUDGET_S = 900.0


def reject_reachable(rows: np.ndarray, floors: np.ndarray, placed: np.ndarray, beta: float) -> bool:
    """Is any map in U(beta) REJECT?  Exact, by greedy fill -- no solver.

    Maximising a linear form over {lower <= p <= upper, sum p = total} is solved exactly by
    filling the largest coefficients to their upper bound from the all-lower start, because the
    single equality makes the feasible set a transportation polytope whose vertices are reached
    that way. Using the box implied by the L1 budget is a RELAXATION of the L1 body, so the radius
    this returns is a lower bound on the true one -- and `relocation_bounded_power_space` builds
    the same box, so the two agree by construction rather than by coincidence.
    """

    total = float(placed.sum())
    budget = beta * total
    upper = placed + budget
    lower = np.maximum(placed - budget, 0.0)
    for j in range(rows.shape[0]):
        row = np.asarray(rows[j], dtype=float)
        p = lower.copy()
        spare = total - float(p.sum())
        for i in np.argsort(-row):
            add = min(upper[i] - p[i], spare)
            p[i] += add
            spare -= add
            if spare <= 1e-12:
                break
        if float(row @ p) >= floors[j]:
            return True
    return False


def coarse_blind(polytope, family, actions, coarse, single_block, budget_s):
    """Does a SAFE/REJECT pair exist that every coarse action reads identically?

    Returns (established, proposed). `established` requires the exactly recomputed cut to be
    disjoint from the coarse library; `proposed` counts what the LP returned before that check.
    """

    try:
        with budget_scope(budget_s):
            witnesses = _collision_search(
                polytope, family, actions, coarse, MARGIN_K,
                FEASIBILITY_TOLERANCE, None, False,
            )
    except UnresolvedComputation:
        return None, None
    if not witnesses:
        return False, False
    for witness in witnesses:
        delta = np.asarray(witness.safe_power_w) - np.asarray(witness.unsafe_power_w)
        # The cut recomputed from the delta itself, not the one the LP reported. An action is in
        # the cut when it reads the direction above its own tolerance; if any COARSE action does,
        # the pair is separable by coarse reports and is not evidence of blindness.
        if any(
            abs(float(np.asarray(actions[i].vector) @ delta)) > actions[i].tolerance
            for i in coarse
        ):
            continue
        # ... and the pair must be separable by SOMETHING, or it is a degenerate zero delta.
        if not any(
            abs(float(np.asarray(actions[i].vector) @ delta)) > actions[i].tolerance
            for i in single_block
        ):
            continue
        return True, True
    return False, True


def main() -> None:
    artifacts = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    if len(sys.argv) > 3:
        instances = [tuple(s.split(":")) for s in sys.argv[3].split(",")]
    else:
        instances = [
            (c, "default", w)
            for w in ("resnet50", "transformer")
            for c in ("arch_a", "arch_b", "arch_c")
        ]

    architectures = {
        row["architecture_id"]: row
        for row in _rows(ROOT / "experiments" / "architectures.tsv")
    }
    costs = _measurement_costs()
    results = []

    for candidate, package, workload in instances:
        started = time.monotonic()
        _base, blocks, placed, floorplan_text = _power_space(
            artifacts / "captures" / f"{workload}--{candidate}.npz"
        )
        family, operator_blocks = load_family(
            artifacts / "operators" / f"{candidate}--{package}.npz"
        )
        if blocks != operator_blocks:
            raise SystemExit("power/operator block identity mismatch")
        actions = build_measurement_library(
            candidate, blocks, floorplan_text, architectures[candidate], costs
        )
        placed = np.asarray(placed, dtype=float)
        rows, floors = reject_cell_rows(family, MARGIN_K)
        floors = np.asarray(floors, dtype=float)

        # A single-block action is one whose vector has exactly one nonzero; everything else is a
        # coarse report. The coarse set is what an architecture-stage flow already produces.
        single_block, coarse = [], []
        for index, action in enumerate(actions):
            vector = np.asarray(action.vector)
            (single_block if int(np.count_nonzero(vector)) == 1 else coarse).append(index)

        # b_reach: the smallest radius at which any admissible map is REJECT.
        if not reject_reachable(rows, floors, placed, 1.0):
            reach = float("inf")
        else:
            lo, hi = 0.0, 1.0
            for _ in range(BISECTION_STEPS + 6):
                mid = 0.5 * (lo + hi)
                if reject_reachable(rows, floors, placed, mid):
                    hi = mid
                else:
                    lo = mid
            reach = hi

        # b_blind: the smallest radius at which a coarse-blind SAFE/REJECT pair is ESTABLISHED.
        # Bisected only above b_reach, since blindness is impossible below it.
        blind = float("inf")
        blind_proposed = float("inf")
        ladder = []
        if np.isfinite(reach):
            lo, hi = reach, 1.0
            established_at_top, proposed_at_top = coarse_blind(
                relocation_bounded_power_space(placed, relocated_fraction=hi),
                family, actions, coarse, single_block, COLLISION_BUDGET_S,
            )
            ladder.append({"beta": hi, "established": established_at_top,
                           "proposed": proposed_at_top})
            if established_at_top:
                blind = hi
                for _ in range(BISECTION_STEPS):
                    mid = 0.5 * (lo + hi)
                    established, proposed = coarse_blind(
                        relocation_bounded_power_space(placed, relocated_fraction=mid),
                        family, actions, coarse, single_block, COLLISION_BUDGET_S,
                    )
                    ladder.append({"beta": mid, "established": established, "proposed": proposed})
                    if established:
                        hi = mid
                        blind = mid
                    else:
                        lo = mid
                    if proposed and blind_proposed > mid:
                        blind_proposed = mid

        row = {
            "candidate": candidate, "package": package, "workload": workload,
            "blocks": len(blocks), "coarse_actions": len(coarse),
            "single_block_actions": len(single_block),
            "beta_reach": reach, "beta_blind": blind,
            "beta_blind_first_proposed": blind_proposed,
            "coarse_sufficient_window": (
                blind - reach if np.isfinite(blind) and np.isfinite(reach) else None
            ),
            "ladder": ladder,
            "elapsed_s": round(time.monotonic() - started, 1),
        }
        results.append(row)
        print(
            "%-8s %-9s %-12s  b_reach %7.3f%%   b_blind %s   window %s   (%.0fs)" % (
                candidate, package, workload, reach * 100,
                ("%7.3f%%" % (blind * 100)) if np.isfinite(blind) else "     none",
                ("%7.3f%%" % ((blind - reach) * 100))
                if np.isfinite(blind) and np.isfinite(reach) else "     n/a",
                row["elapsed_s"],
            ),
            flush=True,
        )
        out_path.write_text(json.dumps(results, indent=1))

    print(json.dumps({"instances": len(results), "out": str(out_path)}), flush=True)


if __name__ == "__main__":
    main()
