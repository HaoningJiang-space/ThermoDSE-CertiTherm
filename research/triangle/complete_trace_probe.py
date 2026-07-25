"""Build one complete routed ThermoDSE phase trace. (NON-CLAIM)

This is the first probe whose emitted power matrix accounts for core, NoC, NoP, and DRAM
energy and whose columns exactly match its augmented HotSpot floorplan.  It still performs
no thermal replay: passing this probe closes the trace-construction prerequisite, not the
transient or decision gate.

Usage:
    python research/triangle/complete_trace_probe.py <out> <workload> <arch_id>
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
from CertiTherm.routed_trace import augment_floorplan_with_dram, lower_routed_trace
from CertiTherm.thermodse_trace import lower_monitor_trace
from CertiTherm.trace_runner import floorplan_units
from research.triangle.order_trace_probe import monitor_snapshot
from research.triangle.route_event_probe import capture_route_events


OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/v6complete")
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
ARCH_ID = sys.argv[3] if len(sys.argv) > 3 else "arch_c"


def main() -> None:
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
    evaluator = _thermodse_evaluator(arch, workload, sim, physical_nop=True)
    evaluator.generate_hardware()
    # Capture the exact class installed into the evaluator, not the pinned legacy base.
    from core.chiplet_eva import Nop  # type: ignore

    with capture_route_events(Nop) as events:
        with monitor_snapshot(evaluator) as snapshot:
            endpoint_latency_ms, endpoint_energy_mj, _ = evaluator.evaluate()
    if len(snapshot["core_dict"]) != 1:
        raise RuntimeError("complete trace probe requires exactly one captured network")
    network = next(iter(snapshot["core_dict"]))
    old_floorplan_path = sim / "floorplan" / "output_3D.flp"
    old_floorplan_text = old_floorplan_path.read_text(encoding="utf-8")
    old_blocks = tuple(floorplan_units(old_floorplan_path))
    clock_hz = float(evaluator.monitor.clk_freq)

    core = lower_monitor_trace(
        block_ids=old_blocks,
        latency_cycles=snapshot["latency_dict"][network],
        core_energy_pj=snapshot["core_dict"][network],
        noc_energy_pj=snapshot["noc_dict"][network],
        nop_energy_pj=snapshot["nop_dict"][network],
        dram_energy_pj=snapshot["dram_dict"][network],
        clock_hz=clock_hz,
        component_names=tuple(evaluator.monitor.NAME_LIST),
    )
    shape = (int(arch["chiplet_x"]), int(arch["chiplet_y"]))
    cuts = (int(arch["cut_x"]), int(arch["cut_y"]))
    dram_locations = tuple((int(x), int(y)) for x, y in evaluator.dram_list)
    augmented = augment_floorplan_with_dram(
        old_floorplan_text,
        io_die_area_each_m2=float(evaluator.IO_die_area_each),
        dram_locations=dram_locations,
        compute_shape=shape,
    )
    batch_factor = int(workload["b_tot"]) // int(workload["b_exe"])
    routed = lower_routed_trace(
        core,
        floorplan=augmented,
        events=events,
        compute_shape=shape,
        chiplet_cuts=cuts,
        noc_hop_cost_pj=float(evaluator.noc_cost),
        nop_hop_cost_pj=float(evaluator.nop_cost),
        batch_factor=batch_factor,
    )

    floorplan_out = OUTPUT / f"complete_floorplan_{WORKLOAD}_{ARCH_ID}.flp"
    trace_out = OUTPUT / f"complete_trace_{WORKLOAD}_{ARCH_ID}.npz"
    floorplan_out.write_text(augmented.text, encoding="utf-8")
    np.savez_compressed(
        trace_out,
        block_ids=np.asarray(augmented.block_ids),
        durations_s=routed.trace.durations_s,
        powers_w=routed.trace.powers_w,
        source_energy_j=np.asarray(routed.source_energy_j),
        route_energy_j=np.asarray(routed.route_energy_j),
        monitor_source_energy_j=np.asarray(routed.monitor_source_energy_j),
        monitor_route_energy_j=np.asarray(routed.monitor_route_energy_j),
        physical_channel_hops=np.asarray(routed.physical_channel_hops),
        monitor_channel_hops=np.asarray(routed.monitor_channel_hops),
        io_die_area_each_m2=np.asarray(augmented.io_die_area_each_m2),
        io_die_aspect_ratio=np.asarray(augmented.io_die_aspect_ratio),
    )

    integrated_j = float(routed.trace.energy_j().sum())
    physical_latency_ms = routed.trace.total_time_s * 1e3
    print(
        f"{ARCH_ID} / {WORKLOAD}: {routed.trace.n_phases} phases x "
        f"{routed.trace.dimension} augmented blocks"
    )
    print(
        f"  physical latency={physical_latency_ms:.6f} ms; legacy endpoint="
        f"{endpoint_latency_ms:.6f} ms; ratio={endpoint_latency_ms/physical_latency_ms:.6f}"
    )
    print(
        f"  corrected thermal source={routed.source_energy_j * 1e3:.6f} mJ; "
        f"integrated trace={integrated_j * 1e3:.6f} mJ; "
        f"corrected route channels={routed.route_energy_j * 1e3:.6f} mJ"
    )
    print(
        f"  monitor source={routed.monitor_source_energy_j * 1e3:.6f} mJ; "
        f"monitor route channels={routed.monitor_route_energy_j * 1e3:.6f} mJ; "
        f"reconciliation delta="
        f"{(routed.source_energy_j-routed.monitor_source_energy_j) * 1e3:.6f} mJ"
    )
    physical_hops = sum(routed.physical_channel_hops)
    monitor_hops = sum(routed.monitor_channel_hops)
    print(
        f"  internal hops physical={physical_hops:.6e} "
        f"(NoC={routed.physical_channel_hops[0]:.6e}, "
        f"NoP={routed.physical_channel_hops[1]:.6e}); "
        f"monitor={monitor_hops:.6e} "
        f"(NoC={routed.monitor_channel_hops[0]:.6e}, "
        f"NoP={routed.monitor_channel_hops[1]:.6e}); "
        f"total ratio={physical_hops/monitor_hops:.9f}"
    )
    print(
        f"  IO geometry: {len(augmented.dram_blocks)} square dies, "
        f"{augmented.io_die_area_each_m2 * 1e6:.3f} mm^2 each"
    )
    print(f"  wrote {floorplan_out}")
    print(f"  wrote {trace_out}")

    report = {
        "arch": ARCH_ID,
        "workload": WORKLOAD,
        "network": network,
        "phases": routed.trace.n_phases,
        "blocks": routed.trace.dimension,
        "physical_latency_ms": physical_latency_ms,
        "legacy_endpoint_latency_ms": float(endpoint_latency_ms),
        "optimization_energy_mj": float(endpoint_energy_mj),
        "thermal_source_energy_mj": routed.source_energy_j * 1e3,
        "integrated_trace_energy_mj": integrated_j * 1e3,
        "route_energy_mj": routed.route_energy_j * 1e3,
        "monitor_source_energy_mj": routed.monitor_source_energy_j * 1e3,
        "monitor_route_energy_mj": routed.monitor_route_energy_j * 1e3,
        "physical_monitor_reconciliation_delta_mj": (
            routed.source_energy_j - routed.monitor_source_energy_j
        )
        * 1e3,
        "noc_hop_cost_pj": float(evaluator.noc_cost),
        "nop_hop_cost_pj": float(evaluator.nop_cost),
        "physical_channel_hops": list(routed.physical_channel_hops),
        "monitor_channel_hops": list(routed.monitor_channel_hops),
        "physical_to_monitor_total_hop_ratio": physical_hops / monitor_hops,
        "batch_factor": batch_factor,
        "events": len(events),
        "io_die_area_each_m2": augmented.io_die_area_each_m2,
        "io_die_aspect_ratio_assumption": augmented.io_die_aspect_ratio,
        "dram_blocks": {
            f"{location[0]},{location[1]}": name
            for location, name in augmented.dram_blocks.items()
        },
        "floorplan": str(floorplan_out),
        "trace": str(trace_out),
        "energy_conserved": bool(
            np.isclose(integrated_j, routed.source_energy_j, rtol=1e-11, atol=1e-18)
        ),
    }
    report_out = OUTPUT / f"complete_trace_{WORKLOAD}_{ARCH_ID}.json"
    report_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  wrote {report_out}")
    print(
        "  COMPLETE TRACE ONLY. Every source joule has a named floorplan location; "
        "HotSpot acceptance, transient discretization, initial state, and decisions "
        "remain untested."
    )


if __name__ == "__main__":
    main()
