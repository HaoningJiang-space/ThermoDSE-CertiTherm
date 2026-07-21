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
