"""Regression: anytime evidence must survive a budget timeout.

These tests used to induce the timeout by racing a 0.35-0.4 s SIGALRM against the solver. That
is a wall-clock race, and it lost on a fast CI runner: the 10-dimensional instance FINISHED
inside the budget, so `test_timeout_preserves_anytime_evidence` returned OPTIMAL and the suite
went red on GitHub while passing on moe-server. A flaky test is worse than none here -- this file
guards the fail-closed path that preserves evidence when a budget expires, and a test that can
pass or fail on machine speed cannot guard anything.

The timeout is now injected deterministically: the separation oracle raises `TimeoutError` on a
chosen call. That is exactly what SIGALRM would do at an arbitrary point, so the handler under
test is identical, but it happens at a known iteration on every machine.
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


def _timeout_on_call(monkeypatch, nth: int) -> None:
    """Make the separation oracle raise TimeoutError on its `nth` call.

    `nth = 3` lets two iterations complete first, so witnesses and a lower bound have genuinely
    accumulated before the budget expires -- which is what these tests are about.
    """
    real = synthesis._collisions
    calls = {"n": 0}

    def counted(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= nth:
            raise TimeoutError("test budget exhausted")
        return real(*args, **kwargs)

    monkeypatch.setattr(synthesis, "_collisions", counted)


def test_timeout_preserves_anytime_evidence(monkeypatch) -> None:
    """A budget timeout previously discarded the entire result."""
    pol, th = _hard_instance()
    acts = tuple(
        MeasurementAction(f"p{i}", np.eye(10)[i], cost=float(1 + i % 4)) for i in range(10)
    )
    _timeout_on_call(monkeypatch, 3)
    plan = synthesize_minimum_observation(
        pol, th, acts, max_iterations=10**7, separation_workers=1
    )
    assert plan.status == "UNRESOLVED"
    assert plan.iterations > 0, "iteration count was discarded"
    assert plan.witnesses, "accumulated witnesses were discarded"
    assert plan.lower_bound is not None, "the anytime lower bound was discarded"
    assert plan.lower_bound >= 0.0
    assert plan.candidate_action_ids, "the working cover was discarded"
    assert plan.candidate_covered_cuts is not None
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
    _timeout_on_call(monkeypatch, 3)
    plan = synthesize_ordered_query(
        cands, acts, max_iterations=10**7, separation_workers=1
    )
    assert plan.status == "UNRESOLVED"
    assert plan.lower_bound is not None, "query-level bound was discarded"
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

    The failing candidate's local bound is accumulated before its status is
    examined; adding it again on the failure path counted it twice.
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
    _timeout_on_call(monkeypatch, 3)
    plan = synthesize_ordered_query(
        cands, acts, max_iterations=10**7, separation_workers=1
    )
    assert plan.status == "UNRESOLVED"
    assert plan.lower_bound is not None
    # Every action costs at most 4 and each candidate has 10 of them, so no
    # valid query bound can exceed the full-library cost.
    full_library = sum(a.cost for a in acts)
    assert plan.lower_bound <= full_library, (
        f"query lower bound {plan.lower_bound} exceeds the full library cost "
        f"{full_library}; a bound above the optimum is never valid"
    )


def test_the_timeout_tests_do_not_race_the_clock() -> None:
    """Pins the fix. These tests failed in CI and passed on the lab host purely because the
    machine was faster than a 0.4 s alarm, so the instance finished and returned OPTIMAL. Any
    reintroduction of a wall-clock budget here makes the suite machine-dependent again."""
    # Checked on the module namespace, not on this file's own text: a source-string guard
    # matches the very literals it forbids and fails on itself. `setitimer` is reachable only
    # through `signal`, so its absence from globals covers both.
    assert "signal" not in globals(), (
        "this module imports `signal` again -- the timeout must be injected deterministically, "
        "not raced against a wall-clock alarm")


def test_the_injected_timeout_lands_after_real_progress(monkeypatch) -> None:
    """The injection must not fire before any work happens, or the test would assert that
    evidence survives when there was never any evidence to survive."""
    pol, th = _hard_instance()
    acts = tuple(
        MeasurementAction(f"p{i}", np.eye(10)[i], cost=float(1 + i % 4)) for i in range(10)
    )
    _timeout_on_call(monkeypatch, 3)
    plan = synthesize_minimum_observation(
        pol, th, acts, max_iterations=10**7, separation_workers=1
    )
    assert plan.status == "UNRESOLVED"
    assert plan.iterations >= 2, "the timeout fired before two iterations completed"
    assert len(plan.witnesses) >= 1
