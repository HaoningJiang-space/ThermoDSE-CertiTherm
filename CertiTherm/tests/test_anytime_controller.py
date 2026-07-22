"""Regression: Anytime-DSOS must use ONE end-to-end budget."""
from __future__ import annotations
import time
import numpy as np
from types import SimpleNamespace
from CertiTherm.core import CandidateSpace, PowerPolytope, ThermalFamily, MeasurementAction
from CertiTherm.experiments import anytime_dsos
from CertiTherm.policies import PolicyResult


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
        assert result.upper_source in ("width", "exact")
        assert len(result.upper_action_ids) > 0 or result.upper_bound == 0


def test_interval_is_ordered_or_flagged() -> None:
    cands, acts = _instance()
    result = anytime_dsos(cands, acts, budget_s=6.0)
    if result.upper_bound is not None and result.lower_bound is not None:
        # Either the interval is ordered, or the violation is recorded loudly.
        assert result.interval_violation or result.lower_bound <= result.upper_bound
        if not result.interval_violation:
            assert result.absolute_gap is not None
            assert result.absolute_gap >= 0.0


def test_same_run_carries_upper_plan_and_bound_metadata(monkeypatch) -> None:
    """The artifact must replay the same contract that supplies its U."""
    cands, acts = _instance()
    width = PolicyResult("CERTIFIED", (acts[1].action_id,), 2.0, 3)
    lower = SimpleNamespace(
        status="UNRESOLVED",
        lower_bound=1.0,
        bound_provenance="weak_duality",
        cost_optimality="UNKNOWN",
    )
    monkeypatch.setattr(
        "CertiTherm.experiments.uncertainty_width_order",
        lambda *_args: tuple(range(len(acts))),
    )
    monkeypatch.setattr(
        "CertiTherm.experiments.sequential_early_stop", lambda *_args: width
    )
    monkeypatch.setattr(
        "CertiTherm.experiments.synthesize_ordered_query", lambda *_args: lower
    )

    result = anytime_dsos(cands, acts, budget_s=6.0)
    assert result.upper_bound == 2.0
    assert result.upper_action_ids == width.selected_action_ids
    assert result.lower_bound == 1.0
    assert result.bound_provenance == "weak_duality"
    assert result.plan_validity == "CERTIFIED"
    assert result.cost_optimality == "BOUNDED_GAP"
    assert result.approximation_ratio == 2.0
    assert result.relative_gap == 1.0


def test_exact_phase_tightens_upper_bound_and_replaces_plan(monkeypatch) -> None:
    cands, acts = _instance()
    width = PolicyResult("CERTIFIED", (acts[3].action_id,), 4.0, 3)
    exact = SimpleNamespace(
        status="OPTIMAL",
        selected_action_ids=(acts[0].action_id,),
        exact_cost=1.0,
        lower_bound=1.0,
        bound_provenance="weak_duality",
        cost_optimality="PROVEN_SELF_VERIFIABLE",
    )
    monkeypatch.setattr(
        "CertiTherm.experiments.uncertainty_width_order",
        lambda *_args: tuple(range(len(acts))),
    )
    monkeypatch.setattr(
        "CertiTherm.experiments.sequential_early_stop", lambda *_args: width
    )
    monkeypatch.setattr(
        "CertiTherm.experiments.synthesize_ordered_query", lambda *_args: exact
    )

    result = anytime_dsos(cands, acts, budget_s=6.0)
    assert result.upper_source == "exact"
    assert result.upper_bound == result.lower_bound == 1.0
    assert result.upper_action_ids == exact.selected_action_ids
    assert result.cost_optimality == "PROVEN_SELF_VERIFIABLE"


