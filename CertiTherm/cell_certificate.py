"""The certificate on CELL rows, because a bound on block averages is not a bound on the peak.

Every certificate this project has issued is `max over BLOCKS of the block-average temperature`. The
330 K limit is not about block averages. Measured, on the same operators:

* inside HotSpot, the block-average peak sits **0.18 - 0.76 K** below the raw cell peak;
* on the independent FEM, a unit impulse puts the domain maximum **0.44 - 2.06 K** above the hottest
  block average.

Peer review raised this three times before it was acted on. It is the largest known unresolved
correctness gap in the certificate, and the fix is not a scalar correction bolted onto the block
result -- a single nominal cell-minus-block difference is not a polytope-wide bound, and the two
maxima are attained at different places.

## Two endpoints, named, because "the peak" is ambiguous

A junction-temperature limit constrains active silicon. A heat sink at 330 K is not a violation of
anything. So the object being certified has to be stated:

* **`tool_compatible`** -- the maximum HotSpot grid value over **die** cells. This is what
  ThermoDSE's own `find_hotpoint` reports (minus its scan over passive layers), so it is the endpoint
  that makes this project's verdicts comparable with the upstream tool's.
* **`active_silicon`** -- the same over cells belonging to any heat-generating region. On a
  single-die package these coincide; on a stack they do not, and the difference is not a detail.

**Neither is a junction-temperature certificate, and the field name says so.** A HotSpot grid value
is a CELL AVERAGE, so `max_j sup_p T_j(p)` is a worst-case maximum of cell averages -- correct as a
discrete, tool-compatible quantity, and *not* a bound on the pointwise temperature inside a cell.
Refinement alone does not close that gap: it needs a one-sided within-cell bound, from an a-posteriori
estimate or a comparison-principle supersolution. Until that exists the result is
`worst_case_max_cell_average_k` and must not be quoted as a junction limit. Peer review asked for
this naming twice.

Certifying the whole box -- every cell of every layer, which is what `find_hotpoint` literally does --
is available as `any_layer` but is **not** a junction criterion and is offered only for reproducing
the upstream number.

## Why it is affordable

Each cell temperature is affine in the power vector, exactly like each block average, so the
certifying quantity is

    U = max over cells j of  sup over admissible p of  T_j(p)

and every one of those suprema is the same greedy fill. At `grid512` there are 262 144 cells, so the
per-row Python loop that serves a 200-block operator does not survive -- `_extreme_rows` does the
whole set as one sort and one prefix sum. The cost is the operator build, which is unchanged: the
impulse responses are the same HotSpot runs, `-grid_steady_file` just asks for more of each run's
output.

Depends on `cross_grid_bound` and `core`, both leaves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from .core import PowerPolytope
from .cross_grid_bound import _extreme_rows
from .reanchored_certificate import assert_box_is_the_feasible_set

ENDPOINTS = ("tool_compatible", "active_silicon", "any_layer")


@dataclass(frozen=True)
class CellCertificate:
    """One design, one uncertainty set, one NAMED endpoint."""

    endpoint: str
    worst_case_max_cell_average_k: float
    argmax_cell: int
    comparison_band_k: float
    slack_k: float
    cells_considered: int

    def __post_init__(self) -> None:
        if self.endpoint not in ENDPOINTS:
            raise ValueError(f"endpoint must be one of {ENDPOINTS}, got {self.endpoint!r}")
        for name, value in (
            ("worst_case_max_cell_average_k", self.worst_case_max_cell_average_k),
            ("comparison_band_k", self.comparison_band_k),
            ("slack_k", self.slack_k),
        ):
            # `isfinite` first and separately: `NaN >= 0` and `NaN < 0` are both False, so a single
            # inequality would let a NaN pass the guard AND be recorded as a verdict.
            if not math.isfinite(value):
                raise ValueError(f"{name} is {value}; a certificate is not built from a non-number")
        if self.comparison_band_k < 0.0:
            raise ValueError("the band is clamped at zero before construction, never negative")
        if self.cells_considered <= 0:
            raise ValueError(
                "no cell belongs to the requested endpoint; certifying an empty set of rows would "
                "return a supremum over nothing"
            )

    @property
    def certified(self) -> bool:
        """`<=` is the frozen comparison, so zero slack certifies."""

        return self.slack_k >= 0.0


def certify_cells(
    cell_rows: np.ndarray,
    cell_ambient: np.ndarray,
    cell_endpoint: Sequence[str],
    space: PowerPolytope,
    total_w: float,
    *,
    endpoint: str,
    limit_k: float,
    margin_k: float,
    linearisation_k: float,
    comparison_rows: Optional[np.ndarray] = None,
    comparison_ambient: Optional[np.ndarray] = None,
) -> CellCertificate:
    """`max_j sup_p T_j(p) (+ band) <= limit - margin - linearisation` over the selected cells,
    where `T_j` is a CELL AVERAGE and the result is therefore not a pointwise bound.

    `cell_endpoint[j]` labels cell `j` with the narrowest endpoint it belongs to, and the selection
    is by containment: `active_silicon` cells are also `any_layer` cells. Restricting the rows is
    what makes the endpoint a *decision*, recorded in the result, rather than an assumption buried in
    which file was loaded.
    """

    if endpoint not in ENDPOINTS:
        raise ValueError(f"endpoint must be one of {ENDPOINTS}, got {endpoint!r}")
    rows = np.atleast_2d(np.asarray(cell_rows, dtype=float))
    ambient = np.atleast_1d(np.asarray(cell_ambient, dtype=float))
    labels = np.asarray(cell_endpoint)
    if ambient.shape != (rows.shape[0],) or labels.shape != (rows.shape[0],):
        raise ValueError("one ambient and one endpoint label are required per cell row")
    if not np.all(np.isfinite(rows)) or not np.all(np.isfinite(ambient)):
        raise ValueError("the cell operator must be finite to bound a peak temperature")
    # Containment, not equality: a `tool_compatible` die cell is also active silicon and also a cell
    # of some layer, so a wider endpoint must not silently exclude the narrower one's rows.
    admitted = {
        "tool_compatible": {"tool_compatible"},
        "active_silicon": {"tool_compatible", "active_silicon"},
        "any_layer": set(ENDPOINTS),
    }[endpoint]
    selected = np.isin(labels, list(admitted))
    if not selected.any():
        raise ValueError(
            f"no cell is labelled for the {endpoint!r} endpoint; the operator and the endpoint "
            "disagree about what this package contains"
        )
    assert_box_is_the_feasible_set(space, total_w)
    lower = np.asarray(space.lower_w, dtype=float)
    upper = np.asarray(space.upper_w, dtype=float)
    peaks = _extreme_rows(rows[selected], lower, upper, total_w) + ambient[selected]
    winner = int(np.argmax(peaks))
    peak = float(peaks[winner])
    band = 0.0
    if comparison_rows is not None:
        # The band is a supremum of the DIFFERENCE, taken independently of the peak's supremum. The
        # two are attained at different cells and different power maps, so adding them is
        # conservative and not tight -- which is the safe direction and is stated rather than hidden.
        difference = (
            np.atleast_2d(np.asarray(comparison_rows, dtype=float))[selected] - rows[selected]
        )
        offset = (
            np.atleast_1d(np.asarray(comparison_ambient, dtype=float))[selected] - ambient[selected]
        )
        band = max(float(np.max(_extreme_rows(difference, lower, upper, total_w) + offset)), 0.0)
    return CellCertificate(
        endpoint=endpoint,
        worst_case_max_cell_average_k=peak,
        argmax_cell=int(np.flatnonzero(selected)[winner]),
        comparison_band_k=band,
        slack_k=limit_k - margin_k - linearisation_k - peak - band,
        cells_considered=int(selected.sum()),
    )
