"""Solution verification must refuse more often than it reports, and name what it establishes.

The module replaces a safety factor invented in this project (`2 * |f_N - f_2N|`) with the standard
three-grid Grid Convergence Index. What makes it better is the REFUSAL: a solution whose observed
order is implausible, whose successive differences oscillate, or whose differences degenerate gets
no error bar, where the previous estimator gave every solution the same multiplier.

Three corrections from peer review are pinned here because each was a real misreading:

* the verdict is `PLAUSIBLE_ORDER`, not `ASYMPTOTIC`. Three grids fit `f_0 + C h^p` exactly, leaving
  no residual with which to TEST the model, so a plausible order is consistent with asymptotic
  behaviour rather than evidence of it.
* three IDENTICAL values are `DEGENERATE`, not converged. They are equally consistent with a solver
  tolerance floor, a quantised output, or a duplicated input.
* a vanishing fine value is a CENTRAL case, not an error. `beta* = 0` is what a nominally infeasible
  design returns and this project produces those; the absolute index is defined there even though
  the relative one is not.
"""

from __future__ import annotations

import math

import pytest

from CertiTherm.solution_verification import (
    ASYMPTOTIC_ORDER_BAND,
    FORMAL_ORDER,
    ORDER_FLOOR,
    SAFETY_FACTOR_THREE_GRID,
    verify,
)

# Measured, `beta*_reject` at grid64 / grid128 / grid256, from the convergence study.
_MEASURED = {
    "heldout_radii_09/resnet50": (0.10236, 0.07304, 0.06229, "PLAUSIBLE_ORDER"),
    "heldout_radii_10/resnet50": (0.10507, 0.07789, 0.06454, "PLAUSIBLE_ORDER"),
    "heldout_radii_09/transformer": (0.02497, 0.01677, 0.01374, "PLAUSIBLE_ORDER"),
    "heldout_radii_07/resnet50": (0.15307, 0.13444, 0.13391, "IMPLAUSIBLE_ORDER"),
    "heldout_radii_06/resnet50": (0.12584, 0.12473, 0.11847, "IMPLAUSIBLE_ORDER"),
    "heldout_radii_11/resnet50": (0.08074, 0.07056, 0.07781, "OSCILLATORY"),
    "heldout_radii_06/transformer": (0.01487, 0.01500, 0.01362, "OSCILLATORY"),
}


@pytest.mark.parametrize("case", sorted(_MEASURED), ids=lambda c: c.replace("/", "_"))
def test_the_measured_registry_is_classified_as_observed(case) -> None:
    """Consistency with the observed classification, which is what a regression would break.

    These fixtures do not establish that the labels are CORRECT -- correctness of a convergence
    verdict is not decidable from three numbers, which is the module's whole point. They pin that
    the classifier keeps saying about real data what it said when the data was examined.
    """

    coarse, medium, fine, expected = _MEASURED[case]
    result = verify(coarse, medium, fine)
    assert result["verdict"] == expected, (
        f"{case}: {coarse}, {medium}, {fine} classified {result['verdict']}, expected {expected} "
        f"({result['note']})"
    )
    if expected == "PLAUSIBLE_ORDER":
        assert result["uncertainty"] is not None and result["uncertainty"] > 0.0
        assert result["extrapolated"] is not None
    else:
        assert result["uncertainty"] is None, (
            "a refused solution must get no error bar; giving it one is the same class of mistake "
            "as a fabricated verdict"
        )
        assert result["extrapolated"] is None


def test_a_textbook_second_order_sequence_recovers_its_own_order_and_extrapolate() -> None:
    """`f_h = f_exact + C h^2` at h, h/2, h/4 must give back p = 2 and f_exact."""

    exact, c = 300.0, 8.0
    coarse, medium, fine = (exact + c * h ** 2 for h in (1.0, 0.5, 0.25))
    result = verify(coarse, medium, fine)

    assert result["verdict"] == "PLAUSIBLE_ORDER"
    assert result["observed_order"] == pytest.approx(2.0, abs=1e-9)
    assert result["extrapolated"] == pytest.approx(exact, abs=1e-9)
    assert result["uncertainty"] == pytest.approx(
        SAFETY_FACTOR_THREE_GRID * abs(fine - medium) / 3.0
    )
    assert result["relative_uncertainty"] == pytest.approx(result["uncertainty"] / abs(fine))


def test_a_first_order_sequence_gets_a_larger_bar_than_a_second_order_one() -> None:
    exact, c = 300.0, 8.0
    first = verify(*(exact + c * h for h in (1.0, 0.5, 0.25)))
    second = verify(*(exact + c * h ** 2 for h in (1.0, 0.5, 0.25)))
    assert first["observed_order"] == pytest.approx(1.0, abs=1e-9)
    assert first["relative_uncertainty"] > second["relative_uncertainty"]


def test_an_oscillating_sequence_is_refused_rather_than_extrapolated() -> None:
    result = verify(300.0, 302.0, 301.0)
    assert result["verdict"] == "OSCILLATORY"
    assert result["uncertainty"] is None and result["observed_order"] is None
    assert "opposite signs" in result["note"]


