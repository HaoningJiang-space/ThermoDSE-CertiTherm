"""The blind-direction bound must never exceed the true optimum, on an instance we can solve.

This is the load-bearing property and it is checked against `synthesize_minimum_observation`
itself, not against an argument in a document. The per-cell decomposition retracted earlier this
round (`docs/PER_CELL_DECOMPOSITION_RETRACTED.md`) was asserted in prose across four commits and
reported five numbers before a test refuted it; these tests exist so that cannot recur.

Non-vacuity is asserted first in every case: a bound of zero satisfies `bound <= optimum`
trivially, so a fixture that establishes no confusable pair proves nothing about the property it
claims to test.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import combinations

import numpy as np
import pytest

from CertiTherm.blind_direction_cuts import (
    blind_direction_cells,
    blind_direction_lower_bound,
    block_instrumentation_cost,
    certify_blind_pair,
    minimum_weight_vertex_cover,
)
from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily
from CertiTherm.synthesis import UnresolvedComputation, synthesize_minimum_observation

MARGIN_K = 0.05
TOLERANCE = 1e-9
SINGLE_BLOCK_COST = 8.0
COARSE_COST = 1.0


def _instance(blocks: int = 6, group: int = 3):
    """Two coarse groups of `group` blocks each, one thermal point per block.

    The response is hot on the diagonal and cool off it, so concentrating power on a block heats
    that block's point. With a total-power equality in the polytope, moving power between two
    blocks of one coarse group is exactly the blind direction: the coarse action reads the group
    total, which the move leaves unchanged.
    """

    response = np.full((1, blocks, blocks), 0.2)
    np.fill_diagonal(response[0], 2.0)
    thermal = ThermalFamily(
        ("m0",), response, np.full((1, blocks), 300.0), 330.0, (), np.zeros(1)
    )
    total = 20.0
    polytope = PowerPolytope.box_with_total(
        np.zeros(blocks), np.full(blocks, total), total
    )
    actions = [
        MeasurementAction(
            "c::module::g0",
            np.asarray([1.0 if b < group else 0.0 for b in range(blocks)]),
            COARSE_COST,
            1e-8,
            "c",
        )
    ]
    actions += [
        MeasurementAction(
            f"c::post_route::b{b}", np.eye(blocks)[b], SINGLE_BLOCK_COST, 1e-8, "c"
        )
        for b in range(blocks)
    ]
    return polytope, thermal, tuple(actions)


def _establish(polytope, thermal, actions, cells, single_block_actions):
    """Certify every within-cell pair, returning the edge lists the bound consumes."""

    points = thermal.response_k_per_w.shape[1]
    edges: dict = {}
    for cell_index, cell in enumerate(cells):
        edges[cell_index] = []
        for left, right in combinations(cell, 2):
            witness = certify_blind_pair(
                polytope,
                thermal,
                actions,
                (left, right),
                single_block_actions,
                [(0, q) for q in (left, right) if q < points],
                MARGIN_K,
                TOLERANCE,
            )
            if witness is not None:
                edges[cell_index].append((left, right))
    return edges


def test_the_bound_never_exceeds_the_exactly_solved_optimum() -> None:
    """The whole method in one assertion, against the certified oracle's own answer."""

    polytope, thermal, actions = _instance()
    single_block_actions, cells = blind_direction_cells(actions, thermal.blocks)
    assert len(cells) == 2 and all(len(cell) == 3 for cell in cells), (
        f"the fixture's coarse action did not split the blocks into two cells: {cells}"
    )

    edges = _establish(polytope, thermal, actions, cells, single_block_actions)
    established = sum(len(e) for e in edges.values())
    assert established == 6, (
        f"only {established} of 6 within-cell pairs were established; a bound built on too few "
        "edges would satisfy the inequality vacuously"
    )

    cost = block_instrumentation_cost(actions, single_block_actions, range(thermal.blocks))
    bound, detail = blind_direction_lower_bound(cells, edges, cost)
    assert bound == Fraction(4) * Fraction(SINGLE_BLOCK_COST), (
        "each cell is a triangle, so its cover is two blocks; two cells give four"
    )
    assert all(d["cover_size"] == 2 for d in detail)

    plan = synthesize_minimum_observation(polytope, thermal, actions, max_iterations=200000)
    assert plan.status == "OPTIMAL", f"fixture must solve exactly, got {plan.status}"
    assert plan.exact_cost is not None
    assert bound <= Fraction(plan.exact_cost).limit_denominator(10 ** 9), (
        f"the blind-direction bound {float(bound)} exceeded the true optimum {plan.exact_cost}; "
        "the vertex-cover argument is unsound"
    )


