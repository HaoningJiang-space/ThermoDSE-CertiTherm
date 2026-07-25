"""Core-only transient replay: does real schedule SHAPE move the peak? (NON-CLAIM)

The smallest defensible flip experiment. Everything about it is deliberately narrow.

WHY CORE-ONLY. The energy ledger (docs/THERMODSE_ENDPOINT_AUDIT.md) measured that of the
four power sources only `core_dict` is both 100% energy-conserving into the ptrace and
genuinely spatially resolved (80 columns). The others are not usable for a spatial claim:
NoC is over-counted 133.41% AND spread uniformly, which erases the spatial information this
experiment exists to measure; NoP lands in one lumped `interposer` column; DRAM never enters
at all. So core-only is the only component whose spatial trace can carry a conclusion.

BOUNDARY, stated up front and repeated in the output. This is a COMPUTE-DOMAIN experiment
with no explicit DRAM power source or thermal node, no NoC and no NoP. Roughly half the
dissipated energy is absent. A flip here supports "under this boundary the cheap abstraction
does not preserve the decision" and NOTHING about a physical package.

THE COMPARISON. Two traces with IDENTICAL per-column energy and identical total duration:

    scheduled  the real per-order vectors at their real durations
    flat       the time-weighted mean vector, held constant

A steady-state model driven by mean power sees exactly one world; only a transient model can
tell them apart. Both use the same floorplan, config, materials and initial condition.

RESAMPLING, and why energy stays exact. HotSpot transient needs a fixed sampling interval,
but the real per-order durations span ~163x. Each order k is assigned
`n_k = max(1, round(dur_k / dt))` steps and its power is then RESCALED by
`dur_k / (n_k * dt)`, so per-column energy is preserved EXACTLY by construction and the error
appears as a bounded timing distortion instead, which is measured and reported. Getting this
backwards -- preserving timing and letting energy drift -- would break the one property the
flat comparison depends on.

Latency is the CYCLE-DERIVED value; the returned endpoint is 1.8x too large.

NON-CLAIM diagnostic. Usage:
    python research/triangle/core_transient_flip.py <out> <workload> <arch_id> [passes]
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.experiments import (
    HOTSPOT, ROOT, TEMPLATE, THERMAL_LIMIT_K, _prepare_thermodse_sim, _registry_split,
    _rows, _thermodse_evaluator,
)

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("_otp", "research/triangle/order_trace_probe.py")
_otp = _ilu.module_from_spec(_spec)
_saved = sys.argv
sys.argv = ["order_trace_probe"]
try:
    _spec.loader.exec_module(_otp)
finally:
    sys.argv = _saved
DICTS, monitor_snapshot = _otp.DICTS, _otp.monitor_snapshot

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/v6flip")
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
ARCH_ID = sys.argv[3] if len(sys.argv) > 3 else "arch_c"
PASSES = int(sys.argv[4]) if len(sys.argv) > 4 else 1
ENERGY_DICTS = ("core_dict", "noc_dict", "nop_dict", "dram_dict")


def read_ptrace(path: Path):
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) != 2:
        raise RuntimeError(f"{path}: expected header + one row")
    names = lines[0].split()
    vals = np.asarray([float(v) for v in lines[1].split()], dtype=float)
    if len(names) != vals.size:
        raise RuntimeError(f"{path}: {len(names)} names vs {vals.size} values")
    return names, vals


def generate(mon, dicts, gen_path: Path):
    saved = {n: getattr(mon, n) for n in ENERGY_DICTS}
    try:
        for n, v in dicts.items():
            setattr(mon, n, v)
        gen_path.mkdir(parents=True, exist_ok=True)
        mon.gen_all_ptrace_3D(gen_path=str(gen_path))
    finally:
        for n, v in saved.items():
            setattr(mon, n, v)
    return read_ptrace(gen_path / "cores_3D.ptrace")


def hotspot_transient(config, floorplan, materials, cols, rows_w, dt, ws, tag):
    ptrace, out = ws / f"{tag}.ptrace", ws / f"{tag}.out"
    with ptrace.open("w") as fh:
        fh.write("\t".join(cols) + "\n")
        for row in rows_w:
            fh.write("\t".join(f"{v:.6f}" for v in row) + "\n")
    cmd = [str(HOTSPOT), "-c", str(config), "-f", str(floorplan), "-p", str(ptrace),
           "-materials_file", str(materials), "-model_type", "block",
           "-sampling_intvl", repr(dt), "-o", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"HotSpot failed: {r.stderr[-400:]}")
    data = np.loadtxt(out, skiprows=1)
    return data if data.ndim == 2 else data.reshape(1, -1)


def main():
    reg = _registry_split("dev_v3")
    arch = next((a for a in _rows(ROOT / "experiments" / "architectures.tsv")
                 if a["split"] == reg and a["architecture_id"] == ARCH_ID), None)
    if arch is None:
        print(f"FAIL: {ARCH_ID} not in {reg}"); sys.exit(2)
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
        ev.evaluate()
    if not snap.get("core_dict"):
        print("FAIL: snapshot empty"); sys.exit(2)
    for n in DICTS:
        if n in snap:
            setattr(mon, n, {k: v.copy() for k, v in snap[n].items()})

    clk = float(mon.clk_freq)
    nets = sorted(snap["core_dict"].keys())
    if len(nets) != 1:
        print(f"FAIL: {len(nets)} networks; this experiment assumes one"); sys.exit(2)
    nn = nets[0]
    dur = snap["latency_dict"][nn] / clk
    t_total = float(dur.sum())
    n_ord = dur.size

    work = Path(tempfile.mkdtemp(prefix="flip-", dir=str(OUTPUT)))
    try:
        # ---- CORE-ONLY per-order vectors, via ThermoDSE's own generator ----------
        zeros = {n: {k: np.zeros_like(v) for k, v in getattr(mon, n).items()}
                 for n in ENERGY_DICTS}
        base = dict(zeros); base["core_dict"] = {k: v.copy()
                                                for k, v in snap["core_dict"].items()}
        cols, ref = generate(mon, base, work / "core-full")
        keep = np.flatnonzero(np.abs(ref) > 0)
        if keep.size == 0:
            print("FAIL: core-only ptrace is all zero"); sys.exit(2)
        print(f"{ARCH_ID}/{WORKLOAD}: {n_ord} orders, core-only occupies "
              f"{keep.size} of {len(cols)} columns, total {ref.sum():.4f} W")

        rows = np.zeros((n_ord, len(cols)))
        for k in range(n_ord):
            iso = dict(zeros)
            iso["core_dict"] = {}
            for key, v in snap["core_dict"].items():
                z = np.zeros_like(v)
                if key == nn and v.shape[0] > k:
                    z[k] = v[k]
                iso["core_dict"][key] = z
            _, vk = generate(mon, iso, work / "ord")
            rows[k] = vk
        sup_err = float(np.abs(rows.sum(axis=0) - ref).max())
        print(f"  per-order superposition error {sup_err:.3e} W "
              f"-> {'OK' if sup_err < 5e-3 else 'FAILED'}")
        if sup_err >= 5e-3:
            sys.exit(3)

        # rows[k] = E_k/T_total ; actual power = rows[k] * T_total/dur_k
        nz = dur > 0
        p_ord = np.zeros_like(rows)
        p_ord[nz] = rows[nz] * (t_total / dur[nz, None])

        # ---- resample onto a fixed dt, preserving per-column energy EXACTLY -----
        dt = float(dur[nz].min())
        steps = np.maximum(1, np.rint(dur / dt)).astype(int)
        scale = np.where(steps > 0, dur / (steps * dt), 0.0)
        timing_err = float(np.abs(steps * dt - dur).max() / dur.max())
        sched_rows = []
        for k in range(n_ord):
            sched_rows.extend([p_ord[k] * scale[k]] * int(steps[k]))
        sched = np.asarray(sched_rows)
        n_steps = sched.shape[0]
        e_sched = sched.sum(axis=0) * dt
        e_true = p_ord * dur[:, None]
        e_err = float(np.abs(e_sched - e_true.sum(axis=0)).max())
        print(f"  resampled to {n_steps} steps of {dt * 1e6:.3f} us; "
              f"per-column energy error {e_err:.3e} J "
              f"(max timing distortion {timing_err * 100:.3f}% of the longest order)")
        if e_err > 1e-9:
            print("FAIL: resampling did not preserve per-column energy"); sys.exit(3)

        # ---- FLAT: same per-column energy, same duration, constant --------------
        flat_vec = e_sched / (n_steps * dt)
        flat = np.tile(flat_vec, (n_steps, 1))
        if not np.allclose(sched.sum(axis=0) * dt, flat.sum(axis=0) * dt, atol=1e-12):
            print("FAIL: the two traces differ in per-column energy"); sys.exit(3)
        print(f"  flat vector total {flat_vec.sum():.4f} W == scheduled mean "
              f"{(sched.mean(axis=0)).sum():.4f} W")

        # ---- replay both, identical everything else ----------------------------
        floorplan = Path(sim) / "floorplan" / "output_3D.flp"
        config = Path(sim) / "example.config"
        materials = TEMPLATE / "example.materials"
        res = {}
        for name, tr in (("scheduled", sched), ("flat", flat)):
            body = np.tile(tr, (PASSES, 1))
            temps = hotspot_transient(config, floorplan, materials, cols, body, dt,
                                      work, name)
            if temps.shape[1] != len(cols):
                print(f"FAIL: {temps.shape[1]} output columns for {len(cols)} units")
                sys.exit(2)
            per = n_steps
            last = temps[-per:]
            drift = (float(np.abs(last - temps[-2 * per:-per]).max())
                     if temps.shape[0] >= 2 * per else float("nan"))
            hot = int(last.max(axis=0).argmax())
            res[name] = {"peak_k": float(last.max()), "peak_unit": cols[hot],
                         "hot_unit_ripple_k": float(last[:, hot].max() - last[:, hot].min()),
                         "final_mean_k": float(last.mean()),
                         "pass_drift_k": drift, "steps": int(temps.shape[0])}
            r = res[name]
            print(f"  {name:9s} peak={r['peak_k']:.4f} K at {r['peak_unit']:12s} "
                  f"hot-unit ripple={r['hot_unit_ripple_k']:.4f} K  "
                  f"pass-to-pass drift={drift:.5f} K")

        gap = res["scheduled"]["peak_k"] - res["flat"]["peak_k"]
        print(f"\n  SHAPE EFFECT (scheduled - flat) = {gap:+.4f} K")
        for name in ("scheduled", "flat"):
            print(f"    {name:9s} peak {res[name]['peak_k']:.4f} K vs limit "
                  f"{THERMAL_LIMIT_K} -> margin {THERMAL_LIMIT_K - res[name]['peak_k']:+.4f} K")
        both_below = all(res[n]["peak_k"] < THERMAL_LIMIT_K for n in res)
        both_above = all(res[n]["peak_k"] > THERMAL_LIMIT_K for n in res)
        print(f"  FEASIBILITY: {'both SAFE' if both_below else 'both REJECT' if both_above else 'THEY DISAGREE'}"
              f" at {THERMAL_LIMIT_K} K")
        if not (both_below or both_above):
            print("    A point-estimate disagreement is NOT a certified flip. It needs "
                  "non-overlapping intervals under a transient error contract that does "
                  "not exist yet (the 0.01 K band is a STEADY-STATE linearisation bound).")

        print(f"\n  BOUNDARY: compute-domain core-only. No DRAM (40.56% of dissipated "
              f"energy), no NoP (10.90%), no NoC. Any conclusion carries this boundary.")
        (OUTPUT / f"core_flip_{WORKLOAD}_{ARCH_ID}.json").write_text(json.dumps({
            "arch": ARCH_ID, "workload": WORKLOAD, "orders": n_ord, "passes": PASSES,
            "dt_s": dt, "steps_per_pass": n_steps, "physical_latency_ms": t_total * 1e3,
            "core_only_columns": int(keep.size), "superposition_err_w": sup_err,
            "resample_energy_err_j": e_err, "timing_distortion_frac": timing_err,
            "results": res, "shape_effect_k": gap, "thermal_limit_k": THERMAL_LIMIT_K,
            "boundary": "compute-domain core-only; DRAM/NoP/NoC excluded",
        }, indent=2))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
