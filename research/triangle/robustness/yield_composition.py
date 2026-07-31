"""The chiplet-count decision changes sign with the yield COMPOSITION rule, not with the physics.

`ThermoDSE/core/chiplet_eva.py:162-165` forms the yield term of EDYP as an area-weighted arithmetic
MEAN of the per-die yields:

    Y_mean = sum_ij (h_i w_j / (sum_i h_i)(sum_j w_j)) * Y(h_i w_j + A_nop)
    Y(a)   = (1 + a * D0 / alpha)^(-alpha)          D0 = 0.08 cm^-2, alpha = 10, 14 nm

The weights sum to one over that Cartesian double loop, so it is a genuine weighted mean. Under a
refinement of a fixed tile grid every child die is smaller than its parent and `Y` is decreasing in
area, so the mean can only RISE as the design is cut -- at any parameter values. There is no term in
it that grows with the die count.

That is the whole issue, and it is a statement about the OBJECTIVE, not an accusation about the
implementation: an aggregation with no count-dependent penalty cannot express the trade the chiplet
cost literature is about. The canonical model (Chiplet Actuary, DAC 2022,
`github.com/Yinxiao-Feng/chiplet-actuary`) uses the SAME per-die negative-binomial yield
(`exploration.py:51`) and then composes it two ways, neither of them an average:

    chip.py:50        N_KGD = N_die_total * die_yield         yield as a per-die COST divisor
    package.py:209    y2    = bonding_yield ** chip_num()     assembly loss, MULTIPLICATIVE in count
    package.py:214    cost_wasted_chips = (raw + defect) * (1 / (y2 * y3) - 1)

so cutting buys per-die yield and pays a penalty that compounds in the number of dies. That is
exactly the term the mean is missing, and it is why that paper finds a die-area CROSSOVER rather
than a monotone preference for more chiplets.

This probe therefore reports the same designs under three explicit system assumptions and lets the
reader see which conclusions survive all of them:

    mean     Y_mean                        what the frozen evaluator reports
    product  prod_ij Y(h_i w_j + A_nop)    all dies must be good, no known-good-die screening
    kgd      sum_ij (h_i w_j + A_nop) / Y(...) / bonding^n   expected SILICON AREA per working
                                                              system -- an explicitly defined proxy,
                                                              NOT Chiplet Actuary's cost, which also
                                                              carries wafer utilisation, scribe loss,
                                                              bump, interposer, substrate, test and
                                                              NRE terms this does not model

None is declared uniquely correct -- that would need fabrication, test, assembly and redundancy
assumptions this project does not have. The point is that the CUT DECISION is not invariant across
them, so it cannot be certified from the objective value alone.

## The general condition, which is what makes this more than one tool's defect

**Proposition (refinement-monotone aggregates cannot price chiplet count).** Let a design be cut
into dies of areas `a_1..a_n`, let `Y` be any strictly decreasing function of die area, and let the
yield term of the objective be the area-weighted mean `G = sum_i (a_i / A) Y(a_i + c)` with per-die
overhead `c >= 0`. Split one die of area `a` into `a'` and `a''` with `a' + a'' = a`. Then

    (a'/A) Y(a'+c) + (a''/A) Y(a''+c)  >  (a/A) Y(a+c)

because `Y(a'+c) > Y(a+c)` and `Y(a''+c) > Y(a+c)` while the weights still sum to `a/A`. So **G
strictly increases under every refinement, at every parameter value**. An objective dividing by `G`
therefore has no interior optimum in the cut dimension arising from the yield term: whatever trade
appears must come from the other factors, and the yield term can only ever argue for cutting further.

The condition is a property of the AGGREGATION, not of this evaluator, and it is what a reader should
check in any thermal-aware chiplet DSE that reports a scalar "yield". An aggregate can price count
risk only if it is NOT refinement-monotone. Both standard alternatives fail refinement-monotonicity
in the useful direction: `prod_i Y_i` decreases under refinement whenever total silicon does not
shrink, and any aggregate carrying `bonding^n` decreases geometrically in the count.

`test_yield_refinement_monotonicity` in the test suite executes the proposition rather than asserting
it in prose.

## The phase boundary, so this is decision analysis and not a disagreement of proxies

Reporting that two objectives prefer two designs invites the reply that different objectives are
supposed to differ. The sharper statement fixes ONE model and varies ONE manufacturing-policy
parameter until the decision flips. With the KGD proxy

    EDYP_kgd(n) = ED(n) * S(n) / y_b^n,        S(n) = sum_i (a_i + c) / Y(a_i + c)

two cuts `m < n` tie at

    y_b* = ( ED(n) S(n) / ED(m) S(m) ) ^ (1 / (n - m))

which is closed form. Below `y_b*` the coarser cut wins, above it the finer one. Reported against the
0.99 organic-substrate bonding yield Chiplet Actuary registers, so a reader can see whether the
boundary sits inside the plausible range or far outside it.

## The self-check that makes the rest trustworthy

Every point recomputes `Y_mean` from the recorded die geometry and compares it against the
`die_yield` the pinned evaluator itself wrote into the capture. If the two disagree beyond
`MEAN_TOLERANCE`, the geometry is being read wrongly and the probe REFUSES -- because the product
and KGD numbers are built from the same edge lists, and a silent geometry error would corrupt them
without any other symptom. This is the cheapest available check that could refute the whole file,
so it runs first and it is fatal.

Peer review required exact per-die recomputation rather than the `Y_mean ** n` shortcut, which is
valid only when the cut divides the tile grid evenly. Two of the twelve swept architectures cut a
5-tile row in two, giving unequal dies, and for those the mean does not determine the product at
all. Reading the edge lists removes the shortcut and the exclusion together.

NON-CLAIM diagnostic. Reads committed captures; writes one JSON.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/yield_composition.py <sweep.json> <capture-dir> \\
        [out.json]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

D0, ALPHA = 0.08, 10          # ThermoDSE/core/gen_hw_setting.py, 14 nm
# Chiplet Actuary's organic-substrate bonding yield (`parameter.ini`, OS section). Used only in the
# KGD column, and reported so a reader can see how much of that column it drives.
BONDING_YIELD = 0.99
# Tight enough to mean what the prose claims. At 5e-4 the check passes a disagreement in the fourth
# decimal while the text said "reproduces to 6 dp"; measured agreement is exact to floating point, so
# the tolerance is set where the claim is.
MEAN_TOLERANCE = 5e-7


def die_yield(area_m2: float) -> float:
    """The registered per-die yield. Area in m^2; the model is stated per cm^2."""

    return (1.0 + area_m2 * 1e4 * D0 / ALPHA) ** (-ALPHA)


def compositions(die_h_m, die_w_m, nop_area_m2):
    """Every composition of one design's per-die yields, from the geometry alone."""

    heights = np.asarray(die_h_m, dtype=float)
    widths = np.asarray(die_w_m, dtype=float)
    if heights.ndim != 1 or widths.ndim != 1 or heights.size == 0 or widths.size == 0:
        raise ValueError("die edge lists must be non-empty one-dimensional arrays")
    if not (np.all(np.isfinite(heights)) and np.all(np.isfinite(widths))):
        raise ValueError("die edge lists must be finite")
    if np.any(heights <= 0) or np.any(widths <= 0):
        raise ValueError("die edges must be positive")
    if not math.isfinite(nop_area_m2) or nop_area_m2 < 0.0:
        # Nonnegativity as well as finiteness: a negative NoP area shrinks every die below its own
        # geometry and raises every yield, with no other symptom.
        raise ValueError(f"the per-die NoP area must be finite and nonnegative, got {nop_area_m2}")

    areas = np.outer(heights, widths).reshape(-1)
    total = float(heights.sum()) * float(widths.sum())
    yields = np.array([die_yield(a + float(nop_area_m2)) for a in areas])
    # Guarded before the log and the division. An underflowed yield would silently produce an
    # infinite KGD cost and a zero product, either of which reads as a decisive preference.
    if not np.all(np.isfinite(yields)) or np.any(yields <= 0.0):
        raise ValueError("per-die yields must be finite and strictly positive to compose")

    mean = float((yields * areas / total).sum())
    # Sum of logs, not a running product: with tens of dies the direct product underflows long
    # before the answer stops mattering, and the log form is exact to the same relative precision.
    product = float(np.exp(np.log(yields).sum()))
    count = areas.size
    bonding = BONDING_YIELD ** count
    kgd_silicon = float(((areas + float(nop_area_m2)) / yields).sum() / bonding)
    return {
        "dies": count,
        "die_areas_m2": [float(a) for a in areas],
        "yield_mean": mean,
        "yield_product": product,
        # Bonding applied to the product too, so that comparing `product` against `kgd` isolates
        # the SCREENING policy and nothing else. Peer review found the earlier comparison confounded:
        # it changed screening, bonding, units and normalisation at once, and a reviewer could then
        # say only that two different objectives picked two different designs.
        "yield_product_with_bonding": float(product * bonding),
        "kgd_silicon_m2_per_good_system": kgd_silicon,
        "bonding_penalty": float(1.0 / bonding - 1.0),
    }


