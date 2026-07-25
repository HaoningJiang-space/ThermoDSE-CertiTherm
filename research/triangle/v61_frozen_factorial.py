"""V6.1 factorial from ONE frozen capture, with runtime provenance and an automatic gate.

Replaces `v61_factorial.sh`, whose evidence contract had five defects. All five are fixed
here, and each fix exists because the shell version's artifacts could only be graded
DIAGNOSTIC:

1. FIFTEEN INDEPENDENT CAPTURES. The shell driver invoked `complete_trace_probe.py` once per
   subset, so ThermoDSE ran 15 times and each run rewrote the shared floorplan and sim
   workspace. Here `capture_frozen_inputs()` runs ONCE and every subset is lowered from the
   same frozen objects, so the hazard is removed structurally rather than checked for.

2. CONCURRENCY RACE ON SHARED PATHS. Two drivers were run against one output directory,
   both rewriting `complete_floorplan_*.flp` and `work/capture--*`. Final hashes agreed and
   subset powers were exactly the sum of singletons, but no report recorded the hashes read
   AT RUN TIME, so a race could not be excluded. Every run now writes into its own directory
   and records the hash of every input as it reads it.

3. REUSE ON DIRECTORY EXISTENCE. `if [ -d "$DEST" ]` accepted partial, crashed or stale
   output. Reuse now requires a complete report whose recorded commit, dirty state, input
   hashes, model, step and component set all match the request.

4. NO GATE. The full-set row must reproduce the registered counterexample or no summary is
   emitted at all.

5. NO MACHINE-READABLE MANIFEST, and 25 reports of three different kinds were archived
   together. One manifest is written naming every row, its role, and its provenance.

Registered counterexample this must reproduce (docs/V6_PHYSICAL_TRACE_GATE.md):
Transformer/arch_b, grid64-max, ~0.5 us -> mean-steady 329.904867 K, periodic 330.19 K,
both at mtxu_16.

NON-CLAIM diagnostic until it has run from a clean revision in an isolated workspace.

Usage:
    python research/triangle/v61_frozen_factorial.py <out> [model] [step_us] [workload] [arch]
"""
from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.experiments import HOTSPOT, THERMAL_LIMIT_K
from CertiTherm.routed_trace import COMPONENTS, lower_routed_trace
from CertiTherm.transient import replay_periodic
from research.triangle.complete_trace_probe import capture_frozen_inputs

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/v61frozen")
MODEL = sys.argv[2] if len(sys.argv) > 2 else "grid64-max"
STEP_US = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
WORKLOAD = sys.argv[4] if len(sys.argv) > 4 else "transformer"
ARCH = sys.argv[5] if len(sys.argv) > 5 else "arch_b"
AMBIENT_K = 318.15

