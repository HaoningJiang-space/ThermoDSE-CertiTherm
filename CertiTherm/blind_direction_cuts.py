"""Cuts along the power directions the coarse instrumentation is algebraically blind to.

Every action produced by `measurements.build_measurement_library` is a 0/1 indicator over a
group of blocks. So for two blocks that fall in the SAME group of every coarse (non-post-route)
action, the direction that moves power from one to the other is invisible to all of them:

    delta = t * (e_b - e_c)   =>   a . delta = t * (1 - 1) = 0   for every such coarse a

A collision along that direction therefore has a separating set of exactly two actions --
`post_route(b)` and `post_route(c)` -- which is the smallest non-trivial cut the hitting-set
master can receive, and the only kind no cheap coarse action can hit.

Two structural consequences, and they are what make this different in kind from accumulating
generic cuts:

* **Vertex cover.** Any certifying selection must contain `post_route(b)` or `post_route(c)` for
  every confusable pair, so the blocks it instruments form a vertex cover of that cell's
  confusability graph. The bound is the cover's minimum weight, computed exactly -- not a
  quantity that grows logarithmically in the number of cuts discovered.
* **Additivity.** Cells partition the blocks and each cell's cuts mention only its own blocks'
  post-route actions, so the per-cell minima ADD. Disjoint supports are exactly what overlapping
  generic cuts lack.

Layer position: this is a research extension that imports FROM `synthesis`, in the same
direction as `kernelized_collision` and for the same reason -- deleting this file leaves the
certified path producing identical verdicts. Never add an import the other way.

Nothing here is a relaxation of the certified problem. Every pair counted is backed by a witness
that survives exact rational re-validation (`certificate.validate_witness`) and whose cut is
recomputed exactly (`certificate.separator_set`); a pair that is not established is dropped, and
dropping pairs only shrinks the graph, whose cover is still a lower bound.

**Composing with the bound `synthesize_minimum_observation` already reports is `max`, never a
sum.** Both lower-bound the SAME selection cost, and the generic cuts can be hit by the very
post-route actions this cover charges for, so adding them double-counts. The sound way to get
more than `max` is not arithmetic at all: seed these individual two-element cuts into the
master's cut ledger and let one hitting-set optimisation combine them with the discovered ones.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .certificate import (
    CertificateError,
    CertificateUnresolved,
    separator_set,
    validate_witness,
)
from .core import MeasurementAction, PowerPolytope, ThermalFamily
from .synthesis import (
    UnresolvedComputation,
    _build_collision_problem,
    _solve_collision_spec,
)

POST_ROUTE_MARKER = "::post_route::"


@dataclass(frozen=True)
class BlindPairWitness:
    """One confusable pair, its exactly validated worlds, and the reject cell that proves it."""

    left_block: int
    right_block: int
    safe_power_w: Tuple[Fraction, ...]
    unsafe_power_w: Tuple[Fraction, ...]
    reject_model: int
    reject_point: int
    cut_action_indices: Tuple[int, ...]


def coarse_indistinguishability_cells(
    actions: Sequence[MeasurementAction], block_count: int
) -> Tuple[Dict[int, int], Tuple[Tuple[int, ...], ...]]:
    """Partition blocks by their coarse signature, and index the post-route action per block.

    Two blocks share a cell exactly when every coarse action either observes both or neither --
    the common refinement of the module, chiplet and placement-region partitions. Post-route
    actions are excluded from the signature by construction: they are the only actions that can
    tell two blocks in one cell apart, which is the whole point.

    Returns `(post_route_index_by_block, cells)` with cells in a deterministic order.
    """

    post_route_index: Dict[int, int] = {}
    coarse: List[np.ndarray] = []
    for index, action in enumerate(actions):
        support = np.flatnonzero(action.vector)
        if POST_ROUTE_MARKER in action.action_id:
            if support.size != 1:
                raise ValueError(
                    f"post-route action {action.action_id} observes {support.size} blocks"
                )
            post_route_index[int(support[0])] = index
        else:
            coarse.append(np.asarray(action.vector))
    matrix = np.asarray(coarse) if coarse else np.zeros((0, block_count))
    if matrix.shape[1] != block_count:
        raise ValueError("action vectors and block count disagree")
    signatures: Dict[Tuple[int, ...], List[int]] = {}
    for block in range(block_count):
        key = tuple(int(v) for v in (matrix[:, block] != 0.0))
        signatures.setdefault(key, []).append(block)
    cells = tuple(tuple(sorted(members)) for _, members in sorted(signatures.items()))
    return post_route_index, cells


def minimum_weight_vertex_cover(
    vertices: Sequence[int],
    edges: Sequence[Tuple[int, int]],
    weight: Mapping[int, float],
    node_budget: int = 2_000_000,
) -> Tuple[float, Tuple[int, ...]]:
    """PROVEN minimum-weight vertex cover, by branching on a still-uncovered edge.

    Exact rather than the usual matching lower bound because a cell holds tens of blocks, and
    the recursion depth is the cover size rather than the vertex count: pick any uncovered edge,
    and every cover must take one of its two endpoints.

    Weighted so the bound stays correct if post-route costs ever differ per block. With equal
    costs it reduces to `cost * |cover|`, and on a k-clique to `cost * (k - 1)`.

    **The search must run to proven optimality or fail.** Any feasible cover's weight is an
    UPPER bound on the minimum, so returning an incumbent after a truncated search and using it
    as a lower bound on the observation cost would overstate it -- the one direction in which
    this whole construction can be unsound rather than merely weak. Peer review named this as
    the principal overestimation risk. Exhausting `node_budget` therefore raises
    `UnresolvedComputation`, which is the package's UNRESOLVED status and not a number.
    """

    for vertex in vertices:
        if vertex not in weight:
            raise ValueError(f"vertex {vertex} has no weight")
        if not float(weight[vertex]) >= 0.0:
            raise ValueError(f"vertex {vertex} has a negative or non-finite weight")
    best_weight, best_cover, nodes = float("inf"), (), 0

    def branch(chosen: Tuple[int, ...], chosen_weight: float, pending: List[Tuple[int, int]]):
        nonlocal best_weight, best_cover, nodes
        nodes += 1
        if nodes > node_budget:
            raise UnresolvedComputation(
                f"vertex cover search exceeded {node_budget} nodes; an incumbent cover is an "
                "upper bound on the minimum and must not be reported as a lower bound"
            )
        if chosen_weight >= best_weight:
            return
        taken = set(chosen)
        uncovered = [(u, v) for u, v in pending if u not in taken and v not in taken]
        if not uncovered:
            best_weight, best_cover = chosen_weight, chosen
            return
        left, right = uncovered[0]
        first, second = (
            (left, right) if weight[left] <= weight[right] else (right, left)
        )
        for pick in (first, second):
            branch(chosen + (pick,), chosen_weight + float(weight[pick]), uncovered)

    branch((), 0.0, list(edges))
    return best_weight, best_cover


def certify_blind_pair(
    polytope: PowerPolytope,
    thermal: ThermalFamily,
    actions: Sequence[MeasurementAction],
    block_pair: Tuple[int, int],
    pair_action_indices: Tuple[int, int],
    reject_specs: Iterable[Tuple[int, int]],
    margin_k: float,
    feasibility_tolerance: float,
) -> Optional[BlindPairWitness]:
    """Prove that no selection omitting BOTH of a pair's post-route actions can certify.

    The delta's shape is imposed on the collision LP as equalities -- `delta_c = 0` off the pair,
    and `delta_left + delta_right = 0` so a coarse action holding both blocks reads zero instead
    of their sum. Constraining the shape is necessary and not merely convenient: an action
    constraint is `|a . delta| <= tol_a`, not an equality, so simply omitting the two post-route
    actions from the selection lets the LP spread the delta across every block. Measured on the
    real instance, the first witness obtained that way had a NINE-action exact cut, seven of them
    coarse -- and one coarse action in the cut collapses the bound, because the master can hit it
    for 1.0 instead of two post-route actions for 8.0.

    Equalities still hold only to the solver's tolerance, so the witness is SNAPPED: the safe
    world is taken as exact rationals and the unsafe world is redefined as
    `safe - t (e_left - e_right)`. That pair's delta is exactly along the blind direction in
    rational arithmetic, so `separator_set` returns exactly the two post-route actions rather
    than whatever the solver's residual happened to push over a tolerance. The snap perturbs the
    unsafe world by about the feasibility tolerance, which is precisely what
    `validate_witness`'s declared `slack` exists to absorb, and the slack stays far below the
    margin, so the SAFE/REJECT sides remain robustly separated.

    Returns None when no scanned reject cell yields a witness or the snapped pair fails exact
    validation. Both are "not established", never "not confusable": callers only ever need
    positives, so a negative is never used as a claim.
    """

    left, right = block_pair
    n = polytope.dimension
    problem = _build_collision_problem(
        polytope, thermal, actions, (), margin_k, feasibility_tolerance
    )
    shape_rows = []
    for block in range(n):
        if block in (left, right):
            continue
        row = np.zeros(2 * n)
        row[block], row[n + block] = 1.0, -1.0
        shape_rows.append(row)
    antisymmetry = np.zeros(2 * n)
    antisymmetry[left], antisymmetry[n + left] = 1.0, -1.0
    antisymmetry[right], antisymmetry[n + right] = 1.0, -1.0
    shape_rows.append(antisymmetry)
    shaped = replace(
        problem,
        a_eq=np.vstack((problem.a_eq, np.asarray(shape_rows))),
        b_eq=np.concatenate((problem.b_eq, np.zeros(len(shape_rows)))),
    )

    slack = Fraction(feasibility_tolerance).limit_denominator(10 ** 12)
    expected_cut = set(pair_action_indices)
    for model, point in reject_specs:
        witness = _solve_collision_spec(shaped, (model, point))
        if witness is None:
            continue
        safe_w = tuple(Fraction(float(v)) for v in witness.safe_power_w)
        step = safe_w[left] - Fraction(float(witness.unsafe_power_w[left]))
        unsafe_w = tuple(
            value - step if index == left else value + step if index == right else value
            for index, value in enumerate(safe_w)
        )
        # The snap makes these true by construction; they are asserted anyway because they are
        # the shape the whole cover argument rests on, and an edit to the snap that quietly broke
        # one of them would otherwise only show up as a wrong bound.
        delta = tuple(s - u for s, u in zip(safe_w, unsafe_w))
        if any(d != 0 for i, d in enumerate(delta) if i not in (left, right)):
            raise CertificateError("the snapped delta is supported outside the pair")
        if delta[left] != -delta[right]:
            raise CertificateError("the snapped delta is not antisymmetric on the pair")
        if delta[left] == 0:
            continue
        try:
            validate_witness(
                safe_w, unsafe_w, model, point, polytope, thermal, margin_k, slack
            )
            cut = separator_set(safe_w, unsafe_w, actions, Fraction(0))
        except (CertificateError, CertificateUnresolved):
            continue
        if set(cut) != expected_cut:
            # With the delta exactly along the blind direction, every action outside the pair
            # reads exactly zero, so the cut can only ever be a SUBSET of the two post-route
            # actions. It is a strict subset when |t| falls at or below an action's tolerance --
            # a degenerate witness, not a broken argument, so it is dropped as unestablished
            # rather than raising. Anything else would mean an action distinguishes two blocks
            # of one cell, which contradicts how the cells were built, and must stop the caller.
            if not set(cut) <= expected_cut:
                raise CertificateError(
                    "a blind-direction witness separated an action outside the pair's two "
                    f"post-route actions (cut size {len(cut)}); the cell partition and the "
                    "action library disagree"
                )
            continue
        return BlindPairWitness(
            left_block=left,
            right_block=right,
            safe_power_w=safe_w,
            unsafe_power_w=unsafe_w,
            reject_model=model,
            reject_point=point,
            cut_action_indices=tuple(sorted(cut)),
        )
    return None


def blind_direction_lower_bound(
    cells: Sequence[Sequence[int]],
    confusable_edges: Mapping[int, Sequence[Tuple[int, int]]],
    post_route_cost: Mapping[int, float],
) -> Tuple[float, Tuple[dict, ...]]:
    """Sum each cell's exact minimum-weight cover -- valid because the cells are disjoint.

    `confusable_edges` maps a cell's index to the pairs established by `certify_blind_pair`.
    Cells with no established edge contribute nothing, which is why an incomplete scan can only
    understate the bound.

    Additivity is the one place this can go UNSOUND rather than merely weak: if two summed cells
    shared a block, that block's post-route action would be paid for twice and the total could
    exceed the true optimum. Both preconditions are therefore checked here rather than assumed
    of the caller -- the cells must be pairwise disjoint, and every edge must join two blocks of
    the cell it is filed under. A caller that files an edge in the wrong cell would otherwise
    produce a cover drawn from blocks another cell also charges for.
    """

    seen: set = set()
    for cell in cells:
        members = set(cell)
        if len(members) != len(cell) or members & seen:
            raise ValueError("cells must be pairwise disjoint for the bound to be additive")
        seen |= members

    total, detail = 0.0, []
    for cell_index, edges in sorted(confusable_edges.items()):
        if not edges:
            continue
        cell = cells[cell_index]
        members = set(cell)
        stray = [(u, v) for u, v in edges if u not in members or v not in members]
        if stray:
            raise ValueError(
                f"cell {cell_index} was given {len(stray)} edge(s) whose blocks it does not "
                "contain; the per-cell minima would no longer be additive"
            )
        cover_weight, cover = minimum_weight_vertex_cover(cell, edges, post_route_cost)
        total += cover_weight
        detail.append({
            "cell_index": cell_index,
            "cell_size": len(cell),
            "confusable_edges": len(edges),
            "min_weight_vertex_cover": cover_weight,
            "cover_size": len(cover),
        })
    return total, tuple(detail)
