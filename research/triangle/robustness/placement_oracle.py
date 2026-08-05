"""The placement oracle: reconcile the routed trace's PER-CORE distribution, not only its total.

## The gap this closes

`docs/THIRTEEN_REASSURING_NUMBERS.md` inventories the round's load-bearing quantities against their
independent checks and finds four with none. The most consequential is the routed lowering's
**placement**: `lower_routed_trace` reconciles the total source energy and the total route energy
against the monitor's counters to `< 1e-9` relative, and **nothing at all checks where the heat
lands**. Every verdict in the round is an input away from that.

## The second derivation, and why it is independent

`monitor.core_dict[nn][order, core, component]` carries per-order, per-core, per-component energy in
picojoules — the compute term, before any routing decision. The routed trace carries per-block power
over a horizon. The two are derived differently: the monitor's is what ThermoDSE's own accounting
recorded per core, and the trace's is what `lower_routed_trace` distributed onto the floorplan's
blocks. Agreement is therefore a check and not a restatement.

**Scope, stated because it is half the answer.** This pairs the **core** placement. The NoC, NoP and
DRAM terms are placed *by the route*, so the monitor has no per-block statement about them to compare
against; their totals are already reconciled and their distribution remains unchecked. Saying so is
the point — an oracle that silently covered only part of the quantity would be worse than none.

## Fail-closed

Refuses on: a block whose name does not resolve to a core index, a core present in one derivation and
absent from the other, and any per-core relative disagreement above the tolerance. The refusal names
the worst core and its magnitude, because "the placement does not reconcile" is not a diagnosis.

NON-CLAIM diagnostic. Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/placement_oracle.py <workload> <arch_id> <workdir>
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from research.triangle.order_trace_probe import monitor_snapshot              # noqa: E402
from research.triangle.robustness.routed_pipeline import lower_case           # noqa: E402

INDEXED = re.compile(r"^(?P<prefix>[A-Za-z]+)_(?P<index>\d+)$")
FABRIC = ("io", "dram", "blockX", "blockY", "blockXY", "eblk", "interposer")
RELATIVE_TOLERANCE = 1e-6


def _core_energy_from_trace(case) -> dict:
    """`{core index: joules}` from the routed trace, core blocks only."""
    per_core = defaultdict(float)
    for row, name in enumerate(case.blocks):
        if any(name.startswith(p) for p in FABRIC):
            continue
        match = INDEXED.match(name)
        if match is None:
            raise SystemExit(
                f"{name!r} is neither fabric nor an indexed core block; the core partition is "
                "undefined and no per-core comparison can be made"
            )
        per_core[int(match.group("index"))] += float(case.placed_w[row]) * case.horizon_s
    return dict(per_core)


def main() -> None:
    workload, arch_id, work = sys.argv[1], sys.argv[2], Path(sys.argv[3])

    case = lower_case(work, workload, arch_id)
    # A second evaluation, snapshotted -- ThermoDSE is deterministic for a fixed design, which is
    # what makes this legitimate, and the totals below would expose it if it were not.
    from CertiTherm.experiments import ROOT, _rows, _prepare_thermodse_sim, _thermodse_evaluator
    arch = next(r for r in _rows(ROOT / "experiments" / "architectures.tsv")
                if r["architecture_id"] == arch_id)
    workload_row = next(r for r in _rows(ROOT / "experiments" / "workloads.tsv")
                        if r["workload_id"] == workload)
    package = next(r for r in _rows(ROOT / "experiments" / "packages.tsv")
                   if r["package_id"] == "default")
    sim = _prepare_thermodse_sim(arch, workload_row, package, work / "monitor", allow_hotspot=True)
    evaluator = _thermodse_evaluator(arch, workload_row, sim, physical_nop=True)
    evaluator.generate_hardware()
    with monitor_snapshot(evaluator) as snapshot:
        evaluator.evaluate()

    # ONE NETWORK, NAMED. `next(iter(...))` silently picks an arbitrary entry when there is more
    # than one, and the aggregation semantics across networks are not specified here. Peer review,
    # round 2: refuse rather than choose.
    if len(snapshot["core_dict"]) != 1:
        raise SystemExit(
            f"the monitor carries {len(snapshot['core_dict'])} networks "
            f"({sorted(snapshot['core_dict'])}); this oracle compares ONE network's per-core energy "
            "and has no declared rule for combining several"
        )
    network = next(iter(snapshot["core_dict"]))
    core_pj = np.asarray(snapshot["core_dict"][network], dtype=float)   # (orders, cores, components)
    # THE AXIS INDEX IS ASSUMED TO BE THE CORE INDEX, AND THAT ASSUMPTION IS NOW STATED AND
    # BOUNDED. `core_dict` is `(orders, cores, components)` and the trace's core ids come from block
    # NAME suffixes; nothing in either object proves the two coordinate systems agree. What can be
    # checked cheaply is that they have the same extent and that the TOTALS match -- a permuted axis
    # would preserve the total and be invisible, so this is a necessary condition, not a sufficient
    # one, and the per-core comparison below is only meaningful under the correspondence.
    monitor = {k: float(v) * 1e-12 for k, v in enumerate(core_pj.sum(axis=(0, 2)))}

    # DETERMINISM IS CHECKED, NOT ASSUMED. The two derivations come from two separate ThermoDSE
    # evaluations, and the docstring's claim that determinism "is what makes this legitimate" was an
    # assertion. A second lowering of the same design must reproduce the first exactly, or the
    # comparison below is between two runs rather than between two derivations of one run.
    again = lower_case(work / "determinism", workload, arch_id)
    if not np.array_equal(np.asarray(again.placed_w), np.asarray(case.placed_w)):
        raise SystemExit(
            "two lowerings of the same design produced different power vectors: worst difference "
            f"{float(np.max(np.abs(again.placed_w - case.placed_w)))!r} W. The oracle compares two "
            "evaluations, so nondeterminism makes its agreement or disagreement meaningless."
        )

    trace = _core_energy_from_trace(case)
    missing = sorted(set(monitor) ^ set(trace))
    if missing:
        raise SystemExit(
            f"{len(missing)} core index/indices appear in one derivation and not the other, e.g. "
            f"{missing[:5]}; the two are not describing the same machine"
        )

    rows, worst, worst_core = [], 0.0, None
    for core in sorted(monitor):
        got, want = trace[core], monitor[core]
        rel = abs(got - want) / max(abs(want), 1e-30)
        rows.append({"core": core, "trace_j": got, "monitor_j": want, "relative": rel})
        if rel > worst:
            worst, worst_core = rel, core

    payload = {
        "workload": workload, "architecture": arch_id, "cores": len(rows),
        "monitor_total_j": sum(monitor.values()), "trace_core_total_j": sum(trace.values()),
        "worst_core": worst_core, "worst_relative": worst,
        "tolerance": RELATIVE_TOLERANCE,
        "reconciles": worst <= RELATIVE_TOLERANCE,
        "scope": ("core placement only. NoC, NoP and DRAM are placed BY THE ROUTE, so the monitor "
                  "has no per-block statement to compare against; their totals reconcile and their "
                  "distribution remains unchecked. The monitor's core AXIS INDEX is assumed to be "
                  "the trace's core NAME SUFFIX; a permuted axis preserves the total and would be "
                  "invisible to this check, so the per-core agreement is meaningful only under that "
                  "correspondence, which nothing here establishes."),
        "determinism_checked": True,
        "per_core": rows,
    }
    print(json.dumps({k: v for k, v in payload.items() if k != "per_core"}, indent=1,
                     sort_keys=True))
    (work / f"placement_oracle_{workload}_{arch_id}.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    if worst > RELATIVE_TOLERANCE:
        raise SystemExit(
            f"the per-core placement does not reconcile: worst at core {worst_core}, trace "
            f"{trace[worst_core]!r} J against monitor {monitor[worst_core]!r} J, relative "
            f"{worst:.6e} > {RELATIVE_TOLERANCE}. The routed lowering is putting compute heat "
            "somewhere the monitor did not record it."
        )


if __name__ == "__main__":
    main()
