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


def _lower(core, event, cuts, endpoint_split=0.5):
    return lower_routed_trace(
        core,
        floorplan=_augmented(),
        events=(event,),
        compute_shape=(2, 1),
        chiplet_cuts=cuts,
        noc_hop_cost_pj=2.0,
        nop_hop_cost_pj=2.0,
        endpoint_split=endpoint_split,
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


# --- component masking for causal isolation ---------------------------------------
# The V6.1 gate needs to attribute one grid-max transient counterexample to a power
# source. Masking gates DEPOSITION only: every route reconciliation receipt is still
# enforced against the full ledger, so a masked run cannot pass on inputs an unmasked
# run would reject.


def _dram_event():
    return {
        "order": 0,
        "kind": "dram_read",
        "destinations": [[0, 0]],
        "dram_locations": [[0, 0], [3, 0]],
        "volume": 4.0,
        "noc_energy_pj": 4.0,
        "nop_energy_pj": 0.0,
        "dram_energy_pj": 10.0,
    }


def _lower_masked(components):
    return lower_routed_trace(
        _core_lowering([4.0, 0.0, 10.0]),
        floorplan=_augmented(),
        events=(_dram_event(),),
        compute_shape=(2, 1),
        chiplet_cuts=(1, 1),
        noc_hop_cost_pj=2.0,
        nop_hop_cost_pj=2.0,
        components=components,
    )


def test_component_split_covers_every_source_and_sums_to_the_full_energy():
    routed = _lower_masked(None)
    assert set(routed.component_energy_j) == {"core", "noc", "nop", "dram"}
    assert routed.component_energy_j["core"] == pytest.approx(5e-12)
    assert routed.component_energy_j["noc"] == pytest.approx(4e-12)
    assert routed.component_energy_j["nop"] == pytest.approx(0.0)
    assert routed.component_energy_j["dram"] == pytest.approx(10e-12)
    assert sum(routed.component_energy_j.values()) == pytest.approx(19e-12)
    assert routed.full_source_energy_j == pytest.approx(19e-12)


def test_unmasked_lowering_is_unchanged_by_the_new_parameter():
    """components=None must reproduce today's behaviour exactly."""
    default = _lower_masked(None)
    explicit = _lower_masked(("core", "noc", "nop", "dram"))
    assert default.retained_components == ("core", "noc", "nop", "dram")
    assert default.source_energy_j == pytest.approx(19e-12)
    assert np.array_equal(default.trace.energy_j(), explicit.trace.energy_j())
    assert default.source_energy_j == pytest.approx(explicit.source_energy_j)


@pytest.mark.parametrize(
    "components,expected_pj",
    [
        (("core",), 5.0),
        (("core", "noc"), 9.0),
        (("core", "dram"), 15.0),
        (("core", "noc", "nop"), 9.0),          # nop is zero in this event
        (("dram",), 10.0),
    ],
)
def test_masked_lowering_conserves_only_the_retained_energy(components, expected_pj):
    routed = _lower_masked(components)
    assert routed.source_energy_j == pytest.approx(expected_pj * 1e-12)
    # the emitted trace must integrate to the RETAINED energy, which is what makes a
    # masked trace replayable; __post_init__ enforces this too
    assert routed.trace.energy_j().sum() == pytest.approx(expected_pj * 1e-12)
    # the full ledger is still reported, so a masked run is comparable with a full one
    assert routed.full_source_energy_j == pytest.approx(19e-12)
    assert sum(routed.component_energy_j.values()) == pytest.approx(19e-12)


def test_masking_a_component_removes_exactly_its_placement():
    """Deposition is gated per component and nothing else moves."""
    full = _lower_masked(None).trace.energy_j()
    no_dram = _lower_masked(("core", "noc", "nop")).trace.energy_j()
    index = {n: i for i, n in enumerate(_lower_masked(None).floorplan.block_ids)}
    assert no_dram[index["dram_x0_y0"]] == pytest.approx(0.0)
    assert no_dram[index["dram_x3_y0"]] == pytest.approx(0.0)
    # every non-DRAM column is untouched
    others = [i for n, i in index.items() if not n.startswith("dram_")]
    assert np.allclose(full[others], no_dram[others])


def test_unknown_or_empty_component_mask_fails_closed():
    with pytest.raises(ValueError, match="unknown power components"):
        _lower_masked(("core", "leakage"))
    with pytest.raises(ValueError, match="at least one component"):
        _lower_masked(())


def test_masking_still_enforces_the_route_reconciliation():
    """A mask must not become a way to skip the receipts that validate the lowering."""
    bad = dict(_dram_event(), noc_energy_pj=99.0)      # disagrees with the monitor ledger
    with pytest.raises(ValueError, match="reconcile"):
        lower_routed_trace(
            _core_lowering([4.0, 0.0, 10.0]),
            floorplan=_augmented(),
            events=(bad,),
            compute_shape=(2, 1),
            chiplet_cuts=(1, 1),
            noc_hop_cost_pj=2.0,
            nop_hop_cost_pj=2.0,
            components=("core",),                      # NoC masked out, still must fail
        )


def _noc_event():
    return {
        "order": 0, "kind": "core_to_core", "source": [0, 0], "destinations": [[1, 0]],
        "dram_locations": [[0, 0], [3, 0]], "volume": 4.0,
        "noc_energy_pj": 8.0, "nop_energy_pj": 0.0, "dram_energy_pj": 0.0,
    }


def test_the_endpoint_split_actually_reaches_the_placement():
    """A knob accepted at the top and dropped on the way down reports a FALSE NEGATIVE.

    `endpoint_split` was added to `lower_routed_trace`'s signature and not threaded to
    `_place_edge_energy`, so a sensitivity sweep over five values produced bit-identical power
    vectors and reported the split's influence as exactly `0.0 K`. That reads as "the modelling
    freedom does not matter" and it is the most dangerous shape a wrong result can take: a
    reassuring number from a disconnected knob. This test asserts the two endpoints move.
    """
    core = _core_lowering([8.0, 0.0, 0.0])
    quarter = _lower(core, _noc_event(), (1, 1), endpoint_split=0.25)
    three_q = _lower(core, _noc_event(), (1, 1), endpoint_split=0.75)
    index = {name: i for i, name in enumerate(quarter.floorplan.block_ids)}
    a, b = index["io_2_0"], index["io_0_1"]

    eq, et = quarter.trace.energy_j(), three_q.trace.energy_j()
    assert eq[a] == pytest.approx(2e-12), "the first endpoint did not take its declared share"
    assert eq[b] == pytest.approx(6e-12), "the second endpoint did not take the complement"
    assert et[a] == pytest.approx(6e-12) and et[b] == pytest.approx(2e-12), (
        "the split did not reverse when the parameter did; it is not wired"
    )
    # Conservation must hold at every split: the parameter moves heat, it does not create it.
    assert eq.sum() == pytest.approx(et.sum())
    assert eq.sum() == pytest.approx(13e-12)


def test_a_split_outside_the_unit_interval_is_refused():
    core = _core_lowering([8.0, 0.0, 0.0])
    for bad in (-0.1, 1.1, float("nan")):
        with pytest.raises(ValueError, match="endpoint_split"):
            _lower(core, _noc_event(), (1, 1), endpoint_split=bad)
