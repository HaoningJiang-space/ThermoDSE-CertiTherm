"""Compare temporal uplift against block/grid model discrepancy. (NON-CLAIM)

Usage:
    python research/triangle/transient_model_comparison.py \
        <block-root> <grid-root> <route-objective-root> [limit-k]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


BLOCK = Path(sys.argv[1])
GRID = Path(sys.argv[2])
OBJECTIVES = Path(sys.argv[3])
LIMIT_K = float(sys.argv[4]) if len(sys.argv) > 4 else 330.0


def load(root, workload, arch):
    path = root / f"{workload}-{arch}" / "transient_report.json"
    return json.loads(path.read_text(encoding="utf-8"))


def objective(workload, arch):
    path = (
        OBJECTIVES
        / f"{workload}-{arch}-physical"
        / f"route_objective_{workload}_{arch}_physical.json"
    )
    return float(json.loads(path.read_text(encoding="utf-8"))["physical_time_edyp"])


def main():
    report = {"limit_k": LIMIT_K, "workloads": {}}
    all_cases = []
    for workload in ("resnet50", "transformer"):
        cases = []
        for arch in ("arch_a", "arch_b", "arch_c"):
            block = load(BLOCK, workload, arch)
            grid = load(GRID, workload, arch)
            item = {
                "arch": arch,
                "objective": objective(workload, arch),
                "block_mean_k": float(block["mean_steady_peak_k"]),
                "block_periodic_k": float(block["periodic_peak_k"]),
                "block_uplift_k": float(block["periodic_peak_k"])
                - float(block["mean_steady_peak_k"]),
                "grid_mean_k": float(grid["mean_steady_peak_k"]),
                "grid_periodic_k": float(grid["periodic_peak_k"]),
                "grid_uplift_k": float(grid["periodic_peak_k"])
                - float(grid["mean_steady_peak_k"]),
                "periodic_model_delta_k": float(block["periodic_peak_k"])
                - float(grid["periodic_peak_k"]),
                "block_feasible": float(block["periodic_peak_k"]) <= LIMIT_K,
                "grid_feasible": float(grid["periodic_peak_k"]) <= LIMIT_K,
                "block_hottest": block["periodic_hottest_block"],
                "grid_hottest": grid["periodic_hottest_block"],
            }
            cases.append(item)
            all_cases.append(item)
            print(
                f"{workload}/{arch}: block={item['block_periodic_k']:.4f} K "
                f"(uplift {item['block_uplift_k']:.4f}), "
                f"grid={item['grid_periodic_k']:.4f} K "
                f"(uplift {item['grid_uplift_k']:.4f}), "
                f"block-grid={item['periodic_model_delta_k']:+.4f} K"
            )
        block_order = tuple(
            item["arch"]
            for item in sorted(
                cases, key=lambda item: (item["block_periodic_k"], item["arch"])
            )
        )
        grid_order = tuple(
            item["arch"]
            for item in sorted(
                cases, key=lambda item: (item["grid_periodic_k"], item["arch"])
            )
        )
        model_feasibility_flips = [
            item["arch"]
            for item in cases
            if item["block_feasible"] != item["grid_feasible"]
        ]
        block_eligible = [item for item in cases if item["block_feasible"]]
        grid_eligible = [item for item in cases if item["grid_feasible"]]
        block_choice = min(
            block_eligible, key=lambda item: (item["objective"], item["arch"])
        )
        grid_choice = min(
            grid_eligible, key=lambda item: (item["objective"], item["arch"])
        )
        if not block_choice["grid_feasible"]:
            coarse_regret = "infeasible"
            relative_regret = None
        else:
            coarse_regret = block_choice["objective"] - grid_choice["objective"]
            relative_regret = coarse_regret / grid_choice["objective"]
        report["workloads"][workload] = {
            "cases": cases,
            "block_order": block_order,
            "grid_order": grid_order,
            "model_ranking_flip": block_order != grid_order,
            "model_feasibility_flips": model_feasibility_flips,
            "block_selected": block_choice["arch"],
            "grid_selected": grid_choice["arch"],
            "coarse_decision_regret_edyp": coarse_regret,
            "coarse_relative_regret": relative_regret,
        }
        print(
            f"  ranking block={block_order}, grid={grid_order}, "
            f"flip={block_order != grid_order}; "
            f"feasibility flips={model_feasibility_flips}"
        )
        print(
            f"  block-selected={block_choice['arch']}, "
            f"grid-selected={grid_choice['arch']}, "
            f"coarse regret={coarse_regret}, relative={relative_regret}"
        )

    maximum_temporal_uplift = max(
        max(item["block_uplift_k"], item["grid_uplift_k"]) for item in all_cases
    )
    minimum_model_delta = min(
        abs(item["periodic_model_delta_k"]) for item in all_cases
    )
    report["maximum_temporal_uplift_k"] = maximum_temporal_uplift
    report["minimum_absolute_model_delta_k"] = minimum_model_delta
    report["uplift_to_minimum_model_delta_ratio"] = (
        maximum_temporal_uplift / minimum_model_delta
        if minimum_model_delta
        else None
    )
    print(
        f"max temporal uplift={maximum_temporal_uplift:.6f} K; "
        f"min |block-grid|={minimum_model_delta:.6f} K"
    )
    output = GRID / "model_comparison.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
