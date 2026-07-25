"""Run fixed-initial and converged-periodic HotSpot transient replay. (NON-CLAIM)

Usage:
    python research/triangle/transient_trace_probe.py \
        <complete-trace.npz> <floorplan.flp> <sim-workdir> <output> [model] [step-us]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.experiments import HOTSPOT
from CertiTherm.phase_trace import PhaseTrace
from CertiTherm.transient import replay_periodic


TRACE = Path(sys.argv[1])
FLOORPLAN = Path(sys.argv[2])
SIM = Path(sys.argv[3])
OUTPUT = Path(sys.argv[4])
MODEL = sys.argv[5] if len(sys.argv) > 5 else "block"
STEP_US = float(sys.argv[6]) if len(sys.argv) > 6 else 0.5


def main():
    with np.load(TRACE, allow_pickle=False) as data:
        block_ids = tuple(str(value) for value in data["block_ids"].tolist())
        trace = PhaseTrace(data["durations_s"], data["powers_w"])
    result = replay_periodic(
        binary=HOTSPOT,
        config=SIM / "example.config",
        floorplan=FLOORPLAN,
        materials=SIM / "example.materials",
        model_id=MODEL,
        block_ids=block_ids,
        trace=trace,
        workspace=OUTPUT,
        max_step_s=STEP_US * 1e-6,
        fixed_initial_k=318.15,
        tolerance_k=0.01,
    )
    report = {
        "trace": str(TRACE),
        "floorplan": str(FLOORPLAN),
        "model": MODEL,
        "max_step_us": STEP_US,
        "actual_step_s": result.step_s,
        "samples_per_cycle": result.samples_per_cycle,
        "cycles": result.cycles,
        "boundary_residual_k": result.boundary_residual_k,
        "peak_residual_k": result.peak_residual_k,
        "periodic_peak_k": result.periodic_peak_k,
        "periodic_hottest_block": result.periodic_hottest_block,
        "fixed_initial_k": 318.15,
        "fixed_initial_peak_k": result.fixed_initial_peak_k,
        "fixed_initial_hottest_block": result.fixed_initial_hottest_block,
        "mean_steady_peak_k": result.mean_steady_peak_k,
        "mean_steady_hottest_block": result.mean_steady_hottest_block,
        "temperature_output_resolution_k": result.temperature_output_resolution_k,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT / "transient_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"{MODEL}: dt={result.step_s * 1e6:.6f} us, "
        f"{result.samples_per_cycle} samples/cycle, {result.cycles} cycles"
    )
    print(
        f"  periodic residual: boundary={result.boundary_residual_k:.6e} K, "
        f"peak={result.peak_residual_k:.6e} K"
    )
    print(
        f"  periodic peak={result.periodic_peak_k:.6f} K "
        f"at {result.periodic_hottest_block}"
    )
    print(
        f"  fixed-318.15K one-cycle peak={result.fixed_initial_peak_k:.6f} K "
        f"at {result.fixed_initial_hottest_block}"
    )
    print(
        f"  time-mean steady peak={result.mean_steady_peak_k:.6f} K "
        f"at {result.mean_steady_hottest_block}; "
        f"periodic uplift={result.periodic_peak_k-result.mean_steady_peak_k:.6f} K"
    )
    print(f"  wrote {report_path}")
    print(
        "  TRANSIENT REPLAY ONLY. A temperature decision requires timestep/model "
        "convergence and cross-candidate comparison."
    )


if __name__ == "__main__":
    main()
