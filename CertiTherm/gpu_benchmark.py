"""Independent CPU-HotSpot parity and end-to-end GPU operator benchmark."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import shutil
import time
from typing import Optional

import numpy as np

from .gpu_hotspot import GpuHotSpotBackend, build_grid_operator_gpu
from .hotspot import HotSpotModel, build_operator, replay_power


ERROR_LIMIT_K = 0.01
THERMAL_LIMIT_K = 330.0
DECISION_MARGIN_K = 1e-4
MODELS = ("grid64-avg", "grid128-avg")
CASES = ("example1", "thermodse-227")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _thermal_state(peak_k: float) -> str:
    conservative_peak = peak_k + ERROR_LIMIT_K
    if conservative_peak <= THERMAL_LIMIT_K - DECISION_MARGIN_K:
        return "SAFE"
    if conservative_peak >= THERMAL_LIMIT_K + DECISION_MARGIN_K:
        return "REJECT"
    return "NUMERICAL_GAP"


def _read_placed_power(path: Path, units: tuple[str, ...]) -> np.ndarray:
    lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines()]
    if len(lines) != 2 or tuple(lines[0]) != units or len(lines[1]) != len(units):
        raise RuntimeError("placed-power trace does not match the floorplan registry")
    power = np.asarray(lines[1], dtype=float)
    if np.any(~np.isfinite(power)) or np.any(power < 0):
        raise RuntimeError("placed-power trace must be finite and nonnegative")
    return power


def _case_inputs(
    reference: Path, case_id: str
) -> tuple[Path, Path, Path, Optional[Path]]:
    if case_id == "example1":
        example = reference.parent / "examples" / "example1"
        return (
            example / "example.config",
            example / "ev6.flp",
            example / "example.materials",
            None,
        )
    if case_id == "thermodse-227":
        template = (
            reference.resolve().parents[2]
            / "CertiTherm"
            / "evidence"
            / "thermodse_tmp_template"
        )
        return (
            template / "example.config",
            template / "floorplan" / "output_3D.flp",
            template / "example.materials",
            template / "ptrace" / "cores_3D_fixed.ptrace",
        )
    raise ValueError(f"unknown GPU benchmark case: {case_id}")


def run(
    reference: Path,
    exporter: Path,
    solver: Path,
    output: Path,
    device: int,
    case_id: str,
) -> None:
    config, floorplan, materials, placed_trace = _case_inputs(reference, case_id)
    required = (reference, exporter, solver, config, floorplan, materials)
    if any(not path.is_file() for path in required) or (
        placed_trace is not None and not placed_trace.is_file()
    ):
        raise RuntimeError("GPU parity inputs are incomplete; run make gpu-bootstrap")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    backend = GpuHotSpotBackend(exporter, solver, device=device)
    rows: list[dict[str, object]] = []
    timing: list[dict[str, object]] = []

    for model_id in MODELS:
        model = HotSpotModel.parse(model_id)
        cpu_start = time.perf_counter()
        cpu_response, cpu_ambient, _, units = build_operator(
            reference,
            config,
            floorplan,
            materials,
            model,
            output / "cpu" / model_id,
            workers=16,
        )
        cpu_seconds = time.perf_counter() - cpu_start
        gpu_start = time.perf_counter()
        gpu_response, gpu_ambient, _, gpu_units = build_grid_operator_gpu(
            reference,
            config,
            floorplan,
            materials,
            model,
            output / "gpu" / model_id,
            backend,
        )
        gpu_seconds = time.perf_counter() - gpu_start
        if units != gpu_units:
            raise RuntimeError("CPU/GPU block registry mismatch")
        ambient_error = float(np.max(np.abs(cpu_ambient - gpu_ambient)))
        response_error = float(np.max(np.abs(cpu_response - gpu_response)))
        rows.extend(
            (
                {
                    "input": case_id,
                    "model": model_id,
                    "case": "zero-ambient",
                    "max_abs_error_k": ambient_error,
                    "limit_k": ERROR_LIMIT_K,
                    "cpu_state": "",
                    "gpu_state": "",
                    "decision_status": "",
                    "status": "PASS" if ambient_error <= ERROR_LIMIT_K else "REJECT",
                },
                {
                    "input": case_id,
                    "model": model_id,
                    "case": "all-unit-impulses",
                    "max_abs_error_k": response_error,
                    "limit_k": ERROR_LIMIT_K,
                    "cpu_state": "",
                    "gpu_state": "",
                    "decision_status": "",
                    "status": "PASS" if response_error <= ERROR_LIMIT_K else "REJECT",
                },
            )
        )
        timing.append(
            {
                "input": case_id,
                "model": model_id,
                "cpu_seconds": cpu_seconds,
                "gpu_seconds": gpu_seconds,
                "speedup": cpu_seconds / gpu_seconds,
                "status": "PASS" if gpu_seconds < cpu_seconds else "REJECT",
            }
        )

        rng = np.random.default_rng(20260721)
        powers = [
            ("zero", np.zeros(len(units))),
            ("uniform", np.full(len(units), 2.0)),
            ("ramp", np.linspace(0.25, 4.0, len(units))),
            ("random", rng.uniform(0.0, 5.0, len(units))),
        ]
        if placed_trace is not None:
            powers.append(("placed", _read_placed_power(placed_trace, units)))
        for case, power in powers:
            direct = replay_power(
                reference,
                config,
                floorplan,
                materials,
                model_id,
                units,
                power,
                output / "direct" / model_id / case,
            )
            predicted = gpu_ambient + gpu_response @ power
            error = float(np.max(np.abs(direct - predicted)))
            cpu_state = _thermal_state(float(np.max(direct)))
            gpu_state = _thermal_state(float(np.max(predicted)))
            accepted = error <= ERROR_LIMIT_K and cpu_state == gpu_state
            rows.append(
                {
                    "input": case_id,
                    "model": model_id,
                    "case": case,
                    "max_abs_error_k": error,
                    "limit_k": ERROR_LIMIT_K,
                    "cpu_state": cpu_state,
                    "gpu_state": gpu_state,
                    "decision_status": (
                        "MATCH" if cpu_state == gpu_state else "MISMATCH"
                    ),
                    "status": "PASS" if accepted else "REJECT",
                }
            )

    _write_tsv(output / "parity.tsv", rows)
    _write_tsv(output / "timing.tsv", timing)
    rejected = [row for row in rows if row["status"] != "PASS"]
    slow = [row for row in timing if row["status"] != "PASS"]
    manifest_rows = []
    for path in sorted(output.rglob("*.tsv")):
        manifest_rows.append(
            {"path": str(path.relative_to(output)), "sha256": _sha256(path)}
        )
    _write_tsv(output / "ARTIFACTS.tsv", manifest_rows)
    lines = [
        "# GPU HotSpot development gate",
        "",
        f"- Parity cases: {len(rows) - len(rejected)}/{len(rows)} PASS",
        f"- Physical input: `{case_id}`",
        f"- Faster operator builds: {len(timing) - len(slow)}/{len(timing)} PASS",
        f"- Maximum absolute temperature error: {max(float(row['max_abs_error_k']) for row in rows):.9g} K",
        f"- Matched thermal decisions: {sum(row['decision_status'] == 'MATCH' for row in rows)}/{sum(bool(row['decision_status']) for row in rows)}",
        f"- Minimum end-to-end speedup: {min(float(row['speedup']) for row in timing):.3f}x",
        "",
        "CPU HotSpot is the reference. GPU kernel output is not used as its own validation.",
    ]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if rejected:
        raise RuntimeError(f"GPU HotSpot parity rejected {len(rejected)} case(s)")
    if slow:
        raise RuntimeError(f"GPU HotSpot was not faster for {len(slow)} model(s)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--exporter", type=Path, required=True)
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--case", choices=CASES, default="example1")
    args = parser.parse_args()
    run(
        args.reference,
        args.exporter,
        args.solver,
        args.output,
        args.device,
        args.case,
    )


if __name__ == "__main__":
    main()
