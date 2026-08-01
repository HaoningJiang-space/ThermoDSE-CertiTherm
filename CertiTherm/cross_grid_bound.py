"""How far two grids can disagree ANYWHERE in the power polytope, per row, in closed form.

The previous discretisation budget took `max |T_N - T_2N|` over five calibration vectors and called
the resulting certificate sound. Peer review was right that those two statements are inconsistent: a
maximum over five power maps is not a bound over the polytope the certificate quantifies over, and
the certificate quantifies over all of it.

Because the thermal model is LINEAR the correct object is available exactly. Writing `A_c`, `A_f`
for the coarse and fine response matrices over the same blocks and `b_c`, `b_f` for their ambients,
row `j`'s cross-grid discrepancy at a power map `p` is

    d_j(p) = (A_c[j] - A_f[j]) . p + (b_c[j] - b_f[j])

which is affine in `p`. Its supremum over the polytope is therefore attained at a vertex, and for
the box-with-total-power polytope this project uses -- `lower <= p <= upper`, `1.p = total` -- both
the maximum and the minimum are found by the same greedy fill that `l1_body` and `threshold` already
use for reachability: sort by coefficient, push power to the extreme. No solver, one pass per row.

**This is a bound over the whole polytope and it is per row.** A row the two grids agree on
everywhere costs nothing; a row they disagree on costs what they disagree by. The five-vector
maximum was neither -- it was a sample, and it was applied to every row of the model equally.

## What it does and does not bound

It bounds the DISCREPANCY BETWEEN TWO GRIDS, not the distance of either from the continuum. Those
differ by `|T_2N - T_inf|`, which no pair of grids can measure. Treating the discrepancy as the
error assumes the finer grid is much closer to the continuum than the coarser one, which is the same
assumption Richardson extrapolation makes and is exactly what `solution_verification` refuses to
grant when the observed order is implausible.

So a caller that wants a defensible model-error budget needs both: this, for the polytope-wide
extent of the disagreement, and a convergence verdict, for whether the disagreement may be read as
an error at all. Neither alone is enough.

## What lives here

The polytope-wide per-row bound, and the model-id helpers that say WHICH pair of grids to compare.
Those helpers came from `grid_convergence_gate`, whose estimator this module replaces: keeping the
naming rules next to the bound that uses them removes a module whose only remaining purpose was to
hold two regexes and a superseded safety factor.

Leaf module: depends only on numpy, `re`, and the polytope's array fields.
"""

from __future__ import annotations

import re
from typing import Sequence

import numpy as np


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