def test_upper_cost_must_replay_from_archived_action_ids(monkeypatch) -> None:
    cands, acts = _instance()
    inconsistent = PolicyResult(
        "CERTIFIED", (acts[0].action_id,), acts[0].cost + 1.0, 3
    )
    monkeypatch.setattr(
        "CertiTherm.experiments.uncertainty_width_order",
        lambda *_args: tuple(range(len(acts))),
    )
    monkeypatch.setattr(
        "CertiTherm.experiments.sequential_early_stop",
        lambda *_args: inconsistent,
    )
    import pytest

    with pytest.raises(RuntimeError, match="does not match replayed action cost"):
        anytime_dsos(cands, acts, budget_s=6.0)


def test_unsynthesizable_result_cannot_coexist_with_an_upper_plan() -> None:
    from CertiTherm.experiments import AnytimeResult, CertifiedContract

    contradiction = AnytimeResult(
        contract=CertifiedContract("width", ("a",), 1.0),
        proof_search=SimpleNamespace(
            status="UNSYNTHESIZABLE",
            lower_bound=None,
            bound_provenance=None,
        ),
        upper_seconds=1.0,
        lower_seconds=1.0,
    )
    assert contradiction.interval_violation
    assert contradiction.plan_validity == "UNRESOLVED"
    assert contradiction.cost_optimality == "UNKNOWN"


def test_query_bundle_serializes_only_its_anytime_evidence(monkeypatch) -> None:
    """Independent baseline values must never leak into the U/L fields."""
    from CertiTherm import experiments
    from CertiTherm.experiments import (
        AnytimeResult,
        CertifiedContract,
        TimedResult,
        _anytime_result_fields,
        _evaluate_query_methods,
    )

    cands, acts = _instance()
    baseline_values = iter(
        (
            SimpleNamespace(status="UNRESOLVED", lower_bound=999.0),
            PolicyResult("CERTIFIED", (acts[0].action_id,), 999.0, 1),
            PolicyResult("CERTIFIED", (acts[0].action_id,), 888.0, 1),
            PolicyResult("CERTIFIED", (acts[0].action_id,), 777.0, 1),
        )
    )
    monkeypatch.setattr(
        experiments,
        "_timed_call",
        lambda _function: TimedResult(next(baseline_values), 1.0, ""),
    )
    anytime = AnytimeResult(
        contract=CertifiedContract("width", (acts[1].action_id,), 2.0),
        proof_search=SimpleNamespace(
            status="UNRESOLVED",
            lower_bound=1.0,
            bound_provenance="weak_duality",
        ),
        upper_seconds=2.0,
        lower_seconds=3.0,
    )
    monkeypatch.setattr(experiments, "anytime_dsos", lambda *_args: anytime)

    methods = _evaluate_query_methods(
        cands,
        acts,
        tuple(range(len(acts))),
        include_anytime=True,
    )
    fields = _anytime_result_fields(methods.anytime)
    assert methods.anytime is anytime
    assert fields["certified_upper_bound"] == 2.0
    assert fields["certified_lower_bound"] == 1.0
    assert fields["bound_provenance"] == "weak_duality"
    assert 999.0 not in fields.values()


def test_legacy_protocol_does_not_run_anytime(monkeypatch) -> None:
    from CertiTherm import experiments
    from CertiTherm.experiments import TimedResult, _evaluate_query_methods

    cands, acts = _instance()
    baseline_values = iter(
        (
            SimpleNamespace(status="UNRESOLVED"),
            PolicyResult("CERTIFIED", (), 0.0, 1),
            PolicyResult("CERTIFIED", (), 0.0, 1),
            PolicyResult("CERTIFIED", (), 0.0, 1),
        )
    )
    monkeypatch.setattr(
        experiments,
        "_timed_call",
        lambda _function: TimedResult(next(baseline_values), 1.0, ""),
    )

    def forbidden_anytime(*_args):
        raise AssertionError("legacy method-freeze-v1 invoked Anytime-DSOS")

    monkeypatch.setattr(experiments, "anytime_dsos", forbidden_anytime)
    methods = _evaluate_query_methods(
        cands,
        acts,
        tuple(range(len(acts))),
        include_anytime=False,
    )
    assert methods.anytime is None
