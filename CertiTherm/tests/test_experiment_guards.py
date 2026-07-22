"""Fail-closed guards for claim-grade experiment launches."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from CertiTherm import experiments


def _set_frozen_v3_environment(monkeypatch) -> None:
    for name, value in experiments.FROZEN_V3_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)


def test_frozen_run_rejects_budget_override() -> None:
    with pytest.raises(ValueError, match="exactly 1800s"):
        experiments._validate_run_request("heldout", True, budget_s=700.0)


def test_burned_split_cannot_be_relabelled_as_frozen_evidence() -> None:
    with pytest.raises(ValueError, match="OPENED_INVALID"):
        experiments._validate_run_request("heldout_v2", True, budget_s=1800.0)


def test_v3_is_unexecutable_until_preconditions_close() -> None:
    with pytest.raises(ValueError, match="only run through its frozen protocol"):
        experiments._validate_run_request("heldout_v3", False, budget_s=1800.0)
    with pytest.raises(ValueError, match="not admitted for frozen execution yet"):
        experiments._validate_run_request("heldout_v3", True, budget_s=1800.0)


def test_nonfrozen_dev_rehearsal_remains_available() -> None:
    experiments._validate_run_request("dev", False, budget_s=25.0)


def test_registered_v1_frozen_request_is_admitted() -> None:
    experiments._validate_run_request("heldout", True, budget_s=1800.0)


def test_unknown_split_is_rejected_before_creating_output() -> None:
    with pytest.raises(ValueError, match="unregistered experiment split"):
        experiments._validate_run_request("typo", False, budget_s=1800.0)


def test_frozen_run_rejects_dirty_worktree(monkeypatch) -> None:
    monkeypatch.setattr(
        experiments.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=" M CertiTherm/core.py\n"),
    )
    with pytest.raises(RuntimeError, match="requires a clean revision"):
        experiments._assert_clean_revision()


def test_v3_registry_is_new_on_both_heldout_axes() -> None:
    architectures = experiments._rows(
        experiments.ROOT / "experiments" / "architectures.tsv"
    )
    workloads = experiments._rows(
        experiments.ROOT / "experiments" / "workloads.tsv"
    )
    v3_arches = [row for row in architectures if row["split"] == "heldout_v3"]
    prior_arches = [row for row in architectures if row["split"] != "heldout_v3"]
    v3_workloads = [row for row in workloads if row["split"] == "heldout_v3"]
    prior_workloads = [row for row in workloads if row["split"] != "heldout_v3"]

    architecture_fields = (
        "chiplet_x",
        "chiplet_y",
        "cut_x",
        "cut_y",
        "interval",
        "mtxu_h",
        "mtxu_w",
        "ubuf",
        "nop_bw",
        "dram_bw",
    )
    def signature(row: dict[str, str]) -> tuple[str, ...]:
        return tuple(row[field] for field in architecture_fields)

    assert len(v3_arches) == 3
    assert {signature(row) for row in v3_arches}.isdisjoint(
        {signature(row) for row in prior_arches}
    )
    assert all(
        int(row["chiplet_x"]) % int(row["cut_x"]) == 0
        and int(row["chiplet_y"]) % int(row["cut_y"]) == 0
        for row in v3_arches
    )
    assert len(v3_workloads) == 4
    assert {row["thermodse_name"] for row in v3_workloads}.isdisjoint(
        {row["thermodse_name"] for row in prior_workloads}
    )
    assert all(
        row["b_tot"] == row["b_exe"] == "1"
        and float(row["sparsity"]) == 0.0
        for row in v3_workloads
    )


def test_hotspot_binary_must_match_bootstrap_receipt(tmp_path) -> None:
    binary = tmp_path / "hotspot"
    receipt = tmp_path / "SHA256SUMS"
    binary.write_bytes(b"pinned binary")
    digest = experiments._sha256(binary)
    receipt.write_text(f"{digest}  hotspot\n", encoding="utf-8")
    assert experiments._verified_binary_digest(binary, receipt) == digest

    receipt.write_text(f"{'0' * 64}  hotspot\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no longer matches"):
        experiments._verified_binary_digest(binary, receipt)


def test_multi_binary_receipt_matches_each_binary_by_name(tmp_path) -> None:
    exporter = tmp_path / "hotspot"
    solver = tmp_path / "certitherm_hotspot_cuda"
    receipt = tmp_path / "GPU_SHA256SUMS"
    exporter.write_bytes(b"exporter")
    solver.write_bytes(b"solver")
    exporter_digest = experiments._sha256(exporter)
    solver_digest = experiments._sha256(solver)
    receipt.write_text(
        f"{exporter_digest}  .build/hotspot-gpu-export/hotspot\n"
        f"{solver_digest}  .build/hotspot-cuda/certitherm_hotspot_cuda\n",
        encoding="utf-8",
    )

    assert (
        experiments._verified_binary_digest(exporter, receipt)
        == exporter_digest
    )
    assert experiments._verified_binary_digest(solver, receipt) == solver_digest


def test_gpu_backend_verifies_the_registered_exporter_and_solver(
    tmp_path, monkeypatch
) -> None:
    build = tmp_path / "hotspot-gpu-export"
    build.mkdir()
    exporter = build / "hotspot"
    solver = tmp_path / "hotspot-cuda" / "certitherm_hotspot_cuda"
    solver.parent.mkdir()
    exporter.write_bytes(b"exporter")
    solver.write_bytes(b"solver")
    (build / "GPU_SHA256SUMS").write_text(
        f"{experiments._sha256(exporter)}  {exporter}\n"
        f"{experiments._sha256(solver)}  {solver}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(experiments, "GPU_HOTSPOT_BUILD", build)
    monkeypatch.setattr(experiments, "GPU_HOTSPOT_EXPORTER", exporter)
    monkeypatch.setattr(experiments, "GPU_HOTSPOT_SOLVER", solver)
    monkeypatch.setenv("CERTITHERM_GPU_HOTSPOT", "1")

    backend = experiments._gpu_backend()

    assert backend is not None
    assert backend.exporter == exporter
    assert backend.solver == solver


def test_cache_receipt_binds_inputs_and_every_cached_file(tmp_path) -> None:
    artifact = tmp_path / "operator.npz"
    calibration = tmp_path / "operator.calibration.tsv"
    artifact.write_bytes(b"operator-v1")
    calibration.write_bytes(b"calibration-v1")
    signature = {
        "kind": "hotspot-operator",
        "builder_sha256": "a" * 64,
        "input_sha256": "b" * 64,
    }
    related = {"calibration": calibration}

    assert not experiments._cache_receipt_matches(
        artifact,
        signature,
        related,
    )
    experiments._write_cache_receipt(artifact, signature, related)
    assert experiments._cache_receipt_matches(artifact, signature, related)

    artifact.write_bytes(b"operator-tampered")
    assert not experiments._cache_receipt_matches(
        artifact,
        signature,
        related,
    )
    artifact.write_bytes(b"operator-v1")
    calibration.write_bytes(b"calibration-tampered")
    assert not experiments._cache_receipt_matches(
        artifact,
        signature,
        related,
    )


def test_operator_failure_taxonomy_keeps_programming_errors_loud() -> None:
    assert experiments._is_archivable_operator_failure(RuntimeError("model"))
    assert experiments._is_archivable_operator_failure(TimeoutError("budget"))
    assert not experiments._is_archivable_operator_failure(NameError("symbol"))
    assert not experiments._is_archivable_operator_failure(TypeError("shape"))


def test_only_wall_clock_timeout_is_an_expected_method_failure() -> None:
    failures = experiments._unexpected_method_failures(
        {
            "exact": "TimeoutError: 1800s budget exhausted",
            "dual": "NameError: missing symbol",
        }
    )
    assert failures == {"dual": "NameError: missing symbol"}


def test_producer_label_names_the_actual_split() -> None:
    assert "--split dev" in experiments._canonical_producer("dev", False)
    v3 = experiments._canonical_producer("heldout_v3", True)
    assert "--split heldout_v3" in v3
    assert v3.endswith("--frozen")
    assert "/home/" not in v3 and "/data/" not in v3


def test_v3_frozen_worker_count_is_part_of_the_protocol(monkeypatch) -> None:
    monkeypatch.setattr(
        experiments,
        "_FROZEN_ENABLED_SPLITS",
        frozenset({"heldout", "heldout_v3"}),
    )
    monkeypatch.setattr(experiments, "QUERY_WORKERS", 2)
    with pytest.raises(ValueError, match="exactly 3 query workers"):
        experiments._validate_run_request(
            "heldout_v3", True, budget_s=1800.0
        )

    monkeypatch.setattr(experiments, "QUERY_WORKERS", 3)
    _set_frozen_v3_environment(monkeypatch)
    experiments._validate_run_request("heldout_v3", True, budget_s=1800.0)


def test_v3_rejects_unpinned_numeric_threads(monkeypatch) -> None:
    monkeypatch.setattr(
        experiments,
        "_FROZEN_ENABLED_SPLITS",
        frozenset({"heldout", "heldout_v3"}),
    )
    monkeypatch.setattr(experiments, "QUERY_WORKERS", 3)
    _set_frozen_v3_environment(monkeypatch)
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "8")

    with pytest.raises(ValueError, match="frozen execution environment"):
        experiments._validate_run_request(
            "heldout_v3", True, budget_s=1800.0
        )


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("CERTITHERM_LP_WORKERS", "2"),
        ("CERTITHERM_GPU_HOTSPOT", "0"),
        ("CERTITHERM_GPU_DEVICE", "1"),
        ("CUDA_VISIBLE_DEVICES", "1"),
    ),
)
def test_v3_rejects_unfrozen_solver_or_gpu_environment(
    monkeypatch, name, value
) -> None:
    monkeypatch.setattr(
        experiments,
        "_FROZEN_ENABLED_SPLITS",
        frozenset({"heldout", "heldout_v3"}),
    )
    monkeypatch.setattr(experiments, "QUERY_WORKERS", 3)
    _set_frozen_v3_environment(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match="frozen execution environment"):
        experiments._validate_run_request(
            "heldout_v3", True, budget_s=1800.0
        )


def test_run_receipt_records_query_scheduler(monkeypatch) -> None:
    monkeypatch.setattr(experiments, "_sha256", lambda _path: "a" * 64)
    monkeypatch.setattr(experiments, "_git_revision", lambda _path: "b" * 40)
    monkeypatch.setenv("CERTITHERM_LP_WORKERS", "1")
    monkeypatch.delenv("CERTITHERM_GPU_HOTSPOT", raising=False)
    receipt = experiments._run_receipt(
        "dev",
        False,
        datetime(2026, 7, 22, tzinfo=timezone.utc),
        "c" * 64,
    )

    assert receipt["query_workers"] == experiments.QUERY_WORKERS
    assert receipt["query_parallelism"] == "persistent-spawn-pool"
    assert receipt["lp_separation_workers"] == "1"
    for name in experiments.FROZEN_NUMERIC_THREAD_VARIABLES:
        assert receipt[name.lower()] == experiments.os.environ.get(name, "")


def test_gpu_run_receipt_records_the_visible_device_mapping(monkeypatch) -> None:
    monkeypatch.setattr(experiments, "_sha256", lambda _path: "a" * 64)
    monkeypatch.setattr(experiments, "_git_revision", lambda _path: "b" * 40)
    monkeypatch.setattr(
        experiments,
        "_verified_binary_digest",
        lambda _binary, _receipt: "c" * 64,
    )
    monkeypatch.setenv("CERTITHERM_GPU_HOTSPOT", "1")
    monkeypatch.setenv("CERTITHERM_GPU_DEVICE", "0")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")

    receipt = experiments._run_receipt(
        "dev",
        False,
        datetime(2026, 7, 22, tzinfo=timezone.utc),
        "d" * 64,
    )

    assert receipt["gpu_device"] == "0"
    assert receipt["cuda_visible_devices"] == "0"