def _extreme_lp(
    coefficients: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    total: float,
    a_ub: np.ndarray,
    b_ub: np.ndarray,
) -> float:
    """`max c.p` over the FULL polytope, including the class-total inequalities.

    **The greedy fill below is exact only for a box with one equality.** `activity_bounded_power_
    space` also caps each content class's aggregate, and those rows were being dropped at the call
    site: the callers passed `space.lower_w` and `space.upper_w` and nothing else. Dropping
    constraints ENLARGES the feasible set, so every bound computed that way was valid but loose --
    sound, never a false certificate, but it turned certifiable designs into refusals and inflated
    every reported band. Peer review found it.

    With disjoint class caps and a global equality the structure is a polymatroid and a nested
    greedy would also be exact, but an LP is the construction that stays correct if the declared set
    ever grows another inequality, and at this size it costs under a millisecond.
    """

    from scipy.optimize import linprog

    objective = np.asarray(coefficients, dtype=float)
    # SCALE THE OBJECTIVE. The row differences are ~1e-3 K/W while the equality's right-hand side is
    # tens of watts, and HiGHS returned `model_status Unknown` on a problem whose feasibility is not
    # in doubt -- the placed power map satisfies every constraint by construction. Dividing by the
    # largest coefficient leaves the argmax untouched and removes the conditioning problem; the
    # optimum is scaled back at the end.
    scale = float(np.max(np.abs(objective)))
    # A CONSTANT OBJECTIVE STILL GOES THROUGH THE SOLVER. Returning 0.0 early looked obviously
    # right -- every feasible point attains it -- but it skipped the feasibility question, so an
    # EMPTY polytope would have produced a number instead of a refusal. Solving with a zero
    # objective costs the same and lets HiGHS answer that question, which is the one that matters.
    if scale == 0.0:
        objective, scale = np.zeros_like(objective), 1.0
    bounds = list(zip(lower.tolist(), upper.tolist()))
    failures = []
    for method in ("highs", "highs-ds", "highs-ipm"):
        result = linprog(
            -objective / scale,
            A_ub=a_ub, b_ub=b_ub,
            A_eq=np.ones((1, objective.size)), b_eq=np.array([total]),
            bounds=bounds, method=method,
        )
        if result.success:
            return float(-result.fun) * scale
        failures.append(f"{method}: {result.message.strip()}")
    # FAIL CLOSED. An unsolved relaxation has no supremum, and falling back to the greedy would
    # silently substitute a bound over a LARGER set -- the very defect this function exists to fix.
    raise ValueError(
        "the polytope maximisation did not solve under any HiGHS variant (" + "; ".join(failures)
        + "); a supremum over a set the solver could not certify as feasible is not a number"
    )


def _extreme(
    coefficients: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    total: float,
    a_ub: np.ndarray = None,
    b_ub: np.ndarray = None,
) -> float:
    """`max c.p` over `{lower <= p <= upper, 1.p = total, A_ub p <= b_ub}`, exactly.

    With no `A_ub` the single equality makes the feasible set a transportation polytope whose
    vertices are reached by starting at `lower` and pushing the remaining budget into the largest
    coefficients first -- a greedy fill, exact and solver-free. With `A_ub` present that is no
    longer true and the work goes to `_extreme_lp`.
    """

    if a_ub is not None and np.asarray(a_ub).size:
        return _extreme_lp(coefficients, lower, upper, total, np.asarray(a_ub), np.asarray(b_ub))
    p = lower.copy()
    spare = total - float(p.sum())
    if spare < -1e-9:
        raise ValueError(
            f"the lower bounds already exceed the total power by {-spare}; the polytope is empty "
            "and a supremum over it is not a number"
        )
    for index in np.argsort(-coefficients):
        if spare <= 1e-12:
            break
        room = upper[index] - p[index]
        if room <= 0.0:
            continue
        take = min(room, spare)
        p[index] += take
        spare -= take
    if spare > 1e-9:
        raise ValueError(
            f"the upper bounds cannot absorb the total power, {spare} left over; the polytope is "
            "empty and a supremum over it is not a number"
        )
    return float(coefficients @ p)


