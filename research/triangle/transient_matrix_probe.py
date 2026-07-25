"""Run the registered 2-workload x 3-candidate transient matrix. (NON-CLAIM)

Usage:
    python research/triangle/transient_matrix_probe.py \
        <complete-root> <out> [model] [step-us] [workers]
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys
from pathlib import Path


COMPLETE = Path(sys.argv[1])
OUTPUT = Path(sys.argv[2])
MODEL = sys.argv[3] if len(sys.argv) > 3 else "block"
STEP_US = sys.argv[4] if len(sys.argv) > 4 else "0.5"
WORKERS = int(sys.argv[5]) if len(sys.argv) > 5 else 3


def run_case(item):
    workload, arch = item
    base = COMPLETE / f"{workload}-{arch}"
    output = OUTPUT / f"{workload}-{arch}"
    command = [
        sys.executable,
        "research/triangle/transient_trace_probe.py",
        str(base / f"complete_trace_{workload}_{arch}.npz"),
        str(base / f"complete_floorplan_{workload}_{arch}.flp"),
        str(base / "work" / f"capture--{workload}--{arch}"),
        str(output),
        MODEL,
        STEP_US,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    return workload, arch, result


def main():
    logs = OUTPUT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    if WORKERS < 1:
        raise ValueError("workers must be positive")
    cases = tuple(
        (workload, arch)
        for workload in ("resnet50", "transformer")
        for arch in ("arch_a", "arch_b", "arch_c")
    )
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(cases))) as pool:
        results = list(pool.map(run_case, cases))
    for workload, arch, result in results:
        (logs / f"{workload}-{arch}.log").write_text(
            result.stdout + result.stderr, encoding="utf-8"
        )
        if result.returncode:
            raise RuntimeError(
                f"{workload}/{arch} transient failed: {result.stderr[-1000:]}"
            )
        summary = [
            line
            for line in result.stdout.splitlines()
            if line.startswith(f"{MODEL}:")
            or line.strip().startswith("periodic peak=")
            or line.strip().startswith("fixed-318.15K")
            or line.strip().startswith("time-mean steady")
        ]
        print(f"{workload}/{arch}")
        for line in summary:
            print("  " + line.strip())


if __name__ == "__main__":
    main()
