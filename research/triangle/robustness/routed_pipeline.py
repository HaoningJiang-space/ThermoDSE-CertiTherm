"""The chain every routed-trace driver walks, named once instead of retyped five times.

## Why this exists

`certified_search`, `envelope_span_sweep`, `lowering_sensitivity` and `composed_result` each contained
the same thirty lines: run ThermoDSE once, lower the routed trace, reduce it to a steady vector, write
the augmented floorplan, write the package config, build or fetch the cell operator, certify. Four
copies of one pipeline is four places for it to drift, and it had already started to -- one copy
reduced the trace before checking its receipts, another after.

The chain is the interesting object, so it is written down:

    lower_case()        ThermoDSE + routed lowering  ->  RoutedCase (steady vector, floorplan, EDYP)
    operator_for()      RoutedCase + library         ->  (rows, ambient, was_hit)
    nominal_peak()      one power map                ->  what the field reports
    certified_peak()    an envelope                  ->  what this project reports

Each driver then says what it varies -- a design field, an envelope width, a lowering parameter, a
mapping -- and nothing else. That is the whole refactor: the drivers become their own question.

## What is deliberately NOT here

The certificate, the operator builder, the lowering and the trace reduction all stay where they are.
This module composes them; it re-implements none of them, because a second implementation cannot be
its own oracle and this project has paid for that lesson four times.

NON-CLAIM support code. No driver semantics change: the composition is the same one the four copies
performed, verified by re-running a driver against its stored result.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from CertiTherm.cell_certificate import certify_cells
from CertiTherm.cross_grid_bound import _extreme_rows
from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K
from CertiTherm.measurements import activity_bounded_power_space, envelope_is_singleton
from CertiTherm.paths import ROOT, TEMPLATE
from CertiTherm.routed_trace import lower_routed_trace
from CertiTherm.tabular import read_rows
from research.triangle.complete_trace_probe import capture_frozen_inputs
from research.triangle.robustness.cell_certificate_run import _configure, cell_operator

MARGIN_K = 0.05
CEILING_K = THERMAL_LIMIT_K - MARGIN_K - MODEL_ERROR_LIMIT_K
RECONCILE_RTOL = 1e-9


@dataclass(frozen=True)
class RoutedCase:
    """One design lowered onto its augmented floorplan: what every driver downstream needs.

    `placed_w` is the duration-weighted mean of the routed trace -- the unique reduction that
    conserves energy -- and it is checked against the lowering's own source receipt before this
    object exists, so no caller can hold a case whose vector does not carry its stated energy.
    """

    workload: str
    arch_id: str
    blocks: tuple
    placed_w: np.ndarray
    floorplan_text: str
    horizon_s: float
    energy_mj: float
    latency_ms: float
    die_yield: float
    receipts: dict

    @property
    def total_w(self) -> float:
        return float(np.sum(self.placed_w))

    @property
    def edyp(self) -> float:
        """`E * D / Y`, ThermoDSE's own objective (`core/chiplet_eva.py:234`), recomputed here."""
        if not all(map(math.isfinite, (self.energy_mj, self.latency_ms, self.die_yield))) \
                or self.die_yield <= 0.0:
            raise ValueError(f"EDYP undefined for E={self.energy_mj!r} D={self.latency_ms!r} "
                             f"Y={self.die_yield!r}")
        return self.energy_mj * self.latency_ms / self.die_yield


def lower_case(work: Path, workload: str, arch_id: str, *, arch_row: dict | None = None,
               io_aspect_ratio: float = 1.0, endpoint_split: float = 0.5) -> RoutedCase:
    """Run ThermoDSE once, place every source where its route says, reduce to the steady vector."""

    frozen = capture_frozen_inputs(work, workload, arch_id, io_aspect_ratio=io_aspect_ratio,
                                   arch_row=arch_row)
    routed = lower_routed_trace(
        frozen["core"], floorplan=frozen["augmented"], events=frozen["events"],
        compute_shape=frozen["shape"], chiplet_cuts=frozen["cuts"],
        noc_hop_cost_pj=frozen["noc_hop_cost_pj"], nop_hop_cost_pj=frozen["nop_hop_cost_pj"],
        batch_factor=frozen["batch_factor"], endpoint_split=endpoint_split,
    )
    augmented = frozen["augmented"]
    durations = np.asarray(routed.trace.durations_s, dtype=float)
    powers = np.asarray(routed.trace.powers_w, dtype=float)
    if not np.all(np.isfinite(powers)) or not np.all(np.isfinite(durations)):
        raise SystemExit(f"{arch_id}/{workload}: the routed trace carries a non-finite entry")
    if np.any(powers < 0.0) or np.any(durations <= 0.0):
        raise SystemExit(f"{arch_id}/{workload}: negative power or non-positive duration")
    horizon = float(durations.sum())
    placed = (powers * durations[:, None]).sum(axis=0) / horizon

    receipts = {
        "source_energy_j": float(routed.source_energy_j),
        "monitor_source_energy_j": float(routed.monitor_source_energy_j),
        "route_energy_j": float(routed.route_energy_j),
        "monitor_route_energy_j": float(routed.monitor_route_energy_j),
    }
    # The lowering refuses internally when these disagree; re-checking here means no RoutedCase can
    # exist whose vector does not reconcile, whatever a future caller does with the lowering.
    for name in ("source", "route"):
        got, want = receipts[f"{name}_energy_j"], receipts[f"monitor_{name}_energy_j"]
        if not np.isclose(got, want, rtol=RECONCILE_RTOL, atol=0.0):
            raise SystemExit(f"{arch_id}/{workload}: {name} energy does not reconcile, "
                             f"{got!r} against {want!r}")
    reduced = float(placed.sum() * horizon)
    if not np.isclose(reduced, receipts["source_energy_j"], rtol=1e-9, atol=0.0):
        raise SystemExit(
            f"{arch_id}/{workload}: the duration-weighted mean carries {reduced!r} J against a "
            f"source receipt of {receipts['source_energy_j']!r}; the reduction loses energy"
        )

    return RoutedCase(
        workload=workload, arch_id=arch_id,
        blocks=tuple(str(b) for b in augmented.block_ids),
        placed_w=placed, floorplan_text=augmented.text, horizon_s=horizon,
        energy_mj=float(frozen["endpoint_energy_mj"]),
        latency_ms=float(frozen["endpoint_latency_ms"]),
        die_yield=float(frozen["die_yield"]), receipts=receipts,
    )