# The gate. Values from the registered grid64-max run; only enforced for that model/step.
GATE = {"model": "grid64-max", "mean_steady_peak_k": 329.904867,
        "periodic_peak_k": 330.19, "hottest": "mtxu_16"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_state():
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    return head.stdout.strip(), [l for l in dirty.stdout.splitlines() if l.strip()]


def subset_tag(sub) -> str:
    return "full" if len(sub) == len(COMPONENTS) else "-".join(sorted(sub))


def reusable(dest: Path, want: dict) -> bool:
    """Reuse only a COMPLETE report whose provenance matches the request.

    Directory existence is not evidence: a crashed run leaves a directory, and a stale one
    leaves a report computed from different inputs.
    """
    report = dest / "v61_row.json"
    if not report.is_file():
        return False
    try:
        got = json.loads(report.read_text())
    except Exception:
        return False
    if not got.get("complete"):
        return False
    keys = ("commit", "dirty", "model", "max_step_us", "components",
            "input_hashes", "hotspot_sha256")
    return all(got.get(k) == want.get(k) for k in keys)


def main() -> None:
    commit, dirty = git_state()
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"### commit={commit[:8]} dirty={len(dirty)} model={MODEL} "
          f"step={STEP_US}us {WORKLOAD}/{ARCH} ###")
    if dirty:
        print(f"  WARNING: {len(dirty)} dirty file(s); this run is DIAGNOSTIC, not "
              f"claim-grade. Claim-grade requires a clean committed revision.")

    # ---- ONE capture, frozen ------------------------------------------------------
    frozen = capture_frozen_inputs(OUT / "capture", WORKLOAD, ARCH, 1.0)
    sim = frozen["sim"]
    flp = OUT / "capture" / f"frozen_floorplan_{WORKLOAD}_{ARCH}.flp"
    flp.write_text(frozen["augmented"].text, encoding="utf-8")
    inputs = {
        "floorplan": flp,
        "config": Path(sim) / "example.config",
        "materials": Path(sim) / "example.materials",
    }
    # Hashes recorded AS THE INPUTS ARE READ, which is what makes a race falsifiable.
    input_hashes = {k: sha256(v) for k, v in inputs.items()}
    hotspot_sha = sha256(Path(HOTSPOT))
    print(f"  frozen capture: {frozen['core'].trace.n_phases} phases, "
          f"{len(frozen['augmented'].block_ids)} blocks, {len(frozen['events'])} events")
    for k, v in input_hashes.items():
        print(f"    {k:11s} {v[:16]}...")

    # ---- lower every non-empty subset from the SAME frozen objects ---------------
    subsets = [sub for k in range(1, len(COMPONENTS) + 1)
               for sub in itertools.combinations(COMPONENTS, k)]
    rows, singles = {}, {}
    for sub in subsets:
        routed = lower_routed_trace(
            frozen["core"], floorplan=frozen["augmented"], events=frozen["events"],
            compute_shape=frozen["shape"], chiplet_cuts=frozen["cuts"],
            noc_hop_cost_pj=frozen["noc_hop_cost_pj"],
            nop_hop_cost_pj=frozen["nop_hop_cost_pj"],
            batch_factor=frozen["batch_factor"], components=sub)
        rows[sub] = routed
        if len(sub) == 1:
            singles[sub[0]] = routed.trace.powers_w

    # ---- the identity that retroactively validated the previous artifacts --------
    # Codified rather than assumed: with one frozen capture it should be exact by
    # construction, so any deviation means the masking itself is wrong.
    worst = 0.0
    for sub, routed in rows.items():
        if len(sub) < 2:
            continue
        expected = sum(singles[name] for name in sub)
        worst = max(worst, float(np.abs(routed.trace.powers_w - expected).max()))
    print(f"  superposition identity (subset == sum of singletons): "
          f"worst {worst:.3e} W")
    if worst > 0.0:
        print("FAIL: masked subsets are not the exact sum of their singletons; the mask "
              "is not a pure deposition gate"); sys.exit(3)

    # ---- replay each row into its OWN directory ---------------------------------
    manifest = {"commit": commit, "dirty": dirty, "model": MODEL,
                "max_step_us": STEP_US, "workload": WORKLOAD, "arch": ARCH,
                "input_hashes": input_hashes, "hotspot_sha256": hotspot_sha,
                "thermal_limit_k": THERMAL_LIMIT_K, "ambient_k": AMBIENT_K,
                "superposition_worst_w": worst,
                "component_energy_j": dict(rows[tuple(COMPONENTS)].component_energy_j),
                "full_source_energy_j": rows[tuple(COMPONENTS)].full_source_energy_j,
                "rows": {}}
    for sub in subsets:
        tag = subset_tag(sub)
        dest = OUT / f"row_{tag}_{MODEL}_{STEP_US:g}us"
        want = {"commit": commit, "dirty": dirty, "model": MODEL,
                "max_step_us": STEP_US, "components": list(sub),
                "input_hashes": input_hashes, "hotspot_sha256": hotspot_sha}
        if reusable(dest, want):
            row = json.loads((dest / "v61_row.json").read_text())
            print(f"  {tag:22s} reused (provenance verified)")
        else:
            dest.mkdir(parents=True, exist_ok=True)
            r = replay_periodic(
                binary=HOTSPOT, config=inputs["config"], floorplan=flp,
                materials=inputs["materials"], model_id=MODEL,
                block_ids=frozen["augmented"].block_ids, trace=rows[sub].trace,
                workspace=dest / "hotspot", max_step_s=STEP_US * 1e-6,
                fixed_initial_k=AMBIENT_K, tolerance_k=0.01)
            row = dict(want)
            row.update({
                "retained_source_energy_j": rows[sub].source_energy_j,
                "mean_steady_peak_k": r.mean_steady_peak_k,
                "mean_steady_hottest_block": r.mean_steady_hottest_block,
                "periodic_peak_k": r.periodic_peak_k,
                "periodic_hottest_block": r.periodic_hottest_block,
                "fixed_initial_peak_k": r.fixed_initial_peak_k,
                "cycles": r.cycles, "step_s": r.step_s,
                "samples_per_cycle": r.samples_per_cycle,
                "boundary_residual_k": r.boundary_residual_k,
                "peak_residual_k": r.peak_residual_k,
                "output_resolution_k": r.temperature_output_resolution_k,
                "complete": True,
            })
            (dest / "v61_row.json").write_text(json.dumps(row, indent=2))
            print(f"  {tag:22s} steady {row['mean_steady_peak_k']:.6f} K  periodic "
                  f"{row['periodic_peak_k']:.2f} K  at {row['periodic_hottest_block']:11s} "
                  f"cyc={row['cycles']}")
        manifest["rows"][tag] = row

    # ---- GATE: the full row must reproduce the registered counterexample ---------
    full = manifest["rows"]["full"]
    if MODEL == GATE["model"]:
        res = full["output_resolution_k"]
        ok = (abs(full["mean_steady_peak_k"] - GATE["mean_steady_peak_k"]) <= 1e-6
              and abs(full["periodic_peak_k"] - GATE["periodic_peak_k"]) <= res + 1e-9
              and full["periodic_hottest_block"] == GATE["hottest"])
        manifest["gate"] = {"model": MODEL, "passed": bool(ok), "expected": GATE}
        print(f"\n  GATE ({MODEL}): {'PASS' if ok else 'FAIL'} -- expected "
              f"{GATE['mean_steady_peak_k']:.6f}/{GATE['periodic_peak_k']:.2f} K at "
              f"{GATE['hottest']}, got {full['mean_steady_peak_k']:.6f}/"
              f"{full['periodic_peak_k']:.2f} K at {full['periodic_hottest_block']}")
        if not ok:
            manifest["summary"] = "SUPPRESSED: the gate did not reproduce the registered "\
                                  "counterexample, so no row may be read"
            (OUT / "v61_manifest.json").write_text(json.dumps(manifest, indent=2))
            print("  no summary emitted."); sys.exit(4)
    else:
        manifest["gate"] = {"model": MODEL, "passed": None,
                            "note": "gate is registered for grid64-max only; this run is a "
                                    "resolution cross-check, not the registered case"}
        print(f"\n  GATE: not applicable to {MODEL}; this run is a resolution cross-check.")

    # ---- summary: minimal crossing coalitions and leave-one-out -----------------
    crossing = {frozenset(sub) for sub in subsets
                if manifest["rows"][subset_tag(sub)]["periodic_peak_k"] >= THERMAL_LIMIT_K}
    minimal = sorted(("+".join(sorted(c)) for c in crossing
                      if not any(o < c for o in crossing)), key=len)
    loo = {}
    for drop in COMPONENTS:
        sub = tuple(c for c in COMPONENTS if c != drop)
        row = manifest["rows"][subset_tag(sub)]
        loo[drop] = {"periodic_peak_k": row["periodic_peak_k"],
                     "below_limit": row["periodic_peak_k"] < THERMAL_LIMIT_K}
    manifest["summary"] = {
        "crossing_subsets": sorted("+".join(sorted(c)) for c in crossing),
        "minimal_crossing_coalitions": minimal,
        "leave_one_out": loo,
        # Absolute uplift only. The uplift/steady-rise RATIO spans about 1.9-5.0% across the
        # 15 subsets and is resolution-sensitive on the small-rise subsets (a 0.01 K output
        # quantum over a ~2 K rise), so no uniform percentage is claimed and any
        # source-identity effect on uplift is UNTESTED.
        "uplift_k": {t: round(r["periodic_peak_k"] - r["mean_steady_peak_k"], 4)
                     for t, r in manifest["rows"].items()},
        "source_identity_effect_on_uplift": "UNTESTED",
        "evidence_grade": ("diagnostic (dirty tree)" if dirty else
                           "isolated single-capture run with runtime provenance; "
                           "HotSpot-bounded, no independent signoff model"),
    }
    print(f"\n  minimal crossing coalitions: {minimal or '(none)'}")
    for drop, v in loo.items():
        print(f"    full-minus-{drop:5s} periodic {v['periodic_peak_k']:.2f} K -> "
              f"{'BELOW  => conditionally necessary' if v['below_limit'] else 'still OVER'}")
    (OUT / "v61_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print(f"\n  wrote {OUT / 'v61_manifest.json'}")
    print("  Conclusions are bounded to THIS candidate, threshold, HotSpot model and "
          "discretisation. No independent signoff model has validated them.")


if __name__ == "__main__":
    main()
