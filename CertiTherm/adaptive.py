"""Exact minimax adaptive limit for a finite, explicitly quantized world set."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import inf
from typing import Sequence, Tuple


@dataclass(frozen=True)
class AdaptiveLimit:
    status: str
    worst_case_cost: float
    first_action: str
    states_evaluated: int


def finite_adaptive_limit(
    decisions: Sequence[str],
    action_ids: Sequence[str],
    outcomes: Sequence[Sequence[str]],
    costs: Sequence[float],
) -> AdaptiveLimit:
    """Solve the exact worst-case decision tree by Bellman recursion.

    `outcomes[a][w]` is the quantized result of action `a` in world `w`.
    This routine makes no continuous-world claim.
    """

    world_count = len(decisions)
    if world_count == 0 or len(action_ids) != len(outcomes) or len(costs) != len(action_ids):
        raise ValueError("nonempty worlds and aligned actions/outcomes/costs are required")
    if any(len(row) != world_count for row in outcomes) or any(cost <= 0 for cost in costs):
        raise ValueError("every action must cover every world at positive cost")
    policy = {}

    @lru_cache(maxsize=None)
    def solve(worlds: Tuple[int, ...], available: Tuple[int, ...]) -> float:
        if len({decisions[world] for world in worlds}) == 1:
            return 0.0
        best = inf
        best_action = -1
        for action in available:
            branches = {}
            for world in worlds:
                branches.setdefault(outcomes[action][world], []).append(world)
            if len(branches) == 1:
                continue
            remaining = tuple(index for index in available if index != action)
            value = float(costs[action]) + max(
                solve(tuple(branch), remaining) for branch in branches.values()
            )
            if value < best:
                best, best_action = value, action
        policy[(worlds, available)] = best_action
        return best

    initial_worlds = tuple(range(world_count))
    initial_actions = tuple(range(len(action_ids)))
    value = solve(initial_worlds, initial_actions)
    first = policy.get((initial_worlds, initial_actions), -1)
    return AdaptiveLimit(
        "OPTIMAL" if value < inf else "UNSYNTHESIZABLE",
        value,
        action_ids[first] if first >= 0 else "",
        solve.cache_info().currsize,
    )
