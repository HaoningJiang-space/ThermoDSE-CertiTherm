"""Certify the declared ThermoDSE archive candidate set. Protocol: `archive-census-v1`.

Everything this script does is fixed by `docs/ARCHIVE_CENSUS_PREREGISTRATION.md`, which was frozen
and committed before any archive design was run. This file implements that document and must not
introduce a choice the document does not make -- the candidate set, the selection rule, the
denominator, the reference, the uncertainty set, the tolerances and the pass thresholds all come
from there.

## Why this is a separate driver

`CertiTherm/experiments.py` reads `experiments/architectures.tsv`, which holds the three FROZEN
held-out splits. The archive is a different population, so it is run through the bridge directly and
**this script never writes to that registry**. Nothing here can open a held-out split, because it
never reads one.

## The three per-design stages

1. **capture** -- ThermoDSE partition/schedule/map, giving a floorplan and a placed power map.
2. **operators** -- HotSpot `grid512-avg` on GPU, the certificate's reference.
3. **model form** -- a DOLFINx FEM operator on GPU, giving the measured band the budget is
   re-anchored on.

A design that fails any stage is **UNRESOLVED and stays in the denominator**. That is not politeness:
dropping it would remove exactly the hard cases and inflate the certified fraction.

NON-CLAIM until the full declared set has been attempted; the JSON records how many were.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/archive_census.py <workdir> <out.json> \\
        [count] [shard] [shards]
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.experiments import ROOT, _capture, _rows

# Transcribed from `ChipletOrchestrationRegret/eval/k0_ranking_margin.py` (`SYS_INFO_RE`,
# `METRIC_RE`), the existing verified reader for this format. Provenance recorded rather than
# re-derived: an invented pattern in this session parsed ZERO rows while looking like it worked.
SYS_INFO_RE = re.compile(r"sys_info:(\[[^\]]*\])")
METRIC_RE = re.compile(
    r"area:\s*([0-9.eE+-]+),\s*peak temperature is\s*([0-9.eE+-]+)\s*K,"
    r"\s*Yield:\s*([0-9.eE+-]+),\s*EDYP:\s*([0-9.eE+-]+)"
)
ARCHIVE_GLOB = "ThermoDSE/tools/results_new/archs_348_300_*.txt"
# Fixed by the protocol, not by a flag: one workload and one package, declared in
# `docs/ARCHIVE_CENSUS_PREREGISTRATION.md` before the run.
WORKLOAD_ID = "resnet50"
PACKAGE_ID = "default"
REPORTED_PEAK_CUTOFF_K = 330.0
FIELDS = (
    "chiplet_x", "chiplet_y", "cut_x", "cut_y", "interval",
    "mtxu_h", "mtxu_w", "ubuf", "nop_bw", "dram_bw",
)


def candidate_set(count: int):
    """The declared set: reported peak <= 330 K, ascending EDYP, top `count`, ties by sys_info."""

    designs = {}
    for path in sorted(ROOT.glob(ARCHIVE_GLOB)):
        pending = None
        for line in path.read_text(errors="replace").splitlines():
            match = SYS_INFO_RE.search(line)
            if match:
                pending = match.group(1)
                continue
            if pending:
                metric = METRIC_RE.search(line)
                if metric:
                    area, peak, yld, edyp = (float(v) for v in metric.groups())
                    designs[pending] = {
                        "area_m2": area, "reported_peak_k": peak, "yield": yld, "edyp": edyp,
                    }
                    pending = None
    if not designs:
        raise SystemExit(
            f"no designs parsed from {ARCHIVE_GLOB}; the archive format changed and the census "
            "would silently certify an empty set"
        )
    pool = [
        (key, value) for key, value in designs.items()
        if value["reported_peak_k"] <= REPORTED_PEAK_CUTOFF_K
    ]
    pool.sort(key=lambda item: (item[1]["edyp"], item[0]))
    return len(designs), len(pool), pool[:count]


def _public(row: dict) -> dict:
    """The registry-shaped fields, without this script's private bookkeeping."""

    return {k: v for k, v in row.items() if not k.startswith("_")}


