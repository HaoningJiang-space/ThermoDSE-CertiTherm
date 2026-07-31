"""A transcribed organic-substrate RECURRING cost for a chiplet system, replacing a proxy.

Peer review's sharpest surviving objection to the phase boundary was that it was derived inside a
proxy `S(n) = sum_i (a_i + c) / Y(a_i + c)` which omits wafer utilisation, scribe loss, bumps,
substrate area and cost, test and the wasted-die term -- **all of them count-dependent**, any one
able to move a crossover by more than the 0.0136 separating a measured 0.9764 from a registered
0.99. So the boundary established that a crossover exists near the registered value, not which side
of it the registered value falls on.

This file addresses that objection by implementing the published recurring-cost path instead. It is a
clean-room transcription of the organic-substrate (`OS`) recurring-cost path of Chiplet Actuary
(Feng and Ma, DAC 2022, `github.com/Yinxiao-Feng/chiplet-actuary`, MIT licence), from
`chiplet_actuary/chip.py`, `chiplet_actuary/package.py` and `parameter.ini`:

    Area_chip   = A + 2 s sqrt(A) + s^2                             scribe lane s = 0.2 mm
    N_die_total = pi (D/2 - e)^2 / Area_chip                         wafer D = 300 mm, edge loss
                  - pi (D - 2 e) / sqrt(2 Area_chip)                 e = 5 mm
    Y(A)        = (1 + D0/100 * A / L)^(-L)                          14 nm: D0 = 0.08 cm^-2, L = 10
    cost_raw    = W / N_die_total                                    wafer cost W = 3984 $
    cost_KGD    = W / (N_die_total * Y)
    cost_defect = cost_KGD - cost_raw                                the YIELD-DISCARD term

    package area = sum of die areas * 4                              os_area_scale_factor
    cost_raw_package = package area * 0.005 * f(area, chips)         RE_cost_factor, size factor
    cost_defect_package = cost_raw_package * (1 / y_b^n - 1)         y_b = 0.99, n = chip count
    cost_wasted_chips   = (raw + defect chips) * (1 / y_b^n - 1)

    RE = cost_raw_chips + cost_defect_chips + cost_raw_package + cost_defect_package
         + cost_wasted_chips
    cost_raw_chips includes A * 0.005 per chip for C4 bumps.

Terms the silicon-area proxy lacked and this has: wafer utilisation with scribe and edge loss, the
yield-discard cost, C4 bump area, substrate area and rate, and the assembly-loss terms -- three of
which grow with the chiplet count. Two things are still absent and are named rather than implied:

* **NRE**, deliberately. It is non-recurring and amortised over a volume this project does not have,
  and its sign is not universal -- per-design package NRE penalises extra cuts at low volume while
  chiplet reuse amortises it and favours them. So this is a RECURRING-cost result, and any statement
  about total product economics needs a volume.
* **An explicit test cost.** `W/(N Y) - W/N` is the extra wafer cost of dies discarded under
  idealised known-good-die screening -- a *yield-discard* cost. It is not wafer probe, die test,
  package test or test escape, none of which the upstream OS path models either. Peer review caught
  this file calling it "the test/discard term"; the honest name is yield-discard.

So this is a **transcribed organic-substrate recurring-cost model**, not a complete or end-to-end
cost flow, and the document says so. Nothing is vendored; provenance is in `vendor/chiplet-actuary.md`.

## The total FACTORISES, and the closed form was never invalidated

Peer review found an algebraic error that this file itself asserted. Writing `K` for the chip terms,
`P` for the raw package and `L = y_b^(-n) - 1` for the assembly loss, the returned total is

    K + P + P L + K L = (K + P)(1 + L) = (K + P) * y_b^(-n)

so every design's cost is a bonding-yield-INDEPENDENT base times `y_b^(-n)`. The earlier claim -- that
the substrate-defect and wasted-chip terms scale with `1/y_b^n` while the raw terms do not, and that
the tie therefore had to be scanned -- confused the individual terms with their sum. Two cuts tie at

    y_b* = ( ED_f (K_f + P_f) / ED_c (K_c + P_c) ) ^ (1 / (n_f - n_c))

exactly, and `base_cost()` below returns `K + P` so a caller can evaluate it. Verified numerically
against `recurring_cost` to 1e-9 on real instances. The numerical scan that replaced it was not
wrong, only unnecessary -- and, being finite, it could report "no crossover" for a `y_b*` outside
its grid, which the closed form classifies instead.

The registry ThermoDSE uses agrees with this model on the per-die yield -- same negative-binomial
family, same `D0 = 0.08` and `alpha = 10` at 14 nm -- which is why the two can be compared at all.

NON-CLAIM diagnostic; no I/O of its own.
"""

from __future__ import annotations

import math

# parameter.ini [Manufacture] and [14] and [OS].
WAFER_DIAMETER_MM = 300.0
SCRIBE_LANE_MM = 0.2
EDGE_LOSS_MM = 5.0
CRITICAL_LEVEL = 10.0
DEFECT_DENSITY_PER_CM2 = 0.08
WAFER_COST_USD = 3984.0
OS_AREA_SCALE = 4.0
OS_RE_COST_FACTOR = 0.005
OS_BUMP_COST_FACTOR = 0.005
OS_BONDING_YIELD = 0.99


def die_yield(area_mm2: float, defect_density_per_cm2: float = DEFECT_DENSITY_PER_CM2) -> float:
    """`(1 + D0/100 * A_mm2 / L)^(-L)`, which is `(1 + D0 * A_cm2 / L)^(-L)`.

    Written in the published form so a reader comparing the two files sees the same expression;
    the `/100` is the mm^2-to-cm^2 conversion and nothing else.
    """

    return (1.0 + defect_density_per_cm2 / 100.0 * area_mm2 / CRITICAL_LEVEL) ** (-CRITICAL_LEVEL)