def test_every_counted_witness_is_exactly_feasible_and_exactly_shaped() -> None:
    """Peer review's sharpest finding, checked on the witnesses the bound actually uses.

    `validate_witness` tolerates a world up to the feasibility tolerance OUTSIDE the polytope,
    and such a world does not strictly prove that any selection fails on the original problem.
    The witnesses counted here are repaired first, so the box and the total-power equality hold
    with NO slack at all, in exact rational arithmetic.
    """

    polytope, thermal, actions = _instance()
    single_block_actions, cells = blind_direction_cells(actions, thermal.blocks)
    left, right = cells[0][0], cells[0][1]
    witness = certify_blind_pair(
        polytope,
        thermal,
        actions,
        (left, right),
        single_block_actions,
        [(0, left), (0, right)],
        MARGIN_K,
        TOLERANCE,
    )
    assert witness is not None, "the fixture must establish this pair or it tests nothing"

    total = Fraction(float(np.asarray(polytope.b_eq)[0]))
    for world in (witness.safe_power_w, witness.unsafe_power_w):
        assert sum(world) == total, "the total-power equality must hold exactly, not to a slack"
        for index, value in enumerate(world):
            assert Fraction(float(polytope.lower_w[index])) <= value
            assert value <= Fraction(float(polytope.upper_w[index]))

    delta = [s - u for s, u in zip(witness.safe_power_w, witness.unsafe_power_w)]
    assert delta[left] != 0 and delta[left] == -delta[right]
    assert all(d == 0 for i, d in enumerate(delta) if i not in (left, right))
    assert set(witness.cut_action_indices) == {
        single_block_actions[left][0],
        single_block_actions[right][0],
    }
    for index, action in enumerate(actions):
        if index in witness.cut_action_indices:
            continue
        exact = sum(Fraction(float(v)) * d for v, d in zip(action.vector, delta))
        assert exact == 0, (
            f"action {action.action_id} reads {exact} on the blind direction, so the cut is not "
            "the two single-block actions and the cover argument does not apply"
        )


def test_cells_are_defined_by_coefficient_columns_not_by_nonzero_support() -> None:
    """A weighted action separates blocks whose support pattern looks identical.

    An earlier version keyed cells on `vector != 0`. Two columns holding 1 and 2 share that
    pattern, but the action reads `a . (e_b - e_c) = -1` along the blind direction, so it DOES
    separate them and the pair's cut would not be two single-block actions.
    """

    singles = tuple(
        MeasurementAction(f"c::post_route::b{b}", np.eye(3)[b], 8.0, 1e-8, "c")
        for b in range(3)
    )
    weighted = MeasurementAction("c::module::g0", np.array([1.0, 2.0, 0.0]), 1.0, 1e-8, "c")
    _single, cells = blind_direction_cells((weighted,) + singles, 3)
    assert sorted(len(cell) for cell in cells) == [1, 1, 1], (
        f"blocks 0 and 1 differ in the weighted action and must not share a cell: {cells}"
    )

    flat = MeasurementAction("c::module::g0", np.array([1.0, 1.0, 0.0]), 1.0, 1e-8, "c")
    _single, flat_cells = blind_direction_cells((flat,) + singles, 3)
    assert sorted(len(cell) for cell in flat_cells) == [1, 2], (
        "with equal coefficients those two blocks must share a cell; otherwise this test shows "
        "nothing about columns versus support"
    )


