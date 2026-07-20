"""Name-aligned ThermoDSE-to-HotSpot wrapper; never truncates by column index."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess


def floorplan_units(path: Path) -> list[str]:
    return [
        fields[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if len(fields := line.split()) >= 5 and not fields[0].startswith("#")
    ]


def align_trace(source: Path, floorplan: Path, output: Path) -> None:
    lines = [line.split() for line in source.read_text(encoding="utf-8").splitlines()]
    if len(lines) < 2 or len(lines[0]) != len(set(lines[0])):
        raise ValueError("ptrace needs a unique header and at least one sample")
    header, units = lines[0], floorplan_units(floorplan)
    index = {name: column for column, name in enumerate(header)}
    missing = [name for name in units if name not in index]
    if missing:
        raise ValueError(f"ptrace misses {len(missing)} floorplan units")
    rows = [units]
    for values in lines[1:]:
        if len(values) != len(header):
            raise ValueError("ptrace row length differs from its header")
        rows.append([values[index[name]] for name in units])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join("\t".join(row) for row in rows) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("floorplan")
    parser.add_argument("ptrace")
    parser.add_argument("side")
    parser.add_argument("workspace")
    parser.add_argument("--hotspot", required=True)
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    aligned = workspace / "ptrace" / "name_aligned.ptrace"
    align_trace(Path(args.ptrace), Path(args.floorplan), aligned)
    outputs = workspace / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    command = [
        args.hotspot,
        "-c",
        args.config,
        "-f",
        args.floorplan,
        "-p",
        str(aligned),
        "-materials_file",
        str(workspace / "example.materials"),
        "-model_type",
        "grid",
        "-grid_rows",
        "64",
        "-grid_cols",
        "64",
        "-grid_map_mode",
        "max",
        "-steady_file",
        str(outputs / "gcc.steady"),
        "-grid_steady_file",
        str(outputs / "gcc.grid.steady"),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise SystemExit(f"HotSpot failed ({result.returncode}): {result.stderr[-500:]}")


if __name__ == "__main__":
    main()
