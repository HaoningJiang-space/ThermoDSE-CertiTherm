"""Is the measured cross-solver difference a property of HotSpot, or of one package?

Every model-form number in this project was measured on `packages.tsv:default`, so "HotSpot reads
colder than an independent FEM on all six points" could be a property of that package rather than of
HotSpot's lumped centre-plus-trapezoid spreading network. `standard` cuts `r_convec` 0.10 -> 0.07 and
the spreader 50 -> 30 mm; `enhanced` cuts `r_convec` to 0.05 and grows the sink 60 -> 100 mm. Both
move the total resistance AND the spreading area -- exactly the axis the network approximates.

**The reading was declared before the operators were built** (`docs/ARCHIVE_CENSUS_PREREGISTRATION.md`
style, and in the plan):

* band tracks the package  -> the finding is about the spreading network and generalises;
* band does not move       -> the finding is weaker but still real;
* **sign flips on some package -> "HotSpot systematically underestimates" is WITHDRAWN.**

The last is the cheapest thing that could still refute the headline, which is why it is run.

This script DECIDES nothing about the band's definition. It calls
`CertiTherm.cross_grid_bound.one_sided_containment_bounds`, the same function `robust_frontier.py`
uses, so the two cannot drift apart. It only iterates it over packages.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/package_sweep_band.py \\
        <operator-root> <artifacts-dir> [span] [packages]

`<operator-root>` holds `g512/<arch>--<package>.npz` and `fem/<arch>--<package>.npz`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cross_grid_bound import one_sided_containment_bounds
from CertiTherm.experiments import _power_space
from CertiTherm.measurements import activity_bounded_power_space

ARCHITECTURES = ("arch_a", "arch_b", "arch_c")
WORKLOADS = ("resnet50", "transformer")


def _operator(path: Path):
    """`(rows, ambient, block_ids)` from a saved single-model operator NPZ."""
    with np.load(path, allow_pickle=False) as data:
        rows = np.asarray(data["response_k_per_w"], dtype=float)
        ambient = np.asarray(data["ambient_k"], dtype=float)
        if rows.shape[0] != 1 or ambient.shape[0] != 1:
            raise SystemExit(
                f"{path} holds {rows.shape[0]} models; this sweep expects exactly one per file so "
                "that no model id has to be guessed"
            )
        return rows[0], ambient[0], [str(b) for b in data["block_ids"]]


def main() -> None:
    root = Path(sys.argv[1])
    artifacts = Path(sys.argv[2])
    span = float(sys.argv[3]) if len(sys.argv) > 3 else 0.30
    packages = sys.argv[4].split(",") if len(sys.argv) > 4 else ["standard", "enhanced"]

    results, skipped = [], []
    for arch in ARCHITECTURES:
        for package in packages:
            coarse_path = root / "g512" / f"{arch}--{package}.npz"
            fine_path = root / "fem" / f"{arch}--{package}.npz"
            if not (coarse_path.exists() and fine_path.exists()):
                skipped.append(f"{arch}/{package}: missing operator")
                continue
            coarse_rows, coarse_ambient, coarse_blocks = _operator(coarse_path)
            fine_rows, fine_ambient, fine_blocks = _operator(fine_path)
            # ORDER, not just count. A band between two matrices whose rows name different blocks
            # is not a band at all, and equal lengths would hide it.
            if coarse_blocks != fine_blocks:
                skipped.append(f"{arch}/{package}: block ids differ between the two operators")
                continue

            for workload in WORKLOADS:
                capture = artifacts / "captures" / f"{workload}--{arch}.npz"
                if not capture.exists():
                    skipped.append(f"{arch}/{workload}: no capture")
                    continue
                _space, capture_blocks, placed, _flp = _power_space(capture)
                if list(capture_blocks) != coarse_blocks:
                    skipped.append(f"{arch}/{workload}/{package}: capture blocks differ")
                    continue
                power = np.asarray(placed, dtype=float)
                polytope = activity_bounded_power_space(capture_blocks, power, activity_span=span)
                hotter, colder = one_sided_containment_bounds(
                    coarse_rows, fine_rows, coarse_ambient, fine_ambient,
                    np.asarray(polytope.lower_w, dtype=float),
                    np.asarray(polytope.upper_w, dtype=float),
                    np.asarray(polytope.a_ub, dtype=float),
                    np.asarray(polytope.b_ub, dtype=float),
                )
                nominal = (fine_rows - coarse_rows) @ power + (fine_ambient - coarse_ambient)
                results.append({
                    "architecture": arch, "workload": workload, "package": package,
                    "rows": int(len(hotter)),
                    "band_k": float(np.max(hotter)),
                    "min_u_j_k": float(np.min(hotter)),
                    "rows_with_negative_u_j": int(np.count_nonzero(hotter < 0.0)),
                    "at_nominal_max_k": float(np.max(nominal)),
                    "at_nominal_min_k": float(np.min(nominal)),
                    # THE PREREGISTERED KILL READING. The headline is "HotSpot reads COLDER", i.e.
                    # T_FEM - T_grid512 > 0. A negative maximum at the nominal map on any package is
                    # the sign flip that withdraws it.
                    "sign_flipped_at_nominal": bool(np.max(nominal) < 0.0),
                    "total_power_w": float(np.sum(power)),
                })

    report = {
        "activity_span": span, "packages": packages,
        "reference_default_band_k": [0.251, 1.061],
        "results": results, "skipped": skipped,
    }
    flips = [r for r in results if r["sign_flipped_at_nominal"]]
    report["any_sign_flip"] = bool(flips)
    # FAIL CLOSED ON AN EMPTY SWEEP. "no sign flip was observed" is true of zero observations, so
    # a run that skipped everything would otherwise print a verdict that reads as corroboration.
    # An absent test must not look like a passed one.
    if not results:
        report["verdict"] = "UNRESOLVED: no (architecture, workload, package) point produced a band"
        print(json.dumps(report, indent=1), flush=True)
        raise SystemExit(
            f"the sweep compared nothing -- {len(skipped)} points were skipped, so the preregistered "
            "sign-flip reading has NOT been tested"
        )
    report["verdict"] = (
        "WITHDRAW 'HotSpot systematically underestimates': sign flipped on "
        + ", ".join(f"{r['architecture']}/{r['workload']}/{r['package']}" for r in flips)
        if flips else
        f"no sign flip across {len(results)} points; the one-signed reading survives this test"
    )
    print(json.dumps(report, indent=1), flush=True)


if __name__ == "__main__":
    main()
