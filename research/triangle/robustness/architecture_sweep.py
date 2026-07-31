"""Generate fresh architecture points and measure their thermal-robustness radii.

The registry supplies three development architectures, which is not enough to say anything about
how the radii behave across a design space. The held-out architectures cannot be used for this --
opening a frozen split to enlarge a sample is exactly what the protocol forbids -- but the design
space is parameterised, so NEW points can be generated instead. They are new data in the
development regime, not held-out data.

Each point costs roughly one capture per workload and one operator: about thirty seconds in total
on this machine, which is why the sample-size objection is answerable at all.

The grid spans the two axes that matter for the thermal-yield coupling: the tile grid (total
compute area) and the chiplet cut (how that area is divided into dies, and therefore yield). The
remaining parameters are held at the registry's own values so the sweep varies what it means to
vary.

NON-CLAIM diagnostic. Writes captures and operators into its own output directory.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/architecture_sweep.py <output-dir> [workloads]
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")
# The probe directory itself, so the sibling exact-L1 helper imports without a package marker.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from CertiTherm.experiments import (
    _capture,
    _measurement_costs,
    _operator,
    _power_space,
    _rows,
    GpuSelection,
    ROOT,
)
from CertiTherm.hotspot import load_family
from CertiTherm.thermal_constraints import reject_cell_rows
from l1_body import radius_l1_closed_form


MARGIN_K = 0.05
# The registry's own values for everything the sweep does not vary.
BASE = {"interval": "0.0017", "mtxu_h": "128", "mtxu_w": "128",
        "ubuf": "1048576", "nop_bw": "144", "dram_bw": "128"}
# (tiles_x, tiles_y, cut_x, cut_y[, interval_m]) -- area, how it is cut into dies, and the
# chiplet spacing. The spacing is the one knob that moves thermal and area in OPPOSITE
# directions without changing the compute: it buys lateral spreading and costs interposer area
# and D2D distance. The `cut` axis alone leaves EDYP nearly stationary (measured: |dEDYP| <= 2.8%
# against a +12% yield swing), so a sweep that varies only the cut cannot exhibit a frontier.
GRID = [(4, 4, 1, 1), (4, 4, 2, 1), (4, 4, 2, 2),
        (6, 3, 1, 1), (6, 3, 2, 1), (6, 3, 3, 1),
        (5, 4, 1, 1), (5, 4, 2, 1), (5, 4, 2, 2),
        (6, 4, 2, 2), (6, 4, 3, 2), (8, 3, 2, 1)]
# The co-optimisation frontier: the same cuts at three spacings. Reached by `--grid frontier`.
FRONTIER = [
    (tx, ty, cx, cy, interval)
    for interval in ("0.0017", "0.0040", "0.0070")
    for (tx, ty, cx, cy) in ((5, 4, 1, 1), (5, 4, 2, 2), (6, 4, 2, 2),
                             (6, 4, 3, 2), (8, 4, 2, 2), (8, 4, 4, 2))
]
# The matched-cut design peer review asked for: same tile grid, same spacing, same workload, and
# ONLY the cut varies, through 1 -> 2 -> 4 equal dies. Every grid has even edges so the cut divides
# evenly and all dies are identical -- which is what makes the per-die yield product exactly
# recoverable rather than approximated from the reported mean.
MATCHED = [
    (tx, ty, cx, cy)
    for (tx, ty) in ((4, 4), (6, 4), (8, 4), (4, 6), (6, 6), (8, 6))
    for (cx, cy) in ((1, 1), (2, 1), (2, 2))
]
GRIDS = {"cut": GRID, "frontier": FRONTIER, "matched": MATCHED}
D0, ALPHA = 0.08, 10          # ThermoDSE/core/gen_hw_setting.py, 14 nm


def radii(family, placed):
    """tau* (uniform under-prediction) and the BOX redistribution radius, both against the floor.

    The second value is NOT the L1 relocated-fraction radius. It is measured on the box implied by
    a transfer budget -- an L-infinity ball of half-width `e * total` intersected with the
    total-power plane -- which is a strict RELAXATION of the L1 body and therefore reaches a floor
    at a SMALLER radius. The exact L1 radius is computed by
    `research/triangle/robustness/l1_body.py:radius_l1` and is the larger of the two on every
    instance measured (e.g. arch_a/default/resnet50: 2.637% box against 4.1% L1). Reporting both
    under the name "beta*" was an error; this one is `epsilon_star`.
    """
    rows, floors = reject_cell_rows(family, MARGIN_K)
    points = family.response_k_per_w.shape[1]
    rise = np.array([float(family.response_k_per_w[m // points, m % points] @ placed)
                     for m in range(rows.shape[0])])
    floors = np.asarray(floors, dtype=float)
    tau = float(np.min(np.where(rise > 0, (floors - rise) / np.where(rise > 0, rise, 1), np.inf)))
    # A negative tau* means the NOMINAL map already reaches a floor. Reporting it as a signed
    # "radius" invites a reader to treat -5% as a small radius rather than as infeasible.
    if tau < 0.0:
        tau = 0.0
    # beta*: the smallest relocated fraction whose implied box reaches a floor. Using the box makes
    # this a RELAXATION of the true L1 body, so the radius reported is a lower bound on the true
    # one -- the conservative direction for a robustness claim.
    total = float(np.sum(placed))
    lo, hi = 0.0, 1.0
    def reaches(beta):
        budget = beta * total
        upper = placed + budget
        lower = np.maximum(placed - budget, 0.0)
        for j in range(rows.shape[0]):
            r = np.asarray(rows[j], dtype=float)
            order = np.argsort(-r)
            p = lower.copy()
            spare = total - float(p.sum())
            for i in order:
                add = min(upper[i] - p[i], spare)
                p[i] += add
                spare -= add
                if spare <= 1e-12:
                    break
            if float(r @ p) >= floors[j]:
                return True
        return False
    # A nominally REJECT design has radius ZERO. Bisecting without this test returns a small
    # positive value after sixteen halvings and fabricates a safe interval below it -- peer review
    # found the same hole in `threshold.py`.
    if reaches(0.0):
        return tau, 0.0
    if not reaches(hi):
        return tau, float("inf")
    for _ in range(16):
        mid = 0.5 * (lo + hi)
        if reaches(mid): hi = mid
        else: lo = mid
    return tau, hi


def main() -> None:
    output = Path(sys.argv[1])
    workloads = (sys.argv[2].split(",") if len(sys.argv) > 2 else ["resnet50", "transformer"])
    grid_name = sys.argv[3] if len(sys.argv) > 3 else "cut"
    if grid_name not in GRIDS:
        raise SystemExit(f"unknown grid {grid_name!r}; choose from {sorted(GRIDS)}")
    grid = [point if len(point) == 5 else (*point, BASE["interval"]) for point in GRIDS[grid_name]]
    output.mkdir(parents=True, exist_ok=True)
    registry = {row["workload_id"]: row for row in _rows(ROOT / "experiments" / "workloads.tsv")}
    package = next(r for r in _rows(ROOT / "experiments" / "packages.tsv")
                   if r["package_id"] == "default")
    gpu = GpuSelection.from_environment()

    results = []
    for index, (tx, ty, cx, cy, interval) in enumerate(grid):
        arch = {"architecture_id": "%s_%02d" % (grid_name, index), "chiplet_x": str(tx),
                "chiplet_y": str(ty), "cut_x": str(cx), "cut_y": str(cy),
                **BASE, "interval": str(interval)}
        started = time.monotonic()
        try:
            captures = {}
            for wl in workloads:
                captures[wl] = _capture(arch, registry[wl], package, output)
            operator = _operator(arch, package, list(captures.values()), output, gpu=gpu)
            family, blocks = load_family(operator)
        except Exception as exc:  # noqa: BLE001 - a refused point is data, not a crash
            print("%-12s %d x %d cut %d x %d gap %s  SKIPPED  %s: %s" % (
                arch["architecture_id"], tx, ty, cx, cy, interval,
                type(exc).__name__, str(exc)[:60]),
                flush=True)
            continue
        for wl in workloads:
            polytope, cap_blocks, placed, _flp = _power_space(captures[wl])
            placed_w = np.asarray(placed, dtype=float)
            tau, eps = radii(family, placed_w)
            # The EXACT L1 relocation radius, not the box's. The two differ by more than an order
            # of magnitude on some instances and only this one may be quoted as "fraction of total
            # power relocated"; `epsilon_star` is a per-block deviation radius.
            reject_rows, reject_floors = reject_cell_rows(family, MARGIN_K)
            beta = radius_l1_closed_form(reject_rows, reject_floors, placed_w)
            with np.load(captures[wl], allow_pickle=False) as data:
                edyp = (float(data["latency_ms"]) * float(data["energy_mj"])
                        / float(data["die_yield"]))
                y = float(data["die_yield"])
            peak = float((family.response_k_per_w @ placed
                          + family.ambient_k[:, :, None][:, :, 0]).max())
            results.append({"arch": arch["architecture_id"], "tiles": [tx, ty], "cut": [cx, cy],
                            "interval_m": float(interval),
                            "dies": cx * cy, "workload": wl, "blocks": len(cap_blocks),
                            "peak_k": peak, "tau_star": tau, "epsilon_star": eps, "beta_star_l1": beta,
                            "yield": y, "edyp": edyp})
            print("%-12s %dx%d cut %dx%d gap %-6s dies %d  %-12s peak %7.2f  tau* %7.1f%%"
                  "  eps* %6.2f%%  beta* %6.2f%%  Y %.4f  EDYP %8.3f  (%.0fs)" % (
                      arch["architecture_id"], tx, ty, cx, cy, interval, cx * cy, wl, peak,
                      tau * 100, eps * 100, beta * 100, y, edyp,
                      time.monotonic() - started), flush=True)
    (output / "sweep.json").write_text(json.dumps(results, indent=1))
    print("\n%d architecture-workload points written to %s" % (len(results), output / "sweep.json"))


if __name__ == "__main__":
    main()