def one_sided_containment_bounds(
    coarse_rows: np.ndarray,
    fine_rows: np.ndarray,
    coarse_ambient: np.ndarray,
    fine_ambient: np.ndarray,
    lower_w: np.ndarray,
    upper_w: np.ndarray,
    total_w: float,
    a_ub: np.ndarray = None,
    b_ub: np.ndarray = None,
):
    """The two SIGNED extrema, which is what set containment actually needs.

    Certifying "every admissible map is safe under the FINE operator" while only holding the coarse
    one requires the amount by which the fine operator can read HOTTER:

        u_j = max_p [ T_fine,j(p) - T_coarse,j(p) ]
        l_j = max_p [ T_coarse,j(p) - T_fine,j(p) ]

    Then, writing `F` for a feasible set at limit `L`,

        {p : T_coarse,j(p) <= L - u_j  for all j}  is a SUBSET of  F_fine
        F_fine  is a SUBSET of  {p : T_coarse,j(p) <= L + l_j  for all j}

    so tightening the coarse rows by `u_j` certifies against the fine operator, and relaxing them by
    `l_j` bounds it from outside. Neither `u_j` nor `l_j` is `max |.|`, and using the symmetric
    magnitude -- as `row_discrepancy_bounds` does -- replaces BOTH by the larger of the two. That is
    valid and needlessly conservative, and the conservatism is not academic here: it is what drove a
    development registry to stop certifying. Peer review supplied the construction.

    Returns `(u, l)`, each one entry per row and each possibly negative -- a negative `u_j` means the
    fine operator reads strictly colder everywhere on the polytope, which TIGHTENS nothing and is
    information rather than an error.
    """

    coarse, fine, ambient_coarse, ambient_fine, lower, upper = _validated(
        coarse_rows, fine_rows, coarse_ambient, fine_ambient, lower_w, upper_w, total_w
    )
    delta = fine - coarse                       # positive where the FINE grid reads hotter
    offset = ambient_fine - ambient_coarse
    u = np.empty(coarse.shape[0], dtype=float)
    lo = np.empty(coarse.shape[0], dtype=float)
    for j in range(coarse.shape[0]):
        u[j] = _extreme(delta[j], lower, upper, total_w, a_ub, b_ub) + offset[j]
        lo[j] = _extreme(-delta[j], lower, upper, total_w, a_ub, b_ub) - offset[j]
    return u, lo


def peak_over_polytope(
    rows: np.ndarray,
    ambient: np.ndarray,
    lower_w: np.ndarray,
    upper_w: np.ndarray,
    total_w: float,
    a_ub: np.ndarray = None,
    b_ub: np.ndarray = None,
) -> float:
    """`max over rows j, over admissible p, of T_j(p)` -- the temperature itself, not a discrepancy.

    **A discrepancy bound is not a temperature bound.** Peer review named this as the largest logical
    gap in the frontier: it evaluated the peak at the NOMINAL power map and then subtracted a
    polytope-wide discrepancy supremum from the resulting headroom. That certifies nothing about the
    polytope, because a different admissible map can be hotter under the very same operator, and no
    amount of cross-model correction detects it -- the two quantities are maximised independently and
    over different things.

    The construction is the same greedy as every other bound here, because `T_j(p) = r_j . p + a_j`
    is affine in `p` and the admissible set is the same box-with-total polytope. So the fix costs one
    pass per row and is exact rather than sampled.
    """

    response = np.atleast_2d(np.asarray(rows, dtype=float))
    ambient_k = np.atleast_1d(np.asarray(ambient, dtype=float))
    lower = np.asarray(lower_w, dtype=float)
    upper = np.asarray(upper_w, dtype=float)
    if ambient_k.shape != (response.shape[0],):
        raise ValueError("one ambient per row is required")
    if lower.shape != (response.shape[1],) or upper.shape != (response.shape[1],):
        raise ValueError("the polytope bounds must have one entry per block")
    for name, array in (
        ("response", response), ("ambient", ambient_k), ("lower", lower), ("upper", upper)
    ):
        if not np.all(np.isfinite(array)):
            raise ValueError(f"the {name} array must be finite to bound a peak temperature")
    if np.any(upper < lower):
        raise ValueError("the polytope has an upper bound below its lower bound")
    if not np.isfinite(total_w) or total_w <= 0.0:
        raise ValueError(f"the total power must be finite and positive, got {total_w}")
    return max(
        _extreme(response[j], lower, upper, total_w, a_ub, b_ub) + float(ambient_k[j])
        for j in range(response.shape[0])
    )


