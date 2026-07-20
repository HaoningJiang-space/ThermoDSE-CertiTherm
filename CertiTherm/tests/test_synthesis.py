from __future__ import annotations

import numpy as np

from CertiTherm import (
    MeasurementAction,
    CandidateSpace,
    PowerPolytope,
    ThermalFamily,
    synthesize_minimum_observation,
    synthesize_ordered_query,
)
from CertiTherm.policies import (
    dual_price_greedy,
    sequential_early_stop,
    uncertainty_width_order,
)
from CertiTherm.adaptive import finite_adaptive_limit


def test_exact_plan_reaches_unit_cost_global_limit() -> None:
    polytope = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    thermal = ThermalFamily(
        model_ids=("block",),
        response_k_per_w=np.array([[[2.0, 0.0]]]),
        ambient_k=np.array([0.0]),
        limit_k=1.0,
    )
    actions = (
        MeasurementAction("p0", np.array([1.0, 0.0])),
        MeasurementAction("p1", np.array([0.0, 1.0])),
    )
    plan = synthesize_minimum_observation(polytope, thermal, actions)
    assert plan.status == "OPTIMAL"
    assert plan.exact_cost == plan.lower_bound == 1.0
    assert plan.optimality_gap == 0.0
    assert len(plan.selected_action_ids) == 1


def test_same_power_cross_model_flip_is_unsynthesizable() -> None:
    polytope = PowerPolytope.box_with_total(np.ones(1), np.ones(1), 1.0)
    thermal = ThermalFamily(
        model_ids=("cool", "hot"),
        response_k_per_w=np.array([[[0.5]], [[1.5]]]),
        ambient_k=np.array([0.0, 0.0]),
        limit_k=1.0,
    )
    plan = synthesize_minimum_observation(
        polytope,
        thermal,
        (MeasurementAction("full-power", np.ones(1)),),
    )
    assert plan.status == "UNSYNTHESIZABLE"
    assert plan.witnesses[-1].cause == "MODEL_NON_IDENTIFIABLE"


def test_model_error_straddling_limit_cannot_be_measured_away() -> None:
    polytope = PowerPolytope.box_with_total(np.ones(1), np.ones(1), 1.0)
    thermal = ThermalFamily(
        model_ids=("block",),
        response_k_per_w=np.array([[[1.0]]]),
        ambient_k=np.array([0.0]),
        limit_k=1.0,
        error_k=np.array([0.01]),
    )
    plan = synthesize_minimum_observation(
        polytope,
        thermal,
        (MeasurementAction("full-power", np.ones(1)),),
    )
    assert plan.status == "UNSYNTHESIZABLE"
    assert plan.witnesses[-1].cause == "MODEL_NON_IDENTIFIABLE"


def test_ordered_query_optimizes_cross_candidate_decision() -> None:
    polytope = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    thermal = ThermalFamily(
        ("block",), np.array([[[2.0, 0.0]]]), np.array([0.0]), 1.0
    )
    candidates = (
        CandidateSpace("fast", polytope, thermal),
        CandidateSpace("slow", polytope, thermal),
    )
    actions = tuple(
        MeasurementAction(
            f"{candidate}-p{index}",
            np.eye(2)[index],
            candidate_id=candidate,
        )
        for candidate in ("fast", "slow")
        for index in range(2)
    )
    plan = synthesize_ordered_query(candidates, actions)
    assert plan.status == "OPTIMAL"
    assert plan.exact_cost == plan.lower_bound
    assert plan.optimality_gap == 0.0
    fixed = sequential_early_stop(candidates, actions, tuple(range(len(actions))))
    width_order = uncertainty_width_order(candidates, actions)
    width = sequential_early_stop(candidates, actions, width_order)
    dual = dual_price_greedy(candidates, actions)
    assert fixed.status == width.status == dual.status == "CERTIFIED"
    assert min(fixed.cost, width.cost, dual.cost) >= plan.exact_cost


def test_finite_adaptive_bellman_limit() -> None:
    result = finite_adaptive_limit(
        decisions=("A", "A", "B", "B"),
        action_ids=("coarse", "left", "right"),
        outcomes=(
            ("0", "1", "0", "1"),
            ("0", "0", "1", "1"),
            ("0", "1", "1", "0"),
        ),
        costs=(1.0, 2.0, 2.0),
    )
    assert result.status == "OPTIMAL"
    assert result.worst_case_cost == 2.0
    assert result.first_action == "left"
