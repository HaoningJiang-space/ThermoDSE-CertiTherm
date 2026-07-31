"""Is the operator disagreement on elongated dies a resolution artefact, or is `block` the outlier?

The preregistered held-out evaluation failed P2: on 6 of 8 decision groups a thermal operator orders
the chiplet cuts differently from the family minimum, and on the `Nx2` grids `grid64-avg` and
`grid128-avg` invert the ordering relative to `block` outright. That refuted the ordering claim
(`docs/HELDOUT_RESULT_RADII.md`) and left one question, which decides whether the claim can ever be
rebuilt or has to stay dead:

* **Resolution artefact.** The grid operators are not converged at 64 and 128 cells on a die whose
  aspect ratio is far outside the development range, and their ordering is numerical noise. Then no
  operator can be trusted here and the claim stays dead until the family is re-validated.
* **`block` is the outlier.** The grid operators agree with each other and with a finer grid, and
  `block` -- which averages power over a whole functional block -- cannot resolve the lateral
  spreading that a two-tile-wide die makes dominant. Then the disagreement is physical, `block` is
  unsuitable for high-aspect-ratio dies, and the claim could be rebuilt on the grid operators alone
  **on a new held-out split**.

The discriminator is a finer grid. `grid256` is registered as CALIBRATION-ONLY and is deliberately
outside the certified family, which is exactly what makes it the right instrument: it can be used to
judge convergence without becoming part of a certificate.

## What this probe may and may not do

The `method-freeze-radii-v1` split is **burned**. These architectures have been seen, so nothing
here can resurrect the ordering claim -- a convergence verdict is evidence about the *instrument*,
not a re-test of the hypothesis. If the grid operators turn out to be converged, the required next
step is a NEW freeze ID and a NEW split, not a re-reading of this one. That constraint is the reason
this file exists as a separate probe rather than as an argument in the result document.

`CertiTherm.experiments.MODELS` is frozen and is NOT touched. This builds its own family by calling
`build_family` directly with its own model list, into its own workspace.

NON-CLAIM diagnostic. Reads held-out captures; writes one JSON.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/grid_convergence.py <sweep-dir> <out.json> \\
        [arch,arch,...] [models]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from CertiTherm.experiments import _power_space, _rows, ROOT
from CertiTherm.frozen_limits import THERMAL_LIMIT_K
from CertiTherm.hotspot import build_family
from CertiTherm.paths import HOTSPOT, TEMPLATE
from CertiTherm.thermal_constraints import reject_cell_rows
from l1_body import radius_l1_closed_form

MARGIN_K = 0.05
# The two the held-out split disagreed on, plus the finer grid that judges them. `block` is scored
# from the same build so the comparison is one family and not two.
DEFAULT_MODELS = "block,grid64-avg,grid128-avg,grid256-avg"
# The Nx2 grids, where the inversion was complete rather than partial.
DEFAULT_ARCHITECTURES = "heldout_radii_06,heldout_radii_07,heldout_radii_08,heldout_radii_09,heldout_radii_10,heldout_radii_11"


def main() -> None:
    root = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    architectures = (sys.argv[3] if len(sys.argv) > 3 else DEFAULT_ARCHITECTURES).split(",")
    model_ids = tuple((sys.argv[4] if len(sys.argv) > 4 else DEFAULT_MODELS).split(","))

    points = {
        (p["arch"], p["workload"]): p for p in json.loads((root / "sweep.json").read_text())
    }
    package = next(
        r for r in _rows(ROOT / "experiments" / "packages.tsv") if r["package_id"] == "default"
    )
    del package  # the config is taken from the workspace the sweep already configured

    rows = []
    for arch in architectures:
        work = root / "work" / f"operator--{arch}--default"
        config, floorplan = work / "package.config", work / "floorplan.flp"
        if not (config.exists() and floorplan.exists()):
            raise SystemExit(
                f"{arch}: the sweep's operator workspace is missing {config.name} or "
                f"{floorplan.name}; this probe reuses the exact inputs the held-out family was "
                "built from rather than regenerating them, so that a difference here is the model "
                "and nothing else"
            )
        workspace = root / "convergence" / arch
        workspace.mkdir(parents=True, exist_ok=True)
        family, blocks = build_family(
            HOTSPOT, config, floorplan, TEMPLATE / "example.materials",
            model_ids, workspace, THERMAL_LIMIT_K,
        )
        reject_rows, reject_floors = reject_cell_rows(family, MARGIN_K)
        per_point = family.response_k_per_w.shape[1]

        for workload in ("resnet50", "transformer"):
            key = (arch, workload)
            if key not in points:
                continue
            _space, capture_blocks, placed, _flp = _power_space(
                root / "captures" / f"{workload}--{arch}.npz"
            )
            if capture_blocks != blocks:
                raise SystemExit(f"{arch}/{workload}: power/operator block identity mismatch")
            power = np.asarray(placed, dtype=float)
            per_model = {}
            for index, model_id in enumerate(family.model_ids):
                lo, hi = index * per_point, (index + 1) * per_point
                per_model[str(model_id)] = radius_l1_closed_form(
                    reject_rows[lo:hi], reject_floors[lo:hi], power
                )
            rows.append({
                "arch": arch, "workload": workload,
                "tiles": points[key]["tiles"], "dies": points[key]["dies"],
                "beta_star_reject_by_model": per_model,
            })
            print(
                "%-18s %-12s  %s" % (
                    arch, workload,
                    "  ".join("%s %.4f%%" % (m.replace("grid", "g"), 100 * v)
                              for m, v in per_model.items()),
                ),
                flush=True,
            )

    # The verdict: does the ordering CHANGE between the two finest grids?
    groups: dict = {}
    for row in rows:
        groups.setdefault((tuple(row["tiles"]), row["workload"]), []).append(row)
    verdicts = []
    for key, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(members) < 2:
            continue
        members.sort(key=lambda r: r["dies"])
        order = {
            model: tuple(
                m["dies"] for m in sorted(members, key=lambda r: r["beta_star_reject_by_model"][model])
            )
            for model in members[0]["beta_star_reject_by_model"]
        }
        fine = [m for m in order if m.startswith("grid")]
        fine.sort(key=lambda m: int(m[4:].split("-")[0]))
        converged = len(fine) >= 2 and order[fine[-1]] == order[fine[-2]]
        block_agrees = "block" in order and order["block"] == order[fine[-1]]
        verdicts.append({
            "tiles": list(key[0]), "workload": key[1],
            "order_by_model": {k: list(v) for k, v in order.items()},
            "finest_two_grids_agree": converged,
            "block_agrees_with_finest_grid": block_agrees,
        })
        print(
            "%-6s %-12s  %s   grids converged: %-5s   block agrees: %s" % (
                "%dx%d" % key[0], key[1],
                "  ".join("%s:%s" % (m.replace("grid", "g"), "<".join(str(d) for d in o))
                          for m, o in order.items()),
                converged, block_agrees,
            ),
            flush=True,
        )

    converged = sum(1 for v in verdicts if v["finest_two_grids_agree"])
    block_ok = sum(1 for v in verdicts if v["block_agrees_with_finest_grid"])
    print(
        "\nthe two finest grids agree in %d of %d groups; `block` agrees with the finest in %d.\n"
        "Converged grids that `block` disagrees with means `block` is the outlier and the "
        "disagreement is physical; grids that do not converge means no operator is trustworthy here."
        % (converged, len(verdicts), block_ok),
        flush=True,
    )
    out_path.write_text(json.dumps(
        {"model_ids": list(model_ids), "note": (
            "Calibration-only. The method-freeze-radii-v1 split is burned, so this is evidence "
            "about the instrument and not a re-test of the ordering hypothesis; rebuilding that "
            "claim requires a new freeze ID and a new split."
        ), "points": rows, "verdicts": verdicts}, indent=1))


if __name__ == "__main__":
    main()
