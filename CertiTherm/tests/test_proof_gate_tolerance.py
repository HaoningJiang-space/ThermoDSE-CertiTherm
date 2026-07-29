"""A proof gate must refuse an unusable tolerance, not widen every constraint to infinity.

`verify_shared_collision_batch` expands every bound and right-hand side by `tolerance`
before checking a proposed primal. With `tolerance = inf` every check passes vacuously and
the gate returns `FEASIBLE` with the reason "all primal constraints verified" -- a
fabricated acceptance, which the fail-closed contract forbids. Its scalar sibling
`verify_feasible_point` already refused the same input, so the batch path was the only way
to obtain it.

These tests pin the refusal AND the asymmetry that produced the bug: the two verifiers must
agree about which tolerances are usable, because the batch one exists only as a vectorised
form of the other.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from CertiTherm.collision_proof import (
    LinearFeasibilitySystem,
    ProposalKind,
    verify_feasible_point,
    verify_shared_collision_batch,
)

UNUSABLE = [float("inf"), float("-inf"), float("nan"), -1.0]


def _system(n: int = 2) -> LinearFeasibilitySystem:
    """A unit box with one `x0 + x1 <= 1` row: small, and violated by a wild point."""

    return LinearFeasibilitySystem(
        a_ub=np.ones((1, n)),
        b_ub=np.array([1.0]),
        a_eq=np.zeros((0, n)),
        b_eq=np.zeros(0),
        lower=np.zeros(n),
        upper=np.ones(n),
    )


def _batch_arguments(system: LinearFeasibilitySystem, primal_value: float):
    """One FEASIBLE-kind cell whose proposed primal sits at `primal_value` in both worlds."""

    cells, n = 1, system.variables
    return (
        system,
        np.array([[1.0, 0.0]]),          # spec_rows
        np.array([0.0]),                 # spec_rhs
        np.array([1]),                   # kinds: 1 == FEASIBLE proposal
        np.full((n, cells), primal_value),
        np.zeros((system.b_ub.size, cells)),
        np.zeros(cells),
        np.zeros((system.b_eq.size, cells)),
    )


@pytest.mark.parametrize("tolerance", UNUSABLE)
def test_batch_gate_refuses_an_unusable_tolerance(tolerance: float) -> None:
    system = _system()
    with pytest.raises(ValueError, match="finite and non-negative"):
        verify_shared_collision_batch(*_batch_arguments(system, 1e6), tolerance)


@pytest.mark.parametrize("tolerance", UNUSABLE)
def test_both_verifiers_agree_on_which_tolerances_are_usable(tolerance: float) -> None:
    """The batch gate is a vectorised `verify_feasible_point`; a disagreement about the
    admissible domain is exactly what let the fabricated acceptance through."""

    system = _system()
    with pytest.raises(ValueError):
        verify_feasible_point(system, np.zeros(system.variables), tolerance)
    with pytest.raises(ValueError):
        verify_shared_collision_batch(*_batch_arguments(system, 0.0), tolerance)


def test_a_wildly_infeasible_point_is_still_rejected_at_a_usable_tolerance() -> None:
    """The counterexample from the bug report, at a tolerance the gate accepts.

    Without this the refusal tests above would pass against a gate that rejects everything.
    """

    system = _system()
    checks = verify_shared_collision_batch(*_batch_arguments(system, 1e6), 1e-9)
    assert len(checks) == 1
    assert not checks[0].accepted
    assert checks[0].kind is ProposalKind.UNKNOWN


def test_a_genuinely_feasible_point_is_still_accepted() -> None:
    """And that it does not reject everything: the gate must still certify a real point."""

    system = _system()
    checks = verify_shared_collision_batch(*_batch_arguments(system, 0.0), 1e-9)
    assert checks[0].accepted
    assert checks[0].kind is ProposalKind.FEASIBLE


def test_the_expansion_is_what_makes_an_infinite_tolerance_unusable() -> None:
    """Document the mechanism the guard defends against, so the guard is not mistaken for
    mere input hygiene: widening a finite bound by infinity destroys the bound."""

    assert math.isinf(1.0 + float("inf"))
    assert not math.isfinite(float("inf"))
