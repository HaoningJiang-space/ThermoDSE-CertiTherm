"""The human-readable REPORT.md an experiment run leaves behind, and the gate it summarises.

Extracted from `experiments.py`, which had grown to 2 911 lines across five unrelated concerns.
This is the one with the fewest ties to the rest: it reads finished result rows and writes
Markdown, so nothing else in the package imports it except the driver that calls it once.

`AnytimeGateSummary` is the frozen v2+ endpoint computation. It lives beside the report rather
than beside the controller because the endpoints exist to be reported: nothing decides on them at
run time, and `passes` hard-fails on a single unexpected failure precisely so a run cannot be
summarised as passing while an ordinary failure hides in the table.

Layer position: depends on the `frozen_limits`, `split_protocol` and `tabular` leaves and on
nothing else in this package. It must stay that way -- an import back to `experiments` would put
a cycle through the driver.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional

import numpy as np

from .frozen_limits import MODEL_ERROR_LIMIT_K
from .split_protocol import protocol_state
from .tabular import read_rows


@dataclass(frozen=True)
class AnytimeGateSummary:
    """Frozen v2+ endpoints computed directly from result rows."""

    queries: int
    frozen_budget_rows: int
    certified_contracts: int
    finite_intervals: int
    false_certificates: int
    unexpected_failures: int
    median_upper_saving: Optional[float]
    self_verifiable: int
    solver_attested: int
    bounded_gap: int

    @property
    def passes(self) -> bool:
        return (
            self.queries == 12
            and self.frozen_budget_rows == self.queries
            and self.false_certificates == 0
            and self.unexpected_failures == 0
            and self.certified_contracts >= 10
            and self.median_upper_saving is not None
            and self.median_upper_saving >= 0.15
            and self.finite_intervals >= 6
        )


def _optional_float(row: Mapping[str, object], field: str) -> Optional[float]:
    value = row.get(field)
    return None if value in (None, "") else float(value)


def summarize_anytime_gate(
    rows: Iterable[Mapping[str, object]],
) -> AnytimeGateSummary:
    rows = list(rows)
    certified = [
        row
        for row in rows
        if row.get("plan_validity") == "CERTIFIED"
        and _optional_float(row, "certified_upper_bound") is not None
        and not row.get("interval_violation")
    ]
    savings = []
    for row in certified:
        upper = _optional_float(row, "certified_upper_bound")
        full = _optional_float(row, "full_registry_cost")
        if upper is not None and full is not None and full > 0:
            savings.append(1.0 - upper / full)
    finite_intervals = sum(
        row.get("plan_validity") == "CERTIFIED"
        and _optional_float(row, "certified_upper_bound") is not None
        and _optional_float(row, "certified_lower_bound") is not None
        and not row.get("interval_violation")
        for row in rows
    )
    false_certificates = sum(
        bool(row.get("interval_violation"))
        or bool(int(row.get("false_certificate") or 0))
        for row in rows
    )
    optimality = [row.get("cost_optimality") for row in rows]
    return AnytimeGateSummary(
        queries=len(rows),
        frozen_budget_rows=sum(
            int(row.get("budget_is_frozen") or 0) == 1 for row in rows
        ),
        certified_contracts=len(certified),
        finite_intervals=finite_intervals,
        false_certificates=false_certificates,
        unexpected_failures=sum(
            bool(row.get("unexpected_failure")) for row in rows
        ),
        median_upper_saving=(float(np.median(savings)) if savings else None),
        self_verifiable=optimality.count("PROVEN_SELF_VERIFIABLE"),
        solver_attested=optimality.count("PROVEN_SOLVER_ATTESTED"),
        bounded_gap=optimality.count("BOUNDED_GAP"),
    )


def write_run_report(
    path: Path,
    split: str,
    operators: Mapping[tuple[str, str], Path],
    results: Iterable[dict[str, object]],
    order_rows: Iterable[dict[str, object]],
    failures: Iterable[dict[str, object]],
    spectral_rows: Iterable[dict[str, object]],
) -> None:
    rows, failures, spectral_rows = (
        list(results),
        list(failures),
        list(spectral_rows),
    )
    statuses = {
        status: sum(row.get("exact_status") == status for row in rows)
        for status in ("OPTIMAL", "UNSYNTHESIZABLE", "UNRESOLVED")
    }
    resolved = [
        row
        for row in rows
        if row.get("exact_status") == "OPTIMAL"
        and row.get("exact_cost") is not None
    ]
    savings = [
        1 - float(row["exact_cost"]) / float(row["full_registry_cost"])
        for row in resolved
    ]
    false_certificates = sum(
        int(row.get("false_certificate") or 0) for row in rows
    )
    model_disagreements = sum(
        int(row.get("placed_model_disagreement") or 0) for row in rows
    )
    comparable = [
        row for row in resolved if row.get("dual_cost") != "" and row.get("width_cost") != ""
    ]
    dual_wins = sum(
        float(row["dual_cost"]) < float(row["width_cost"])
        for row in comparable
    )
    calibration_errors = []
    for operator in operators.values():
        for row in read_rows(operator.with_suffix(".calibration.tsv")):
            calibration_errors.append(float(row["max_abs_error_k"]))
    full_tail = [
        float(row["certified_peak_tail_k"])
        for row in spectral_rows
        if int(row["rank"]) == int(row["dimension"])
    ]
    anytime_gate = summarize_anytime_gate(rows)
    protocol_state = protocol_state(split)
    if protocol_state == "FROZEN_ACTIVE":
        anytime_verdict = "PASS" if anytime_gate.passes else "FAIL"
    else:
        anytime_verdict = f"NOT_SCORED ({protocol_state})"
    lines = [
        f"# CertiTherm {split} gate report",
        "",
        f"- Physical operators admitted: {len(operators)}",
        f"- Direct operator replays: {len(calibration_errors)}",
        f"- Certified spectral-envelope records: {len(spectral_rows)}",
        (
            f"- Maximum full-rank spectral residual: {max(full_tail):.9g} K"
            if full_tail
            else "- Maximum full-rank spectral residual: unavailable"
        ),
        f"- Exact status: {statuses}",
        f"- Internal false/contradictory certificates: {false_certificates}",
        f"- Archived placed-reference model disagreements: {model_disagreements}",
        (
            f"- Maximum direct-replay residual: {max(calibration_errors):.9g} K "
            f"(frozen bound {MODEL_ERROR_LIMIT_K:.3g} K)"
            if calibration_errors
            else "- Maximum direct-replay residual: unavailable"
        ),
        (
            f"- Median exact saving vs full registry: {np.median(savings):.1%}"
            if savings
            else "- Median exact saving vs full registry: unavailable"
        ),
        f"- Dual policy beats width: {dual_wins}/{len(comparable)} comparable queries",
        f"- Archived failures: {len(failures)}",
        "",
        "## Proof-carrying Anytime-DSOS gate",
        "",
        f"- Protocol state: {protocol_state}",
        f"- Gate verdict: {anytime_verdict}",
        (
            f"- Frozen-budget rows: "
            f"{anytime_gate.frozen_budget_rows}/{anytime_gate.queries}"
        ),
        (
            f"- Certified-contract coverage: "
            f"{anytime_gate.certified_contracts}/{anytime_gate.queries}"
        ),
        (
            f"- Finite certified intervals: "
            f"{anytime_gate.finite_intervals}/{anytime_gate.queries}"
        ),
        f"- False/contradictory certificates: {anytime_gate.false_certificates}",
        (
            "- Unexpected method/infrastructure failures: "
            f"{anytime_gate.unexpected_failures}"
        ),
        (
            f"- Median certified-U saving vs full registry: "
            f"{anytime_gate.median_upper_saving:.1%}"
            if anytime_gate.median_upper_saving is not None
            else "- Median certified-U saving vs full registry: unavailable"
        ),
        (
            "- Cost proof classes: "
            f"self-verifiable={anytime_gate.self_verifiable}, "
            f"solver-attested={anytime_gate.solver_attested}, "
            f"bounded-gap={anytime_gate.bounded_gap}"
        ),
        "",
        "## Workload-specific EDYP order",
        "",
        "| Workload | Rank | Architecture | EDYP |",
        "|---|---:|---|---:|",
    ]
    for row in order_rows:
        lines.append(
            f"| {row['workload']} | {row['objective_rank']} | "
            f"{row['architecture']} | {float(row['edyp']):.9g} |"
        )
    lines += [
        "",
        "## Query evidence",
        "",
        "| Workload | Package | Exact | Exact cost | Anytime U | Anytime L | U/L | Validity | Optimality | Fixed | Width | Dual | Full |",
        "|---|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|",
    ]
    numeric = lambda value: (
        "" if value in (None, "") else f"{float(value):.9g}"
    )
    for row in rows:
        lines.append(
            f"| {row['workload']} | {row['package']} | {row['exact_status']} | "
            f"{numeric(row.get('exact_cost'))} | "
            f"{numeric(row.get('certified_upper_bound'))} | "
            f"{numeric(row.get('certified_lower_bound'))} | "
            f"{numeric(row.get('approximation_ratio'))} | "
            f"{row.get('plan_validity', '')} | "
            f"{row.get('cost_optimality', '')} | "
            f"{numeric(row.get('fixed_cost'))} | "
            f"{numeric(row.get('width_cost'))} | "
            f"{numeric(row.get('dual_cost'))} | "
            f"{numeric(row.get('full_registry_cost'))} |"
        )
    lines += [
        "",
        "The exact cost is the registered finite-library non-adaptive batch "
        "optimum, not an unrestricted or continuous-adaptive sensor limit.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
