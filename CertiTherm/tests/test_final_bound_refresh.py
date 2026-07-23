"""The anytime lower bound must not be starved on timeout.

On a budget-exhausted run the whole value of the anytime path is the bound it
reports over the cuts already in hand. That final refresh solves one LP, and it
was being run under the SAME deadline that had just expired -- so it raised
"method budget exhausted before solver launch", the handler swallowed it, and
the reported bound stayed at its last power-of-two value. Measured on the
triangle experiment: a 300 s run reported 5.0 while its 3442 accumulated cuts
justified 20.1.

`override_budget` gives that one bounded solve a fresh, independent, still
fail-closed deadline.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from CertiTherm.solver_budget import budget_scope, override_budget
from CertiTherm.synthesis import _anytime_lower_bound


def _tiny_instance():
    # Two disjoint singleton cuts: the exact optimum is 2, so a successful
    # bound is unambiguous and a starved one is obviously wrong.
    costs = np.array([1.0, 1.0])
    cuts = [np.array([1.0, 0.0]), np.array([0.0, 1.0])]
    return costs, cuts


def _expire(seconds: float = 0.02) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pass


def test_expired_budget_starves_the_refresh() -> None:
    """The bug: under an already-expired budget the bound LP cannot launch.

    This documents WHY the fix is needed. `budget_scope` cannot revive the
    deadline, so the solve raises rather than returning a number.
    """

    costs, cuts = _tiny_instance()
    with budget_scope(0.001):
        _expire()
        with pytest.raises(TimeoutError):
            _anytime_lower_bound(costs, cuts)


def test_override_budget_lets_the_final_refresh_run() -> None:
    """The fix: a fresh override budget runs the same solve to completion."""

    costs, cuts = _tiny_instance()
    with budget_scope(0.001):
        _expire()
        with override_budget(30.0):
            value = _anytime_lower_bound(costs, cuts)
    assert value is not None
    assert value == pytest.approx(2.0)


def test_override_budget_ignores_the_parent_rather_than_tightening() -> None:
    """budget_scope tightens toward the parent; override must not.

    If override merely nested, the expired parent would still win and the solve
    would still starve. This pins that override installs a genuinely fresh
    deadline.
    """

    costs, cuts = _tiny_instance()
    with budget_scope(1e-4):
        _expire()
        # A nested budget_scope would keep the expired parent and still raise.
        with pytest.raises(TimeoutError):
            with budget_scope(30.0):
                _anytime_lower_bound(costs, cuts)
        # override does not.
        with override_budget(30.0):
            assert _anytime_lower_bound(costs, cuts) == pytest.approx(2.0)


def test_override_budget_is_still_fail_closed() -> None:
    """The override is bounded, not unbounded: a non-positive value is rejected."""

    with pytest.raises(ValueError):
        with override_budget(0.0):
            pass
