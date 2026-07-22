"""Discretization of trained gate probabilities into a concrete action-index
tuple. Pure numpy -- no torch dependency, so this stays testable even before
torch is available. Always re-verify the result with the exact oracle
(oracle.find_witness); this never certifies anything by itself.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

import numpy as np


def greedy_cover_rounding(
    gates: np.ndarray,
    cost: np.ndarray,
    coverage: np.ndarray,
    budget: Optional[float] = None,
) -> Tuple[int, ...]:
    """Round by adding actions in descending gate/cost order, STOPPING as soon
    as every pooled witness is covered.

    This is the rounding that matters. Plain thresholding at 0.5 fails on the
    symmetric case: when several actions are interchangeable, the relaxation's
    optimum is symmetric and fractional (for two equivalent unit-cost actions
    covering one witness, both gates converge to 0.75), so a 0.5 threshold
    takes ALL of them when one would do. Observed on the first real run:
    `selected=(0,1)`, proxy_cost 2.0 against an exact optimum of 1.0.

    Ordering by the learned `gates / cost` and stopping at full coverage keeps
    what the relaxation actually learned (the preference order) while
    restoring the one property thresholding destroys (minimality). It is the
    same greedy stopping rule `CertiTherm.synthesis._greedy_cover` uses, with
    the learned score replacing the pure cost-effectiveness heuristic.

    `coverage` is the HARD (0/1) separation matrix, shape (witnesses, actions).
    Returns candidate-local indices, sorted.
    """
    order = np.argsort(-(gates / np.clip(cost, 1e-12, None)), kind="stable")
    uncovered = np.ones(coverage.shape[0], dtype=bool)
    selected: list[int] = []
    spend = 0.0
    for index in order:
        if not uncovered.any():
            break
        if not coverage[uncovered, index].any():
            continue  # covers nothing still-uncovered
        if budget is not None and spend + cost[index] > budget:
            continue
        selected.append(int(index))
        spend += float(cost[index])
        uncovered &= ~coverage[:, index].astype(bool)
    return tuple(sorted(selected))
