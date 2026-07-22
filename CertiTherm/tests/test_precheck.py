"""Pure checks for heldout-v3 non-thermal precheck semantics."""

from __future__ import annotations

import sys

import pytest

from CertiTherm import experiments
from CertiTherm.precheck import (
    PASS,
    REPLACEMENT_REQUIRED,
    UNRESOLVED,
    _minimum_gap,
    classify_precheck,
    rank_precheck_rows,
)


def test_precheck_ranks_each_workload_and_computes_adjacent_gap() -> None:
    rows = [
        {"workload_id": workload, "architecture_id": arch, "edyp": edyp}
        for workload in ("w0", "w1")
        for arch, edyp in (("a", 12.0), ("b", 10.0), ("c", 15.0))
    ]
    ranked = rank_precheck_rows(rows)
    assert [
        row["architecture_id"] for row in ranked if row["workload_id"] == "w0"
    ] == ["b", "a", "c"]
    assert _minimum_gap(ranked) == pytest.approx(0.2)


def test_precheck_rejects_an_incomplete_architecture_set() -> None:
    with pytest.raises(RuntimeError, match="expected 3"):
        rank_precheck_rows(
            (
                {"workload_id": "w", "architecture_id": "a", "edyp": 1.0},
                {"workload_id": "w", "architecture_id": "b", "edyp": 2.0},
            )
        )


def test_precheck_rejects_duplicate_architectures() -> None:
    with pytest.raises(RuntimeError, match="duplicate architectures"):
        rank_precheck_rows(
            (
                {"workload_id": "w", "architecture_id": "a", "edyp": 1.0},
                {"workload_id": "w", "architecture_id": "a", "edyp": 2.0},
                {"workload_id": "w", "architecture_id": "b", "edyp": 3.0},
            )
        )


@pytest.mark.parametrize(
    ("completed", "invalid", "failures", "gap", "expected"),
    (
        (12, 0, 0, 0.01, PASS),
        (12, 0, 0, 0.009, REPLACEMENT_REQUIRED),
        (11, 1, 0, float("-inf"), REPLACEMENT_REQUIRED),
        (11, 0, 1, float("-inf"), UNRESOLVED),
        (11, 0, 0, float("-inf"), UNRESOLVED),
    ),
)
def test_precheck_outcomes_do_not_turn_failures_into_replacements(
    completed: int,
    invalid: int,
    failures: int,
    gap: float,
    expected: str,
) -> None:
    assert (
        classify_precheck(
            completed_rows=completed,
            invalid_candidates=invalid,
            unexpected_failures=failures,
            minimum_gap=gap,
        )
        == expected
    )


def test_nonthermal_sim_has_two_independent_hotspot_guards(tmp_path) -> None:
    architecture = next(
        row
        for row in experiments._rows(
            experiments.ROOT / "experiments" / "architectures.tsv"
        )
        if row["split"] == "heldout_v3"
    )
    workload = next(
        row
        for row in experiments._rows(
            experiments.ROOT / "experiments" / "workloads.tsv"
        )
        if row["split"] == "heldout_v3"
    )
    package = next(
        row
        for row in experiments._rows(
            experiments.ROOT / "experiments" / "packages.tsv"
        )
        if row["package_id"] == "default"
    )
    sim = experiments._prepare_thermodse_sim(
        architecture,
        workload,
        package,
        tmp_path,
        allow_hotspot=False,
    )
    assert not tuple((sim / "outputs").glob("*.steady"))
    assert "HotSpot is forbidden" in (sim / "run.sh").read_text(encoding="utf-8")


def test_compatibility_layer_loads_frozen_legacy_workloads() -> None:
    thermodse_path = str(experiments.THERMODSE)
    if thermodse_path not in sys.path:
        sys.path.insert(0, thermodse_path)
    experiments._install_thermodse_compatibility()

    from nns import import_network  # type: ignore

    for workload in ("alex_net", "lstm_gnmt"):
        assert import_network(workload).net_name
