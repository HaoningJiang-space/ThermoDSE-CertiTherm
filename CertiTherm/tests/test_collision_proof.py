import numpy as np
import pytest

from CertiTherm.collision_proof import (
    CollisionProposal,
    LinearFeasibilitySystem,
    ProposalKind,
    verify_feasible_point,
    verify_infeasible_ray,
    verify_proposal,
)


def _system(a_ub, b_ub, *, a_eq=(), b_eq=(), bounds=((-2.0, 2.0),)):
    n = len(bounds)
    return LinearFeasibilitySystem(
        np.asarray(a_ub, dtype=float).reshape(-1, n),
        np.asarray(b_ub, dtype=float),
        np.asarray(a_eq, dtype=float).reshape(-1, n),
        np.asarray(b_eq, dtype=float),
        np.asarray([bound[0] for bound in bounds]),
        np.asarray([bound[1] for bound in bounds]),
    )


def test_feasible_point_is_independently_accepted() -> None:
    system = _system([[1.0], [-1.0]], [1.0, 0.0], a_eq=[[2.0]], b_eq=[1.0])
    check = verify_feasible_point(system, [0.5], 1e-10)
    assert check.accepted and check.kind == ProposalKind.FEASIBLE


@pytest.mark.parametrize("point", ([1.5], [-0.1], [float("nan")]))
def test_bad_feasible_point_fails_closed(point) -> None:
    system = _system([[1.0], [-1.0]], [1.0, 0.0])
    assert not verify_feasible_point(system, point, 1e-10).accepted


def test_residual_free_farkas_ray_is_accepted() -> None:
    # x <= 0 and x >= 1 cannot both hold. y=(1,1) gives A.T y=0,
    # b.T y=-1, so the certified contradiction has unit slack.
    system = _system([[1.0], [-1.0]], [0.0, -1.0])
    check = verify_infeasible_ray(system, [1.0, 1.0])
    assert check.accepted and check.kind == ProposalKind.INFEASIBLE
    assert check.certified_slack is not None and check.certified_slack > 0.99


def test_residual_aware_ray_uses_box_bounds() -> None:
    # x <= -1 is impossible over [0, 2]. The non-zero residual is handled by
    # min_{x in [0,2]} x = 0 > -1.
    system = _system([[1.0]], [-1.0], bounds=((0.0, 2.0),))
    assert verify_infeasible_ray(system, [3.0]).accepted


@pytest.mark.parametrize("ray", ([1.0, 0.0], [-1.0, -1.0], [0.0, 0.0]))
def test_invalid_or_nonproving_ray_fails_closed(ray) -> None:
    system = _system([[1.0], [-1.0]], [0.0, -1.0])
    assert not verify_infeasible_ray(system, ray).accepted


def test_equalities_are_available_to_infeasibility_certificate() -> None:
    # x = 0 conflicts with x >= 1. Canonical ray order is
    # [inequalities, +equalities, -equalities].
    system = _system([[-1.0]], [-1.0], a_eq=[[1.0]], b_eq=[0.0])
    check = verify_infeasible_ray(system, [1.0, 1.0, 0.0])
    assert check.accepted


def test_unknown_and_tampered_proposals_never_become_verdicts() -> None:
    system = _system([[1.0]], [0.0])
    unknown = CollisionProposal(ProposalKind.UNKNOWN)
    tampered = CollisionProposal(ProposalKind.FEASIBLE, primal=np.array([1.0]))
    assert not verify_proposal(system, unknown, 1e-10).accepted
    assert not verify_proposal(system, tampered, 1e-10).accepted


def test_malformed_system_is_rejected_before_verification() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        LinearFeasibilitySystem(
            np.ones((2, 2)),
            np.ones(1),
            np.empty((0, 2)),
            np.empty(0),
            np.zeros(2),
            np.ones(2),
        )
