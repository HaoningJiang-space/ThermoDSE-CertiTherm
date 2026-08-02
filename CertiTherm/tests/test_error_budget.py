"""The two sides use the same measurement in opposite directions, and that is the whole point."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.error_budget import ErrorBudget

_U = np.array([0.5, -0.2, 0.0, 1.1])


def test_safe_clamps_a_negative_bound_because_disagreement_must_not_add_slack() -> None:
    budget = ErrorBudget(linearisation_k=0.01, model_form_upper_k=_U)
    assert np.allclose(budget.safe_allowance_k(), [0.51, 0.01, 0.01, 1.11])


def test_reject_does_NOT_clamp_because_a_negative_bound_must_raise_the_threshold() -> None:
    """`T_model >= L + margin - u_j`. With `u_j < 0` that is a STRICTER test, and clamping it to
    zero would lower the threshold and admit worlds that are not actually unsafe."""

    budget = ErrorBudget(linearisation_k=0.01, model_form_upper_k=_U)
    assert np.allclose(budget.reject_allowance_k(), [0.51, -0.19, 0.01, 1.11])
    assert budget.reject_allowance_k()[1] < budget.safe_allowance_k()[1]


def test_the_linearisation_term_stays_a_non_negative_symmetric_magnitude() -> None:
    """Its meaning is unchanged; overloading it is what this module exists to stop."""

    with pytest.raises(ValueError, match="symmetric magnitude"):
        ErrorBudget(linearisation_k=-0.01)
    with pytest.raises(ValueError, match="symmetric magnitude"):
        ErrorBudget(linearisation_k=float("nan"))


def test_a_signed_per_row_bound_is_kept_signed() -> None:
    """Requiring non-negativity here would silently discard 26 measured rows."""

    budget = ErrorBudget(linearisation_k=0.0, model_form_upper_k=np.array([-0.39, 0.7]))
    assert budget.model_form_upper_k[0] == -0.39


def test_upper_and_lower_must_cover_the_same_rows() -> None:
    with pytest.raises(ValueError, match="same rows"):
        ErrorBudget(linearisation_k=0.0, model_form_upper_k=np.zeros(3),
                    model_form_lower_k=np.zeros(4))


def test_budgeting_without_a_model_form_bound_refuses_rather_than_assuming_zero() -> None:
    """Assuming zero would certify against a model whose disagreement was never measured."""

    for method in ("safe_allowance_k", "reject_allowance_k"):
        with pytest.raises(ValueError, match="no model-form upper bound"):
            getattr(ErrorBudget(linearisation_k=0.01), method)()
