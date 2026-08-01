"""Thermal reciprocity: `R` must be symmetric, and checking it is free.

The steady bilinear form `a(u,v) = int k grad u . grad v + int_{Gamma_R} h u v` is symmetric, so the
solution operator `S` is self-adjoint. With the block-average observation
`T_j(u) = |B_j|^-1 int_{B_j} u` and a unit-power impulse into block `i`,

    R_ji = <chi_j, S chi_i> / (|B_i| |B_j|) = <S chi_j, chi_i> / (|B_i| |B_j|) = R_ij

-- thermal Maxwell-Betti. **`R` is symmetric as a theorem, not as an approximation**, so any
asymmetry is a defect in the operator, the geometry, the boundary conditions, or the observation
functional. It costs one subtraction to check and it was never checked.

## What it found on the first run

| operator | relative asymmetry |
| --- | --- |
| FEM (DOLFINx) | 0.00 % (1e-10 - 1e-12) |
| HotSpot `block` | 0.00 % (1e-10) |
| HotSpot `grid512-avg` | **2.50 %** |
| HotSpot `grid256-avg` | **4.54 %** |
| HotSpot `grid128-avg` | **7.90 %** |

The FEM and the block model are symmetric to machine precision, as the theorem requires. HotSpot's
grid-to-block averaging is not, and the asymmetry **shrinks monotonically with refinement**, which
identifies it as a discretisation artefact of the mapping rather than a solver error: assigning grid
cells to blocks by cell membership is not the adjoint-consistent `L^2` projection, so `B_N T` is not
a self-adjoint observation.

## How much it actually costs, which is far less than the relative figure suggests

A first estimate multiplied the relative asymmetry by the operator scale and the total power --
"2.5 % of 6.5 K/W over 14 W is 2.3 K" -- and concluded the artefact was comparable to the model-form
band. **That was a misuse of a relative figure and is withdrawn.** The certifying quantity is
`max_j sup_p T_j(p)`, and symmetrising the operator (the nearest reciprocal one) moves it by:

| case | asymmetry | shift in `sup_p T` |
| --- | --- | --- |
| `arch_a`/transformer, `grid128-avg` | 12.03 % | **+0.0711 K** |
| `arch_b`/transformer, `grid128-avg` | 9.94 % | +0.0534 K |
| `arch_c`/resnet50, `grid128-avg` | 7.90 % | +0.0142 K |
| `arch_a`/transformer, `grid512-avg` | 6.35 % | **+0.0020 K** |
| `arch_b`/transformer, `grid512-avg` | 3.08 % | +0.0199 K |
| `arch_c`/resnet50, `grid512-avg` | 2.50 % | +0.0107 K |

**Two orders of magnitude below the first estimate.** The asymmetry is entrywise and relative to the
largest entry, while the certificate is a maximum over rows of a weighted sum; the asymmetric parts
neither align with the argmax row nor with the extremal power vector, so they largely cancel.

So the invariant earns its place as a **defect detector** -- it is exact, it costs one subtraction,
and it identified a real inconsistency in how HotSpot's grid output is read -- and not as an error
term. A `gridN-avg` band carries at most a few hundredths of a kelvin of this artefact, not a few
kelvin.

This module reports; it does not refuse. A tolerance would have to be a modelling decision about how
much mapping artefact is acceptable, and that decision belongs to the caller.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ReciprocityReport:
    """How far one response matrix is from the symmetry the physics requires."""

    max_asymmetry_k_per_w: float
    max_magnitude_k_per_w: float
    relative: float
    worst_pair: tuple

    def __post_init__(self) -> None:
        for name, value in (
            ("max_asymmetry_k_per_w", self.max_asymmetry_k_per_w),
            ("max_magnitude_k_per_w", self.max_magnitude_k_per_w),
            ("relative", self.relative),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} is {value}; a reciprocity residual is a finite magnitude")


def reciprocity_residual(response_k_per_w: np.ndarray) -> ReciprocityReport:
    """`max |R - R^T|`, its scale, and which pair of blocks is worst."""

    matrix = np.asarray(response_k_per_w, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError(
            f"reciprocity is a statement about a square block-to-block operator, got {matrix.shape}"
        )
    if not np.all(np.isfinite(matrix)):
        raise ValueError("the response matrix must be finite to have a reciprocity residual")
    gap = np.abs(matrix - matrix.T)
    scale = float(np.max(np.abs(matrix)))
    worst = np.unravel_index(int(np.argmax(gap)), gap.shape)
    return ReciprocityReport(
        max_asymmetry_k_per_w=float(np.max(gap)),
        max_magnitude_k_per_w=scale,
        # `scale == 0` means an all-zero operator, which is symmetric; the residual is 0 and so is
        # the ratio. Guarding here rather than dividing keeps a degenerate case from becoming NaN.
        relative=float(np.max(gap) / scale) if scale > 0.0 else 0.0,
        worst_pair=(int(worst[0]), int(worst[1])),
    )


def family_reciprocity_residuals(family) -> np.ndarray:
    """One residual per model of a `ThermalFamily`, in K/W. `NaN` where reciprocity does not apply.

    A second implementation of this landed in `core.py` while this module was being written, which is
    exactly the duplication the project's own rule warns about -- two constructions of one invariant,
    neither checking the other. The primitive lives here because this is where the measurements and
    the tests are; `core` stays a leaf that validates its own dataclasses and does not grow analysis.

    **Reciprocity applies only when a model's evaluation points ARE its source blocks.** A
    block-average family observes the same blocks it drives, so `R` is square and must be symmetric.
    A cell-level operator observes 262 144 cells from 237 sources: the matrix is not square and the
    statement is simply not about it. Those models get `NaN` rather than a fabricated zero.

    The other implementation's docstring said no committed operator had been measured against this.
    That is no longer true and the numbers are in this module's header: HotSpot's `gridN-avg` breaks
    it by 2.5-12 %, shrinking with refinement, while `block` and the FEM hold it to 1e-10.
    """

    response = np.asarray(family.response_k_per_w, dtype=float)
    residuals = np.full(response.shape[0], np.nan)
    for index in range(response.shape[0]):
        matrix = response[index]
        if matrix.shape[0] == matrix.shape[1]:
            residuals[index] = reciprocity_residual(matrix).max_asymmetry_k_per_w
    return residuals