def _validated(coarse_rows, fine_rows, coarse_ambient, fine_ambient, lower_w, upper_w, total_w):
    """Shared shape and finiteness checks for both bound flavours."""

    coarse = np.atleast_2d(np.asarray(coarse_rows, dtype=float))
    fine = np.atleast_2d(np.asarray(fine_rows, dtype=float))
    lower = np.asarray(lower_w, dtype=float)
    upper = np.asarray(upper_w, dtype=float)
    if coarse.shape != fine.shape:
        raise ValueError(
            f"the two grids must describe the same rows over the same blocks: {coarse.shape} "
            f"against {fine.shape}"
        )
    ambient_coarse = np.atleast_1d(np.asarray(coarse_ambient, dtype=float))
    ambient_fine = np.atleast_1d(np.asarray(fine_ambient, dtype=float))
    if ambient_coarse.shape != (coarse.shape[0],) or ambient_fine.shape != (coarse.shape[0],):
        raise ValueError("one ambient per row is required for each grid")
    if lower.shape != (coarse.shape[1],) or upper.shape != (coarse.shape[1],):
        raise ValueError("the polytope bounds must have one entry per block")
    for name, array in (("coarse", coarse), ("fine", fine), ("lower", lower), ("upper", upper),
                        ("coarse ambient", ambient_coarse), ("fine ambient", ambient_fine)):
        if not np.all(np.isfinite(array)):
            raise ValueError(f"the {name} array must be finite to bound a discrepancy")
    if np.any(upper < lower):
        raise ValueError("the polytope has an upper bound below its lower bound")
    if not np.isfinite(total_w) or total_w <= 0.0:
        raise ValueError(f"the total power must be finite and positive, got {total_w}")
    return coarse, fine, ambient_coarse, ambient_fine, lower, upper


def row_discrepancy_bounds(
    coarse_rows: np.ndarray,
    fine_rows: np.ndarray,
    coarse_ambient: np.ndarray,
    fine_ambient: np.ndarray,
    lower_w: np.ndarray,
    upper_w: np.ndarray,
    total_w: float,
) -> np.ndarray:
    """Per row, `sup_p |d_j(p)|` over the polytope. One entry per row, all nonnegative.

    Both maximum and minimum are computed, because the discrepancy is signed and the certificate
    needs its magnitude: a row where the coarse grid reads 0.4 K COLD everywhere is as dangerous as
    one where it reads 0.4 K hot, and taking only the maximum would score the first as zero.
    """

    u, lo = one_sided_containment_bounds(
        coarse_rows, fine_rows, coarse_ambient, fine_ambient, lower_w, upper_w, total_w
    )
    # The symmetric magnitude is the larger of the two signed extrema. Kept because a single scalar
    # per row is what the operator build charges, but a caller certifying set containment should use
    # the signed pair, which is strictly tighter.
    return np.maximum(np.maximum(u, lo), 0.0)


def sample_bound(
    coarse_rows: np.ndarray,
    fine_rows: np.ndarray,
    coarse_ambient: np.ndarray,
    fine_ambient: np.ndarray,
    vectors,
) -> np.ndarray:
    """The old five-vector maximum, kept so the gap between a sample and a bound is measurable.

    Reported beside `row_discrepancy_bounds` rather than deleted, because "the sample understated
    the polytope-wide bound by this factor" is the number that shows why the change was necessary.
    """

    coarse = np.atleast_2d(np.asarray(coarse_rows, dtype=float))
    fine = np.atleast_2d(np.asarray(fine_rows, dtype=float))
    ambient_coarse = np.atleast_1d(np.asarray(coarse_ambient, dtype=float))
    ambient_fine = np.atleast_1d(np.asarray(fine_ambient, dtype=float))
    worst = np.zeros(coarse.shape[0], dtype=float)
    seen = 0
    for power in vectors:
        p = np.asarray(power, dtype=float)
        if p.shape != (coarse.shape[1],):
            raise ValueError("every sample vector must have one entry per block")
        worst = np.maximum(
            worst, np.abs((coarse - fine) @ p + (ambient_coarse - ambient_fine))
        )
        seen += 1
    if seen == 0:
        raise ValueError(
            "no sample vectors were supplied; an empty sample would report a discrepancy of zero "
            "and pass every operator"
        )
    return worst
