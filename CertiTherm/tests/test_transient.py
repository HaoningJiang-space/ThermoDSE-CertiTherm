"""Pure tests for transient time discretization."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.phase_trace import PhaseTrace
from CertiTherm.transient import (
    _parse_steady,
    _within_output_tolerance,
    replay_periodic,
    resample_uniform,
)


def test_uniform_resampling_preserves_each_block_energy():
    trace = PhaseTrace(
        np.asarray([0.3, 0.7]),
        np.asarray([[2.0, 0.0], [0.0, 3.0]]),
    )
    step, powers = resample_uniform(trace, 0.4)
    assert step == pytest.approx(1.0 / 3.0)
    assert powers.shape == (3, 2)
    assert powers.sum(axis=0) * step == pytest.approx([0.6, 2.1])


def test_uniform_resampling_rejects_bad_step():
    trace = PhaseTrace(np.asarray([1.0]), np.asarray([[1.0]]))
    with pytest.raises(ValueError, match="positive"):
        resample_uniform(trace, 0.0)


def test_periodic_replay_rejects_subresolution_convergence(tmp_path):
    trace = PhaseTrace(np.asarray([1.0]), np.asarray([[1.0]]))
    with pytest.raises(ValueError, match="output resolution"):
        replay_periodic(
            binary=tmp_path / "missing",
            config=tmp_path / "missing",
            floorplan=tmp_path / "missing",
            materials=tmp_path / "missing",
            model_id="block",
            block_ids=("x",),
            trace=trace,
            workspace=tmp_path,
            max_step_s=1.0,
            fixed_initial_k=318.15,
            tolerance_k=0.001,
        )


def test_steady_parser_aligns_by_block_name(tmp_path):
    path = tmp_path / "mean.steady"
    path.write_text("internal_0 999\nb 322.5\na 321.0\n", encoding="utf-8")
    assert _parse_steady(path, ("a", "b")) == pytest.approx([321.0, 322.5])


def test_decimal_output_resolution_has_only_numeric_slack():
    assert _within_output_tolerance(0.010000000000047748, 0.01)
    assert not _within_output_tolerance(0.01001, 0.01)
