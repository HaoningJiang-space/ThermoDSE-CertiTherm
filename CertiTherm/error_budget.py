"""The error budget as three named terms with the right signs, instead of one overloaded scalar.

`ThermalFamily.error_k` is one **non-negative** number per model and `thermal_constraints` broadcasts
it across every row. That is exactly right for what it measures -- the linearisation residual, a
symmetric magnitude from replaying a power map directly against impulse superposition -- and exactly
wrong for what has since been measured on top of it.

## Why one field cannot hold both

`one_sided_containment_bounds` returns `u_j = sup_p [T_ref,j(p) - T_model,j(p)]`: **signed** and **per
row**. Measured on the development split, 26 rows across two cases are NEGATIVE, down to -0.39 K.
The two quantities differ in three ways at once -- sign, granularity, and what a certificate is
allowed to do with them:

* **SAFE** needs the amount the reference can read HOTTER. A negative `u_j` there must be clamped to
  zero, or disagreement between two models would ADD slack.
* **REJECT** is defined in `thermal_constraints` as *not certifiably safe*, not *proven unsafe*. Its
  bound is `T_model >= L + margin - u_j`, so a negative `u_j` must **RAISE** the threshold. Clamping
  it lowers the threshold and manufactures not-safe worlds the physics does not contain.

That second case is why this matters beyond tidiness. For an observation-synthesis claim -- *how many
measurements suffice* -- an inflated REJECT set inflates the minimum observation set, produces
spurious collision witnesses and spurious `UNSYNTHESIZABLE` verdicts. Fail-closed forbids issuing
SAFE without establishing safety; it does **not** license misdescribing what a certificate says.

## Scope, measured so it is neither over- nor under-stated

The reduction currently applied is `max_j u_j`, which is positive on all six development cases, so
**the clamp has never fired and no published number changes**. The defect is structural, not
contaminating -- and it becomes live the moment per-row budgets are used, which is precisely what the
observation-count claim needs.

## What must be rebuilt, and what must not be mistaken for it

A SAFE row subset proved sufficient under a single scalar `max` need not remain sufficient once each
row is relaxed by a different amount. Kernel subsets, reject specifications and collision witnesses
are all derived from the constraint set and must be re-derived. **That is not a receipt swap.**
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class ErrorBudget:
    """Three terms, each with its own sign convention, for one model over `n` rows.

    `linearisation_k` keeps `error_k`'s meaning unchanged: a non-negative symmetric magnitude. The
    two model-form terms are signed and per row, because that is what the measurement produces.
    """

    linearisation_k: float
    model_form_upper_k: Optional[np.ndarray] = None
    model_form_lower_k: Optional[np.ndarray] = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.linearisation_k) or self.linearisation_k < 0.0:
            raise ValueError(
                f"linearisation_k is {self.linearisation_k}; it is a symmetric magnitude and must be "
                "finite and non-negative"
            )
        for name in ("model_form_upper_k", "model_form_lower_k"):
            value = getattr(self, name)
            if value is None:
                continue
            array = np.asarray(value, dtype=float)
            if array.ndim != 1 or not np.all(np.isfinite(array)):
                raise ValueError(f"{name} must be a finite vector, one entry per row")
            # NOT clamped and NOT required non-negative. A negative entry is the measurement saying
            # the reference reads COLDER on that row, which is information both sides need and which
            # the two sides use in opposite directions.
            object.__setattr__(self, name, array)
        upper, lower = self.model_form_upper_k, self.model_form_lower_k
        if upper is not None and lower is not None and upper.shape != lower.shape:
            raise ValueError("the upper and lower model-form bounds must cover the same rows")

    def safe_allowance_k(self) -> np.ndarray:
        """What SAFE subtracts, per row. **Clamped**, because a colder reference must not add slack."""

        if self.model_form_upper_k is None:
            raise ValueError("no model-form upper bound was supplied; SAFE cannot budget one")
        return self.linearisation_k + np.maximum(self.model_form_upper_k, 0.0)

    def reject_allowance_k(self) -> np.ndarray:
        """What REJECT subtracts, per row. **Not clamped**, because a negative bound must RAISE
        the threshold -- `T_model >= L + margin - u_j` with `u_j < 0` is a stricter test, and
        clamping it to zero would admit worlds that are not actually unsafe."""

        if self.model_form_upper_k is None:
            raise ValueError("no model-form upper bound was supplied; REJECT cannot budget one")
        return self.linearisation_k + self.model_form_upper_k
