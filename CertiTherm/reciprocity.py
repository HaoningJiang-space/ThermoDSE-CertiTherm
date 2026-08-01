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

It is not negligible. At `grid512`, 2.5 % of 6.5 K/W over a 14 W map is about 2.3 K -- the same order
as the model-form band measured against the independent solver. **So part of any `gridN-avg`-versus-
FEM band is this mapping artefact and not model form**, and a band that does not separate them
attributes to HotSpot's physics an error introduced by how its output was read.

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
