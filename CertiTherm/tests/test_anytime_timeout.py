"""Regression: anytime evidence must survive a budget timeout.

These tests used to induce the timeout by racing a 0.35-0.4 s SIGALRM against the solver. That
is a wall-clock race, and it lost on a fast CI runner: the 10-dimensional instance FINISHED
inside the budget, so `test_timeout_preserves_anytime_evidence` returned OPTIMAL and the suite
went red on GitHub while passing on moe-server. A flaky test is worse than none here -- this file
guards the fail-closed path that preserves evidence when a budget expires, and a test that can
pass or fail on machine speed cannot guard anything.

The timeout is now injected deterministically: the separation oracle raises `TimeoutError` on a
chosen call, so the budget expires at a known iteration on every machine.

Scope, stated precisely because the first draft overstated it: this exercises the same
fail-closed EXCEPTION HANDLER, not identical interruption semantics. A real signal can arrive
between arbitrary bytecodes, including partway through a state update; this injection happens at
a clean call boundary. Native solver `time_limit` translation, signal-handler installation and
restoration, and worker-pool exception propagation are separate mechanisms and are not covered
here.
"""
from __future__ import annotations
import numpy as np
import pytest

import CertiTherm.synthesis as synthesis
from CertiTherm.core import CandidateSpace, PowerPolytope, ThermalFamily, MeasurementAction
from CertiTherm.synthesis import synthesize_minimum_observation, synthesize_ordered_query


def _hard_instance(n: int = 10):
    pol = PowerPolytope.box_with_total(np.zeros(n), np.ones(n), 1.0)
    resp = np.array([[np.eye(n)[i] * 2.0 for i in range(n)]])
    th = ThermalFamily(("b",), resp, np.array([0.0]), 1.0)
    return pol, th


# Modest cap: enough to reach the injected call, small enough that a refactor which bypasses the
# seam fails quickly instead of masquerading as the expected timeout after a very long run.
_ITERATION_CAP = 50

_ORIGINAL_COLLISIONS = synthesis._collisions


class _Injection:
    """Records that the fault actually fired, so a test cannot pass by never timing out."""

    def __init__(self, nth: int) -> None:
        self.nth, self.calls, self.fired = nth, 0, 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        # `==`, not `>=`: the helper claims to raise on the nth call. Raising on every later
        # call too would hide a swallow-and-continue in the loop instead of exposing it.
        if self.calls == self.nth:
            self.fired += 1
            raise TimeoutError("test budget exhausted")
        return _ORIGINAL_COLLISIONS(*args, **kwargs)


def _timeout_on_call(monkeypatch, nth: int) -> _Injection:
    """Make the separation oracle raise TimeoutError on its `nth` call.

    `nth = 3` lets two iterations complete first, so witnesses and a lower bound have genuinely
    accumulated before the budget expires. Always wraps the ORIGINAL callable, so a test may
    install a fresh injection more than once. Returns the controller: every test must assert it
    fired, otherwise "no timeout happened" would look like success.
    """
    injection = _Injection(nth)
    monkeypatch.setattr(synthesis, "_collisions", injection)
    return injection


def test_timeout_preserves_anytime_evidence(monkeypatch) -> None:
    """A budget timeout previously discarded the entire result."""
    pol, th = _hard_instance()
    acts = tuple(
        MeasurementAction(f"p{i}", np.eye(10)[i], cost=float(1 + i % 4)) for i in range(10)
    )
    injection = _timeout_on_call(monkeypatch, 3)
    plan = synthesize_minimum_observation(
        pol, th, acts, max_iterations=_ITERATION_CAP, separation_workers=1
    )
    assert injection.fired == 1, "the injected timeout never fired; nothing was tested"
    assert plan.status == "UNRESOLVED"
    # Each of these is asserted STRICTLY, because the failure being guarded is "the evidence was
    # discarded" and a discarded field comes back as 0, None or empty. `lower_bound >= 0.0` and
    # `candidate_covered_cuts is not None` both accepted exactly that: the real values here are
    # 1.0 and 2, so a reset to zero would have passed the old assertions.
    assert plan.iterations >= 2, "iteration count was discarded"
    assert len(plan.witnesses) >= 1, "accumulated witnesses were discarded"
    assert plan.lower_bound is not None, "the anytime lower bound was discarded"
    assert plan.lower_bound > 0.0, "a zero bound is what a discarded bound looks like"
    assert plan.candidate_action_ids, "the working cover was discarded"
    assert plan.candidate_covered_cuts, "an empty covered-cut set covers nothing"
    # The candidate is explicitly NOT a certified plan or an upper bound.
    assert plan.selected_action_ids == ()
    assert plan.exact_cost is None
    assert plan.optimality_gap is None


