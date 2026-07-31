"""Does budgeting the discretisation error change any DECISION, or only the numbers?

Every radius this project reported was computed with only the linearisation error budgeted, and
`docs/DISCRETISATION_ERROR_EXCEEDS_THE_DECISION_BAND.md` measures them as overstated by 1.3x on
compact geometry and up to 4.8x on elongated. Propagating that correction is mechanical for the
NUMBERS. What is not mechanical is which CLAIMS survive it, and that turns on one question:

    does the robustness-optimal cut change in any decision group?

Because of how the held-out result landed, that question is unusually narrow. The claims that
survived the preregistered split are P3, P4, P6 and P8 -- the composition and cost results -- and
none of them touches the thermal operator, so budgeting cannot move them. The single survivor that
does touch it is **P5**, "the cost-optimal and robustness-optimal cuts disagree", and P5 depends only
on the ARGMAX of `beta*` within a group, not on its magnitude. A uniform shrink changes no argmax; a
shrink that varies by operator resolution might.

So this compares two `yield_composition` outputs -- one unbudgeted, one budgeted -- and reports
per group whether `dies_most_robust` moved. It deliberately reports the magnitudes too, because a
group whose argmax is preserved by a hair is not the same evidence as one preserved by a mile.

Written and committed while the budgeted sweep was still running and before it had produced a point,
so that the comparison cannot be shaped around what it found.

NON-CLAIM diagnostic.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/budget_impact.py <unbudgeted.json> \\
        <budgeted.json> [out.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _by_group(payload):
    groups: dict = {}
    for point in payload["points"]:
        key = (tuple(point["tiles"]), point["workload"])
        groups.setdefault(key, {})[point["dies"]] = point
    return groups


def main() -> None:
    before = json.loads(Path(sys.argv[1]).read_text())
    after = json.loads(Path(sys.argv[2]).read_text())
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    old, new = _by_group(before), _by_group(after)
    shared = sorted(set(old) & set(new), key=str)
    if not shared:
        raise SystemExit(
            "the two runs share no decision group, so nothing can be compared; check that both "
            "were produced from the same architecture grid"
        )

    def radius(point):
        value = point.get("beta_star_l1")
        return value if value is not None else point.get("epsilon_star")

    rows, changed = [], 0
    for key in shared:
        cuts = sorted(set(old[key]) & set(new[key]))
        if len(cuts) < 2:
            continue
        pick_old = max(cuts, key=lambda n: radius(old[key][n]) or -1.0)
        pick_new = max(cuts, key=lambda n: radius(new[key][n]) or -1.0)
        # The margin the argmax survives by, in the budgeted run: how far the winner leads the
        # runner-up, relative to the winner. A preserved argmax with a 1% lead is much weaker
        # evidence than one with a 50% lead, and reporting only the boolean would hide that.
        ranked = sorted((radius(new[key][n]) or 0.0 for n in cuts), reverse=True)
        lead = (ranked[0] - ranked[1]) / ranked[0] if ranked[0] > 0 else 0.0
        shrink = {
            n: (radius(new[key][n]) or 0.0) / (radius(old[key][n]) or float("inf"))
            for n in cuts
        }
        moved = pick_old != pick_new
        changed += 1 if moved else 0
        rows.append({
            "tiles": list(key[0]), "workload": key[1],
            "robust_cut_unbudgeted": pick_old, "robust_cut_budgeted": pick_new,
            "argmax_changed": moved,
            "budgeted_lead_over_runner_up": lead,
            "radius_retained_by_cut": shrink,
        })
        print(
            "%-6s %-12s  robust n=%d -> n=%d  %-9s lead %5.1f%%  retained %s" % (
                "%dx%d" % key[0], key[1], pick_old, pick_new,
                "CHANGED" if moved else "unchanged", 100 * lead,
                " ".join("n%d:%.0f%%" % (n, 100 * f) for n, f in sorted(shrink.items())),
            ),
            flush=True,
        )

    print(
        "\n%d of %d decision groups change their robustness-optimal cut when the discretisation "
        "error is budgeted.\nP5 -- the only surviving held-out claim that touches the thermal "
        "operator -- depends on this argmax and on nothing else about the radii."
        % (changed, len(rows)),
        flush=True,
    )
    if out_path is not None:
        out_path.write_text(json.dumps({"groups": rows, "argmax_changes": changed}, indent=1))


if __name__ == "__main__":
    main()
