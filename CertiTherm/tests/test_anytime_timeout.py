"""Regression: anytime evidence must survive a wall-clock budget."""
from __future__ import annotations
import signal
import numpy as np
import pytest
from CertiTherm.core import CandidateSpace, PowerPolytope, ThermalFamily, MeasurementAction
from CertiTherm.synthesis import synthesize_minimum_observation, synthesize_ordered_query


def _hard_instance(n: int = 10):
    pol = PowerPolytope.box_with_total(np.zeros(n), np.ones(n), 1.0)
    resp = np.array([[np.eye(n)[i] * 2.0 for i in range(n)]])
    th = ThermalFamily(("b",), resp, np.array([0.0]), 1.0)
    return pol, th


def _run_under_alarm(fn, seconds: float):
    def expire(*_a):
        raise TimeoutError("test budget exhausted")
    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        return fn()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_timeout_preserves_anytime_evidence() -> None:
    """A budget timeout previously discarded the entire result."""
    pol, th = _hard_instance()
    acts = tuple(
        MeasurementAction(f"p{i}", np.eye(10)[i], cost=float(1 + i % 4)) for i in range(10)
    )
    plan = _run_under_alarm(
        lambda: synthesize_minimum_observation(
            pol, th, acts, max_iterations=10**7, separation_workers=1
        ),
        0.4,
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


def test_timeout_on_ordered_query_still_reports_a_bound() -> None:
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
    plan = _run_under_alarm(
        lambda: synthesize_ordered_query(
            cands, acts, max_iterations=10**7, separation_workers=1
        ),
        0.35,
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
