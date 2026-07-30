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
    assert "gpu = GpuSelection.from_environment()" in source
    assert "_operator_cache_signature(arch, package, captures, gpu)" in source
    assert "_gpu_backend(gpu)" in source
    assert source.count("GpuSelection.from_environment()") == 1, (
        "the operator took the snapshot more than once, which reopens the disagreement"
    )
