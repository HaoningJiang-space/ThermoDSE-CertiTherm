"""Add the exact L1 relocation radius to a sweep that was captured without it.

`architecture_sweep.py` gained `beta_star_l1` after the matched sweep was already running, and
re-running a forty-minute HotSpot sweep to add a quantity derivable from its own saved artifacts
would be waste. The radius needs only the operator and the placed power map, both of which the sweep
writes, so this recomputes it in seconds.

It also serves as the check that the two are the same quantity: the value it writes must equal what
`architecture_sweep` would have produced, because both call `radius_l1_closed_form` on the same
`reject_cell_rows` at the same margin. There is no second implementation here to drift.

NON-CLAIM diagnostic. Reads a sweep directory; rewrites its `sweep.json` in place.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/relocation_radii.py <sweep-dir> [package]
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
from CertiTherm.thermal_constraints import reject_cell_rows
from l1_body import radius_l1_closed_form

MARGIN_K = 0.05


def main() -> None:
    root = Path(sys.argv[1])
    package = sys.argv[2] if len(sys.argv) > 2 else "default"
    sweep_path = root / "sweep.json"
    points = json.loads(sweep_path.read_text())

    families: dict = {}
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
        rows, floors = reject_cell_rows(family, MARGIN_K)
        beta = radius_l1_closed_form(rows, floors, np.asarray(placed, dtype=float))
        point["beta_star_l1"] = beta
        print(
            "%-12s %-12s  eps* %7s  beta* %7s" % (
                arch, point["workload"],
                "%.3f%%" % (point["epsilon_star"] * 100)
                if np.isfinite(point.get("epsilon_star", float("inf"))) else "none",
                "%.3f%%" % (beta * 100) if np.isfinite(beta) else "none",
            ),
            flush=True,
        )
        # The containment the whole geometry split rests on, asserted on real instances rather than
        # only on the unit-test fixture: the deviation box contains the L1 body, so it must reach a
        # floor no later. `epsilon_star` is measured on that box.
        eps = point.get("epsilon_star")
        if eps is not None and np.isfinite(eps) and np.isfinite(beta) and eps > beta + 1e-6:
            raise SystemExit(
                f"{arch}/{point['workload']}: the deviation-box radius {eps} exceeds the exact L1 "
                f"radius {beta}, which contradicts the containment the two are separated by"
            )

    sweep_path.write_text(json.dumps(points, indent=1))
    print(json.dumps({"points": len(points), "out": str(sweep_path)}))


if __name__ == "__main__":
    main()
