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
import sys
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.operator_library import OperatorLibrary                      # noqa: E402
from research.triangle.robustness.routed_pipeline import (                    # noqa: E402
    CEILING_K, certified_peak, lower_case, nominal_peak, operator_for,
)

SPAN = 0.30
DEFAULT_SPLITS = (0.25, 0.40, 0.50, 0.60, 0.75)
DEFAULT_ASPECTS = (0.5, 1.0, 2.0)


def _spread(rows, key):
    """Widest certified-peak range at a FIXED value of the other parameter."""
    groups = {}
    for row in rows:
        groups.setdefault(row[key], []).append(row["certified_peak_k"])
    return max(max(v) - min(v) for v in groups.values())


def main() -> None:
    workload, arch_id, work_root = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    splits = tuple(float(v) for v in sys.argv[4].split(",")) if len(sys.argv) > 4 else DEFAULT_SPLITS
    aspects = (tuple(float(v) for v in sys.argv[5].split(","))
               if len(sys.argv) > 5 else DEFAULT_ASPECTS)

    library = OperatorLibrary(work_root / "operators")
    rows = []
    for aspect in aspects:
        tag = f"aspect{aspect:g}"
        # The operator depends only on the floorplan, which only the ASPECT moves; the split is a
        # matvec on it. So the operator is fetched once per aspect and every split reuses it.
        geometry = lower_case(work_root / "work" / tag, workload, arch_id, io_aspect_ratio=aspect)
        operator, ambient, hit = operator_for(geometry, library, work_root / "work" / tag,
                                              workers=8)
        for split in splits:
            case = lower_case(work_root / "work" / tag, workload, arch_id,
                              io_aspect_ratio=aspect, endpoint_split=split)
            if case.blocks != geometry.blocks:
                raise SystemExit("the endpoint split moved the floorplan; it is a placement "
                                 "parameter and must not")
            peak = certified_peak(operator, ambient, case, SPAN)
            rows.append({"aspect": aspect, "split": split, "blocks": len(case.blocks),
                         "mean_power_w": case.total_w,
                         "nominal_peak_k": nominal_peak(operator, ambient, case),
                         "certified_peak_k": peak, "slack_k": CEILING_K - peak,
                         "operator_hit": hit})
            print(f"  aspect {aspect:>4g}  split {split:>4.2f}  {len(case.blocks):>4d} blocks  "
                  f"{case.total_w:8.4f} W  nominal {rows[-1]['nominal_peak_k']:8.3f}  "
                  f"certified {peak:8.3f}  {'CERT' if peak <= CEILING_K else 'REF '}  "
                  f"{'HIT' if hit else 'miss'}", flush=True)

    powers = [r["mean_power_w"] for r in rows]
    if max(powers) - min(powers) > 1e-9 * max(powers):
        raise SystemExit(
            f"total placed power varies from {min(powers)!r} to {max(powers)!r} across the sweep; "
            "these parameters only move heat, so a varying total is a conservation defect and the "
            "spread below would be that defect rather than a sensitivity"
        )

    peaks = [r["certified_peak_k"] for r in rows]
    summary = {
        "workload": workload, "architecture": arch_id, "span": SPAN, "ceiling_k": CEILING_K,
        "total_spread_k": max(peaks) - min(peaks),
        "spread_from_split_at_fixed_aspect_k": _spread(rows, "aspect"),
        "spread_from_aspect_at_fixed_split_k": _spread(rows, "split"),
        "min_peak_k": min(peaks), "max_peak_k": max(peaks),
        "all_certify": all(p <= CEILING_K for p in peaks),
        "any_certify": any(p <= CEILING_K for p in peaks),
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