def architecture_row(index: int, sys_info: str, record: dict) -> dict:
    """One archive design as the same 10-field row the bridge already consumes.

    The bridge takes `[chiplet_x, chiplet_y, cut_x, cut_y, interval, mtxu_h, mtxu_w, ubuf, nop_bw,
    dram_bw]`, which is exactly what the archive stores, so no translation is invented here. The
    identifier is positional in the DECLARED ordering, which makes it a deterministic function of
    the four pinned files rather than of the order this script happens to iterate in.
    """

    values = [v.strip() for v in sys_info.strip("[]").split(",")]
    if len(values) != len(FIELDS):
        raise SystemExit(f"design {index} has {len(values)} parameters, expected {len(FIELDS)}")
    row = {"architecture_id": f"arxv{index:03d}", "split": "archive", "rank": str(index)}
    for name, value in zip(FIELDS, values):
        row[name] = value if name == "interval" else str(int(float(value)))
    row["_sys_info"] = sys_info
    row["_edyp_reported"] = record["edyp"]
    row["_reported_peak_k"] = record["reported_peak_k"]
    return row


def main() -> None:
    workdir = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 64
    shard = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    shards = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    plan_only = os.environ.get("CERTITHERM_CENSUS_PLAN") == "1"

    distinct, pool_size, chosen = candidate_set(count)
    if len(chosen) != count:
        raise SystemExit(
            f"the declared set asks for {count} designs and the pool holds {len(chosen)}; the "
            "protocol's denominator cannot be met and the census must not silently shrink it"
        )
    rows = [architecture_row(i, key, value) for i, (key, value) in enumerate(chosen)]
    workdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "protocol": "archive-census-v1",
        "archive_distinct_designs": distinct,
        "candidate_pool_reported_peak_at_or_below_330k": pool_size,
        "declared_count": count,
        "denominator": count,
        "shard": shard, "shards": shards,
        # `dict | dict` is 3.9+, and the pinned interpreter is python3.8. Written out rather
        # than relying on a version the bootstrap does not promise.
        "designs": [dict(_public(row), sys_info=row["_sys_info"],
                         edyp_reported=row["_edyp_reported"],
                         reported_peak_k=row["_reported_peak_k"]) for row in rows],
    }
    (workdir / "candidate_set.json").write_text(json.dumps(manifest, indent=1))
    mine = [row for index, row in enumerate(rows) if index % shards == shard]
    print(
        "archive %d distinct, pool %d at or below %.1f K, declared %d, this shard %d"
        % (distinct, pool_size, REPORTED_PEAK_CUTOFF_K, count, len(mine)),
        flush=True,
    )
    if plan_only:
        for row in mine:
            print(
                "  %s  EDYP %8.3f  reported peak %6.1f K  %s"
                % (row["architecture_id"], row["_edyp_reported"], row["_reported_peak_k"],
                   row["_sys_info"]),
                flush=True,
            )
        out_path.write_text(json.dumps(manifest, indent=1))
        return

    workloads = {row["workload_id"]: row for row in _rows(ROOT / "experiments" / "workloads.tsv")}
    packages = {row["package_id"]: row for row in _rows(ROOT / "experiments" / "packages.tsv")}
    workload, package = workloads[WORKLOAD_ID], packages[PACKAGE_ID]

    results = []
    for row in mine:
        arch_id = row["architecture_id"]
        arch = _public(row)
        record = {
            "architecture_id": arch_id, "sys_info": row["_sys_info"],
            "edyp_reported": row["_edyp_reported"], "reported_peak_k": row["_reported_peak_k"],
        }
        try:
            capture = _capture(arch, workload, package, workdir)
            record["capture"] = str(capture)
            record["status"] = "CAPTURED"
        except Exception as error:  # noqa: BLE001 -- any failure is UNRESOLVED, not a dropped row
            # UNRESOLVED, AND IT STAYS IN THE DENOMINATOR. Dropping a design whose capture failed
            # would remove exactly the hard cases and inflate the certified fraction; the protocol
            # fixes the denominator at the declared count for this reason.
            record["status"] = "UNRESOLVED"
            record["error"] = f"{type(error).__name__}: {error}"[:400]
        print(
            "  %-8s %-11s EDYP %8.3f  reported peak %6.1f K%s"
            % (arch_id, record["status"], record["edyp_reported"], record["reported_peak_k"],
               "  " + record.get("error", "")),
            flush=True,
        )
        results.append(record)
        manifest["results"] = results
        out_path.write_text(json.dumps(manifest, indent=1))

    captured = sum(1 for r in results if r["status"] == "CAPTURED")
    print(
        "\ncaptures: %d of %d in this shard; %d UNRESOLVED and retained in the denominator"
        % (captured, len(mine), len(mine) - captured),
        flush=True,
    )


if __name__ == "__main__":
    main()
