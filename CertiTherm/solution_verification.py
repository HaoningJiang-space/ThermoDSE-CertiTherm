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
    (the textbook asymptotic check is tautological with three grids -- see below)

`Fs = 1.25` is the three-grid value; the `Fs = 3` in the literature is for a two-grid study with an
ASSUMED order, which is what the previous estimator effectively was.

## Why chip thermal work does not already do this

In the tools and papers surveyed for this work, "convergence" in chip-thermal simulation almost
always means **iterative solver convergence** -- HotSpot iterates Kirchhoff's current law to a
residual threshold and accelerates it with multigrid -- and no discretisation-convergence study for
the thermal response quantities used in physical-design decisions was found. That is a scoped
observation about what a survey turned up, not a claim about the whole field; peer review was right
that two search results cannot support the stronger version.

What is certain is local: the frozen `0.01 K` contract here checks LINEARITY at a fixed grid, HotSpot
checks the ITERATION, and the discretisation error was measured by nobody until it was measured here.
A grid-count comparison against published guidance (`1024x1024` for thermal-aware physical design
against `128x128` here) is NOT evidence on its own -- resolution is meaningless without die
dimensions, cell pitch, heat-source length scales and a target tolerance -- and is not relied on.

## What this module refuses to do

Report an uncertainty for a solution outside the asymptotic range. Three verdicts:

* `PLAUSIBLE_ORDER` -- monotone and the observed order sits in a plausible band. A GCI is returned.
  The name is deliberate: with three grids and a one-term model `f_0 + C h^p` there are exactly as
  many observations as parameters, so nothing is left over to TEST the model with. A plausible order
  is consistent with asymptotic behaviour; it is not evidence of it, and calling the verdict
  `ASYMPTOTIC` claimed evidence that three points cannot carry. Peer review named this.
* `OSCILLATORY` -- the two differences have opposite signs. Richardson extrapolation does not apply;
  no uncertainty is returned.
* `IMPLAUSIBLE_ORDER` -- monotone but the observed order is outside the band. No uncertainty. Note
  what this does NOT establish: a high observed order may be cancellation, superconvergence, an
  active-set change, or the solver noise floor rather than a failure to converge. Refusing is
  conservative; the diagnosis is not a proof of non-convergence.

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

# The band's lower edge doubles as the floor: an order below it is REFUSED rather than clamped, so
# the clamp only ever binds from above. Kept as a named constant because `r^p - 1` diverges as
# `p -> 0` and a future widening of the band must not reintroduce that.
ORDER_FLOOR = 0.5

# The band of observed orders that counts as asymptotic behaviour for this discretisation. HotSpot's
# grid model is a finite-difference RC network, formally first to second order, so an observed order
# in roughly that range is evidence the grids are in the asymptotic range and one far outside it is
# evidence they are not.
#
# This replaces the textbook check `GCI(coarse,med) / (r^p * GCI(med,fine)) ~= 1`, which is
# TAUTOLOGICAL with three grids WHENEVER THE OBSERVED ORDER IS USED UNCLAMPED: substituting
# `p = ln(e_cm/e_mf)/ln(r)` makes the error ratio cancel exactly and leaves `|f_fine/f_med|`. It is
# not tautological for a clamped order, which is why the reported ratio is still worth printing. The
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
    # A vanishing fine-grid value is a CENTRAL case here, not a degenerate one: `beta* = 0` is what
    # a nominally infeasible design returns, and this project produces those. The relative index is
    # undefined there but the ABSOLUTE one, `Fs |f_f - f_m| / (r^p - 1)`, is perfectly well defined.
    # Refusing zero would make the API unable to describe its own most important outcome. Peer
    # review caught this.
    relative_is_defined = f_fine != 0.0

    e_coarse_medium = f_medium - f_coarse
    e_medium_fine = f_fine - f_medium

    if e_medium_fine == 0.0 and e_coarse_medium == 0.0:
        # Identical on all three grids. NOT reported as zero uncertainty: three equal floats can
        # come from a solver tolerance, a quantised output, a duplicated input or a common bias, and
        # none of those is evidence of a converged discretisation. Peer review objected to the
        # earlier reading and was right.
        return {
            "verdict": "DEGENERATE", "observed_order": None, "order_used": None,
            "extrapolated": None, "uncertainty": None, "relative_uncertainty": None,
            "asymptotic_ratio": None,
            "note": (
                "identical on all three grids; that is consistent with convergence but equally with "
                "a tolerance floor, a quantised output or a duplicated input, so no uncertainty is "
                "claimed"
            ),
        }
    if e_medium_fine == 0.0 or e_coarse_medium == 0.0:
        # One difference vanishes and the other does not. The observed order is undefined -- and a
        # zero difference is not "opposite signs", so calling it oscillatory was wrong.
        return {
            "verdict": "DEGENERATE", "observed_order": None, "order_used": None,
            "extrapolated": None, "uncertainty": None, "relative_uncertainty": None,
            "asymptotic_ratio": None,
            "note": (
                f"one successive difference is exactly zero ({e_coarse_medium:+.6g} then "
                f"{e_medium_fine:+.6g}); the observed order is undefined"
            ),
        }

    ratio = e_coarse_medium / e_medium_fine
    if ratio < 0.0:
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
    # ABSOLUTE first, because it is always defined; the relative index is the absolute one divided
    # by the fine value and only exists when that value does not vanish.
    absolute = SAFETY_FACTOR_THREE_GRID * abs(e_medium_fine) / denominator
    gci_fine = absolute / abs(f_fine) if relative_is_defined else None
    gci_coarse = (
        SAFETY_FACTOR_THREE_GRID * abs(e_coarse_medium / f_medium) / denominator
        if f_medium != 0.0 else float("inf")
    )

    # Reported, not used as the gate -- see ASYMPTOTIC_ORDER_BAND for why it is tautological here.
    asymptotic_ratio = (
        gci_coarse / (refinement_ratio ** order_used * gci_fine)
        if gci_fine not in (None, 0.0) else None
    )
    low, high = ASYMPTOTIC_ORDER_BAND
    if not (low <= observed_order <= high):
        return {
            "verdict": "IMPLAUSIBLE_ORDER", "observed_order": observed_order,
            "order_used": order_used, "extrapolated": None, "uncertainty": None,
            "relative_uncertainty": None, "asymptotic_ratio": asymptotic_ratio,
            "note": (
                f"the observed order {observed_order:.2f} is outside [{low}, {high}], which a "
                "finite-difference RC network cannot exhibit in the asymptotic range; the "
                "discretisation error is UNKNOWN, not large"
            ),
        }
    return {
        "verdict": "PLAUSIBLE_ORDER", "observed_order": observed_order, "order_used": order_used,
        "extrapolated": extrapolated,
        "uncertainty": absolute,
        "relative_uncertainty": gci_fine,
        "asymptotic_ratio": asymptotic_ratio,
        "note": (
            "observed order clamped to the formal order"
            if observed_order > FORMAL_ORDER else
            ("observed order raised to the floor" if observed_order < ORDER_FLOOR else "")
        ),
    }
