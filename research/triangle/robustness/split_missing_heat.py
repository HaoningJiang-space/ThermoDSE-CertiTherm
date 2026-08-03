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
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cross_grid_bound import _extreme_rows
from CertiTherm.experiments import _power_space
from CertiTherm.tabular import read_rows as _rows

# THE MISSING FRACTION IS PER CASE, AND USING ONE VALUE FOR ALL SIX WAS THE SINGLE POINT OF FAILURE.
# This constant used to be `9.2218 / 4.6118 - 1.0 = 0.9997`, the audit closure for ONE architecture,
# applied to every case by scaling with total power. `research/triangle/energy_ledger.py` measures it
# per case, and the true span is 0.3328 to 0.9997 -- a factor of three. 0.9997 is the LARGEST of the
# six, so every uplift computed from it was overstated, in the direction that makes the certificate
# look stricter than it is. Every document that quoted a scaled-`Q` number is withdrawn; see
# `docs/PER_CASE_Q_WITHDRAWS_THE_PLACEMENT_FREE_REFUSAL.md`.
#
# It is read from the committed ledger and there is NO fallback: a case absent from the table is a
# refusal, not a default, because the default is exactly what went wrong.
MISSING_ENERGY_LEDGER = Path("experiments") / "missing_energy_ledger.tsv"
CROSS_SOLVER_BAND_K = (0.2997, 1.4332)          # docs/PACKAGE_SWEEP_RESULT.md, all three packages


def _missing_over_admitted(root: Path):
    """`{(workload, arch): ratio}` from the committed ledger, checked rather than trusted."""
    table = {}
    for row in _rows(root / MISSING_ENERGY_LEDGER):
        ratio = float(row["missing_over_admitted"])
        shares = [float(row[f"{s}_share_of_missing"]) for s in ("dram", "nop", "noc", "core")]
        # A ratio a certificate is built from must not be NaN, and `NaN <= 0` is False, so the
        # finiteness check is separate and first.
        if not math.isfinite(ratio) or ratio <= 0.0:
            raise SystemExit(f"{row['arch_id']}/{row['workload']}: missing ratio {ratio!r}")
        # 1e-8 is the table's own precision (nine decimals, four shares), not a tolerance chosen to
        # let the data through: the identity holds to 1e-12 before serialisation.
        if not all(map(math.isfinite, shares)) or abs(sum(shares) - 1.0) > 1e-8:
            raise SystemExit(
                f"{row['arch_id']}/{row['workload']}: source shares sum to {sum(shares)!r}, not 1; "
                "the ledger does not classify all of the missing energy"
            )
        table[(row["workload"], row["arch_id"])] = ratio
    if not table:
        raise SystemExit(f"{MISSING_ENERGY_LEDGER} is empty")
    return table

# NON-UNIFORMITY ALLOWANCE. The uniform-density cap `q_i <= Q * A_i / A(S)` with the total equality
# `sum q_i = Q` is a SINGLETON, not a set: summing the caps gives exactly `Q`, so every `q_i` is
# forced to its bound and the only feasible placement is the uniform one. The "spread" it produces is
# therefore the value AT an assumed placement, not a supremum over placements, and a certificate read
# off it certifies uniform density rather than every admissible spreading. Verified numerically:
# `sum(upper) == Q` to machine precision at n = 5, 50 and 181.
#
# `kappa` restores the set. `q_i <= kappa * Q * A_i / A(S)` says the heat is spread over the die and
# no block carries more than `kappa` times its area share -- `kappa = 1` is exactly uniform (the
# singleton), and `kappa >= A(S) / min_i A_i` readmits the point load. The greedy fill stays exact
# because a box with a total equality is a fractional knapsack at every `kappa`.
#
# NO SOURCE IS CLAIMED FOR ANY PARTICULAR VALUE. What is reported instead is the CRITICAL kappa at
# which each case stops certifying, which needs no provenance and turns the assumption into a
# falsifiable condition: "this verdict holds unless some block carries more than K times its area
# share".
KAPPA_SWEEP = (1.0, 1.25, 1.5, 2.0, 3.0, 5.0, 10.0)


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


# Baselines a reviewer will ask about. None of them knows the missing heat exists, which is the
# point: they are not weaker versions of this method, they are what is done today.
GUESSED_GUARD_BANDS_K = (3.0, 5.0)


