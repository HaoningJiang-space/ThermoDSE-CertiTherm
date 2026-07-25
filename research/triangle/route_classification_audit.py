"""Audit ThermoDSE channel counters against explicit physical route edges. (NON-CLAIM)

The route-event ledger preserves ThermoDSE's aggregate NoC/NoP counters.  This audit asks
the independent spatial question: whenever an event reports positive energy for a channel,
does its reconstructed route contain at least one edge of that physical channel?

Usage:
    python research/triangle/route_classification_audit.py <route-event.json> [...]
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.routed_trace import _edge_channel, _event_edge_weights


def architecture(arch_id):
    with Path("experiments/architectures.tsv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["architecture_id"] == arch_id:
                return row
    raise ValueError(f"unknown architecture: {arch_id}")


def audit(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    arch = architecture(report["arch"])
    nx, ny = int(arch["chiplet_x"]), int(arch["chiplet_y"])
    cut_x, cut_y = int(arch["cut_x"]), int(arch["cut_y"])
    mismatches = Counter()
    examples = []
    classified_energy = Counter()
    mismatch_energy = Counter()

    for event in report["events"]:
        weights = _event_edge_weights(event, nx)
        present = {
            _edge_channel(edge, nx, ny, cut_x, cut_y)
            for edge, weight in weights.items()
            if float(weight) > 0.0
        }
        for channel in ("noc", "nop"):
            energy_pj = float(event[f"{channel}_energy_pj"])
            if energy_pj <= 0.0:
                continue
            classified_energy[channel] += energy_pj
            if channel in present:
                continue
            key = (str(event["kind"]), channel, tuple(sorted(present)))
            mismatches[key] += 1
            mismatch_energy[channel] += energy_pj
            if len(examples) < 12:
                examples.append(
                    {
                        "order": int(event["order"]),
                        "stage": event["stage"],
                        "kind": event["kind"],
                        "source": event.get("source"),
                        "destinations": event.get("destinations"),
                        "reported_channel": channel,
                        "reported_energy_pj": energy_pj,
                        "physical_channels": sorted(present),
                    }
                )

    print(
        f"{report['arch']} / {report['workload']}: {len(report['events'])} events; "
        f"{sum(mismatches.values())} positive-channel mismatches"
    )
    for channel in ("noc", "nop"):
        total = float(classified_energy[channel])
        bad = float(mismatch_energy[channel])
        fraction = bad / total if total else 0.0
        print(
            f"  {channel}: mismatched energy={bad:.6e}/{total:.6e} pJ "
            f"({fraction:.6%})"
        )
    for key, count in sorted(mismatches.items()):
        print(f"  {key}: {count} events")
    for example in examples:
        print("  example " + json.dumps(example, separators=(",", ":")))
    return not mismatches


def main():
    if len(sys.argv) < 2:
        raise SystemExit("pass at least one route-event JSON")
    passed = True
    for argument in sys.argv[1:]:
        passed = audit(Path(argument)) and passed
    if not passed:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
