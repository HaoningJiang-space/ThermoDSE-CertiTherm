"""The instrumentation tier a decision needs is a STEP function of the power-model accuracy.

The question DSOS asks is "which observations are decision-sufficient". Answered per instance that
is a number, and a number is not a method. This probe measures the thing that IS one: the answer is
a step function of a single physically meaningful parameter, with two computable breakpoints.

Let `U(b)` be the uncertainty set at radius `b`, selected by argv and RECORDED in every output row:

    relocation  the largest box inscribed in `|p - q|_1 <= 2 b sum(q)` -- a SUBSET of the L1
                transfer ball, so a bound proved on it is also a bound for the L1 problem
    deviation   the L-infinity ball of half-width `b sum(q)` -- a SUPERSET of that ball, whose
                bounds do NOT transfer to an L1 statement

Both are intersected with the total-power plane and the nonnegative orthant, and both are NESTED in
`b`, so anything measured on them is monotone and two breakpoints separate three tiers:

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

`b_reach` is a robustness radius of the same family as the ones in
`docs/THERMAL_ROBUSTNESS_RADII.md`, measured on whichever set was selected. That it is ALSO the
point at which observation becomes necessary is not a coincidence and needs no experiment: below it
the REJECT set is empty, so there is nothing to distinguish. `b_blind` is the new quantity, and it
is the one that decides whether a designer needs post-route per-block power extraction or can stop
at the reports an architecture-stage flow already produces.

Two assumptions are load-bearing in the first tier and are stated rather than left implicit. The
empty plan certifies only because SAFE is the complement of REJECT under the registered margin --
`reject_cell_rows` and the SAFE conjunction partition the admissible maps, with the fail-closed
margin folded one-sidedly into REJECT -- and because the nominal map itself is admitted at every
radius, so the SAFE side is non-empty. Neither survives a formulation with an indifference band
between the two, and this probe does not have one.

`b_reach <= b_blind` holds by construction: a blind pair contains a REJECT map, so it cannot exist
before REJECT maps do. The gap between them is the range of power-model accuracy over which cheap
instrumentation is provably enough, and it is what a designer actually wants to know.

## The asymmetry that makes only ONE of the two breakpoints a proof

`b_reach` is decided by an exact maximisation and is a genuine breakpoint. `b_blind` is NOT
symmetric, and an earlier version of this docstring claimed a bracket it cannot support:

* an EXACTLY VALIDATED blind witness at radius `b` proves the true breakpoint is AT MOST `b`;
* a failure to find one proves NOTHING. The collision search may have returned a point on the LP's
  feasibility boundary that exact recomputation rejects -- the same failure that produced 425
  numerically unresolved survivors in `docs/BLIND_DIRECTION_BOUND.md` -- or it may have timed out.

So there is no lower bound on `b_blind` here, and the honest structure is FOUR states, not three:
the fourth is `UNRESOLVED`, which the repository's fail-closed contract requires and which the
earlier version silently folded into "coarse suffices". A step whose search is unresolved must not
advance the not-blind endpoint, because doing so would widen the interval over which cheap
instrumentation is claimed sufficient -- and that is the fail-OPEN direction. It now refuses.

## What makes a blindness witness count

A witness counts only when its cut, recomputed from the returned delta, contains NO coarse action:
that is what "the coarse library reads them identically" means, and it is checked rather than
assumed. `exhaustive` is on, so every collision the search returns is examined -- checking only the
first would report "not blind" whenever the first happened to be a boundary artifact, which is what
the first run of this probe did on five of six instances.

A pair that no action in the library separates is NOT discarded. It is stronger evidence than
blindness, not weaker: it means the registered library cannot certify the decision at any price, so
it is recorded as `unsynthesizable` and reported separately.

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
from CertiTherm.measurements import (
    build_measurement_library,
    deviation_bounded_power_space,
    relocation_bounded_power_space,
)
from CertiTherm.solver_budget import budget_scope
from CertiTherm.synthesis import UnresolvedComputation, _collision_search
from CertiTherm.thermal_constraints import reject_cell_rows

MARGIN_K = 0.05
FEASIBILITY_TOLERANCE = 1e-9
BISECTION_STEPS = 14
COLLISION_BUDGET_S = 900.0
# Which uncertainty set the tiers are measured on, selected by argv. `relocation` is the box
# INSCRIBED in the L1 transfer ball, so its bounds transfer to an L1 statement; `deviation` is the
# L-infinity superset, whose bounds do not. Reporting one under the other's name was the error peer
# review found, so the choice is recorded in every output row rather than left implicit.
SPACES = {
    "relocation": (relocation_bounded_power_space, "relocated_fraction"),
    "deviation": (deviation_bounded_power_space, "deviation_fraction"),
}
GEOMETRY = "relocation"


def reject_reachable(rows, floors, placed, radius, build_space, radius_key) -> bool:
    """Is any map in U(beta) REJECT?  Exact, by greedy fill -- no solver.

    Maximising a linear form over {lower <= p <= upper, sum p = total} is solved exactly by
    filling the largest coefficients to their upper bound from the all-lower start, because the
    single equality makes the feasible set a transportation polytope whose vertices are reached
    that way. Exact for the BOX; the box is whatever `build_space` returns, so this answers the
    reachability question for the same set the collision search is run on and the two cannot drift
    apart. Radius zero is the nominal map itself, which is why it is passed through unmodified
    rather than through a builder that refuses a non-positive fraction.
    """

    total = float(placed.sum())
    if radius <= 0.0:
        upper = lower = placed.copy()
    else:
        space = build_space(placed, **{radius_key: radius})
        upper = np.asarray(space.upper_w, dtype=float)
        lower = np.asarray(space.lower_w, dtype=float)
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

    Returns one of `"blind"`, `"unsynthesizable"`, `"separable"` or `"unresolved"`.

    `"separable"` -- the ONLY verdict that lets the bisection advance its not-blind endpoint --
    requires the search to have completed AND every returned collision to be separated by some
    coarse action under exact recomputation. Anything else is `"unresolved"`, because a search that
    died, timed out, or returned only boundary artifacts has established nothing about whether a
    blind pair exists.
    """

    try:
        with budget_scope(budget_s):
            witnesses = _collision_search(
                polytope, family, actions, coarse, MARGIN_K,
                FEASIBILITY_TOLERANCE, None, True,
            )
    except UnresolvedComputation:
        return "unresolved"
    if not witnesses:
        return "separable"
    boundary_artifacts = 0
    for witness in witnesses:
        delta = np.asarray(witness.safe_power_w) - np.asarray(witness.unsafe_power_w)
        # The cut recomputed from the delta itself, not the one the LP reported. An action is in
        # the cut when it reads the direction above its own tolerance.
        reads = {
            index: abs(float(np.asarray(actions[index].vector) @ delta))
            > actions[index].tolerance
            for index in list(coarse) + list(single_block)
        }
        if any(reads[index] for index in coarse):
            # A SELECTED action reads this delta, so the returned point violates a constraint the
            # collision LP imposed: it is a feasibility-boundary artifact, not a separable pair.
            # Counting it as evidence that coarse reports suffice is exactly the fail-open error.
            boundary_artifacts += 1
            continue
        if not any(reads[index] for index in single_block):
            # No action in the library separates the pair at all. Stronger than blindness: the
            # decision cannot be certified from this library at any price.
            return "unsynthesizable"
        return "blind"
    return "unresolved" if boundary_artifacts else "separable"