def test_an_implausible_observed_order_is_refused_without_claiming_non_convergence() -> None:
    """A high observed order may be cancellation, superconvergence, or the solver noise floor.

    Refusing is conservative; the note must not assert that the solution is diverging, which three
    points cannot establish either.
    """

    low, high = ASYMPTOTIC_ORDER_BAND
    result = verify(0.15307, 0.13444, 0.13391)
    assert result["verdict"] == "IMPLAUSIBLE_ORDER"
    assert result["observed_order"] > high
    assert result["uncertainty"] is None
    assert "UNKNOWN" in result["note"]


def test_an_order_above_the_formal_one_but_inside_the_band_is_clamped_and_still_reported() -> None:
    """The clamp binds only from above -- below the band the verdict is a refusal, not a clamp.

    `GCI` scales as `1/(r^p - 1)`, so clamping DOWN to the formal order enlarges the bar, which is
    the conservative direction. An earlier test claimed to exercise the clamp using `p = 1.5`, which
    exercises neither end.
    """

    exact, c = 300.0, 8.0
    result = verify(*(exact + c * h ** 2.3 for h in (1.0, 0.5, 0.25)))
    assert result["observed_order"] == pytest.approx(2.3, abs=1e-9)
    assert result["order_used"] == pytest.approx(FORMAL_ORDER)
    assert result["verdict"] == "PLAUSIBLE_ORDER"

    unclamped = verify(*(exact + c * h ** 2.0 for h in (1.0, 0.5, 0.25)))
    assert result["uncertainty"] > 0 and unclamped["order_used"] == pytest.approx(2.0)


def test_a_vanishing_fine_value_gets_an_ABSOLUTE_bar_because_it_is_a_central_case() -> None:
    """`beta* = 0` is a nominally infeasible design, which this project produces by the dozen.

    An earlier version refused it, which made the API unable to describe its own most important
    outcome. The relative index is undefined at zero; the absolute one is not.
    """

    # (0.12, 0.04, 0.0): successive differences -0.08 then -0.04, ratio 2, so p = 1 exactly. The
    # first attempt used (0.08, 0.04, 0.0), whose ratio is 1 and whose order is therefore 0 -- below
    # the band, correctly refused. The fixture was wrong, not the classifier.
    result = verify(0.12, 0.04, 0.0)
    assert result["verdict"] == "PLAUSIBLE_ORDER"
    assert result["uncertainty"] is not None and result["uncertainty"] > 0.0
    assert result["relative_uncertainty"] is None
    assert result["extrapolated"] is not None


def test_identical_solutions_on_all_three_grids_are_DEGENERATE_not_converged() -> None:
    """Three equal floats are consistent with a tolerance floor or a duplicated input."""

    result = verify(300.0, 300.0, 300.0)
    assert result["verdict"] == "DEGENERATE"
    assert result["uncertainty"] is None and result["extrapolated"] is None
    assert verify(0.0, 0.0, 0.0)["verdict"] == "DEGENERATE", (
        "the all-zero case must reach the degenerate branch rather than tripping an earlier guard"
    )


def test_one_vanishing_difference_is_DEGENERATE_not_OSCILLATORY() -> None:
    """A zero difference is not opposite signs, and the observed order is undefined either way."""

    for triple in ((310.0, 300.0, 300.0), (300.0, 300.0, 310.0)):
        result = verify(*triple)
        assert result["verdict"] == "DEGENERATE", triple
        assert result["uncertainty"] is None
        assert "exactly zero" in result["note"]


def test_non_finite_inputs_and_a_degenerate_refinement_ratio_are_refused() -> None:
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            verify(bad, 300.0, 300.5)
    for ratio in (1.0, 0.5, 0.0, -2.0, float("nan")):
        with pytest.raises(ValueError):
            verify(310.0, 305.0, 302.0, refinement_ratio=ratio)


def test_the_order_floor_is_the_band_edge_so_slow_convergence_refuses_rather_than_clamps() -> None:
    exact, c = 300.0, 8.0
    result = verify(*(exact + c * h ** 0.2 for h in (1.0, 0.5, 0.25)))
    assert result["observed_order"] < ORDER_FLOOR
    assert result["verdict"] == "IMPLAUSIBLE_ORDER"
    assert result["uncertainty"] is None


def test_the_asymptotic_ratio_is_reported_but_does_not_gate() -> None:
    """Tautological with three grids and an UNCLAMPED observed order, so it cannot be the criterion.

    Substituting `p = ln(e_cm/e_mf)/ln(r)` makes the error ratio cancel, leaving `|f_fine/f_med|`.
    An earlier version gated on it and refused a textbook-clean case whose only sin was moving 15 %
    between grids.
    """

    coarse, medium, fine = _MEASURED["heldout_radii_09/resnet50"][:3]
    result = verify(coarse, medium, fine)
    assert result["verdict"] == "PLAUSIBLE_ORDER"
    assert result["order_used"] == pytest.approx(result["observed_order"]), (
        "the fixture must be unclamped or the tautology does not hold"
    )
    assert result["asymptotic_ratio"] == pytest.approx(abs(fine / medium), rel=1e-9)
    assert not math.isclose(result["asymptotic_ratio"], 1.0, abs_tol=0.10), (
        "the fixture no longer exercises the case the tautological check would have refused"
    )
