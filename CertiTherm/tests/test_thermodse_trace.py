"""Tests for the fail-closed ThermoDSE monitor-to-floorplan lowering."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.thermodse_trace import (
    THERMODSE_COMPONENTS,
    lower_monitor_trace,
)


def _blocks(n_cores=2):
    blocks = ["eblk0"]
    for core in range(n_cores):
        blocks.extend(
            f"{prefix}_{core}" for prefix in ("obuf", "vecu", "mtxu", "ibuf", "ubuf")
        )
        blocks.extend(f"io_{side}_{core}" for side in range(4))
    return blocks


def _lower(**overrides):
    # Two orders, two cores, seven components.  Values are pJ and intentionally all
    # distinct enough that a swapped component/core index is observable.
    core = np.arange(1, 2 * 2 * 7 + 1, dtype=float).reshape(2, 2, 7)
    values = {
        "block_ids": _blocks(),
        "latency_cycles": np.array([2.0, 4.0]),
        "core_energy_pj": core,
        "noc_energy_pj": np.array([3.0, 5.0]),
        "nop_energy_pj": np.array([7.0, 11.0]),
        "dram_energy_pj": np.array([13.0, 17.0]),
        "clock_hz": 2.0,
        "component_names": THERMODSE_COMPONENTS,
    }
    values.update(overrides)
    return lower_monitor_trace(**values)


def test_exact_core_mapping_and_energy_identity():
    lowered = _lower()
    blocks = {name: i for i, name in enumerate(lowered.block_ids)}
    energy = lowered.trace.energy_j()
    core = np.arange(1, 29, dtype=float).reshape(2, 2, 7) * 1e-12

    assert energy[blocks["mtxu_0"]] == pytest.approx(core[:, 0, 0].sum())
    assert energy[blocks["vecu_1"]] == pytest.approx(core[:, 1, 1].sum())
    assert energy[blocks["ubuf_0"]] == pytest.approx(core[:, 0, 2].sum())
    assert energy[blocks["ibuf_1"]] == pytest.approx(
        core[:, 1, 3].sum() + core[:, 1, 4].sum()
    )
    assert energy[blocks["obuf_0"]] == pytest.approx(
        core[:, 0, 5].sum() + core[:, 0, 6].sum()
    )
    assert energy[blocks["eblk0"]] == 0.0

    source_j = (np.arange(1, 29).sum() + 3 + 5 + 7 + 11 + 13 + 17) * 1e-12
    assert lowered.thermal_energy_j == pytest.approx(source_j)
    assert lowered.represented_energy_j + lowered.residual_energy_j == pytest.approx(
        source_j
    )


def test_durations_and_power_are_per_order_not_whole_run_averages():
    lowered = _lower()
    assert lowered.trace.durations_s.tolist() == [1.0, 2.0]
    mtxu0 = lowered.block_ids.index("mtxu_0")
    assert lowered.trace.powers_w[:, mtxu0] == pytest.approx([1e-12, 15e-12 / 2])


def test_external_energy_stays_explicit_and_blocks_complete_replay():
    lowered = _lower()
    assert lowered.unplaced_energy_j == pytest.approx(
        np.array([[3.0, 7.0, 13.0], [5.0, 11.0, 17.0]]) * 1e-12
    )
    assert lowered.residual_energy_j > 0.0
    assert not lowered.is_complete
    assert 0.0 < lowered.represented_fraction < 1.0


def test_missing_or_extra_core_blocks_fail_closed():
    with pytest.raises(ValueError, match="missing required core block"):
        _lower(block_ids=[name for name in _blocks() if name != "mtxu_1"])
    with pytest.raises(ValueError, match="not represented by monitor"):
        _lower(block_ids=_blocks() + ["mtxu_2"])


def test_zero_duration_or_bad_component_registry_fails_closed():
    with pytest.raises(ValueError, match="positive duration"):
        _lower(latency_cycles=np.array([2.0, 0.0]))
    with pytest.raises(ValueError, match="component_names"):
        _lower(component_names=("mtxu",) * 7)
