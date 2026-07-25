"""V6.1 causal isolation: does CORE schedule shape alone move the peak? (NON-CLAIM)

Rewritten to use `CertiTherm.transient.replay_periodic`. The first version shipped its own
transient runner and resampler, which was duplication of already-verified infrastructure and
carried defects that engine does not have: it defaulted to one pass so the convergence
residual was always NaN, it reported drift without failing closed, it checked energy before
serialisation rather than after, it normalised timing distortion by the LONGEST order so
short-order error was hidden, and it ran only the `block` model although the flip this gate
is meant to explain appeared under grid-max safety semantics.

`replay_periodic` supplies all of that: exact fractional-overlap resampling that validates
per-block energy and raises (`resample_uniform`, rtol 1e-11, and zero timing distortion
because phases are split across bins rather than rounded to whole steps), a common fixed
initial state, automatic convergence by cycle doubling, a mean-steady reference, and a guard
refusing any convergence claim finer than HotSpot's 0.01 K output resolution.

WHAT THIS SCRIPT STILL DOES ITSELF, because it is the genuinely new part: extract CORE-ONLY
per-order power vectors using ThermoDSE's OWN `gen_all_ptrace_3D` by source and order
isolation, then align them to the floorplan and PROVE the alignment discards no heat.

WHY CORE-ONLY. The energy ledger (docs/THERMODSE_ENDPOINT_AUDIT.md) measured that of the
four sources only `core_dict` is both 100% conserving into the ptrace and genuinely spatially
resolved (80 columns). NoC is over-counted 133.41% AND spread uniformly, which erases the
spatial information this gate measures; NoP lands in one lumped `interposer` column; DRAM
never enters. So core is the only component whose spatial trace can carry a conclusion, and
isolating it is the point: it asks whether core schedule shape ALONE suffices.

BOUNDARY, repeated in every line of output. Compute-domain, core-only. No DRAM (40.56% of
dissipated energy), no NoP (10.90%), no NoC. A difference here supports "under this boundary
core schedule shape does / does not move the peak" and nothing about a physical package.

HOW FAR A CORE-ONLY RESULT TRANSFERS, derived rather than assumed. The model is linear and
passive, so temperature superposes -- but `peak()` is a max and does NOT. Writing the
background sources as a per-unit offset `B(u)` and noting that a constant-power trace's
periodic temperature is constant in time:

    Delta = max_{u,t}[S(u) + ripple(u,t)] - max_u[S(u)],     S(u) = T_flat(u) + B(u)

so which unit wins depends on `B`, and a core-only Delta does NOT extrapolate directly.
There is, however, a bound independent of `B`:

    Delta_full <= max_u max_t ripple(u,t)

Hence core-only is CONCLUSIVE IN THE NEGATIVE DIRECTION -- if the largest ripple is under the
numerical floor, core schedule shape cannot move the peak under ANY background -- while in the
positive direction it is only a LOWER bound, because a background can move the ripple onto a
hotter unit. Reporting that bound needs the per-unit temperature matrix, which
`PeriodicTransientResult` does not expose (scalars only), so it is recorded as a gap rather
than claimed.

NON-CLAIM diagnostic. Usage:
    python research/triangle/core_transient_flip.py <out> <workload> <arch_id> [models] [step_us]
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
    HOTSPOT, ROOT, TEMPLATE, THERMAL_LIMIT_K, _prepare_thermodse_sim, _registry_split,
    _rows, _thermodse_evaluator,
)
from CertiTherm.phase_trace import PhaseTrace
from CertiTherm.trace_runner import floorplan_units
from CertiTherm.transient import replay_periodic

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
MODELS = tuple((sys.argv[4] if len(sys.argv) > 4 else "block,grid64-max").split(","))
STEP_US = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5
ENERGY_DICTS = ("core_dict", "noc_dict", "nop_dict", "dram_dict")
AMBIENT_K = 318.15                      # the established fixed initial state


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
    """Call ThermoDSE's OWN generator with the given energy dicts installed."""
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
        print(f"FAIL: {len(nets)} networks; this gate assumes one"); sys.exit(2)
    nn = nets[0]
    dur = snap["latency_dict"][nn] / clk
    if not np.all(dur > 0):
        print(f"FAIL: {int((dur <= 0).sum())} zero-length orders"); sys.exit(2)
    t_total, n_ord = float(dur.sum()), dur.size

    work = Path(tempfile.mkdtemp(prefix="flip-", dir=str(OUTPUT)))
    try:
        # ---- CORE-ONLY per-order vectors, via ThermoDSE's own generator ----------
        zeros = {n: {k: np.zeros_like(v) for k, v in getattr(mon, n).items()}
                 for n in ENERGY_DICTS}
        base = dict(zeros)
        base["core_dict"] = {k: v.copy() for k, v in snap["core_dict"].items()}
        cols, ref = generate(mon, base, work / "core-full")
        print(f"{ARCH_ID}/{WORKLOAD}: {n_ord} orders, physical latency "
              f"{t_total * 1e3:.6f} ms, core-only total {ref.sum():.4f} W")

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
        p_ord = rows * (t_total / dur[:, None])     # rows[k] = E_k/T_total

        # ---- align to the floorplan and PROVE no heat is discarded --------------
        floorplan = Path(sim) / "floorplan" / "output_3D.flp"
        units = floorplan_units(floorplan)
        idx = {n: j for j, n in enumerate(cols)}
        absent = [n for n in units if n not in idx]
        if absent:
            print(f"FAIL: {len(absent)} floorplan units absent from the header"); sys.exit(2)
        unplaced = [j for j, n in enumerate(cols) if n not in set(units)]
        leak = float(np.abs(p_ord[:, unplaced]).max()) if unplaced else 0.0
        if leak > 0.0:
            print(f"FAIL: {leak:.6f} W sits in columns with no floorplan unit; the trace "
                  f"is not core-only and the comparison is void"); sys.exit(3)
        take = [idx[n] for n in units]
        p_aligned = p_ord[:, take]
        print(f"  aligned onto {len(units)} floorplan units, discarding "
              f"{len(unplaced)} provably-zero columns")

        # ---- the two traces: identical per-block energy, identical duration -----
        scheduled = PhaseTrace(dur, p_aligned)
        flat = PhaseTrace(np.array([t_total]), scheduled.mean_power_w[None, :])
        e_err = float(np.abs(scheduled.energy_j() - flat.energy_j()).max())
        if e_err > 1e-15:
            print(f"FAIL: per-block energy differs by {e_err:.3e} J"); sys.exit(3)
        print(f"  scheduled vs flat: per-block energy identical (max diff {e_err:.2e} J), "
              f"mean total {scheduled.mean_power_w.sum():.4f} W")

        report = {"arch": ARCH_ID, "workload": WORKLOAD, "orders": n_ord,
                  "physical_latency_ms": t_total * 1e3, "max_step_us": STEP_US,
                  "superposition_err_w": sup_err, "floorplan_units": len(units),
                  "boundary": "compute-domain core-only; DRAM/NoP/NoC excluded",
                  "models": {}}
        for model_id in MODELS:
            res = {}
            for name, tr in (("scheduled", scheduled), ("flat", flat)):
                r = replay_periodic(
                    binary=HOTSPOT, config=Path(sim) / "example.config",
                    floorplan=floorplan, materials=Path(sim) / "example.materials",
                    model_id=model_id, block_ids=units, trace=tr,
                    workspace=work / f"{model_id}-{name}",
                    max_step_s=STEP_US * 1e-6, fixed_initial_k=AMBIENT_K,
                    tolerance_k=0.01)
                res[name] = r
                print(f"  [{model_id}] {name:9s} periodic peak={r.periodic_peak_k:.4f} K "
                      f"at {r.periodic_hottest_block:12s} cycles={r.cycles} "
                      f"boundary_resid={r.boundary_residual_k:.4f} "
                      f"peak_resid={r.peak_residual_k:.4f} K")
                print(f"                       fixed-initial peak="
                      f"{r.fixed_initial_peak_k:.4f} K   mean-steady peak="
                      f"{r.mean_steady_peak_k:.4f} K at {r.mean_steady_hottest_block}")

            s, f = res["scheduled"], res["flat"]

            # FREE CROSS-CHECK on the engine and on this usage. The flat trace holds
            # constant power, so its periodic orbit IS its steady state: the two peaks
            # must agree to the output resolution. A mismatch means the periodic solve,
            # the resampling, or the block-id ordering is wrong -- and would otherwise
            # show up only as a plausible-looking shape effect.
            flat_self = abs(f.periodic_peak_k - f.mean_steady_peak_k)
            ok_flat = flat_self <= f.temperature_output_resolution_k + 1e-9
            print(f"    consistency: flat periodic {f.periodic_peak_k:.4f} vs its own "
                  f"mean-steady {f.mean_steady_peak_k:.4f} K -> diff {flat_self:.4f} K "
                  f"{'OK' if ok_flat else 'MISMATCH'}")
            if not ok_flat:
                print(f"    FAIL: a constant-power trace must reach its steady state; "
                      f"the periodic solve or the column ordering is wrong, so the shape "
                      f"effect below cannot be trusted")
                sys.exit(3)
            if f.periodic_hottest_block != f.mean_steady_hottest_block:
                print(f"    FAIL: flat's periodic hottest block "
                      f"{f.periodic_hottest_block} != its steady hottest block "
                      f"{f.mean_steady_hottest_block}")
                sys.exit(3)

            gap = s.periodic_peak_k - f.periodic_peak_k
            resolution = max(s.temperature_output_resolution_k,
                             f.temperature_output_resolution_k)
            # Only conclusions larger than the residuals AND the output resolution can
            # be read at all; the frozen 0.01 K band is a STEADY-STATE linearisation
            # bound and does not cover transient discretisation, so it is a floor here,
            # not a certified error contract.
            noise = max(resolution, s.peak_residual_k, f.peak_residual_k,
                        s.boundary_residual_k, f.boundary_residual_k)
            print(f"\n  [{model_id}] SHAPE EFFECT (scheduled - flat) = {gap:+.4f} K")
            print(f"    largest residual / output resolution = {noise:.4f} K "
                  f"-> effect is {abs(gap) / noise:.2f}x it")
            if abs(gap) <= noise:
                verdict = "INDETERMINATE"
                print(f"    INDETERMINATE: the difference does not exceed the numerical "
                      f"floor; core schedule shape is not resolvable here.")
            else:
                verdict = "RESOLVED"
            # `>=` on both sides so the exactly-at-limit case cannot fall through into a
            # spurious disagreement, which a strict < / > pair does.
            s_safe = s.periodic_peak_k < THERMAL_LIMIT_K
            f_safe = f.periodic_peak_k < THERMAL_LIMIT_K
            if s_safe == f_safe:
                feas = "both SAFE" if s_safe else "both REJECT"
            else:
                feas = "DISAGREE (point estimate only)"
            print(f"    margins: scheduled {THERMAL_LIMIT_K - s.periodic_peak_k:+.4f} K, "
                  f"flat {THERMAL_LIMIT_K - f.periodic_peak_k:+.4f} K -> {feas}")
            same_hot = s.periodic_hottest_block == f.periodic_hottest_block
            print(f"    hottest block: {'unchanged' if same_hot else 'MOVED'} "
                  f"({s.periodic_hottest_block} vs {f.periodic_hottest_block})")
            if feas.startswith("DISAGREE"):
                print(f"    A point-estimate disagreement is NOT a certified flip: that "
                      f"needs non-overlapping intervals under a transient error contract, "
                      f"which does not exist yet.")
            report["models"][model_id] = {
                "shape_effect_k": gap, "numerical_floor_k": noise, "verdict": verdict,
                "flat_self_consistency_k": flat_self,
                "feasibility": feas, "hottest_block_moved": not same_hot,
                **{f"{n}_{k}": getattr(r, k) for n, r in res.items()
                   for k in ("periodic_peak_k", "periodic_hottest_block", "cycles",
                             "boundary_residual_k", "peak_residual_k",
                             "fixed_initial_peak_k", "mean_steady_peak_k", "step_s",
                             "samples_per_cycle")},
            }
        print(f"\n  BOUNDARY: compute-domain core-only. No DRAM (40.56% of dissipated "
              f"energy), no NoP (10.90%), no NoC.")
        (OUTPUT / f"core_flip_{WORKLOAD}_{ARCH_ID}.json").write_text(
            json.dumps(report, indent=2, default=str))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
