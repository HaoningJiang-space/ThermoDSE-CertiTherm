from __future__ import annotations

from fractions import Fraction
from types import SimpleNamespace

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
from CertiTherm.synthesis import (
    _fraction_lower_float,
    _greedy_cover,
    _insert_minimal_cut,
    _query_collision,
    _solve_master,
    _state_collision,
)


def test_exact_bound_conversion_never_rounds_upward() -> None:
    exact = Fraction(1, 10)
    converted = _fraction_lower_float(exact)
    assert converted is not None
    assert Fraction(converted) <= exact
    assert converted < 0.1  # binary64 0.1 itself lies above the exact tenth
    assert _fraction_lower_float(Fraction(1, 2)) == 0.5


def test_width_order_is_truly_sequential_with_one_worker(monkeypatch) -> None:
    """workers=1 must not construct a spawn pool under the budget alarm."""
    polytope = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    thermal = ThermalFamily(
        ("block",), np.array([[[2.0, 0.0]]]), np.array([0.0]), 1.0
    )
    candidates = (CandidateSpace("only", polytope, thermal),)
    actions = (
        MeasurementAction("p0", np.array([1.0, 0.0]), candidate_id="only"),
        MeasurementAction("p1", np.array([0.0, 1.0]), candidate_id="only"),
    )

    def forbidden_pool(*_args, **_kwargs):
        raise AssertionError("one-worker width scoring constructed a process pool")

    monkeypatch.setattr("CertiTherm.policies.ProcessPoolExecutor", forbidden_pool)
    assert set(uncertainty_width_order(candidates, actions, workers=1)) == {0, 1}


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


def test_model_family_is_one_fail_closed_robust_envelope() -> None:
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
    assert plan.status == "OPTIMAL"
    assert plan.exact_cost == 0.0
    assert not plan.witnesses


def test_ordered_query_does_not_ask_power_channels_to_identify_models() -> None:
    polytope = PowerPolytope.box_with_total(np.ones(1), np.ones(1), 1.0)
    thermal = ThermalFamily(
        model_ids=("cool", "hot"),
        response_k_per_w=np.array([[[0.5]], [[1.5]]]),
        ambient_k=np.array([0.0, 0.0]),
        limit_k=1.0,
    )
    plan = synthesize_ordered_query(
        (CandidateSpace("only", polytope, thermal),),
        (MeasurementAction("full", np.ones(1), candidate_id="only"),),
    )
    assert plan.status == "OPTIMAL"
    assert plan.selected_action_ids == ()
    assert not plan.witnesses


def test_model_error_is_a_fail_closed_upper_temperature_bound() -> None:
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
    assert plan.status == "OPTIMAL"
    assert plan.exact_cost == 0.0
    assert not plan.witnesses


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
    action_index = {action.action_id: index for index, action in enumerate(actions)}
    for policy in (fixed, width, dual):
        selected = tuple(
            action_index[action_id] for action_id in policy.selected_action_ids
        )
        assert _query_collision(candidates, actions, selected, 1e-4, 1e-8) is None


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


def test_query_constraint_generation_matches_all_subset_enumeration() -> None:
    polytope = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    thermal = ThermalFamily(
        ("block",), np.array([[[2.0, 0.0]]]), np.array([0.0]), 1.0
    )
    candidates = (
        CandidateSpace("first", polytope, thermal),
        CandidateSpace("second", polytope, thermal),
    )
    actions = (
        MeasurementAction(
            "first-p0", np.array([1.0, 0.0]), 3.0, candidate_id="first"
        ),
        MeasurementAction(
            "first-p1", np.array([0.0, 1.0]), 2.0, candidate_id="first"
        ),
        MeasurementAction(
            "second-p0", np.array([1.0, 0.0]), 4.0, candidate_id="second"
        ),
        MeasurementAction(
            "second-p1", np.array([0.0, 1.0]), 1.0, candidate_id="second"
        ),
    )
    feasible_costs = []
    for mask in range(1 << len(actions)):
        selected = tuple(
            index for index in range(len(actions)) if mask & (1 << index)
        )
        if _query_collision(candidates, actions, selected, 1e-4, 1e-8) is None:
            feasible_costs.append(sum(actions[index].cost for index in selected))
    plan = synthesize_ordered_query(candidates, actions)
    assert plan.status == "OPTIMAL"
    assert plan.exact_cost == min(feasible_costs)
    assert plan.lower_bound == plan.exact_cost
    assert plan.optimality_gap == 0.0


