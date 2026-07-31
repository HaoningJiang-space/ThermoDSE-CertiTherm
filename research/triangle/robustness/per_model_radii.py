"""Is the robustness ordering an artefact of one thermal operator?

The registered family carries three HotSpot operators -- `block`, `grid64-avg`, `grid128-avg` --
and every radius reported elsewhere is a minimum over ALL of them, which is the fail-closed
aggregation but also hides whether they agree. If the ordering of chiplet cuts by `beta*` came from
one operator and the other two disagreed, the claim that the radius orders designs stably would rest
on a modelling choice exactly like the one it criticises in the yield term.

So each operator is scored on its own here, and the question is not whether the radii AGREE
numerically -- they will not, a block model and a 128-cell grid resolve different peaks -- but
whether they induce the same ORDER over the cuts within a decision group. Order is what a decision
consumes.

**This is within-family agreement, not independent validation, and the difference matters.** All
three are HotSpot with the same floorplan, package and boundary conditions, so a systematic error in
that stack moves all three together. An independent simulator would be the real check and is
recorded as blocked rather than skipped: the sibling 3D-ICE adapter cannot represent this package,
whose die, spreader and sink have three distinct footprints while that tool's passive layers share
one global chip footprint (`docs/` and the withdrawn independent-model gate). Truncating them to the
die footprint adds about 2.57 K of series copper against a 0.095 K margin. So the honest statement is
that the ordering survives every operator this project can legitimately run, and that the family is
one linear stack.

`grid256` is calibration-only and is not in the certified family, so it is not scored here either.

NON-CLAIM diagnostic. Reads a sweep and its operators; writes one JSON.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/per_model_radii.py <sweep-dir> [package] [out.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from CertiTherm.experiments import _power_space
from CertiTherm.hotspot import load_family
from CertiTherm.thermal_constraints import reject_cell_rows, robust_safe_cell_rows
from l1_body import radius_l1_closed_form

MARGIN_K = 0.05


def _rows_for_model(family, index, margin_k):
    """The reject rows and safe right-hand sides belonging to ONE operator.

    Both tables are `reshape(-1)` over `(models, points)`, so operator `index` owns the contiguous
    block `[index * points, (index + 1) * points)`. Slicing the wrong axis would silently mix
    operators and make every per-model number meaningless while still producing a plausible table,
    so the slice is derived from the response shape rather than assumed.
    """

    points = family.response_k_per_w.shape[1]
    lo, hi = index * points, (index + 1) * points
    reject_rows, reject_floors = reject_cell_rows(family, margin_k)
    safe_rows, safe_rhs = robust_safe_cell_rows(family, margin_k)
    if reject_rows.shape[0] != family.response_k_per_w.shape[0] * points:
        raise SystemExit("reject rows are not one per (model, point); the slice would be wrong")
    return reject_rows[lo:hi], reject_floors[lo:hi], safe_rows[lo:hi], safe_rhs[lo:hi]


def main() -> None:
    root = Path(sys.argv[1])
    package = sys.argv[2] if len(sys.argv) > 2 else "default"
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] != "-" else None

    points = json.loads((root / "sweep.json").read_text())
    families: dict = {}
    rows = []
    for point in points:
        arch = point["arch"]
        if arch not in families:
            families[arch] = load_family(root / "operators" / f"{arch}--{package}.npz")
        family, operator_blocks = families[arch]
        _space, blocks, placed, _flp = _power_space(
            root / "captures" / f"{point['workload']}--{arch}.npz"
        )
        if blocks != operator_blocks:
            raise SystemExit(f"{arch}: power/operator block identity mismatch")
        power = np.asarray(placed, dtype=float)

        per_model = {}
        for index, model_id in enumerate(family.model_ids):
            reject_rows, reject_floors, safe_rows, safe_rhs = _rows_for_model(
                family, index, MARGIN_K
            )
            per_model[str(model_id)] = {
                "beta_star_reject": radius_l1_closed_form(reject_rows, reject_floors, power),
                "beta_star_safe": radius_l1_closed_form(safe_rows, safe_rhs, power),
            }
        rows.append({
            "arch": arch, "tiles": point["tiles"], "workload": point["workload"],
            "dies": point["dies"], "beta_star_family": point.get("beta_star_l1"),
            "per_model": per_model,
        })

    model_ids = sorted({m for r in rows for m in r["per_model"]})
    groups: dict = {}
    for row in rows:
        groups.setdefault((tuple(row["tiles"]), row["workload"]), []).append(row)

    disagreements = 0
    verdicts = []
    for key, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(members) < 2:
            continue
        members.sort(key=lambda r: r["dies"])
        # BOTH radii. Agreement on the REJECT ordering does not establish agreement on the safety
        # ordering, and the two are different decisions -- the split that peer review required is
        # only honoured if it is carried through here as well.
        orders = {}
        for which in ("beta_star_reject", "beta_star_safe"):
            for model_id in model_ids:
                orders[f"{model_id}|{which}"] = tuple(
                    m["dies"] for m in sorted(
                        members, key=lambda r: r["per_model"][model_id][which]
                    )
                )
        family_order = tuple(
            m["dies"] for m in sorted(
                members,
                key=lambda r: (
                    r["beta_star_family"] if r["beta_star_family"] is not None else -1.0
                ),
            )
        )
        # Near-ties would let tuple agreement hide a disagreement the sort resolved arbitrarily, so
        # the smallest separation actually seen is reported beside the verdict.
        separations = [
            abs(a["per_model"][m][w] - b["per_model"][m][w])
            for w in ("beta_star_reject", "beta_star_safe")
            for m in model_ids
            for a, b in zip(members, members[1:])
        ]
        agree = len(set(orders.values())) == 1 and set(orders.values()) == {family_order}
        disagreements += 0 if agree else 1
        verdicts.append({
            "tiles": list(key[0]), "workload": key[1],
            "order_by_model_and_radius": {k: list(v) for k, v in orders.items()},
            "order_family": list(family_order),
            "all_models_and_both_radii_induce_the_family_order": agree,
            "smallest_adjacent_separation": min(separations) if separations else None,
        })
        print(
            "%-6s %-12s  family %s   %s   %s" % (
                "%dx%d" % key[0], key[1], "<".join(str(d) for d in family_order),
                "  ".join(
                    "%s:%s" % (
                        m.replace("grid", "g"),
                        "/".join(
                            "<".join(str(d) for d in orders[f"{m}|{w}"])
                            for w in ("beta_star_reject", "beta_star_safe")
                        ),
                    )
                    for m in model_ids
                ),
                ("AGREE" if agree else "DISAGREE")
                + (" minsep %.2e" % min(separations) if separations else ""),
            ),
            flush=True,
        )

    print(
        "\n%d of %d decision groups have an operator that orders the cuts differently from the "
        "family minimum." % (disagreements, len(verdicts)),
        flush=True,
    )
    if out_path is not None:
        out_path.write_text(json.dumps({"model_ids": model_ids, "points": rows,
                                        "verdicts": verdicts}, indent=1))


if __name__ == "__main__":
    main()
