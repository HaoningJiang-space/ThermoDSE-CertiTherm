"""Build registered linear thermal operators with the official HotSpot binary."""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import subprocess
from typing import Iterable, List, Sequence, Tuple

import numpy as np

from .core import ThermalFamily


@dataclass(frozen=True)
class HotSpotModel:
    model_id: str
    model_type: str
    grid_rows: int = 0
    grid_cols: int = 0
    grid_map_mode: str = "max"

    @classmethod
    def parse(cls, text: str) -> "HotSpotModel":
        if text == "block":
            return cls("block", "block")
        if text.startswith("grid") and text.endswith("-max"):
            size = int(text[4:-4])
            if size <= 0:
                raise ValueError("grid size must be positive")
            return cls(text, "grid", size, size, "max")
        raise ValueError(f"unsupported registered HotSpot model: {text}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _floorplan_units(path: Path) -> List[str]:
    units = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if fields and not fields[0].startswith("#") and len(fields) >= 5:
            units.append(fields[0])
    if not units or len(units) != len(set(units)):
        raise ValueError("floorplan must contain unique nonempty units")
    return units


def _parse_steady(path: Path, units: Sequence[str]) -> np.ndarray:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 2:
            try:
                values[fields[0]] = float(fields[1])
            except ValueError:
                pass
    missing = [unit for unit in units if unit not in values]
    if missing:
        raise RuntimeError(f"HotSpot steady output misses {len(missing)} floorplan units")
    out = np.asarray([values[unit] for unit in units])
    if not np.all(np.isfinite(out)):
        raise RuntimeError("HotSpot returned non-finite temperature")
    return out


def _write_ptrace(path: Path, units: Sequence[str], power_w: np.ndarray) -> None:
    path.write_text(
        "\t".join(units)
        + "\n"
        + "\t".join(f"{value:.12g}" for value in power_w)
        + "\n",
        encoding="utf-8",
    )


def _run(
    binary: Path,
    config: Path,
    floorplan: Path,
    materials: Path,
    model: HotSpotModel,
    units: Sequence[str],
    power_w: np.ndarray,
    workspace: Path,
    tag: str,
) -> np.ndarray:
    ptrace = workspace / f"{tag}.ptrace"
    steady = workspace / f"{tag}.steady"
    _write_ptrace(ptrace, units, power_w)
    command = [
        str(binary),
        "-c",
        str(config),
        "-f",
        str(floorplan),
        "-p",
        str(ptrace),
        "-materials_file",
        str(materials),
        "-model_type",
        model.model_type,
        "-steady_file",
        str(steady),
    ]
    if model.model_type == "grid":
        command += [
            "-grid_rows",
            str(model.grid_rows),
            "-grid_cols",
            str(model.grid_cols),
            "-grid_map_mode",
            model.grid_map_mode,
        ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"HotSpot {model.model_id} failed ({result.returncode}): {result.stderr[-500:]}"
        )
    return _parse_steady(steady, units)


def build_operator(
    binary: Path,
    config: Path,
    floorplan: Path,
    materials: Path,
    model: HotSpotModel,
    workspace: Path,
    workers: int = 8,
) -> Tuple[np.ndarray, np.ndarray, str, Tuple[str, ...]]:
    """Build one response matrix by zero-power and unit-impulse replay."""

    paths = tuple(Path(path).resolve() for path in (binary, config, floorplan, materials))
    if any(not path.is_file() for path in paths):
        raise FileNotFoundError("HotSpot binary/config/floorplan/materials must exist")
    workspace.mkdir(parents=True, exist_ok=True)
    units = tuple(_floorplan_units(paths[2]))
    zero = _run(*paths, model, units, np.zeros(len(units)), workspace, "zero")
    def impulse(index: int) -> np.ndarray:
        power = np.zeros(len(units))
        power[index] = 1.0
        return _run(
            *paths, model, units, power, workspace, f"impulse-{index:04d}"
        ) - zero

    if workers <= 0:
        raise ValueError("workers must be positive")
    with ThreadPoolExecutor(max_workers=min(workers, len(units))) as pool:
        columns = list(pool.map(impulse, range(len(units))))
    response = np.column_stack(columns)
    if np.any(response < -1e-7):
        raise RuntimeError("HotSpot response violates registered steady-state monotonicity")
    response = np.maximum(response, 0.0)
    provenance = hashlib.sha256(
        (
            model.model_id
            + "\n"
            + "\n".join(f"{path.name}\t{_sha256(path)}" for path in paths)
        ).encode("utf-8")
    ).hexdigest()
    return response, zero, provenance, units


def build_family(
    binary: Path,
    config: Path,
    floorplan: Path,
    materials: Path,
    model_ids: Iterable[str],
    workspace: Path,
    limit_k: float,
    workers: int = 8,
) -> Tuple[ThermalFamily, Tuple[str, ...]]:
    responses, ambients, provenance = [], [], []
    units: Tuple[str, ...] = ()
    parsed = tuple(HotSpotModel.parse(model_id) for model_id in model_ids)
    for model in parsed:
        response, ambient, digest, current_units = build_operator(
            binary,
            config,
            floorplan,
            materials,
            model,
            workspace / model.model_id,
            workers,
        )
        if units and units != current_units:
            raise RuntimeError("HotSpot models returned inconsistent block identities")
        units = current_units
        responses.append(response)
        ambients.append(ambient)
        provenance.append(digest)
    family = ThermalFamily(
        model_ids=tuple(model.model_id for model in parsed),
        response_k_per_w=np.stack(responses),
        ambient_k=np.stack(ambients),
        limit_k=limit_k,
        provenance_sha256=tuple(provenance),
    )
    return family, units


def save_family(path: Path, family: ThermalFamily, block_ids: Sequence[str]) -> None:
    """Store numeric evidence without pickle or ad-hoc JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        model_ids=np.asarray(family.model_ids),
        response_k_per_w=family.response_k_per_w,
        ambient_k=family.ambient_k,
        limit_k=np.asarray(family.limit_k),
        provenance_sha256=np.asarray(family.provenance_sha256),
        block_ids=np.asarray(block_ids),
    )


def load_family(path: Path) -> Tuple[ThermalFamily, Tuple[str, ...]]:
    with np.load(path, allow_pickle=False) as data:
        family = ThermalFamily(
            model_ids=tuple(data["model_ids"].tolist()),
            response_k_per_w=data["response_k_per_w"],
            ambient_k=data["ambient_k"],
            limit_k=float(data["limit_k"]),
            provenance_sha256=tuple(data["provenance_sha256"].tolist()),
        )
        return family, tuple(data["block_ids"].tolist())
