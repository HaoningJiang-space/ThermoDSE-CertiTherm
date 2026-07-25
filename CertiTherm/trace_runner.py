"""Name-aligned ThermoDSE-to-HotSpot wrapper; never truncates by column index.

Aligning by NAME removes the positional-truncation hazard but introduces a different one:
a ptrace column whose name is not a floorplan unit is simply not carried over. In practice
that silently discarded 10.9% of the dissipated energy -- ThermoDSE emits an `interposer`
column holding all NoP power and no floorplan unit is named `interposer`, so the heat
vanished with no diagnostic at all (docs/THERMODSE_ENDPOINT_AUDIT.md). `align_trace`
therefore FAILS CLOSED on any unplaced column that carries power.
"""

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


def unplaced_power(source: Path, floorplan: Path) -> dict:
    """Power sitting in ptrace columns that name no floorplan unit.

    That is heat alignment would discard. Keyed by column name, holding the largest
    magnitude seen over all rows so a column that is non-zero in any sample is caught.
    """
    lines = [line.split() for line in source.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if len(lines) < 2:
        return {}
    units = set(floorplan_units(floorplan))
    dropped = {}
    for column, name in enumerate(lines[0]):
        if name in units:
            continue
        worst = 0.0
        for values in lines[1:]:
            if column < len(values):
                try:
                    worst = max(worst, abs(float(values[column])))
                except ValueError:
                    continue
        if worst > 0.0:
            dropped[name] = worst
    return dropped


def align_trace(source: Path, floorplan: Path, output: Path,
                allow_unplaced: bool = False) -> dict:
    """Reorder `source`'s columns onto `floorplan`'s units by name.

    Returns the unplaced-power report. Raises unless `allow_unplaced`, because a column
    naming no floorplan unit is heat that never reaches the thermal model: dropping it
    understates every temperature while leaving the output entirely plausible.
    """
    lines = [line.split() for line in source.read_text(encoding="utf-8").splitlines()]
    if len(lines) < 2 or len(lines[0]) != len(set(lines[0])):
        raise ValueError("ptrace needs a unique header and at least one sample")
    header, units = lines[0], floorplan_units(floorplan)
    index = {name: column for column, name in enumerate(header)}
    missing = [name for name in units if name not in index]
    if missing:
        raise ValueError(f"ptrace misses {len(missing)} floorplan units")
    dropped = unplaced_power(source, floorplan)
    if dropped and not allow_unplaced:
        worst = sorted(dropped.items(), key=lambda kv: -kv[1])[:4]
        raise ValueError(
            f"{len(dropped)} ptrace column(s) name no floorplan unit yet carry power "
            f"(up to {sum(dropped.values()):.4f} W in total): {worst}. Aligning would "
            f"discard that heat silently. Place the source, or pass allow_unplaced=True "
            f"to accept the omission as a declared boundary and record it.")
    rows = [units]
    for values in lines[1:]:
        if len(values) != len(header):
            raise ValueError("ptrace row length differs from its header")
        rows.append([values[index[name]] for name in units])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join("\t".join(row) for row in rows) + "\n", encoding="utf-8"
    )
    return dropped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("floorplan")
    parser.add_argument("ptrace")
    parser.add_argument("side")
    parser.add_argument("workspace")
    parser.add_argument("--hotspot", required=True)
    parser.add_argument("--allow-unplaced", action="store_true",
                        help="accept ptrace columns naming no floorplan unit, recording "
                             "the discarded power instead of failing closed")
    args = parser.parse_args()
    workspace = Path(args.workspace).resolve()
    aligned = workspace / "ptrace" / "name_aligned.ptrace"
    dropped = align_trace(Path(args.ptrace), Path(args.floorplan), aligned,
                          allow_unplaced=args.allow_unplaced)
    if dropped:
        print(f"WARNING: accepted {len(dropped)} unplaced column(s) carrying "
              f"{sum(dropped.values()):.4f} W as a DECLARED BOUNDARY: {sorted(dropped)}")
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
