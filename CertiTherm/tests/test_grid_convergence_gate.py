"""The gate must refuse the operator that the frozen contract admitted, and admit the ones it should.

`docs/GRID_CONVERGENCE_FINDING.md` measured a `grid128-avg` operator that passed the 0.01 K linearity
contract with a worst error of 0.0027 K while disagreeing with a 4x finer grid by 17 % in the
relocation radius it induced. These tests pin that the new gate catches that case, using a replay
stub rather than HotSpot so they run anywhere -- which is also why `grid_drift` takes the replay as
an argument instead of calling the binary itself.
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.grid_convergence_gate import (
    GRID_DRIFT_LIMIT_K,
    gate,
    grid_drift,
    reference_model_id,
    refined_model_id,
)

_VECTORS = [
    ("placed", np.array([1.0, 2.0, 3.0])),
    ("bounded-uniform", np.array([2.0, 2.0, 2.0])),
]


def _replay(fields):
    """A stub returning a declared per-block field for each model id."""

    def inner(model_id, power):
        del power
        return np.asarray(fields[model_id], dtype=float)

    return inner


def test_the_refinement_of_a_grid_id_doubles_its_size() -> None:
    assert refined_model_id("grid64-avg") == "grid128-avg"
    assert refined_model_id("grid128-avg") == "grid256-avg"
    assert refined_model_id("grid256") == "grid512"


def test_a_model_without_a_refinement_parameter_is_refused_not_silently_passed() -> None:
    """`block` has no grid size. Returning it unchanged would gate it vacuously."""

    for model_id in ("block", "grid-avg", "gridN-avg", "grid0-avg"):
        with pytest.raises(ValueError):
            refined_model_id(model_id)


def test_an_operator_that_agrees_with_its_refinement_passes() -> None:
    fields = {
        "grid128-avg": [300.0, 310.0, 320.0],
        "grid256-avg": [300.01, 310.02, 320.0],
    }
    result = grid_drift(_replay(fields), "grid128-avg", _VECTORS)
    assert result["worst_drift_k"] == pytest.approx(0.02)
    assert result["refined_model_id"] == "grid256-avg"
    assert len(result["per_vector"]) == len(_VECTORS)


def test_the_measured_under_resolved_operator_is_REFUSED() -> None:
    """The case the frozen contract admitted: linear, and 17 % away from a finer grid.

    A block at 320 K under `grid128` and 316 K under `grid256` is a 4 K disagreement -- far beyond
    what a 0.01 K LINEARITY budget would ever see, because that budget never compares resolutions.
    """

    fields = {
        "grid128-avg": [300.0, 310.0, 320.0],
        "grid256-avg": [300.0, 310.0, 316.0],
    }
    verdict = gate(_replay(fields), ["grid128-avg"], _VECTORS)
    assert verdict["status"] == "REFUSED"
    assert verdict["refusals"] and "grid128-avg" in verdict["refusals"][0]
    assert verdict["measured"][0]["worst_drift_k"] == pytest.approx(4.0)


def test_block_is_MEASURED_now_and_ungated_survives_only_without_any_grid() -> None:
    """This test previously asserted the hole. `block` used to land in `ungated`; it is now gated.

    The old assertion was that a caller reading only `status` must not conclude `block` was checked.
    That was right about the danger and wrong about the remedy -- the remedy is to check it. What
    remains genuinely ungatable is a family with no grid model at all, and that case is kept.
    """

    fields = {"block": [300.0], "grid64-avg": [300.0], "grid128-avg": [300.0]}
    verdict = gate(_replay(fields), ["block", "grid64-avg"], [("placed", np.array([1.0]))])
    assert verdict["status"] == "PASS"
    assert verdict["ungated"] == [], "block must no longer escape the gate"
    assert sorted(m["model_id"] for m in verdict["measured"]) == ["block", "grid64-avg"]
    # `block` is compared against the refinement of the finest grid in the family it was given.
    assert next(m for m in verdict["measured"] if m["model_id"] == "block")[
        "refined_model_id"
    ] == "grid128-avg"

    # The one genuinely unmeasurable case: nothing to compare against.
    only_block = gate(_replay({"block": [300.0]}), ["block"], [("placed", np.array([1.0]))])
    assert only_block["ungated"] == ["block"]
    assert only_block["measured"] == []


def test_an_empty_vector_list_is_refused_rather_than_scoring_zero_drift() -> None:
    """With no vectors the loop never runs and every operator would pass at drift zero."""

    with pytest.raises(ValueError):
        grid_drift(_replay({}), "grid64-avg", [])


def test_a_non_finite_field_is_refused_rather_than_passing_the_bound() -> None:
    """`nan > limit` is False, so the value would pass the check AND be recorded as the drift."""

    fields = {"grid64-avg": [300.0, float("nan")], "grid128-avg": [300.0, 300.0]}
    with pytest.raises(ValueError):
        grid_drift(_replay(fields), "grid64-avg", [("placed", np.array([1.0, 1.0]))])


def test_a_block_count_mismatch_is_refused() -> None:
    """Two resolutions must be compared over the same blocks or the difference is meaningless."""

    fields = {"grid64-avg": [300.0, 310.0], "grid128-avg": [300.0]}
    with pytest.raises(ValueError):
        grid_drift(_replay(fields), "grid64-avg", [("placed", np.array([1.0, 1.0]))])


def test_a_non_positive_or_non_finite_limit_is_refused() -> None:
    fields = {"grid64-avg": [300.0], "grid128-avg": [300.0]}
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            gate(_replay(fields), ["grid64-avg"], [("placed", np.array([1.0]))], limit_k=bad)


def test_the_drift_limit_is_separate_from_the_linearisation_budget() -> None:
    """One bounds discretisation and gates the build; the other bounds linearity and enters the LP.

    Registering them as one number would make a change to either silently move the other, and the
    measured case is exactly why they differ: 0.0027 K of linearity error alongside kelvins of
    discretisation drift.
    """

    from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K

    assert GRID_DRIFT_LIMIT_K != MODEL_ERROR_LIMIT_K
    assert GRID_DRIFT_LIMIT_K > MODEL_ERROR_LIMIT_K


def test_the_budget_covers_both_error_sources_with_the_richardson_factor() -> None:
    """`drift` is not the operator's error; it is the gap between two refinements.

    `|T_N - T_inf| <= |T_N - T_2N| + |T_2N - T_inf|`, and the second term is unmeasured. Assuming
    at least first-order convergence bounds it by the first, hence the factor of two. The assumption
    is registered as a constant so a reader can see it and change it.
    """

    from CertiTherm.grid_convergence_gate import GRID_DRIFT_SAFETY_FACTOR, budgeted_error_k

    assert GRID_DRIFT_SAFETY_FACTOR >= 1.0, (
        "a factor below one would budget LESS than the measured gap between two refinements, "
        "which is unsound in the direction that matters"
    )
    assert budgeted_error_k(0.01, 0.250) == pytest.approx(0.01 + 2.0 * 0.250)
    assert budgeted_error_k(0.01, 0.0) == pytest.approx(0.01), (
        "a converged operator must cost exactly the linearisation budget and nothing more"
    )


def test_the_budget_is_monotone_in_the_drift_so_a_coarser_grid_is_never_cheaper() -> None:
    from CertiTherm.grid_convergence_gate import budgeted_error_k

    budgets = [budgeted_error_k(0.01, d) for d in (0.0, 0.05, 0.25, 1.41)]
    assert all(a < b for a, b in zip(budgets, budgets[1:]))


def test_a_non_finite_or_negative_input_to_the_budget_is_refused() -> None:
    """An unmeasurable error cannot be budgeted, and must not silently become zero."""

    from CertiTherm.grid_convergence_gate import budgeted_error_k

    for bad in (float("nan"), float("inf"), -0.1):
        with pytest.raises(ValueError):
            budgeted_error_k(0.01, bad)
        with pytest.raises(ValueError):
            budgeted_error_k(bad, 0.1)


def test_block_is_compared_against_the_finest_grid_rather_than_left_ungated() -> None:
    """The hole that decided a published radius.

    Measured on `6x2` cut 1x1 with the budget applied: the two charged grid operators gave
    `beta* = 5.796 %` and `6.448 %` while `block`, carrying only the 0.01 K linearisation budget,
    gave 3.757 % and set the family minimum. Charging the measured models did not protect the family
    because the binding one escaped.
    """

    family = ("block", "grid64-avg", "grid128-avg")
    assert reference_model_id("block", family) == "grid256-avg"
    assert reference_model_id("grid64-avg", family) == "grid128-avg"
    assert reference_model_id("grid128-avg", family) == "grid256-avg"


def test_a_family_with_no_grid_at_all_cannot_gate_block_and_says_so() -> None:
    with pytest.raises(ValueError):
        reference_model_id("block", ("block",))
