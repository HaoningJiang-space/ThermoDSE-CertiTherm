"""The LP rows that encode "this power map is thermally safe", and their two-world lift.

Two consumers need these and nothing else from each other: `synthesis`, which builds the
collision LP, and `thermal_kernel`, which validates a reduced SAFE-row subset against the
full set. Before this module the second imported them from the first, and `synthesis` had
to import `thermal_kernel` lazily inside a function to break the resulting load cycle --
the only import cycle in the package. Neither of these functions depends on synthesis or on
kernels, so they belong below both.

Layer position: depends only on `core`. Nothing here solves, searches, or decides; it turns
a `PowerPolytope` and a `ThermalFamily` into coefficient matrices.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from .core import PowerPolytope, ThermalFamily


def two_world_polytope_rows(
    polytope: PowerPolytope,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Lift the polytope's own constraints onto the variable pair `(p_safe, p_unsafe)`.

    A collision is a statement about TWO power maps at once, so the LP variable is their
    concatenation and every original constraint must hold of each half independently. That
    is a block-diagonal duplication: `[[A, 0], [0, A]]` against `[b, b]`.

    Returns `(a_eq, b_eq, a_ub, b_ub)` in that order, each already doubled. Every returned
    array is freshly allocated and owns its data -- callers freeze some of them with
    `flags.writeable = False`, which would corrupt the frozen `PowerPolytope` if they were
    views onto it.
    """

    n = polytope.dimension
    zeros_eq = np.zeros((polytope.a_eq.shape[0], n))
    a_eq = np.vstack(
        (np.hstack((polytope.a_eq, zeros_eq)), np.hstack((zeros_eq, polytope.a_eq)))
    )
    b_eq = np.concatenate((polytope.b_eq, polytope.b_eq))
    zeros_ub = np.zeros((polytope.a_ub.shape[0], n))
    a_ub = np.vstack(
        (np.hstack((polytope.a_ub, zeros_ub)), np.hstack((zeros_ub, polytope.a_ub)))
    )
    b_ub = np.concatenate((polytope.b_ub, polytope.b_ub))
    return a_eq, b_eq, a_ub, b_ub


def robust_safe_cell_rows(
    thermal: ThermalFamily, margin_k: float
) -> Tuple[np.ndarray, np.ndarray]:
    """All model/point upper bounds defining one fail-closed SAFE cell.

    One row per (model, evaluation point): `response . p <= limit - margin - error -
    ambient`. Both the safety margin and the model-error band are subtracted from the
    right-hand side, so each tightens the constraint. That direction is the fail-closed one
    -- error can only make a power map harder to call safe, never easier.

    Row order is `reshape(-1)` over (model, point), which is what
    `VerifiedThermalKernel.safe_row_indices` indexes into. Changing it would silently
    reinterpret every committed kernel artifact.
    """

    rows = thermal.response_k_per_w.reshape(-1, thermal.blocks)
    rhs = (
        thermal.limit_k
        - margin_k
        - thermal.error_k[:, None]
        - thermal.ambient_k
    ).reshape(-1)
    return rows, rhs


def reject_cell_rows(
    thermal: ThermalFamily, margin_k: float
) -> Tuple[np.ndarray, np.ndarray]:
    """Every (model, point) REJECT row and its floor, one row per cell.

    **What REJECT means here, precisely, because the name overstates it.** With a model error
    bounded by `e`, a GUARANTEED-safe verdict needs `T_model <= limit - e` and a GUARANTEED-unsafe
    one needs `T_model >= limit + e`. This floor SUBTRACTS `e`, so crossing it proves only that the
    true temperature COULD exceed the limit -- "not certifiably safe", not "proven unsafe". That is
    the correct predicate for a fail-closed acceptance policy, which must refuse anything it cannot
    certify, and it is what the whole pipeline decides. Prose reading REJECT as a physical rejection
    overstates it; peer review found the conflation.

    The sign of `margin_k` is what keeps the SAFE and REJECT cells from overlapping -- this adds it
    where `robust_safe_cell_rows` subtracts it -- and the two are written next to each other so a
    drift in one is visible against the other. A scalar `reject_cell_floor` used to sit here as a
    third statement of the same expression; it had no callers and no test tying it to this matrix,
    so its claim that the two "cannot disagree" was unchecked. Deleted rather than left as an
    unverified duplicate.

    Row order is `reshape(-1)` over (models, points), matching `robust_safe_cell_rows`, so
    a flat index `i` refers to model `i // points` and point `i % points`. Kernel artifacts
    store `reject_specs` as that decomposition, so the order is part of their format.
    """

    response = thermal.response_k_per_w
    models, points = response.shape[0], response.shape[1]
    rows = response.reshape(-1, thermal.blocks)
    floors = (
        thermal.limit_k
        + margin_k
        - thermal.error_k[:, None]
        - thermal.ambient_k
    ).reshape(-1)
    # rows and floors are both `reshape(-1)` of the same (models, points) grid, so their
    # lengths agree by construction rather than by check.
    del models, points
    return rows, floors
