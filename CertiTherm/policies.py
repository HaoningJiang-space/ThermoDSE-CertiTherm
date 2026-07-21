"""Matched approximate policies measured against the exact DSOS limit."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing import get_context
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from .core import CandidateSpace, MeasurementAction, PowerPolytope, WorldPair
from .synthesis import _collision, _configured_workers, _required_candidate_indices


@dataclass(frozen=True)
class PolicyResult:
    status: str
    selected_action_ids: Tuple[str, ...]
    cost: float
    oracle_calls: int


def _width_score(
    task: Tuple[int, MeasurementAction, PowerPolytope, int]
) -> Tuple[float, int, str, int]:
    index, action, polytope, candidate_rank = task
    kwargs = dict(
        A_ub=polytope.a_ub,
        b_ub=polytope.b_ub,
        A_eq=polytope.a_eq,
        b_eq=polytope.b_eq,
        bounds=list(zip(polytope.lower_w, polytope.upper_w)),
        method="highs",
    )
    lower = linprog(action.vector, **kwargs)
    upper = linprog(-action.vector, **kwargs)
    if not lower.success or not upper.success:
        raise RuntimeError("width baseline LP unresolved")
    width = -float(upper.fun) - float(lower.fun)
    return width / action.cost, candidate_rank, action.action_id, index


def _cut(
    candidate_id: str,
    witness: WorldPair,
    actions: Sequence[MeasurementAction],
    separation_tolerance: float,
) -> np.ndarray:
    delta = witness.safe_power_w - witness.unsafe_power_w
    return np.asarray(
        [
            action.candidate_id == candidate_id
            and abs(float(action.vector @ delta))
            > action.tolerance + separation_tolerance
            for action in actions
        ],
        dtype=float,
    )


def _local_collision(
    candidates: Sequence[CandidateSpace],
    actions: Sequence[MeasurementAction],
    selected: Sequence[int],
    required: Sequence[int],
    margin_k: float,
    feasibility_tolerance: float,
    cache: Dict[Tuple[int, Tuple[int, ...]], Optional[WorldPair]],
) -> Optional[Tuple[str, WorldPair]]:
    selected_set = set(selected)
    for candidate_index in required:
        candidate = candidates[candidate_index]
        global_indices = tuple(
            index
            for index, action in enumerate(actions)
            if action.candidate_id == candidate.candidate_id
        )
        local_selected = tuple(
            local
            for local, index in enumerate(global_indices)
            if index in selected_set
        )
        key = candidate_index, local_selected
        if key not in cache:
            cache[key] = _collision(
                candidate.power,
                candidate.thermal,
                tuple(actions[index] for index in global_indices),
                local_selected,
                margin_k,
                feasibility_tolerance,
            )
        if cache[key] is not None:
            return candidate.candidate_id, cache[key]
    return None


def sequential_early_stop(
    candidates: Sequence[CandidateSpace],
    actions: Sequence[MeasurementAction],
    order: Sequence[int],
    *,
    margin_k: float = 1e-4,
    feasibility_tolerance: float = 1e-10,
    separation_tolerance: float = 1e-9,
) -> PolicyResult:
    """Return the same first certified prefix as literal sequential replay.

    Certification is monotone under adding observations. Bisection therefore
    finds the exact early-stop prefix with logarithmically many oracle calls;
    it changes evaluation time, not policy order, selected channels, or cost.
    """

    cache = {}
    required = _required_candidate_indices(
        candidates, margin_k, feasibility_tolerance
    )
    calls = 0

    def collision(prefix: int) -> Optional[Tuple[str, WorldPair]]:
        nonlocal calls
        calls += 1
        return _local_collision(
            candidates,
            actions,
            tuple(order[:prefix]),
            required,
            margin_k,
            feasibility_tolerance,
            cache,
        )

    if collision(0) is None:
        return PolicyResult("CERTIFIED", (), 0.0, calls)
    if collision(len(order)) is not None:
        selected = tuple(order)
        return PolicyResult(
            "UNSYNTHESIZABLE",
            tuple(actions[index].action_id for index in selected),
            sum(actions[index].cost for index in selected),
            calls,
        )
    low, high = 0, len(order)
    while high - low > 1:
        middle = (low + high) // 2
        if collision(middle) is None:
            high = middle
        else:
            low = middle
    selected = tuple(order[:high])
    return PolicyResult(
        "CERTIFIED",
        tuple(actions[index].action_id for index in selected),
        sum(actions[index].cost for index in selected),
        calls,
    )


def uncertainty_width_order(
    candidates: Sequence[CandidateSpace],
    actions: Sequence[MeasurementAction],
    *,
    workers: Optional[int] = None,
) -> Tuple[int, ...]:
    """Order by obtainable measurement range per cost; no decision information."""

    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    candidate_rank = {
        candidate.candidate_id: rank for rank, candidate in enumerate(candidates)
    }

    worker_count = min(_configured_workers(workers), len(actions))
    tasks = tuple(
        (
            index,
            action,
            candidate_map[action.candidate_id].power,
            candidate_rank[action.candidate_id],
        )
        for index, action in enumerate(actions)
    )
    with ProcessPoolExecutor(
        max_workers=worker_count,
        mp_context=get_context("spawn"),
    ) as pool:
        scores = list(pool.map(_width_score, tasks, chunksize=4))
    return tuple(
        item[3] for item in sorted(scores, key=lambda item: (-item[0], item[1], item[2]))
    )


def dual_price_greedy(
    candidates: Sequence[CandidateSpace],
    actions: Sequence[MeasurementAction],
    *,
    margin_k: float = 1e-4,
    feasibility_tolerance: float = 1e-10,
    separation_tolerance: float = 1e-9,
) -> PolicyResult:
    """Greedy zero-error InfoCertGain using decision-cut LP dual prices."""

    costs = np.asarray([action.cost for action in actions])
    selected, cuts, cache = [], [], {}
    required = _required_candidate_indices(
        candidates, margin_k, feasibility_tolerance
    )
    for calls in range(len(actions) + 1):
        witness = _local_collision(
            candidates,
            actions,
            selected,
            required,
            margin_k,
            feasibility_tolerance,
            cache,
        )
        if witness is None:
            return PolicyResult(
                "CERTIFIED",
                tuple(actions[index].action_id for index in selected),
                sum(actions[index].cost for index in selected),
                calls + 1,
            )
        cut = _cut(witness[0], witness[1], actions, separation_tolerance)
        if not np.any(cut):
            return PolicyResult(
                "UNSYNTHESIZABLE",
                tuple(actions[index].action_id for index in selected),
                sum(actions[index].cost for index in selected),
                calls + 1,
            )
        cuts.append(cut)
        cover = np.asarray(cuts)
        unresolved = (
            np.sum(cover[:, selected], axis=1) == 0
            if selected
            else np.ones(len(cover), dtype=bool)
        )
        residual = cover[unresolved]
        bounds = [(0.0, 0.0) if index in selected else (0.0, 1.0) for index in range(len(actions))]
        relaxation = linprog(
            costs,
            A_ub=-residual,
            b_ub=-np.ones(len(residual)),
            bounds=bounds,
            method="highs",
        )
        if not relaxation.success:
            return PolicyResult("UNRESOLVED", (), float("nan"), calls + 1)
        dual = -np.asarray(relaxation.ineqlin.marginals)
        score = residual.T @ dual / costs
        score[selected] = -np.inf
        next_index = int(np.argmax(score))
        if not np.isfinite(score[next_index]) or score[next_index] <= 0:
            separators = np.flatnonzero(cut)
            unselected = [index for index in separators if index not in selected]
            if not unselected:
                return PolicyResult("UNRESOLVED", (), float("nan"), calls + 1)
            next_index = min(unselected, key=lambda index: (costs[index], index))
        selected.append(next_index)
    return PolicyResult("UNRESOLVED", (), float("nan"), len(actions) + 1)
