"""The re-anchored feasibility certificate: ONE definition, taking the polytope rather than a box.

Two callers computed this arithmetic independently -- the census verdict and the frontier probe --
and they had drifted in exactly the way the project's own rule warns about: a second implementation
cannot be its own oracle, and here neither was checking the other. The quantities are the same, so
they belong in one place.

## Why the signature takes a `PowerPolytope`

The defect peer review found was that both callers passed `space.lower_w` and `space.upper_w` and
dropped `space.a_ub` / `space.b_ub`, so the maximisation ran over a LARGER set than the declared one.
That was possible only because the interface accepted loose arrays. **Taking the polytope makes the
mistake unrepresentable**, which is a stronger fix than remembering to pass two more arguments.

## What the certificate is, and what each term is for

    sup_p T_ref(p)  +  sup_p [T_cmp(p) - T_ref(p)]  <=  limit - margin - linearisation

* `sup_p T_ref(p)` is a TEMPERATURE bound over the whole admissible set, not the value at the
  nominal power map. A discrepancy bound is not a temperature bound: a different admissible map can
  be hotter under the very same operator, and no cross-model correction detects that.
* `sup_p [T_cmp - T_ref]` is one-sided -- the amount the comparison operator can read HOTTER -- so
  folding it in can only make certification harder. A negative band means the comparison operator is
  uniformly cooler, which is information, but it is clamped at zero here because a certificate must
  not be *helped* by disagreement.
* `linearisation` stays as its own term. It measures direct replay against impulse superposition,
  which is a different error source from disagreement between two affine operators; deleting it
  while adding a model-form band would leave superposition unbudgeted.

Both suprema are attained exactly -- every row is affine in the power vector -- so this is a bound,
not an estimate, over whatever polytope is handed to it.

Depends on `core` and `cross_grid_bound`, both leaves. Nothing in the package imports it back.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .core import PowerPolytope
from .cross_grid_bound import one_sided_containment_bounds, peak_over_polytope


@dataclass(frozen=True, slots=True)
class ReanchoredCertificate:
    """One design, one uncertainty set. `slack_k >= 0` is the verdict."""

    sup_peak_k: float
    model_form_band_k: float
    slack_k: float

    def __post_init__(self) -> None:
        for name, value in (
            ("sup_peak_k", self.sup_peak_k),
            ("model_form_band_k", self.model_form_band_k),
            ("slack_k", self.slack_k),
        ):
            # `isfinite` first and separately. `NaN >= 0` is False and `NaN < 0` is also False, so a
            # single inequality lets a NaN both fail the check and be recorded as a verdict.
            if not math.isfinite(value):
                raise ValueError(f"{name} is {value}; a certificate is not built from a non-number")
        if self.model_form_band_k < 0.0:
            raise ValueError("the band is clamped at zero before construction, never negative")

    @property
    def certified(self) -> bool:
        """`<=` is the frozen comparison, so zero slack certifies."""

        return self.slack_k >= 0.0


def certify_over_polytope(
    reference_rows: np.ndarray,
    reference_ambient: np.ndarray,
    space: PowerPolytope,
    total_w: float,
    *,
    limit_k: float,
    margin_k: float,
    linearisation_k: float,
    comparison_rows: Optional[np.ndarray] = None,
    comparison_ambient: Optional[np.ndarray] = None,
) -> ReanchoredCertificate:
    """Certify the reference operator over `space`, optionally re-anchored on a comparison operator.

    With no comparison operator the band is zero and this is the plain polytope certificate against
    the reference. With one, the band is the amount the comparison can read hotter, folded in
    one-sidedly -- which is what turns a HotSpot certificate into a certificate against an
    independent solver.
    """

    lower = np.asarray(space.lower_w, dtype=float)
    upper = np.asarray(space.upper_w, dtype=float)
    a_ub = np.asarray(space.a_ub, dtype=float)
    b_ub = np.asarray(space.b_ub, dtype=float)
    peak = peak_over_polytope(
        reference_rows, reference_ambient, lower, upper, total_w, a_ub, b_ub
    )
    band = 0.0
    if comparison_rows is not None:
        hotter, _colder = one_sided_containment_bounds(
            reference_rows, comparison_rows, reference_ambient, comparison_ambient,
            lower, upper, total_w, a_ub, b_ub,
        )
        band = max(float(np.max(hotter)), 0.0)
    return ReanchoredCertificate(
        sup_peak_k=peak,
        model_form_band_k=band,
        slack_k=limit_k - margin_k - linearisation_k - peak - band,
    )
