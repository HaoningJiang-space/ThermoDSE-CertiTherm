"""Discretisation uncertainty by the standard method, replacing a safety factor invented here.

`grid_convergence_gate.budgeted_error_k` charges `2 * |f_N - f_2N|`. That factor was reasoned from a
triangle inequality plus an assumption of at least first-order convergence, which is defensible as
far as it goes -- but it is a two-grid estimate, it applies the same multiplier whether the solution
is converging beautifully or not converging at all, and measured on this registry it was wrong in
BOTH directions:

    heldout_radii_07/08   |f_128 - f_256| / f_256 = 0.4 %    charged 2x a nearly-converged solution
    heldout_radii_06/11   oscillatory, no convergence at all  charged as if an error bar existed

The second is the serious one. **A solution that is not converging cannot be given an error bar**,
and manufacturing one is the same class of mistake as a fabricated verdict -- which this project's
fail-closed contract exists to prevent everywhere else.

The field has a standard for exactly this problem: solution verification by grid refinement, Roache
(1994, 1997), codified in ASME V&V 20-2009 Section 7.2 as the Grid Convergence Index. With three
solutions at a constant refinement ratio `r`:

    observed order        p    = ln[(f_coarse - f_med) / (f_med - f_fine)] / ln(r)
    Richardson estimate   f_ex = f_fine + (f_fine - f_med) / (r^p - 1)
    uncertainty           GCI  = Fs * |(f_fine - f_med) / f_fine| / (r^p - 1),   Fs = 1.25
    asymptotic check      GCI(coarse,med) / (r^p * GCI(med,fine))  ~=  1

`Fs = 1.25` is the three-grid value; the `Fs = 3` in the literature is for a two-grid study with an
ASSUMED order, which is what the previous estimator effectively was.

## Why chip thermal work does not already do this

The chip-thermal literature discusses grid resolution and "convergence" at length, but almost always
means **iterative solver convergence** -- HotSpot iterates Kirchhoff's current law to a residual
threshold and accelerates it with multigrid. That is convergence of the solve, not of the
discretisation. Nothing in that pipeline compares a solution against a finer grid, and neither did
this project: the frozen `0.01 K` contract checks LINEARITY at a fixed grid, HotSpot checks the
ITERATION, and the discretisation error was measured by nobody.

The gap is not small. Published guidance for thermal-aware physical design puts the required active
-layer resolution at `1024x1024` and beyond; this project's certified family stops at `128x128`.

## What this module refuses to do

Report an uncertainty for a solution outside the asymptotic range. Three verdicts:

* `ASYMPTOTIC` -- monotone, observed order plausible, asymptotic ratio near one. A GCI is returned
  and it is a defensible error bar.
* `OSCILLATORY` -- the two differences have opposite signs. Richardson extrapolation does not apply;
  no uncertainty is returned.
* `NOT_ASYMPTOTIC` -- monotone but the asymptotic ratio is far from one, or the observed order is
  implausible. No uncertainty is returned.

The last two are `UNRESOLVED` in this project's vocabulary: the honest output is that the
discretisation error is unknown, not that it is large.

Leaf module: depends on nothing in the package.
"""

from __future__ import annotations

import math

# ASME V&V 20-2009 Sec. 7.2 / Roache: 1.25 when the order is OBSERVED from three grids.
SAFETY_FACTOR_THREE_GRID = 1.25

# The formal order of the discretisation. HotSpot's grid model is a finite-difference RC network
# whose block-averaged output is at best second order, and an OBSERVED order above the formal one is
# not physical -- it means the coarse-medium difference is anomalously large or the medium-fine one
# anomalously small. Roache's guidance is to use the formal order in that case, which is also the
# conservative choice here: `GCI` scales as `1 / (r^p - 1)`, so a smaller `p` gives a LARGER bar.
FORMAL_ORDER = 2.0

# Below this the sequence is barely converging and the extrapolation is not trustworthy; clamping
# here rather than at zero keeps `r^p - 1` away from zero, where the GCI diverges.
ORDER_FLOOR = 0.5

# The band of observed orders that counts as asymptotic behaviour for this discretisation. HotSpot's
# grid model is a finite-difference RC network, formally first to second order, so an observed order
# in roughly that range is evidence the grids are in the asymptotic range and one far outside it is
# evidence they are not.
#
# This replaces the textbook check `GCI(coarse,med) / (r^p * GCI(med,fine)) ~= 1`, which is
# TAUTOLOGICAL with three grids: substituting the observed `p`, defined as
# `ln(e_cm/e_mf)/ln(r)`, makes the error-ratio cancel exactly and leaves only `f_fine/f_med`. The
# first version of this module used it and refused a textbook-clean case -- `heldout_radii_09`,
# monotone with `p = 1.45` -- purely because its solution had moved 15 % between grids. That check
# is meaningful only with FOUR or more grids, or with an assumed formal order; with three and an
# observed order it measures nothing about convergence. The ratio is still reported, because
# `f_fine/f_med` is worth seeing, but it does not gate.
ASYMPTOTIC_ORDER_BAND = (0.5, 2.5)