def main() -> None:
    artifacts = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    global GEOMETRY
    GEOMETRY = sys.argv[4] if len(sys.argv) > 4 else "relocation"
    if GEOMETRY not in SPACES:
        raise SystemExit(f"unknown geometry {GEOMETRY!r}; choose from {sorted(SPACES)}")
    build_space, radius_key = SPACES[GEOMETRY]
    if len(sys.argv) > 3 and sys.argv[3] != "-":
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

        # e_reach: the smallest radius at which any admissible map is REJECT.
        #
        # The nominal map itself is the b = 0 member, so `reject_reachable(..., 0.0)` answers
        # whether the DESIGN is nominally infeasible. Bisecting without that test would return a
        # small positive value after a finite number of halvings and fabricate a safe interval
        # below it -- peer review found this in both this probe and `architecture_sweep.radii`.
        if reject_reachable(rows, floors, placed, 0.0, build_space, radius_key):
            reach = 0.0
        elif not reject_reachable(rows, floors, placed, 1.0, build_space, radius_key):
            reach = float("inf")
        else:
            lo, hi = 0.0, 1.0
            for _ in range(BISECTION_STEPS + 6):
                mid = 0.5 * (lo + hi)
                if reject_reachable(rows, floors, placed, mid, build_space, radius_key):
                    hi = mid
                else:
                    lo = mid
            reach = hi

        # e_blind: the smallest radius at which a coarse-blind SAFE/REJECT pair is ESTABLISHED.
        # Only established witnesses move it, and only a `separable` verdict may advance the
        # not-blind endpoint. An `unresolved` step stops the bisection instead of being read as
        # "coarse suffices here" -- that reading is the fail-open direction.
        blind = float("inf")
        unsynthesizable_at = float("inf")
        ladder = []
        unresolved_steps = 0

        def probe(radius):
            verdict = coarse_blind(
                build_space(placed, **{radius_key: radius}),
                family, actions, coarse, single_block, COLLISION_BUDGET_S,
            )
            ladder.append({"radius": radius, "verdict": verdict})
            return verdict

        if reach > 0.0 and np.isfinite(reach):
            top = probe(1.0)
            if top == "unsynthesizable":
                unsynthesizable_at = 1.0
            if top in ("blind", "unsynthesizable"):
                blind = 1.0
                lo, hi = reach, 1.0
                for _ in range(BISECTION_STEPS):
                    mid = 0.5 * (lo + hi)
                    verdict = probe(mid)
                    if verdict in ("blind", "unsynthesizable"):
                        hi = blind = mid
                        if verdict == "unsynthesizable":
                            unsynthesizable_at = min(unsynthesizable_at, mid)
                    elif verdict == "separable":
                        lo = mid
                    else:
                        unresolved_steps += 1
                        break
            elif top == "unresolved":
                unresolved_steps += 1

        # The tier a designer reads off, with UNRESOLVED as a first-class state.
        if reach == 0.0:
            tier = "NOMINALLY_INFEASIBLE"
        elif not np.isfinite(reach):
            tier = "NO_MEASUREMENT_NEEDED_AT_ANY_RADIUS"
        elif np.isfinite(blind):
            tier = "PER_BLOCK_REQUIRED_ABOVE_E_BLIND"
        elif unresolved_steps:
            tier = "UNRESOLVED"
        else:
            tier = "COARSE_SUFFICIENT_THROUGH_RADIUS_1"

        row = {
            "candidate": candidate, "package": package, "workload": workload,
            "blocks": len(blocks), "coarse_actions": len(coarse),
            "single_block_actions": len(single_block),
            # Named for the geometry it is actually measured on. `relocation_bounded_power_space`
            # returns the BOX implied by the transfer budget, not the L1 body: an L-infinity ball of
            # half-width `e * total` intersected with the total-power plane. The exact L1 radius is
            # a DIFFERENT number (`research/triangle/robustness/geometries.py:radius_l1`) and the
            # two must not be reported under one name -- they were, and the box value is the smaller
            # of the two on every instance measured.
            "geometry": GEOMETRY,
            "epsilon_reach": reach,
            "epsilon_blind": blind,
            "epsilon_unsynthesizable": unsynthesizable_at,
            "tier": tier,
            "unresolved_steps": unresolved_steps,
            "coarse_sufficient_window": (
                blind - reach if np.isfinite(blind) and np.isfinite(reach) else None
            ),
            "ladder": ladder,
            "elapsed_s": round(time.monotonic() - started, 1),
        }
        results.append(row)
        print(
            "%-8s %-9s %-12s  e_reach %8s   e_blind %8s   %-34s (%.0fs)" % (
                candidate, package, workload,
                "%7.3f%%" % (reach * 100) if np.isfinite(reach) else "none",
                "%7.3f%%" % (blind * 100) if np.isfinite(blind) else "none",
                tier, row["elapsed_s"],
            ),
            flush=True,
        )
        out_path.write_text(json.dumps(results, indent=1))

    print(json.dumps({"instances": len(results), "out": str(out_path)}), flush=True)


if __name__ == "__main__":
    main()
