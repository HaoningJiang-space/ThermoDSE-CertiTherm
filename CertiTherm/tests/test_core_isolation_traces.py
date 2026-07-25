"""The scheduled/flat contract the causal-isolation gate rests on.

The whole gate is "same energy, same duration, different shape". If either trace loses
energy or duration in construction or in serialisation, the comparison measures the
bookkeeping instead of the physics -- and would still produce a plausible number.

`PhaseTrace` carries no block identity: it holds `durations_s` and `powers_w` only, and the
block names go to `replay_periodic` separately. So "columns line up" cannot be asserted on
the trace object; it has to be asserted as `dimension == len(block_ids)` together with the
alignment being built FROM the floorplan names.
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.phase_trace import PhaseTrace
from CertiTherm.transient import resample_uniform


def _scheduled():
    """Uneven durations spanning ~160x, like the real per-order trace."""
    dur = np.array([3.828e-07, 6.241e-05, 1.5e-05, 4.0e-06])
    powers = np.array([[8.0, 0.0, 1.0],
                       [1.0, 4.0, 0.5],
                       [0.0, 0.0, 6.0],
                       [2.0, 2.0, 2.0]])
    return PhaseTrace(dur, powers)


def _flat_of(trace: PhaseTrace) -> PhaseTrace:
    return PhaseTrace(np.asarray([trace.total_time_s]), trace.mean_power_w[None, :])


def test_flat_shares_duration_and_per_block_energy_exactly():
    s = _scheduled()
    f = _flat_of(s)
    assert f.total_time_s == pytest.approx(s.total_time_s, rel=0, abs=0)
    assert f.energy_j() == pytest.approx(s.energy_j(), rel=1e-15)
    assert f.mean_power_w == pytest.approx(s.mean_power_w, rel=1e-15)


def test_flat_differs_in_shape_which_is_the_whole_point():
    s = _scheduled()
    f = _flat_of(s)
    assert s.n_phases > 1 and f.n_phases == 1
    assert not np.allclose(s.peak_power_w, f.peak_power_w)


def test_resampling_conserves_per_block_energy_for_both_traces():
    """resample_uniform validates internally and raises; assert it does not raise and
    that the returned samples still integrate to the source energy."""
    s = _scheduled()
    f = _flat_of(s)
    for trace in (s, f):
        step, samples = resample_uniform(trace, max_step_s=0.25e-6)
        assert samples.shape[1] == trace.dimension
        assert step * samples.shape[0] == pytest.approx(trace.total_time_s, rel=1e-12)
        assert samples.sum(axis=0) * step == pytest.approx(trace.energy_j(), rel=1e-11)


def test_resampled_energy_still_matches_between_the_two_traces():
    """The comparison's precondition survives resampling, not just construction."""
    s, f = _scheduled(), _flat_of(_scheduled())
    step_s, samp_s = resample_uniform(s, max_step_s=0.25e-6)
    step_f, samp_f = resample_uniform(f, max_step_s=0.25e-6)
    assert samp_s.sum(axis=0) * step_s == pytest.approx(
        samp_f.sum(axis=0) * step_f, rel=1e-11)


def test_a_short_phase_is_not_dropped_by_coarse_resampling():
    """The shortest real order is ~0.38 us. A step coarser than it must still carry its
    energy, because fractional overlaps are averaged rather than rounded away."""
    s = _scheduled()
    _, samples = resample_uniform(s, max_step_s=10e-6)      # ~26x the shortest phase
    assert samples.shape[0] >= 1
    step, samples = resample_uniform(s, max_step_s=10e-6)
    assert samples.sum(axis=0) * step == pytest.approx(s.energy_j(), rel=1e-11)


def test_dimension_is_how_column_identity_must_be_asserted():
    """PhaseTrace has no block_ids, so the alignment contract is dimension plus building
    the column order FROM the floorplan names."""
    s = _scheduled()
    assert not hasattr(s, "block_ids")
    block_ids = ("a", "b", "c")
    assert s.dimension == len(block_ids)


def test_zero_length_phase_is_rejected_before_it_can_divide_by_zero():
    with pytest.raises(ValueError):
        PhaseTrace(np.array([1.0, 0.0]), np.array([[1.0], [1.0]]))
