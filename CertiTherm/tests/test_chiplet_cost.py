"""The transcribed cost flow, pinned against hand computation and against its own claims.

`research/triangle/robustness/chiplet_cost.py` is a clean-room transcription of a published
organic-substrate recurring-cost model (provenance in `vendor/chiplet-actuary.md`). A transcription
that is merely plausible is worth nothing: the reason it exists is to replace a silicon-area proxy
whose omissions peer review showed could move a phase boundary by more than the boundary's distance
from the value it was being compared against. So each term is checked, and in particular each term
that GROWS with the chiplet count -- those are the ones the proxy lacked and the whole argument
turns on them.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research" / "triangle" / "robustness"))

from chiplet_cost import (  # noqa: E402
    CRITICAL_LEVEL,
    DEFECT_DENSITY_PER_CM2,
    EDGE_LOSS_MM,
    OS_BONDING_YIELD,
    SCRIBE_LANE_MM,
    WAFER_DIAMETER_MM,
    die_yield,
    dies_per_wafer,
    recurring_cost,
)


def test_the_per_die_yield_matches_the_registry_model_it_is_compared_against() -> None:
    """The comparison in the document is only like-for-like if the per-die models agree.

    ThermoDSE writes `(1 + A_cm2 * D0 / alpha)^(-alpha)`; the transcription writes
    `(1 + D0/100 * A_mm2 / alpha)^(-alpha)`. Those are the same expression, and a divergence would
    silently make every cross-model statement in the document invalid.
    """

    for area_mm2 in (10.0, 57.0, 143.0, 300.0):
        registry = (1.0 + (area_mm2 / 100.0) * DEFECT_DENSITY_PER_CM2 / CRITICAL_LEVEL) ** (
            -CRITICAL_LEVEL
        )
        assert die_yield(area_mm2) == pytest.approx(registry, rel=1e-12)


def test_gross_die_per_wafer_matches_hand_computation_including_scribe_and_edge_loss() -> None:
    """The wafer-utilisation term the proxy omitted, written out independently."""

    area = 100.0
    chip = area + 2.0 * SCRIBE_LANE_MM * math.sqrt(area) + SCRIBE_LANE_MM ** 2
    expected = (
        math.pi * (WAFER_DIAMETER_MM / 2.0 - EDGE_LOSS_MM) ** 2 / chip
        - math.pi * (WAFER_DIAMETER_MM - 2.0 * EDGE_LOSS_MM) / math.sqrt(2.0 * chip)
    )
    assert dies_per_wafer(area) == pytest.approx(expected, rel=1e-12)
    assert 500.0 < dies_per_wafer(100.0) < 700.0, "a 100 mm^2 die on a 300 mm wafer"


def test_smaller_dies_pay_proportionally_more_scribe_and_the_edge_term_pulls_the_other_way() -> None:
    """Two opposing wafer-utilisation effects, asserted separately because the NET sign surprises.

    The first version of this test asserted that four 50 mm^2 dies come out of a wafer less
    efficiently than one 200 mm^2 die. That is false for this model at these sizes -- measured,
    1160.7 against 4 x 276.2 = 1104.8 -- because the edge-loss subtraction penalises a LARGE die
    more than the extra scribe penalises a small one. The code was faithful and the assertion was
    wrong, so each effect is now checked on its own rather than through a net quantity whose sign
    depends on the size regime.
    """

    def scribe_overhead(area):
        return (area + 2.0 * SCRIBE_LANE_MM * math.sqrt(area) + SCRIBE_LANE_MM ** 2) / area - 1.0

    assert scribe_overhead(50.0) > scribe_overhead(200.0), (
        "the scribe lane is a fixed width, so it must cost a smaller die a larger fraction"
    )
    assert scribe_overhead(50.0) == pytest.approx(0.05743, abs=1e-4)
    assert scribe_overhead(200.0) == pytest.approx(0.02849, abs=1e-4)

    # And the net, recorded rather than assumed, so a change of regime is visible as a failure.
    assert dies_per_wafer(50.0) > 4.0 * dies_per_wafer(200.0)


def test_every_count_dependent_term_grows_when_a_die_is_split() -> None:
    """The three terms the proxy lacked, each checked to move in the direction claimed."""

    whole = recurring_cost([200.0])
    quartered = recurring_cost([50.0] * 4)

    assert quartered["chips"] == 4
    assert quartered["assembly_loss_multiplier"] > whole["assembly_loss_multiplier"]
    # A single-chip package still carries ONE bond to the substrate in this model, so its loss term
    # is `1/y - 1` rather than zero. An earlier version of this test asserted zero; the model is
    # faithful to the published flow and the assertion was wrong.
    assert whole["cost_defect_package"] > 0.0
    assert quartered["cost_defect_package"] > whole["cost_defect_package"]
    assert quartered["cost_wasted_chips"] > whole["cost_wasted_chips"]
    # ... while the term that motivates cutting moves the other way.
    assert quartered["cost_defect_chips"] < whole["cost_defect_chips"], (
        "splitting must reduce the yield-loss cost, or there is no trade to study"
    )


def test_assembly_loss_compounds_geometrically_in_the_chip_count() -> None:
    for chips in (1, 2, 4, 8):
        cost = recurring_cost([50.0] * chips)
        assert cost["assembly_loss_multiplier"] == pytest.approx(
            1.0 / OS_BONDING_YIELD ** chips - 1.0
        )


def test_the_total_is_the_sum_of_the_reported_terms() -> None:
    """A total that does not equal its own breakdown makes every attribution unreadable."""

    cost = recurring_cost([80.0, 80.0])
    assert cost["recurring_total"] == pytest.approx(
        cost["cost_raw_chips"] + cost["cost_defect_chips"] + cost["cost_raw_package"]
        + cost["cost_defect_package"] + cost["cost_wasted_chips"]
    )


def test_a_lower_bonding_yield_only_ever_raises_the_cost() -> None:
    previous = None
    for bonding in (1.0, 0.99, 0.97, 0.94, 0.90):
        total = recurring_cost([50.0] * 4, bonding_yield=bonding)["recurring_total"]
        if previous is not None:
            assert total > previous
        previous = total


def test_a_bonding_yield_above_one_is_refused() -> None:
    """It is a probability. Accepting 1.02 would let a sensitivity sweep leave physical reality."""

    with pytest.raises(ValueError):
        recurring_cost([50.0], bonding_yield=1.02)


def test_degenerate_geometry_and_factors_are_refused() -> None:
    for areas in ([], [0.0], [-5.0], [float("nan")], [float("inf")]):
        with pytest.raises(ValueError):
            recurring_cost(areas)
    for name in ("defect_density_per_cm2", "wafer_cost_usd", "area_scale",
                 "bump_cost_factor", "re_cost_factor"):
        for bad in (0.0, -1.0, float("nan")):
            with pytest.raises(ValueError):
                recurring_cost([50.0], **{name: bad})


def test_a_die_too_large_for_the_wafer_is_refused_not_priced() -> None:
    """`dies_per_wafer` goes negative before it goes to zero; a negative divisor would print a
    negative cost and read as the cheapest option in the sweep."""

    assert dies_per_wafer(70000.0) <= 0.0, "the fixture no longer exceeds the wafer"
    with pytest.raises(ValueError):
        recurring_cost([70000.0])
