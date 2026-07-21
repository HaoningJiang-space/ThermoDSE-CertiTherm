"""Certified thermal-mode analysis; never a learned simulation surrogate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

import numpy as np
from scipy.optimize import linprog

from .core import MeasurementAction, PowerPolytope, ThermalFamily


@dataclass(frozen=True)
class ThermalSpectrum:
    """Joint input modes of every registered model and thermal point."""

    singular_values: np.ndarray
    modes: np.ndarray

    def retained_energy(self, rank: int) -> float:
        energy = self.singular_values**2
        return float(np.sum(energy[:rank]) / np.sum(energy)) if np.any(energy) else 1.0


def thermal_spectrum(thermal: ThermalFamily) -> ThermalSpectrum:
    """Diagonalize the stacked HotSpot Green operators in power space."""

    stacked = thermal.response_k_per_w.reshape(-1, thermal.blocks)
    eigenvalues, modes = np.linalg.eigh(stacked.T @ stacked)
    order = np.argsort(eigenvalues)[::-1]
    singular = np.sqrt(np.maximum(eigenvalues[order], 0.0))
    return ThermalSpectrum(singular, modes[:, order])


def audit_ranks(dimension: int) -> Tuple[int, ...]:
    """Deterministic logarithmic rank grid including both exact endpoints."""

    ranks = {0, dimension}
    value = 1
    while value < dimension:
        ranks.add(value)
        value *= 2
    return tuple(sorted(ranks))


def _box_total_extreme(
    polytope: PowerPolytope, row: np.ndarray, maximize: bool
) -> Optional[float]:
    n = polytope.dimension
    if (
        polytope.a_ub.shape[0]
        or polytope.a_eq.shape != (1, n)
        or not np.allclose(polytope.a_eq[0], 1.0, atol=0.0, rtol=0.0)
    ):
        return None
    coefficients = row if maximize else -row
    power = polytope.lower_w.copy()
    remaining = float(polytope.b_eq[0] - np.sum(power))
    for index in np.argsort(coefficients)[::-1]:
        addition = min(remaining, polytope.upper_w[index] - power[index])
        power[index] += addition
        remaining -= addition
        if remaining <= 1e-12:
            break
    if remaining > 1e-8:
        raise ValueError("box-with-total power polytope is infeasible")
    value = float(row @ power)
    return value if maximize else value


def _linear_extreme(
    polytope: PowerPolytope, row: np.ndarray, maximize: bool
) -> float:
    direct = _box_total_extreme(polytope, row, maximize)
    if direct is not None:
        return direct
    objective = -row if maximize else row
    result = linprog(
        objective,
        A_ub=polytope.a_ub,
        b_ub=polytope.b_ub,
        A_eq=polytope.a_eq,
        b_eq=polytope.b_eq,
        bounds=list(zip(polytope.lower_w, polytope.upper_w)),
        method="highs",
        options={
            "primal_feasibility_tolerance": 1e-10,
            "dual_feasibility_tolerance": 1e-10,
        },
    )
    if not result.success:
        raise RuntimeError(f"spectral tail LP unresolved: {result.message}")
    return float(row @ result.x)


def certified_tail_bound_k(
    polytope: PowerPolytope,
    thermal: ThermalFamily,
    spectrum: ThermalSpectrum,
    rank: int,
) -> float:
    """Exact registered-domain L-infinity error of a modal truncation."""

    if not 0 <= rank <= polytope.dimension or thermal.blocks != polytope.dimension:
        raise ValueError("invalid spectral rank or inconsistent power dimension")
    modes = spectrum.modes[:, :rank]
    projector = modes @ modes.T
    rows = thermal.response_k_per_w.reshape(-1, thermal.blocks) @ (
        np.eye(thermal.blocks) - projector
    )
    bound = 0.0
    for row in rows:
        lower = _linear_extreme(polytope, row, False)
        upper = _linear_extreme(polytope, row, True)
        bound = max(bound, abs(lower), abs(upper))
    return bound


def channel_spectral_leverage(
    action: MeasurementAction, spectrum: ThermalSpectrum
) -> float:
    """Single-channel coverage of thermally amplified input-mode energy."""

    norm = float(np.linalg.norm(action.vector))
    energy = spectrum.singular_values**2
    if norm == 0 or not np.any(energy):
        return 0.0
    coefficients = spectrum.modes.T @ (action.vector / norm)
    return float(np.sum(energy * coefficients**2) / np.sum(energy))


def spectral_envelope(
    polytope: PowerPolytope,
    thermal: ThermalFamily,
    ranks: Optional[Iterable[int]] = None,
) -> tuple[ThermalSpectrum, tuple[tuple[int, float, float], ...]]:
    """Return rank, retained energy, and certified peak-tail bound records."""

    spectrum = thermal_spectrum(thermal)
    records = tuple(
        (
            rank,
            spectrum.retained_energy(rank),
            certified_tail_bound_k(polytope, thermal, spectrum, rank),
        )
        for rank in (audit_ranks(polytope.dimension) if ranks is None else ranks)
    )
    return spectrum, records
