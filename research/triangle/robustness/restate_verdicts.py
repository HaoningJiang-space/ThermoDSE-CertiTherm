"""Restate every verdict of this round as model-relative, with the solver gap beside it.

`CertiTherm/model_relative_verdict.py` makes the correct form *possible*; this makes it the form the
round's own results are actually written in, which is the difference between a type and a practice.

For each case it emits, in one place:

* the verdict **with respect to** the HotSpot model that produced it, naming the operator digest;
* the **measured** disagreement against the independent FEM reference, on the cases it was measured
  on and named as such;
* and, separately and under its own name, what the verdict becomes **if that disagreement were
  treated as a bound** — which is the pair-model statement, not either solver's.

The third is what folding the band in amounts to. It is reported because a reader has to be able to
see it, and it is kept in a different column because it is a different claim.

NON-CLAIM diagnostic; pure post-processing of evidence already on disk.

Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/restate_verdicts.py <out.json> <band.json> ...
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.digest import sha256_file                                    # noqa: E402
from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K     # noqa: E402
from CertiTherm.model_relative_verdict import (                               # noqa: E402
    CrossModelGap, ModelRelativeVerdict, ThermalModel,
)

MARGIN_K = 0.05
CEILING_K = THERMAL_LIMIT_K - MARGIN_K - MODEL_ERROR_LIMIT_K


def main() -> None:
    out_path = Path(sys.argv[1])
    band_paths = [Path(p) for p in sys.argv[2:]]
    if not band_paths:
        raise SystemExit("no band files given; there is nothing to restate")

    rows = []
    for band_path in band_paths:
        band = json.loads(band_path.read_text(encoding="utf-8"))
        hotspot_operator = band_path.parent.parent / "certicheck" / "cellcert"
        # The digest is of the operator the verdict actually read. If it is not on this host the
        # restatement REFUSES rather than inventing an identifier -- a verdict whose model cannot be
        # re-derived is not attributable, which is the whole point of carrying the model.
        candidates = [p for p in (band_path.parent / band["fem_operator"],) if p.exists()]
        if not candidates:
            raise SystemExit(f"{band['fem_operator']} is not beside {band_path}; cannot digest it")
        fem_digest = sha256_file(candidates[0])
        hs_name = band["hotspot_operator"]
        hs_candidates = [p for p in Path(hotspot_operator).glob(hs_name)] if \
            Path(hotspot_operator).exists() else []
        hs_digest = sha256_file(hs_candidates[0]) if hs_candidates else ""
        if not hs_digest:
            raise SystemExit(
                f"the HotSpot operator {hs_name!r} was not found under {hotspot_operator}; the "
                "verdict's own model cannot be digested and the restatement refuses"
            )

        hotspot = ThermalModel(solver="hotspot", model_id="grid128-avg", package_id="default",
                               endpoint="tool_compatible", operator_sha256=hs_digest)
        fem = ThermalModel(solver="dolfinx", model_id="p1-cell128", package_id="default",
                           endpoint="tool_compatible", operator_sha256=fem_digest)
        case = band["capture"].replace(".npz", "")
        peak = float(band["hotspot_certified_peak_k"])
        gap = CrossModelGap(
            reference=fem,
            delta_certified_k=float(band["delta_certified_k"]),
            row_wise_band_k=float(band["e_total_k"]),
            tight_bound_k=float(band["effective_band_k"]),
            measured_on=(case,),
        )
        verdict = ModelRelativeVerdict(
            model=hotspot,
            status="CERTIFIED" if peak <= CEILING_K else "REFUTED",
            certified_peak_k=peak, ceiling_k=CEILING_K, case=case, gaps=(gap,),
        )
        restated = verdict.verdict_if_gap_were_a_bound("dolfinx")
        rows.append({"verdict": verdict.as_dict(), "if_gap_were_a_bound": restated.as_dict()})
        print(verdict.sentence())
        print(f"    if that gap were a bound: {restated.status} with respect to "
              f"{restated.model.solver}, slack {restated.slack_k:+.4f} K")

    changed = sum(1 for r in rows
                  if r["verdict"]["status"] != r["if_gap_were_a_bound"]["status"])
    print()
    print(f"{len(rows)} cases; the status changes on {changed} of them when the measured solver "
          "disagreement is treated as a bound instead of reported beside the verdict.")
    out_path.write_text(json.dumps(
        {"ceiling_k": CEILING_K, "cases": len(rows), "status_changes_under_bound": changed,
         "rows": rows,
         "note": ("The verdict column is with respect to the named HotSpot model. The gap column is "
                  "a MEASUREMENT against an independent solver on the named cases, not a bound on "
                  "reality: neither model is ground truth. The third column is the different, "
                  "pair-model claim that folding the gap in would make.")},
        indent=1, sort_keys=True), encoding="utf-8")
    print(f"-> {out_path}")


if __name__ == "__main__":
    main()
