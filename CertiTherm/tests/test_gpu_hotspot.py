import struct

import numpy as np
import pytest

from CertiTherm.gpu_benchmark import _read_placed_power, _thermal_state
from CertiTherm.gpu_hotspot import (
    GpuHotSpotBackend,
    _read_output,
    _require_linear_config,
)


def test_gpu_output_parser_preserves_block_rhs_layout(tmp_path):
    path = tmp_path / "temperatures.bin"
    values = np.arange(12, dtype="<f8").reshape(3, 4)
    header = struct.pack("<8sIIQQQdd", b"CTHGO01\0", 1, 8, 3, 4, 17, 1e-13, 2.5)
    path.write_bytes(header + values.tobytes())
    parsed, iterations, residual, solve_ms = _read_output(path)
    assert np.array_equal(parsed, values)
    assert iterations == 17
    assert residual == pytest.approx(1e-13)
    assert solve_ms == pytest.approx(2.5)


def test_gpu_output_parser_rejects_truncation(tmp_path):
    path = tmp_path / "temperatures.bin"
    header = struct.pack("<8sIIQQQdd", b"CTHGO01\0", 1, 8, 3, 4, 17, 1e-13, 2.5)
    path.write_bytes(header + np.zeros(11, dtype="<f8").tobytes())
    with pytest.raises(RuntimeError, match="payload"):
        _read_output(path)


def test_gpu_backend_rejects_unsafe_controls(tmp_path):
    with pytest.raises(ValueError, match="device"):
        GpuHotSpotBackend(tmp_path / "exporter", tmp_path / "solver", device=-1)
    with pytest.raises(ValueError, match="tolerance"):
        GpuHotSpotBackend(
            tmp_path / "exporter",
            tmp_path / "solver",
            relative_tolerance=0,
        )


@pytest.mark.parametrize("flag", ("-leakage_used", "-package_model_used"))
def test_gpu_backend_rejects_nonlinear_hotspot_modes(tmp_path, flag):
    config = tmp_path / "hotspot.config"
    config.write_text(f"{flag} 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match=flag):
        _require_linear_config(config)


def test_gpu_backend_accepts_fixed_linear_hotspot_config(tmp_path):
    config = tmp_path / "hotspot.config"
    config.write_text(
        "-leakage_used 0 # fixed power\n-package_model_used 0\n",
        encoding="utf-8",
    )
    _require_linear_config(config)


def test_placed_power_trace_requires_exact_registry(tmp_path):
    trace = tmp_path / "power.ptrace"
    trace.write_text("a\tb\n1.5\t2.5\n", encoding="utf-8")
    assert np.array_equal(_read_placed_power(trace, ("a", "b")), [1.5, 2.5])
    with pytest.raises(RuntimeError, match="registry"):
        _read_placed_power(trace, ("b", "a"))


def test_gpu_decision_gate_is_conservative_and_fail_closed():
    assert _thermal_state(329.0) == "SAFE"
    assert _thermal_state(331.0) == "REJECT"
    assert _thermal_state(330.0 - 0.01) == "NUMERICAL_GAP"


def test_the_gpu_build_root_moves_the_solver_the_exporter_and_the_receipt_together(monkeypatch, tmp_path) -> None:
    """A rebuilt solver must not be pairable with the pinned build's receipt.

    The three paths were independent constants, so testing a rebuilt CUDA solver meant editing the
    source -- and overriding only the solver path would have verified a new binary against an old
    `GPU_SHA256SUMS`, which is the false-hit direction the digest check exists to prevent. One root
    makes that combination unrepresentable.
    """

    import importlib

    monkeypatch.setenv("CERTITHERM_GPU_BUILD_ROOT", str(tmp_path))
    module = importlib.reload(importlib.import_module("CertiTherm.experiments"))
    try:
        # `is_relative_to` is 3.9+; the pinned interpreter is python3.8.
        assert module.GPU_BUILD_ROOT == tmp_path
        for path in (
            module.GPU_HOTSPOT_SOLVER, module.GPU_HOTSPOT_EXPORTER, module.GPU_HOTSPOT_BUILD
        ):
            assert str(path).startswith(str(tmp_path)), path
    finally:
        monkeypatch.delenv("CERTITHERM_GPU_BUILD_ROOT")
        importlib.reload(module)


def test_the_grid_reader_refuses_a_foreign_or_truncated_file(tmp_path) -> None:
    """The raw grid is a second output in its own format; a wrong one must not be read as numbers."""

    import struct

    from CertiTherm.gpu_hotspot import _GRID_HEADER, _read_grid

    good = tmp_path / "grid.bin"
    good.write_bytes(_GRID_HEADER.pack(b"CTHGG01", 1, 8, 2, 3) + np.zeros(6).tobytes())
    assert _read_grid(good, 3).shape == (2, 3)

    wrong_magic = tmp_path / "wrong.bin"
    wrong_magic.write_bytes(_GRID_HEADER.pack(b"CTHGO01", 1, 8, 2, 3) + np.zeros(6).tobytes())
    with pytest.raises(RuntimeError, match="unsupported"):
        _read_grid(wrong_magic, 3)

    short = tmp_path / "short.bin"
    short.write_bytes(_GRID_HEADER.pack(b"CTHGG01", 1, 8, 2, 3) + np.zeros(4).tobytes())
    with pytest.raises(RuntimeError, match="expected"):
        _read_grid(short, 3)

    with pytest.raises(RuntimeError, match="right-hand sides"):
        _read_grid(good, 4)


def test_a_non_finite_grid_is_refused_rather_than_returned(tmp_path) -> None:
    """A NaN cell would become a NaN row in a cell operator and pass every `>` guard downstream."""

    from CertiTherm.gpu_hotspot import _GRID_HEADER, _read_grid

    poisoned = np.zeros(6)
    poisoned[2] = np.nan
    path = tmp_path / "nan.bin"
    path.write_bytes(_GRID_HEADER.pack(b"CTHGG01", 1, 8, 2, 3) + poisoned.tobytes())
    with pytest.raises(RuntimeError, match="non-finite"):
        _read_grid(path, 3)


def test_a_negative_refinement_budget_is_refused(tmp_path) -> None:
    from pathlib import Path

    from CertiTherm.gpu_hotspot import GpuHotSpotBackend

    exporter, solver = tmp_path / "hotspot", tmp_path / "solver"
    exporter.write_text("x")
    solver.write_text("y")
    with pytest.raises(ValueError, match="cannot be negative"):
        GpuHotSpotBackend(Path(exporter), Path(solver), max_refinements=-1)
