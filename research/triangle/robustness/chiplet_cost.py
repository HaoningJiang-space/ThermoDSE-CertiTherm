"""The complete organic-substrate recurring cost of a chiplet system, not a silicon-area proxy.

Peer review's sharpest surviving objection to the phase boundary was that it was derived inside a
proxy `S(n) = sum_i (a_i + c) / Y(a_i + c)` which omits wafer utilisation, scribe loss, bumps,
substrate area and cost, test and the wasted-die term -- **all of them count-dependent**, any one
able to move a crossover by more than the 0.0136 separating a measured 0.9764 from a registered
0.99. So the boundary established that a crossover exists near the registered value, not which side
of it the registered value falls on.

This file removes that objection by implementing the published flow instead of a proxy. It is a
clean-room transcription of the organic-substrate (`OS`) recurring-cost path of Chiplet Actuary
(Feng and Ma, DAC 2022, `github.com/Yinxiao-Feng/chiplet-actuary`, MIT licence), from
`chiplet_actuary/chip.py`, `chiplet_actuary/package.py` and `parameter.ini`:

    Area_chip   = A + 2 s sqrt(A) + s^2                             scribe lane s = 0.2 mm
    N_die_total = pi (D/2 - e)^2 / Area_chip                         wafer D = 300 mm, edge loss
                  - pi (D - 2 e) / sqrt(2 Area_chip)                 e = 5 mm
    Y(A)        = (1 + D0/100 * A / L)^(-L)                          14 nm: D0 = 0.08 cm^-2, L = 10
    cost_raw    = W / N_die_total                                    wafer cost W = 3984 $
    cost_KGD    = W / (N_die_total * Y)
    cost_defect = cost_KGD - cost_raw                                the test/discard term

    package area = sum of die areas * 4                              os_area_scale_factor
    cost_raw_package = package area * 0.005 * f(area, chips)         RE_cost_factor, size factor
    cost_defect_package = cost_raw_package * (1 / y_b^n - 1)         y_b = 0.99, n = chip count
    cost_wasted_chips   = (raw + defect chips) * (1 / y_b^n - 1)

    RE = cost_raw_chips + cost_defect_chips + cost_raw_package + cost_defect_package
         + cost_wasted_chips
    cost_raw_chips includes A * 0.005 per chip for C4 bumps.

**Every term the proxy omitted is present**, and three of them grow with the chiplet count: the
substrate defect term, the wasted-chip term, and the per-chip bump area. Nothing is vendored --
this is a transcription with the source, commit-free path and licence recorded, in the style the
workspace requires before reuse. NRE is deliberately NOT included: it is a non-recurring cost
amortised over an unknown volume, so adding it would make the comparison depend on a number this
project does not have. That exclusion is a scope statement, not an omission of a count-dependent
recurring term.

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


def critical_bonding_yield(coarse_metric: float, fine_metric: float, coarse_n: int, fine_n: int):
    """Where two cuts tie, solved for the ONE parameter that enters as `y_b^(-n)`.

    Both objectives carry the same `1 / y_b^n` factor on their yield-dependent part, so the tie
    condition is closed form only when the rest is `y_b`-independent. Under the full cost flow it
    is NOT -- the substrate defect term and the wasted-chip term both scale with `1/y_b^n` while
    the raw chip and raw package terms do not -- so this closed form belongs to the PROXY and the
    full model must be swept numerically instead. Kept here, next to the model that refutes its
    applicability, so the distinction cannot be lost again.
    """

    if fine_n <= coarse_n or coarse_metric <= 0.0:
        raise ValueError("the finer cut must have strictly more dies and a positive coarse metric")
    return (fine_metric / coarse_metric) ** (1.0 / (fine_n - coarse_n))
