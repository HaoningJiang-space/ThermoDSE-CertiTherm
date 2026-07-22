"""Regression: Anytime-DSOS must use ONE end-to-end budget."""
from __future__ import annotations
import time
import numpy as np
from CertiTherm.core import CandidateSpace, PowerPolytope, ThermalFamily, MeasurementAction
from CertiTherm.experiments import anytime_dsos


def _instance(n: int = 8):
    pol = PowerPolytope.box_with_total(np.zeros(n), np.ones(n), 1.0)
    resp = np.array([[np.eye(n)[i] * 2.0 for i in range(n)]])
    th = ThermalFamily(("b",), resp, np.array([0.0]), 1.0)
    cands = (CandidateSpace("c0", pol, th),)
    acts = tuple(
        MeasurementAction(f"c0-p{i}", np.eye(n)[i], cost=float(1 + i % 4), candidate_id="c0")
        for i in range(n)
    )
    return cands, acts


def test_anytime_respects_one_end_to_end_budget() -> None:
    """The whole point of v2.1's budget clause: not two full budgets."""
    cands, acts = _instance()
    budget = 6.0
    started = time.perf_counter()
    result = anytime_dsos(cands, acts, budget_s=budget)
    elapsed = time.perf_counter() - started
    assert elapsed <= budget * 1.5, (
        f"took {elapsed:.1f}s against a {budget}s end-to-end budget; the phases "
        "are not sharing one budget"
    )
    assert result.upper_seconds + result.lower_seconds <= budget * 1.5


def test_upper_bound_only_from_a_certified_contract() -> None:
    cands, acts = _instance()
    result = anytime_dsos(cands, acts, budget_s=6.0)
    if result.upper_bound is not None:
        assert result.upper_source == "width"


def test_interval_is_ordered_or_flagged() -> None:
    cands, acts = _instance()
    result = anytime_dsos(cands, acts, budget_s=6.0)
    if result.upper_bound is not None and result.lower_bound is not None:
        # Either the interval is ordered, or the violation is recorded loudly.
        assert result.interval_violation or result.lower_bound <= result.upper_bound
        if not result.interval_violation:
            assert result.absolute_gap is not None
            assert result.absolute_gap >= 0.0


def test_driver_sources_the_v21_endpoints_from_the_controller() -> None:
    """The previous revision built U as min(width, dual, fixed) in the driver.

    That violated method-freeze-v2.1 twice -- U and L from separately budgeted
    runs, and independent baselines substituted into U -- and the other tests
    in this file could not catch it because they call `anytime_dsos` directly
    while the driver never did. Assert the wiring, not just the mechanism.
    """
    import inspect
    from CertiTherm import experiments

    source = inspect.getsource(experiments.run)
    assert "anytime_dsos(" in source, (
        "the experiment driver does not call anytime_dsos; the v2.1 endpoints "
        "would again describe a post-hoc pairing rather than one algorithm"
    )
    # U must not be assembled from the baseline policies in the driver.
    assert "min(certified_uppers)" not in source
    for baseline in ("width.cost", "dual.cost", "fixed.cost"):
        assert f"upper = {baseline}" not in source
