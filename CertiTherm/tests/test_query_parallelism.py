"""Query-granularity parallelism must preserve per-query semantics and order."""

from __future__ import annotations

import numpy as np
import pytest

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
        )
