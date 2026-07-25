"""Run the registered 2-workload x 3-candidate transient matrix. (NON-CLAIM)

Usage:
    python research/triangle/transient_matrix_probe.py <complete-root> <out> [model] [step-us]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


COMPLETE = Path(sys.argv[1])
OUTPUT = Path(sys.argv[2])
MODEL = sys.argv[3] if len(sys.argv) > 3 else "block"
STEP_US = sys.argv[4] if len(sys.argv) > 4 else "0.5"


def main():
    logs = OUTPUT / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    for workload in ("resnet50", "transformer"):
        for arch in ("arch_a", "arch_b", "arch_c"):
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
            ]
            print(f"{workload}/{arch}")
            for line in summary:
                print("  " + line.strip())


if __name__ == "__main__":
    main()
