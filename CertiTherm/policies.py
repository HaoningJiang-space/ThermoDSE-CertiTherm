"""Matched approximate policies measured against the exact DSOS limit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from .core import CandidateSpace, MeasurementAction
from .synthesis import _query_collision


@dataclass(frozen=True)
class PolicyResult:
    status: str
    selected_action_ids: Tuple[str, ...]
    cost: float
    oracle_calls: int


def _cut(witness, actions: Sequence[MeasurementAction], separation_tolerance: float) -> np.ndarray:
    pairs = {pair.candidate_id: pair for pair in witness.candidates}
    return np.asarray(
        [
            abs(
                float(
                    action.vector
                    @ (
                        pairs[action.candidate_id].left_power_w
                        - pairs[action.candidate_id].right_power_w
                    )
                )
            )
            > action.tolerance + separation_tolerance
            for action in actions
        ],
        dtype=float,
    )


def sequential_early_stop(
    candidates: Sequence[CandidateSpace],
    actions: Sequence[MeasurementAction],
    order: Sequence[int],
    *,
    margin_k: float = 1e-4,
    feasibility_tolerance: float = 1e-10,
    separation_tolerance: float = 1e-9,
) -> PolicyResult:
    """Fair fixed/width baseline: same oracle, and stop immediately when certified."""

    selected = []
    for calls in range(len(order) + 1):
        witness = _query_collision(
            candidates, actions, selected, margin_k, feasibility_tolerance
        )
        if witness is None:
            return PolicyResult(
                "CERTIFIED",
                tuple(actions[index].action_id for index in selected),
                sum(actions[index].cost for index in selected),
                calls + 1,
            )
        if calls == len(order):
            return PolicyResult(
                "UNSYNTHESIZABLE",
                tuple(actions[index].action_id for index in selected),
                sum(actions[index].cost for index in selected),
                calls + 1,
            )
        selected.append(order[calls])
    raise AssertionError("unreachable")


def uncertainty_width_order(
    candidates: Sequence[CandidateSpace], actions: Sequence[MeasurementAction]
) -> Tuple[int, ...]:
    """Order by obtainable measurement range per cost; no decision information."""

    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    candidate_rank = {
        candidate.candidate_id: rank for rank, candidate in enumerate(candidates)
    }
    scores = []
    for index, action in enumerate(actions):
        polytope = candidate_map[action.candidate_id].power
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
        scores.append(
            (
                width / action.cost,
                candidate_rank[action.candidate_id],
                action.action_id,
                index,
            )
        )
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
    selected, cuts = [], []
    for calls in range(len(actions) + 1):
        witness = _query_collision(
            candidates, actions, selected, margin_k, feasibility_tolerance
        )
        if witness is None:
            return PolicyResult(
                "CERTIFIED",
                tuple(actions[index].action_id for index in selected),
                sum(actions[index].cost for index in selected),
                calls + 1,
            )
        cut = _cut(witness, actions, separation_tolerance)
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
