"""Summarize NON-CLAIM spatial-trace probes without copying raw artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from CertiTherm.phase_trace import PhaseTrace
from CertiTherm.thermodse_trace import (
    ThermoDSETraceLowering,
    spatial_variation,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(
        "workload,arch,orders,physical_ms,represented_fraction,"
        "residual_mj,spatial_tv_weighted,spatial_tv_max,unique_hottest_blocks"
    )
    reports = sorted(args.root.glob("*/order_trace_probe_*.json"))
    if not reports:
        raise SystemExit(f"no probe reports below {args.root}")
    for report_path in reports:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if len(report["networks"]) != 1:
            raise RuntimeError("summary requires one captured network per probe")
        network = next(iter(report["networks"].values()))
        with np.load(network["spatial_trace_npz"], allow_pickle=False) as data:
            lowering = ThermoDSETraceLowering(
                block_ids=tuple(str(value) for value in data["block_ids"]),
                trace=PhaseTrace(
                    durations_s=np.asarray(data["durations_s"], dtype=float),
                    powers_w=np.asarray(data["powers_w"], dtype=float),
                ),
                unplaced_energy_j=np.asarray(data["unplaced_energy_j"], dtype=float),
            )
        variation = spatial_variation(lowering)
        print(
            f"{report['workload']},{report['arch']},{network['orders']},"
            f"{lowering.trace.total_time_s * 1e3:.6f},"
            f"{lowering.represented_fraction:.4f},"
            f"{lowering.residual_energy_j * 1e3:.4f},"
            f"{variation.time_weighted_tv:.4f},{variation.max_tv:.4f},"
            f"{len(variation.unique_hottest_block_ids)}"
        )


if __name__ == "__main__":
    main()
