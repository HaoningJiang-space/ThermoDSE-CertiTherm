"""Certify at the cell endpoint from the ROUTED trace, so the spreading bracket becomes a number.

`docs/THE_GENERATOR_PUTS_THE_MISSING_HEAT_CENTRALLY.md` bracketed what the legacy trace's **uniform**
NoC spread can hide at **3.137 - 46.445 K**, with every upper bracket exceeding its own slack on all
six development points. That bracket is the largest unquantified term in this project, and unlike the
missing DRAM and NoP heat it is not a matvec: it needs the spatial information back.

**The spatial information is already back.** `CertiTherm/physical_nop.py` replaces ThermoDSE's route
ledger — whose `link_hops` is *"allocated with an `x + 2` row width but indexed with `x`"* — with
unaliased deterministic XY routing, and `CertiTherm/routed_trace.py` places the result: same-chiplet
NoC energy split between the two facing `io_*` blocks, cross-chiplet NoP on the intervening
`blockX_*`/`blockY_*`, DRAM-access energy on explicit DRAM dies. `docs/V6_PHYSICAL_TRACE_GATE.md`
validated the event capture at a worst per-order relative error of `2.19e-15`.

What has never been done is **certifying on it**. `CertiTherm/experiments.py` never references either
module and `thermodse_bridge.py:134` defaults `physical_nop=False`, so every verdict in this
repository was taken on the legacy trace. This driver closes that gap for one case.

## What is reused rather than rebuilt

Everything except the input. `cell_operator`, `certify_cells`, `_block_average`, `_configure` and
`_rows` come from `cell_certificate_run.py` unchanged, so the endpoint, the projection and the
certificate are the same objects `docs/CELL_ENDPOINT_RESULT.md` reports — which is the point, since
the number produced here is meant to be compared against that table and not against a new convention.

## The one reduction this driver performs, and its check

The routed trace is time-resolved, `powers_w` of shape `(orders, blocks)` with `durations_s`. The
steady operator consumes one vector, so the reduction is the **duration-weighted mean** — the unique
reduction that conserves energy. It is checked against the trace's own `source_energy_j` receipt
rather than assumed, and the trace's two reconciliation receipts (`source` and `route` against their
`monitor_*` counterparts) are enforced before anything is built, because a lowering that does not
reconcile is not evidence about placement.

NON-CLAIM diagnostic. HotSpot, not FEM: the endpoint must be the one `CELL_ENDPOINT_RESULT.md` uses
or the comparison is against a different convention. That makes the impulse loop CPU-bound HotSpot
rather than the cuDSS batch path.

Usage (moe-server, repo root):

    .venv/bin/python research/triangle/robustness/routed_cell_certificate.py \\
        <complete_trace.npz> <complete_floorplan.flp> <workspace> <out.json> [model] [span] [workers]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from CertiTherm.cell_certificate import certify_cells                     # noqa: E402
from CertiTherm.cross_grid_bound import _extreme_rows                     # noqa: E402
from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K  # noqa: E402
from CertiTherm.measurements import activity_bounded_power_space          # noqa: E402
from CertiTherm.paths import ROOT, TEMPLATE                               # noqa: E402
from CertiTherm.tabular import read_rows as _rows                         # noqa: E402

from cell_certificate_run import _block_average, _configure, cell_operator  # noqa: E402

MARGIN_K = 0.05
RECONCILE_RTOL = 1e-9


def _steady_power(trace_path: Path):
    """`(block_ids, duration-weighted mean power)`, with the trace's own receipts enforced first."""

    with np.load(trace_path, allow_pickle=False) as data:
        blocks = [str(b) for b in data["block_ids"]]
        powers = np.asarray(data["powers_w"], dtype=float)
        durations = np.asarray(data["durations_s"], dtype=float)
        receipts = {k: float(data[k]) for k in (
            "source_energy_j", "monitor_source_energy_j",
            "route_energy_j", "monitor_route_energy_j",
        )}

    # The lowering's own reconciliation. `lower_routed_trace` refuses when these disagree, but the
    # trace on disk was produced by an earlier run and nothing re-checks it at load. A placement that
    # does not reconcile is not evidence ABOUT placement, whatever else it is.
    for name in ("source", "route"):
        got, want = receipts[f"{name}_energy_j"], receipts[f"monitor_{name}_energy_j"]
        if not np.isclose(got, want, rtol=RECONCILE_RTOL, atol=0.0):
            raise SystemExit(
                f"{name} energy does not reconcile: {got!r} against monitor {want!r}, "
                f"relative {abs(got - want) / abs(want):.3e} > {RECONCILE_RTOL}"
            )

    if powers.ndim != 2 or durations.shape != (powers.shape[0],):
        raise SystemExit(f"powers_w {powers.shape} and durations_s {durations.shape} disagree")
    if not np.all(np.isfinite(powers)) or not np.all(np.isfinite(durations)):
        raise SystemExit("routed trace carries non-finite power or duration")
    if np.any(powers < 0.0) or np.any(durations <= 0.0):
        raise SystemExit("routed trace carries negative power or non-positive duration")

    horizon = float(durations.sum())
    mean_power = (powers * durations[:, None]).sum(axis=0) / horizon

    # The duration-weighted mean is the unique reduction that conserves energy; check it against the
    # trace's own source receipt rather than trusting the arithmetic.
    reduced_energy = float(mean_power.sum() * horizon)
    if not np.isclose(reduced_energy, receipts["source_energy_j"], rtol=1e-9, atol=0.0):
        raise SystemExit(
            f"the duration-weighted mean carries {reduced_energy!r} J against a source receipt of "
            f"{receipts['source_energy_j']!r}; the reduction is not energy-conserving"
        )
    return blocks, mean_power, horizon, receipts


