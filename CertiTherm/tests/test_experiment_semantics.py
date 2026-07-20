from __future__ import annotations

import numpy as np

from CertiTherm.experiments import _ordered_architectures
from CertiTherm.measurements import build_measurement_library, coarse_power_space


def _capture(path, latency: float, energy: float, die_yield: float) -> None:
    np.savez_compressed(
        path,
        latency_ms=np.asarray(latency),
        energy_mj=np.asarray(energy),
        die_yield=np.asarray(die_yield),
    )


def test_candidate_order_is_workload_edyp_not_static_rank(tmp_path) -> None:
    architectures = [
        {"architecture_id": "arch_a", "rank": "0"},
        {"architecture_id": "arch_b", "rank": "1"},
        {"architecture_id": "arch_c", "rank": "2"},
    ]
    captures = {}
    for architecture, edyp in (("arch_a", 9.0), ("arch_b", 2.0), ("arch_c", 5.0)):
        path = tmp_path / f"{architecture}.npz"
        _capture(path, edyp, 1.0, 1.0)
        captures[("workload", architecture)] = path
    ordered = _ordered_architectures("workload", architectures, captures)
    assert [row["architecture_id"] for row in ordered] == [
        "arch_b",
        "arch_c",
        "arch_a",
    ]


def test_unified_eda_library_has_real_cost_levels_and_no_duplicates() -> None:
    blocks = ("alu_0", "alu_1", "sram_0", "sram_1")
    floorplan = "\n".join(
        (
            "alu_0 1 1 0 0",
            "alu_1 1 1 2 0",
            "sram_0 1 1 0 2",
            "sram_1 1 1 2 2",
        )
    )
    architecture = {
        "chiplet_x": "2",
        "chiplet_y": "1",
        "cut_x": "2",
        "cut_y": "1",
    }
    costs = {"module": 1, "chiplet": 2, "placement_region": 4, "post_route": 8}
    actions = build_measurement_library(
        "candidate", blocks, floorplan, architecture, costs
    )
    assert {action.action_id.split("::")[1] for action in actions} >= {
        "module",
        "chiplet",
    }
    assert {action.cost for action in actions} >= {1.0, 2.0}
    supports = [tuple(np.flatnonzero(action.vector)) for action in actions]
    assert len(supports) == len(set(supports))
    assert tuple(range(len(blocks))) not in supports


def test_coarse_observation_reveals_only_total_power() -> None:
    polytope = coarse_power_space(np.array([1.0, 2.0, 3.0]))
    np.testing.assert_array_equal(polytope.a_eq, np.ones((1, 3)))
    np.testing.assert_array_equal(polytope.b_eq, np.array([6.0]))
    np.testing.assert_array_equal(polytope.upper_w, np.full(3, 6.0))
