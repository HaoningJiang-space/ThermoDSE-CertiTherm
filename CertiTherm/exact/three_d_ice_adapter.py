#!/usr/bin/env python3
"""Adapter: HotSpot-style floorplan/ptrace -> 3D-ICE steady temperatures."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


POWER_SCALE = 16.0


REPO_ROOT = Path(__file__).resolve().parents[2]
THREE_D_ICE_BIN = REPO_ROOT / "3d-ice" / "bin" / "3D-ICE-Emulator"


def _read_hotspot_flp(path: Path) -> list[tuple[str, float, float, float, float]]:
    rows: list[tuple[str, float, float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        parts = text.split()
        if len(parts) < 5:
            continue
        rows.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])))
    if not rows:
        raise RuntimeError(f"no floorplan rows in {path}")
    return rows


def _read_ptrace(path: Path) -> dict[str, float]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 2:
        raise RuntimeError(f"invalid ptrace: {path}")
    names = lines[0].split("\t")
    values = [float(v) for v in lines[1].split("\t")]
    if len(names) != len(values):
        raise RuntimeError(f"ptrace header/value mismatch: {path}")
    return dict(zip(names, values))


def _parse_hotspot_config(config_path: Path) -> dict[str, float | str]:
    out: dict[str, float | str] = {}
    pattern = re.compile(r"^\s*(-[A-Za-z0-9_]+)\s+([^\s#]+)")
    for line in config_path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = pattern.match(text)
        if not match:
            continue
        key = match.group(1)
        value = match.group(2)
        if value == "(null)":
            continue
        try:
            out[key] = float(value)
        except ValueError:
            out[key] = value
    return out


def _read_materials(path: Path) -> dict[str, dict[str, float | str]]:
    rows = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    out: dict[str, dict[str, float | str]] = {}
    idx = 0
    while idx + 3 < len(rows):
        name = rows[idx]
        mtype = rows[idx + 1]
        try:
            conductivity = float(rows[idx + 2])
            capacity = float(rows[idx + 3])
        except ValueError:
            idx += 1
            continue
        entry: dict[str, float | str] = {
            "type": mtype,
            "conductivity": conductivity,
            "capacity": capacity,
        }
        if mtype == "fluid" and idx + 4 < len(rows):
            try:
                entry["viscosity"] = float(rows[idx + 4])
                idx += 5
            except ValueError:
                idx += 4
        else:
            idx += 4
        out[name] = entry
    return out


def _write_3dice_flp(
    path: Path,
    rows: list[tuple[str, float, float, float, float]],
    powers: dict[str, float],
) -> tuple[float, float]:
    scale = 1.0e6  # hotspot files are in meters
    max_x = 0.0
    max_y = 0.0
    with path.open("w", encoding="utf-8") as stream:
        flp_names = [name for name, _, _, _, _ in rows]
        ptrace_names = list(powers.keys())
        if set(flp_names) != set(ptrace_names):
            missing = sorted(set(flp_names) - set(ptrace_names))
            extra = sorted(set(ptrace_names) - set(flp_names))
            raise RuntimeError(
                "ptrace/floorplan block mismatch: "
                f"missing={missing[:8]} extra={extra[:8]}"
            )
        for name, w, h, x, y in rows:
            px = max(0, int(round(x * scale)))
            py = max(0, int(round(y * scale)))
            pw = max(1, int(round(w * scale)))
            ph = max(1, int(round(h * scale)))
            # The emulator consumes the replay-corpus trace unit, which is
            # a calibrated scale above the raw ThermoDSE watt values.
            p = float(powers[name]) * POWER_SCALE
            stream.write(f"{name} :\n")
            stream.write(f"  position {px}, {py} ;\n")
            stream.write(f"  dimension {pw}, {ph} ;\n")
            stream.write(f"  power values {p:.10f} ;\n\n")
            max_x = max(max_x, px + pw)
            max_y = max(max_y, py + ph)
    return max_x, max_y


def _write_stk(
    path: Path,
    flp_file: Path,
    chip_length: int,
    chip_width: int,
    ambient: float,
    heat_transfer_coeff: float,
    chip_thickness: float,
    chip_conductivity: float,
    chip_capacity: float,
    spreader_side: float,
    spreader_thickness: float,
) -> Path:
    tflp_out = path.parent / "tflp.txt"
    path.write_text(
        (
            "material CHIP_MAT :\n"
            f"   thermal conductivity     {chip_conductivity * 1e-6:.12g} ;\n"
            f"   volumetric heat capacity {chip_capacity * 1e-18:.12g} ;\n\n"
            "top heat sink :\n"
            f"   heat transfer coefficient {heat_transfer_coeff:.12g} ;\n"
            f"   temperature               {ambient:.6f} ;\n\n"
            "dimensions :\n"
            f"   chip length {chip_length}, width {chip_width} ;\n"
            f"   cell length {max(1, chip_length // 10)}, width {max(1, chip_width // 10)} ;\n"
            "   non-uniform true;\n\n"
            "die TOP_IC :\n"
            f"   source {max(chip_thickness * 1e6, 1.0):.3f} CHIP_MAT ;\n\n"
            "stack:\n"
            f'   die DIE0 TOP_IC floorplan "{flp_file}" ;\n\n'
            "solver:\n"
            "   steady ;\n"
            f"   initial temperature {ambient:.6f} ;\n"
            "   numofcores 1 ;\n\n"
            "output:\n"
            f'   Tflp ( DIE0, "{tflp_out}", average, final ) ;\n'
        ),
        encoding="utf-8",
    )
    return tflp_out


def _parse_tflp(path: Path) -> dict[str, float]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    data = [line for line in lines if not line.startswith("%")]
    if not data:
        raise RuntimeError(f"empty Tflp output: {path}")
    header = [item.strip() for item in lines[-2].lstrip("%").split("\t") if item.strip()]
    values = [item.strip() for item in data[-1].split("\t") if item.strip()]
    if len(header) < 2 or len(values) < 2:
        raise RuntimeError(f"cannot parse Tflp output: {path}")
    result: dict[str, float] = {}
    for name, value in zip(header[1:], values[1:]):
        clean = name.replace("(K)", "").strip()
        result[clean] = float(value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="3D-ICE adapter for CertiTherm witness replay")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--floorplan", type=Path, required=True)
    parser.add_argument("--ptrace", type=Path, required=True)
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--steady-out", type=Path, required=True)
    args = parser.parse_args()

    if not THREE_D_ICE_BIN.is_file():
        raise SystemExit(f"3D-ICE emulator not found: {THREE_D_ICE_BIN}")

    flp_rows = _read_hotspot_flp(args.floorplan)
    powers = _read_ptrace(args.ptrace)
    cfg = _parse_hotspot_config(args.config)
    materials = _read_materials(args.materials)

    ambient = float(cfg.get("-ambient", 300.0))
    r_convec = float(cfg.get("-r_convec", 0.05))
    sink_side = float(cfg.get("-s_sink", 0.05))
    sink_area = max(sink_side * sink_side, 1e-12)
    heat_transfer_coeff = 1.0 / (r_convec * sink_area)

    chip_material = str(cfg.get("-material_chip", "silicon"))
    chip = materials.get(chip_material, {})
    chip_conductivity = float(chip.get("conductivity", 130.0))
    chip_capacity = float(chip.get("capacity", 1630300.0))
    chip_thickness = float(cfg.get("-t_chip", 0.00015))
    spreader_side = float(cfg.get("-s_spreader", sink_side))
    spreader_thickness = float(cfg.get("-t_spreader", 0.0013))

    with tempfile.TemporaryDirectory(prefix="certitherm_3dice_") as tmp:
        tmpdir = Path(tmp)
        flp_path = tmpdir / "input.flp"
        chip_x, chip_y = _write_3dice_flp(flp_path, flp_rows, powers)
        stk_path = tmpdir / "input.stk"
        tflp_out = _write_stk(
            stk_path,
            flp_path,
            chip_length=max(1, int(round(chip_x))),
            chip_width=max(1, int(round(chip_y))),
            ambient=ambient,
            heat_transfer_coeff=heat_transfer_coeff,
            chip_thickness=chip_thickness,
            chip_conductivity=chip_conductivity,
            chip_capacity=chip_capacity,
            spreader_side=spreader_side,
            spreader_thickness=spreader_thickness,
        )
        result = subprocess.run(
            [str(THREE_D_ICE_BIN), str(stk_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"3D-ICE emulator failed ({result.returncode}): {result.stderr[-400:]}")
        temps = _parse_tflp(tflp_out)
        args.steady_out.parent.mkdir(parents=True, exist_ok=True)
        with args.steady_out.open("w", encoding="utf-8") as stream:
            for name, value in temps.items():
                stream.write(f"{name} {value:.6f}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
