"""Is the feasible-set disagreement an artefact of one envelope width? Re-certify every candidate.

`docs/THE_NOMINAL_RULE_ADMITS_WHAT_THE_ENVELOPE_REFUTES.md` compares the nominal rule against the
envelope rule at a single span, `0.30`. The obvious attack (`ADVERSARIAL_SELF_REVIEW.md` A3) is that
the span is a knob and the disagreement was tuned into existence by picking it.

The answer is a sweep, and it is cheap for the reason leg 1 exists: the certificate is a sort, so
re-certifying a candidate at a new span costs **12 ms**. What is not cheap is the operator -- and
every design here has already been evaluated once, so **the operator library should hit on all of
them**. That is the first run in this project where the library's hit rate is expected to be high,
and it is reported rather than assumed.

Only the power vector has to be recomputed, because the search stored peaks rather than power maps.
That is one ThermoDSE evaluation per design, ~7 s, and it is the honest cost of not having stored the
vector -- recorded here so a future run stores it.

## What the sweep can and cannot show

It shows how `|F_nominal| - |F_envelope|` and the two rules' optima move with the declared span. It
does **not** identify a "correct" span: a wider envelope is a weaker claim about the workload and a
stronger requirement on the design, and which to declare is an engineering decision. What a reader
gets is the whole curve, so the verdict at their own span is readable off it.

NON-CLAIM diagnostic. Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/envelope_span_sweep.py \\
        <certified_search_*.json> <workdir> [spans]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.frozen_limits import THERMAL_LIMIT_K                          # noqa: E402
from CertiTherm.operator_library import OperatorLibrary                       # noqa: E402
from research.triangle.robustness.routed_pipeline import (                     # noqa: E402
    CEILING_K, certified_peak, lower_case, nominal_peak, operator_for,
)

DEFAULT_SPANS = (0.05, 0.10, 0.20, 0.30, 0.50, 0.75, 1.00)


def main() -> None:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    work_root = Path(sys.argv[2])
    spans = tuple(float(v) for v in sys.argv[3].split(",")) if len(sys.argv) > 3 else DEFAULT_SPANS
    workload, seed_id = payload["workload"], payload["seed"]

    library = OperatorLibrary(work_root / "operators")
    rows = []
    for index, candidate in enumerate(payload["all"]):
        design = dict(candidate["design"])
        design["architecture_id"] = seed_id
        tag = f"cand{index:03d}"
        case = lower_case(work_root / "work" / tag, workload, seed_id, arch_row=design)
        operator, ambient, hit = operator_for(case, library, work_root / "work" / tag, workers=8)
        peaks = {span: certified_peak(operator, ambient, case, span) for span in spans}
        rows.append({"tag": tag, "design": candidate["design"], "edyp": candidate["edyp"],
                     "nominal_peak_k": nominal_peak(operator, ambient, case),
                     "peaks": peaks, "operator_hit": hit})
        print(f"  {tag}: EDYP {candidate['edyp']:8.4f} nominal {rows[-1]['nominal_peak_k']:8.3f} "
              f"{'HIT ' if hit else 'miss'} "
              + " ".join(f"{s}:{peaks[s]:.3f}" for s in spans), flush=True)

    print()
    header = "%-8s %10s %10s %10s %10s" % ("span", "n_nominal", "n_envelope", "EDYP_nom", "EDYP_env")
    print(header); print("-" * len(header))
    nominal_set = [r for r in rows if r["nominal_peak_k"] <= THERMAL_LIMIT_K]
    nominal_best = min(nominal_set, key=lambda r: r["edyp"]) if nominal_set else None
    summary = []
    for span in spans:
        envelope_set = [r for r in rows if r["peaks"][span] <= CEILING_K]
        envelope_best = min(envelope_set, key=lambda r: r["edyp"]) if envelope_set else None
        summary.append({
            "span": span, "n_nominal": len(nominal_set), "n_envelope": len(envelope_set),
            "edyp_nominal": nominal_best["edyp"] if nominal_best else None,
            "edyp_envelope": envelope_best["edyp"] if envelope_best else None,
            "same_choice": bool(nominal_best and envelope_best
                                and nominal_best["design"] == envelope_best["design"]),
            "admitted_but_refuted": sum(1 for r in nominal_set if r["peaks"][span] > CEILING_K),
        })
        print("%-8.2f %10d %10d %10s %10s" % (
            span, len(nominal_set), len(envelope_set),
            f"{nominal_best['edyp']:.4f}" if nominal_best else "none",
            f"{envelope_best['edyp']:.4f}" if envelope_best else "none"))

    out = Path(sys.argv[1]).with_name(f"span_sweep_{workload}_{seed_id}.json")
    out.write_text(json.dumps({"workload": workload, "seed": seed_id, "spans": list(spans),
                               "ceiling_k": CEILING_K, "nominal_limit_k": THERMAL_LIMIT_K,
                               "summary": summary, "rows": rows,
                               "library": library.stats.as_dict()}, indent=1, sort_keys=True),
                   encoding="utf-8")
    print(f"\nlibrary hits {library.stats.hits}/{library.stats.hits + library.stats.misses} "
          f"({100 * library.stats.hit_rate:.1f} %)  -> {out}")


if __name__ == "__main__":
    main()
