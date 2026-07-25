"""Capture pre-index communication events and reconcile them per order. (NON-CLAIM)

`Nop.link_hops` cannot be decoded spatially because its allocation uses an `(x + 2)`
stride while `get_link_idx` uses `x`, aliasing external columns with the following row.
The higher-level calls still retain source/destination coordinates and volume:

    move_between_core(src, destinations, volume)
    read_from_DRAM(destinations, volume)
    write_to_DRAM(src, volume)

This read-only adapter wraps those calls, records their arguments, and measures the exact
counter delta produced by the original implementation.  It then reconciles the event energy
against `monitor.noc_dict/nop_dict/dram_dict` for every schedule order.  Passing establishes
that a route-aware lowering can start from unaliased events; it does not yet assign those
events to floorplan blocks.

Usage:
    python research/triangle/route_event_probe.py <out> <workload> <arch_id>
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
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


OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/v6routes")
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
ARCH_ID = sys.argv[3] if len(sys.argv) > 3 else "arch_c"


def _coord(value):
    return [int(value[0]), int(value[1])]


def _coord_list(values):
    return [_coord(value) for value in values]


@contextmanager
def capture_route_events(nop_class):
    """Patch one imported Nop class for the narrow duration of an evaluation."""

    originals = {
        name: getattr(nop_class, name)
        for name in ("clear", "move_between_core", "read_from_DRAM", "write_to_DRAM")
    }
    state = {}
    events = []

    def clear(self):
        result = originals["clear"](self)
        item = state.setdefault(id(self), {"epoch": -1})
        item["epoch"] += 1
        return result

    def wrap(name, kind):
        original = originals[name]

        def captured(self, *args, **kwargs):
            item = state.get(id(self))
            if item is None or item["epoch"] < 0:
                raise RuntimeError(f"{name} occurred before the first Nop.clear boundary")
            before = (
                float(self.tot_noc_hops),
                float(self.tot_nop_hops),
                float(self.tot_DRAM_access),
            )
            result = original(self, *args, **kwargs)
            after = (
                float(self.tot_noc_hops),
                float(self.tot_nop_hops),
                float(self.tot_DRAM_access),
            )
            delta_noc_hops = after[0] - before[0]
            delta_dram_access = after[2] - before[2]
            # ThermoDSE's NoP endpoint explicitly subtracts DRAM access from the
            # accumulated NoP hops before multiplying by nop_hop_cost.
            delta_nop_hops = after[1] - before[1] - delta_dram_access
            if min(delta_noc_hops, delta_nop_hops, delta_dram_access) < -1e-9:
                raise RuntimeError("a route event decreased an energy counter")
            epoch = int(item["epoch"])
            event = {
                "order": epoch // 2,
                "stage": "input" if epoch % 2 == 0 else "output",
                "kind": kind,
                "volume": float(args[-1]),
                "noc_energy_pj": delta_noc_hops * float(self.noc_hop_cost),
                "nop_energy_pj": delta_nop_hops * float(self.nop_hop_cost),
                "dram_energy_pj": delta_dram_access * float(self.DRAM_acc_cost),
                "dram_locations": _coord_list(self.dram_list),
            }
            if kind == "core_to_core":
                event["source"] = _coord(args[0])
                event["destinations"] = _coord_list(args[1])
            elif kind == "dram_read":
                event["destinations"] = _coord_list(args[0])
            else:
                event["source"] = _coord(args[0])
            events.append(event)
            return result

        return captured

    nop_class.clear = clear
    nop_class.move_between_core = wrap("move_between_core", "core_to_core")
    nop_class.read_from_DRAM = wrap("read_from_DRAM", "dram_read")
    nop_class.write_to_DRAM = wrap("write_to_DRAM", "dram_write")
    try:
        yield events
    finally:
        for name, original in originals.items():
            setattr(nop_class, name, original)


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
    evaluator = _thermodse_evaluator(arch, workload, sim)
    evaluator.generate_hardware()

    from core.nop import Nop  # type: ignore

    with capture_route_events(Nop) as events:
        with monitor_snapshot(evaluator) as snapshot:
            evaluator.evaluate()

    if len(snapshot["noc_dict"]) != 1:
        raise RuntimeError("route probe requires exactly one captured network")
    network = next(iter(snapshot["noc_dict"]))
    expected = np.column_stack(
        (
            snapshot["noc_dict"][network],
            snapshot["nop_dict"][network],
            snapshot["dram_dict"][network],
        )
    )
    batch_factor = int(workload["b_tot"]) // int(workload["b_exe"])
    actual = np.zeros_like(expected)
    for event in events:
        order = int(event["order"])
        if order >= actual.shape[0]:
            raise RuntimeError("captured event order exceeds the monitor trace")
        actual[order, 0] += event["noc_energy_pj"] * batch_factor
        actual[order, 1] += event["nop_energy_pj"] * batch_factor
        actual[order, 2] += event["dram_energy_pj"] * batch_factor

    error = np.abs(actual - expected)
    channel_names = ("noc", "nop", "dram")
    print(
        f"{ARCH_ID} / {WORKLOAD}: {len(events)} events over {expected.shape[0]} orders"
    )
    summary = {}
    for column, channel in enumerate(channel_names):
        scale = max(float(np.abs(expected[:, column]).max()), 1.0)
        max_abs = float(error[:, column].max())
        max_rel = max_abs / scale
        summary[channel] = {
            "source_energy_pj": float(expected[:, column].sum()),
            "event_energy_pj": float(actual[:, column].sum()),
            "max_order_abs_error_pj": max_abs,
            "max_order_relative_error": max_rel,
        }
        print(
            f"  {channel:4s}: source={summary[channel]['source_energy_pj']:.6e} pJ  "
            f"events={summary[channel]['event_energy_pj']:.6e} pJ  "
            f"max/order error={max_abs:.3e} pJ ({max_rel:.3e} relative)"
        )

    tolerance = 1e-10
    reconciled = bool(
        all(item["max_order_relative_error"] <= tolerance for item in summary.values())
    )
    print(f"  per-order reconciliation: {'PASS' if reconciled else 'FAIL'}")
    report = {
        "arch": ARCH_ID,
        "workload": WORKLOAD,
        "network": network,
        "batch_factor": batch_factor,
        "orders": int(expected.shape[0]),
        "events": events,
        "channels": summary,
        "per_order_reconciled": reconciled,
        "relative_tolerance": tolerance,
    }
    output = OUTPUT / f"route_events_{WORKLOAD}_{ARCH_ID}.json"
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  wrote {output}")
    if not reconciled:
        raise SystemExit(3)
    print(
        "  EVENT CAPTURE ONLY. Coordinates and energy survive before the aliased "
        "link_hops index; no floorplan placement or thermal claim is made."
    )


if __name__ == "__main__":
    main()
