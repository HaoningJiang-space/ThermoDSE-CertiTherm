"""The gate the frozen error contract cannot be: does a grid operator agree with a finer grid?

`experiments.py` calibrates each operator by replaying a power vector through the SAME `model_id`
and comparing against that model's own linear prediction:

    direct    = replay_power(..., model_id, ..., power)
    predicted = ambient[m] + response[m] @ power
    error     = max|direct - predicted|            PASS if <= MODEL_ERROR_LIMIT_K

That is a test of LINEARITY at a fixed discretisation. Both sides share the grid, so an operator
that is perfectly linear and badly under-resolved passes with an error near zero. Measured on a
`6x2` held-out architecture (`docs/GRID_CONVERGENCE_FINDING.md`): `grid128-avg` passed with a worst
calibration error of **0.0027 K**, 27 % of the budget, while its relocation radius differed from a
4x finer grid by **17 %**, and the cut ordering it induced was reversed. Two operators in the
certified family disagreed by up to 25 % with a finer grid on geometries the contract admitted
without complaint, and nothing in the pipeline ever compared an operator against a finer one.

This module is the missing comparison, and it is deliberately the CHEAP form of it. Rebuilding a
full `grid2N` impulse-response operator costs one HotSpot solve per block per model -- prohibitive.
What the contract actually needs is not a second operator but evidence that the TEMPERATURE FIELD is
resolved, and that needs only one extra replay per calibration vector:

    coarse = replay_power(..., "gridN-avg",  ..., power)
    fine   = replay_power(..., "grid2N-avg", ..., power)
    drift  = max|coarse - fine|                    PASS if <= limit

`len(CALIBRATION_VECTOR_IDS)` extra solves per grid model, against `n_blocks` for a full rebuild.

## What a PASS does and does not mean

A pass says the block-mapped steady field at `N` agrees with the field at `2N` on the calibration
vectors, to the registered bound. It does NOT say the operator is converged in any stronger sense:
there is no `4N` here, agreement between two successive refinements is the standard Richardson-style
check and not a proof, and the calibration vectors are five power maps rather than the whole
polytope. A REFUSAL, on the other hand, is decisive -- two resolutions of the same physics disagreed
by more than the bound, so at least one of them is wrong.

`block` has no refinement parameter and is therefore not gated here. That is a gap, not an
exemption: `block` was the outlier in one of the four groups measured, and nothing in this module
would catch it.

## Status

**Not wired into `experiments.py`.** That module is frozen under `method-freeze-radii-v1`, whose
split is already burned, and adding a gate to the operator build is a method change that requires a
new freeze ID and a fresh development run before any claim rests on it. This module is the
implementation and its tests; adopting it is the first item of the next round.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

# The bound is separate from `MODEL_ERROR_LIMIT_K` on purpose. That one bounds linearisation error
# and is folded one-sidedly into every SAFE/REJECT row; this one bounds DISCRETISATION drift and
# does not enter the certificate at all -- it decides whether an operator may be built. Registering
# them as one number would make a change to either silently move the other.
GRID_DRIFT_LIMIT_K = 0.05

_GRID = re.compile(r"^grid(\d+)(-.+)?$")


def refined_model_id(model_id: str) -> str:
    """`gridN-avg` -> `grid2N-avg`. Raises for anything without a refinement parameter."""

    match = _GRID.match(model_id)
    if match is None:
        raise ValueError(
            f"{model_id!r} has no grid refinement parameter, so it cannot be convergence-gated; "
            "`block` is the case this refers to and it is a known gap, not an exemption"
        )
    size = int(match.group(1))
    if size <= 0:
        raise ValueError(f"{model_id!r} has a non-positive grid size")
    return f"grid{size * 2}{match.group(2) or ''}"


def grid_drift(
    replay: Callable[[str, np.ndarray], np.ndarray],
    model_id: str,
    vectors: Sequence[tuple[str, np.ndarray]],
) -> dict:
    """Worst per-block disagreement between `model_id` and its 2x refinement, over the vectors.

    `replay` takes `(model_id, power)` and returns the per-block steady temperatures, so the caller
    owns the HotSpot invocation and this module stays testable without a binary.
    """

    if not vectors:
        raise ValueError(
            "convergence cannot be judged from zero calibration vectors; an empty vector list "
            "would report a drift of zero and pass every operator"
        )
    fine_id = refined_model_id(model_id)
    worst = 0.0
    worst_vector = None
    rows = []
    for vector_id, power in vectors:
        coarse = np.asarray(replay(model_id, power), dtype=float)
        fine = np.asarray(replay(fine_id, power), dtype=float)
        if coarse.shape != fine.shape:
            raise ValueError(
                f"{vector_id}: {model_id} returned {coarse.shape} blocks and {fine_id} returned "
                f"{fine.shape}; block-average mapping must preserve the block identity or the "
                "comparison is between different things"
            )
        # Finiteness first and separately: `nan > limit` is False, so a non-finite temperature
        # would pass the bound AND be recorded as the drift. Five instances of that shape are
        # already recorded in this repository.
        if not (np.all(np.isfinite(coarse)) and np.all(np.isfinite(fine))):
            raise ValueError(f"{vector_id}: {model_id} or {fine_id} returned a non-finite field")
        drift = float(np.max(np.abs(coarse - fine)))
        rows.append({"vector_id": vector_id, "drift_k": drift})
        if drift > worst:
            worst, worst_vector = drift, vector_id
    return {
        "model_id": model_id,
        "refined_model_id": fine_id,
        "worst_drift_k": worst,
        "worst_vector_id": worst_vector,
        "per_vector": rows,
    }


def gate(
    replay: Callable[[str, np.ndarray], np.ndarray],
    model_ids: Sequence[str],
    vectors: Sequence[tuple[str, np.ndarray]],
    limit_k: float = GRID_DRIFT_LIMIT_K,
) -> Mapping[str, object]:
    """Refuse the family unless every refinable operator agrees with its 2x refinement.

    Fail-closed in the same style as the linearity contract: the return carries `status` and every
    measured drift, and a caller that ignores `status` still has the numbers. Models without a
    refinement parameter are listed under `ungated` rather than silently passed, because a caller
    reading only `status` would otherwise believe `block` had been checked.
    """

    if not np.isfinite(limit_k) or limit_k <= 0.0:
        raise ValueError(f"the drift limit must be finite and positive, got {limit_k}")
    measured, ungated, refusals = [], [], []
    for model_id in model_ids:
        try:
            refined_model_id(model_id)
        except ValueError:
            ungated.append(model_id)
            continue
        result = grid_drift(replay, model_id, vectors)
        measured.append(result)
        if result["worst_drift_k"] > limit_k:
            refusals.append(
                f'{model_id} drifts {result["worst_drift_k"]:.4f} K from '
                f'{result["refined_model_id"]} on {result["worst_vector_id"]}, above {limit_k} K'
            )
    return {
        "status": "PASS" if not refusals else "REFUSED",
        "limit_k": limit_k,
        "measured": measured,
        "ungated": ungated,
        "refusals": refusals,
    }