def test_an_action_is_single_block_by_its_vector_not_by_its_name() -> None:
    """Classifying on the `post_route` substring let a rename change the bound silently."""

    renamed = MeasurementAction("c::probe::b0", np.array([1.0, 0.0]), 8.0, 1e-8, "c")
    pair = MeasurementAction("c::post_route::both", np.array([1.0, 1.0]), 8.0, 1e-8, "c")
    single, cells = blind_direction_cells((renamed, pair), 2)
    assert single == {0: (0,)}, "the renamed singleton must still be a single-block action"
    assert cells == ((0, 1),), "the two-block action must not be treated as single-block"


def test_the_cover_is_exact_on_graphs_whose_answer_is_known() -> None:
    """Clique, path, star and unequal weights -- the branching must not merely be plausible."""

    unit = {v: Fraction(1) for v in range(6)}
    clique = [(i, j) for i, j in combinations(range(5), 2)]
    assert minimum_weight_vertex_cover(range(5), clique, unit)[0] == 4
    assert minimum_weight_vertex_cover(range(5), [(0, 1), (1, 2), (2, 3), (3, 4)], unit)[0] == 2
    assert minimum_weight_vertex_cover(range(6), [(0, k) for k in range(1, 6)], unit)[0] == 1
    assert minimum_weight_vertex_cover(range(5), [], unit)[0] == 0

    skewed = {0: Fraction(10), 1: Fraction(1), 2: Fraction(1)}
    weight, cover = minimum_weight_vertex_cover(range(3), [(0, 1), (0, 2)], skewed)
    assert weight == 2 and set(cover) == {1, 2}, (
        "the cheap pair must beat the single expensive hub; a size-minimising cover would "
        "return the hub and be wrong"
    )


def test_a_truncated_cover_search_refuses_rather_than_returning_an_incumbent() -> None:
    """Peer review's principal overestimation risk, guarded and checked.

    Any feasible cover's weight is an UPPER bound on the minimum, so reporting an incumbent from
    a truncated search as a LOWER bound on observation cost would overstate it -- the only way
    this construction can be unsound rather than merely weak. It must fail closed.
    """

    unit = {v: Fraction(1) for v in range(12)}
    clique = [(i, j) for i, j in combinations(range(12), 2)]
    with pytest.raises(UnresolvedComputation, match="upper bound on the minimum"):
        minimum_weight_vertex_cover(range(12), clique, unit, node_budget=5)
    assert minimum_weight_vertex_cover(range(12), clique, unit)[0] == 11


def test_an_incomplete_edge_set_only_lowers_the_bound() -> None:
    """Dropping evidence must never raise a lower bound -- the failure mode that was retracted."""

    polytope, thermal, actions = _instance()
    single_block_actions, cells = blind_direction_cells(actions, thermal.blocks)
    edges = _establish(polytope, thermal, actions, cells, single_block_actions)
    cost = block_instrumentation_cost(actions, single_block_actions, range(thermal.blocks))
    full, _ = blind_direction_lower_bound(cells, edges, cost)
    assert full > 0
    for cell_index in list(edges):
        for drop in range(len(edges[cell_index])):
            partial = {k: list(v) for k, v in edges.items()}
            partial[cell_index] = partial[cell_index][:drop] + partial[cell_index][drop + 1:]
            reduced, _ = blind_direction_lower_bound(cells, partial, cost)
            assert reduced <= full


def test_overlapping_cells_are_refused_because_the_sum_would_double_count() -> None:
    """The only way this bound can exceed the true optimum, guarded at its source."""

    cost = {b: Fraction(8) for b in range(3)}
    with pytest.raises(ValueError, match="pairwise disjoint"):
        blind_direction_lower_bound(((0, 1), (1, 2)), {0: [(0, 1)], 1: [(1, 2)]}, cost)


def test_an_edge_filed_under_the_wrong_cell_is_refused() -> None:
    """A misfiled edge draws a cover from blocks another cell also charges for."""

    cost = {b: Fraction(8) for b in range(4)}
    with pytest.raises(ValueError, match="does not contain"):
        blind_direction_lower_bound(((0, 1), (2, 3)), {0: [(1, 2)]}, cost)


