"""Energy-source ledger and per-order power vectors from the ORIGINAL ptrace path.

Closes two prerequisites of the v6 gate at once, and deliberately does NOT reimplement
ThermoDSE's column construction.

WHY NOT REIMPLEMENT. Replaying `gen_all_ptrace_3D`'s column logic in a second implementation
would let both copies share the same denominator, indexing or omission bug and still agree.
Exact agreement would prove compatibility with current behaviour, not correctness. So the
ORIGINAL function is used as the oracle, exploited through the fact that it is LINEAR in the
energy dictionaries:

    zero every energy dict except order k, call the original generator, read the file back
    -> that file IS order k's contribution, computed by ThermoDSE's own code

`latency_dict` is left INTACT while doing this, so the generator keeps dividing by the same
total latency for every order. Each returned column is therefore
`E_k[col] / T_total`, and multiplying by `T_total / dur_k` recovers order k's actual power.
Summing the raw contributions must reproduce the unmodified ptrace exactly -- that is the
superposition check, and it is what localises any discrepancy to a COLUMN rather than
leaving it as one aggregate ratio.

THE ENERGY LEDGER. A vector that omits a source cannot integrate to a total that includes it,
so "conservation" is meaningless until every source is classified. For each source the ledger
records the amount, which columns receive it, and which of those columns survive name
alignment against the actual HotSpot floorplan. Then TWO separate identities are enforced:

    integral(original ptrace) == sum of isolated emitted contributions
    total source energy       == admitted + omitted - over-injected

This distinction matters because ThermoDSE emits NoP power to an `interposer` column that is
not in `output_3D.flp`; CertiTherm's name alignment drops it before HotSpot.  Conversely, the
NoC denominator can inject more energy than the source contains.  No unexplained residual is
permitted and the two errors are never allowed to cancel each other silently.

Latency uses the CYCLE-DERIVED value, not the returned endpoint: the endpoint is 1.8x too
large because `chiplet_eva.py:223` treats cycles as nanoseconds
(see docs/THERMODSE_ENDPOINT_AUDIT.md).

NON-CLAIM diagnostic. Usage:
    python research/triangle/energy_ledger.py <out> <workload> <arch_id>
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.experiments import (
    ROOT, _prepare_thermodse_sim, _registry_split, _rows, _thermodse_evaluator,
)
from CertiTherm.trace_runner import floorplan_units
# reuse the snapshot adapter without needing research/ to be a package
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("_otp", "research/triangle/order_trace_probe.py")
_otp = _ilu.module_from_spec(_spec)
_saved_argv = sys.argv
sys.argv = ["order_trace_probe"]                 # its module level reads sys.argv
try:
    _spec.loader.exec_module(_otp)
finally:
    sys.argv = _saved_argv
DICTS, monitor_snapshot = _otp.DICTS, _otp.monitor_snapshot

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/v6ledger")
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
ARCH_ID = sys.argv[3] if len(sys.argv) > 3 else "arch_c"
ENERGY_DICTS = ("core_dict", "noc_dict", "nop_dict", "dram_dict")
RESIDUAL_TOL = 1e-6              # relative; anything larger is a reported failure
PTRACE_DECIMALS = 4              # statistic.py serializes every power with f"{x:.4f}"


def read_ptrace(path: Path):
    """-> (column names, values). Fails closed on a shape mismatch."""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) != 2:
        raise RuntimeError(f"{path}: expected header + one row, got {len(lines)} lines")
    names = lines[0].split()
    vals = np.asarray([float(v) for v in lines[1].split()], dtype=float)
    if len(names) != vals.size:
        raise RuntimeError(f"{path}: {len(names)} names vs {vals.size} values")
    return names, vals


def generate(mon, dicts, gen_path: Path):
    """Call the ORIGINAL generator with the given energy dicts installed."""
    saved = {name: getattr(mon, name) for name in ENERGY_DICTS}
    try:
        for name, value in dicts.items():
            setattr(mon, name, value)
        gen_path.mkdir(parents=True, exist_ok=True)
        mon.gen_all_ptrace_3D(gen_path=str(gen_path))
    finally:
        for name, value in saved.items():
            setattr(mon, name, value)
    return read_ptrace(gen_path / "cores_3D.ptrace")


def main():
    reg = _registry_split("dev_v3")
    arches = [r for r in _rows(ROOT / "experiments" / "architectures.tsv")
              if r["split"] == reg]
    arch = next((a for a in arches if a["architecture_id"] == ARCH_ID), None)
    if arch is None:
        print(f"FAIL: {ARCH_ID} not in split {reg}"); sys.exit(2)
    wl = next(w for w in _rows(ROOT / "experiments" / "workloads.tsv")
              if w["split"] == reg and w["workload_id"] == WORKLOAD)
    pkg = next(p for p in _rows(ROOT / "experiments" / "packages.tsv")
               if p["package_id"] == "default")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    sim = _prepare_thermodse_sim(arch, wl, pkg, OUTPUT, allow_hotspot=True)
    ev = _thermodse_evaluator(arch, wl, sim)
    ev.generate_hardware()
    mon = ev.monitor
    with monitor_snapshot(ev) as snap:
        ep_latency_ms, ep_energy_mj, _ = ev.evaluate()
    if "core_dict" not in snap or not snap["core_dict"]:
        print("FAIL: snapshot empty"); sys.exit(2)

    clk = float(mon.clk_freq)
    nets = sorted(snap["core_dict"].keys())
    # restore the snapshot so the ORIGINAL generator can be re-run against it
    for name in DICTS:
        if name in snap:
            setattr(mon, name, {k: v.copy() for k, v in snap[name].items()})

    cycles = float(sum(snap["latency_dict"][n].sum() for n in nets))
    t_total_s = cycles / clk
    print(f"{ARCH_ID} / {WORKLOAD}: nets={nets} cycles={cycles:.0f} clk={clk:.3e}")
    print(f"  physical latency = {t_total_s * 1e3:.6f} ms   "
          f"legacy endpoint = {ep_latency_ms:.6f} ms   ratio={ep_latency_ms/(t_total_s*1e3):.6f}")

    work = Path(tempfile.mkdtemp(prefix="ledger-", dir=str(OUTPUT)))
    try:
        # --- the unmodified reference, produced by ThermoDSE itself ---------------
        base_names, base_vals = generate(mon, {}, work / "full")
        print(f"  ptrace: {len(base_names)} columns, total {base_vals.sum():.4f} W")
        thermal_names = tuple(floorplan_units(sim / "floorplan" / "output_3D.flp"))
        base_index = {name: column for column, name in enumerate(base_names)}
        missing = [name for name in thermal_names if name not in base_index]
        if missing:
            print(f"FAIL: original ptrace misses {len(missing)} floorplan units")
            sys.exit(2)
        thermal_idx = np.asarray([base_index[name] for name in thermal_names], dtype=int)
        thermal_name_set = set(thermal_names)
        dropped_names = tuple(name for name in base_names if name not in thermal_name_set)
        print(f"  HotSpot admission: {len(thermal_names)} floorplan columns; "
              f"{len(dropped_names)} emitted columns are dropped by name alignment")

        # --- energy ledger -------------------------------------------------------
        # Each source is probed by zeroing every OTHER source and regenerating, so the
        # destination columns are established by the original code, not by reading it.
        srcs = {}
        for src in ENERGY_DICTS:
            only = {}
            for name in ENERGY_DICTS:
                d = getattr(mon, name)
                only[name] = ({k: v.copy() for k, v in d.items()} if name == src
                              else {k: np.zeros_like(v) for k, v in d.items()})
            names_i, vals_i = generate(mon, only, work / f"only-{src}")
            if names_i != base_names:
                print(f"FAIL: column names changed when isolating {src}"); sys.exit(2)
            e_pj = float(sum(getattr(mon, src)[n].sum() for n in nets))
            emitted_pj = float(vals_i.sum()) * t_total_s * 1e12
            admitted_pj = float(vals_i[thermal_idx].sum()) * t_total_s * 1e12
            srcs[src] = {
                "energy_pj": e_pj,
                "emitted_ptrace_power_w": float(vals_i.sum()),
                "emitted_ptrace_energy_pj": emitted_pj,
                "hotspot_admitted_power_w": float(vals_i[thermal_idx].sum()),
                "hotspot_admitted_energy_pj": admitted_pj,
                "emitted_fraction": emitted_pj / e_pj if e_pj else 0.0,
                "hotspot_admitted_fraction": admitted_pj / e_pj if e_pj else 0.0,
                "columns_receiving": [base_names[j]
                                      for j in np.flatnonzero(np.abs(vals_i) > 0)][:8],
                "n_columns_receiving": int((np.abs(vals_i) > 0).sum()),
                "dropped_columns_receiving": [
                    base_names[j] for j in np.flatnonzero(np.abs(vals_i) > 0)
                    if base_names[j] not in thermal_name_set
                ][:8],
            }
            s = srcs[src]
            print(f"    {src:11s} E={e_pj:.4e} pJ  -> emitted "
                  f"{s['emitted_fraction'] * 100:6.2f}%  -> HotSpot admits "
                  f"{s['hotspot_admitted_fraction'] * 100:6.2f}%  "
                  f"over {s['n_columns_receiving']} emitted cols")

        # --- identity 1: the isolated sources must superpose to the reference -----
        superposed = np.zeros_like(base_vals)
        for src in ENERGY_DICTS:
            _, v = read_ptrace(work / f"only-{src}" / "cores_3D.ptrace")
            superposed += v
        lin_err = float(np.abs(superposed - base_vals).max())
        print(f"\n  LINEARITY of the original generator: max column error "
              f"{lin_err:.3e} W -> {'OK' if lin_err < 1e-3 else 'FAILED'}")
        if lin_err >= 1e-3:
            print("    The generator is NOT linear in the energy dicts, so per-order "
                  "superposition is invalid and the per-order extraction below cannot be "
                  "trusted. Stopping.")
            sys.exit(3)

        # --- identity 2: source vs actual HotSpot admission -----------------------
        emitted_pj = sum(s["emitted_ptrace_energy_pj"] for s in srcs.values())
        admitted_pj = sum(s["hotspot_admitted_energy_pj"] for s in srcs.values())
        tot_pj = sum(s["energy_pj"] for s in srcs.values())
        omitted_pj = sum(
            max(s["energy_pj"] - s["hotspot_admitted_energy_pj"], 0.0)
            for s in srcs.values()
        )
        overinjected_pj = sum(
            max(s["hotspot_admitted_energy_pj"] - s["energy_pj"], 0.0)
            for s in srcs.values()
        )
        net_missing_pj = tot_pj - admitted_pj
        ptraced_pj = float(base_vals.sum()) * t_total_s * 1e12
        resid = abs(ptraced_pj - emitted_pj) / max(emitted_pj, 1.0)
        print(f"\n  IDENTITY 1  integral(original ptrace) == isolated emitted energy")
        print(f"    {ptraced_pj:.6e} vs {emitted_pj:.6e} pJ   "
              f"relative residual {resid:.3e} "
              f"-> {'OK' if resid < RESIDUAL_TOL else 'FAILED'}")
        print(f"  IDENTITY 2  source energy vs actual HotSpot-admitted columns")
        print(f"    total source={tot_pj:.6e}  HotSpot-admitted={admitted_pj:.6e} pJ")
        print(f"    omitted={omitted_pj:.6e}  over-injected={overinjected_pj:.6e}  "
              f"net missing={net_missing_pj:.6e} pJ "
              f"({net_missing_pj / tot_pj * 100:.2f}% of sources)")
        print(f"    reported optimization endpoint = {ep_energy_mj * 1e9:.6e} pJ "
              f"({ep_energy_mj * 1e9 / tot_pj * 100:.2f}% of sources)")

        # --- per-order vectors, via the ORIGINAL generator ----------------------
        per_order = {}
        for nn in nets:
            n_ord = snap["latency_dict"][nn].size
            dur = snap["latency_dict"][nn] / clk
            rows = np.zeros((n_ord, base_vals.size))
            for k in range(n_ord):
                iso = {}
                for name in ENERGY_DICTS:
                    d = getattr(mon, name)
                    iso[name] = {}
                    for key, v in d.items():
                        z = np.zeros_like(v)
                        if key == nn and v.shape[0] > k:
                            z[k] = v[k]
                        iso[name][key] = z
                _, v_k = generate(mon, iso, work / "order")
                rows[k] = v_k                          # = E_k[col] / T_total
            # rescale each row from the shared divisor to the order's own duration
            scaled = np.zeros_like(rows)
            nzk = dur > 0
            scaled[nzk] = rows[nzk] * (t_total_s / dur[nzk, None])
            sup = rows.sum(axis=0)
            err = float(np.abs(sup - base_vals).max())
            # Each isolated row and the reference are independently rounded to four
            # decimals.  The worst-case difference in their sum is therefore
            # (n_orders + 1) half-ULPs; use the derived bound, not a magic threshold.
            quantization_bound_w = (n_ord + 1) * 0.5 * 10.0 ** (-PTRACE_DECIMALS)
            print(f"\n  [{nn}] per-order superposition over {n_ord} orders: "
                  f"max column error {err:.3e} W, serialization bound "
                  f"{quantization_bound_w:.3e} W -> "
                  f"{'OK' if err <= quantization_bound_w else 'FAILED'}")
            if err > quantization_bound_w:
                print("    per-order contributions do not sum to the reference; refusing "
                      "to emit a trace"); sys.exit(3)
            admitted_scaled = scaled[:, thermal_idx]
            admitted_reference = base_vals[thermal_idx]
            per_order[nn] = {
                "durations_s": dur.tolist(),
                "power_w_shape": list(admitted_scaled.shape),
                "serialization_bound_w": quantization_bound_w,
            }
            np.savez_compressed(
                OUTPUT / f"order_trace_{WORKLOAD}_{ARCH_ID}_{nn}.npz",
                columns=np.asarray(thermal_names), durations_s=dur,
                powers_w=admitted_scaled, reference_ptrace_w=admitted_reference,
                dropped_columns=np.asarray(dropped_names), cycles=np.asarray(cycles),
                clk_freq_hz=np.asarray(clk))
            print(f"    wrote HotSpot-admitted per-order vectors: "
                  f"{admitted_scaled.shape[0]} orders x {admitted_scaled.shape[1]} "
                  f"floorplan columns")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    (OUTPUT / f"energy_ledger_{WORKLOAD}_{ARCH_ID}.json").write_text(json.dumps({
        "arch": ARCH_ID, "workload": WORKLOAD, "clk_freq_hz": clk, "cycles": cycles,
        "physical_latency_ms": t_total_s * 1e3, "legacy_endpoint_latency_ms": ep_latency_ms,
        "optimization_energy_mj": ep_energy_mj, "sources": srcs,
        "emitted_ptrace_pj": emitted_pj, "hotspot_admitted_pj": admitted_pj,
        "omitted_pj": omitted_pj, "overinjected_pj": overinjected_pj,
        "net_missing_pj": net_missing_pj, "total_source_pj": tot_pj,
        "identity1_residual": resid, "generator_linearity_max_err_w": lin_err,
        "per_order": per_order,
    }, indent=2))
    print("\n  LEDGER ONLY. Establishes the energy boundary and extracts per-order vectors "
          "using ThermoDSE's own generator. It replays nothing thermally and claims nothing "
          "about decisions.")


if __name__ == "__main__":
    main()
