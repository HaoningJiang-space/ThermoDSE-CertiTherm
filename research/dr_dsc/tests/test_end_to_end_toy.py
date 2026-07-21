"""Stage B: full loop against known-answer fixtures, cross-checked against the
exact path.

Compares against `synthesize_ordered_query` (NOT
`synthesize_minimum_observation`, which is a different, older single-polytope
collision path -- comparing against that would not be like-for-like).

The original version of this file asserted only `gap >= -1e-9`, which the
degenerate "select every action" outcome satisfies trivially: it would have
printed PASS at 2x the known optimum. The assertions below pin the actual
optimum instead. UNVERIFIED until run on moe-server -- see ../README.md.
"""
from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.core import CandidateSpace, MeasurementAction, PowerPolytope, ThermalFamily
from CertiTherm.synthesis import synthesize_ordered_query

from research.dr_dsc.oracle import find_witness, local_actions
from research.dr_dsc.train import train_gate


def _thermal():
    """One model, T = 2*p0, limit 1.0 -> SAFE needs p0 < ~0.5, REJECT p0 > ~0.5."""
    return ThermalFamily(
        model_ids=("block",),
        response_k_per_w=np.array([[[2.0, 0.0]]]),
        ambient_k=np.array([0.0]),
        limit_k=1.0,
    )


def _symmetric_fixture():
    """Mirrors CertiTherm/tests/test_synthesis.py::
    test_exact_plan_reaches_unit_cost_global_limit. Both actions cost 1 and
    either one suffices (p0+p1=1 makes each determine the other)."""
    polytope = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    candidate = CandidateSpace("only", polytope, _thermal())
    actions = (
        MeasurementAction("p0", np.array([1.0, 0.0]), candidate_id="only"),
        MeasurementAction("p1", np.array([0.0, 1.0]), candidate_id="only"),
    )
    return candidate, actions


def _asymmetric_fixture():
    """Same physics, but reading block 1 costs 8x. Both actions still separate,
    so ONLY a cost-aware proposal picks the cheap one. This is the fixture that
    actually tests proposal quality -- the symmetric one cannot, because the
    two actions are interchangeable."""
    polytope = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    candidate = CandidateSpace("only", polytope, _thermal())
    actions = (
        MeasurementAction("cheap-p0", np.array([1.0, 0.0]), cost=1.0, candidate_id="only"),
        MeasurementAction("pricey-p1", np.array([0.0, 1.0]), cost=8.0, candidate_id="only"),
    )
    return candidate, actions


def test_fixture_is_not_vacuous() -> None:
    """Guard against fixture drift: the empty selection MUST admit a collision,
    otherwise every downstream 'verified' result is vacuously true and the
    whole Stage B suite silently stops testing anything."""
    candidate, actions = _symmetric_fixture()
    local = local_actions(actions, candidate)
    assert find_witness(candidate, local, ()) is not None, (
        "empty selection must NOT certify -- fixture no longer exercises the loop"
    )
    assert find_witness(candidate, local, (0,)) is None, (
        "a single action must suffice here (p0+p1=1 determines the other)"
    )


def test_local_index_convention_survives_interleaved_candidates() -> None:
    """`selected` indexes into the candidate-LOCAL action list. If a future
    refactor leaks global indices in, this catches it."""
    candidate, _ = _symmetric_fixture()
    other = CandidateSpace("other", PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0), _thermal())
    interleaved = (
        MeasurementAction("other-p0", np.array([1.0, 0.0]), candidate_id="other"),
        MeasurementAction("only-p0", np.array([1.0, 0.0]), candidate_id="only"),
        MeasurementAction("other-p1", np.array([0.0, 1.0]), candidate_id="other"),
        MeasurementAction("only-p1", np.array([0.0, 1.0]), candidate_id="only"),
    )
    local = local_actions(interleaved, candidate)
    assert [a.action_id for a in local] == ["only-p0", "only-p1"]
    # Local index 0 is "only-p0" (global index 1); it must certify on its own.
    assert find_witness(candidate, local, (0,)) is None
    assert other.candidate_id == "other"


def test_symmetric_toy_reaches_the_exact_optimum() -> None:
    candidate, actions = _symmetric_fixture()
    exact = synthesize_ordered_query((candidate,), actions)
    assert exact.status == "OPTIMAL"
    assert exact.exact_cost == 1.0

    result = train_gate(candidate, actions, max_rounds=10, steps_per_round=150)
    print(
        f"[symmetric] selected={result.selected} proxy_cost={result.proxy_cost} "
        f"exact_cost={exact.exact_cost} stop_reason={result.stop_reason} "
        f"rounds={result.training_rounds} oracle_checks={result.oracle_checks}"
    )

    assert result.state_pair_verified, f"did not converge: {result.stop_reason}"
    assert find_witness(candidate, local_actions(actions, candidate), result.selected) is None

    # The real assertion: one action suffices, so selecting both is a FAILURE,
    # not a pass. This is what the original `gap >= -1e-9` let through.
    assert len(result.selected) == 1, (
        f"expected a single action, got {result.selected} -- cost pressure is not working"
    )
    assert result.proxy_cost == exact.exact_cost


def test_asymmetric_toy_prefers_the_cheap_action() -> None:
    candidate, actions = _asymmetric_fixture()
    exact = synthesize_ordered_query((candidate,), actions)
    assert exact.status == "OPTIMAL"
    assert exact.exact_cost == 1.0, "the cost-1 action alone is optimal"

    result = train_gate(candidate, actions, max_rounds=10, steps_per_round=150)
    print(
        f"[asymmetric] selected={result.selected} proxy_cost={result.proxy_cost} "
        f"exact_cost={exact.exact_cost} stop_reason={result.stop_reason}"
    )

    assert result.state_pair_verified, f"did not converge: {result.stop_reason}"
    assert result.selected == (0,), (
        f"expected the cost-1 action (local index 0), got {result.selected}"
    )
    assert result.proxy_cost == 1.0


def test_infeasible_budget_does_not_fake_a_certificate() -> None:
    """A budget too small for any separating action must terminate WITHOUT
    claiming verification -- the fail-closed property, at prototype level."""
    candidate, actions = _asymmetric_fixture()
    result = train_gate(candidate, actions, budget=0.5, max_rounds=4, steps_per_round=50)
    print(f"[infeasible-budget] {result.selected} verified={result.state_pair_verified} "
          f"stop_reason={result.stop_reason}")
    assert result.selected == ()
    assert not result.state_pair_verified


def test_invalid_hyperparameters_are_rejected() -> None:
    candidate, actions = _symmetric_fixture()
    with pytest.raises(ValueError):
        train_gate(candidate, actions, cost_penalty=1.0)
    with pytest.raises(ValueError):
        train_gate(candidate, actions, max_rounds=0)
