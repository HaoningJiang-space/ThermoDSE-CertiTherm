"""Pre-open ThermoDSE feasibility check for the heldout-v3 split.

This command is intentionally narrower than `CertiTherm.experiments`: it never
builds a thermal operator, never runs HotSpot, and never constructs a DSOS
query.  It records only the non-thermal metrics permitted by the v3 protocol.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import socket
import subprocess
import sys
import traceback
from typing import Iterable, Mapping

from .experiments import (
    ROOT,
    THERMODSE,
    _assert_clean_revision,
    _rows,
    _sha256,
    _write_tsv,
    evaluate_nonthermal_candidate,
    NonthermalCandidateInvalid,
)


SPLIT = "heldout_v3"
MIN_ADJACENT_EDYP_GAP = 0.01
PASS = "PASS"
REPLACEMENT_REQUIRED = "REPLACEMENT_REQUIRED"
UNRESOLVED = "UNRESOLVED"


def rank_precheck_rows(
    rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Rank each workload by EDYP and attach the adjacent relative gap."""

    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(row["workload_id"])].append(row)

    ranked: list[dict[str, object]] = []
    for workload_id in sorted(groups):
        group = sorted(groups[workload_id], key=lambda row: float(row["edyp"]))
        if len(group) != 3:
            raise RuntimeError(
                f"{workload_id} has {len(group)} precheck rows; expected 3"
            )
        if len({str(row["architecture_id"]) for row in group}) != len(group):
            raise RuntimeError(f"{workload_id} contains duplicate architectures")
        previous = None
        for rank, source in enumerate(group):
            row = dict(source)
            edyp = float(row["edyp"])
            row["edyp_rank"] = rank
            row["adjacent_relative_gap"] = (
                "" if previous is None else (edyp - previous) / previous
            )
            ranked.append(row)
            previous = edyp
    return ranked


def _minimum_gap(rows: Iterable[Mapping[str, object]]) -> float:
    gaps = [
        float(row["adjacent_relative_gap"])
        for row in rows
        if row.get("adjacent_relative_gap") not in (None, "")
    ]
    return min(gaps) if gaps else float("-inf")


def classify_precheck(
    *,
    completed_rows: int,
    invalid_candidates: int,
    unexpected_failures: int,
    minimum_gap: float,
) -> str:
    """Map evidence to a protocol outcome without conflating code failures."""

    if unexpected_failures or completed_rows + invalid_candidates != 12:
        return UNRESOLVED
    if invalid_candidates or minimum_gap < MIN_ADJACENT_EDYP_GAP:
        return REPLACEMENT_REQUIRED
    return PASS


def _git_revision(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def run(output: Path) -> bool:
    """Execute the one permitted v3 non-thermal check and write its receipt."""

    if output.exists():
        raise RuntimeError(f"refusing to overwrite precheck output {output}")
    _assert_clean_revision()
    if not THERMODSE.is_dir():
        raise RuntimeError("run make bootstrap before the v3 precheck")

    architectures = [
        row
        for row in _rows(ROOT / "experiments" / "architectures.tsv")
        if row["split"] == SPLIT
    ]
    workloads = [
        row
        for row in _rows(ROOT / "experiments" / "workloads.tsv")
        if row["split"] == SPLIT
    ]
    packages = _rows(ROOT / "experiments" / "packages.tsv")
    default_package = next(
        row for row in packages if row["package_id"] == "default"
    )
    if len(architectures) != 3 or len(workloads) != 4:
        raise RuntimeError("v3 precheck requires exactly 3 architectures x 4 workloads")

    output.mkdir(parents=True)
    started_at = datetime.now(timezone.utc)
    git_sha = _git_revision(ROOT)
    rows, invalid_candidates, failures = [], [], []
    for workload in workloads:
        for architecture in architectures:
            identity = {
                "workload_id": workload["workload_id"],
                "architecture_id": architecture["architecture_id"],
            }
            try:
                metrics = evaluate_nonthermal_candidate(
                    architecture,
                    workload,
                    default_package,
                    output,
                )
                rows.append({**identity, **metrics, "git_sha": git_sha})
            except NonthermalCandidateInvalid as exc:
                invalid_candidates.append(
                    {
                        **identity,
                        "reason": str(exc),
                        "git_sha": git_sha,
                    }
                )
            except Exception as exc:
                failures.append(
                    {
                        **identity,
                        "failure_type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                        "git_sha": git_sha,
                    }
                )

    complete = not invalid_candidates and not failures and len(rows) == 12
    ranked = rank_precheck_rows(rows) if complete else rows
    minimum_gap = _minimum_gap(ranked) if complete else float("-inf")
    status = classify_precheck(
        completed_rows=len(rows),
        invalid_candidates=len(invalid_candidates),
        unexpected_failures=len(failures),
        minimum_gap=minimum_gap,
    )

    _write_tsv(output / "PRECHECK.tsv", ranked)
    if invalid_candidates:
        _write_tsv(output / "INVALID_CANDIDATES.tsv", invalid_candidates)
    if failures:
        _write_tsv(output / "FAILURES.tsv", failures)
    ended_at = datetime.now(timezone.utc)
    receipt = {
        "split": SPLIT,
        "git_sha": git_sha,
        "thermodse_sha": _git_revision(THERMODSE),
        "hotspot_sha": _git_revision(ROOT / "HotSpot"),
        "host": socket.gethostname(),
        "python": sys.version.split()[0],
        "started_at_utc": started_at.isoformat(),
        "ended_at_utc": ended_at.isoformat(),
        "hotspot_invocations": 0,
        "architectures_sha256": _sha256(
            ROOT / "experiments" / "architectures.tsv"
        ),
        "workloads_sha256": _sha256(ROOT / "experiments" / "workloads.tsv"),
        "status": status,
    }
    _write_tsv(output / "RECEIPT.tsv", [receipt])
    report = [
        "# CertiTherm heldout-v3 non-thermal precheck",
        "",
        f"- Status: {receipt['status']}",
        f"- Git SHA: `{git_sha}`",
        f"- Completed combinations: {len(rows)}/12",
        f"- Invalid candidates: {len(invalid_candidates)}",
        f"- Failures: {len(failures)}",
        "- HotSpot invocations: 0 (Python call disabled plus shell fail-fast sentinel)",
        (
            f"- Minimum adjacent EDYP gap: {minimum_gap:.3%} "
            f"(required {MIN_ADJACENT_EDYP_GAP:.1%})"
            if complete
            else "- Minimum adjacent EDYP gap: unavailable"
        ),
        "",
        "This check contains no temperature, thermal operator, measurement "
        "registry, DSOS result, or observation-contract cost.",
        "",
    ]
    (output / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    scientific_files = sorted(
        path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS"
    )
    (output / "SHA256SUMS").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in scientific_files),
        encoding="utf-8",
    )
    return status == PASS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not run(args.output):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