def test_timeout_on_ordered_query_still_reports_a_bound(monkeypatch) -> None:
    """The experiment driver calls this path, not the single-polytope one."""
    pol, th = _hard_instance()
    cands = tuple(CandidateSpace(f"c{k}", pol, th) for k in range(2))
    acts = tuple(
        MeasurementAction(
            f"c{k}-p{i}", np.eye(10)[i], cost=float(1 + i % 4), candidate_id=f"c{k}"
        )
        for k in range(2)
        for i in range(10)
    )
    injection = _timeout_on_call(monkeypatch, 3)
    plan = synthesize_ordered_query(
        cands, acts, max_iterations=_ITERATION_CAP, separation_workers=1
    )
    assert injection.fired == 1, "the injected timeout never fired; nothing was tested"
    assert plan.lower_bound is not None, "query-level bound was discarded"
    assert plan.status == "UNRESOLVED"
    assert plan.plan_validity == "UNRESOLVED"
    assert plan.cost_optimality == "UNKNOWN"


def test_orthogonal_dimensions_agree_with_status() -> None:
    pol = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    th = ThermalFamily(("b",), np.array([[[2.0, 0.0]]]), np.array([0.0]), 1.0)
    acts = (
        MeasurementAction("p0", np.array([1.0, 0.0])),
        MeasurementAction("p1", np.array([0.0, 1.0])),
    )
    plan = synthesize_minimum_observation(pol, th, acts)
    assert plan.status == "OPTIMAL"
    assert plan.plan_validity == "CERTIFIED"
    assert plan.cost_optimality in ("PROVEN_SELF_VERIFIABLE", "PROVEN_SOLVER_ATTESTED")


def test_query_bound_does_not_double_count_the_failing_candidate(monkeypatch) -> None:
    """A lower bound above the true optimum would certify a suboptimal plan.

    The failing candidate's local bound is accumulated before its status is examined; adding it
    again on the failure path counted it twice.

    This needs an EXACT oracle. The previous assertion was only
    `query_bound <= full_library_cost`, and with a full library of 46.0 against a candidate-local
    bound of order 1-4, a doubled bound of order 2-8 passes it comfortably -- so the test named
    for double counting could not detect double counting. Instead: run candidate 0 alone under
    the identical injection to obtain its local bound `b`, then require the query bound to equal
    `b` exactly, not `2b`.
    """
    pol, th = _hard_instance()
    cands = tuple(CandidateSpace(f"c{k}", pol, th) for k in range(2))
    acts = tuple(
        MeasurementAction(
            f"c{k}-p{i}", np.eye(10)[i], cost=float(1 + i % 4), candidate_id=f"c{k}"
        )
        for k in range(2)
        for i in range(10)
    )

    # The query walks candidates in order, so call 3 lands inside candidate c0. Reproduce c0
    # alone with the same injection: its local bound is the only thing the query can report.
    c0_actions = tuple(a for a in acts if a.candidate_id == "c0")
    local_injection = _timeout_on_call(monkeypatch, 3)
    local = synthesize_minimum_observation(
        pol, th, c0_actions, max_iterations=_ITERATION_CAP, separation_workers=1
    )
    assert local_injection.fired == 1
    assert local.status == "UNRESOLVED"
    b = local.lower_bound
    assert b is not None
    # Non-degeneracy: if b were 0 then b == 2b and this oracle would prove nothing. It is 1.0
    # for this fixture; assert it stays positive so the test cannot quietly go vacuous.
    assert b > 0, "a zero local bound makes the doubled and correct values indistinguishable"

    query_injection = _timeout_on_call(monkeypatch, 3)
    plan = synthesize_ordered_query(
        cands, acts, max_iterations=_ITERATION_CAP, separation_workers=1
    )
    assert query_injection.fired == 1, "the injected timeout never fired; nothing was tested"
    assert plan.status == "UNRESOLVED"
    assert plan.lower_bound is not None

    assert plan.lower_bound == pytest.approx(b), (
        f"query lower bound {plan.lower_bound} != the failing candidate's own bound {b}. "
        f"Doubling it would give {2 * b}, which the old `<= full library` assertion accepted."
    )
    # and the invariant the old assertion checked, kept as a weaker backstop
    assert plan.lower_bound <= sum(a.cost for a in acts)


def test_the_injected_timeout_lands_after_real_progress(monkeypatch) -> None:
    """The injection must not fire before any work happens, or the evidence assertions would be
    checking that nothing survived nothing."""
    pol, th = _hard_instance()
    acts = tuple(
        MeasurementAction(f"p{i}", np.eye(10)[i], cost=float(1 + i % 4)) for i in range(10)
    )
    injection = _timeout_on_call(monkeypatch, 3)
    plan = synthesize_minimum_observation(
        pol, th, acts, max_iterations=_ITERATION_CAP, separation_workers=1
    )
    assert injection.fired == 1 and injection.calls == 3
    assert plan.status == "UNRESOLVED"
    assert plan.iterations >= 2, "the timeout fired before two iterations completed"
    assert len(plan.witnesses) >= 1, "no witness accumulated before the budget expired"
    assert plan.lower_bound is not None and plan.lower_bound > 0