def dies_per_wafer(area_mm2: float) -> float:
    """Gross die per wafer WITH scribe lane and edge loss -- the wafer-utilisation term.

    This is why cutting is not free even before yield: a smaller die wastes proportionally more
    area on its own scribe lane, and the edge-loss correction subtracts a perimeter term.
    """

    chip = area_mm2 + 2.0 * SCRIBE_LANE_MM * math.sqrt(area_mm2) + SCRIBE_LANE_MM ** 2
    return (
        math.pi * (WAFER_DIAMETER_MM / 2.0 - EDGE_LOSS_MM) ** 2 / chip
        - math.pi * (WAFER_DIAMETER_MM - 2.0 * EDGE_LOSS_MM) / math.sqrt(2.0 * chip)
    )


def _package_size_factor(package_area_mm2: float, chips: int) -> float:
    """The published substrate-complexity step: one chip is simple, larger packages need layers."""

    if chips == 1:
        return 1.0
    if package_area_mm2 > 30.0 * 30.0:
        return 2.0
    if package_area_mm2 > 17.0 * 17.0:
        return 1.75
    return 1.5


def recurring_cost(
    die_areas_mm2,
    *,
    bonding_yield: float = OS_BONDING_YIELD,
    defect_density_per_cm2: float = DEFECT_DENSITY_PER_CM2,
    wafer_cost_usd: float = WAFER_COST_USD,
    area_scale: float = OS_AREA_SCALE,
    bump_cost_factor: float = OS_BUMP_COST_FACTOR,
    re_cost_factor: float = OS_RE_COST_FACTOR,
):
    """Recurring cost of one working system, with every term broken out.

    Each parameter is exposed because the point of this file is the SENSITIVITY: a boundary that
    moves when a cost factor is swept inside its plausible range was never a boundary.
    """

    areas = [float(a) for a in die_areas_mm2]
    if not areas or any((not math.isfinite(a)) or a <= 0.0 for a in areas):
        raise ValueError("die areas must be a non-empty list of finite positive mm^2 values")
    for name, value in (
        ("bonding_yield", bonding_yield), ("defect_density", defect_density_per_cm2),
        ("wafer_cost", wafer_cost_usd), ("area_scale", area_scale),
        ("bump_cost_factor", bump_cost_factor), ("re_cost_factor", re_cost_factor),
    ):
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and positive, got {value}")
    if bonding_yield > 1.0:
        raise ValueError(f"bonding_yield is a probability and cannot exceed 1, got {bonding_yield}")

    chips = len(areas)
    raw_chips = 0.0
    defect_chips = 0.0
    for area in areas:
        gross = dies_per_wafer(area)
        if gross <= 0.0:
            raise ValueError(
                f"a die of {area} mm^2 does not fit the wafer (gross die per wafer {gross}); the "
                "cost of a design that cannot be manufactured is not a number to report"
            )
        yielded = die_yield(area, defect_density_per_cm2)
        cost_raw = wafer_cost_usd / gross
        raw_chips += cost_raw + area * bump_cost_factor
        defect_chips += wafer_cost_usd / (gross * yielded) - cost_raw

    package_area = sum(areas) * area_scale
    raw_package = package_area * re_cost_factor * _package_size_factor(package_area, chips)
    assembly_loss = 1.0 / bonding_yield ** chips - 1.0
    defect_package = raw_package * assembly_loss
    wasted_chips = (raw_chips + defect_chips) * assembly_loss

    return {
        "chips": chips,
        "cost_raw_chips": raw_chips,
        "cost_defect_chips": defect_chips,
        "cost_raw_package": raw_package,
        "cost_defect_package": defect_package,
        "cost_wasted_chips": wasted_chips,
        "assembly_loss_multiplier": assembly_loss,
        "recurring_total": raw_chips + defect_chips + raw_package + defect_package + wasted_chips,
    }


def base_cost(die_areas_mm2, **overrides) -> float:
    """`K + P`: the part of the recurring cost that does NOT depend on the bonding yield.

    `recurring_total = base_cost * bonding_yield^(-chips)` exactly, which is what makes the tie
    between two cuts a closed form again.
    """

    cost = recurring_cost(die_areas_mm2, **overrides)
    return cost["cost_raw_chips"] + cost["cost_defect_chips"] + cost["cost_raw_package"]


def critical_bonding_yield(coarse_metric: float, fine_metric: float, coarse_n: int, fine_n: int):
    """Where two cuts tie in bonding yield, exactly.

    `metric` is `energy x delay x base_cost` -- the objective with the `y_b^(-n)` factor divided
    out. Since the full total factorises as `base * y_b^(-n)`, the tie condition
    `ED_c B_c y^(-n_c) = ED_f B_f y^(-n_f)` gives the root below with no scanning.

    The returned value is a bare root and may lie OUTSIDE `(0, 1]`. That is information, not an
    error: `y_b* > 1` means the coarser cut wins at every attainable bonding yield and `y_b* <= 0`
    cannot occur for positive metrics. Callers must classify it; an earlier version of this study
    quoted a root of 1.0025 beside a registered 0.99 as though the two were comparable.
    """

    if fine_n <= coarse_n:
        raise ValueError("the finer cut must have strictly more dies")
    if not (coarse_metric > 0.0 and fine_metric > 0.0):
        raise ValueError("both metrics must be positive to take a root of their ratio")
    return (fine_metric / coarse_metric) ** (1.0 / (fine_n - coarse_n))
