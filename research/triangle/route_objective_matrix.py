"""Run and compare the 2x3 legacy/physical route objective audit. (NON-CLAIM)

Usage:
    python research/triangle/route_objective_matrix.py <out> [workers]
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import sys
from pathlib import Path


OUTPUT = Path(sys.argv[1])
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 6


def run_case(item):
    workload, arch, mode = item
    case_output = OUTPUT / f"{workload}-{arch}-{mode}"
    case_output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "research/triangle/route_objective_probe.py",
        str(case_output),
        workload,
        arch,
        mode,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    return workload, arch, mode, case_output, result


def main():
    if WORKERS < 1:
        raise ValueError("workers must be positive")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cases = tuple(
        (workload, arch, mode)
        for workload in ("resnet50", "transformer")
        for arch in ("arch_a", "arch_b", "arch_c")
        for mode in ("legacy", "physical")
    )
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(cases))) as pool:
        results = list(pool.map(run_case, cases))
    reports = {}
    for workload, arch, mode, case_output, result in results:
        (case_output / "probe.log").write_text(
            result.stdout + result.stderr, encoding="utf-8"
        )
        if result.returncode:
            raise RuntimeError(
                f"{workload}/{arch}/{mode} failed: {result.stderr[-1000:]}"
            )
        report_path = (
            case_output / f"route_objective_{workload}_{arch}_{mode}.json"
        )
        reports[(workload, arch, mode)] = json.loads(
            report_path.read_text(encoding="utf-8")
        )

    summary = {"workloads": {}}
    for workload in ("resnet50", "transformer"):
        item = {"cases": {}}
        for arch in ("arch_a", "arch_b", "arch_c"):
            legacy = reports[(workload, arch, "legacy")]
            physical = reports[(workload, arch, "physical")]
            old = float(legacy["physical_time_edyp"])
            new = float(physical["physical_time_edyp"])
            item["cases"][arch] = {
                "legacy": legacy,
                "physical": physical,
                "relative_edyp_change": new / old - 1.0,
            }
            print(
                f"{workload}/{arch}: EDYP {old:.9g} -> {new:.9g} "
                f"({(new/old-1.0):+.3%})"
            )
        for mode in ("legacy", "physical"):
            ranking = tuple(
                sorted(
                    ("arch_a", "arch_b", "arch_c"),
                    key=lambda arch: (
                        reports[(workload, arch, mode)]["physical_time_edyp"],
                        arch,
                    ),
                )
            )
            item[f"{mode}_ranking"] = ranking
        item["ranking_flip"] = (
            item["legacy_ranking"] != item["physical_ranking"]
        )
        print(
            f"{workload}: legacy={item['legacy_ranking']}, "
            f"physical={item['physical_ranking']}, flip={item['ranking_flip']}"
        )
        summary["workloads"][workload] = item
    output = OUTPUT / "route_objective_summary.json"
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
