"""Fail-closed adapter for the custom batched FP64 CUDA HotSpot backend."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import struct
import subprocess
from typing import Sequence, Tuple

import numpy as np


_OUTPUT_HEADER = struct.Struct("<8sIIQQQdd")


@dataclass(frozen=True)
class GpuHotSpotBackend:
    exporter: Path
    solver: Path
    device: int = 0
    relative_tolerance: float = 1e-11
    absolute_tolerance: float = 1e-12
    max_iterations: int = 10_000

    def __post_init__(self) -> None:
        if self.device < 0:
            raise ValueError("GPU device must be nonnegative")
        if self.relative_tolerance <= 0 or self.absolute_tolerance < 0:
            raise ValueError("invalid GPU solver tolerances")
        if self.max_iterations <= 0:
            raise ValueError("GPU solver iteration limit must be positive")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _floorplan_units(path: Path) -> Tuple[str, ...]:
    units = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields and not fields[0].startswith("#") and len(fields) >= 5:
            units.append(fields[0])
    if not units or len(units) != len(set(units)):
        raise ValueError("floorplan must contain unique nonempty units")
    return tuple(units)


def _write_zero_ptrace(path: Path, units: Sequence[str]) -> None:
    path.write_text(
        "\t".join(units) + "\n" + "\t".join("0" for _ in units) + "\n",
        encoding="utf-8",
    )


def _require_linear_config(path: Path) -> None:
    """Reject HotSpot feedback modes that do not define one affine operator."""

    flags: dict[str, int] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        fields = raw_line.split("#", 1)[0].split()
        if len(fields) >= 2 and fields[0] in {
            "-leakage_used",
            "-package_model_used",
        }:
            try:
                flags[fields[0]] = int(fields[1])
            except ValueError as exc:
                raise ValueError(f"invalid HotSpot flag in {path}: {raw_line}") from exc
    enabled = sorted(flag for flag, value in flags.items() if value != 0)
    if enabled:
        raise ValueError(
            "GPU operator requires fixed linear physics; unsupported: "
            + ", ".join(enabled)
        )


def _read_output(path: Path) -> tuple[np.ndarray, int, float, float]:
    with path.open("rb") as stream:
        raw = stream.read(_OUTPUT_HEADER.size)
        if len(raw) != _OUTPUT_HEADER.size:
            raise RuntimeError("truncated GPU HotSpot output header")
        magic, version, scalar_bytes, blocks, rhs, iterations, residual, solve_ms = (
            _OUTPUT_HEADER.unpack(raw)
        )
        if magic[:7] != b"CTHGO01" or version != 1 or scalar_bytes != 8:
            raise RuntimeError("unsupported GPU HotSpot output format")
        payload = stream.read()
    expected = blocks * rhs * scalar_bytes
    if len(payload) != expected:
        raise RuntimeError(
            f"GPU HotSpot output payload has {len(payload)} bytes, expected {expected}"
        )
    values = np.frombuffer(payload, dtype="<f8").reshape((blocks, rhs)).copy()
    if not np.all(np.isfinite(values)) or not np.isfinite(residual):
        raise RuntimeError("GPU HotSpot returned non-finite output")
    return values, int(iterations), float(residual), float(solve_ms)


def build_grid_operator_gpu(
    reference_binary: Path,
    config: Path,
    floorplan: Path,
    materials: Path,
    model,
    workspace: Path,
    backend: GpuHotSpotBackend,
) -> tuple[np.ndarray, np.ndarray, str, Tuple[str, ...]]:
    """Build zero and all unit responses in one exact-system GPU batch."""

    if model.model_type != "grid" or model.grid_map_mode != "avg":
        raise ValueError("GPU backend supports registered grid-average models only")
    paths = tuple(
        Path(path).resolve()
        for path in (
            reference_binary,
            config,
            floorplan,
            materials,
            backend.exporter,
            backend.solver,
        )
    )
    if any(not path.is_file() for path in paths):
        raise FileNotFoundError("GPU HotSpot inputs and binaries must exist")
    _require_linear_config(paths[1])
    workspace.mkdir(parents=True, exist_ok=True)
    units = _floorplan_units(paths[2])
    ptrace = workspace / "zero.ptrace"
    steady = workspace / "export.steady"
    system = workspace / "system.bin"
    output = workspace / "temperatures.bin"
    stats = workspace / "solver.tsv"
    _write_zero_ptrace(ptrace, units)

    command = [
        str(paths[4]),
        "-c",
        str(paths[1]),
        "-f",
        str(paths[2]),
        "-p",
        str(ptrace),
        "-materials_file",
        str(paths[3]),
        "-model_type",
        "grid",
        "-grid_rows",
        str(model.grid_rows),
        "-grid_cols",
        str(model.grid_cols),
        "-grid_map_mode",
        "avg",
        "-steady_file",
        str(steady),
    ]
    environment = os.environ.copy()
    environment["CERTITHERM_GPU_SYSTEM"] = str(system)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=300,
        env=environment,
    )
    if result.returncode != 0 or not system.is_file():
        raise RuntimeError(
            "HotSpot GPU system export failed: "
            + (result.stderr or result.stdout)[-800:]
        )

    result = subprocess.run(
        [
            str(paths[5]),
            str(system),
            str(output),
            str(stats),
            str(backend.device),
            f"{backend.relative_tolerance:.17g}",
            f"{backend.absolute_tolerance:.17g}",
            str(backend.max_iterations),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0 or not output.is_file() or not stats.is_file():
        raise RuntimeError(
            "custom CUDA HotSpot solve failed: "
            + (result.stderr or result.stdout)[-800:]
        )

    temperatures, _, residual, _ = _read_output(output)
    if temperatures.shape != (len(units), len(units) + 1):
        raise RuntimeError(
            "GPU HotSpot block mapping disagrees with floorplan unit registry"
        )
    ambient = temperatures[:, 0]
    response = temperatures[:, 1:] - ambient[:, None]
    if np.any(response < -1e-7):
        raise RuntimeError("GPU HotSpot response violates steady-state monotonicity")
    response = np.maximum(response, 0.0)
    provenance = hashlib.sha256(
        (
            "certitherm-custom-fp64-batched-pcg-v1\n"
            + model.model_id
            + "\n"
            + f"relative_residual={residual:.17g}\n"
            + "\n".join(f"{path.name}\t{_sha256(path)}" for path in paths)
            + f"\nsystem.bin\t{_sha256(system)}"
        ).encode("utf-8")
    ).hexdigest()
    return response, ambient, provenance, units
