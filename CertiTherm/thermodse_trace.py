"""Fail-closed lowering of ThermoDSE monitor data to a spatial phase trace.

ThermoDSE records per-order, per-core energy for seven components, but only aggregate
per-order NoC, NoP, and DRAM energy.  The core energy has an exact name mapping into the
generated floorplan:

    mtxu -> mtxu_N       vecu -> vecu_N       ubuf -> ubuf_N
    l0a + l0b -> ibuf_N  l0c + l1c -> obuf_N

There is no equally defensible spatial mapping for the three aggregate external channels.
In particular, inventing a uniform distribution would conserve energy while fabricating
where the heat was deposited.  This module therefore returns the exact floorplan-aligned
core trace and carries NoC/NoP/DRAM as explicit *unplaced* energy.  A caller may use the
trace for a diagnostic, but must not call it a complete thermal trace while the residual is
non-zero.

All monitor energies are pJ and latencies are cycles; public outputs use SI units.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np

from CertiTherm.phase_trace import PhaseTrace


THERMODSE_COMPONENTS = ("mtxu", "vecu", "ubuf", "l0a", "l0b", "l0c", "l1c")
UNPLACED_CHANNELS = ("noc", "nop", "dram")


@dataclass(frozen=True)
class ThermoDSETraceLowering:
    """One exact partial lowering plus the energy that still lacks a location."""

    block_ids: Tuple[str, ...]
    trace: PhaseTrace
    unplaced_energy_j: np.ndarray  # (phases, noc/nop/dram)

    def __post_init__(self) -> None:
        blocks = tuple(str(name) for name in self.block_ids)
        residual = np.asarray(self.unplaced_energy_j, dtype=float)
        if len(blocks) != self.trace.dimension or len(set(blocks)) != len(blocks):
            raise ValueError("block_ids must uniquely identify every trace column")
        if residual.shape != (self.trace.n_phases, len(UNPLACED_CHANNELS)):
            raise ValueError("unplaced_energy_j must have shape (phases, 3)")
        if not np.all(np.isfinite(residual)) or np.any(residual < 0.0):
            raise ValueError("unplaced_energy_j must be finite and non-negative")
        residual.setflags(write=False)
        object.__setattr__(self, "block_ids", blocks)
        object.__setattr__(self, "unplaced_energy_j", residual)

    @property
    def represented_energy_j(self) -> float:
        return float(self.trace.energy_j().sum())

    @property
    def residual_energy_j(self) -> float:
        return float(self.unplaced_energy_j.sum())

    @property
    def thermal_energy_j(self) -> float:
        return self.represented_energy_j + self.residual_energy_j

    @property
    def represented_fraction(self) -> float:
        total = self.thermal_energy_j
        return self.represented_energy_j / total if total else float("nan")

    @property
    def is_complete(self) -> bool:
        """True only when every joule has a floorplan location."""
        return bool(np.all(self.unplaced_energy_j == 0.0))


def lower_monitor_trace(
    *,
    block_ids: Sequence[str],
    latency_cycles: np.ndarray,
    core_energy_pj: np.ndarray,
    noc_energy_pj: np.ndarray,
    nop_energy_pj: np.ndarray,
    dram_energy_pj: np.ndarray,
    clock_hz: float,
    component_names: Sequence[str] = THERMODSE_COMPONENTS,
) -> ThermoDSETraceLowering:
    """Lower one ThermoDSE network snapshot without inventing heat locations.

    The function fails on zero-duration orders, missing floorplan blocks, ambiguous
    component names, or any energy/time shape mismatch.  It deliberately does not accept a
    policy for smearing external energy: that policy needs route/PHY evidence and belongs
    in a later, separately reviewed lowering stage.
    """

    blocks = tuple(str(name) for name in block_ids)
    if not blocks or len(set(blocks)) != len(blocks):
        raise ValueError("block_ids must be non-empty and unique")
    if not np.isfinite(clock_hz) or clock_hz <= 0.0:
        raise ValueError("clock_hz must be finite and positive")

    latency = np.asarray(latency_cycles, dtype=float)
    core = np.asarray(core_energy_pj, dtype=float)
    external = tuple(
        np.asarray(values, dtype=float)
        for values in (noc_energy_pj, nop_energy_pj, dram_energy_pj)
    )
    names = tuple(str(name) for name in component_names)

    if latency.ndim != 1 or latency.size == 0:
        raise ValueError("latency_cycles must be a non-empty vector")
    if core.ndim != 3 or core.shape[0] != latency.size:
        raise ValueError("core_energy_pj must have shape (phases, cores, components)")
    if core.shape[2] != len(names) or len(set(names)) != len(names):
        raise ValueError("component_names must uniquely name every component column")
    if set(names) != set(THERMODSE_COMPONENTS):
        raise ValueError(
            "component_names must contain exactly " + ", ".join(THERMODSE_COMPONENTS)
        )
    if any(values.shape != latency.shape for values in external):
        raise ValueError("each external-energy channel must match latency_cycles")
    arrays = (latency, core, *external)
    if any(not np.all(np.isfinite(values)) for values in arrays):
        raise ValueError("monitor arrays must be finite")
    if np.any(latency <= 0.0):
        raise ValueError(
            "every ThermoDSE order must have positive duration; refusing to drop or "
            "merge a zero-duration order"
        )
    if np.any(core < 0.0) or any(np.any(values < 0.0) for values in external):
        raise ValueError("monitor energies must be non-negative")

    index = {name: column for column, name in enumerate(blocks)}
    comp = {name: column for column, name in enumerate(names)}
    n_phases, n_cores, _ = core.shape
    energy_j = np.zeros((n_phases, len(blocks)), dtype=float)

    mappings = (
        ("mtxu", ("mtxu",)),
        ("vecu", ("vecu",)),
        ("ubuf", ("ubuf",)),
        ("ibuf", ("l0a", "l0b")),
        ("obuf", ("l0c", "l1c")),
    )
    required = []
    for core_id in range(n_cores):
        for floorplan_prefix, sources in mappings:
            block = f"{floorplan_prefix}_{core_id}"
            required.append(block)
            if block not in index:
                raise ValueError(f"floorplan is missing required core block {block}")
            energy_j[:, index[block]] = sum(
                core[:, core_id, comp[source]] for source in sources
            ) * 1e-12

    # A mismatched architecture can contain all low-numbered blocks but additional core
    # blocks as well.  Refuse that silent partial alignment.
    known_prefixes = tuple(prefix for prefix, _ in mappings)
    unexpected = [
        block
        for block in blocks
        if block.startswith(tuple(f"{prefix}_" for prefix in known_prefixes))
        and block not in set(required)
    ]
    if unexpected:
        raise ValueError(
            "floorplan contains core blocks not represented by monitor data: "
            + ", ".join(unexpected[:5])
        )

    durations_s = latency / float(clock_hz)
    powers_w = energy_j / durations_s[:, None]
    residual_j = np.column_stack(external) * 1e-12
    lowering = ThermoDSETraceLowering(
        block_ids=blocks,
        trace=PhaseTrace(durations_s=durations_s, powers_w=powers_w),
        unplaced_energy_j=residual_j,
    )

    source_total_j = (float(core.sum()) + sum(float(values.sum()) for values in external)) * 1e-12
    if not np.isclose(
        lowering.thermal_energy_j, source_total_j, rtol=1e-12, atol=1e-18
    ):
        raise RuntimeError("lowered trace does not conserve source monitor energy")
    return lowering
