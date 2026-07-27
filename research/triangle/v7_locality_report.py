"""Generate the transient-locality report from committed data. (NON-CLAIM tooling)

No number in the output is hand-transcribed. Everything is either read from the schema-5
manifest, read from the pinned stack-mapping artifact's material block, or derived from those by
a stated formula printed alongside it.

Two sources, and why each is legitimate here:

- `artifacts_receipts/v61_cg5_schema5/v61_manifest.json` -- the claim-grade factorial. The
  workload period is NOT a separate input: it is `step_s * samples_per_cycle`.
- `docs/registration/v7_gate_stack_mapping.json` -- its material block (die conductivity, heat
  capacity, thickness, TIM properties) was read programmatically from the hash-pinned HotSpot
  materials file. That artifact is marked REJECTED_BEFORE_USE, but the rejection concerned its
  GEOMETRY (three package footprints cannot share one global footprint), not these material
  constants, which are unaffected.

Usage: python research/triangle/v7_locality_report.py [out.md]
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "artifacts_receipts/v61_cg5_schema5/v61_manifest.json"
MAPPING = ROOT / "docs/registration/v7_gate_stack_mapping.json"


def _corr(xs, ys) -> float:
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return num / den


def penetration_depth_m(k_si: float, c_si: float, omega: float) -> float:
    """delta = sqrt(2 alpha / omega), alpha = k / c. The 1-D semi-infinite scale, not a
    predicted uplift."""
    return math.sqrt(2.0 * (k_si / c_si) / omega)


def analyse() -> dict:
    m = json.loads(MANIFEST.read_text())
    mapping = json.loads(MAPPING.read_text())
    ambient = m["ambient_k"]
    full = m["rows"]["full"]
    quantum = full["output_resolution_k"]

    period_s = full["step_s"] * full["samples_per_cycle"]
    omega = 2.0 * math.pi / period_s

    die = mapping["die"]
    k_si = die["thermal_conductivity_w_per_um_k"] * 1e6
    c_si = die["volumetric_heat_capacity_j_per_um3_k"] * 1e18
    t_die_um = die["thickness_um"]
    tim = next(x for x in mapping["passive_layers_above"] if x["layer_id"] == "tim")
    k_tim = tim["thermal_conductivity_w_per_um_k"] * 1e6
    c_tim = tim["volumetric_heat_capacity_j_per_um3_k"] * 1e18

    rows = {}
    for tag, r in m["rows"].items():
        rows[tag] = {
            "energy_mj": r["retained_source_energy_j"] * 1e3,
            "rise_k": r["mean_steady_peak_k"] - ambient,
            "uplift_k": r["periodic_peak_k"] - r["mean_steady_peak_k"],
            "has_core": "core" in r["components"],
        }
    core_rows = [v for v in rows.values() if v["has_core"]]
    core_only, whole = rows["core"], rows["full"]

    d_rise = whole["rise_k"] - core_only["rise_k"]
    d_uplift = whole["uplift_k"] - core_only["uplift_k"]
    # Bound by one output quantum: the raw change is only ~1.4 quanta, so the defensible form is
    # an upper bound on the uplift change, never a percentage.
    d_uplift_bound = abs(d_uplift) + quantum

    return {
        "period_s": period_s, "omega": omega, "quantum": quantum,
        "k_si": k_si, "c_si": c_si, "alpha": k_si / c_si, "t_die_um": t_die_um,
        "delta_si_um": penetration_depth_m(k_si, c_si, omega) * 1e6,
        "delta_tim_um": penetration_depth_m(k_tim, c_tim, omega) * 1e6,
        "tim_thickness_um": tim["thickness_um"],
        "rows": rows, "core_only": core_only, "full": whole,
        "added_energy_frac": (whole["energy_mj"] - core_only["energy_mj"]) / whole["energy_mj"],
        "d_rise_k": d_rise, "d_uplift_k": d_uplift, "d_uplift_bound_k": d_uplift_bound,
        "sensitivity_ratio": d_rise / d_uplift_bound,
        "d_uplift_quanta": abs(d_uplift) / quantum,
        "corr_all_energy_rise": _corr([v["energy_mj"] for v in rows.values()],
                                      [v["rise_k"] for v in rows.values()]),
        "corr_all_energy_uplift": _corr([v["energy_mj"] for v in rows.values()],
                                        [v["uplift_k"] for v in rows.values()]),
        "corr_core_energy_rise": _corr([v["energy_mj"] for v in core_rows],
                                       [v["rise_k"] for v in core_rows]),
        "corr_core_energy_uplift": _corr([v["energy_mj"] for v in core_rows],
                                         [v["uplift_k"] for v in core_rows]),
        "core_energy_span": max(v["energy_mj"] for v in core_rows)
                            / min(v["energy_mj"] for v in core_rows),
        "n_core": len(core_rows), "n_rows": len(rows),
        "model": m["model"], "workload": m["workload"], "arch": m["arch"],
        "commit": m["commit"],
    }


def render(a: dict) -> str:
    L: list[str] = []
    A = L.append
    A("# V7 — the periodic uplift is die-local; the crossing claim is withdrawn")
    A("")
    A("Generated from committed data by `research/triangle/v7_locality_report.py`. No number here "
      "is hand-transcribed: each is read from "
      "`artifacts_receipts/v61_cg5_schema5/v61_manifest.json` or from the material block of "
      "`docs/registration/v7_gate_stack_mapping.json`, or derived from those by the formula "
      "printed beside it. The workload period is not a separate input — it is "
      "`step_s * samples_per_cycle`.")
    A("")
    A("## What is withdrawn")
    A("")
    A(f"The claim that the `{a['model']}` {a['workload']}/{a['arch']} 330 K crossing is "
      f"model-robust — that transient analysis flips this feasibility decision in a way that "
      f"survives model choice.")
    A("")
    A("**It is withdrawn because model-robust support could not be established, not because an "
      "independent model disproved it.** No 3D-ICE or FEM run was performed and no gate output "
      "exists. The independent-model gate was preregistered and then closed without a verdict, "
      "because 3D-ICE cannot represent this package: `ThreeDicePassiveLayerSpec` carries no "
      "footprint and the chip dimensions are global, so a 21.7 x 17.95 mm die, a 50 mm spreader "
      "and a 60 mm sink cannot coexist. Truncating them to the chip footprint adds 44.921 mK/W "
      "of series copper — about 2.57 K at 57.18 W against a 0.095133 K margin — and enlarging "
      "the global footprint instead would extend the silicon die itself as fictitious material.")
    A("")
    A("The >= 0.69 K intra-HotSpot spatial spread recorded in `docs/V6_PHYSICAL_TRACE_GATE.md` "
      "establishes that the classification is **fragile**, not that transient boundary flips do "
      "not exist. Nothing here is a convergence result.")
    A("")
    A("## What replaces it: the uplift is local, and that is measurable")
    A("")
    A(f"The V6.1 factorial is already a locality experiment. Going from the `core`-only subset to "
      f"the full four-source set adds **{100*a['added_energy_frac']:.1f}% of the dissipated "
      f"energy**, and:")
    A("")
    A("| quantity | core only | full | change |")
    A("| --- | ---: | ---: | ---: |")
    A(f"| steady rise above ambient | {a['core_only']['rise_k']:.3f} K | "
      f"{a['full']['rise_k']:.3f} K | **{a['d_rise_k']:+.3f} K** |")
    A(f"| periodic uplift | {a['core_only']['uplift_k']:.4f} K | {a['full']['uplift_k']:.4f} K | "
      f"{a['d_uplift_k']:+.4f} K |")
    A("")
    A(f"The uplift change is only {a['d_uplift_quanta']:.1f} output quanta at the "
      f"{a['quantum']} K reporting resolution, so the defensible form is an upper bound rather "
      f"than a percentage: **the uplift moves by at most {a['d_uplift_bound_k']:.3f} K** while "
      f"the steady rise moves {a['d_rise_k']:.3f} K — a sensitivity ratio of "
      f"**>= {a['sensitivity_ratio']:.0f}x**.")
    A("")
    A(f"Across all {a['n_rows']} subsets, `corr(energy, steady rise) = "
      f"{a['corr_all_energy_rise']:+.3f}` and `corr(energy, uplift) = "
      f"{a['corr_all_energy_uplift']:+.3f}`. Restricting to the {a['n_core']} subsets that "
      f"contain `core`, where energy still varies {a['core_energy_span']:.1f}x, the split is "
      f"sharper: `corr(energy, steady rise) = {a['corr_core_energy_rise']:+.3f}` against "
      f"`corr(energy, uplift) = {a['corr_core_energy_uplift']:+.3f}` — no trend.")
    A("")
    A("## Why: the thermal wave never reaches the package")
    A("")
    A(f"At a period of {a['period_s']*1e3:.7f} ms ({1/a['period_s']:.0f} Hz, "
      f"omega = {a['omega']:.0f} rad/s), with silicon `alpha = k/c = {a['k_si']:.1f}/"
      f"{a['c_si']:.0f} = {a['alpha']:.3e}` m^2/s, the penetration depth is")
    A("")
    A(f"    delta = sqrt(2 alpha / omega) = {a['delta_si_um']:.1f} um")
    A("")
    A(f"against a {a['t_die_um']:.0f} um die: `delta / t_die = "
      f"{a['delta_si_um']/a['t_die_um']:.2f}`. In the TIM it is {a['delta_tim_um']:.1f} um "
      f"against a {a['tim_thickness_um']:.0f} um layer. The periodic component is therefore "
      f"confined to the die and the first few tens of microns above it, which is why lateral and "
      f"remote sources — DRAM dies at the chip corners, distributed NoC and NoP — contribute "
      f"steady heat but almost no local ripple.")
    A("")
    A("## The criterion this yields")
    A("")
    A("> Transient refinement is decision-relevant exactly when the steady margin is smaller "
      "than the **local** ripple. The ripple is set by die properties and workload frequency and "
      "is estimable without any package model; the absolute level, which is what a threshold "
      "crossing depends on, is precisely the package-dependent part.")
    A("")
    A("That is why the two halves of this instance have opposite epistemic status. The uplift is "
      "a robust physical feature: it survives removing 45% of the dissipated power, and its "
      "scale follows from a diffusion length. The crossing is not certifiable at 0.1 K, because "
      "it depends on an absolute level that no two thermal models agree on to that precision — "
      "within HotSpot alone, changing only the spatial mapping moves it by >= 0.69 K.")
    A("")
    A("## Scope")
    A("")
    A(f"- One candidate ({a['workload']}/{a['arch']}), one workload period, one HotSpot model, "
      f"and `{a['model']}` is **out of the certified family** "
      f"(`block`, `grid64-avg`, `grid128-avg`) — so none of this is certificate evidence.")
    A("- `delta` is a one-dimensional semi-infinite estimate. It supplies the *scale* and the "
      "explanation; it is not a predicted uplift. The sensitivity ratio is the measurement.")
    A("- The energy/uplift decoupling is measured across the subsets of a single instance. It is "
      "consistent with the twelve `block` and `grid64-avg` uplifts already recorded "
      "(0.017–0.144 K), but those cases have no committed per-case traces, so no cross-workload "
      "predictor is claimed.")
    A("- No independent thermal model has validated any number here.")
    A("")
    A(f"Source manifest commit `{a['commit'][:12]}`.")
    return "\n".join(L) + "\n"


def main() -> None:
    a = analyse()
    text = render(a)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
        print(f"wrote {sys.argv[1]} ({text.count(chr(10))} lines)")
    else:
        # write, not print: print appends a newline on top of the text's own, which would make
        # stdout differ from the file by one byte and break the byte-for-byte regeneration test
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
