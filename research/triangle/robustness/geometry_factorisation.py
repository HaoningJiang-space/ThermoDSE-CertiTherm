"""Which of the ten design parameters change the floorplan? Measured, because the guess was wrong.

## Why this exists

Leg 2 of the plan assumed the design space factors into geometry x power, so that one thermal
operator serves many candidates. Measured on the 61 archive designs with routed lowering, the reuse
rate keyed by floorplan text is **0.0 %** -- 61 designs, 61 distinct floorplans. That is the same
count `docs/DIRECTION_FIXED_GEOMETRY.md` already reports ("64 distinct floorplan geometries with zero
shared"), now confirmed on the DRAM-augmented floorplans rather than the legacy ones.

So caching per design is worthless, and the question is not whether the space factors but **along
which coordinates**. A search that moves only along parameters the floorplan does not depend on stays
inside one operator, and every candidate there costs 12 ms instead of a HotSpot solve
(`docs/CERTIFICATE_IN_THE_LOOP.md`). A search that moves the other parameters pays for a rebuild.

This measures the partition instead of asserting it: perturb one field at a time from a base design
and digest the resulting augmented floorplan.

## What a NULL result means, and it is a real outcome

If every parameter moves the floorplan, the design space does not factor, leg 2's operator cache
cannot exist, and the loop must either rebuild per candidate -- 30-90 s, which caps a search at
hundreds of candidates rather than millions -- or the search must be restricted to a genuinely fixed
geometry, which is what `DIRECTION_FIXED_GEOMETRY` already decided. Reporting that is the point; the
cache is not built on a hope.

NON-CLAIM diagnostic. One ThermoDSE evaluation per perturbation, about 7 s each.

Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/geometry_factorisation.py <outdir> [arch_id]
"""

from __future__ import annotations

import hashlib
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.experiments import ROOT, _rows                              # noqa: E402
from research.triangle.complete_trace_probe import capture_frozen_inputs     # noqa: E402

WORKLOAD_ID = "resnet50"
# The ten fields the bridge consumes, in the order ThermoDSE's own design vector uses.
FIELDS = ("chiplet_x", "chiplet_y", "cut_x", "cut_y", "interval",
          "mtxu_h", "mtxu_w", "ubuf", "nop_bw", "dram_bw")
# One perturbation per field, chosen to stay inside ThermoDSE's own admissible ranges: integers move
# by one step where that is meaningful, powers of two double, and the interval moves by 0.0003 m,
# which is the granularity the archive designs themselves vary it on.
PERTURBATIONS = {
    "chiplet_x": lambda v: str(int(v) + 1),
    "chiplet_y": lambda v: str(int(v) + 1),
    "cut_x": lambda v: str(int(v) + 1),
    "cut_y": lambda v: str(int(v) + 1),
    "interval": lambda v: f"{float(v) + 0.0003:.4f}",
    "mtxu_h": lambda v: str(int(v) * 2),
    "mtxu_w": lambda v: str(int(v) * 2),
    "ubuf": lambda v: str(int(v) * 2),
    "nop_bw": lambda v: str(int(v) * 2),
    "dram_bw": lambda v: str(int(v) * 2),
}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _floorplan_of(output: Path, arch: dict, tag: str):
    """`(digest, block count, mean power)` of the augmented floorplan this design induces."""
    frozen = capture_frozen_inputs(output / "work" / tag, WORKLOAD_ID,
                                   arch["architecture_id"], arch_row=arch)
    augmented = frozen["augmented"]
    return (_digest(augmented.text), len(augmented.block_ids),
            float(frozen["endpoint_energy_mj"]), float(frozen["endpoint_latency_ms"]))


def main() -> None:
    output = Path(sys.argv[1])
    base_id = sys.argv[2] if len(sys.argv) > 2 else "arch_a"
    output.mkdir(parents=True, exist_ok=True)

    base = next(row for row in _rows(ROOT / "experiments" / "architectures.tsv")
                if row["architecture_id"] == base_id)
    base_digest, base_blocks, base_energy, base_latency = _floorplan_of(output, dict(base), "base")
    print(f"base {base_id}: floorplan {base_digest}, {base_blocks} blocks, "
          f"{base_energy:.4f} mJ, {base_latency:.4f} ms", flush=True)

    rows = []
    for field in FIELDS:
        perturbed = dict(base)
        try:
            perturbed[field] = PERTURBATIONS[field](base[field])
        except (KeyError, ValueError) as error:
            raise SystemExit(f"{field}: cannot perturb {base.get(field)!r}: {error}")
        # The identifier must stay `base_id` because `capture_frozen_inputs` names its outputs from
        # it and refuses a mismatch; the perturbation is carried in the workdir tag instead.
        try:
            digest, blocks, energy, latency = _floorplan_of(output, perturbed, f"perturb_{field}")
        except Exception as error:                     # noqa: BLE001 - archived, not swallowed
            # A perturbation ThermoDSE rejects is not evidence that the field leaves geometry alone.
            # It is UNRESOLVED for that field and is reported as such rather than counted either way.
            rows.append({"field": field, "from": base[field], "to": perturbed[field],
                         "status": "UNRESOLVED",
                         "error": f"{type(error).__name__}: {error}",
                         "traceback": traceback.format_exc()[-800:]})
            print(f"  {field:<10} {base[field]} -> {perturbed[field]}: UNRESOLVED, "
                  f"{type(error).__name__}: {error}", flush=True)
            continue
        moved = digest != base_digest
        rows.append({"field": field, "from": base[field], "to": perturbed[field],
                     "status": "MOVES_GEOMETRY" if moved else "GEOMETRY_INVARIANT",
                     "floorplan_sha256_16": digest, "blocks": blocks,
                     "energy_mj": energy, "latency_ms": latency,
                     "energy_changed": abs(energy - base_energy) > 1e-9,
                     "latency_changed": abs(latency - base_latency) > 1e-9})
        print(f"  {field:<10} {base[field]:>9} -> {perturbed[field]:<9} "
              f"{'MOVES GEOMETRY' if moved else 'geometry invariant':<19} "
              f"blocks {blocks:>4}  E {energy:9.4f} mJ  T {latency:8.4f} ms", flush=True)

    invariant = [r["field"] for r in rows if r["status"] == "GEOMETRY_INVARIANT"]
    unresolved = [r["field"] for r in rows if r["status"] == "UNRESOLVED"]
    print()
    print(f"geometry-invariant: {invariant or 'NONE'}")
    print(f"unresolved:         {unresolved or 'none'}")
    if not invariant:
        print("NULL RESULT: no parameter leaves the floorplan fixed, so the design space does not "
              "factor into geometry x power and an operator cache keyed by geometry cannot amortise "
              "over a search that moves any of these fields.")

    report = output / f"geometry_factorisation_{base_id}.json"
    report.write_text(json.dumps(
        {"base": base_id, "workload": WORKLOAD_ID, "base_floorplan": base_digest,
         "base_blocks": base_blocks, "geometry_invariant": invariant,
         "unresolved": unresolved, "rows": rows}, indent=1, sort_keys=True), encoding="utf-8")
    print(f"-> {report}")


if __name__ == "__main__":
    main()