def test_parallel_multicut_matches_serial_exact_plan() -> None:
    polytope = PowerPolytope.box_with_total(np.zeros(3), np.ones(3), 1.0)
    thermal = ThermalFamily(
        ("block",),
        np.array([[[2.0, 0.0, 0.0], [0.0, 2.0, 0.0]]]),
        np.array([0.0]),
        1.0,
    )
    actions = tuple(
        MeasurementAction(f"p{index}", np.eye(3)[index], cost)
        for index, cost in enumerate((3.0, 2.0, 1.0))
    )
    serial = synthesize_minimum_observation(
        polytope, thermal, actions, separation_workers=1
    )
    parallel = synthesize_minimum_observation(
        polytope, thermal, actions, separation_workers=4
    )
    assert serial.status == parallel.status == "OPTIMAL"
    assert serial.selected_action_ids == parallel.selected_action_ids
    assert serial.exact_cost == parallel.exact_cost
    assert serial.lower_bound == parallel.lower_bound
    assert serial.optimality_gap == parallel.optimality_gap == 0.0


def test_hitting_set_cut_antichain_discards_supersets() -> None:
    cuts = []
    assert _insert_minimal_cut(cuts, np.array([1.0, 1.0, 0.0]))
    assert not _insert_minimal_cut(cuts, np.array([1.0, 1.0, 1.0]))
    assert _insert_minimal_cut(cuts, np.array([1.0, 0.0, 0.0]))
    assert len(cuts) == 1
    np.testing.assert_array_equal(cuts[0], [1.0, 0.0, 0.0])


def test_master_column_dominance_preserves_integer_and_lp_optima() -> None:
    costs = np.array([3.0, 2.0, 2.0, 5.0, 0.1])
    cuts = (
        np.array([1.0, 1.0, 0.0, 1.0, 0.0]),
        np.array([0.0, 1.0, 1.0, 1.0, 0.0]),
        np.array([0.0, 0.0, 1.0, 1.0, 0.0]),
    )
    master = _solve_master(costs, cuts)
    # Column 3 covers every cut but is more expensive than columns 1+2.
    # Column 0 is dominated by column 1, and column 4 covers no cut.
    assert master.selected == (1, 2)
    assert master.cost == master.lower_bound == 4.0
    assert master.relaxation_bound == 4.0
    assert len(master.dual_prices) == len(cuts)


def test_integral_lp_master_skips_branch_and_bound(monkeypatch) -> None:
    def unexpected_milp(*args, **kwargs):
        raise AssertionError("integral LP must not invoke MILP")

    monkeypatch.setattr("CertiTherm.synthesis.milp", unexpected_milp)
    master = _solve_master(
        np.array([1.0, 2.0]),
        (np.array([1.0, 1.0]),),
    )
    assert master.selected == (0,)
    assert master.cost == master.lower_bound == 1.0


def test_lp_bound_matching_incumbent_skips_branch_and_bound(monkeypatch) -> None:
    def unexpected_milp(*args, **kwargs):
        raise AssertionError("closed primal-dual gap must not invoke MILP")

    def fractional_relaxation(*args, **kwargs):
        return SimpleNamespace(
            success=True,
            fun=2.0,
            x=np.array([0.5, 0.5, 0.5]),
            ineqlin=SimpleNamespace(marginals=np.array([-0.5, -0.5, -0.5])),
        )

    monkeypatch.setattr("CertiTherm.synthesis.milp", unexpected_milp)
    monkeypatch.setattr("CertiTherm.synthesis.linprog", fractional_relaxation)
    master = _solve_master(
        np.array([1.0, 1.0, 2.0]),
        (
            np.array([1.0, 1.0, 0.0]),
            np.array([0.0, 1.0, 1.0]),
            np.array([1.0, 0.0, 1.0]),
        ),
        incumbent=(0, 1),
    )
    assert master.selected == (0, 1)
    assert master.cost == master.lower_bound == 2.0


