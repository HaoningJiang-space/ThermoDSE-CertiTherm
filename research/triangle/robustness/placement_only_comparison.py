"""Is the assumed-central nuisance placement an UPPER bound on the routed one? Same geometry, matvec.

`PER_CASE_Q_WITHDRAWS_THE_PLACEMENT_FREE_REFUSAL.md` compares the assumed-central construction
(`legacy sup_p peak + NET uplift`) against the routed certificate and finds the assumed value BELOW
the routed one on two cases. That comparison is not clean: the routed run uses the DRAM-augmented
floorplan, so it changes the geometry as well as the placement, and the two effects are confounded.

This isolates the placement. Both vectors are evaluated **against the same cell operator, built on
the same augmented floorplan**, and both carry **exactly the same total power**, so the only
difference is where the non-core heat sits:

* `routed`   -- the trace's own duration-weighted mean, i.e. every source where its route puts it;
* `assumed`  -- the same total, with all non-core power lifted off its blocks and redistributed
                area-weighted over the sys-area blocks, which is what `split_missing_heat.py` and
                `central_share_uplift.py` do. Two variants: excluding the four `eblk*` frame strips
                (what `central_share_uplift` does) and including them at their area share (what
                `split_missing_heat`'s `frame_fraction` does).

The quantity compared is the nominal peak cell average, `max_j (R q)_j + a_j`, which needs no
polytope: a polytope over one placement and a polytope over another are not the same set, so
comparing their suprema would reintroduce the confound this script exists to remove.

NON-CLAIM diagnostic. Pure numpy against operators already built; no HotSpot, no GPU, seconds.

Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/placement_only_comparison.py <operator.npz> ...
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

FRAME_PREFIX = "eblk"


def _family(block: str) -> str:
    if block.startswith("dram"):
        return "dram"
    if block.startswith(FRAME_PREFIX):
        return "frame"
    if block.startswith("io_"):
        return "noc"
    if block.startswith("block"):
        return "nop"
    return "core"


def _areas(floorplan_text: str, blocks):
    area = {}
    for line in floorplan_text.splitlines():
        parts = line.split()
        if len(parts) >= 5:
            area[parts[0]] = float(parts[1]) * float(parts[2])
    missing = [b for b in blocks if b not in area]
    if missing:
        raise SystemExit(f"{len(missing)} blocks name no floorplan unit, e.g. {missing[:3]}")
    return np.asarray([area[b] for b in blocks], dtype=float)


def _redistribute(power, families, areas, *, include_frame: bool):
    """Lift every non-core watt off its block and spread it area-weighted over the sys area."""
    core = families == "core"
    support = ~(families == "dram")
    if not include_frame:
        support = support & (families != "frame")
    if not support.any() or areas[support].sum() <= 0.0:
        raise SystemExit("empty redistribution support")
    moved = float(power[~core].sum())
    out = np.where(core, power, 0.0)
    weight = np.where(support, areas, 0.0)
    return out + moved * weight / weight.sum()


def main() -> None:
    rows = []
    for operator_path in (Path(p) for p in sys.argv[1:]):
        result = operator_path.with_suffix(".json")
        meta = json.loads(result.read_text(encoding="utf-8"))
        trace = next(operator_path.parent.parent.rglob(meta["trace"]), None)
        floorplan = next(operator_path.parent.parent.rglob(meta["floorplan"]), None)
        if trace is None or floorplan is None:
            raise SystemExit(f"{operator_path}: cannot locate {meta['trace']} / {meta['floorplan']}")

        with np.load(operator_path, allow_pickle=False) as data:
            response = np.asarray(data["response_k_per_w"], dtype=float)[0]
            ambient = np.asarray(data["ambient_k"], dtype=float)[0]
            blocks = [str(b) for b in data["block_ids"]]
        with np.load(trace, allow_pickle=False) as data:
            if [str(b) for b in data["block_ids"]] != blocks:
                raise SystemExit(f"{operator_path}: trace and operator disagree on the block list")
            powers = np.asarray(data["powers_w"], dtype=float)
            durations = np.asarray(data["durations_s"], dtype=float)
        routed = (powers * durations[:, None]).sum(axis=0) / durations.sum()

        families = np.asarray([_family(b) for b in blocks])
        areas = _areas(floorplan.read_text(encoding="utf-8"), blocks)
        variants = {
            "routed": routed,
            "assumed_no_frame": _redistribute(routed, families, areas, include_frame=False),
            "assumed_with_frame": _redistribute(routed, families, areas, include_frame=True),
        }

        peaks = {}
        for name, q in variants.items():
            # Same total to machine precision, or the comparison is between two different problems.
            if not math.isclose(float(q.sum()), float(routed.sum()), rel_tol=1e-12, abs_tol=0.0):
                raise SystemExit(f"{name}: total {q.sum()!r} != routed {routed.sum()!r}")
            if not np.all(np.isfinite(q)) or np.any(q < 0.0):
                raise SystemExit(f"{name}: non-finite or negative power")
            peaks[name] = float(np.max(response @ q + ambient))

        rows.append({
            "case": operator_path.stem, "blocks": len(blocks),
            "total_w": float(routed.sum()), **peaks,
            "assumed_minus_routed_no_frame": peaks["assumed_no_frame"] - peaks["routed"],
            "assumed_minus_routed_with_frame": peaks["assumed_with_frame"] - peaks["routed"],
        })

    header = "%-24s %6s %8s %10s %10s %10s %9s %9s" % (
        "case", "blocks", "total W", "routed", "assumed", "asm+frame", "d(asm)", "d(+frame)")
    print(header)
    print("-" * len(header))
    for r in rows:
        print("%-24s %6d %8.3f %10.4f %10.4f %10.4f %+9.4f %+9.4f%s" % (
            r["case"], r["blocks"], r["total_w"], r["routed"], r["assumed_no_frame"],
            r["assumed_with_frame"], r["assumed_minus_routed_no_frame"],
            r["assumed_minus_routed_with_frame"],
            "" if r["assumed_minus_routed_no_frame"] >= 0 else "   <-- NOT an upper bound"))
    print()
    print(json.dumps(rows, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
