"""The blind-direction bound must never exceed the true optimum, on an instance we can solve.

This is the load-bearing property and it is checked against `synthesize_minimum_observation`
itself, not against an argument in a document. The per-cell decomposition retracted earlier this
round (`docs/PER_CELL_DECOMPOSITION_RETRACTED.md`) was asserted in prose across four commits and
reported five numbers before a test refuted it; the test here exists so that cannot recur.

Non-vacuity is asserted first in every case: a bound of zero satisfies `bound <= optimum`
trivially, so a fixture that establishes no confusable pair proves nothing about the property it
claims to test.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pytest

from CertiTherm.blind_direction_cuts import (
    blind_direction_lower_bound,
    certify_blind_pair,
    coarse_indistinguishability_cells,
    minimum_weight_vertex_cover,
)
from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily
from CertiTherm.synthesis import synthesize_minimum_observation

MARGIN_K = 0.05
TOLERANCE = 1e-9
POST_ROUTE_COST = 8.0
COARSE_COST = 1.0


def _instance(blocks: int = 6, group: int = 3):
    """Two coarse groups of `group` blocks each, one thermal point per block.

    The response is hot on the diagonal and cool off it, so concentrating power on a block
    heats that block's point. With a total-power equality in the polytope, moving power between
    two blocks of one coarse group is exactly the blind direction: the coarse action reads the
    group total, which the move leaves unchanged.
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
            f"c::post_route::b{b}", np.eye(blocks)[b], POST_ROUTE_COST, 1e-8, "c"
        )
        for b in range(blocks)
    ]
    return polytope, thermal, tuple(actions)


def _establish(polytope, thermal, actions, cells, post_route_index):
    """Certify every within-cell pair, returning the edge lists the bound consumes."""

    points = thermal.response_k_per_w.shape[1]
    edges: dict = {}
    for cell_index, cell in enumerate(cells):
        edges[cell_index] = []
        for left, right in combinations(cell, 2):
            specs = [(0, q) for q in (left, right) if q < points]
            witness = certify_blind_pair(
                polytope,
                thermal,
                actions,
                (left, right),
                (post_route_index[left], post_route_index[right]),
                specs,
                MARGIN_K,
                TOLERANCE,
            )
            if witness is not None:
                edges[cell_index].append((left, right))
    return edges


def test_the_bound_never_exceeds_the_exactly_solved_optimum() -> None:
    """The whole method in one assertion, against the certified oracle's own answer."""

    polytope, thermal, actions = _instance()
    post_route_index, cells = coarse_indistinguishability_cells(actions, thermal.blocks)
    assert len(cells) == 2 and all(len(cell) == 3 for cell in cells), (
        f"the fixture's coarse action did not split the blocks into two cells: {cells}"
    )

    edges = _establish(polytope, thermal, actions, cells, post_route_index)
    established = sum(len(e) for e in edges.values())
    assert established == 6, (
        f"only {established} of 6 within-cell pairs were established; a bound built on too few "
        "edges would satisfy the inequality vacuously"
    )

    weight = {b: float(actions[i].cost) for b, i in post_route_index.items()}
    bound, detail = blind_direction_lower_bound(cells, edges, weight)
    assert bound == pytest.approx(4 * POST_ROUTE_COST), (
        "each cell is a triangle, so its cover is two blocks; two cells give four"
    )
    assert all(d["cover_size"] == 2 for d in detail)

    plan = synthesize_minimum_observation(polytope, thermal, actions, max_iterations=200000)
    assert plan.status == "OPTIMAL", f"fixture must solve exactly, got {plan.status}"
    assert plan.exact_cost is not None
    assert bound <= plan.exact_cost + 1e-9, (
        f"the blind-direction bound {bound} exceeded the true optimum {plan.exact_cost}; the "
        "vertex-cover argument is unsound"
    )


