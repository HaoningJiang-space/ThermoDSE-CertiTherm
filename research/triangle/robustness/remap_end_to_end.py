"""Is the mapping actually free? Apply the permutation for real and re-route everything.

## The claim-blocking objection this answers

Peer review (Codex, rounds 1 and 2, items #2/#18) held that `certified_mapping.py` permutes **core
power profiles under fixed fabric power and fixed performance**, while a physically executed task
remapping would also change communication paths, link and router power, congestion, latency and
EDYP. So "the mapping level is free -- no area, no energy, no latency" is established for the
permutation as modelled and **not** for a remapping, and the unchecked NoC/NoP/DRAM distribution is
exactly the part most likely to move. It was ruled claim-blocking for any statement about realisable
benefit.

## Why it is reachable without touching the pinned submodule

`ThermoDSE/core/schedule.py:30` builds `self.idx2coreidx_map` once at init and caches it: logical
task index -> physical core coordinate. **Permuting that list is the remapping.** Everything
downstream -- the round-based schedule, the NoC/NoP hop counts, the route events this project
captures -- reads through it, so a permuted map produces a genuinely re-routed evaluation rather
than a relabelled one. It is patched in place for the duration of one evaluation, the way
`capture_route_events` and `install_physical_nop` already do, and restored afterwards.

## What is compared

For the identity map and for a supplied permutation, both lowered through the same pipeline:

* **fabric power** (`io_*`, `blockX/Y_*`, `dram_*`) -- the quantity the permutation-only model holds
  fixed. If it moves, "free" is false and by how much;
* **latency, energy, EDYP** -- the other things held fixed;
* **nominal and certified peak** -- what the mapping result reports.

A permutation that leaves all of these unchanged would vindicate the abstraction. One that does not
bounds the error in the published mapping numbers.

NON-CLAIM diagnostic. Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/remap_end_to_end.py <workload> <arch> <perm-json> <work>
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.operator_library import OperatorLibrary                       # noqa: E402
from research.triangle.robustness.routed_pipeline import (                     # noqa: E402
    CEILING_K, certified_peak, lower_case, nominal_peak, operator_for,
)

SPAN = 0.30
FABRIC = ("io", "dram", "blockX", "blockY", "blockXY")


@contextmanager
def permuted_core_map(permutation):
    """Patch `Schedule.__init__` so the cached logical->physical map is permuted, then restore.

    The permutation is applied to the CACHE the scheduler builds, not to the geometry: core `k`
    keeps its position and receives the work that logical index `permutation[k]` would have had.
    Nothing on disk is modified and the original method is restored on exit.
    """
    from core.schedule import Schedule  # type: ignore

    original = Schedule.__init__

    def patched(self, *args, **kwargs):
        original(self, *args, **kwargs)
        cached = list(self.idx2coreidx_map)
        if len(permutation) != len(cached):
            raise SystemExit(
                f"the permutation has {len(permutation)} entries and the scheduler cached "
                f"{len(cached)} cores; a permutation of a different length is not a remapping"
            )
        if sorted(permutation) != list(range(len(cached))):
            raise SystemExit("the permutation is not a permutation of 0..n-1")
        self.idx2coreidx_map = [cached[permutation[k]] for k in range(len(cached))]

    Schedule.__init__ = patched
    try:
        yield
    finally:
        Schedule.__init__ = original


def _split(case):
    """`(fabric_w, core_w)` from a lowered case."""
    fabric = sum(float(case.placed_w[i]) for i, b in enumerate(case.blocks)
                 if any(b.startswith(p) for p in FABRIC))
    return fabric, case.total_w - fabric


def main() -> None:
    workload, arch_id = sys.argv[1], sys.argv[2]
    permutation = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))["permutation"]
    work = Path(sys.argv[4])
    library = OperatorLibrary(work / "operators")

    rows = {}
    for name, perm in (("identity", None), ("remapped", permutation)):
        target = work / name
        if perm is None:
            case = lower_case(target, workload, arch_id)
        else:
            with permuted_core_map(perm):
                case = lower_case(target, workload, arch_id)
        operator, ambient, _hit = operator_for(case, library, target, workers=10)
        fabric, core = _split(case)
        rows[name] = {
            "total_w": case.total_w, "fabric_w": fabric, "core_w": core,
            "latency_ms": case.latency_ms, "energy_mj": case.energy_mj,
            "die_yield": case.die_yield, "edyp": case.edyp,
            "nominal_peak_k": nominal_peak(operator, ambient, case),
            "certified_peak_k": certified_peak(operator, ambient, case, SPAN),
            "blocks": len(case.blocks),
        }
        print(f"  {name:9s} fabric {fabric:8.4f} W  core {core:8.4f} W  EDYP {case.edyp:9.4f}  "
              f"nominal {rows[name]['nominal_peak_k']:8.3f}  certified "
              f"{rows[name]['certified_peak_k']:8.3f}", flush=True)

    a, b = rows["identity"], rows["remapped"]
    delta = {k: b[k] - a[k] for k in a if isinstance(a[k], float)}
    payload = {
        "workload": workload, "architecture": arch_id, "span": SPAN, "ceiling_k": CEILING_K,
        "identity": a, "remapped": b, "delta": delta,
        "fabric_power_moved": abs(delta["fabric_w"]) > 1e-9,
        "edyp_moved": abs(delta["edyp"]) > 1e-9,
        "verdict": ("the permutation-only abstraction is EXACT for this pair"
                    if abs(delta["fabric_w"]) <= 1e-9 and abs(delta["edyp"]) <= 1e-9
                    else "the abstraction is NOT exact: a real remapping moves fabric power "
                         "and/or EDYP, so the published mapping gain is not a realisable-benefit "
                         "number"),
    }
    print()
    print(json.dumps(payload, indent=1, sort_keys=True))
    (work / f"remap_end_to_end_{workload}_{arch_id}.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
