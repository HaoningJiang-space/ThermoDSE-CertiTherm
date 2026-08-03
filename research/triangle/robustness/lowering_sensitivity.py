"""How much of the certified peak is the routed lowering's own modelling freedom? Sweep it.

Every verdict in this round is taken on the routed trace, and that lowering has three named degrees
of freedom (`docs/ADVERSARIAL_SELF_REVIEW.md` B3):

1. **the link endpoint split** -- how a link's dissipation divides between the two blocks it
   connects, fixed at 50/50. **Swept here.** The floorplan does not change, so the operator is a
   library HIT and every point costs one lowering plus a 12 ms certificate;
2. **`io_die_aspect_ratio`** -- labelled *"a sensitivity parameter, not a discovered fact"* at
   `routed_trace.py:117`. **Swept here.** It changes the floorplan, so each value costs an operator
   build;
3. **X-then-Y deterministic routing** versus ThermoDSE's own. **NOT swept**: `physical_nop.py` has
   one routing function and parameterising it is a change to the spatial fact source rather than to
   a coefficient. Named so the omission is visible.

The quantity reported is the certified peak `max_j sup_p T_j(p)` at the declared envelope, because
that is what every verdict reads. A spread comparable to the margins would mean the verdicts are
statements about the lowering rather than about the designs.

NON-CLAIM diagnostic. Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/lowering_sensitivity.py \\
        <workload> <arch_id> <workdir> [splits] [aspects]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cell_certificate import certify_cells                        # noqa: E402
from CertiTherm.experiments import ROOT, _rows                               # noqa: E402
from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K     # noqa: E402
from CertiTherm.measurements import activity_bounded_power_space             # noqa: E402
from CertiTherm.operator_library import OperatorLibrary                      # noqa: E402
from CertiTherm.paths import TEMPLATE                                        # noqa: E402
from CertiTherm.routed_trace import lower_routed_trace                       # noqa: E402
from research.triangle.complete_trace_probe import capture_frozen_inputs      # noqa: E402
from research.triangle.robustness.cell_certificate_run import (               # noqa: E402
    _configure, cell_operator,
)

MARGIN_K = 0.05
CEILING_K = THERMAL_LIMIT_K - MARGIN_K - MODEL_ERROR_LIMIT_K
SPAN = 0.30
DEFAULT_SPLITS = (0.25, 0.40, 0.50, 0.60, 0.75)
DEFAULT_ASPECTS = (0.5, 1.0, 2.0)


def main() -> None:
    workload, arch_id, work_root = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    splits = tuple(float(v) for v in sys.argv[4].split(",")) if len(sys.argv) > 4 else DEFAULT_SPLITS
    aspects = (tuple(float(v) for v in sys.argv[5].split(","))
               if len(sys.argv) > 5 else DEFAULT_ASPECTS)

    library = OperatorLibrary(work_root / "operators")
    packages = {row["package_id"]: row for row in _rows(ROOT / "experiments" / "packages.tsv")}
    rows = []

    for aspect in aspects:
        tag = f"aspect{aspect:g}"
        frozen = capture_frozen_inputs(work_root / "work" / tag, workload, arch_id,
                                       io_aspect_ratio=aspect)
        augmented = frozen["augmented"]
        blocks = [str(b) for b in augmented.block_ids]
        work = work_root / "work" / tag
        floorplan = work / "floorplan.flp"
        floorplan.write_text(augmented.text, encoding="utf-8")
        config = work / "package.config"
        _configure(TEMPLATE / "example.config", config, packages[library.package_id])
        operator, ambient, hit = library.get_or_build(
            augmented.text, blocks,
            lambda: cell_operator(config, floorplan, blocks, library.model_id, work, 8),
        )

        for split in splits:
            routed = lower_routed_trace(
                frozen["core"], floorplan=augmented, events=frozen["events"],
                compute_shape=frozen["shape"], chiplet_cuts=frozen["cuts"],
                noc_hop_cost_pj=frozen["noc_hop_cost_pj"],
                nop_hop_cost_pj=frozen["nop_hop_cost_pj"],
                batch_factor=frozen["batch_factor"], endpoint_split=split,
            )
            durations = np.asarray(routed.trace.durations_s, dtype=float)
            powers = np.asarray(routed.trace.powers_w, dtype=float)
            placed = (powers * durations[:, None]).sum(axis=0) / float(durations.sum())
            total = float(placed.sum())
            space = activity_bounded_power_space(blocks, placed, activity_span=SPAN)
            cell = certify_cells(
                operator, ambient, ["tool_compatible"] * operator.shape[0], space, total,
                endpoint="tool_compatible", limit_k=THERMAL_LIMIT_K, margin_k=MARGIN_K,
                linearisation_k=MODEL_ERROR_LIMIT_K,
            )
            peak = float(cell.worst_case_max_cell_average_k)
            nominal = float(np.max(operator @ placed + ambient))
            if not (math.isfinite(peak) and math.isfinite(nominal)):
                raise SystemExit(f"{tag} split {split}: a peak is not finite")
            # The total placed power must not depend on either parameter: both only move heat
            # around. If it does, the lowering is losing or inventing energy and the spread below
            # would be a conservation error read as a sensitivity.
            rows.append({"aspect": aspect, "split": split, "blocks": len(blocks),
                         "mean_power_w": total, "nominal_peak_k": nominal,
                         "certified_peak_k": peak, "slack_k": CEILING_K - peak,
                         "operator_hit": hit})
            print(f"  aspect {aspect:>4g}  split {split:>4.2f}  {len(blocks):>4d} blocks  "
                  f"{total:8.4f} W  nominal {nominal:8.3f}  certified {peak:8.3f}  "
                  f"{'CERT' if peak <= CEILING_K else 'REF '}  {'HIT' if hit else 'miss'}",
                  flush=True)

    powers = [r["mean_power_w"] for r in rows]
    if max(powers) - min(powers) > 1e-9 * max(powers):
        raise SystemExit(
            f"total placed power varies from {min(powers)!r} to {max(powers)!r} across the sweep; "
            "these parameters only move heat, so a varying total is a conservation defect and the "
            "spread below would be that defect rather than a sensitivity"
        )

    peaks = [r["certified_peak_k"] for r in rows]
    by_split = {s: [r["certified_peak_k"] for r in rows if r["split"] == s] for s in splits}
    by_aspect = {a: [r["certified_peak_k"] for r in rows if r["aspect"] == a] for a in aspects}
    summary = {
        "workload": workload, "architecture": arch_id, "span": SPAN, "ceiling_k": CEILING_K,
        "total_spread_k": max(peaks) - min(peaks),
        "spread_from_split_at_fixed_aspect_k": max(
            max(v) - min(v) for v in ({a: [r["certified_peak_k"] for r in rows if r["aspect"] == a]
                                       for a in aspects}).values()),
        "spread_from_aspect_at_fixed_split_k": max(
            max(v) - min(v) for v in ({s: [r["certified_peak_k"] for r in rows if r["split"] == s]
                                       for s in splits}).values()),
        "min_peak_k": min(peaks), "max_peak_k": max(peaks),
        "all_certify": all(r["certified_peak_k"] <= CEILING_K for r in rows),
        "any_certify": any(r["certified_peak_k"] <= CEILING_K for r in rows),
        "library": library.stats.as_dict(),
    }
    print()
    print(json.dumps(summary, indent=1, sort_keys=True))
    out = work_root / f"lowering_sensitivity_{workload}_{arch_id}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, sort_keys=True),
                   encoding="utf-8")
    print(f"-> {out}")
    if summary["any_certify"] != summary["all_certify"]:
        print("THE VERDICT FLIPS INSIDE THE LOWERING'S OWN FREEDOM. Any certificate on this trace is "
              "a statement about the lowering as much as about the design.")


if __name__ == "__main__":
    main()