def operator_for(case: RoutedCase, library, work: Path, *, workers: int = 1):
    """`(rows, ambient, was_hit)` for this case's geometry, built once and reused by digest."""

    work.mkdir(parents=True, exist_ok=True)
    floorplan = work / "floorplan.flp"
    floorplan.write_text(case.floorplan_text, encoding="utf-8")
    config = work / "package.config"
    packages = {row["package_id"]: row for row in read_rows(ROOT / "experiments" / "packages.tsv")}
    if library.package_id not in packages:
        raise SystemExit(f"unknown package {library.package_id!r}; have {sorted(packages)}")
    _configure(TEMPLATE / "example.config", config, packages[library.package_id])
    blocks = list(case.blocks)
    return library.get_or_build(
        case.floorplan_text, blocks,
        lambda: cell_operator(config, floorplan, blocks, library.model_id, work, workers),
    )


def nominal_peak(rows, ambient, case: RoutedCase) -> float:
    """`max_j T_j(p_nom)`: the point evaluation the whole field reports."""
    peak = float(np.max(np.asarray(rows) @ case.placed_w + np.asarray(ambient)))
    if not math.isfinite(peak):
        raise SystemExit("the nominal peak is not finite; UNRESOLVED rather than a number")
    return peak


def envelope(case: RoutedCase, span: float):
    """The declared activity envelope for this case, refusing a degenerate one.

    A singleton envelope makes every envelope quantity a point evaluation wearing another name
    (`CertiTherm.measurements.envelope_is_singleton`, `docs/ADVERSARIAL_SELF_REVIEW.md` E1). Callers
    that want to report it rather than refuse can call the predicate themselves; the default here is
    to refuse, because silently returning the nominal peak is what produced that anomaly.
    """
    space = activity_bounded_power_space(list(case.blocks), case.placed_w, activity_span=span)
    if envelope_is_singleton(space):
        raise SystemExit(
            f"{case.arch_id}/{case.workload}: the activity envelope at span {span} admits exactly "
            "one power map, so a supremum over it is the nominal point evaluation. Every live block "
            "is alone in its content class and the class-total cap pins the vector."
        )
    return space


def certified_peak(rows, ambient, case: RoutedCase, span: float) -> float:
    """`max_j sup_p T_j(p)` over the declared envelope, exactly."""
    cell = certify_cells(
        rows, ambient, ["tool_compatible"] * np.asarray(rows).shape[0], envelope(case, span),
        case.total_w, endpoint="tool_compatible", limit_k=THERMAL_LIMIT_K, margin_k=MARGIN_K,
        linearisation_k=MODEL_ERROR_LIMIT_K,
    )
    peak = float(cell.worst_case_max_cell_average_k)
    if not math.isfinite(peak):
        raise SystemExit(f"span {span}: the supremum is not finite; UNRESOLVED rather than a number")
    return peak


def certified_peak_from_vector(rows, ambient, blocks: Sequence[str], placed, span: float) -> float:
    """The same quantity for a power vector that is not a `RoutedCase` -- e.g. a permuted mapping."""
    placed = np.asarray(placed, dtype=float)
    space = activity_bounded_power_space(list(blocks), placed, activity_span=span)
    peak = float(np.max(_extreme_rows(
        np.asarray(rows), np.asarray(space.lower_w, dtype=float),
        np.asarray(space.upper_w, dtype=float), float(placed.sum())) + np.asarray(ambient)))
    if not math.isfinite(peak):
        raise SystemExit("the supremum is not finite; UNRESOLVED rather than a number")
    return peak
