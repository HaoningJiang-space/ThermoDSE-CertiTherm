"""Does the chiplet-count crossover survive the complete cost model, and where does it sit?

The proxy result said: the `n=2` versus `n=4` crossover lands in 0.9764-0.9997 with the registered
0.99 inside it. Peer review's objection was that the proxy omitted wafer utilisation, scribe loss,
bumps, substrate area and cost, test and the wasted-die term -- every one count-dependent, any one
able to move a crossover by more than the 0.0136 that separates 0.9764 from 0.99. So the proxy
established that a crossover exists near the registered value, not which side 0.99 falls on.

This probe answers that with the published flow instead (`chiplet_cost.py`, provenance in
`vendor/chiplet-actuary.md`), and it answers it the only way the full model allows: **numerically**.
The closed form `y_b* = (ratio)^(1/(n-m))` belongs to the proxy, where every yield-dependent term
carried the same `1/y_b^n` factor. Under the full flow the substrate defect term and the wasted-chip
term scale with `1/y_b^n` while the raw chip and raw package terms do not, so the tie condition is
no longer a power of a constant ratio and must be scanned.

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

from chiplet_cost import OS_BONDING_YIELD, recurring_cost

# Each swept one at a time around the registered value, over a range a reader can defend.
SENSITIVITY = {
    "defect_density_per_cm2": (0.04, 0.06, 0.08, 0.11, 0.16),
    "wafer_cost_usd": (2000.0, 3000.0, 3984.0, 6000.0, 9000.0),
    "area_scale": (2.0, 3.0, 4.0, 6.0, 8.0),
    "bump_cost_factor": (0.001, 0.0025, 0.005, 0.01, 0.02),
    "re_cost_factor": (0.001, 0.0025, 0.005, 0.01, 0.02),
}
BONDING_GRID = [1.0 - i / 2000.0 for i in range(0, 401)]      # 1.000 down to 0.800 in 0.0005 steps


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

    previous = None
    for y_b in BONDING_GRID:
        fine_wins = (
            objective(fine["die_areas_mm2"], fine["energy_delay"], y_b, **overrides)
            < objective(coarse["die_areas_mm2"], coarse["energy_delay"], y_b, **overrides)
        )
        if previous is not None and fine_wins != previous:
            return {"critical_bonding_yield": y_b, "finer_wins_above": fine_wins}
        previous = fine_wins
    return {"critical_bonding_yield": None, "finer_wins_everywhere": bool(previous)}


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
        robust = max(members, key=lambda r: r["beta_star_l1"] if r["beta_star_l1"] else -1.0)

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
                        "critical_bonding_yield": swept["critical_bonding_yield"],
                        "finer_wins_at_registered_bonding": fine_better,
                    })
            winners = {entry["finer_wins_at_registered_bonding"] for entry in moved}
            pairs.append({
                "dies_coarse": coarse["dies"], "dies_fine": fine["dies"],
                "registered": base,
                "order_is_stable_under_every_swept_factor": len(winners) == 1,
                "sensitivity": moved,
            })

        verdicts.append({
            "tiles": list(key[0]), "workload": key[1],
            "dies_at_registered_cost": at_registered["dies"],
            "dies_most_robust": robust["dies"],
            "cost_choice_matches_robust": at_registered["dies"] == robust["dies"],
            "pairs": pairs,
        })
        print(
            "%-6s %-12s  cost->n=%-2d  robust->n=%-2d  %s" % (
                "%dx%d" % key[0], key[1], at_registered["dies"], robust["dies"],
                "  ".join(
                    "%d/%d:%s%s" % (
                        p["dies_coarse"], p["dies_fine"],
                        "%.4f" % p["registered"]["critical_bonding_yield"]
                        if p["registered"]["critical_bonding_yield"] is not None
                        else ("finer-always" if p["registered"].get("finer_wins_everywhere")
                              else "coarser-always"),
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
    print(
        "\n%d of %d cut pairs change their winner under at least one swept cost factor.\n"
        "The full-cost choice coincides with the robustness choice in %d of %d groups."
        % (unstable, total_pairs, matches, len(verdicts)),
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
