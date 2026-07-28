"""Build one complete routed ThermoDSE phase trace. (NON-CLAIM)

This is the first probe whose emitted power matrix accounts for core, NoC, NoP, and DRAM
energy and whose columns exactly match its augmented HotSpot floorplan.  It still performs
no thermal replay: passing this probe closes the trace-construction prerequisite, not the
transient or decision gate.

Usage:
    python research/triangle/complete_trace_probe.py <out> <workload> <arch_id> \
        [io_aspect_ratio] [components]

`components` is an optional comma-separated subset of {core,noc,nop,dram} used by the V6.1
causal-isolation gate to attribute a thermal result to a power source. Omitting it emits the
full trace exactly as before. A masked emission carries the component mask in its filename,
so an ablation cannot overwrite the full-trace evidence, and every route reconciliation
receipt is still enforced against the full ledger inside `lower_routed_trace`.
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
from research.triangle.v61_contract import positional_script_argument as _argument


# Parse argv ONLY when run as a script -- see `positional_script_argument` for the two
# failures this prevents. `capture_frozen_inputs()` is imported by the factorial driver, so
# import must have no side effects on argv.
OUTPUT = _argument(1, Path("artifacts/v6complete"), Path, module_name=__name__)
WORKLOAD = _argument(2, "resnet50", module_name=__name__)
ARCH_ID = _argument(3, "arch_c", module_name=__name__)
IO_ASPECT_RATIO = _argument(4, 1.0, float, module_name=__name__)
# Optional comma-separated component mask over {core,noc,nop,dram} for V6.1 causal
# isolation. Absent means the full trace, i.e. the existing behaviour. The mask is
# encoded in the emitted filenames so an ablation cannot overwrite the full-trace
# evidence, and it is recorded in the JSON receipt.
_MASK = _argument(5, "", module_name=__name__)
COMPONENTS = tuple(_MASK.split(",")) if _MASK else None
SUFFIX = "" if COMPONENTS is None else "_" + "-".join(sorted(COMPONENTS))


def capture_frozen_inputs(output: Path, workload_id: str, arch_id: str,
                          io_aspect_ratio: float = 1.0):
    """Run ThermoDSE ONCE and freeze everything the lowering needs.

    Extracted so a factorial can capture once and compose every source subset from the
    SAME frozen objects. The previous factorial invoked this module 15 times, which meant
    15 independent ThermoDSE evaluations each rewriting the shared floorplan and sim
    workspace -- a latent contamination hazard, and a concurrency race when two drivers ran
    against one output directory. Measured artifacts happened to stay consistent (subset
    powers were exactly the sum of singletons), but the reports never recorded the hashes
    read at run time, so a race could not be ruled out and the results are diagnostic only.

    Returns everything by value; the caller may lower any number of component subsets from
    it without re-entering ThermoDSE.
    """
    reg = _registry_split("dev_v3")
    arch = next(
        row
        for row in _rows(ROOT / "experiments" / "architectures.tsv")
        if row["split"] == reg and row["architecture_id"] == arch_id
    )
    workload = next(
        row
        for row in _rows(ROOT / "experiments" / "workloads.tsv")
        if row["split"] == reg and row["workload_id"] == workload_id
    )
    package = next(
        row
        for row in _rows(ROOT / "experiments" / "packages.tsv")
        if row["package_id"] == "default"
    )
    output.mkdir(parents=True, exist_ok=True)
    sim = _prepare_thermodse_sim(arch, workload, package, output, allow_hotspot=True)
    evaluator = _thermodse_evaluator(arch, workload, sim, physical_nop=True)
    evaluator.generate_hardware()
    # Capture the exact class installed into the evaluator, not the pinned legacy base.
    from core.chiplet_eva import Nop  # type: ignore

    with capture_route_events(Nop) as events:
        with monitor_snapshot(evaluator) as snapshot:
            endpoint_latency_ms, endpoint_energy_mj, die_yield = evaluator.evaluate()
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
        io_die_aspect_ratio=io_aspect_ratio,
    )
    batch_factor = int(workload["b_tot"]) // int(workload["b_exe"])
    return {
        "sim": sim, "core": core, "augmented": augmented, "events": events,
        "shape": shape, "cuts": cuts, "batch_factor": batch_factor,
        "noc_hop_cost_pj": float(evaluator.noc_cost),
        "nop_hop_cost_pj": float(evaluator.nop_cost),
        "endpoint_latency_ms": endpoint_latency_ms,
        "endpoint_energy_mj": endpoint_energy_mj,
        "die_yield": die_yield,
        "clock_hz": clock_hz, "network": network,
        "old_blocks": old_blocks, "arch": arch, "workload": workload,
    }


def main() -> None:
    frozen = capture_frozen_inputs(OUTPUT, WORKLOAD, ARCH_ID, IO_ASPECT_RATIO)
    sim = frozen["sim"]
    core = frozen["core"]
    augmented = frozen["augmented"]
    events = frozen["events"]
    shape, cuts = frozen["shape"], frozen["cuts"]
    batch_factor = frozen["batch_factor"]
    endpoint_latency_ms = frozen["endpoint_latency_ms"]
    endpoint_energy_mj = frozen["endpoint_energy_mj"]
    die_yield = frozen["die_yield"]
    clock_hz, network = frozen["clock_hz"], frozen["network"]
    old_blocks = frozen["old_blocks"]
    arch, workload = frozen["arch"], frozen["workload"]
    routed = lower_routed_trace(
        core,
        floorplan=augmented,
        events=events,
        compute_shape=shape,
        chiplet_cuts=cuts,
        noc_hop_cost_pj=frozen["noc_hop_cost_pj"],
        nop_hop_cost_pj=frozen["nop_hop_cost_pj"],
        batch_factor=batch_factor,
        components=COMPONENTS,
    )

    floorplan_out = OUTPUT / f"complete_floorplan_{WORKLOAD}_{ARCH_ID}.flp"
    trace_out = OUTPUT / f"complete_trace_{WORKLOAD}_{ARCH_ID}{SUFFIX}.npz"
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
        full_source_energy_j=np.asarray(routed.full_source_energy_j),
        retained_components=np.asarray(routed.retained_components),
        component_names=np.asarray(tuple(routed.component_energy_j)),
        component_energy_j=np.asarray(tuple(routed.component_energy_j.values())),
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
        f"  IO geometry: {len(augmented.dram_blocks)} dies, "
        f"{augmented.io_die_area_each_m2 * 1e6:.3f} mm^2 each, "
        f"width/height={augmented.io_die_aspect_ratio:.3f}"
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
        "die_yield": float(die_yield),
        "optimization_edyp": (
            float(endpoint_latency_ms) * float(endpoint_energy_mj) / float(die_yield)
        ),
        "thermal_source_energy_mj": routed.source_energy_j * 1e3,
        "integrated_trace_energy_mj": integrated_j * 1e3,
        "route_energy_mj": routed.route_energy_j * 1e3,
        "monitor_source_energy_mj": routed.monitor_source_energy_j * 1e3,
        "monitor_route_energy_mj": routed.monitor_route_energy_j * 1e3,
        "physical_monitor_reconciliation_delta_mj": (
            routed.source_energy_j - routed.monitor_source_energy_j
        )
        * 1e3,
        "noc_hop_cost_pj": frozen["noc_hop_cost_pj"],
        "nop_hop_cost_pj": frozen["nop_hop_cost_pj"],
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
    report["retained_components"] = list(routed.retained_components)
    report["component_energy_mj"] = {k: v * 1e3
                                     for k, v in routed.component_energy_j.items()}
    report["full_source_energy_mj"] = routed.full_source_energy_j * 1e3
    report_out = OUTPUT / f"complete_trace_{WORKLOAD}_{ARCH_ID}{SUFFIX}.json"
    report_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  wrote {report_out}")
    print(
        "  COMPLETE TRACE ONLY. Every source joule has a named floorplan location; "
        "HotSpot acceptance, transient discretization, initial state, and decisions "
        "remain untested."
    )


if __name__ == "__main__":
    main()
