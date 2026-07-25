"""Tests for route-aware complete ThermoDSE trace lowering."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.phase_trace import PhaseTrace
from CertiTherm.routed_trace import (
    augment_floorplan_with_dram,
    lower_routed_trace,
)
from CertiTherm.thermodse_trace import ThermoDSETraceLowering


def _floorplan_2x1():
    # Only the names/adjacency targets needed by the lowering; geometry is a complete
    # 2 m x 1 m rectangle for easy receipt checks.
    return "\n".join(
        (
            "mtxu_0 0.2 0.4 0.0 0.0",
            "io_0_0 0.1 1.0 0.2 0.0",
            "io_1_0 0.2 0.1 0.3 0.0",
            "io_2_0 0.1 1.0 0.5 0.0",
            "io_3_0 0.2 0.1 0.3 0.9",
            "blockX_0 0.8 1.0 0.6 0.0",
            "mtxu_1 0.2 0.4 1.4 0.0",
            "io_0_1 0.1 1.0 1.6 0.0",
            "io_1_1 0.2 0.1 1.7 0.0",
            "io_2_1 0.1 1.0 1.9 0.0",
            "io_3_1 0.2 0.1 1.7 0.9",
        )
    ) + "\n"


def _core_lowering(external_pj):
    blocks = tuple(line.split()[0] for line in _floorplan_2x1().splitlines())
    powers = np.zeros((1, len(blocks)))
    powers[0, blocks.index("mtxu_0")] = 2e-12
    powers[0, blocks.index("mtxu_1")] = 3e-12
    return ThermoDSETraceLowering(
        block_ids=blocks,
        trace=PhaseTrace(np.array([1.0]), powers),
        unplaced_energy_j=np.asarray([external_pj], dtype=float) * 1e-12,
    )


def _lower(core, event, cuts):
    return lower_routed_trace(
        core,
        floorplan=_augmented(),
        events=(event,),
        compute_shape=(2, 1),
        chiplet_cuts=cuts,
        noc_hop_cost_pj=2.0,
        nop_hop_cost_pj=2.0,
    )


def _augmented():
    return augment_floorplan_with_dram(
        _floorplan_2x1(),
        io_die_area_each_m2=0.01,
        dram_locations=((0, 0), (3, 0)),
        compute_shape=(2, 1),
    )


def test_augmentation_preserves_names_and_io_die_area():
    augmented = _augmented()
    assert set(_core_lowering([0, 0, 0]).block_ids).issubset(augmented.block_ids)
    assert set(augmented.dram_blocks) == {(0, 0), (3, 0)}
    rows = {
        fields[0]: tuple(float(value) for value in fields[1:5])
        for line in augmented.text.splitlines()
        if (fields := line.split())
    }
    for name in augmented.dram_blocks.values():
        width, height, _, _ = rows[name]
        assert width * height == pytest.approx(0.01)
        assert width == pytest.approx(height)
    # Original x=0 block is shifted by one square-die side.
    assert rows["mtxu_0"][2] == pytest.approx(0.1)


def test_augmentation_exposes_equal_area_aspect_ratio_sensitivity():
    augmented = augment_floorplan_with_dram(
        _floorplan_2x1(),
        io_die_area_each_m2=0.01,
        dram_locations=((0, 0), (3, 0)),
        compute_shape=(2, 1),
        io_die_aspect_ratio=4.0,
    )
    rows = {
        fields[0]: tuple(float(value) for value in fields[1:5])
        for line in augmented.text.splitlines()
        if (fields := line.split())
    }
    width, height, _, _ = rows["dram_x0_y0"]
    assert width / height == pytest.approx(4.0)
    assert width * height == pytest.approx(0.01)
    assert augmented.io_die_aspect_ratio == pytest.approx(4.0)


def test_augmentation_rejects_overlapping_source_floorplan():
    bad = _floorplan_2x1() + "overlap 0.1 0.1 0.05 0.05\n"
    with pytest.raises(ValueError, match="overlap"):
        augment_floorplan_with_dram(
            bad,
            io_die_area_each_m2=0.01,
            dram_locations=((0, 0), (3, 0)),
            compute_shape=(2, 1),
        )


def test_same_chiplet_noc_energy_splits_facing_io_blocks():
    core = _core_lowering([8.0, 0.0, 0.0])
    event = {
        "order": 0,
        "kind": "core_to_core",
        "source": [0, 0],
        "destinations": [[1, 0]],
        "dram_locations": [[0, 0], [3, 0]],
        "volume": 4.0,
        "noc_energy_pj": 8.0,
        "nop_energy_pj": 0.0,
        "dram_energy_pj": 0.0,
    }
    routed = _lower(core, event, (1, 1))
    energy = routed.trace.energy_j()
    index = {name: i for i, name in enumerate(routed.floorplan.block_ids)}
    assert energy[index["io_2_0"]] == pytest.approx(4e-12)
    assert energy[index["io_0_1"]] == pytest.approx(4e-12)
    assert energy.sum() == pytest.approx(13e-12)


def test_cross_chiplet_nop_energy_goes_to_gap_block():
    core = _core_lowering([0.0, 6.0, 0.0])
    event = {
        "order": 0,
        "kind": "core_to_core",
        "source": [0, 0],
        "destinations": [[1, 0]],
        "dram_locations": [[0, 0], [3, 0]],
        "volume": 3.0,
        "noc_energy_pj": 0.0,
        "nop_energy_pj": 6.0,
        "dram_energy_pj": 0.0,
    }
    routed = _lower(core, event, (2, 1))
    energy = routed.trace.energy_j()
    index = {name: i for i, name in enumerate(routed.floorplan.block_ids)}
    assert energy[index["blockX_0"]] == pytest.approx(6e-12)


def test_dram_read_places_access_energy_and_conserves_all_sources():
    core = _core_lowering([4.0, 0.0, 10.0])
    event = {
        "order": 0,
        "kind": "dram_read",
        "destinations": [[0, 0]],
        "dram_locations": [[0, 0], [3, 0]],
        "volume": 4.0,
        "noc_energy_pj": 4.0,
        "nop_energy_pj": 0.0,
        "dram_energy_pj": 10.0,
    }
    routed = _lower(core, event, (1, 1))
    energy = routed.trace.energy_j()
    index = {name: i for i, name in enumerate(routed.floorplan.block_ids)}
    # 5 pJ DRAM access on each die.  The external PHY edge has no separately
    # characterized energy in ThermoDSE and is therefore not invented here.
    assert energy[index["dram_x0_y0"]] == pytest.approx(5e-12)
    assert energy[index["dram_x3_y0"]] == pytest.approx(5e-12)
    assert energy.sum() == pytest.approx((2 + 3 + 4 + 10) * 1e-12)


def test_event_ledger_mismatch_fails_closed():
    core = _core_lowering([0.0, 7.0, 0.0])
    event = {
        "order": 0,
        "kind": "core_to_core",
        "source": [0, 0],
        "destinations": [[1, 0]],
        "dram_locations": [[0, 0], [3, 0]],
        "volume": 3.0,
        "noc_energy_pj": 0.0,
        "nop_energy_pj": 6.0,
        "dram_energy_pj": 0.0,
    }
    with pytest.raises(ValueError, match="do not reconcile"):
        lower_routed_trace(
            core,
            floorplan=_augmented(),
            events=(event,),
            compute_shape=(2, 1),
            chiplet_cuts=(2, 1),
            noc_hop_cost_pj=2.0,
            nop_hop_cost_pj=2.0,
        )


def test_legacy_boundary_channel_mismatch_fails_closed():
    core = _core_lowering([6.0, 0.0, 0.0])
    event = {
        "order": 0,
        "kind": "core_to_core",
        "source": [0, 0],
        "destinations": [[1, 0]],
        "dram_locations": [[0, 0], [3, 0]],
        "volume": 3.0,
        # This is the known ThermoDSE boundary error: the adjacent cross-chiplet
        # edge was charged at the NoC cost.
        "noc_energy_pj": 6.0,
        "nop_energy_pj": 0.0,
        "dram_energy_pj": 0.0,
    }
    with pytest.raises(ValueError, match="physical route energy"):
        lower_routed_trace(
            core,
            floorplan=_augmented(),
            events=(event,),
            compute_shape=(2, 1),
            chiplet_cuts=(2, 1),
            noc_hop_cost_pj=2.0,
            nop_hop_cost_pj=5.0,
        )
