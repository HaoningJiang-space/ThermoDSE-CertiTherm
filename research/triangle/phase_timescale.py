"""Does power SHAPE change peak temperature at the REAL workload timescale? (NON-CLAIM)

The decisive question for whether a transient formulation belongs in the paper at all.

The transient probe (docs/TRANSIENT_PROBE.md) showed thermal inertia exists: a 20 W 1 ms
impulse gives +5.07 K with multi-exponential decay. But it used an arbitrary impulse. The
captures say the whole `resnet50` workload has `latency_ms = 0.602` -- SHORTER than the
~1 ms fast thermal component. If the chip low-passes everything at that scale, two
differently-shaped power traces reach the same temperature, a steady-state model on mean
power loses nothing, and "steady-state ranking differs from transient ranking" cannot happen.

So this compares, at that timescale and on real placed power, two traces with the same
per-block time average -- which is all a steady-state model driven by mean power can see:

    flat    every step at the mean power              p_mean
    bursty  alternating 2*p_mean / 0                  same per-block mean

**ADVERSARIAL SENSITIVITY TEST, NOT WORKLOAD EVIDENCE.** The bursty trace doubles every
block simultaneously, which is very likely unreachable for any legal schedule -- precisely
the sort of world `CertiTherm/phase_trace.py` exists to exclude. `latency_ms` is also the
whole-workload latency, not a layer or kernel phase duration, and the capture holds a single
whole-run average power vector, so no real phase structure is available here.

The probe is therefore conclusive in ONE direction only. A gap at or below the reference
scale would rule transient shape out at this timescale. A LARGE gap establishes nothing
about real schedules and must not be cited as workload evidence: only a trace derived from
a real scheduler can support a positive claim.

Both traces are replayed over many periods and the period-over-period drift is reported,
because the two approach DIFFERENT periodic states and an unconverged comparison is
differentially biased.

Usage: python research/triangle/phase_timescale.py <out> <workload> <cand> [period_ms] [periods]
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.experiments import (
    HOTSPOT, ROOT, TEMPLATE, THERMAL_LIMIT_K, _capture, _configure,
    _ordered_architectures, _registry_split, _rows,
)
from CertiTherm.hotspot import _floorplan_units

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/diag150b")
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
CAND = int(sys.argv[3]) if len(sys.argv) > 3 else 1
PERIOD_MS = float(sys.argv[4]) if len(sys.argv) > 4 else 0.602   # measured latency_ms
PERIODS = int(sys.argv[5]) if len(sys.argv) > 5 else 400         # reach periodic steady state
STEPS_PER_PHASE = 4                                             # resolution within a phase
ERROR_BAND_K = 0.01                                             # frozen linearisation band


def hotspot_transient(config, floorplan, materials, units, rows_w, sampling_s, ws, tag):
    """Run one transient simulation; return the (steps, units) temperature matrix."""
    ptrace = ws / f"{tag}.ptrace"
    out = ws / f"{tag}.out"
    with ptrace.open("w") as fh:
        fh.write("\t".join(units) + "\n")
        for row in rows_w:
            fh.write("\t".join(f"{v:.6f}" for v in row) + "\n")
    cmd = [str(HOTSPOT), "-c", str(config), "-f", str(floorplan), "-p", str(ptrace),
           "-materials_file", str(materials), "-model_type", "block",
           "-sampling_intvl", repr(sampling_s), "-o", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if res.returncode != 0 or not out.exists():
        raise RuntimeError(f"HotSpot transient failed: {res.stderr[-400:]}")
    data = np.loadtxt(out, skiprows=1)
    if data.ndim == 1:
        data = data.reshape(1, -1)
    return data


def main():
    reg = _registry_split("dev_v3")
    arches = sorted((r for r in _rows(ROOT / "experiments" / "architectures.tsv")
                     if r["split"] == reg), key=lambda r: int(r["rank"]))
    pkgs = _rows(ROOT / "experiments" / "packages.tsv")
    default_pkg = next(p for p in pkgs if p["package_id"] == "default")
    wl = next(w for w in _rows(ROOT / "experiments" / "workloads.tsv")
              if w["split"] == reg and w["workload_id"] == WORKLOAD)
    caps = {(WORKLOAD, a["architecture_id"]): _capture(a, wl, default_pkg, OUTPUT)
            for a in arches}
    a0 = _ordered_architectures(WORKLOAD, arches, caps)[CAND]
    cap = caps[(WORKLOAD, a0["architecture_id"])]

    ws = OUTPUT / "work" / f"phase_timescale--{a0['architecture_id']}"
    ws.mkdir(parents=True, exist_ok=True)
    with np.load(cap, allow_pickle=False) as d:
        (ws / "floorplan.flp").write_text(str(d["floorplan_text"]), encoding="utf-8")
        placed = np.asarray(d["placed_power_w"], dtype=float)
        latency_ms = float(d["latency_ms"])
    floorplan = ws / "floorplan.flp"
    config = ws / "package.config"
    _configure(TEMPLATE / "example.config", config, default_pkg)
    materials = TEMPLATE / "example.materials"
    units = _floorplan_units(floorplan)

    if placed.size != len(units):
        # FAIL CLOSED. Zero-padding or truncating a mismatched power vector silently
        # moves power onto the wrong blocks, which would corrupt every temperature
        # here while still producing plausible-looking numbers.
        print(f"FAIL: placed_power_w has {placed.size} entries but the floorplan has "
              f"{len(units)} units; refusing to guess an alignment")
        sys.exit(2)

    period_s = PERIOD_MS * 1e-3
    sampling_s = period_s / (2 * STEPS_PER_PHASE)
    total_w = float(placed.sum())
    print(f"{a0['architecture_id']} ({WORKLOAD} c{CAND}): {len(units)} units, "
          f"placed total {total_w:.2f} W, capture latency {latency_ms:.3f} ms")
    print(f"period {PERIOD_MS:.3f} ms over {PERIODS} periods "
          f"({PERIODS * 2 * STEPS_PER_PHASE} steps of {sampling_s * 1e6:.1f} us)")

    # FLAT: mean power every step. BURSTY: 2x for half the period, 0 for the other half.
    # Identical mean and identical energy -- a steady-state abstraction cannot tell them
    # apart, which is the whole point.
    flat_period = [placed] * (2 * STEPS_PER_PHASE)
    bursty_period = ([placed * 2.0] * STEPS_PER_PHASE
                     + [np.zeros_like(placed)] * STEPS_PER_PHASE)
    flat_rows = flat_period * PERIODS
    bursty_rows = bursty_period * PERIODS
    if not np.allclose(np.mean(flat_rows, axis=0), np.mean(bursty_rows, axis=0)):
        print("FAIL: the two traces do not share a mean; the comparison would be meaningless")
        sys.exit(2)

    results = {}
    for name, rows in (("flat", flat_rows), ("bursty", bursty_rows)):
        temps = hotspot_transient(config, floorplan, materials, units, rows,
                                  sampling_s, ws, name)
        if temps.shape[1] != len(units):
            print(f"FAIL: HotSpot returned {temps.shape[1]} columns for {len(units)} "
                  f"units; column-to-unit mapping cannot be trusted"); sys.exit(2)
        per = 2 * STEPS_PER_PHASE
        if temps.shape[0] < 2 * per:
            print(f"FAIL: only {temps.shape[0]} steps; need at least two periods"); sys.exit(2)
        last, prev = temps[-per:], temps[-2 * per:-per]
        hot = int(last.max(axis=0).argmax())           # the hottest UNIT over the period
        # CONVERGENCE: with a package tail still visible at 8 ms, a fixed period count
        # may not have reached the periodic orbit. Incomplete convergence biases the
        # comparison, so report the period-over-period drift instead of assuming.
        drift = float(np.abs(last - prev).max())
        results[name] = {
            "peak_k": float(last.max()),
            "peak_unit": units[hot],
            # temporal quantities on the HOTTEST UNIT only. Taking max-min across both
            # units and time mixes spatial gradient with temporal ripple and is not
            # physically interpretable.
            "hot_unit_mean_k": float(last[:, hot].mean()),
            "hot_unit_ripple_k": float(last[:, hot].max() - last[:, hot].min()),
            "period_drift_k": drift,
            "converged": bool(drift < 0.001),          # 10x under the 0.01 K band
            "steps": int(temps.shape[0]),
        }
        r = results[name]
        print(f"  {name:7s} peak={r['peak_k']:.4f} K at {r['peak_unit']:12s} "
              f"hot-unit ripple={r['hot_unit_ripple_k']:.4f} K  "
              f"period drift={drift:.5f} K {'(converged)' if r['converged'] else '(NOT CONVERGED)'}")

    if not (results["flat"]["converged"] and results["bursty"]["converged"]):
        print("\n  WARNING: at least one trace has not reached a periodic orbit. The two "
              "traces approach different periodic states, so an unconverged comparison is "
              "DIFFERENTIALLY biased -- rerun with more periods before reading the gap.")
    gap = results["bursty"]["peak_k"] - results["flat"]["peak_k"]
    margin = THERMAL_LIMIT_K - results["flat"]["peak_k"]
    print(f"\n  SHAPE EFFECT on peak temperature: {gap:+.4f} K")
    # ERROR_BAND_K is the STEADY-STATE linearisation/replay contract. It is NOT a
    # transient discretisation or physical-model error bound, so it is a reference
    # scale here, not a detectability threshold for transient work.
    print(f"  steady-state linearisation band (reference scale only, NOT a transient "
          f"error bound): +/-{ERROR_BAND_K} K -> gap is {abs(gap) / ERROR_BAND_K:.1f}x it")
    if margin > 0:
        print(f"  distance from flat peak to THERMAL_LIMIT_K={THERMAL_LIMIT_K}: "
              f"{margin:.4f} K -> shape effect is {abs(gap) / margin * 100:.2f}% of it")
    else:
        print(f"  flat peak already exceeds THERMAL_LIMIT_K={THERMAL_LIMIT_K}")
    print("\n  ADVERSARIAL SENSITIVITY TEST, NOT WORKLOAD EVIDENCE. The bursty trace "
          "doubles every block simultaneously, which is very likely UNREACHABLE for any "
          "legal schedule -- exactly the kind of world CertiTherm/phase_trace.py exists to "
          "exclude. So this probe is conclusive only in the NEGATIVE direction: a gap at or "
          "below the reference scale would rule transient shape out, while a LARGE gap "
          "establishes nothing about real schedules and must not be cited as one. Only a "
          "trace derived from a real scheduler can support a positive claim.")

    (OUTPUT / f"phase_timescale_{WORKLOAD}_c{CAND}.json").write_text(json.dumps({
        "candidate": a0["architecture_id"], "workload": WORKLOAD, "cand_index": CAND,
        "period_ms": PERIOD_MS, "periods": PERIODS, "sampling_s": sampling_s,
        "capture_latency_ms": latency_ms, "placed_total_w": total_w,
        "error_band_k": ERROR_BAND_K, "thermal_limit_k": THERMAL_LIMIT_K,
        "results": results, "shape_effect_k": gap,
    }, indent=2))


if __name__ == "__main__":
    main()
