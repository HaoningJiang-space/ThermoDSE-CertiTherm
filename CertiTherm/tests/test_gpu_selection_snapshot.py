"""The cache identity and the operator build must read the GPU configuration exactly once.

`CERTITHERM_GPU_HOTSPOT` was consulted at four independent points and `CERTITHERM_GPU_DEVICE` at
three. Nothing tied the reading used by `_operator_cache_signature` to the one used by
`_gpu_backend`, so a signature could describe a CPU build while a GPU produced the operator, and the
receipt would look entirely consistent.

That is the false-hit direction: results internally coherent but attributed to the wrong thermal
operator, which can enter claim-grade evidence unnoticed. Peer review named the hazard in the
abstract; these tests pin the snapshot that closes it.
"""

from __future__ import annotations

import pytest

from CertiTherm import experiments
from CertiTherm.experiments import GpuSelection


def test_a_snapshot_reflects_the_environment_it_was_taken_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-vacuity: the snapshot must actually vary, or the tests below prove nothing."""

    monkeypatch.delenv("CERTITHERM_GPU_HOTSPOT", raising=False)
    monkeypatch.delenv("CERTITHERM_GPU_DEVICE", raising=False)
    assert GpuSelection.from_environment() == GpuSelection(enabled=False, device=0)

    monkeypatch.setenv("CERTITHERM_GPU_HOTSPOT", "1")
    monkeypatch.setenv("CERTITHERM_GPU_DEVICE", "3")
    assert GpuSelection.from_environment() == GpuSelection(enabled=True, device=3)


def test_the_signature_records_the_snapshot_it_is_given_not_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A passed snapshot must win over the live environment, which is what ties the two consumers."""

    monkeypatch.setattr(experiments, "_sha256", lambda _p: "a" * 64)
    monkeypatch.setattr(experiments, "_git_revision", lambda _p: "b" * 40)
    monkeypatch.setattr(experiments, "_verified_binary_digest", lambda *_a: "c" * 64)
    monkeypatch.setenv("CERTITHERM_GPU_HOTSPOT", "0")

    arch = {"architecture_id": "arch_a"}
    package = {"package_id": "default"}
    cpu = experiments._operator_cache_signature(
        arch, package, (), GpuSelection(enabled=False, device=0)
    )
    gpu = experiments._operator_cache_signature(
        arch, package, (), GpuSelection(enabled=True, device=2)
    )
    assert cpu["input_sha256"] != gpu["input_sha256"], (
        "the signature ignored the snapshot, so it cannot be tied to the build"
    )

    # And the environment does NOT override a supplied snapshot.
    monkeypatch.setenv("CERTITHERM_GPU_HOTSPOT", "1")
    monkeypatch.setenv("CERTITHERM_GPU_DEVICE", "7")
    again = experiments._operator_cache_signature(
        arch, package, (), GpuSelection(enabled=False, device=0)
    )
    assert again == cpu, "the live environment leaked past the snapshot"


def test_the_device_reaches_the_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two GPU runs on different devices are different operators and must not share a receipt."""

    monkeypatch.setattr(experiments, "_sha256", lambda _p: "a" * 64)
    monkeypatch.setattr(experiments, "_git_revision", lambda _p: "b" * 40)
    monkeypatch.setattr(experiments, "_verified_binary_digest", lambda *_a: "c" * 64)
    arch = {"architecture_id": "arch_a"}
    package = {"package_id": "default"}
    first = experiments._operator_cache_signature(
        arch, package, (), GpuSelection(enabled=True, device=0)
    )
    second = experiments._operator_cache_signature(
        arch, package, (), GpuSelection(enabled=True, device=1)
    )
    assert first["input_sha256"] != second["input_sha256"]


def test_a_disabled_selection_builds_no_backend() -> None:
    """The backend must follow the snapshot, not the environment, for the same reason."""

    assert experiments._gpu_backend(GpuSelection(enabled=False, device=0)) is None


def test_the_operator_threads_one_snapshot_through_both_consumers() -> None:
    """The wiring itself, asserted, because it is what the whole snapshot exists to guarantee."""

    import inspect

    source = inspect.getsource(experiments._operator)
    assert "_operator_cache_signature(arch, package, captures, gpu)" in source
    assert "_gpu_backend(gpu)" in source
    assert "GpuSelection.from_environment()" not in source, (
        "the operator took its own reading again; the run's snapshot is the only one allowed"
    )
    parameter = inspect.signature(experiments._operator).parameters["gpu"]
    assert parameter.default is inspect.Parameter.empty, (
        "an ambient default lets a caller reintroduce the disagreement without writing anything "
        "that looks wrong"
    )


def test_the_run_receipt_records_the_snapshot_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The receipt must describe what the operators were built under, not a later reading.

    `_run_receipt` read `CERTITHERM_GPU_HOTSPOT` twice and `CERTITHERM_GPU_DEVICE` once on its own,
    so nothing tied the receipt's description to any operator's cache identity, and its two readings
    of the same variable were not tied to each other either.
    """

    from datetime import datetime, timezone

    monkeypatch.setattr(experiments, "_sha256", lambda _p: "a" * 64)
    monkeypatch.setattr(experiments, "_git_revision", lambda _p: "b" * 40)
    monkeypatch.setattr(experiments, "_verified_binary_digest", lambda *_a: "c" * 64)
    monkeypatch.setenv("CERTITHERM_GPU_HOTSPOT", "1")
    monkeypatch.setenv("CERTITHERM_GPU_DEVICE", "9")
    started = datetime.now(timezone.utc)

    cpu = experiments._run_receipt(
        "dev", False, started, "d" * 64, GpuSelection(enabled=False, device=0), "e" * 40, started
    )
    assert cpu["operator_backend"] == "cpu-hotspot", (
        "the live environment leaked past the snapshot"
    )
    assert "gpu_device" not in cpu

    on_two = experiments._run_receipt(
        "dev", False, started, "d" * 64, GpuSelection(enabled=True, device=2), "e" * 40, started
    )
    assert on_two["operator_backend"] == "gpu-proposal+cpu-hotspot-calibration"
    assert on_two["gpu_device"] == "2", "the receipt recorded a device it was not given"


def test_the_run_takes_exactly_one_snapshot_and_shares_it() -> None:
    """One reading for the whole run: every operator identity and the receipt describe the same one."""

    import inspect

    run_source = inspect.getsource(experiments.run)
    assert run_source.count("GpuSelection.from_environment()") == 1, (
        "the run took the GPU snapshot more than once, so its consumers can disagree again"
    )
    assert "gpu=gpu," in run_source, "the operators were not given the run's snapshot"
    assert "_seal_run_artifacts(output, split, frozen, started_at, hotspot_digest, gpu)" in run_source

    sealing = inspect.getsource(experiments._seal_run_artifacts)
    assert "split, frozen, started_at, hotspot_digest, gpu, git_sha, completed_at" in sealing
    assert sealing.index("_assert_repository_unchanged_by_run()") < sealing.index(
        'output / "RUN_RECEIPT.tsv"'
    ), (
        "the integrity gate must run BEFORE the bundle is sealed, or a failed run leaves an output "
        "directory that looks like a complete evidence bundle"
    )
    assert sealing.count("_git_revision(ROOT)") == 1, (
        "the sealing phase read the revision more than once, so RUN_RECEIPT.tsv and ARTIFACTS.tsv "
        "can claim different revisions for one bundle"
    )
    assert "_git_revision(ROOT)" not in run_source, (
        "the revision must be read once, in the phase that records it"
    )
