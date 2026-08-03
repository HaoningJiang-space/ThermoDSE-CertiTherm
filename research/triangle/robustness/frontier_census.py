"""Move the archive population to the thermal frontier by giving it back the heat it is missing.

## Why the existing census cannot answer anything

`docs/ARCHIVE_CENSUS_RESULT.md` certified 64 of 64 archive designs and said so against itself: the
**tightest design clears the limit by 5.40 K while the largest model-form band anywhere is 1.23 K**,
and nothing moves across a 24x sweep of the uncertainty parameter. A test that cannot fail measures
nothing, and the reason is upstream of the test -- the candidate set was selected on the archive's own
reported peak, a column the same document proves is not reproducible.

## Why this is expected to be different, and it is a measurement not a hope

The census ran on the LEGACY trace, which omits DRAM entirely and lumps NoP
(`docs/THERMODSE_ENDPOINT_AUDIT.md`). Giving the heat back moved the six development points up by
**1.3 to 4.7 K** at the cell endpoint (`docs/ROUTED_CERTIFICATE_AND_THE_BOUND_THAT_IS_NOT_ONE.md`),
against a census whose tightest slack is 5.40 K. The displacement is the same order as the margin, so
a population that could not fail becomes one that can -- or the routed displacement is smaller here
than on the development split, which is itself the answer and is reported as such.

`docs/G2_REPAIR_THE_WINDOW_IS_ONE_DIMENSIONAL.md` needs exactly this: candidates whose distance to
the limit lies in the separator band, over a population wider than the development split.

## What is reused rather than rebuilt

Every part. `archive_census.candidate_set` parses and hash-checks the four pinned archive files and
applies the declared selection; `archive_census.architecture_row` turns a design into the same
registry-shaped row the bridge consumes; `complete_trace_probe.capture_frozen_inputs` runs ThermoDSE
once and freezes what the lowering needs; `routed_trace.lower_routed_trace` places every source.
Nothing here re-derives a ThermoDSE quantity -- a second implementation cannot be its own oracle.

This driver only produces the routed trace and floorplan per design. The certificate is
`routed_cell_certificate.py`, unchanged, so the numbers stay comparable with the development split's.

NON-CLAIM diagnostic.

Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/frontier_census.py <outdir> [start] [stop] [workload]

**A different workload is a different population, not a re-reading of `archive-census-v1`.** That
protocol froze `resnet50`, and its result may not be quoted for any other. Running the same designs
under another workload is legitimate and is exactly what the low-power finding calls for -- the
archive's declared designs draw 5.5-18.5 W under `resnet50` against 28-57 W for the development
split -- but it must be reported under its own name.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.routed_trace import lower_routed_trace                       # noqa: E402
from research.triangle.complete_trace_probe import capture_frozen_inputs      # noqa: E402
from research.triangle.robustness.archive_census import (                     # noqa: E402
    DECLARED_COUNT, WORKLOAD_ID as PROTOCOL_WORKLOAD_ID, architecture_row, candidate_set,
)

RECONCILE_RTOL = 1e-9


def _emit(output: Path, arch_id: str, workload_id: str, frozen, routed) -> dict:
    """Write the trace and floorplan `routed_cell_certificate.py` consumes, receipts included."""

    augmented = frozen["augmented"]
    floorplan_out = output / f"complete_floorplan_{workload_id}_{arch_id}.flp"
    trace_out = output / f"complete_trace_{workload_id}_{arch_id}.npz"
    floorplan_out.write_text(augmented.text, encoding="utf-8")
    np.savez_compressed(
        trace_out,
        block_ids=np.asarray(augmented.block_ids),
        durations_s=routed.trace.durations_s,
        powers_w=routed.trace.powers_w,
        source_energy_j=np.asarray(routed.source_energy_j),
        route_energy_j=np.asarray(routed.route_energy_j),
        monitor_source_energy_j=np.asarray(routed.monitor_source_energy_j),
        monitor_route_energy_j=np.asarray(routed.monitor_route_energy_j),
    )

    # The lowering refuses internally when these disagree; re-checking here means a trace on disk
    # cannot be silently non-reconciling if that path is ever relaxed.
    for name, got, want in (
        ("source", routed.source_energy_j, routed.monitor_source_energy_j),
        ("route", routed.route_energy_j, routed.monitor_route_energy_j),
    ):
        if not np.isclose(float(got), float(want), rtol=RECONCILE_RTOL, atol=0.0):
            raise SystemExit(f"{arch_id}: {name} energy does not reconcile, {got!r} vs {want!r}")

    durations = np.asarray(routed.trace.durations_s, dtype=float)
    powers = np.asarray(routed.trace.powers_w, dtype=float)
    horizon = float(durations.sum())
    mean = (powers * durations[:, None]).sum(axis=0) / horizon
    return {
        "architecture_id": arch_id,
        "blocks": int(len(augmented.block_ids)),
        "phases": int(powers.shape[0]),
        "horizon_s": horizon,
        "mean_power_w": float(mean.sum()),
        "source_energy_j": float(routed.source_energy_j),
        "route_energy_j": float(routed.route_energy_j),
        "endpoint_latency_ms": float(frozen["endpoint_latency_ms"]),
        "endpoint_energy_mj": float(frozen["endpoint_energy_mj"]),
        "die_yield": float(frozen["die_yield"]),
        "trace": trace_out.name,
        "floorplan": floorplan_out.name,
    }


def main() -> None:
    output = Path(sys.argv[1])
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    stop = int(sys.argv[3]) if len(sys.argv) > 3 else DECLARED_COUNT
    workload_id = sys.argv[4] if len(sys.argv) > 4 else PROTOCOL_WORKLOAD_ID
    output.mkdir(parents=True, exist_ok=True)
    if workload_id != PROTOCOL_WORKLOAD_ID:
        print(f"NOTE: {workload_id!r} is NOT the workload `archive-census-v1` froze "
              f"({PROTOCOL_WORKLOAD_ID!r}). This is a different population and its result must not "
              "be quoted as that census's.", flush=True)

    distinct, pool, declared = candidate_set(DECLARED_COUNT)
    print(f"archive: {distinct} distinct designs, {pool} at or below the reported cutoff, "
          f"{len(declared)} declared; this shard {start}:{stop}", flush=True)

    rows, failures = [], []
    for index in range(start, min(stop, len(declared))):
        sys_info, record = declared[index]
        arch = architecture_row(index, sys_info, record)
        arch_id = arch["architecture_id"]
        target = output / f"complete_trace_{workload_id}_{arch_id}.npz"
        if target.exists():
            print(f"  {arch_id}: already emitted, skipping", flush=True)
            continue
        started = time.monotonic()
        try:
            frozen = capture_frozen_inputs(output / "work" / arch_id, workload_id, arch_id,
                                           arch_row=arch)
            routed = lower_routed_trace(
                frozen["core"], floorplan=frozen["augmented"], events=frozen["events"],
                compute_shape=frozen["shape"], chiplet_cuts=frozen["cuts"],
                noc_hop_cost_pj=frozen["noc_hop_cost_pj"],
                nop_hop_cost_pj=frozen["nop_hop_cost_pj"],
                batch_factor=frozen["batch_factor"],
            )
            row = _emit(output, arch_id, workload_id, frozen, routed)
        except Exception as error:                      # noqa: BLE001 - archived, not swallowed
            # FAIL CLOSED PER DESIGN, NOT PER RUN. A design ThermoDSE cannot evaluate is archived
            # with its traceback and excluded from the population; it is never given a fabricated
            # trace, and the census reports how many were excluded so a shrunken population cannot
            # pass as a complete one.
            failures.append({"architecture_id": arch_id, "sys_info": sys_info,
                             "error": f"{type(error).__name__}: {error}",
                             "traceback": traceback.format_exc()[-2000:]})
            print(f"  {arch_id}: EXCLUDED, {type(error).__name__}: {error}", flush=True)
            continue
        row["reported_peak_k"] = float(record["reported_peak_k"])
        row["reported_edyp"] = float(record["edyp"])
        row["sys_info"] = sys_info
        row["seconds"] = time.monotonic() - started
        rows.append(row)
        print(f"  {arch_id}: {row['blocks']} blocks, {row['phases']} phases, "
              f"{row['mean_power_w']:.3f} W, {row['seconds']:.0f} s", flush=True)

    report = output / f"frontier_census_{start}_{stop}.json"
    report.write_text(json.dumps(
        {"workload": workload_id, "declared": len(declared), "shard": [start, stop],
         "emitted": len(rows), "excluded": len(failures),
         "rows": rows, "failures": failures}, indent=1, sort_keys=True), encoding="utf-8")
    print(f"emitted {len(rows)}, excluded {len(failures)} -> {report}", flush=True)


if __name__ == "__main__":
    main()
