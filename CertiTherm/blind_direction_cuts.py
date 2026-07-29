"""Cuts along the power directions the coarse instrumentation is algebraically blind to.

An action separates a pair of worlds only through the difference it reads, `a . (p1 - p2)`. So
for two blocks b, c whose coefficient COLUMNS agree in every action that observes more than one
block, the direction `delta = t (e_b - e_c)` is invisible to all of them:

    a . delta = t * (a_b - a_c) = 0    for every such action

A collision along that direction can therefore be separated only by single-block actions on b or
on c -- the smallest non-trivial cut the hitting-set master can receive, and the only kind no
cheap coarse action can hit.

Two structural consequences, and they are what make this different in kind from accumulating
generic cuts:

* **Vertex cover.** Any certifying selection must instrument b or c for every confusable pair,
  so the instrumented blocks form a vertex cover of that cell's confusability graph. The bound
  is the cover's proven minimum weight -- not a quantity that grows logarithmically in the
  number of cuts discovered.
* **Additivity.** Cells partition the blocks and each cell's cuts mention only its own blocks'
  single-block actions, so the per-cell minima ADD. Disjoint supports are exactly what
  overlapping generic cuts lack.

This is NOT the retracted per-cell decomposition (`docs/PER_CELL_DECOMPOSITION_RETRACTED.md`).
Nothing is dropped from the thermal problem: every witness is validated against the FULL SAFE
conjunction over every (model, point). What decomposes here is the hitting-set supports, not the
physics.

Layer position: a research extension that imports FROM `synthesis`, in the same direction as
`kernelized_collision` and for the same reason -- deleting this file leaves the certified path
producing identical verdicts. Never add an import the other way.

**Composing with the bound `synthesize_minimum_observation` already reports is `max`, never a
sum.** Both lower-bound the SAME selection cost, and the generic cuts can be hit by the very
single-block actions this cover charges for, so adding them double-counts. The sound way to get
more than `max` is not arithmetic at all: seed these individual small cuts into the master's cut
ledger and let one hitting-set optimisation combine them with the discovered ones.

Exactness. Peer review's sharpest finding was that `validate_witness` tolerates worlds up to the
feasibility tolerance OUTSIDE the power polytope, so a witness accepted with slack does not
strictly prove that any selection fails on the original problem -- the thermal margin protects
the SAFE/REJECT classification but repairs no domain infeasibility. Witnesses here are therefore
repaired to exact rational feasibility and validated with ZERO slack; a pair whose witness cannot
be repaired is dropped rather than accepted conditionally.
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


@dataclass(frozen=True)
class BlindPairWitness:
    """One confusable pair, its exactly feasible worlds, and the reject cell that proves it.

    Both `cut_action_ids` and `cut_action_indices` are kept. An index is only meaningful for the
    exact action sequence used during certification -- deduplication, reordering or library
    regeneration can silently make the same index name a different action -- so anything stored
    or compared across runs must go through the IDs.
    """

    left_block: int
    right_block: int
    safe_power_w: Tuple[Fraction, ...]
    unsafe_power_w: Tuple[Fraction, ...]
    reject_model: int
    reject_point: int
    cut_action_indices: Tuple[int, ...]
    cut_action_ids: Tuple[str, ...]


def blind_direction_cells(
    actions: Sequence[MeasurementAction], block_count: int
) -> Tuple[Dict[int, Tuple[int, ...]], Tuple[Tuple[int, ...], ...]]:
    """Split the library into single-block actions, and group blocks no other action separates.

    An action counts as single-block when its coefficient vector has exactly one nonzero -- a
    property of the vector, not of the action's name. An earlier version classified by the
    `"::post_route::"` substring, which peer review rejected as too fragile for a load-bearing
    theorem: a renamed action would silently change the partition and therefore the bound.

    Cells group blocks whose coefficient COLUMNS are exactly equal across every multi-block
    action. Equality of columns, not of nonzero SUPPORT: two columns holding 1 and 2 share a
    support pattern, but `a . (e_b - e_c) = -1`, so that action does separate them and the two
    blocks do not belong in one cell.

    Returns `(single_block_actions_by_block, cells)`. A block with no single-block action still
    appears in its cell; `block_instrumentation_cost` refuses it, because a cover cannot charge
    for an action that does not exist.
    """

    by_block: Dict[int, List[int]] = {}
    multi: List[np.ndarray] = []
    for index, action in enumerate(actions):
        vector = np.asarray(action.vector, dtype=float)
        if vector.size != block_count:
            raise ValueError(
                f"action {action.action_id} has width {vector.size}, expected {block_count}"
            )
        support = np.flatnonzero(vector)
        if support.size == 1:
            by_block.setdefault(int(support[0]), []).append(index)
        else:
            multi.append(vector)
    matrix = np.asarray(multi) if multi else np.zeros((0, block_count))
    columns: Dict[Tuple[float, ...], List[int]] = {}
    for block in range(block_count):
        columns.setdefault(tuple(matrix[:, block].tolist()), []).append(block)
    cells = tuple(tuple(sorted(members)) for _, members in sorted(columns.items()))
    return {block: tuple(indices) for block, indices in by_block.items()}, cells


def block_instrumentation_cost(
    actions: Sequence[MeasurementAction],
    single_block_actions: Mapping[int, Sequence[int]],
    blocks: Iterable[int],
) -> Dict[int, Fraction]:
    """The cheapest way to instrument each block on its own, as an exact rational.

    A cut here is a subset of the two blocks' single-block actions, so hitting it costs at least
    the cheapest such action on one of them. Taking the minimum is what keeps the vertex weight a
    LOWER bound on what hitting through that block can cost. Rational rather than float because
    the result is published as a certified bound, and an ulp of upward drift in a float sum would
    technically place it above the mathematical optimum.
    """

    costs: Dict[int, Fraction] = {}
    for block in blocks:
        indices = single_block_actions.get(block, ())
        if not indices:
            raise ValueError(
                f"block {block} has no single-block action, so a cover cannot charge for it"
            )
        costs[block] = min(Fraction(float(actions[i].cost)) for i in indices)
    return costs


def minimum_weight_vertex_cover(
    vertices: Sequence[int],
    edges: Sequence[Tuple[int, int]],
    weight: Mapping[int, Fraction],
    node_budget: int = 2_000_000,
) -> Tuple[Fraction, Tuple[int, ...]]:
    """PROVEN minimum-weight vertex cover, by branching on a still-uncovered edge.

    Exact rather than the usual matching lower bound because a cell holds tens of blocks, and the
    recursion depth is the cover size rather than the vertex count: pick any uncovered edge, and
    every cover must take one of its two endpoints. Weights are rationals, so the comparisons and
    the accumulated total are exact.

    **The search must run to proven optimality or fail.** Any feasible cover's weight is an UPPER
    bound on the minimum, so returning an incumbent after a truncated search and using it as a
    lower bound on observation cost would overstate it -- the one direction in which this whole
    construction can be unsound rather than merely weak. Peer review named this as the principal
    overestimation risk. Exhausting `node_budget` raises `UnresolvedComputation`, which is the
    package's UNRESOLVED status and not a number.
    """

    for vertex in vertices:
        if vertex not in weight:
            raise ValueError(f"vertex {vertex} has no weight")
        if weight[vertex] < 0:
            raise ValueError(f"vertex {vertex} has a negative weight")
    for left, right in edges:
        if left == right:
            raise ValueError("a self-edge cannot be covered by choosing one of two endpoints")
        if left not in weight or right not in weight:
            raise ValueError(f"edge ({left}, {right}) names a vertex with no weight")
    best_weight: Optional[Fraction] = None
    best_cover: Tuple[int, ...] = ()
    nodes = 0

    def branch(chosen: Tuple[int, ...], chosen_weight: Fraction, pending: List[Tuple[int, int]]):
        nonlocal best_weight, best_cover, nodes
        nodes += 1
        if nodes > node_budget:
            raise UnresolvedComputation(
                f"vertex cover search exceeded {node_budget} nodes; an incumbent cover is an "
                "upper bound on the minimum and must not be reported as a lower bound"
            )
        if best_weight is not None and chosen_weight >= best_weight:
            return
        taken = set(chosen)
        uncovered = [(u, v) for u, v in pending if u not in taken and v not in taken]
        if not uncovered:
            best_weight, best_cover = chosen_weight, chosen
            return
        left, right = uncovered[0]
        first, second = (left, right) if weight[left] <= weight[right] else (right, left)
        for pick in (first, second):
            branch(chosen + (pick,), chosen_weight + weight[pick], uncovered)

    branch((), Fraction(0), list(edges))
    return (Fraction(0) if best_weight is None else best_weight), best_cover


def _exactly_feasible_pair(
    safe_float: Sequence[float],
    step: Fraction,
    block_pair: Tuple[int, int],
    polytope: PowerPolytope,
) -> Optional[Tuple[Tuple[Fraction, ...], Tuple[Fraction, ...]]]:
    """Repair an LP witness into two EXACTLY power-feasible rational worlds, or give up.

    `validate_witness` accepts a world up to the feasibility tolerance outside the polytope, and
    such a world does not strictly prove that any selection fails on the original problem. So the
    proposal is repaired here and validated with zero slack afterwards.

    The repair adds the SAME correction to both worlds, which leaves `delta` -- and therefore the
    cut, and therefore the whole argument -- untouched. It clamps into the box and then removes a
    single equality residual through one coordinate outside the pair. That covers the polytope
    this project actually uses (`box_with_total`: one total-power row, no inequality rows);
    anything else returns None rather than an unrepaired pair, because a bound is not worth a
    silent exception.
    """

    left, right = block_pair
    lower = tuple(Fraction(float(v)) for v in polytope.lower_w)
    upper = tuple(Fraction(float(v)) for v in polytope.upper_w)
    a_eq = np.asarray(polytope.a_eq, dtype=float)
    if a_eq.shape[0] != 1 or np.asarray(polytope.a_ub, dtype=float).shape[0] != 0:
        return None
    row = tuple(Fraction(float(v)) for v in a_eq[0])
    target = Fraction(float(np.asarray(polytope.b_eq, dtype=float)[0]))
    if row[left] != row[right]:
        # The blind direction would move the two worlds off the equality by different amounts,
        # so no common correction can place both of them on it.
        return None

    safe = [min(max(Fraction(float(v)), lower[i]), upper[i]) for i, v in enumerate(safe_float)]
    residual = target - sum(r * p for r, p in zip(row, safe))
    if residual != 0:
        for j in range(len(safe)):
            if j in (left, right) or row[j] == 0:
                continue
            shifted = safe[j] + residual / row[j]
            if lower[j] <= shifted <= upper[j]:
                safe[j] = shifted
                break
        else:
            return None

    unsafe = list(safe)
    unsafe[left] = safe[left] - step
    unsafe[right] = safe[right] + step
    for world in (safe, unsafe):
        for i, value in enumerate(world):
            if value < lower[i] or value > upper[i]:
                return None
        if sum(r * p for r, p in zip(row, world)) != target:
            return None
    return tuple(safe), tuple(unsafe)


def certify_blind_pair(
    polytope: PowerPolytope,
    thermal: ThermalFamily,
    actions: Sequence[MeasurementAction],
    block_pair: Tuple[int, int],
    single_block_actions: Mapping[int, Sequence[int]],
    reject_specs: Iterable[Tuple[int, int]],
    margin_k: float,
    feasibility_tolerance: float,
) -> Optional[BlindPairWitness]:
    """Prove that no selection instrumenting NEITHER block of a pair can certify.

    The delta's shape is imposed on the collision LP as equalities -- `delta_c = 0` off the pair,
    and `delta_left + delta_right = 0` so an action holding both blocks reads zero rather than
    their sum. Constraining the shape is necessary, not merely convenient: an action constraint
    is `|a . delta| <= tol_a`, not an equality, so simply omitting the two actions from the
    selection lets the LP spread the delta across every block. Measured on the real instance, the
    first witness obtained that way had a NINE-action exact cut, seven of them coarse -- and one
    coarse action in the cut collapses the bound, since the master can hit it for 1.0 instead of
    two single-block actions for 8.0.

    The LP result is then treated as a PROPOSAL, never as evidence: the safe world is snapped to
    rationals, repaired to exact polytope feasibility, and the unsafe world is rebuilt as
    `safe - t (e_left - e_right)` so the delta is exactly along the blind direction. Both worlds
    are re-proved from scratch by `validate_witness` with ZERO slack, and the cut is recomputed by
    `separator_set`. Only then does the pair count.

    Returns None when no scanned reject cell yields a witness, the repair fails, validation
    fails, or the step falls at or below an action's tolerance. All of those are "not
    established", never "not confusable": callers only ever need positives, so a negative is
    never used as a claim.
    """

    left, right = block_pair
    if left == right:
        raise ValueError("a blind direction needs two distinct blocks")
    left_actions = set(single_block_actions.get(left, ()))
    right_actions = set(single_block_actions.get(right, ()))
    admissible = left_actions | right_actions
    if not left_actions or not right_actions:
        return None
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

    for model, point in reject_specs:
        witness = _solve_collision_spec(shaped, (model, point))
        if witness is None:
            continue
        step = Fraction(float(witness.safe_power_w[left])) - Fraction(
            float(witness.unsafe_power_w[left])
        )
        if step == 0:
            continue
        repaired = _exactly_feasible_pair(witness.safe_power_w, step, block_pair, polytope)
        if repaired is None:
            continue
        safe_w, unsafe_w = repaired
        try:
            validate_witness(
                safe_w, unsafe_w, model, point, polytope, thermal, margin_k, Fraction(0)
            )
            cut = separator_set(safe_w, unsafe_w, actions, Fraction(0))
        except (CertificateError, CertificateUnresolved):
            continue
        if not set(cut) <= admissible:
            raise CertificateError(
                f"a blind-direction witness for blocks {left} and {right} separated an action "
                "observing neither of them alone; the cell partition and the action library "
                "disagree"
            )
        if not (set(cut) & left_actions) or not (set(cut) & right_actions):
            # One side's own instruments do not read the step, so instrumenting the other side
            # alone already separates this witness and the edge would constrain nothing.
            continue
        return BlindPairWitness(
            left_block=left,
            right_block=right,
            safe_power_w=safe_w,
            unsafe_power_w=unsafe_w,
            reject_model=model,
            reject_point=point,
            cut_action_indices=tuple(sorted(cut)),
            cut_action_ids=tuple(actions[i].action_id for i in sorted(cut)),
        )
    return None


def blind_direction_lower_bound(
    cells: Sequence[Sequence[int]],
    confusable_edges: Mapping[int, Sequence[Tuple[int, int]]],
    block_cost: Mapping[int, Fraction],
) -> Tuple[Fraction, Tuple[dict, ...]]:
    """Sum each cell's proven minimum-weight cover -- valid because the cells are disjoint.

    `confusable_edges` maps a cell's index to the pairs established by `certify_blind_pair`.
    Cells with no established edge contribute nothing, which is why an incomplete scan can only
    understate the bound.

    Additivity is the one place this can go UNSOUND rather than merely weak: if two summed cells
    shared a block, that block's instrumentation would be charged twice and the total could
    exceed the true optimum. Both preconditions are checked here rather than assumed of the
    caller -- the cells must be pairwise disjoint, and every edge must join two blocks of the
    cell it is filed under.
    """

    seen: set = set()
    for cell in cells:
        members = set(cell)
        if len(members) != len(cell) or members & seen:
            raise ValueError("cells must be pairwise disjoint for the bound to be additive")
        seen |= members

    total, detail = Fraction(0), []
    for cell_index, edges in sorted(confusable_edges.items()):
        if not edges:
            continue
        if not 0 <= cell_index < len(cells):
            raise ValueError(f"edges were filed under nonexistent cell {cell_index}")
        cell = cells[cell_index]
        members = set(cell)
        stray = [(u, v) for u, v in edges if u not in members or v not in members]
        if stray:
            raise ValueError(
                f"cell {cell_index} was given {len(stray)} edge(s) whose blocks it does not "
                "contain; the per-cell minima would no longer be additive"
            )
        cover_weight, cover = minimum_weight_vertex_cover(cell, edges, block_cost)
        total += cover_weight
        detail.append({
            "cell_index": cell_index,
            "cell_size": len(cell),
            "confusable_edges": len(edges),
            "min_weight_vertex_cover": float(cover_weight),
            "cover_size": len(cover),
        })
    return total, tuple(detail)