def main() -> None:
    sweep_path = Path(sys.argv[1])
    captures = Path(sys.argv[2])
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    points = json.loads(sweep_path.read_text())
    rows = []
    for point in points:
        capture = captures / f"{point['workload']}--{point['arch']}.npz"
        with np.load(capture, allow_pickle=False) as data:
            missing = [k for k in ("die_h_list_m", "die_w_list_m", "nop_area_m2") if k not in data]
            if missing:
                raise SystemExit(
                    f"{capture} predates the die-geometry recording and is missing {missing}; "
                    "recapture rather than reconstructing the geometry from the composed scalar, "
                    "which cannot be inverted for unequal dies"
                )
            derived = compositions(
                data["die_h_list_m"], data["die_w_list_m"], float(data["nop_area_m2"])
            )
            reported = float(data["die_yield"])
            latency = float(data["latency_ms"])
            energy = float(data["energy_mj"])

        # Fatal, and first: the product and KGD columns are built from the same edge lists, so a
        # geometry misread would corrupt them with no other symptom.
        if not math.isfinite(reported) or abs(derived["yield_mean"] - reported) > MEAN_TOLERANCE:
            raise SystemExit(
                f"{point['arch']}/{point['workload']}: recomputed area-weighted mean "
                f"{derived['yield_mean']:.6f} disagrees with the evaluator's own die_yield "
                f"{reported:.6f} by more than {MEAN_TOLERANCE}; the die geometry is being read "
                "wrongly and every composition below it is unsound"
            )

        energy_delay = latency * energy
        rows.append({
            **{k: point[k] for k in ("arch", "tiles", "cut", "dies", "workload") if k in point},
            "interval_m": point.get("interval_m"),
            "epsilon_star": point.get("epsilon_star", point.get("beta_star")),
            # The EXACT L1 relocation radius when the sweep recorded one. Distinct from
            # `epsilon_star`, which is the deviation box's; the two must never be merged.
            "beta_star_l1": point.get("beta_star_l1"),
            "tau_star": point.get("tau_star"),
            "peak_k": point.get("peak_k"),
            "energy_delay": energy_delay,
            "yield_mean": derived["yield_mean"],
            "yield_product": derived["yield_product"],
            "yield_product_with_bonding": derived["yield_product_with_bonding"],
            "edyp_mean": energy_delay / derived["yield_mean"],
            "edyp_product": energy_delay / derived["yield_product"],
            "edyp_product_bonded": energy_delay / derived["yield_product_with_bonding"],
            "kgd_silicon_m2_per_good_system": derived["kgd_silicon_m2_per_good_system"],
            "edyp_kgd": energy_delay * derived["kgd_silicon_m2_per_good_system"],
            "bonding_penalty": derived["bonding_penalty"],
            "die_areas_m2": derived["die_areas_m2"],
            "equal_dies": len(set(round(a, 12) for a in derived["die_areas_m2"])) == 1,
        })

    # Which composition prefers which cut, per (tile grid, spacing, workload) decision group.
    groups: dict = {}
    for row in rows:
        key = (tuple(row["tiles"]), row.get("interval_m"), row["workload"])
        groups.setdefault(key, []).append(row)
    verdicts = []
    for key, members in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(members) < 2:
            continue
        # The bonding yield at which each coarser/finer pair ties under the KGD proxy. `edyp_kgd`
        # already carries `1 / bonding^n`, so multiply it back out before solving.
        boundaries = []
        ordered = sorted(members, key=lambda r: r["dies"])
        for coarse_row, fine_row in zip(ordered, ordered[1:]):
            m, n = coarse_row["dies"], fine_row["dies"]
            if n <= m:
                continue
            unbonded_coarse = coarse_row["edyp_kgd"] * BONDING_YIELD ** m
            unbonded_fine = fine_row["edyp_kgd"] * BONDING_YIELD ** n
            if unbonded_coarse <= 0 or not math.isfinite(unbonded_fine / unbonded_coarse):
                continue
            critical = (unbonded_fine / unbonded_coarse) ** (1.0 / (n - m))
            # A critical value above 1 is NOT a phase boundary: every physical bonding yield
            # satisfies 0 < y_b <= 1, so the coarser cut wins at every attainable value and there is
            # no crossover. Quoting it beside genuine boundaries would invite a reader to compare
            # 1.0025 with 0.99 as if a 1% change could cross it.
            boundaries.append({
                "dies_coarse": m, "dies_fine": n,
                "critical_bonding_yield": critical,
                "physical_crossover": critical <= 1.0,
                "finer_wins_at_registered_bonding": BONDING_YIELD > critical,
                "critical_inside_plausible_range": 0.95 <= critical <= 1.0,
            })
        picks = {
            name: min(members, key=lambda r: r[field])
            for name, field in (("mean", "edyp_mean"), ("product", "edyp_product"),
                                ("product_bonded", "edyp_product_bonded"), ("kgd", "edyp_kgd"))
        }
        # Ranked by the EXACT relocation radius when it is present, since that is the quantity the
        # document quotes; the deviation-box radius is the fallback for a sweep captured before it.
        def _radius(row):
            value = row["beta_star_l1"] if row["beta_star_l1"] is not None else row["epsilon_star"]
            return value if value is not None else -1.0

        robust = max(members, key=_radius)
        verdicts.append({
            "tiles": list(key[0]), "interval_m": key[1], "workload": key[2],
            "dies_by_composition": {n: p["dies"] for n, p in picks.items()},
            "dies_most_robust": robust["dies"],
            "compositions_disagree": len({p["dies"] for p in picks.values()}) > 1,
            "robust_choice_matches_mean": picks["mean"]["dies"] == robust["dies"],
            "all_equal_dies": all(m["equal_dies"] for m in members),
            "bonding_phase_boundaries": boundaries,
        })
        print(
            "%-9s gap %-7s %-12s  mean->n=%-2d prod->n=%-2d prod+bond->n=%-2d kgd->n=%-2d  "
            "robust n=%-2d  %-8s  y_b* %s"
            % (
                "%dx%d" % key[0], key[1], key[2],
                picks["mean"]["dies"], picks["product"]["dies"],
                picks["product_bonded"]["dies"], picks["kgd"]["dies"], robust["dies"],
                "DISAGREE" if len({p["dies"] for p in picks.values()}) > 1 else "agree",
                ",".join(
                    "%d/%d:%s" % (
                        b["dies_coarse"], b["dies_fine"],
                        "%.4f" % b["critical_bonding_yield"] if b["physical_crossover"]
                        else "none(>1)",
                    )
                    for b in boundaries
                ),
            ),
            flush=True,
        )

    disagree = sum(1 for v in verdicts if v["compositions_disagree"])
    print(
        "\n%d of %d decision groups change their preferred chiplet count with the composition rule."
        % (disagree, len(verdicts)),
        flush=True,
    )
    payload = {"bonding_yield": BONDING_YIELD, "points": rows, "verdicts": verdicts}
    if out_path is not None:
        out_path.write_text(json.dumps(payload, indent=1))


if __name__ == "__main__":
    main()
