import struct

import numpy as np
import pytest

from CertiTherm.gpu_hotspot import GpuHotSpotBackend, _read_output


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
