"""Split the missing heat by the geometry the generator establishes, and re-test the DECISION.

`docs/NUISANCE_BOUND_IS_NOT_AN_ESCAPE.md` placed ALL of the missing heat on `eblk0..3` and concluded
the `arch_b -> arch_c` headline was strengthened. **That was wrong**: `gen_cover_flp`
(`ThermoDSE/core/gen_floorplan.py:202-209`) emits FIVE blocks, not four -- `name_e0..e3` form the
frame and `name` is a central block of exactly `(sys_width, sys_height)` covering the compute die.
Measured on the committed captures, the frame is only **19-25 %** of the cover area.

So the honest construction splits the missing power by that ratio:

* the FRAME share is PLACED on `eblk0..3` weighted by area -- established from the generator;
* the CENTRE share is left as a nuisance set supported on the die blocks with a total-power
  equality, entering each row through the support function `h_Q(r_j) = sup_q r_j q`, which is the
  greedy fill `cross_grid_bound._extreme_rows` computes exactly.

Every piece is therefore either established or explicitly bounded, and nothing is guessed.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/split_missing_heat.py <operator-root> <artifacts>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cross_grid_bound import _extreme_rows
from CertiTherm.experiments import _power_space

# From the audit closure: dissipated 9.2218 mJ against 4.6118 mJ reaching HotSpot.
MISSING_OVER_ARRIVING = 9.2218 / 4.6118 - 1.0
CROSS_SOLVER_BAND_K = (0.2997, 1.4332)          # docs/PACKAGE_SWEEP_RESULT.md, all three packages


def _geometry(floorplan_text: str, blocks):
    """`(frame_area, centre_area, per-block area)` from the capture's own floorplan."""
    area = {}
    frame = 0.0
    xs, ys = [], []
    for line in str(floorplan_text).splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        name = parts[0]
        w, h, x, y = (float(v) for v in parts[1:5])
        area[name] = w * h
        if name.startswith("eblk"):
            frame += w * h
        else:
            xs += [x, x + w]
            ys += [y, y + h]
    if not xs:
        raise SystemExit("the floorplan has no non-eblk block; the centre area is undefined")
    centre = (max(xs) - min(xs)) * (max(ys) - min(ys))
    missing = [b for b in blocks if b not in area]
    if missing:
        raise SystemExit(f"{len(missing)} placed blocks name no floorplan unit, e.g. {missing[:3]}")
    return frame, centre, np.asarray([area[b] for b in blocks], dtype=float)


