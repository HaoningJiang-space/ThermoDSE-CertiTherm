"""Does the chiplet-count crossover survive the complete cost model, and where does it sit?

The proxy result said: the `n=2` versus `n=4` crossover lands in 0.9764-0.9997 with the registered
0.99 inside it. Peer review's objection was that the proxy omitted wafer utilisation, scribe loss,
bumps, substrate area and cost, test and the wasted-die term -- every one count-dependent, any one
able to move a crossover by more than the 0.0136 that separates 0.9764 from 0.99. So the proxy
established that a crossover exists near the registered value, not which side 0.99 falls on.

This probe answers that with the transcribed recurring-cost model instead (`chiplet_cost.py`,
provenance in `vendor/chiplet-actuary.md`).

**It is answered in closed form, and an earlier version of this docstring was wrong about why it
could not be.** That version claimed the tie had to be scanned because the substrate-defect and
wasted-chip terms scale with `1/y_b^n` while the raw terms do not. The individual terms do differ;
their SUM does not. With `K` the chip terms, `P` the raw package and `L = y_b^(-n) - 1`,

    K + P + P L + K L = (K + P)(1 + L) = (K + P) y_b^(-n)

so the total is a bonding-yield-independent base times `y_b^(-n)` and the tie is a root, exactly as
for the proxy. Peer review found the error. The scan is retained ALONGSIDE the root as a
cross-check -- two implementations, one algebraic and one enumerative -- and any disagreement is
raised rather than reconciled. A scan alone was also unable to distinguish "no crossing" from "a
crossing outside my grid", which the root classifies.

Two questions, and the second is the one that decides whether the first means anything:

1. At the registered parameters, which cut minimises `energy x delay x recurring cost`, and where
   does the crossover in bonding yield sit?
2. Does that crossover stay inside `(0, 1]` -- and does the ORDER of the cuts at the registered
   0.99 stay the same -- as each omitted cost factor is swept across its plausible range? A boundary
   that moves out of the attainable range under a defensible parameter change was never a boundary,
   and saying so is the point of running this.

NON-CLAIM diagnostic. Reads a sweep and its captures; writes one JSON.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/cost_crossover.py <sweep.json> <capture-dir> \\
        [out.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chiplet_cost import (
    OS_BONDING_YIELD,
    base_cost,
    critical_bonding_yield,
    recurring_cost,
)

# Each swept one at a time around the registered value, over a range a reader can defend.
SENSITIVITY = {
    "defect_density_per_cm2": (0.04, 0.06, 0.08, 0.11, 0.16),
    "wafer_cost_usd": (2000.0, 3000.0, 3984.0, 6000.0, 9000.0),
    "area_scale": (2.0, 3.0, 4.0, 6.0, 8.0),
    "bump_cost_factor": (0.001, 0.0025, 0.005, 0.01, 0.02),
    "re_cost_factor": (0.001, 0.0025, 0.005, 0.01, 0.02),
}
BONDING_GRID = [1.0 - i / 2000.0 for i in range(0, 401)]      # 1.000 down to 0.800 in 0.0005 steps
JOINT_SAMPLES = 4000
JOINT_SEED = 20260801
# Bonding yield joins the joint sweep as a sixth factor; it is scanned separately for the crossover
# but must vary WITH the others when the question is how often each cut wins.
JOINT_RANGES = dict(SENSITIVITY, bonding_yield=(0.95, 1.0))


def objective(die_areas_mm2, energy_delay, bonding_yield, **overrides) -> float:
    """`energy x delay x recurring cost of one working system`.

    The analogue of `E D / Y` with a cost per working system in place of a yield probability, which
    is what the published model actually produces. Units are joule-seconds-dollars and are only ever
    compared within one decision group, never across grids.
    """

    cost = recurring_cost(die_areas_mm2, bonding_yield=bonding_yield, **overrides)
    return energy_delay * cost["recurring_total"]


def crossover(members, coarse, fine, **overrides):
    """The largest bonding yield at which the FINER cut stops winning, scanned not solved.

    Returns `None` when the order never changes across the grid, with the side it stays on -- a
    non-crossing pair is a result, not a gap, and reporting it as a boundary would be the error the
    proxy version made when it printed 1.0025.
    """

    # The exact root first. `metric` is the objective with the `y_b^(-n)` factor divided out.
    exact = critical_bonding_yield(
        coarse["energy_delay"] * base_cost(coarse["die_areas_mm2"], **overrides),
        fine["energy_delay"] * base_cost(fine["die_areas_mm2"], **overrides),
        coarse["dies"], fine["dies"],
    )
    inside = 0.0 < exact <= 1.0

    # The scan, kept as an independent cross-check of the root rather than as the answer.
    scanned = None
    previous = None
    for y_b in BONDING_GRID:                       # descends from 1.00 to 0.80
        fine_wins = (
            objective(fine["die_areas_mm2"], fine["energy_delay"], y_b, **overrides)
            < objective(coarse["die_areas_mm2"], coarse["energy_delay"], y_b, **overrides)
        )
        if previous is not None and fine_wins != previous:
            # The grid DESCENDS, so `previous` is the state ABOVE this point. Reporting `fine_wins`
            # -- the state below -- as "wins above" inverted the label; peer review caught it.
            scanned = {"critical_bonding_yield": y_b, "finer_wins_above": previous}
            break
        previous = fine_wins
    if scanned is None:
        scanned = {"critical_bonding_yield": None, "finer_wins_over_scanned_grid": bool(previous)}

    agree = (
        scanned["critical_bonding_yield"] is not None
        and abs(scanned["critical_bonding_yield"] - exact) <= 2.0 / len(BONDING_GRID)
    ) or (scanned["critical_bonding_yield"] is None and not (min(BONDING_GRID) <= exact <= 1.0))
    if not agree:
        raise RuntimeError(
            f"the exact root {exact} and the scan {scanned} disagree; one of the two "
            "implementations of the same tie is wrong and neither may be reported"
        )

    return {
        "critical_bonding_yield_exact": exact,
        "inside_physical_range": inside,
        "classification": (
            "crossover" if inside else
            ("coarser_wins_at_every_attainable_bonding_yield" if exact > 1.0 else "degenerate")
        ),
        "scanned": scanned,
    }


def joint_sweep(members, rng):
    """How often does each cut win when EVERY factor moves at once?

    One-at-a-time sweeps answer "is this decision fragile to any single assumption", which is the
    weaker question: they cannot see a combination where two factors cancel, and they cannot say how
    much of the plausible space each option owns. Sampling the box jointly answers both, and it is
    the version a reader should be given when the conclusion is "the decision is not determined by
    the cost model".

    Uniform over each factor's own range, which is a stated prior and not a measured one -- the
    ranges come from the published parameter file's own spread across nodes and package types, and a
    different prior would give different shares. What does NOT depend on the prior is whether any
    option owns the whole box.
    """

    wins = {member["dies"]: 0 for member in members}
    for _ in range(JOINT_SAMPLES):
        draw = {}
        for name, values in JOINT_RANGES.items():
            low, high = min(values), max(values)
            draw[name] = float(rng.uniform(low, high))
        bonding = draw.pop("bonding_yield")
        best = min(
            members,
            key=lambda r: objective(r["die_areas_mm2"], r["energy_delay"], bonding, **draw),
        )
        wins[best["dies"]] += 1
    return {n: c / JOINT_SAMPLES for n, c in wins.items()}


def main() -> None:
    sweep_path = Path(sys.argv[1])
    captures = Path(sys.argv[2])
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    points = json.loads(sweep_path.read_text())
    rows = []
    for point in points:
        with np.load(
            captures / f"{point['workload']}--{point['arch']}.npz", allow_pickle=False
        ) as data:
            heights = np.asarray(data["die_h_list_m"], dtype=float)
            widths = np.asarray(data["die_w_list_m"], dtype=float)
            energy_delay = float(data["latency_ms"]) * float(data["energy_mj"])
        # metres to millimetres, which is the unit the published flow is written in.
        areas = (np.outer(heights, widths).reshape(-1) * 1e6).tolist()
        rows.append({
            "arch": point["arch"], "tiles": point["tiles"], "workload": point["workload"],
            "dies": point["dies"], "die_areas_mm2": areas, "energy_delay": energy_delay,
            "beta_star_l1": point.get("beta_star_l1"),
            "cost": recurring_cost(areas),
        })

    groups: dict = {}
    for row in rows:
        groups.setdefault((tuple(row["tiles"]), row["workload"]), []).append(row)

    verdicts = []
    for key, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(members) < 2:
            continue
        members.sort(key=lambda r: r["dies"])
        at_registered = min(
            members,
            key=lambda r: objective(r["die_areas_mm2"], r["energy_delay"], OS_BONDING_YIELD),
        )
        # `is not None`, not truthiness: a radius of exactly 0.0 is a real measurement -- the
        # design is nominally infeasible -- and reading it as missing would rank it last by accident.
        robust = max(
            members,
            key=lambda r: r["beta_star_l1"] if r["beta_star_l1"] is not None else -1.0,
        )

        pairs = []
        for coarse, fine in zip(members, members[1:]):
            base = crossover(members, coarse, fine)
            # One factor at a time. If the winner at the registered bonding yield flips under a
            # defensible value of any single omitted term, the boundary is a proxy artefact and the
            # honest report is that the decision is not determined by cost either.
            moved = []
            for name, values in SENSITIVITY.items():
                for value in values:
                    swept = crossover(members, coarse, fine, **{name: value})
                    fine_better = (
                        objective(fine["die_areas_mm2"], fine["energy_delay"],
                                  OS_BONDING_YIELD, **{name: value})
                        < objective(coarse["die_areas_mm2"], coarse["energy_delay"],
                                    OS_BONDING_YIELD, **{name: value})
                    )
                    moved.append({
                        "factor": name, "value": value,
                        "critical_bonding_yield_exact": swept["critical_bonding_yield_exact"],
                        "inside_physical_range": swept["inside_physical_range"],
                        "finer_wins_at_registered_bonding": fine_better,
                    })
            winners = {entry["finer_wins_at_registered_bonding"] for entry in moved}
            pairs.append({
                "dies_coarse": coarse["dies"], "dies_fine": fine["dies"],
                "registered": base,
                "order_is_stable_under_every_swept_factor": len(winners) == 1,
                "sensitivity": moved,
            })

        shares = joint_sweep(members, np.random.default_rng(JOINT_SEED))
        verdicts.append({
            "tiles": list(key[0]), "workload": key[1],
            "joint_sweep_win_share": shares,
            "joint_sweep_samples": JOINT_SAMPLES,
            "any_cut_owns_the_whole_box": max(shares.values()) == 1.0,
            "dies_at_registered_cost": at_registered["dies"],
            "dies_most_robust": robust["dies"],
            "cost_choice_matches_robust": at_registered["dies"] == robust["dies"],
            "pairs": pairs,
        })
        print(
            "%-6s %-12s  cost->n=%-2d  robust->n=%-2d  joint[%s]  %s" % (
                "%dx%d" % key[0], key[1], at_registered["dies"], robust["dies"],
                " ".join("%d:%.0f%%" % (n, 100 * f) for n, f in sorted(shares.items())),
                "  ".join(
                    "%d/%d:%s%s" % (
                        p["dies_coarse"], p["dies_fine"],
                        "%.4f" % p["registered"]["critical_bonding_yield_exact"]
                        if p["registered"]["inside_physical_range"]
                        else "y*=%.4f(outside)" % p["registered"]["critical_bonding_yield_exact"],
                        "" if p["order_is_stable_under_every_swept_factor"] else "*UNSTABLE",
                    )
                    for p in pairs
                ),
            ),
            flush=True,
        )

    unstable = sum(
        1 for v in verdicts for p in v["pairs"]
        if not p["order_is_stable_under_every_swept_factor"]
    )
    total_pairs = sum(len(v["pairs"]) for v in verdicts)
    matches = sum(1 for v in verdicts if v["cost_choice_matches_robust"])
    owned = sum(1 for v in verdicts if v["any_cut_owns_the_whole_box"])
    print(
        "\n%d of %d cut pairs change their winner under at least one swept cost factor.\n"
        "Under the JOINT sweep of all six factors, %d of %d groups have a single cut winning "
        "every one of the %d samples; in the rest the decision is split.\n"
        "The full-cost choice coincides with the robustness choice in %d of %d groups."
        % (unstable, total_pairs, owned, len(verdicts), JOINT_SAMPLES, matches, len(verdicts)),
        flush=True,
    )
    if out_path is not None:
        out_path.write_text(json.dumps(
            {"bonding_yield_registered": OS_BONDING_YIELD, "sensitivity_grid": SENSITIVITY,
             "verdicts": verdicts,
             "points": [{k: v for k, v in r.items() if k != "die_areas_mm2"} for r in rows]},
            indent=1,
        ))


if __name__ == "__main__":
    main()
