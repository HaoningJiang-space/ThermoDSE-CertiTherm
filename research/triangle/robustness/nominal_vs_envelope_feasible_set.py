"""The two feasible sets, compared exactly: a nominal peak against an envelope certificate.

## The attack this answers, which is the strongest one against the search result

`docs/CERTIFIED_SEARCH_RESULT.md` reports a certificate-constrained search reaching a feasible design
at `+8.77 %` EDYP from a baseline the certificate refuses. The obvious reply is that the baseline was
simply tuned against the wrong limit -- ThermoDSE's own cap is **348 K**, documented as unsupported,
while this study's is **330 K** -- so a fair comparison would re-run ThermoDSE's search at 330 K.

**That comparison does not need its optimiser, and running it would be weaker rather than stronger.**
ThermoDSE's thermal feasibility test is `evaluate_thermal()`, a single **nominal** HotSpot peak,
entering `scbo_search.py` as the hard SCBO constraint `c2 = peak_temp - max_temp <= 0` (plus a
`+0.05 * (maxT - peak)` coolness bonus in the objective). So its feasible set at any cap `L` is

    F_nominal(L) = { design : nominal peak <= L }

and ours is

    F_envelope   = { design : sup over the activity envelope <= L - margin - error }

Both are **deterministic functions of numbers this repository already measured for every candidate**.
Comparing the sets directly is exact; re-running a stochastic optimiser would answer the same question
with sampling noise on top, and would invite "your BO run was unlucky" as a reply.

So this script builds both sets over the SAME candidate list, reports each rule's own optimum, and
lists every design the two rules disagree about. What it can conclude is a statement about the
**rule**, not about the optimiser: whether a feasibility test built on a nominal peak admits designs
that are infeasible over the envelope.

## Fail-closed

A candidate with a non-finite peak on either side is `UNRESOLVED` and is excluded from both sets, with
the count reported. It is never assumed feasible for one rule and infeasible for the other.

NON-CLAIM diagnostic; pure post-processing, seconds, no solver.

Usage (repo root):
    .venv/bin/python research/triangle/robustness/nominal_vs_envelope_feasible_set.py \\
        <certified_search_*.json> [more.json ...] [--limit 330.0]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


def _rule_optimum(rows, key, threshold):
    """`(feasible, optimum)` under `row[key] <= threshold`, minimising EDYP."""
    feasible = [r for r in rows if r[key] <= threshold]
    if not feasible:
        return [], None
    return feasible, min(feasible, key=lambda r: r["edyp"])


def main() -> None:
    argv = list(sys.argv[1:])
    limit = 330.0
    if "--limit" in argv:
        index = argv.index("--limit")
        limit = float(argv[index + 1])
        del argv[index:index + 2]

    for path in (Path(p) for p in argv):
        payload = json.loads(path.read_text(encoding="utf-8"))
        ceiling = float(payload["ceiling_k"])
        rows, unresolved = [], 0
        for row in payload["all"]:
            nominal = float(row["nominal_peak_k"])
            certified = float(row["certified_peak_k"])
            if not (math.isfinite(nominal) and math.isfinite(certified)):
                unresolved += 1
                continue
            rows.append(row)
        if not rows:
            raise SystemExit(f"{path}: no resolvable candidate")

        # ThermoDSE's rule at THIS study's limit -- the strongest form of the objection, since its
        # own cap of 348 K would admit strictly more.
        nominal_set, nominal_best = _rule_optimum(rows, "nominal_peak_k", limit)
        envelope_set, envelope_best = _rule_optimum(rows, "certified_peak_k", ceiling)

        admitted_but_refuted = [r for r in nominal_set
                                if r["certified_peak_k"] > ceiling]
        refused_but_certified = [r for r in rows
                                 if r["nominal_peak_k"] > limit and r["certified_peak_k"] <= ceiling]

        print(f"== {path.name}   seed {payload['seed']} / {payload['workload']}, "
              f"span {payload['span']}, {len(rows)} candidates, {unresolved} unresolved")
        print(f"   nominal rule  peak <= {limit}      : {len(nominal_set)} feasible")
        print(f"   envelope rule sup  <= {ceiling}    : {len(envelope_set)} feasible")
        for name, best in (("nominal", nominal_best), ("envelope", envelope_best)):
            if best is None:
                print(f"   {name:<9} optimum : NONE feasible under this rule")
                continue
            print(f"   {name:<9} optimum : EDYP {best['edyp']:9.4f}  nominal {best['nominal_peak_k']:8.3f}"
                  f"  certified {best['certified_peak_k']:8.3f}  {best['design']}")
        if nominal_best and envelope_best:
            same = nominal_best["design"] == envelope_best["design"]
            print(f"   the two rules pick {'the SAME' if same else 'DIFFERENT'} design; "
                  f"EDYP ratio envelope/nominal = "
                  f"{envelope_best['edyp'] / nominal_best['edyp']:.4f}")
        print(f"   admitted by the nominal rule, REFUTED by the envelope : "
              f"{len(admitted_but_refuted)}")
        for r in sorted(admitted_but_refuted, key=lambda r: r["edyp"])[:5]:
            print(f"       EDYP {r['edyp']:9.4f}  nominal {r['nominal_peak_k']:8.3f} <= {limit}"
                  f"  but sup {r['certified_peak_k']:8.3f} > {ceiling}   {r['design']}")
        print(f"   refused by the nominal rule, CERTIFIED by the envelope : "
              f"{len(refused_but_certified)}")
        for r in sorted(refused_but_certified, key=lambda r: r["edyp"])[:5]:
            print(f"       EDYP {r['edyp']:9.4f}  nominal {r['nominal_peak_k']:8.3f} >  {limit}"
                  f"  but sup {r['certified_peak_k']:8.3f} <= {ceiling}  {r['design']}")
        print()


if __name__ == "__main__":
    main()
