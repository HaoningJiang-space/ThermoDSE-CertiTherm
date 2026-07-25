"""Measure legacy-vs-physical route effects on the ThermoDSE objective. (NON-CLAIM)

Usage:
    python research/triangle/route_objective_probe.py \
        <out> <workload> <arch> <legacy|physical>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.experiments import (
    ROOT,
    _prepare_thermodse_sim,
    _registry_split,
    _rows,
    _thermodse_evaluator,
)
from research.triangle.order_trace_probe import monitor_snapshot


OUTPUT = Path(sys.argv[1])
WORKLOAD = sys.argv[2]
ARCH_ID = sys.argv[3]
MODE = sys.argv[4]


def main():
    if MODE not in ("legacy", "physical"):
        raise ValueError("mode must be legacy or physical")
    reg = _registry_split("dev_v3")
    arch = next(
        row
        for row in _rows(ROOT / "experiments" / "architectures.tsv")
        if row["split"] == reg and row["architecture_id"] == ARCH_ID
    )
    workload = next(
        row
        for row in _rows(ROOT / "experiments" / "workloads.tsv")
        if row["split"] == reg and row["workload_id"] == WORKLOAD
    )
    package = next(
        row
        for row in _rows(ROOT / "experiments" / "packages.tsv")
        if row["package_id"] == "default"
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sim = _prepare_thermodse_sim(arch, workload, package, OUTPUT, allow_hotspot=True)
    evaluator = _thermodse_evaluator(
        arch, workload, sim, physical_nop=(MODE == "physical")
    )
    evaluator.generate_hardware()
    # The endpoint objective is independent of the legacy steady thermal side effect.
    # Suppress that call narrowly; this probe makes no temperature claim.
    evaluator.flp_generator.run_hotspot = lambda *args, **kwargs: None
    with monitor_snapshot(evaluator) as snapshot:
        endpoint_latency_ms, endpoint_energy_mj, die_yield = evaluator.evaluate()
    network = next(iter(snapshot["latency_dict"]))
    physical_latency_ms = (
        float(np.sum(snapshot["latency_dict"][network]))
        / float(evaluator.monitor.clk_freq)
        * 1e3
    )
    source_energy_mj = (
        float(np.sum(snapshot["core_dict"][network]))
        + float(np.sum(snapshot["noc_dict"][network]))
        + float(np.sum(snapshot["nop_dict"][network]))
        + float(np.sum(snapshot["dram_dict"][network]))
    ) * 1e-9
    report = {
        "workload": WORKLOAD,
        "arch": ARCH_ID,
        "route_mode": MODE,
        "endpoint_latency_ms": float(endpoint_latency_ms),
        "physical_latency_ms": physical_latency_ms,
        "endpoint_energy_mj": float(endpoint_energy_mj),
        "source_energy_mj": source_energy_mj,
        "die_yield": float(die_yield),
        "endpoint_edyp": (
            float(endpoint_latency_ms) * float(endpoint_energy_mj) / float(die_yield)
        ),
        "physical_time_edyp": (
            physical_latency_ms * float(endpoint_energy_mj) / float(die_yield)
        ),
    }
    output = OUTPUT / f"route_objective_{WORKLOAD}_{ARCH_ID}_{MODE}.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"{WORKLOAD}/{ARCH_ID}/{MODE}: physical latency={physical_latency_ms:.6f} ms, "
        f"endpoint energy={endpoint_energy_mj:.6f} mJ, "
        f"physical-time EDYP={report['physical_time_edyp']:.9g}"
    )
    print(f"  source energy={source_energy_mj:.6f} mJ; wrote {output}")
    print("  OBJECTIVE AUDIT ONLY. The steady thermal side effect was suppressed.")


if __name__ == "__main__":
    main()
