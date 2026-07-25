"""Pure tests for transient time discretization."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.phase_trace import PhaseTrace
from CertiTherm.transient import resample_uniform


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
