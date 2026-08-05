"""A verdict is relative to a declared thermal model, and the solver gap is measured beside it.

## Why this type exists

`docs/E_TOTAL_AT_THE_CELL_ENDPOINT.md` measured the HotSpot-versus-FEM disagreement at the cell
endpoint and then tried to fold it into the certificate as an error band. That is the wrong object.
The band measures **which solver you trust**, not an error against reality: neither HotSpot nor the
DOLFINx reference is ground truth, and the FEM operator carries `error_k = NaN` deliberately so that
nothing can certify *against* it. Folding a solver disagreement in as if it bounded reality turns a
comparison of two models into a claim about a chip.

Every thermal DSE in this field produces a verdict relative to whichever solver it ran, silently. The
defensible move is not to pretend otherwise but to **say which model**, and to report the gap to an
independent one as a separate measured quantity that a reader can act on.

So:

* a verdict is `CERTIFIED` / `REFUTED` / `UNRESOLVED` **with respect to a named `ThermalModel`**, and
  it cannot be constructed without one;
* a `CrossModelGap` is a **measurement on the cases it was measured on**, never a bound, and it is
  stored beside the verdict rather than inside the slack;
* nothing in this module subtracts a gap from a slack. The one operation that combines them,
  `verdict_if_gap_were_a_bound`, is named for what it is and returns a **different** verdict object
  whose model is the pair, so the two statements can never be swapped by accident.

## The rule this encodes, in one line

**"CERTIFIED" is not a sentence.** "CERTIFIED with respect to HotSpot `grid128-avg` at package
`default`, with a measured +0.071 K disagreement against an independent FEM on three cases" is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Tuple

STATUSES = ("CERTIFIED", "REFUTED", "UNRESOLVED")


@dataclass(frozen=True)
class ThermalModel:
    """Everything that decides what number a solver returns, digested so it cannot drift.

    `solver` and `model_id` are not enough on their own: the same HotSpot binary at the same grid
    resolution returns a different field for a different package, and a different BINARY returns a
    different field for everything. `operator_sha256` pins the response matrix actually used, which
    is the only object the certificate reads.
    """

    solver: str
    model_id: str
    package_id: str
    endpoint: str
    operator_sha256: str
    binary_sha256: str = ""

    def __post_init__(self) -> None:
        for name in ("solver", "model_id", "package_id", "endpoint", "operator_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"ThermalModel.{name} must be a non-empty string, got {value!r}")
        if len(self.operator_sha256) < 16:
            raise ValueError(
                f"operator_sha256 {self.operator_sha256!r} is too short to identify an operator; a "
                "verdict whose model cannot be re-derived is not attributable"
            )

    @property
    def name(self) -> str:
        return f"{self.solver}/{self.model_id}@{self.package_id}[{self.endpoint}]"

    def as_dict(self) -> dict:
        return {"solver": self.solver, "model_id": self.model_id, "package_id": self.package_id,
                "endpoint": self.endpoint, "operator_sha256": self.operator_sha256,
                "binary_sha256": self.binary_sha256}


@dataclass(frozen=True)
class CrossModelGap:
    """A MEASURED disagreement between two thermal models. Not a bound, and not transferable.

    `delta_certified_k` is signed: positive means the reference model is hotter on the certified
    quantity. `row_wise_band_k` and `tight_bound_k` are the two aggregations of the per-row
    difference — the first gives every row its own adversarial power map, the second takes one
    maximum over `(row supremum + row error)` and is the tighter sound form.

    `measured_on` names the cases. It is required, and it is required because a gap quoted for a case
    it was not measured on is exactly the substitution this whole module exists to stop.
    """

    reference: ThermalModel
    delta_certified_k: float
    row_wise_band_k: float
    tight_bound_k: float
    measured_on: Tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("delta_certified_k", "row_wise_band_k", "tight_bound_k"):
            value = float(getattr(self, name))
            # Finiteness first and separately: `NaN < 0` and `NaN >= 0` are both False, so a single
            # inequality would accept a non-finite gap AND record it.
            if not math.isfinite(value):
                raise ValueError(f"CrossModelGap.{name} is {value!r}; a gap that is not a number "
                                 "cannot be reported as one")
        if self.row_wise_band_k < 0.0 or self.tight_bound_k < 0.0:
            raise ValueError("the band aggregations are one-sided and cannot be negative")
        if self.tight_bound_k > self.row_wise_band_k + 1e-9:
            raise ValueError(
                f"the tight aggregation {self.tight_bound_k!r} exceeds the row-wise one "
                f"{self.row_wise_band_k!r}; the derivation says it cannot, so one is computed wrongly"
            )
        if not self.measured_on:
            raise ValueError(
                "measured_on is empty; a gap with no named cases is indistinguishable from a bound, "
                "which is the substitution this type exists to prevent"
            )


@dataclass(frozen=True)
class ModelRelativeVerdict:
    """`status` holds **with respect to `model`** and nowhere else.

    `gaps` are reported beside the verdict and are never subtracted from `slack_k`. There is no
    method here that does that silently; `verdict_if_gap_were_a_bound` does it explicitly and
    returns a different object.
    """

    model: ThermalModel
    status: str
    certified_peak_k: float
    ceiling_k: float
    case: str
    gaps: Tuple[CrossModelGap, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status {self.status!r} is not one of {STATUSES}")
        for name in ("certified_peak_k", "ceiling_k"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"{name} is not finite; the verdict is UNRESOLVED, not a number")
        if not self.case.strip():
            raise ValueError("case must name what was certified")
        # The status must agree with the numbers it is reported next to. A REFUTED verdict carrying a
        # positive slack, or the reverse, is the shape a copy-paste error takes.
        if self.status == "CERTIFIED" and self.certified_peak_k > self.ceiling_k:
            raise ValueError(
                f"CERTIFIED with a peak {self.certified_peak_k!r} above the ceiling "
                f"{self.ceiling_k!r}; the status contradicts its own numbers"
            )
        if self.status == "REFUTED" and self.certified_peak_k <= self.ceiling_k:
            raise ValueError(
                f"REFUTED with a peak {self.certified_peak_k!r} at or below the ceiling "
                f"{self.ceiling_k!r}; the status contradicts its own numbers"
            )

    @property
    def slack_k(self) -> float:
        return self.ceiling_k - self.certified_peak_k

    def sentence(self) -> str:
        """The verdict as it must be written down. Never the bare status."""
        gap = ""
        if self.gaps:
            worst = max(self.gaps, key=lambda g: abs(g.delta_certified_k))
            gap = (f", with a measured {worst.delta_certified_k:+.4f} K disagreement against "
                   f"{worst.reference.name} on {len(worst.measured_on)} case"
                   f"{'s' if len(worst.measured_on) != 1 else ''}")
        return (f"{self.case}: {self.status} with respect to {self.model.name}, slack "
                f"{self.slack_k:+.4f} K{gap}")

    def verdict_if_gap_were_a_bound(self, reference_solver: str) -> "ModelRelativeVerdict":
        """The DIFFERENT statement: treat the measured disagreement as a bound and re-decide.

        This is what folding the band in amounts to, and it is offered only under a name that says
        so. The returned verdict's model is the **pair**, because the resulting claim is no longer
        about either solver alone -- it is "no admissible power map makes either model exceed the
        limit", which is a stronger and differently-scoped statement.

        It uses `tight_bound_k`, the one-maximum aggregation, because that is the tightest sound
        form; the row-wise band would be the same statement, more loosely.
        """
        matching = [g for g in self.gaps if g.reference.solver == reference_solver]
        if not matching:
            raise ValueError(
                f"no measured gap against {reference_solver!r}; the verdict cannot be restated "
                f"against a model it was never compared with. Have: "
                f"{sorted({g.reference.solver for g in self.gaps})}"
            )
        # THE GAP MUST HAVE BEEN MEASURED ON *THIS* CASE. `measured_on` was required so a gap could
        # not be quoted for a case it was never measured on, and this method selected by solver name
        # alone -- leaving open exactly the cross-case substitution the type exists to prevent.
        # Peer review caught it; the requirement is now enforced where it is used, not only where it
        # is stored.
        on_this_case = [g for g in matching if self.case in g.measured_on]
        if not on_this_case:
            raise ValueError(
                f"the gap against {reference_solver!r} was measured on "
                f"{sorted({c for g in matching for c in g.measured_on})}, not on {self.case!r}. A "
                "measurement is not transferable to a case it was not measured on."
            )
        gap = max(on_this_case, key=lambda g: g.tight_bound_k)
        peak = self.certified_peak_k + gap.tight_bound_k
        pair = ThermalModel(
            solver=f"max({self.model.solver},{gap.reference.solver})",
            model_id=f"{self.model.model_id}+{gap.reference.model_id}",
            package_id=self.model.package_id,
            endpoint=self.model.endpoint,
            operator_sha256=f"{self.model.operator_sha256[:16]}+{gap.reference.operator_sha256[:16]}",
        )
        # AN UPPER BOUND ABOVE THE CEILING IS `UNRESOLVED`, NOT `REFUTED`. `peak` here is an upper
        # bound on the pair's peak under the hypothetical premise; exceeding the ceiling means the
        # bound fails to certify, NOT that some admissible power map exceeds the limit. Returning
        # REFUTED would manufacture a refutation from a failed certification, which is the exact
        # direction this project's fail-closed contract forbids. A REFUTED verdict needs an attained
        # witness or a lower bound above the ceiling, and this construction supplies neither.
        status = "CERTIFIED" if peak <= self.ceiling_k else "UNRESOLVED"
        if status == "UNRESOLVED":
            # The constructor cross-checks CERTIFIED/REFUTED against the numbers; UNRESOLVED carries
            # the bound for the reader without asserting a verdict about it.
            return ModelRelativeVerdict(
                model=pair, status=status, certified_peak_k=self.certified_peak_k,
                ceiling_k=self.ceiling_k, case=self.case, gaps=(),
            )
        return ModelRelativeVerdict(
            model=pair, status=status, certified_peak_k=peak, ceiling_k=self.ceiling_k,
            case=self.case, gaps=(),
        )

    def as_dict(self) -> dict:
        return {
            "case": self.case, "status": self.status, "model": self.model.as_dict(),
            "certified_peak_k": self.certified_peak_k, "ceiling_k": self.ceiling_k,
            "slack_k": self.slack_k,
            "sentence": self.sentence(),
            # Deliberately a sibling of the verdict and not a term in it.
            "cross_model_gaps": [
                {"reference": g.reference.as_dict(),
                 "delta_certified_k": g.delta_certified_k,
                 "row_wise_band_k": g.row_wise_band_k,
                 "tight_bound_k": g.tight_bound_k,
                 "measured_on": list(g.measured_on),
                 "note": "MEASURED on the named cases; not a bound and not transferable"}
                for g in self.gaps
            ],
        }
