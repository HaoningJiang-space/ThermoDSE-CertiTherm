"""Compare time-mean steady and periodic thermal decisions. (NON-CLAIM)

Usage:
    python research/triangle/transient_decision_report.py \
        <complete-root> <transient-root> [limit-k]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


COMPLETE = Path(sys.argv[1])
TRANSIENT = Path(sys.argv[2])
LIMIT_K = float(sys.argv[3]) if len(sys.argv) > 3 else 330.0


def load_case(workload, arch):
    complete_path = (
        COMPLETE
        / f"{workload}-{arch}"
        / f"complete_trace_{workload}_{arch}.json"
    )
    transient_path = TRANSIENT / f"{workload}-{arch}" / "transient_report.json"
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    transient = json.loads(transient_path.read_text(encoding="utf-8"))
    return {
        "arch": arch,
        "objective": float(complete["optimization_edyp"]),
        "mean_peak_k": float(transient["mean_steady_peak_k"]),
        "periodic_peak_k": float(transient["periodic_peak_k"]),
        "uplift_k": float(transient["periodic_peak_k"])
        - float(transient["mean_steady_peak_k"]),
        "mean_feasible": float(transient["mean_steady_peak_k"]) <= LIMIT_K,
        "periodic_feasible": float(transient["periodic_peak_k"]) <= LIMIT_K,
    }


def choose(cases, feasibility):
    eligible = [case for case in cases if case[feasibility]]
    return min(eligible, key=lambda case: (case["objective"], case["arch"])) if eligible else None


def main():
    report = {"limit_k": LIMIT_K, "workloads": {}}
    for workload in ("resnet50", "transformer"):
        cases = [load_case(workload, arch) for arch in ("arch_a", "arch_b", "arch_c")]
        mean_order = tuple(
            case["arch"]
            for case in sorted(cases, key=lambda case: (case["mean_peak_k"], case["arch"]))
        )
        periodic_order = tuple(
            case["arch"]
            for case in sorted(
                cases, key=lambda case: (case["periodic_peak_k"], case["arch"])
            )
        )
        mean_choice = choose(cases, "mean_feasible")
        periodic_choice = choose(cases, "periodic_feasible")
        if mean_choice is None or periodic_choice is None:
            regret = None
        elif not mean_choice["periodic_feasible"]:
            regret = "infeasible"
        else:
            regret = mean_choice["objective"] - periodic_choice["objective"]
        item = {
            "cases": cases,
            "mean_thermal_order": mean_order,
            "periodic_thermal_order": periodic_order,
            "ranking_flip": mean_order != periodic_order,
            "feasibility_flips": [
                case["arch"]
                for case in cases
                if case["mean_feasible"] != case["periodic_feasible"]
            ],
            "mean_selected": mean_choice["arch"] if mean_choice else None,
            "periodic_oracle_selected": (
                periodic_choice["arch"] if periodic_choice else None
            ),
            "decision_regret_edyp": regret,
        }
        report["workloads"][workload] = item

        print(f"{workload} @ {LIMIT_K:.2f} K")
        for case in cases:
            print(
                f"  {case['arch']}: objective={case['objective']:.9g}, "
                f"mean={case['mean_peak_k']:.4f} K "
                f"({'F' if case['mean_feasible'] else 'I'}), "
                f"periodic={case['periodic_peak_k']:.4f} K "
                f"({'F' if case['periodic_feasible'] else 'I'}), "
                f"uplift={case['uplift_k']:.4f} K"
            )
        print(
            f"  thermal ranking: mean={mean_order}, periodic={periodic_order}, "
            f"flip={item['ranking_flip']}"
        )
        print(
            f"  feasibility flips={item['feasibility_flips']}; "
            f"mean-selected={item['mean_selected']}; "
            f"periodic-oracle={item['periodic_oracle_selected']}; "
            f"regret={item['decision_regret_edyp']}"
        )

    output = TRANSIENT / "decision_report.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