def test_nearby_float_bound_cannot_claim_self_verifiable_optimality(
    monkeypatch,
) -> None:
    cuts = (
        np.array([1.0, 1.0, 0.0]),
        np.array([0.0, 1.0, 1.0]),
        np.array([1.0, 0.0, 1.0]),
    )

    monkeypatch.setattr(
        "CertiTherm.synthesis._integer_lagrangian_bound",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "CertiTherm.synthesis._anytime_lower_bound",
        lambda *_args: 2.0 - 5e-7,
    )
    master = _solve_master(np.ones(3), cuts)
    assert master.cost == 2.0
    assert master.bound_provenance == "solver_branch_and_bound"


def test_greedy_cut_discovery_point_covers_every_registered_cut() -> None:
    costs = np.array([4.0, 1.0, 2.0])
    cuts = (
        np.array([1.0, 1.0, 0.0]),
        np.array([1.0, 0.0, 1.0]),
    )
    selected = _greedy_cover(costs, cuts)
    assert selected == (1, 2)
    assert np.all(np.sum(np.asarray(cuts)[:, selected], axis=1) >= 1.0)


def test_early_stop_bisection_matches_the_first_certified_prefix() -> None:
    polytope = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    thermal = ThermalFamily(
        ("block",), np.array([[[2.0, 0.0]]]), np.array([0.0]), 1.0
    )
    candidate = CandidateSpace("candidate", polytope, thermal)
    actions = tuple(
        MeasurementAction(f"null-{index}", np.zeros(2)) for index in range(12)
    ) + (MeasurementAction("decisive", np.array([1.0, 0.0])),)
    result = sequential_early_stop(
        (candidate,), actions, tuple(range(len(actions)))
    )
    assert result.status == "CERTIFIED"
    assert result.selected_action_ids[-1] == "decisive"
    assert result.selected_action_ids == tuple(action.action_id for action in actions)
    assert result.oracle_calls <= 6


def test_ordered_decomposition_skips_unreachable_candidate_decisions() -> None:
    power = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    ambiguous = ThermalFamily(
        ("block",), np.array([[[2.0, 0.0]]]), np.array([0.0]), 1.0
    )
    always_reject = ThermalFamily(
        ("block",), np.array([[[2.0, 2.0]]]), np.array([0.0]), 1.0
    )
    candidates = (
        CandidateSpace("first", power, ambiguous),
        CandidateSpace("unreachable", power, always_reject),
        CandidateSpace("last", power, ambiguous),
    )
    actions = tuple(
        MeasurementAction(
            candidate,
            np.array([1.0, 0.0]),
            cost,
            candidate_id=candidate,
        )
        for candidate, cost in (
            ("first", 2.0),
            ("unreachable", 0.5),
            ("last", 3.0),
        )
    )
    plan = synthesize_ordered_query(candidates, actions)
    assert plan.status == "OPTIMAL"
    assert plan.selected_action_ids == ("first", "last")
    assert plan.exact_cost == plan.lower_bound == 5.0
    assert _query_collision(candidates, actions, (0, 2), 1e-4, 1e-8) is None
    assert _query_collision(candidates, actions, (0,), 1e-4, 1e-8) is not None


def test_equal_query_states_use_exact_diagonal_coupling() -> None:
    power = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    thermal = ThermalFamily(
        ("cool",), np.zeros((1, 1, 2)), np.array([0.0]), 1.0
    )
    candidate = CandidateSpace("candidate", power, thermal)
    pair = _state_collision(candidate, (), (), "SAFE", "SAFE", 1e-4, 1e-8)
    assert pair is not None
    np.testing.assert_array_equal(pair.left_power_w, pair.right_power_w)
    assert (
        _state_collision(candidate, (), (), "REJECT", "REJECT", 1e-4, 1e-8)
        is None
    )
