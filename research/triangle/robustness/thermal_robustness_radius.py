"""The thermal robustness radius: the largest activity envelope under which a design still certifies.

## The metric, and why it is the one a decision can consume

A peak temperature is a number about ONE power map. Every thermal-aware DSE in the field reports one
-- evaluate a workload, read the peak, compare to a limit -- and every one of them therefore answers
"is this design feasible for the traces we happened to run", not "is it feasible". The certificate
here answers the second question, because it takes an exact supremum over a declared activity
envelope rather than evaluating a point in it.

That makes a scalar available that a point evaluation cannot produce:

    radius(design) = sup { s >= 0 : sup_{p in P(s)} max_j T_j(p) <= L - margin - error }

the largest envelope half-width the design tolerates. `radius = 0` means it is feasible only exactly
at its nominal activity; a large radius means workload variation cannot break it. It is one
interpretable number per design, it is monotone by construction, and it ORDERS designs by something a
nominal peak cannot see.

## Why it is cheap enough to sit inside a search loop, which is the whole point

`activity_bounded_power_space` is a box with a total-power equality. The support function of that set
is a FRACTIONAL KNAPSACK: sort the row's coefficients descending and fill greedily. So

    sup_{p in P} (R p)_j  =  r_j . lower  +  greedy fill of the spare budget

is exact -- not a relaxation, not a bound -- and costs one sort per row. With `R` fixed for a
geometry, evaluating a candidate is **one matvec and one sort**, against one HotSpot invocation for
the simulate-and-guard-band approach. `_extreme_rows` does every cell row at once as a sort plus a
prefix sum.

Monotonicity is what makes the radius well defined and bisectable: `P(s) subset P(s')` for `s <= s'`,
because widening the span only relaxes each box bound while the total equality is unchanged. So the
supremum is non-decreasing in `s` and the feasible set of spans is an interval `[0, radius]`. The
bisection is therefore searching a monotone predicate, and that is asserted at run time rather than
assumed, because a non-monotone sweep would mean the polytope construction changed meaning.

## Fail-closed

A design is `CERTIFIED` at a span, `REFUTED` at it, or the run is `UNRESOLVED` -- never a fabricated
radius. A design whose NOMINAL point already exceeds the ceiling is `REFUTED_AT_NOMINAL`; one that
clears the nominal point but fails at the narrowest expressible envelope is `REFUTED_AT_MIN_SPAN`.
Both carry radius `0.0`, and both are refusals rather than small radii -- "tolerates no variation"
and "is infeasible" are different statements and collapsing them would report an infeasible design as
a merely fragile one.

NON-CLAIM diagnostic. Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/thermal_robustness_radius.py \\
        <trace.npz> <floorplan.flp> <workspace> <out.json> [model] [workers] [max_span]
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from CertiTherm.cell_certificate import certify_cells                        # noqa: E402
from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K     # noqa: E402
from CertiTherm.measurements import (                                        # noqa: E402
    activity_bounded_power_space, envelope_is_singleton,
)
from CertiTherm.paths import ROOT, TEMPLATE                                  # noqa: E402
from CertiTherm.tabular import read_rows as _rows                            # noqa: E402

from cell_certificate_run import _configure, cell_operator                    # noqa: E402
from routed_cell_certificate import MARGIN_K, _steady_power                   # noqa: E402

# The bisection stops when the bracket is this wide. It is a span, dimensionless, and 1e-4 is far
# below any span a design decision would distinguish.
RADIUS_TOLERANCE = 1e-4
# `activity_bounded_power_space` requires a strictly positive span -- a zero-width envelope is the
# nominal POINT, not a set, and it is evaluated directly as `max_j (R p_nom)_j + a_j` rather than
# through a degenerate polytope. So the sweep starts just above zero.
SPAN_FLOOR = 1e-3
# Spans the sweep reports outright, so the radius is never the only evidence and a reader can see
# the curve the bisection walked.
REPORTED_SPANS = (SPAN_FLOOR, 0.05, 0.15, 0.30, 0.60, 1.00, 1.50, 2.00)


def _nominal_peak(rows, ambient, placed) -> float:
    """`max_j T_j(p_nom)`: a point evaluation, which is what the whole field reports."""
    peak = float(np.max(np.asarray(rows) @ np.asarray(placed, dtype=float) + np.asarray(ambient)))
    if not math.isfinite(peak):
        raise SystemExit("the nominal peak is not finite; UNRESOLVED rather than a number")
    return peak


def _peak_at(rows, ambient, blocks, placed, span: float) -> float:
    """`max_j sup_{p in P(span)} T_j(p)`, exactly: greedy fill over a box with a total equality."""

    total = float(np.sum(placed))
    space = activity_bounded_power_space(blocks, placed, activity_span=span)
    cell = certify_cells(
        rows, ambient, ["tool_compatible"] * rows.shape[0], space, total,
        endpoint="tool_compatible", limit_k=THERMAL_LIMIT_K, margin_k=MARGIN_K,
        linearisation_k=MODEL_ERROR_LIMIT_K,
    )
    peak = float(cell.worst_case_max_cell_average_k)
    if not math.isfinite(peak):
        raise SystemExit(f"span {span}: the supremum is not finite; UNRESOLVED rather than a radius")
    return peak


def radius(rows, ambient, blocks, placed, ceiling: float, max_span: float):
    """`(radius, curve, status)` by bisection on a predicate proved monotone and checked to be."""

    curve = []
    for span in REPORTED_SPANS:
        if span > max_span:
            break
        curve.append({"span": span, "peak_k": _peak_at(rows, ambient, blocks, placed, span)})

    # Monotone by construction -- P(s) grows with s -- so a decreasing peak means the polytope
    # construction no longer means what this bisection assumes. Refuse rather than bisect.
    for before, after in zip(curve, curve[1:]):
        if after["peak_k"] < before["peak_k"] - 1e-9:
            raise SystemExit(
                f"the supremum fell from {before['peak_k']!r} at span {before['span']} to "
                f"{after['peak_k']!r} at span {after['span']}; P(s) is not nested and the radius "
                "is not defined by bisection"
            )

    if curve[0]["peak_k"] > ceiling:
        # Refused at the narrowest envelope this construction can express. That is a REFUSAL, not a
        # radius of zero: "tolerates no variation" and "is infeasible" are different statements and
        # collapsing them would report an infeasible design as a merely fragile one.
        return 0.0, curve, "REFUTED_AT_MIN_SPAN"
    if curve[-1]["peak_k"] <= ceiling and curve[-1]["span"] >= max_span:
        return float(max_span), curve, "CERTIFIED_TO_MAX_SPAN"

    low = max(c["span"] for c in curve if c["peak_k"] <= ceiling)
    high = min(c["span"] for c in curve if c["peak_k"] > ceiling)
    while high - low > RADIUS_TOLERANCE:
        mid = 0.5 * (low + high)
        if _peak_at(rows, ambient, blocks, placed, mid) <= ceiling:
            low = mid
        else:
            high = mid
    return low, curve, "RADIUS"


def main() -> None:
    trace_path, floorplan_src = Path(sys.argv[1]), Path(sys.argv[2])
    work, out_path = Path(sys.argv[3]), Path(sys.argv[4])
    model_id = sys.argv[5] if len(sys.argv) > 5 else "grid128-avg"
    workers = int(sys.argv[6]) if len(sys.argv) > 6 else 1
    max_span = float(sys.argv[7]) if len(sys.argv) > 7 else 2.0

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

    operator = out_path.with_suffix(".npz")
    if not operator.exists():
        started = time.monotonic()
        rows, ambient = cell_operator(config, floorplan, blocks, model_id, work, workers)
        build_s = time.monotonic() - started
        np.savez_compressed(
            operator, model_ids=np.asarray([model_id]), response_k_per_w=rows[None, :, :],
            ambient_k=ambient[None, :], block_ids=np.asarray(blocks),
            cell_endpoint=np.asarray(["tool_compatible"] * rows.shape[0]),
        )
    else:
        build_s = 0.0
    with np.load(operator, allow_pickle=False) as data:
        rows = np.asarray(data["response_k_per_w"], dtype=float)[0]
        ambient = np.asarray(data["ambient_k"], dtype=float)[0]
        if [str(b) for b in data["block_ids"]] != blocks:
            raise SystemExit("the saved operator resolves a different block list than this trace")

    ceiling = THERMAL_LIMIT_K - MARGIN_K - MODEL_ERROR_LIMIT_K
    nominal = _nominal_peak(rows, ambient, placed)

    # A SINGLETON ENVELOPE MAKES THE RADIUS MEANINGLESS, AND SILENTLY REASSURING.
    # `activity_bounded_power_space` caps each block at its content class's total, which collapses
    # the set to a point when every live block is alone in its class. The supremum then equals the
    # nominal peak at every span and the bisection reports `CERTIFIED_TO_MAX_SPAN` -- "tolerates
    # +-200 %" for a design that tolerates nothing. Refuse the radius and say why; the nominal
    # verdict is still reported because it is the only one the set supports.
    probe = activity_bounded_power_space(blocks, placed, activity_span=SPAN_FLOOR)
    if envelope_is_singleton(probe):
        payload = {
            "trace": trace_path.name, "floorplan": floorplan_src.name, "model": model_id,
            "blocks": len(blocks), "cells": int(rows.shape[0]),
            "horizon_s": horizon, "mean_power_w": float(np.sum(placed)),
            "ceiling_k": ceiling, "nominal_peak_k": nominal,
            "dist_to_ceiling_k": ceiling - nominal,
            "robustness_radius": None, "status": "SINGLETON_ENVELOPE",
            "curve": [], "operator_build_s": build_s, "radius_solve_s": 0.0,
            "reconciliation": receipts,
            "note": ("every live block is alone in its content class, so the class-total cap equals "
                     "the placed power and the total equality pins every coordinate. The envelope "
                     "admits exactly one power map; a radius over it would be a point evaluation "
                     "wearing an envelope's name."),
        }
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({k: v for k, v in payload.items() if k != "curve"}, indent=1,
                         sort_keys=True))
        return
    started = time.monotonic()
    value, curve, status = radius(rows, ambient, blocks, placed, ceiling, max_span)
    certify_s = time.monotonic() - started
    if nominal > ceiling:
        # The point evaluation the field reports already fails, so no envelope can succeed and the
        # radius is not the interesting quantity here.
        status = "REFUTED_AT_NOMINAL"

    payload = {
        "trace": trace_path.name, "floorplan": floorplan_src.name, "model": model_id,
        "blocks": len(blocks), "cells": int(rows.shape[0]),
        "horizon_s": horizon, "mean_power_w": float(np.sum(placed)),
        "ceiling_k": ceiling, "nominal_peak_k": nominal,
        "dist_to_ceiling_k": ceiling - nominal,
        "peak_at_min_span_k": curve[0]["peak_k"],
        "robustness_radius": value, "status": status, "curve": curve,
        "operator_build_s": build_s, "radius_solve_s": certify_s,
        "reconciliation": receipts,
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "curve"}, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