def main() -> None:
    root, artifacts = Path(sys.argv[1]), Path(sys.argv[2])
    packages = sys.argv[3].split(",") if len(sys.argv) > 3 else ["default", "standard", "enhanced"]
    missing_ratio = _missing_over_admitted(Path("."))
    results = []
    for package in packages:
      for capture in sorted((artifacts / "captures").glob("*.npz")):
          name = capture.stem
          workload, arch = name.split("--")
          if (workload, arch) not in missing_ratio:
              raise SystemExit(
                  f"{arch}/{workload} has no row in {MISSING_ENERGY_LEDGER}. A missing fraction is "
                  "measured per case, never defaulted -- defaulting it is the error this table exists "
                  "to prevent. Run research/triangle/energy_ledger.py for this case first."
              )
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
          missing_w = missing_ratio[(workload, arch)] * float(power.sum())

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
          share = np.where(die, centre_w * areas / max(die_area, 1e-30), 0.0)

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

          def spread_at(kappa):
              """`sup_q sum_i (R_ji - m) q_i` over the box `[0, kappa * share]` with `sum q = Q`.

              At `kappa = 1` the box's own sum equals `Q`, so the greedy has no freedom and returns the
              uniform-density value. Above 1 it is a genuine supremum over a non-degenerate set.
              """
              return float(_extreme_rows((row - m)[None, :], lower,
                                         np.asarray(kappa) * share, centre_w)[0])

          spread = spread_at(1.0)
          by_kappa = {f"{k:g}": spread_at(k) for k in KAPPA_SWEEP}

          # The critical kappa: where `peak + guaranteed + spread(kappa)` first reaches the limit.
          # Monotone in kappa (a larger box can only raise a supremum), so a bisection is exact to
          # tolerance and needs no provenance for kappa itself.
          headroom = limit - (peak + guaranteed)
          if headroom <= 0.0:
              critical = 0.0                      # already refuted before any placement is considered
          elif spread_at(KAPPA_SWEEP[-1]) <= headroom:
              critical = float("inf")             # survives the whole swept range
          else:
              lo, hi = 1.0, float(KAPPA_SWEEP[-1])
              if spread_at(lo) > headroom:
                  critical = 1.0                  # fails even at exact uniform density
              else:
                  for _ in range(60):
                      mid = 0.5 * (lo + hi)
                      if spread_at(mid) <= headroom:
                          lo = mid
                      else:
                          hi = mid
                  critical = lo

          results.append({
              "spread_by_kappa_k": by_kappa,
              "critical_kappa": critical,
              "workload": workload, "architecture": arch, "package": package,
              "frame_fraction": frame_fraction,
              "missing_over_admitted": missing_ratio[(workload, arch)],
              "missing_w": missing_w,
              "peak_with_frame_share_k": peak,
              "guaranteed_rise_k": guaranteed,
              "placement_spread_k": spread,
              "lower_bound_k": peak + guaranteed,
              "upper_bound_k": peak + guaranteed + spread,
              "slack_k": limit - (peak + guaranteed + spread),
              "refuted_regardless_of_placement": bool(peak + guaranteed > limit),
              "certified_at_uniform_density": bool(peak + guaranteed + spread <= limit),
              # WHAT THE FIELD DOES TODAY, on the same operator and the same nominal map. None of
              # these knows the missing heat exists -- that IS the comparison, not a handicap.
              "nominal_peak_k": float((rows @ power + ambient).max()),
              "verdict_nominal": ("SAFE" if float((rows @ power + ambient).max()) <= limit
                                  else "UNSAFE"),
              "verdict_guard": {
                  "%.0fK" % g: ("SAFE" if float((rows @ power + ambient).max()) + g <= limit
                                else "UNSAFE")
                  for g in GUESSED_GUARD_BANDS_K
              },
              "verdict_here": ("REFUTED_PLACEMENT_FREE" if peak + guaranteed > limit
                               else "CERTIFIED" if peak + guaranteed + spread <= limit
                               else "UNRESOLVED"),
          })

    if not results:
        raise SystemExit("no (architecture, workload) point produced a bound; nothing was tested")

    # THE HEADLINE NUMBER: what fraction is decided WITHOUT knowing where the missing heat goes.
    decided = [r for r in results if r["verdict_here"] != "UNRESOLVED"]
    placement_free = [r for r in results if r["verdict_here"] == "REFUTED_PLACEMENT_FREE"]
    disagreements = [
        {"case": f'{r["architecture"]}/{r["workload"]}/{r["package"]}',
         "here": r["verdict_here"], "nominal": r["verdict_nominal"], "guard": r["verdict_guard"]}
        for r in results
        if (r["verdict_here"] == "REFUTED_PLACEMENT_FREE" and r["verdict_nominal"] == "SAFE")
        or (r["verdict_here"] == "CERTIFIED" and "UNSAFE" in r["verdict_guard"].values())
    ]
    summary = {
        "points": len(results),
        "decided": len(decided),
        "decidability": len(decided) / len(results),
        "placement_free_verdicts": len(placement_free),
        "disagreements_with_the_field": disagreements,
    }

    by_key = {(r["architecture"], r["workload"]): r for r in results}
    verdict = {}
    for workload in sorted({r["workload"] for r in results}):
        b, c = by_key.get(("arch_b", workload)), by_key.get(("arch_c", workload))
        if not (b and c):
            continue
        band_hi = CROSS_SOLVER_BAND_K[1]
        verdict[workload] = (
            "HEADLINE HOLDS AT UNIFORM DENSITY: arch_b %s, arch_c certified with %.3f K against a "
            "%.4f K band, and stops certifying once some block carries more than %.3gx its area share"
            % ("refuted under EVERY placement" if b["refuted_regardless_of_placement"]
               else "not certified", c["slack_k"], band_hi, c["critical_kappa"])
            if (not b["certified_at_uniform_density"]) and c["certified_at_uniform_density"] and c["slack_k"] > band_hi else
            "UNRESOLVED: arch_b certified=%s, arch_c certified=%s, arch_c slack %.3f K vs band %.4f K"
            % (b["certified_at_uniform_density"], c["certified_at_uniform_density"], c["slack_k"], band_hi)
        )
    print(json.dumps({"missing_over_admitted": {f"{a}/{w}": r
                                                for (w, a), r in sorted(missing_ratio.items())},
                      "cross_solver_band_k": CROSS_SOLVER_BAND_K,
                      "summary": summary,
                      "results": results, "verdict": verdict}, indent=1), flush=True)


if __name__ == "__main__":
    main()
