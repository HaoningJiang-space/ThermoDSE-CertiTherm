"""Frozen-oracle adapter: wraps CertiTherm's exact scipy/HiGHS collision LP
to produce adversarial witnesses for the differentiable gate layer in gate.py.

The oracle itself is never modified, approximated, or made differentiable
here -- `_state_collision` runs exactly as CertiTherm.synthesis defines it.
gate.py only ever sees a witness's power delta as a fixed constant (Danskin's
theorem); nothing here differentiates through the LP that produced it.

Dependency-fragility note: `_state_collision` is a private (underscore)
function of CertiTherm.synthesis. That's a deliberate choice (it's the exact,
already-validated collision construction -- reimplementing SAFE/REJECT
thermal-row assembly independently here would risk silently drifting from
the real physics), but it means a future refactor of synthesis.py can break
this file without any public-API contract violation. If that happens, re-read
`CertiTherm/synthesis.py::_state_collision` and update the call here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from CertiTherm.core import CandidateSpace, MeasurementAction
from CertiTherm.synthesis import _state_collision

DEFAULT_MARGIN_K = 1e-4
DEFAULT_FEASIBILITY_TOLERANCE = 1e-10


@dataclass(frozen=True)
class Witness:
    """One SAFE/REJECT (or other state-pair) collision world pair, as plain
    numpy arrays -- decoupled from CertiTherm's dataclasses so gate.py/train.py
    don't need to import CertiTherm.core beyond what oracle.py already does."""

    delta_w: np.ndarray  # left_power_w - right_power_w
    left_model_id: str
    right_model_id: str


def local_actions(actions: Sequence[MeasurementAction], candidate: CandidateSpace) -> List[MeasurementAction]:
    """Filter to this candidate's own actions, in their given order -- matches
    the local-indexing convention `_state_collision`/`_query_collision` use."""
    return [action for action in actions if action.candidate_id == candidate.candidate_id]


def action_geometry(actions: Sequence[MeasurementAction]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Stack (vectors, tolerances, costs) for a candidate-local action list, in order."""
    vectors = np.stack([action.vector for action in actions])
    tolerances = np.asarray([action.tolerance for action in actions])
    costs = np.asarray([action.cost for action in actions])
    return vectors, tolerances, costs


def find_witness(
    candidate: CandidateSpace,
    actions: Sequence[MeasurementAction],
    selected: Sequence[int],
    left_state: str = "SAFE",
    right_state: str = "REJECT",
    margin_k: float = DEFAULT_MARGIN_K,
    feasibility_tolerance: float = DEFAULT_FEASIBILITY_TOLERANCE,
) -> Optional[Witness]:
    """Exact: does a collision survive the currently `selected` local action
    indices? `actions` must already be filtered to this candidate (see
    `local_actions`), matching `_state_collision`'s own convention.

    Returns None exactly when the exact oracle finds no collision -- i.e.
    `selected` already certifies this candidate's `left_state`/`right_state`
    decision boundary for this state pair.
    """
    pair = _state_collision(
        candidate, actions, selected, left_state, right_state, margin_k, feasibility_tolerance
    )
    if pair is None:
        return None
    return Witness(
        delta_w=pair.left_power_w - pair.right_power_w,
        left_model_id=pair.left_model_id,
        right_model_id=pair.right_model_id,
    )
