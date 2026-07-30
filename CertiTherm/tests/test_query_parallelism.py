"""Query-granularity parallelism must preserve per-query semantics and order."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm import experiments
from CertiTherm.core import (
    CandidateSpace,
    MeasurementAction,
    PowerPolytope,
    ThermalFamily,
)
from CertiTherm.experiments import PreparedQuery, _evaluate_query_batch


def _prepared_query(candidate_id: str) -> PreparedQuery:
    dimension = 2
    power = PowerPolytope.box_with_total(
        np.zeros(dimension), np.ones(dimension), 1.0
    )
    thermal = ThermalFamily(
        ("block",),
        (2.0 * np.eye(dimension))[None, :, :],
        np.asarray([0.0]),
        1.5,
    )
    candidate = CandidateSpace(candidate_id, power, thermal)
    actions = tuple(
        MeasurementAction(
            f"{candidate_id}::post_route::p{index}",
            np.eye(dimension)[index],
            cost=1.0,
            candidate_id=candidate_id,
        )
        for index in range(dimension)
    )
    return PreparedQuery(
        query_id=f"{candidate_id}--default",
        workload_id=candidate_id,
        package_id="default",
        candidates=(candidate,),
        actions=actions,
        fixed_order=tuple(range(dimension)),
        placed_by_candidate={candidate_id: np.full(dimension, 0.5)},
    )


def test_spawn_pool_evaluates_complete_queries_in_registry_order() -> None:
    queries = (_prepared_query("first"), _prepared_query("second"))
    results = _evaluate_query_batch(
        queries,
        include_anytime=False,
        workers=2,
        # Zero, which is METHOD_WORKERS' own default: it is a scheduler SELECTOR, not just a
        # count, and any nonzero value routes the batch through the method-level path instead.
        method_workers=0,
    )

    assert len(results) == len(queries)
    for query, result in zip(queries, results):
        assert result.anytime is None
        assert result.fixed.value is not None
        assert all(
            action_id.startswith(f"{query.workload_id}::")
            for action_id in result.fixed.value.selected_action_ids
        )


def test_query_batch_rejects_nonpositive_worker_count() -> None:
    with pytest.raises(ValueError, match="positive"):
        _evaluate_query_batch(
            (_prepared_query("only"),),
            include_anytime=False,
            workers=0,
            method_workers=0,
        )


def test_worker_failure_is_archived_without_dropping_the_query(
    monkeypatch,
    tmp_path,
) -> None:
    class FailedFuture:
        def result(self):
            raise RuntimeError("worker disappeared")

    class FailedPool:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def submit(self, *_args):
            return FailedFuture()

    monkeypatch.setattr(experiments, "ProcessPoolExecutor", FailedPool)
    query = _prepared_query("failed")
    results = _evaluate_query_batch(
        (query,),
        include_anytime=True,
        workers=2,
        # Zero: `method_workers` selects the SCHEDULER, not just a count. Any nonzero value sends
        # the batch down the method-level path, where a patched pool failure surfaces per method
        # instead of as the query_error this test is about.
        method_workers=0,
    )

    assert len(results) == 1
    result = results[0]
    assert result.exact.value is None
    assert "worker disappeared" in result.query_error
    assert tuple(result.errors) == ("query_worker",)
    assert result.anytime is not None
    assert result.anytime.plan_validity == "UNRESOLVED"
    assert "worker disappeared" in result.anytime.error

    evidence = experiments._archive_query_evidence(
        query,
        result,
        split="dev",
        operators={},
        output=tmp_path,
    )
    assert evidence.result["plan_validity"] == "UNRESOLVED"
    assert "query_worker=" in evidence.result["failure"]
    assert "query_worker=" in evidence.result["unexpected_failure"]
    assert len(evidence.failures) == 1
    assert evidence.failures[0]["stage"] == "query_worker"