def verify(f_coarse: float, f_medium: float, f_fine: float, refinement_ratio: float = 2.0) -> dict:
    """Solution verification from three grid levels, or a refusal.

    `f_coarse`, `f_medium`, `f_fine` are the SAME functional evaluated on successively refined
    grids -- a peak temperature, a robustness radius, anything scalar. `refinement_ratio` is the
    factor between successive grids, 2 for `grid64 -> grid128 -> grid256`.

    Returns a dict carrying `verdict`, and an `uncertainty` only when the verdict is `ASYMPTOTIC`.
    """

    values = (f_coarse, f_medium, f_fine)
    if not all(math.isfinite(v) for v in values):
        raise ValueError(f"all three grid solutions must be finite, got {values}")
    if not math.isfinite(refinement_ratio) or refinement_ratio <= 1.0:
        raise ValueError(f"the refinement ratio must be finite and above 1, got {refinement_ratio}")
    if f_fine == 0.0:
        raise ValueError(
            "the fine-grid solution is exactly zero, so a relative error is undefined; a functional "
            "that can vanish must be verified in absolute form instead"
        )

    e_coarse_medium = f_medium - f_coarse
    e_medium_fine = f_fine - f_medium

    if e_medium_fine == 0.0 and e_coarse_medium == 0.0:
        # Identical on all three grids. Converged to machine precision, not a degenerate input.
        return {
            "verdict": "ASYMPTOTIC", "observed_order": float("inf"), "order_used": FORMAL_ORDER,
            "extrapolated": f_fine, "uncertainty": 0.0, "relative_uncertainty": 0.0,
            "asymptotic_ratio": 1.0, "note": "identical on all three grids",
        }
    if e_medium_fine == 0.0:
        raise ValueError(
            "the medium and fine grids agree exactly while the coarse one differs; the observed "
            "order is undefined and this is far more likely a duplicated input than a converged one"
        )

    ratio = e_coarse_medium / e_medium_fine
    if ratio <= 0.0:
        # Opposite signs: the solution overshoots and comes back. Richardson extrapolation assumes a
        # monotone error series and does not apply, so no uncertainty is produced.
        return {
            "verdict": "OSCILLATORY", "observed_order": None, "order_used": None,
            "extrapolated": None, "uncertainty": None, "relative_uncertainty": None,
            "asymptotic_ratio": None,
            "note": (
                f"successive differences have opposite signs ({e_coarse_medium:+.6g} then "
                f"{e_medium_fine:+.6g}); the discretisation error is UNKNOWN, not large"
            ),
        }

    observed_order = math.log(ratio) / math.log(refinement_ratio)
    order_used = min(max(observed_order, ORDER_FLOOR), FORMAL_ORDER)
    denominator = refinement_ratio ** order_used - 1.0

    extrapolated = f_fine + e_medium_fine / denominator
    relative_fine = abs(e_medium_fine / f_fine)
    gci_fine = SAFETY_FACTOR_THREE_GRID * relative_fine / denominator
    relative_coarse = abs(e_coarse_medium / f_medium) if f_medium != 0.0 else float("inf")
    gci_coarse = SAFETY_FACTOR_THREE_GRID * relative_coarse / denominator

    # Reported, not used as the gate -- see ASYMPTOTIC_ORDER_BAND for why it is tautological here.
    asymptotic_ratio = (
        gci_coarse / (refinement_ratio ** order_used * gci_fine) if gci_fine > 0 else float("inf")
    )
    low, high = ASYMPTOTIC_ORDER_BAND
    if not (low <= observed_order <= high):
        return {
            "verdict": "NOT_ASYMPTOTIC", "observed_order": observed_order,
            "order_used": order_used, "extrapolated": None, "uncertainty": None,
            "relative_uncertainty": None, "asymptotic_ratio": asymptotic_ratio,
            "note": (
                f"the observed order {observed_order:.2f} is outside [{low}, {high}], which a "
                "finite-difference RC network cannot exhibit in the asymptotic range; the "
                "discretisation error is UNKNOWN, not large"
            ),
        }
    return {
        "verdict": "ASYMPTOTIC", "observed_order": observed_order, "order_used": order_used,
        "extrapolated": extrapolated,
        "uncertainty": gci_fine * abs(f_fine),
        "relative_uncertainty": gci_fine,
        "asymptotic_ratio": asymptotic_ratio,
        "note": (
            "observed order clamped to the formal order"
            if observed_order > FORMAL_ORDER else
            ("observed order raised to the floor" if observed_order < ORDER_FLOOR else "")
        ),
    }