def test_a_block_with_no_single_block_action_cannot_be_charged() -> None:
    """A cover may only charge for an action the master could actually select."""

    _polytope, thermal, actions = _instance()
    single_block_actions, _cells = blind_direction_cells(actions, thermal.blocks)
    trimmed = {b: v for b, v in single_block_actions.items() if b != 0}
    with pytest.raises(ValueError, match="no single-block action"):
        block_instrumentation_cost(actions, trimmed, range(thermal.blocks))


def test_a_witness_whose_step_is_below_tolerance_is_dropped_not_raised() -> None:
    """A degenerate witness is missing evidence, not a broken argument."""

    polytope, thermal, actions = _instance()
    huge_tolerance = tuple(
        MeasurementAction(a.action_id, a.vector, a.cost, 1e6, a.candidate_id) for a in actions
    )
    single_block_actions, cells = blind_direction_cells(huge_tolerance, thermal.blocks)
    left, right = cells[0][0], cells[0][1]
    assert (
        certify_blind_pair(
            polytope, thermal, huge_tolerance, (left, right), single_block_actions,
            [(0, left), (0, right)], MARGIN_K, TOLERANCE,
        )
        is None
    )
    # Non-vacuity: the same pair IS established once the tolerance is realistic, so the drop
    # above is caused by the tolerance and not by the pair being unreachable.
    single_block_actions, _ = blind_direction_cells(actions, thermal.blocks)
    assert (
        certify_blind_pair(
            polytope, thermal, actions, (left, right), single_block_actions,
            [(0, left), (0, right)], MARGIN_K, TOLERANCE,
        )
        is not None
    )


def test_cells_are_a_partition_of_every_block() -> None:
    """Non-vacuity for the partition itself: nothing dropped, nothing double-counted."""

    _polytope, thermal, actions = _instance(blocks=8, group=5)
    single_block_actions, cells = blind_direction_cells(actions, thermal.blocks)
    flat = [block for cell in cells for block in cell]
    assert sorted(flat) == list(range(8)) and len(flat) == len(set(flat))
    assert sorted(len(cell) for cell in cells) == [3, 5]
    assert sorted(single_block_actions) == list(range(8))


def _seed_cuts(polytope, thermal, actions, cells, single_block_actions):
    """Every established pair's cut, as action IDs -- the form the master accepts."""

    points = thermal.response_k_per_w.shape[1]
    seeds = []
    for cell in cells:
        for left, right in combinations(cell, 2):
            witness = certify_blind_pair(
                polytope, thermal, actions, (left, right), single_block_actions,
                [(0, q) for q in (left, right) if q < points], MARGIN_K, TOLERANCE,
            )
            if witness is not None:
                seeds.append(witness.cut_action_ids)
    return seeds


def test_seeded_and_unseeded_synthesis_agree_on_the_optimum_and_the_verdict() -> None:
    """Seeding may change convergence, never the answer -- the tier-2 integration invariant.

    A seeded cut is a NECESSARY constraint, so it excludes no certifying selection, and the
    loop still exits only when the separation oracle finds no collision. If a seed were invalid
    it would cut off the true optimum and this comparison would diverge. That is exactly the
    failure peer review asked to be made visible, so it is asserted rather than argued.
    """

    polytope, thermal, actions = _instance()
    single_block_actions, cells = blind_direction_cells(actions, thermal.blocks)
    seeds = _seed_cuts(polytope, thermal, actions, cells, single_block_actions)
    assert len(seeds) == 6, f"the fixture must produce seeds or this compares nothing: {seeds}"

    plain = synthesize_minimum_observation(polytope, thermal, actions, max_iterations=200000)
    seeded = synthesize_minimum_observation(
        polytope, thermal, actions, max_iterations=200000, seed_cuts=seeds
    )
    assert plain.status == seeded.status == "OPTIMAL"
    assert plain.exact_cost == seeded.exact_cost
    assert seeded.lower_bound is not None and plain.lower_bound is not None
    # The SELECTION may differ: the hitting-set optimum is not unique and seeding changes which
    # optimum the MILP reaches. Asserting set equality was measured to fail here on a plan of
    # equal cost, which is a fact about the instance and not a defect. What must agree is the
    # cost and the verdict -- an invalid seed would cut off the true optimum and raise the cost.
    cost_of = lambda plan: sum(
        a.cost for a in actions if a.action_id in set(plan.selected_action_ids)
    )
    assert cost_of(plain) == cost_of(seeded) == plain.exact_cost


