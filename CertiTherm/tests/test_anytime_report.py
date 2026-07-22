"""Report-level acceptance logic for proof-carrying Anytime-DSOS."""

from __future__ import annotations

import pytest

from CertiTherm.experiments import _summarize_anytime_gate


def _row(index: int) -> dict[str, object]:
    certified = index < 10
    finite = index < 6
    return {
        "plan_validity": "CERTIFIED" if certified else "UNRESOLVED",
        "certified_upper_bound": 80.0 if certified else "",
        "certified_lower_bound": 70.0 if finite else "",
        "full_registry_cost": 100.0,
        "interval_violation": "",
        "false_certificate": 0,
        "cost_optimality": "BOUNDED_GAP" if finite else "UNKNOWN",
        "budget_is_frozen": 1,
    }


def test_anytime_gate_passes_only_when_all_frozen_thresholds_hold() -> None:
    summary = _summarize_anytime_gate(_row(index) for index in range(12))
    assert summary.certified_contracts == 10
    assert summary.finite_intervals == 6
    assert summary.median_upper_saving == pytest.approx(0.2)
    assert summary.false_certificates == 0
    assert summary.passes


def test_interval_contradiction_is_a_hard_gate_failure() -> None:
    rows = [_row(index) for index in range(12)]
    rows[0]["interval_violation"] = "L exceeds U"
    summary = _summarize_anytime_gate(rows)
    assert summary.false_certificates == 1
    assert not summary.passes


def test_unverified_candidate_is_not_counted_as_a_certified_upper() -> None:
    rows = [_row(index) for index in range(12)]
    rows[0]["plan_validity"] = "UNRESOLVED"
    summary = _summarize_anytime_gate(rows)
    assert summary.certified_contracts == 9
    assert not summary.passes


def test_rehearsal_budget_cannot_pass_the_frozen_gate() -> None:
    rows = [_row(index) for index in range(12)]
    rows[0]["budget_is_frozen"] = 0
    summary = _summarize_anytime_gate(rows)
    assert summary.frozen_budget_rows == 11
    assert not summary.passes
