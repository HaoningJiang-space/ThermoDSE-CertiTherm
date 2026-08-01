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

## `block` is gated too, against the finest grid, because the gap was load-bearing

`block` has no refinement parameter, so the first version left it ungated -- and that hole turned
out to decide the answer. Measured on `6x2` cut 1x1 with the budget applied: the two charged grid
operators give `beta* = 5.796 %` and `6.448 %` while `block`, carrying only the 0.01 K linearisation
budget, gives **3.757 %** and sets the family minimum. Charging the models that were measured did not
protect the family, because the model that binds it was the one that escaped.

The repair uses a fact the first version missed: `block` and `gridN-avg` are two DISCRETISATIONS of
the same physics that both produce per-block temperatures, so they are directly comparable. `block`
is therefore gated against the FINEST grid in the family -- `reference_model_id` below -- and the
comparison costs nothing extra, since that replay already exists for the grid gate.

It is a weaker statement than the grid-to-grid one: `block` -> `grid256-avg` is not a refinement of
`block`, so the Richardson argument for the safety factor does not apply to it and the drift is used
as a plain lower bound on the disagreement. That is recorded rather than glossed.

## Budgeting beats refusing, at equal soundness

The first version of this module refused an operator whose drift exceeded the bound, and running it
refused **every** operator including the compact development controls
(`docs/DISCRETISATION_ERROR_EXCEEDS_THE_DECISION_BAND.md`). That is fail-closed but useless: it
produces no certificate at all, and it treats a large error as the defect when the actual defect is
an UNBUDGETED one.

`budgeted_error_k` is the repair. `thermal_constraints` already subtracts `error_k` from both the
SAFE and the REJECT right-hand sides, so folding the discretisation term in makes SAFE harder to
reach and REJECT easier -- fail-closed on both -- and yields a sound, weaker certificate instead of
none. The price shows up where it should: as a smaller robustness radius on an under-resolved
operator. Refusal is then reserved for a band so wide the decision is vacuous.

## Status

**Not wired into `experiments.py`.** That module is frozen under `method-freeze-radii-v1`, whose
split is already burned, and adding a gate to the operator build is a method change that requires a
new freeze ID and a fresh development run before any claim rests on it. This module is the
implementation and its tests; adopting it is the first item of the next round.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

import numpy as np

# The bound is separate from `MODEL_ERROR_LIMIT_K` on purpose. That one bounds linearisation error
# and is folded one-sidedly into every SAFE/REJECT row; this one bounds DISCRETISATION drift and
# does not enter the certificate at all -- it decides whether an operator may be built. Registering
# them as one number would make a change to either silently move the other.
GRID_DRIFT_LIMIT_K = 0.05

# `drift = |T_N - T_2N|` is NOT a bound on the operator's error `|T_N - T_inf|`. By the triangle
# inequality the true error is at most `drift + |T_2N - T_inf|`, and the second term is unmeasured
# here because there is no `4N`. Under the standard assumption that the scheme is at least
# first-order convergent and the refinement monotone, `|T_2N - T_inf| <= drift`, giving
# `|T_N - T_inf| <= 2 * drift`. That factor is the Richardson-style safety margin below.
#
# It is an ASSUMPTION, not a proof: a scheme that is not converging at all, or one whose error
# changes sign between refinements, breaks it. It is registered as a named constant rather than
# multiplied in silently so that a reader can see exactly what is being assumed and change it.
GRID_DRIFT_SAFETY_FACTOR = 2.0


def budgeted_error_k(linearisation_error_k: float, drift_k: float) -> float:
    """The model-error bound that covers BOTH error sources, for one operator.

    The frozen `MODEL_ERROR_LIMIT_K` budgets linearisation and nothing else, which is the defect
    this module exists to repair: an unbudgeted error is the problem, not a large one. Folding the
    discretisation term in here makes the certificate SOUND and weaker, rather than absent -- and
    `thermal_constraints` already subtracts `error_k` from BOTH the SAFE and the REJECT right-hand
    sides, so a larger budget makes SAFE harder to reach and REJECT easier, which is the fail-closed
    direction on both.

    Refusing the operator outright and budgeting it are both fail-closed. Budgeting is strictly more
    useful at equal soundness, so refusal is reserved for a band so wide the decision is vacuous --
    which the caller decides, since only it knows the ambient and the limit.

    **This function does not make a certificate sound, and an earlier version of this docstring said
    it did.** `drift_k` here comes from a maximum over five calibration vectors, and a maximum over
    five power maps is not a bound over the polytope the certificate quantifies over. Peer review
    caught the inconsistency. `CertiTherm/cross_grid_bound.py` computes the genuine polytope-wide
    supremum in closed form, per row, and is what a soundness claim must rest on; this remains a
    cheap per-model estimate for the operator-build gate. The Richardson factor is also assumed
    rather than established -- `CertiTherm/solution_verification.py` is where that assumption is
    tested, and it refuses two thirds of the measured registry.
    """

    if not math.isfinite(linearisation_error_k) or linearisation_error_k < 0.0:
        raise ValueError(
            f"the linearisation budget must be finite and nonnegative, got {linearisation_error_k}"
        )
    if not math.isfinite(drift_k) or drift_k < 0.0:
        raise ValueError(f"the measured drift must be finite and nonnegative, got {drift_k}")
    return linearisation_error_k + GRID_DRIFT_SAFETY_FACTOR * drift_k

_GRID = re.compile(r"^grid(\d+)(-.+)?$")


def reference_model_id(model_id: str, family_model_ids: Sequence[str]) -> str:
    """What `model_id` must be compared against: its own 2x refinement, or the finest grid.

    A `gridN` model is compared with `grid2N`, which is a genuine refinement and supports the
    Richardson factor. A model with no refinement parameter -- `block` -- is compared with the
    refinement of the finest grid in the family, because both produce per-block temperatures and are
    therefore two discretisations of the same physics. Leaving it out was a hole that decided a
    published radius; see the module docstring.
    """

    try:
        return refined_model_id(model_id)
    except ValueError:
        grids = [m for m in family_model_ids if _GRID.match(m)]
        if not grids:
            raise ValueError(
                f"{model_id!r} has no refinement parameter and the family contains no grid model "
                "to compare it against, so its discretisation error cannot be measured at all"
            )
        finest = max(grids, key=lambda m: int(_GRID.match(m).group(1)))
        return refined_model_id(finest)


def refined_model_id(model_id: str) -> str:
    """`gridN-avg` -> `grid2N-avg`. Raises for anything without a refinement parameter."""

    match = _GRID.match(model_id)
    if match is None:
        raise ValueError(
            f"{model_id!r} has no grid refinement parameter; use `reference_model_id` to compare "
            "it against the finest grid in its family instead"
        )
    size = int(match.group(1))
    if size <= 0:
        raise ValueError(f"{model_id!r} has a non-positive grid size")
    return f"grid{size * 2}{match.group(2) or ''}"


def grid_drift(
    replay: Callable[[str, np.ndarray], np.ndarray],
    model_id: str,
    vectors: Sequence[tuple[str, np.ndarray]],
    reference_id: Optional[str] = None,
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
    fine_id = reference_id or refined_model_id(model_id)
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
            reference = reference_model_id(model_id, model_ids)
        except ValueError:
            ungated.append(model_id)
            continue
        result = grid_drift(replay, model_id, vectors, reference_id=reference)
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