def test_a_seed_naming_an_unknown_action_fails_closed() -> None:
    """A silently dropped seed would weaken the bound with no trace; it must be UNRESOLVED."""

    polytope, thermal, actions = _instance()
    plan = synthesize_minimum_observation(
        polytope, thermal, actions, max_iterations=1000, seed_cuts=[("c::post_route::b99",)]
    )
    assert plan.status == "UNRESOLVED" and plan.exact_cost is None


def test_an_empty_seed_cut_is_refused() -> None:
    """An empty cut asserts nothing separates a collision and would forge UNSYNTHESIZABLE."""

    polytope, thermal, actions = _instance()
    plan = synthesize_minimum_observation(
        polytope, thermal, actions, max_iterations=1000, seed_cuts=[()]
    )
    assert plan.status == "UNRESOLVED" and plan.exact_cost is None


def test_the_cover_solves_the_dense_cells_the_real_instance_actually_has() -> None:
    """The shape that exhausted the node budget on arch_a, and the reason it no longer does.

    Its four largest cells hold 21 blocks with 199-209 of the 210 possible edges. Branching on an
    EDGE decides two vertices per level, so a near-complete cell needs a depth-20 descent before
    the first incumbent appears and the search timed out at two million nodes. Branching on a
    max-degree VERTEX decides twenty at once on the excluding side: either the hub is in the
    cover, or every one of its neighbours is.

    The refusal was correct rather than harmful -- it declined to report an incumbent as a lower
    bound -- but a bound that cannot be computed is still no bound, so the search itself had to
    get better.
    """

    from itertools import combinations as _combinations
    import random as _random

    weight = {v: Fraction(8) for v in range(21)}
    complete = list(_combinations(range(21), 2))
    assert len(complete) == 210
    assert minimum_weight_vertex_cover(range(21), complete, weight)[0] == 160, (
        "a 21-clique needs every vertex but one"
    )
    near = _random.Random(0).sample(complete, 199)
    value, cover = minimum_weight_vertex_cover(range(21), near, weight, node_budget=200_000)
    assert value == 144 and len(cover) == 18, (
        f"expected the measured cell-16 value of 144.0 over 18 blocks, got {float(value)}"
    )


def test_seeding_starts_separation_from_the_seeded_selection() -> None:
    """The integration bug, pinned: seeds are useless if the first separation ignores them.

    `selected` stays empty until the first master refresh, which is correct only when the ledger
    starts empty. With seeds present, separating against the empty selection returns generic
    collisions whose cuts are wide; every wide cut is a superset of one of the narrow two-action
    seeds, the antichain rejects them all as dominated, and the loop's "no new cut" guard fires
    at iteration one. On the real instance that produced UNRESOLVED with no bound at all, worse
    than not seeding.

    A one-iteration run is enough to see it: with the fix the first separation is asked about a
    selection that already hits every seed.
    """

    polytope, thermal, actions = _instance()
    single_block_actions, cells = blind_direction_cells(actions, thermal.blocks)
    seeds = _seed_cuts(polytope, thermal, actions, cells, single_block_actions)
    assert seeds, "no seeds means this test cannot distinguish the two entry points"

    one = synthesize_minimum_observation(
        polytope, thermal, actions, max_iterations=1, seed_cuts=seeds
    )
    assert one.status != "UNRESOLVED", (
        f"a seeded first iteration must make progress, got {one.status}: {one.message}"
    )
    assert one.lower_bound is not None and one.lower_bound > 0, (
        "the seeded master must report a positive bound from the very first iteration"
    )

    bare = synthesize_minimum_observation(polytope, thermal, actions, max_iterations=1)
    assert bare.lower_bound is None or one.lower_bound >= bare.lower_bound, (
        "seeding must not produce a weaker first-iteration bound than not seeding"
    )