def test_a_pair_the_bound_counts_really_cannot_be_left_uninstrumented() -> None:
    """The vertex-cover step, checked one edge at a time rather than assumed.

    The bound's premise is that omitting BOTH of a confusable pair's post-route actions leaves
    the selection unable to certify. Here that is checked directly: the pair's own witness is
    invisible to every action outside its two-element cut, so any selection avoiding both is
    defeated by it.
    """

    polytope, thermal, actions = _instance()
    post_route_index, cells = coarse_indistinguishability_cells(actions, thermal.blocks)
    left, right = cells[0][0], cells[0][1]
    witness = certify_blind_pair(
        polytope,
        thermal,
        actions,
        (left, right),
        (post_route_index[left], post_route_index[right]),
        [(0, left), (0, right)],
        MARGIN_K,
        TOLERANCE,
    )
    assert witness is not None, "the fixture must establish this pair or it tests nothing"
    assert set(witness.cut_action_indices) == {
        post_route_index[left],
        post_route_index[right],
    }
    delta = [s - u for s, u in zip(witness.safe_power_w, witness.unsafe_power_w)]
    assert any(d != 0 for d in delta), "a zero delta would make every action a non-separator"
    for index, action in enumerate(actions):
        if index in witness.cut_action_indices:
            continue
        exact = sum(int(round(v)) * d for v, d in zip(action.vector, delta))
        assert exact == 0, (
            f"action {action.action_id} reads {exact} on the blind direction, so the cut is not "
            "the two post-route actions and the cover argument does not apply"
        )


def test_the_cover_is_exact_on_graphs_whose_answer_is_known() -> None:
    """Clique, path, star and unequal weights -- the branching must not merely be plausible."""

    unit = {v: 1.0 for v in range(6)}
    clique = [(i, j) for i, j in combinations(range(5), 2)]
    assert minimum_weight_vertex_cover(range(5), clique, unit)[0] == 4.0
    path = [(0, 1), (1, 2), (2, 3), (3, 4)]
    assert minimum_weight_vertex_cover(range(5), path, unit)[0] == 2.0
    star = [(0, k) for k in range(1, 6)]
    assert minimum_weight_vertex_cover(range(6), star, unit)[0] == 1.0
    assert minimum_weight_vertex_cover(range(5), [], unit)[0] == 0.0

    skewed = {0: 10.0, 1: 1.0, 2: 1.0}
    weight, cover = minimum_weight_vertex_cover(range(3), [(0, 1), (0, 2)], skewed)
    assert weight == 2.0 and set(cover) == {1, 2}, (
        "the cheap pair must beat the single expensive hub; a size-minimising cover would "
        "return the hub and be wrong"
    )


def test_an_incomplete_edge_set_only_lowers_the_bound() -> None:
    """Dropping evidence must never raise a lower bound -- the failure mode that was retracted."""

    polytope, thermal, actions = _instance()
    post_route_index, cells = coarse_indistinguishability_cells(actions, thermal.blocks)
    edges = _establish(polytope, thermal, actions, cells, post_route_index)
    weight = {b: float(actions[i].cost) for b, i in post_route_index.items()}
    full, _ = blind_direction_lower_bound(cells, edges, weight)
    assert full > 0.0
    for cell_index in list(edges):
        for drop in range(len(edges[cell_index])):
            partial = {k: list(v) for k, v in edges.items()}
            partial[cell_index] = partial[cell_index][:drop] + partial[cell_index][drop + 1:]
            reduced, _ = blind_direction_lower_bound(cells, partial, weight)
            assert reduced <= full + 1e-12


def test_a_post_route_action_that_observes_two_blocks_is_refused() -> None:
    """The cell partition is only meaningful if post-route really means one block."""

    bad = (
        MeasurementAction("c::post_route::b0", np.array([1.0, 1.0, 0.0]), 8.0, 1e-8, "c"),
    )
    with pytest.raises(ValueError, match="observes 2 blocks"):
        coarse_indistinguishability_cells(bad, 3)


def test_cells_are_a_partition_of_every_block() -> None:
    """Non-vacuity for the partition itself: nothing dropped, nothing double-counted."""

    _polytope, thermal, actions = _instance(blocks=8, group=5)
    post_route_index, cells = coarse_indistinguishability_cells(actions, thermal.blocks)
    flat = [block for cell in cells for block in cell]
    assert sorted(flat) == list(range(8)) and len(flat) == len(set(flat))
    assert sorted(len(cell) for cell in cells) == [3, 5]
    assert sorted(post_route_index) == list(range(8))
