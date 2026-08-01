"""Is the robust-feasible frontier non-empty? Answered on built operators, before spending weeks.

The proposal (T3) is to replace the frozen `0.01 K` band with the MEASURED cross-model discrepancy,
re-run certification, and publish the architectures that stay feasible across the whole band together
with the EDYP price of choosing one. That is the right shape -- a positive deliverable rather than
"everything is uncertain" -- and it eliminates the pipeline's largest correctness risk whether or not
it is published.

**But its premise is testable in minutes and has already failed once.** Budgeting a five-vector
estimate and re-running the registry left 4 of 18 architectures refused and every transformer point
at `beta* = 0` (`docs/BUDGETED_REGISTRY_DOES_NOT_CERTIFY.md`). Since then the honest bound has been
measured at 2.5-5.3x that estimate. So the frontier may be empty, and finding that out costs a few
minutes of arithmetic on operators that already exist rather than 6-8 weeks.

This probe computes, per architecture and workload, on already-built operators:

* the **cross-grid** band -- `sup_p [T_grid64(p) - T_grid128(p)]` over the power polytope, per row;
* the **cross-model** band -- the same between `block` and `grid128`, which is the family's internal
  disagreement and is equally invisible to a linearity contract;
* whether the design is still certifiable with that band folded in one-sidedly;
* the frontier: architectures feasible under EVERY band tried;
* the EDYP price of the cheapest robust architecture against the EDYP-optimal one.

No HotSpot runs. Everything below reads saved operators and captures.

NON-CLAIM diagnostic. Writes one JSON.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/robust_frontier.py <artifact-root> <out.json> \\
        [package]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cross_grid_bound import one_sided_containment_bounds
from CertiTherm.experiments import _power_space, _rows, ROOT
from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import content_upper_bounds

MARGIN_K = 0.05


def main() -> None:
    artifacts = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    package = sys.argv[3] if len(sys.argv) > 3 else "default"

    architectures = [row["architecture_id"] for row in _rows(ROOT / "experiments" / "architectures.tsv")]
    rows = []
    for arch in architectures:
        operator = artifacts / "operators" / f"{arch}--{package}.npz"
        if not operator.exists():
            continue
        family, blocks = load_family(operator)
        ids = list(family.model_ids)
        for workload in ("resnet50", "transformer"):
            capture = artifacts / "captures" / f"{workload}--{arch}.npz"
            if not capture.exists():
                continue
            _space, capture_blocks, placed, _flp = _power_space(capture)
            if capture_blocks != blocks:
                raise SystemExit(f"{arch}/{workload}: block identity mismatch")
            power = np.asarray(placed, dtype=float)
            upper = content_upper_bounds(blocks, power)
            total = float(np.sum(power))
            lower = np.zeros(len(blocks))

            with np.load(capture, allow_pickle=False) as data:
                edyp = (
                    float(data["latency_ms"]) * float(data["energy_mj"]) / float(data["die_yield"])
                )

            bands = {}
            for name, coarse_id, fine_id in (
                ("cross_grid_64_128", "grid64-avg", "grid128-avg"),
                ("cross_model_block_128", "block", "grid128-avg"),
            ):
                if coarse_id not in ids or fine_id not in ids:
                    continue
                ci, fi = ids.index(coarse_id), ids.index(fine_id)
                hotter, _colder = one_sided_containment_bounds(
                    family.response_k_per_w[ci], family.response_k_per_w[fi],
                    family.ambient_k[ci], family.ambient_k[fi],
                    lower, upper, total,
                )
                bands[name] = float(np.max(hotter))

            # Certifiability at nominal power with each band folded in one-sidedly, on the FINEST
            # available operator -- the coarse one is what the band corrects toward it.
            fine = ids.index("grid128-avg") if "grid128-avg" in ids else 0
            nominal_peak = float(
                np.max(family.response_k_per_w[fine] @ power + family.ambient_k[fine])
            )
            headroom = THERMAL_LIMIT_K - MARGIN_K - nominal_peak
            rows.append({
                "architecture": arch, "workload": workload,
                "nominal_peak_k": nominal_peak,
                "headroom_to_limit_k": headroom,
                "frozen_band_k": MODEL_ERROR_LIMIT_K,
                "bands_k": bands,
                "certifiable_under": {
                    name: bool(headroom - band > 0.0) for name, band in bands.items()
                },
                "certifiable_under_frozen_band": bool(headroom - MODEL_ERROR_LIMIT_K > 0.0),
                "slack_after_worst_band_k": headroom - max(bands.values()) if bands else None,
                "edyp": edyp,
            })
            worst = max(bands.values()) if bands else float("nan")
            print(
                "%-8s %-12s peak %7.2f K  headroom %6.3f K  bands %s  worst/frozen %6.0fx  %s"
                % (
                    arch, workload, nominal_peak, headroom,
                    " ".join("%s=%.3f" % (n.split("_")[-1], b) for n, b in bands.items()),
                    worst / MODEL_ERROR_LIMIT_K,
                    "ROBUST-FEASIBLE" if headroom - worst > 0 else "NOT certifiable",
                ),
                flush=True,
            )

    frontier = [r for r in rows if r["slack_after_worst_band_k"] and r["slack_after_worst_band_k"] > 0]
    by_workload = {}
    for row in rows:
        by_workload.setdefault(row["workload"], []).append(row)
    prices = {}
    for workload, group in by_workload.items():
        robust = [r for r in group if r["slack_after_worst_band_k"] and r["slack_after_worst_band_k"] > 0]
        best_any = min(group, key=lambda r: r["edyp"])
        prices[workload] = {
            "edyp_optimal": best_any["architecture"], "edyp_optimal_value": best_any["edyp"],
            "robust_count": len(robust),
            "cheapest_robust": min(robust, key=lambda r: r["edyp"])["architecture"] if robust else None,
            "price_of_robustness_pct": (
                100.0 * (min(r["edyp"] for r in robust) / best_any["edyp"] - 1.0) if robust else None
            ),
        }
        print(
            "\n%-12s EDYP-optimal %s (%.3f); robust-feasible %d of %d; %s"
            % (
                workload, best_any["architecture"], best_any["edyp"], len(robust), len(group),
                (
                    "cheapest robust %s at %+.1f%% EDYP"
                    % (prices[workload]["cheapest_robust"], prices[workload]["price_of_robustness_pct"])
                    if robust else "THE FRONTIER IS EMPTY"
                ),
            ),
            flush=True,
        )

    print(
        "\nrobust-feasible points: %d of %d. The frontier is what T3 would publish; an empty one "
        "means the proposal needs reformulating before it is worth weeks." % (len(frontier), len(rows)),
        flush=True,
    )
    out_path.write_text(json.dumps({"points": rows, "price_of_robustness": prices}, indent=1))


if __name__ == "__main__":
    main()