def main() -> None:
    trace_path = Path(sys.argv[1])
    floorplan_src = Path(sys.argv[2])
    work = Path(sys.argv[3])
    out_path = Path(sys.argv[4])
    model_id = sys.argv[5] if len(sys.argv) > 5 else "grid128-avg"
    span = float(sys.argv[6]) if len(sys.argv) > 6 else 0.30
    # Scheduling only: the operator is bit-identical at every worker count, see cell_operator.
    workers = int(sys.argv[7]) if len(sys.argv) > 7 else 1

    blocks, placed, horizon, receipts = _steady_power(trace_path)
    floorplan_text = floorplan_src.read_text(encoding="utf-8")
    flp_blocks = [line.split()[0] for line in floorplan_text.splitlines() if line.split()]
    if flp_blocks != blocks:
        raise SystemExit(
            f"floorplan lists {len(flp_blocks)} blocks and the trace {len(blocks)}, or their order "
            "differs; a power vector aligned to one and placed by the other is silently wrong"
        )

    work.mkdir(parents=True, exist_ok=True)
    floorplan = work / "floorplan.flp"
    floorplan.write_text(floorplan_text, encoding="utf-8")
    config = work / "package.config"
    packages = {row["package_id"]: row for row in _rows(ROOT / "experiments" / "packages.tsv")}
    _configure(TEMPLATE / "example.config", config, packages["default"])

    print(f"routed trace: {len(blocks)} blocks, {horizon:.6g} s horizon, "
          f"{float(placed.sum()):.4f} W mean, receipts reconcile", flush=True)

    operator = out_path.with_suffix(".npz")
    if not operator.exists():
        started = time.monotonic()
        rows, ambient = cell_operator(config, floorplan, blocks, model_id, work, workers)
        print("  built in %.0f s" % (time.monotonic() - started), flush=True)
        np.savez_compressed(
            operator, model_ids=np.asarray([model_id]), response_k_per_w=rows[None, :, :],
            ambient_k=ambient[None, :], block_ids=np.asarray(blocks),
            cell_endpoint=np.asarray(["tool_compatible"] * rows.shape[0]),
        )
    with np.load(operator, allow_pickle=False) as data:
        rows = np.asarray(data["response_k_per_w"], dtype=float)[0]
        ambient = np.asarray(data["ambient_k"], dtype=float)[0]
        if [str(b) for b in data["block_ids"]] != blocks:
            raise SystemExit("the saved operator resolves a different block list than this trace")

    total = float(placed.sum())
    space = activity_bounded_power_space(blocks, placed, activity_span=span)
    cell = certify_cells(
        rows, ambient, ["tool_compatible"] * rows.shape[0], space, total,
        endpoint="tool_compatible", limit_k=THERMAL_LIMIT_K, margin_k=MARGIN_K,
        linearisation_k=MODEL_ERROR_LIMIT_K,
    )
    block_rows = _block_average(rows, blocks, floorplan_text)
    block_ambient = _block_average(ambient[:, None], blocks, floorplan_text).ravel()
    block_peak = float(np.max(
        _extreme_rows(block_rows, np.asarray(space.lower_w, dtype=float),
                      np.asarray(space.upper_w, dtype=float), total) + block_ambient
    ))

    # THE NOMINAL PEAK WAS NEVER WRITTEN, AND THAT MADE THIS EVIDENCE UNHARVESTABLE. The certified
    # peak alone cannot be paired with anything: every population question in this project is about
    # the GAP between the point evaluation and the supremum. Six routed certificates -- the round's
    # central evidence -- were invisible to `limit_parametric_disagreement` for exactly this reason.
    # It is one matvec on an operator already in memory.
    nominal = float(np.max(rows @ placed + ambient))
    if not np.isfinite(nominal):
        raise SystemExit("the nominal peak is not finite; UNRESOLVED rather than a number")

    payload = {
        "trace": trace_path.name, "floorplan": floorplan_src.name,
        "nominal_peak_k": nominal,
        "model": model_id, "span": span,
        "blocks": len(blocks), "cells": int(rows.shape[0]),
        "horizon_s": horizon, "mean_power_w": total,
        "endpoint": cell.endpoint,
        "worst_case_max_cell_average_k": cell.worst_case_max_cell_average_k,
        "argmax_cell": cell.argmax_cell,
        "slack_k": cell.slack_k,
        "certified": cell.certified,
        "sup_peak_over_exact_block_projection_k": block_peak,
        "reconciliation": receipts,
    }
    attach(payload, [CaseRecord(
        case=trace_path.stem, nominal_peak_k=nominal,
        certified_peak_k=cell.worst_case_max_cell_average_k, span=span,
        ceiling_k=THERMAL_LIMIT_K - MARGIN_K - MODEL_ERROR_LIMIT_K, model=model_id,
        source="routed_cell_certificate",
    )])
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
