"""Measured tool cost of the thermal fidelity ladder (NON-CLAIM).

Every cost in `measurement_registry.tsv` is a HAND-ASSIGNED 1/2/4/8. Nothing in the
project has ever measured what an analysis actually costs, so the whole premise
that cheap analysis should be preferred over expensive analysis is currently
unquantified -- and so is the "real report cost vs 1/2/4/8" ablation.

This measures the cheapest real data point available without any new
infrastructure: wall time of a single HotSpot steady solve at each registered
model fidelity, on a REAL candidate's floorplan, plus the cost of building the
full linear operator at that fidelity (one solve per block, which is what
CertiTherm actually pays).

What it establishes: the RATIO between fidelity levels. That ratio is what decides
whether "only refine when the winner could change" has any system value -- if the
finest model is barely dearer than the coarsest, the methodology has nothing to
save.

What it does NOT establish: the cost of the analyses further up the proposed
ladder (placed transient power, FEM/3D-ICE signoff), which are not implemented
here, nor licence/queue costs of a real EDA flow.

Usage (clone root, after operators are cached):
    python research/triangle/fidelity_cost.py <out> <workload> <cand> [reps]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.hotspot import HotSpotModel, _run, _floorplan_units
from CertiTherm.experiments import (
    HOTSPOT, ROOT, TEMPLATE, _capture, _configure, _ordered_architectures,
    _registry_split, _rows,
)

OUTPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/diag150b")
WORKLOAD = sys.argv[2] if len(sys.argv) > 2 else "resnet50"
CAND = int(sys.argv[3]) if len(sys.argv) > 3 else 1
REPS = int(sys.argv[4]) if len(sys.argv) > 4 else 5
MODELS = ("block", "grid64-avg", "grid128-avg", "grid256-avg")


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

    # Materialise the same HotSpot inputs the operator build uses (experiments.py
    # writes floorplan.flp from the capture and configures package.config), so the
    # measured cost is the cost of the analysis CertiTherm actually runs.
    ws = OUTPUT / "work" / f"fidelity_cost--{a0['architecture_id']}"
    ws.mkdir(parents=True, exist_ok=True)
    with np.load(caps[(WORKLOAD, a0["architecture_id"])], allow_pickle=False) as data:
        floorplan = ws / "floorplan.flp"
        floorplan.write_text(str(data["floorplan_text"]), encoding="utf-8")
    config = ws / "package.config"
    _configure(TEMPLATE / "example.config", config, default_pkg)
    materials = TEMPLATE / "example.materials"
    binary = HOTSPOT
    units = _floorplan_units(floorplan)
    n = len(units)

    print(f"{a0['architecture_id']} ({WORKLOAD} c{CAND}): {n} floorplan units, "
          f"{REPS} reps per model, binary={binary}", flush=True)

    unit_power = np.ones(n, dtype=float)
    rows = []
    for mid in MODELS:
        model = HotSpotModel.parse(mid)
        times = []
        for r in range(REPS):
            t0 = time.perf_counter()
            try:
                _run(binary, config, floorplan, materials, model, units, unit_power,
                     ws, f"cost_{mid}_{r}")
            except Exception as exc:                    # fail closed, never fabricate
                print(f"  {mid}: FAILED ({type(exc).__name__}: {exc}) -> UNRESOLVED")
                times = None
                break
            times.append(time.perf_counter() - t0)
        if times is None:
            rows.append({"model": mid, "status": "UNRESOLVED"})
            continue
        t = np.array(times)
        # CertiTherm builds a LINEAR OPERATOR: one solve per block, plus ambient.
        operator_s = float(t.mean()) * (n + 1)
        rows.append({"model": mid, "status": "OK", "reps": REPS,
                     "solve_median_s": float(np.median(t)),
                     "solve_min_s": float(t.min()), "solve_max_s": float(t.max()),
                     "operator_build_s_est": operator_s})
        print(f"  {mid:12s} solve median={np.median(t):.3f}s "
              f"[{t.min():.3f}-{t.max():.3f}]  -> operator build est "
              f"{operator_s:.0f}s ({operator_s/60:.1f} min)", flush=True)

    ok = [r for r in rows if r.get("status") == "OK"]
    if len(ok) >= 2:
        base = ok[0]["solve_median_s"]
        print("\n  fidelity ladder cost RATIO (relative to the coarsest working model):")
        for r in ok:
            print(f"    {r['model']:12s} {r['solve_median_s']/base:8.2f}x  "
                  f"(operator {r['operator_build_s_est']/ok[0]['operator_build_s_est']:.2f}x)")
        print("\n  A narrow ratio means 'refine only when the winner could change' has "
              "little to save; a wide one is what gives the methodology system value.")

    out = OUTPUT / f"fidelity_cost_{WORKLOAD}_c{CAND}.json"
    out.write_text(json.dumps({"candidate": a0["architecture_id"], "workload": WORKLOAD,
                               "cand_index": CAND, "units": n, "rows": rows}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
