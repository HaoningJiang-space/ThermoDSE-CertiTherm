"""Compose the two levels: the architecture the certificate accepts, then the mapping it optimises.

`CERTIFIED_SEARCH_RESULT.md` found an architecture change that turns a refused design into a
certified one at `+8.77 %` EDYP. `CERTIFIED_MAPPING_AND_THE_UNIFICATION.md` found that remapping
recovers `0.02-0.52 K` at **no** area, energy or latency cost. The two levels are independent -- one
moves the geometry, the other moves only the power vector -- so their gains should add.

"Should" is not a measurement. This runs the composition end to end on one design and reports all
four corners, so the claim is a table rather than an argument:

    (ThermoDSE architecture, ThermoDSE mapping)   -- the incumbent
    (ThermoDSE architecture, certified mapping)   -- mapping level alone, free
    (certified architecture, ThermoDSE mapping)   -- architecture level alone, costs EDYP
    (certified architecture, certified mapping)   -- both

NON-CLAIM diagnostic. Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/composed_result.py \\
        <workload> <arch_id> <field=value,...> <workdir>
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.experiments import ROOT, _rows                               # noqa: E402
from CertiTherm.operator_library import OperatorLibrary                      # noqa: E402
from CertiTherm.paths import TEMPLATE                                        # noqa: E402
from CertiTherm.routed_trace import lower_routed_trace                       # noqa: E402
from research.triangle.complete_trace_probe import capture_frozen_inputs      # noqa: E402
from research.triangle.robustness.cell_certificate_run import (               # noqa: E402
    _configure, cell_operator,
)


def _emit(workload, arch_id, arch_row, work_root, library, tag):
    """`(trace_path, floorplan_path, operator_path, edyp)` for one design."""
    frozen = capture_frozen_inputs(work_root / "work" / tag, workload, arch_id, arch_row=arch_row)
    routed = lower_routed_trace(
        frozen["core"], floorplan=frozen["augmented"], events=frozen["events"],
        compute_shape=frozen["shape"], chiplet_cuts=frozen["cuts"],
        noc_hop_cost_pj=frozen["noc_hop_cost_pj"], nop_hop_cost_pj=frozen["nop_hop_cost_pj"],
        batch_factor=frozen["batch_factor"],
    )
    augmented = frozen["augmented"]
    blocks = [str(b) for b in augmented.block_ids]
    work = work_root / "work" / tag
    work.mkdir(parents=True, exist_ok=True)
    trace_path = work / "trace.npz"
    np.savez_compressed(
        trace_path, block_ids=np.asarray(blocks),
        durations_s=routed.trace.durations_s, powers_w=routed.trace.powers_w,
        source_energy_j=np.asarray(routed.source_energy_j),
        route_energy_j=np.asarray(routed.route_energy_j),
        monitor_source_energy_j=np.asarray(routed.monitor_source_energy_j),
        monitor_route_energy_j=np.asarray(routed.monitor_route_energy_j),
    )
    floorplan = work / "floorplan.flp"
    floorplan.write_text(augmented.text, encoding="utf-8")
    config = work / "package.config"
    packages = {row["package_id"]: row for row in _rows(ROOT / "experiments" / "packages.tsv")}
    _configure(TEMPLATE / "example.config", config, packages[library.package_id])
    rows, ambient, hit = library.get_or_build(
        augmented.text, blocks,
        lambda: cell_operator(config, floorplan, blocks, library.model_id, work, 10),
    )
    operator_path = work / "operator.npz"
    np.savez_compressed(
        operator_path, model_ids=np.asarray([library.model_id]),
        response_k_per_w=rows[None, :, :], ambient_k=ambient[None, :],
        block_ids=np.asarray(blocks),
    )
    edyp = (float(frozen["endpoint_energy_mj"]) * float(frozen["endpoint_latency_ms"])
            / float(frozen["die_yield"]))
    print(f"  {tag}: {len(blocks)} blocks, EDYP {edyp:.4f}, operator {'HIT' if hit else 'built'}",
          flush=True)
    return trace_path, floorplan, operator_path, edyp


def main() -> None:
    workload, arch_id, overrides, work_root = (sys.argv[1], sys.argv[2], sys.argv[3],
                                               Path(sys.argv[4]))
    work_root.mkdir(parents=True, exist_ok=True)
    library = OperatorLibrary(work_root / "operators")

    base = dict(next(row for row in _rows(ROOT / "experiments" / "architectures.tsv")
                     if row["architecture_id"] == arch_id))
    found = dict(base)
    for item in overrides.split(","):
        key, value = item.split("=")
        if key not in found:
            raise SystemExit(f"{key!r} is not an architecture field; have {sorted(found)}")
        found[key] = value
    if found == base:
        raise SystemExit("the override changes nothing; there is no composition to measure")

    corners = {}
    for name, row in (("thermodse_arch", base), ("certified_arch", found)):
        trace, _flp, operator, edyp = _emit(workload, arch_id, row, work_root, library, name)
        out = subprocess.run(
            [sys.executable, "research/triangle/robustness/certified_mapping.py",
             str(operator), str(trace), "3000"],
            capture_output=True, text=True, timeout=3600,
        )
        if out.returncode != 0:
            raise SystemExit(f"{name}: certified_mapping failed\n{out.stderr[-800:]}")
        text = out.stdout
        payload = json.loads(text[text.index("{"):])
        corners[name] = {"edyp": edyp, **payload}

    ceiling = corners["thermodse_arch"]["ceiling_k"]
    table = []
    for arch_name, arch_label in (("thermodse_arch", "ThermoDSE arch"),
                                  ("certified_arch", "certified arch")):
        c = corners[arch_name]
        for map_key, map_label in (("thermodse_mapping_certified_k", "ThermoDSE map"),
                                   ("best_mapping_certified_k", "certified map")):
            table.append({"architecture": arch_label, "mapping": map_label,
                          "edyp": c["edyp"], "certified_peak_k": c[map_key],
                          "slack_k": ceiling - c[map_key],
                          "verdict": "CERTIFIED" if c[map_key] <= ceiling else "REFUTED"})

    header = "%-16s %-14s %10s %12s %9s  %s" % (
        "architecture", "mapping", "EDYP", "certified", "slack", "verdict")
    print()
    print(header)
    print("-" * len(header))
    for r in table:
        print("%-16s %-14s %10.4f %12.4f %+9.4f  %s" % (
            r["architecture"], r["mapping"], r["edyp"], r["certified_peak_k"], r["slack_k"],
            r["verdict"]))

    base_peak = table[0]["certified_peak_k"]
    payload = {
        "workload": workload, "seed": arch_id, "overrides": overrides, "ceiling_k": ceiling,
        "table": table,
        "mapping_only_gain_k": base_peak - table[1]["certified_peak_k"],
        "architecture_only_gain_k": base_peak - table[2]["certified_peak_k"],
        "combined_gain_k": base_peak - table[3]["certified_peak_k"],
        "additivity_residual_k": (
            (base_peak - table[3]["certified_peak_k"])
            - ((base_peak - table[1]["certified_peak_k"])
               + (base_peak - table[2]["certified_peak_k"]))),
        "edyp_ratio": table[3]["edyp"] / table[0]["edyp"],
        "library": library.stats.as_dict(),
    }
    print()
    print(json.dumps({k: v for k, v in payload.items() if k != "table"}, indent=1, sort_keys=True))
    (work_root / f"composed_{workload}_{arch_id}.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
