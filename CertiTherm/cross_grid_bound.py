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

Leaf module: depends only on numpy and the polytope's array fields.
"""

from __future__ import annotations

import numpy as np


def _extreme(coefficients: np.ndarray, lower: np.ndarray, upper: np.ndarray, total: float) -> float:
    """`max c.p` over `{lower <= p <= upper, 1.p = total}`, exactly, by greedy fill.

    The single equality makes the feasible set a transportation polytope whose vertices are reached
    by starting at `lower` and pushing the remaining budget into the largest coefficients first.
    """

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

    delta_rows = coarse - fine
    delta_ambient = ambient_coarse - ambient_fine
    bounds = np.empty(coarse.shape[0], dtype=float)
    for j in range(coarse.shape[0]):
        row = delta_rows[j]
        high = _extreme(row, lower, upper, total_w) + delta_ambient[j]
        low = -_extreme(-row, lower, upper, total_w) + delta_ambient[j]
        bounds[j] = max(abs(high), abs(low))
    return bounds


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
