"""Solution verification must refuse more often than it reports, and must refuse the right cases.

The module replaces a safety factor invented in this project (`2 * |f_N - f_2N|`) with the standard
three-grid Grid Convergence Index. What makes it better is not the constant but the REFUSAL: a
solution outside the asymptotic range gets no error bar at all, where the previous estimator gave
every solution the same multiplier including two that were oscillating.

The fixtures below are built from the measured registry so the tests fail if the classification
drifts away from what was actually observed.
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
    "heldout_radii_09/resnet50": (0.10236, 0.07304, 0.06229, "ASYMPTOTIC"),
    "heldout_radii_10/resnet50": (0.10507, 0.07789, 0.06454, "ASYMPTOTIC"),
    "heldout_radii_09/transformer": (0.02497, 0.01677, 0.01374, "ASYMPTOTIC"),
    "heldout_radii_07/resnet50": (0.15307, 0.13444, 0.13391, "NOT_ASYMPTOTIC"),
    "heldout_radii_06/resnet50": (0.12584, 0.12473, 0.11847, "NOT_ASYMPTOTIC"),
    "heldout_radii_11/resnet50": (0.08074, 0.07056, 0.07781, "OSCILLATORY"),
    "heldout_radii_06/transformer": (0.01487, 0.01500, 0.01362, "OSCILLATORY"),
}


@pytest.mark.parametrize("case", sorted(_MEASURED), ids=lambda c: c.replace("/", "_"))
def test_the_measured_registry_is_classified_as_observed(case) -> None:
    coarse, medium, fine, expected = _MEASURED[case]
    result = verify(coarse, medium, fine)
    assert result["verdict"] == expected, (
        f"{case}: {coarse}, {medium}, {fine} classified {result['verdict']}, expected {expected} "
        f"({result['note']})"
    )
    if expected == "ASYMPTOTIC":
        assert result["uncertainty"] is not None and result["uncertainty"] > 0.0
        assert result["extrapolated"] is not None
    else:
        assert result["uncertainty"] is None, (
            "a solution outside the asymptotic range must get no error bar; giving it one is the "
            "same class of mistake as a fabricated verdict"
        )
        assert result["extrapolated"] is None


def test_a_textbook_second_order_sequence_recovers_its_own_order_and_extrapolate() -> None:
    """`f_h = f_exact + C h^2` sampled at h, h/2, h/4 must give back p = 2 and f_exact.

    Constructed rather than measured, so the arithmetic is checked against a known answer instead of
    against the implementation's own output.
    """

    exact, c = 300.0, 8.0
    coarse, medium, fine = (exact + c * h ** 2 for h in (1.0, 0.5, 0.25))
    result = verify(coarse, medium, fine)

    assert result["verdict"] == "ASYMPTOTIC"
    assert result["observed_order"] == pytest.approx(2.0, abs=1e-9)
    assert result["extrapolated"] == pytest.approx(exact, abs=1e-9)
    # GCI = Fs * |(f_fine - f_med)/f_fine| / (r^p - 1), with p = 2 and r = 2 so the denominator is 3.
    relative = abs((fine - medium) / fine)
    assert result["relative_uncertainty"] == pytest.approx(
        SAFETY_FACTOR_THREE_GRID * relative / 3.0
    )


def test_a_first_order_sequence_gets_a_larger_bar_than_a_second_order_one() -> None:
    """Slower convergence must cost more uncertainty, or the index is not measuring convergence."""

    exact, c = 300.0, 8.0
    first = verify(*(exact + c * h for h in (1.0, 0.5, 0.25)))
    second = verify(*(exact + c * h ** 2 for h in (1.0, 0.5, 0.25)))
    assert first["observed_order"] == pytest.approx(1.0, abs=1e-9)
    assert first["relative_uncertainty"] > second["relative_uncertainty"]


def test_an_oscillating_sequence_is_refused_rather_than_extrapolated() -> None:
    """Richardson assumes a monotone error series; opposite signs mean it does not apply."""

    result = verify(300.0, 302.0, 301.0)
    assert result["verdict"] == "OSCILLATORY"
    assert result["uncertainty"] is None and result["observed_order"] is None
    assert "opposite signs" in result["note"]


def test_an_implausible_observed_order_is_refused() -> None:
    """A finite-difference RC network cannot show order 5 in the asymptotic range.

    Measured on four architectures, so this is not a hypothetical: an order that high means the
    coarse-medium difference is anomalously large or the medium-fine one anomalously small, and in
    either case the three grids are not a refinement sequence in the asymptotic range.
    """

    low, high = ASYMPTOTIC_ORDER_BAND
    result = verify(0.15307, 0.13444, 0.13391)
    assert result["verdict"] == "NOT_ASYMPTOTIC"
    assert result["observed_order"] > high
    assert result["uncertainty"] is None


def test_the_order_used_for_the_index_is_clamped_but_the_observed_one_is_reported() -> None:
    """Clamping to the formal order is Roache's guidance AND the conservative direction here.

    `GCI` scales as `1 / (r^p - 1)`, so a smaller order gives a LARGER bar. Reporting the observed
    order alongside keeps the clamp visible.
    """

    exact, c = 300.0, 8.0
    result = verify(*(exact + c * h ** 1.5 for h in (1.0, 0.5, 0.25)))
    assert result["observed_order"] == pytest.approx(1.5, abs=1e-9)
    assert result["order_used"] == pytest.approx(1.5)
    assert ORDER_FLOOR <= result["order_used"] <= FORMAL_ORDER


def test_identical_solutions_on_all_three_grids_are_converged_not_degenerate() -> None:
    result = verify(300.0, 300.0, 300.0)
    assert result["verdict"] == "ASYMPTOTIC"
    assert result["uncertainty"] == 0.0
    assert result["extrapolated"] == 300.0


def test_two_grids_agreeing_exactly_while_the_third_differs_is_refused() -> None:
    """The observed order is undefined, and a duplicated input is far likelier than convergence."""

    with pytest.raises(ValueError):
        verify(310.0, 300.0, 300.0)


def test_non_finite_inputs_and_a_degenerate_refinement_ratio_are_refused() -> None:
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            verify(bad, 300.0, 300.5)
    for ratio in (1.0, 0.5, 0.0, -2.0, float("nan")):
        with pytest.raises(ValueError):
            verify(310.0, 305.0, 302.0, refinement_ratio=ratio)


def test_a_vanishing_fine_solution_is_refused_because_a_relative_index_is_undefined() -> None:
    """`beta*` can be exactly zero -- a nominally infeasible design -- and 0 has no relative error."""

    with pytest.raises(ValueError):
        verify(0.05, 0.02, 0.0)


def test_the_asymptotic_ratio_is_reported_but_does_not_gate() -> None:
    """It is tautological with three grids and an observed order; the module says so and the test
    pins that it is not used as the criterion.

    Substituting `p = ln(e_cm/e_mf)/ln(r)` makes the error ratio cancel exactly, leaving
    `f_fine/f_med`. An earlier version gated on it and refused a textbook-clean case whose only sin
    was moving 15 % between grids.
    """

    coarse, medium, fine = _MEASURED["heldout_radii_09/resnet50"][:3]
    result = verify(coarse, medium, fine)
    assert result["verdict"] == "ASYMPTOTIC"
    assert result["asymptotic_ratio"] == pytest.approx(fine / medium, rel=1e-9)
    assert not math.isclose(result["asymptotic_ratio"], 1.0, abs_tol=0.10), (
        "the fixture no longer exercises the case that the tautological check would have refused"
    )
