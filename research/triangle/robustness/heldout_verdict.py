"""Score the eight preregistered predictions against the held-out split. Written before the data.

`docs/HELDOUT_PROTOCOL_RADII.md` declares eight predictions and four kill conditions under freeze ID
`method-freeze-radii-v1`. This file evaluates exactly those, at exactly those thresholds, and it was
committed **before the held-out sweep produced any point** -- which is the only thing that stops a
scorer from being written around whatever the data happened to say.

Each prediction is a pure function of the artifacts. Nothing here selects, filters or reweights: an
architecture the error contract refused is absent from the sweep and is counted as refused, and a
prediction whose inputs are missing is `UNRESOLVED` rather than skipped.

NON-CLAIM in construction, but its OUTPUT is the claim-grade verdict for this split. One run.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/heldout_verdict.py <heldout-sweep-dir> \\
        <cost-crossover.json> <per-model.json> <yield-composition.json> [out.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DECLARED_ARCHITECTURES = 18
MAX_REFUSALS = 9                 # more than this and the run is UNRESOLVED, not reported


def _groups(points, key=("tiles", "interval_m", "workload")):
    out: dict = {}
    for point in points:
        out.setdefault(tuple(str(point.get(k)) for k in key), []).append(point)
    return {k: sorted(v, key=lambda r: r["dies"]) for k, v in out.items() if len(v) > 1}


def p1_radius_strictly_monotone(points):
    """`beta*_reject` rises strictly with the die count in EVERY decision group."""

    failures = []
    for key, members in _groups(points).items():
        radii = [m.get("beta_star_l1") for m in members]
        if any(r is None for r in radii):
            return "UNRESOLVED", ["beta_star_l1 missing; run relocation_radii.py first"]
        if not all(a < b for a, b in zip(radii, radii[1:])):
            failures.append(f"{key}: {radii}")
    return ("PASS" if not failures else "FAIL"), failures


def p2_every_operator_and_radius_agrees(per_model):
    verdicts = per_model.get("verdicts", [])
    if not verdicts:
        return "UNRESOLVED", ["per-model verdicts absent"]
    bad = [
        f'{v["tiles"]}/{v["workload"]}'
        for v in verdicts
        if not v.get("all_models_and_both_radii_induce_the_family_order")
    ]
    return ("PASS" if not bad else "FAIL"), bad


def p3_product_prefers_monolithic(yield_comp):
    verdicts = yield_comp.get("verdicts", [])
    if not verdicts:
        return "UNRESOLVED", ["yield-composition verdicts absent"]
    bad = [
        f'{v["tiles"]}/{v["workload"]}: n={v["dies_by_composition"]["product"]}'
        for v in verdicts
        if v["dies_by_composition"].get("product") != 1
    ]
    return ("PASS" if len(bad) <= 0 else ("FAIL" if len(bad) > 2 else "DOWNGRADE")), bad


def p4_recurring_cost_prefers_monolithic(cost, groups_expected):
    verdicts = cost.get("verdicts", [])
    if not verdicts:
        return "UNRESOLVED", ["cost verdicts absent"], 0
    hits = sum(1 for v in verdicts if v["dies_at_registered_cost"] == 1)
    threshold = max(1, round(9 * len(verdicts) / groups_expected))
    status = "PASS" if hits >= threshold else ("FAIL" if hits < round(7 * len(verdicts) / groups_expected) else "DOWNGRADE")
    return status, [f"{hits} of {len(verdicts)} prefer n=1, threshold {threshold}"], hits


def p5_cost_and_robustness_disagree(cost, groups_expected):
    verdicts = cost.get("verdicts", [])
    if not verdicts:
        return "UNRESOLVED", ["cost verdicts absent"], 0
    hits = sum(1 for v in verdicts if not v["cost_choice_matches_robust"])
    threshold = max(1, round(9 * len(verdicts) / groups_expected))
    status = "PASS" if hits >= threshold else ("FAIL" if hits < round(7 * len(verdicts) / groups_expected) else "DOWNGRADE")
    return status, [f"{hits} of {len(verdicts)} disagree, threshold {threshold}"], hits


def p6_no_cut_owns_the_box(cost):
    verdicts = cost.get("verdicts", [])
    if not verdicts:
        return "UNRESOLVED", ["cost verdicts absent"]
    bad = [f'{v["tiles"]}/{v["workload"]}' for v in verdicts if v.get("any_cut_owns_the_whole_box")]
    return ("PASS" if not bad else "FAIL"), bad


def p7_containment_holds_on_every_point(points):
    bad = []
    for point in points:
        eps, beta = point.get("epsilon_star"), point.get("beta_star_l1")
        if eps is None or beta is None:
            return "UNRESOLVED", ["epsilon_star or beta_star_l1 missing"]
        if eps > beta + 1e-9:
            bad.append(f'{point["arch"]}/{point["workload"]}: {eps} > {beta}')
    return ("PASS" if not bad else "FAIL"), bad


def p8_monolithic_pair_root_outside_range(cost):
    verdicts = cost.get("verdicts", [])
    if not verdicts:
        return "UNRESOLVED", ["cost verdicts absent"]
    bad = []
    for verdict in verdicts:
        first = next((p for p in verdict["pairs"] if p["dies_coarse"] == 1), None)
        if first is None:
            return "UNRESOLVED", ["no n=1 pair in a decision group"]
        if first["registered"]["inside_physical_range"]:
            bad.append(
                f'{verdict["tiles"]}/{verdict["workload"]}: '
                f'{first["registered"]["critical_bonding_yield_exact"]}'
            )
    return ("PASS" if len(bad) <= 2 else "FAIL"), bad


def main() -> None:
    sweep_dir = Path(sys.argv[1])
    cost = json.loads(Path(sys.argv[2]).read_text())
    per_model = json.loads(Path(sys.argv[3]).read_text())
    yield_comp = json.loads(Path(sys.argv[4]).read_text())
    out_path = Path(sys.argv[5]) if len(sys.argv) > 5 else None

    points = json.loads((sweep_dir / "sweep.json").read_text())
    architectures = len({p["arch"] for p in points})
    refused = DECLARED_ARCHITECTURES - architectures

    results = {}
    if refused > MAX_REFUSALS:
        results["RUN"] = {
            "status": "UNRESOLVED",
            "detail": [
                f"{refused} of {DECLARED_ARCHITECTURES} architectures refused, above the "
                f"preregistered ceiling of {MAX_REFUSALS}; the split is not reported on the remainder"
            ],
        }
    else:
        groups_expected = 12
        results["P1_radius_strictly_monotone"] = dict(zip(("status", "detail"), p1_radius_strictly_monotone(points)))
        results["P2_every_operator_and_radius_agrees"] = dict(zip(("status", "detail"), p2_every_operator_and_radius_agrees(per_model)))
        results["P3_product_prefers_monolithic"] = dict(zip(("status", "detail"), p3_product_prefers_monolithic(yield_comp)))
        s, d, h = p4_recurring_cost_prefers_monolithic(cost, groups_expected)
        results["P4_recurring_cost_prefers_monolithic"] = {"status": s, "detail": d, "count": h}
        s, d, h = p5_cost_and_robustness_disagree(cost, groups_expected)
        results["P5_cost_and_robustness_disagree"] = {"status": s, "detail": d, "count": h}
        results["P6_no_cut_owns_the_box"] = dict(zip(("status", "detail"), p6_no_cut_owns_the_box(cost)))
        results["P7_containment_holds"] = dict(zip(("status", "detail"), p7_containment_holds_on_every_point(points)))
        results["P8_monolithic_pair_root_outside"] = dict(zip(("status", "detail"), p8_monolithic_pair_root_outside_range(cost)))

    payload = {
        "freeze_id": "method-freeze-radii-v1",
        "protocol": "docs/HELDOUT_PROTOCOL_RADII.md",
        "architectures_declared": DECLARED_ARCHITECTURES,
        "architectures_evaluated": architectures,
        "architectures_refused": refused,
        "points": len(points),
        "predictions": results,
    }
    for name, entry in results.items():
        print("%-40s %-11s %s" % (name, entry["status"], "; ".join(entry["detail"])[:90]), flush=True)
    statuses = [e["status"] for e in results.values()]
    print(
        "\n%d PASS, %d DOWNGRADE, %d FAIL, %d UNRESOLVED of %d"
        % (statuses.count("PASS"), statuses.count("DOWNGRADE"), statuses.count("FAIL"),
           statuses.count("UNRESOLVED"), len(statuses)),
        flush=True,
    )
    if out_path is not None:
        out_path.write_text(json.dumps(payload, indent=1))


if __name__ == "__main__":
    main()
