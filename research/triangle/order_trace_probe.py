"""Probe: are ThermoDSE's per-order latency and energy obtainable and conserved? (NON-CLAIM)

Before building a `schedule_trace_capture`, establish that the data it would need actually
exists, survives the evaluation, and reconciles with the endpoints CertiTherm already
depends on. Building the capture first and discovering the data is insufficient is the
expensive order.

WHERE THE TIME INFORMATION IS THROWN AWAY. `CertiTherm/experiments.py::_capture` keeps one
whole-run averaged power vector -- it explicitly requires "exactly one aligned power sample".
Inside ThermoDSE, `statistic.py:221` collapses the temporal axis the same way:

    avg_p = np.sum(self.core_dict[nn][:, idx, m]) * 1e-12 / latency    # sum over ALL orders

WHAT SURVIVES, AND WHAT DOES NOT. `chiplet_evaluator.monitor` is an instance attribute, so
the OBJECT outlives `evaluate()` -- unlike the `Evaluator`, which is a local and gets
`.clear()`ed. But its CONTENTS do not: `chiplet_eva.py:239` calls `self.monitor.clear()` on
the line before `return`. The first version of this probe fail-closed on exactly that, which
is the intended behaviour.

The data is still complete at `chiplet_eva.py:231`, where `gen_all_ptrace_3D` writes the
averaged ptrace. So the adapter intercepts `monitor.clear` and snapshots first. That is a
READ-ONLY adapter -- the pinned submodule is untouched -- and it follows a pattern already
used in `experiments.py::_hotspot_disabled`, which monkeypatches `run_hotspot` the same way.

On the monitor:

    monitor.latency_dict[nn][order]           per-order latency, in CYCLES
    monitor.core_dict[nn][order, core, 7]     per-order per-core component energy, pJ
    monitor.noc_dict / nop_dict / dram_dict   per-order interconnect and memory energy, pJ
    monitor.core_utl_dict[nn][order, core]    per-order core utilisation

So no change to the pinned ThermoDSE submodule is needed: this reads the monitor after the
existing CertiTherm invocation path runs.

CONSERVATION, and TWO ENERGIES THAT MUST NOT BE CONFLATED. `get_nn_cost` returns

    e_tot = e_nop + e_noc + e_dram + e_core - e_comp

excluding compute energy on the stated grounds that it is fixed across ThermoDSE's design
space. Read as a single "total energy" that is a defect, and the workspace contract records
it at `core/statistic.py:200` as one. But for this work the accurate framing is that there
are two DIFFERENT quantities, and the right reconciliation is an identity rather than an
equality:

    optimization_energy_mj          what ThermoDSE ranks EDYP by (compute excluded)
    thermal_dissipated_energy_mj    what heats the die (compute INCLUDED)

    thermal_dissipated = optimization + excluded_compute

A thermal trace must be built from the second. This probe reports both and the gap between
them, and never treats a mismatch as an error to be reconciled away.

WHAT THIS PROBE CAN AND CANNOT DECIDE. It reports the SCALAR total power per order. That is
enough to show availability and conservation, and enough to show that variation EXISTS. It is
NOT enough to decide the transient direction, and an earlier version of this docstring
wrongly claimed it was.

The reason is first-principles: temperature responds to a SPATIAL power vector,

    T(t) = T_amb + integral G(t - tau) p(tau) dtau     with p(tau) a vector over blocks

so a flat scalar total is fully compatible with a hotspot MIGRATING between chiplets from
order to order, which changes peak temperature through diffusion, adjacency and history. The
inference "scalar total is flat, therefore no phase structure to exploit" is invalid in both
directions and is withdrawn. Only a floorplan-aligned per-order power VECTOR can decide it;
that is the successor probe.

NON-CLAIM diagnostic. Usage:
    python research/triangle/order_trace_probe.py <out> <workload> <arch_id>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from contextlib import contextmanager

from CertiTherm.experiments import (
    ROOT, _prepare_thermodse_sim, _registry_split, _rows, _thermodse_evaluator,
)
from CertiTherm.thermodse_trace import lower_monitor_trace
from CertiTherm.trace_runner import floorplan_units

DICTS = ("core_dict", "latency_dict", "noc_dict", "nop_dict", "dram_dict", "core_utl_dict")


@contextmanager
def monitor_snapshot(evaluator):
    """Capture the monitor's per-order data before ThermoDSE clears it.

    `chiplet_eva.py` calls `monitor.clear()` immediately before returning, so reading
    the dicts after `evaluate()` yields nothing. This wraps `clear` to deep-copy first.
    Read-only with respect to the pinned submodule: nothing on disk is modified and the
    original method is restored on exit.
    """
    mon = evaluator.monitor
    original = mon.clear
    box = {}

    def clear_after_snapshot(*args, **kwargs):
        if not box:                                  # keep the FIRST (complete) state
            for name in DICTS:
                d = getattr(mon, name, None)
                if isinstance(d, dict):
                    box[name] = {k: np.array(v, dtype=float, copy=True)
                                 for k, v in d.items()}
        return original(*args, **kwargs)

    mon.clear = clear_after_snapshot
    try:
        yield box
    finally:
        mon.clear = original

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/v6probe")
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
ARCH_ID = sys.argv[3] if len(sys.argv) > 3 else "arch_c"


def main():
    reg = _registry_split("dev_v3")
    arches = [r for r in _rows(ROOT / "experiments" / "architectures.tsv")
              if r["split"] == reg]
    arch = next((a for a in arches if a["architecture_id"] == ARCH_ID), None)
    if arch is None:
        print(f"FAIL: {ARCH_ID} not in split {reg}; have "
              f"{[a['architecture_id'] for a in arches]}"); sys.exit(2)
    wl = next(w for w in _rows(ROOT / "experiments" / "workloads.tsv")
              if w["split"] == reg and w["workload_id"] == WORKLOAD)
    pkg = next(p for p in _rows(ROOT / "experiments" / "packages.tsv")
               if p["package_id"] == "default")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    sim = _prepare_thermodse_sim(arch, wl, pkg, OUTPUT, allow_hotspot=True)
    ev = _thermodse_evaluator(arch, wl, sim)
    ev.generate_hardware()
    mon = getattr(ev, "monitor", None)
    if mon is None:
        print("FAIL: evaluator has no `monitor`; the internals are not reachable this way")
        sys.exit(2)
    with monitor_snapshot(ev) as snap:
        latency, energy, die_yield = ev.evaluate()
    print(f"{ARCH_ID} / {WORKLOAD}: endpoints latency={latency:.6f} ms "
          f"energy={energy:.6f} mJ yield={die_yield:.4f}")

    if "core_dict" not in snap or not snap["core_dict"]:
        print("FAIL: the snapshot captured no core_dict; monitor.clear was never reached "
              "or the attribute names have changed")
        sys.exit(2)
    names = sorted(snap["core_dict"].keys())
    clk = float(getattr(mon, "clk_freq"))
    print(f"  networks recorded: {names}   clk_freq={clk:.3e} Hz")

    report = {"arch": ARCH_ID, "workload": WORKLOAD, "clk_freq_hz": clk,
              "endpoint_latency_ms": float(latency), "endpoint_energy_mj": float(energy),
              "networks": {}}
    floorplan = sim / "floorplan" / "output_3D.flp"
    blocks = tuple(floorplan_units(floorplan))

    lat_cycles_all = 0.0
    e_true_pj_all = 0.0
    for nn in names:
        core = snap["core_dict"][nn]                               # (orders, cores, 7)
        lat = snap["latency_dict"][nn]                             # (orders,) cycles
        noc = snap["noc_dict"][nn]
        nop = snap["nop_dict"][nn]
        dram = snap["dram_dict"][nn]
        n_ord, n_core, n_comp = core.shape
        print(f"\n  [{nn}] orders={n_ord} cores={n_core} components={n_comp}")

        # --- per-order duration -------------------------------------------------
        dur_s = lat / clk
        nz = dur_s > 0
        print(f"    duration_s : total={dur_s.sum():.6e} "
              f"min={dur_s[nz].min() if nz.any() else 0:.3e} "
              f"max={dur_s.max():.3e} zero-length orders={int((~nz).sum())}")

        # --- per-order power: energy / duration, the quantity statistic.py averages away
        e_core_ord = core.sum(axis=(1, 2))                          # pJ per order
        e_ext_ord = noc + nop + dram
        e_ord = e_core_ord + e_ext_ord
        p_ord = np.zeros(n_ord)
        p_ord[nz] = e_ord[nz] * 1e-12 / dur_s[nz]                   # W
        p_mean = e_ord.sum() * 1e-12 / dur_s.sum() if dur_s.sum() > 0 else float("nan")
        act = p_ord[nz]
        print(f"    power_w    : time-weighted mean={p_mean:.4f}  "
              f"per-order min={act.min() if act.size else 0:.4f} "
              f"max={act.max() if act.size else 0:.4f}")
        if act.size and p_mean > 0:
            print(f"    VARIATION  : max/mean={act.max()/p_mean:.3f}x  "
                  f"min/mean={act.min()/p_mean:.3f}x  "
                  f"cv={act.std()/act.mean():.4f}")
            print(f"                 (SCALAR total only. A flat scalar is still compatible "
                  f"with a hotspot migrating between chiplets, so this cannot decide the "
                  f"transient direction either way -- a spatial vector probe can.)")

        # --- conservation --------------------------------------------------------
        e_comp = (core[:, :, mon.NAME_LIST.index("mtxu")].sum()
                  + core[:, :, mon.NAME_LIST.index("vecu")].sum())
        e_true = e_core_ord.sum() + e_ext_ord.sum()
        e_endpointish = e_true - e_comp
        print(f"    energy_pJ  : true total={e_true:.6e}  "
              f"core={e_core_ord.sum():.4e} noc={noc.sum():.4e} "
              f"nop={nop.sum():.4e} dram={dram.sum():.4e}")
        print(f"    KNOWN DEFECT (statistic.py:200): the reported endpoint subtracts "
              f"e_comp={e_comp:.4e} pJ")
        print(f"                 true={e_true:.6e} vs endpoint-style={e_endpointish:.6e} pJ "
              f"-> the endpoint is {e_endpointish/e_true*100:.1f}% of the true total")

        lat_cycles_all += lat.sum()
        e_true_pj_all += e_true
        lowered = lower_monitor_trace(
            block_ids=blocks,
            latency_cycles=lat,
            core_energy_pj=core,
            noc_energy_pj=noc,
            nop_energy_pj=nop,
            dram_energy_pj=dram,
            clock_hz=clk,
            component_names=tuple(mon.NAME_LIST),
        )
        vector_out = OUTPUT / f"spatial_trace_{WORKLOAD}_{ARCH_ID}_{nn}.npz"
        np.savez_compressed(
            vector_out,
            block_ids=np.asarray(lowered.block_ids),
            durations_s=lowered.trace.durations_s,
            powers_w=lowered.trace.powers_w,
            unplaced_channels=np.asarray(("noc", "nop", "dram")),
            unplaced_energy_j=lowered.unplaced_energy_j,
        )
        print(f"    spatial     : represented={lowered.represented_energy_j:.6e} J  "
              f"unplaced={lowered.residual_energy_j:.6e} J  "
              f"represented_fraction={lowered.represented_fraction:.4f}")
        print(f"                 wrote {vector_out}")
        if not lowered.is_complete:
            print("                 INCOMPLETE FOR THERMAL REPLAY: NoC/NoP/DRAM have "
                  "aggregate energy but no defensible floorplan location")
        report["networks"][nn] = {
            "orders": int(n_ord), "cores": int(n_core), "components": int(n_comp),
            "duration_total_s": float(dur_s.sum()),
            "zero_length_orders": int((~nz).sum()),
            "power_mean_w": float(p_mean),
            "power_min_w": float(act.min()) if act.size else None,
            "power_max_w": float(act.max()) if act.size else None,
            "power_cv": float(act.std() / act.mean()) if act.size and act.mean() else None,
            "e_true_pj": float(e_true), "e_comp_pj": float(e_comp),
            "e_core_pj": float(e_core_ord.sum()), "e_noc_pj": float(noc.sum()),
            "e_nop_pj": float(nop.sum()), "e_dram_pj": float(dram.sum()),
            "spatial_trace_npz": str(vector_out),
            "represented_energy_j": lowered.represented_energy_j,
            "unplaced_energy_j": lowered.residual_energy_j,
            "represented_fraction": lowered.represented_fraction,
            "complete_for_thermal_replay": lowered.is_complete,
        }

    # --- reconcile against the endpoints CertiTherm already trusts ---------------
    lat_s = lat_cycles_all / clk
    print(f"\n  RECONCILIATION")
    print(f"    sum(per-order duration) = {lat_s * 1e3:.6f} ms   "
          f"endpoint latency = {latency:.6f} ms   "
          f"ratio = {lat_s * 1e3 / latency if latency else float('nan'):.4f}")
    e_true_mj = e_true_pj_all * 1e-9
    print(f"    sum(per-order TRUE energy) = {e_true_mj:.6f} mJ   "
          f"endpoint energy = {energy:.6f} mJ   "
          f"ratio = {e_true_mj / energy if energy else float('nan'):.4f}")
    print(f"    A latency ratio far from 1.0 means the per-order durations do not tile the "
          f"run (batching, multi-network accumulation, or an unaccounted phase), and a "
          f"trace built from them would not be replayable.")
    report["reconciliation"] = {
        "per_order_latency_ms": float(lat_s * 1e3),
        "latency_ratio": float(lat_s * 1e3 / latency) if latency else None,
        "per_order_true_energy_mj": float(e_true_mj),
        "energy_ratio": float(e_true_mj / energy) if energy else None,
    }

    out = OUTPUT / f"order_trace_probe_{WORKLOAD}_{ARCH_ID}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\n  wrote {out}")
    print("  PROBE ONLY: builds an exact floorplan-aligned CORE trace and accounts for every "
          "source joule, but does not invent locations for aggregate NoC/NoP/DRAM energy. "
          "The trace is therefore incomplete for thermal replay and claims nothing about "
          "decisions.")


if __name__ == "__main__":
    main()