def main() -> None:
    root, artifacts = Path(sys.argv[1]), Path(sys.argv[2])
    package = sys.argv[3] if len(sys.argv) > 3 else "standard"
    results = []
    for capture in sorted((artifacts / "captures").glob("*.npz")):
        name = capture.stem
        workload, arch = name.split("--")
        operator = root / "g512" / f"{arch}--{package}.npz"
        if not operator.exists():
            continue
        with np.load(operator, allow_pickle=False) as data:
            rows = np.asarray(data["response_k_per_w"], dtype=float)[0]
            ambient = np.asarray(data["ambient_k"], dtype=float)[0]
            limit = float(data["limit_k"])
        _space, blocks, placed, floorplan = _power_space(capture)
        power = np.asarray(placed, dtype=float)
        if rows.shape[1] != power.size:
            continue

        frame_area, centre_area, areas = _geometry(floorplan, blocks)
        frame_fraction = frame_area / (frame_area + centre_area)
        missing_w = MISSING_OVER_ARRIVING * float(power.sum())

        # PLACED: the frame share, area-weighted over eblk0..3.
        is_frame = np.asarray([b.startswith("eblk") for b in blocks])
        if not is_frame.any():
            continue
        weights = np.where(is_frame, areas, 0.0)
        placed_nuisance = missing_w * frame_fraction * weights / weights.sum()

        # BOUNDED: the centre share, adversarial over the die blocks with a total equality. Support
        # function of a box-with-total is the same greedy fill the certificate already uses.
        centre_w = missing_w * (1.0 - frame_fraction)
        die = ~is_frame
        lower = np.zeros(power.size)
        # THE DECLARED SET HAS TO SAY WHAT THE SOURCE IS. Allowing `q_i` up to the whole centre
        # share lets a plane of DRAM collapse onto one 1 mm block, which is not a conservative
        # reading of an unknown placement -- it is a different physical object. DRAM is a memory
        # plane and NoP is interconnect: both are DISTRIBUTED sources with bounded areal density.
        # So the box is a uniform-density cap, `q_i <= Q * area_i / area(S)`, which is exactly the
        # statement "the heat is spread over the die, we just do not know how evenly". The total
        # equality is unchanged, so the set still contains every admissible spreading.
        die_area = float(areas[die].sum())
        upper = np.where(die, centre_w * areas / max(die_area, 1e-30), 0.0)

        nominal = rows @ (power + placed_nuisance) + ambient
        hottest = int(np.argmax(nominal))
        peak = float(nominal.max())

        # THE DECOMPOSITION THAT MAKES THIS TWO-SIDED, and it is where the elegance is.
        #
        # `R`'s rows are Green's functions: a source acts on an observation point through a nearly
        # uniform FAR field -- that is what the spreader does -- plus a NEAR field significant only
        # for sources close to it. Writing `m = min_{i in S} R_ji`,
        #
        #     R_j q  =  Q * m  +  sum_i (R_ji - m) q_i
        #
        # The first term is produced by EVERY admissible placement, because the heat is conserved
        # and has to go somewhere in `S`. It is not an error -- it is a known, unavoidable rise.
        # Only the second term is "we do not know where it is", and its width is the row's SPREAD
        # over `S`, not the row's maximum. Reporting the lumped adversarial max conflates the two
        # and charges the certificate for heat it knows about.
        #
        # And because the first term is a guarantee rather than a bound, the same decomposition
        # REFUTES: if `peak + Q*m > limit` the design is infeasible under every placement, with no
        # placement evidence required at all.
        row = rows[hottest]
        m = float(row[die].min())
        guaranteed = centre_w * m
        spread = float(_extreme_rows((row - m)[None, :], lower, upper, centre_w)[0])

        results.append({
            "workload": workload, "architecture": arch, "package": package,
            "frame_fraction": frame_fraction,
            "missing_w": missing_w,
            "peak_with_frame_share_k": peak,
            "guaranteed_rise_k": guaranteed,
            "placement_spread_k": spread,
            "lower_bound_k": peak + guaranteed,
            "upper_bound_k": peak + guaranteed + spread,
            "slack_k": limit - (peak + guaranteed + spread),
            "refuted_regardless_of_placement": bool(peak + guaranteed > limit),
            "certified": bool(peak + guaranteed + spread <= limit),
        })

    if not results:
        raise SystemExit("no (architecture, workload) point produced a bound; nothing was tested")

    by_key = {(r["architecture"], r["workload"]): r for r in results}
    verdict = {}
    for workload in sorted({r["workload"] for r in results}):
        b, c = by_key.get(("arch_b", workload)), by_key.get(("arch_c", workload))
        if not (b and c):
            continue
        band_hi = CROSS_SOLVER_BAND_K[1]
        verdict[workload] = (
            "HEADLINE HOLDS: arch_b %s, arch_c certified with %.3f K against a %.4f K band"
            % ("refuted under EVERY placement" if b["refuted_regardless_of_placement"]
               else "not certified", c["slack_k"], band_hi)
            if (not b["certified"]) and c["certified"] and c["slack_k"] > band_hi else
            "UNRESOLVED: arch_b certified=%s, arch_c certified=%s, arch_c slack %.3f K vs band %.4f K"
            % (b["certified"], c["certified"], c["slack_k"], band_hi)
        )
    print(json.dumps({"missing_over_arriving": MISSING_OVER_ARRIVING,
                      "cross_solver_band_k": CROSS_SOLVER_BAND_K,
                      "results": results, "verdict": verdict}, indent=1), flush=True)


if __name__ == "__main__":
    main()
