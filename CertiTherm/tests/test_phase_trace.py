"""Tests for the phase-trace IR and the schedule-reachable power set."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.phase_trace import (
    PhaseTrace, ScheduleSpace, TaskSpec, box_polytope, tightening_report,
)


def _tasks():
    return (
        TaskSpec("a", np.array([4.0, 0.0]), 1.0, "chiplet0"),
        TaskSpec("b", np.array([0.0, 4.0]), 1.0, "chiplet1"),
        TaskSpec("c", np.array([3.0, 3.0]), 2.0, "chiplet0"),
    )


def test_task_rejects_negative_and_nonfinite_power():
    with pytest.raises(ValueError):
        TaskSpec("a", np.array([-1.0, 0.0]), 1.0, "r")
    with pytest.raises(ValueError):
        TaskSpec("a", np.array([np.nan, 0.0]), 1.0, "r")
    with pytest.raises(ValueError):
        TaskSpec("a", np.array([1.0]), 0.0, "r")


def test_precedence_cycle_is_rejected():
    t = _tasks()
    with pytest.raises(ValueError, match="cycle"):
        ScheduleSpace(t, precedence=(("a", "b"), ("b", "a")))


def test_unknown_task_in_precedence_is_rejected():
    with pytest.raises(ValueError, match="unknown task"):
        ScheduleSpace(_tasks(), precedence=(("a", "zzz"),))


def test_resource_exclusion_forbids_overlap():
    """`a` and `c` share chiplet0 at capacity 1, so they may never be concurrent."""
    space = ScheduleSpace(_tasks())
    sets = list(space.concurrent_sets())
    assert frozenset({"a", "c"}) not in sets
    assert frozenset({"a", "b"}) in sets          # different resources may overlap
    assert frozenset() in sets                    # an idle instant is reachable


def test_capacity_allows_overlap_when_raised():
    space = ScheduleSpace(_tasks(), capacity={"chiplet0": 2})
    assert frozenset({"a", "c"}) in list(space.concurrent_sets())


def test_precedence_forbids_overlap_transitively():
    """An indirect successor may not overlap its ancestor either."""
    tasks = (
        TaskSpec("a", np.array([1.0, 0.0]), 1.0, "r0"),
        TaskSpec("b", np.array([0.0, 1.0]), 1.0, "r1"),
        TaskSpec("c", np.array([1.0, 1.0]), 1.0, "r2"),
    )
    space = ScheduleSpace(tasks, precedence=(("a", "b"), ("b", "c")))
    sets = list(space.concurrent_sets())
    assert frozenset({"a", "b"}) not in sets
    assert frozenset({"a", "c"}) not in sets      # transitive: a -> b -> c


def test_reachable_points_are_sums_of_concurrent_tasks():
    space = ScheduleSpace(_tasks())
    pts = {tuple(row) for row in space.reachable_points_w()}
    assert (0.0, 0.0) in pts                      # idle
    assert (4.0, 4.0) in pts                      # a || b
    assert (3.0, 7.0) in pts                      # c || b
    assert (7.0, 3.0) not in pts                  # a || c is illegal (shared resource)


def test_reachable_set_is_strictly_tighter_than_the_box():
    """The point of the module: the box admits power no legal execution reaches."""
    space = ScheduleSpace(_tasks())
    rep = tightening_report(space)
    assert rep["reachable_total_w"] < rep["box_total_w"]
    assert rep["total_w_ratio"] < 1.0
    # the box permits per-block maxima simultaneously: 4 + 7 = 11 W
    assert box_polytope(space).upper_w.tolist() == [4.0, 7.0]
    # but the best legal concurrent total is c || b = 3 + 7 = 10 W
    assert rep["reachable_total_w"] == pytest.approx(10.0)


def test_structural_envelope_contains_every_reachable_point():
    """Soundness of the over-approximation: nothing physical is excluded."""
    space = ScheduleSpace(_tasks())
    poly = space.structural_envelope()
    for row in space.reachable_points_w():
        assert np.all(row >= poly.lower_w - 1e-12)
        assert np.all(row <= poly.upper_w + 1e-12)
        assert poly.a_ub @ row <= poly.b_ub + 1e-12


def test_enumeration_refuses_rather_than_truncating():
    """Missing a concurrent set could hide a collision, so it must fail closed."""
    from CertiTherm import phase_trace as pt
    tasks = tuple(TaskSpec(f"t{i}", np.array([1.0, 1.0]), 1.0, f"r{i}") for i in range(20))
    space = ScheduleSpace(tasks)
    original = pt.MAX_CONCURRENT_SETS
    try:
        pt.MAX_CONCURRENT_SETS = 10
        with pytest.raises(ValueError, match="refusing to enumerate"):
            list(space.concurrent_sets())
    finally:
        pt.MAX_CONCURRENT_SETS = original


def test_phase_trace_mean_is_all_a_steady_model_sees():
    trace = PhaseTrace(np.array([1.0, 3.0]), np.array([[8.0, 0.0], [0.0, 4.0]]))
    assert trace.total_time_s == pytest.approx(4.0)
    assert trace.mean_power_w == pytest.approx([2.0, 3.0])
    assert trace.peak_power_w == pytest.approx([8.0, 4.0])
    assert trace.energy_j() == pytest.approx([8.0, 12.0])


def test_two_traces_can_share_a_mean_yet_differ_in_shape():
    """The premise the transient work rests on: equal time-weighted mean power, so a
    steady-state abstraction sees ONE world, while the traces are distinct."""
    flat = PhaseTrace(np.array([2.0, 2.0]), np.array([[3.0, 3.0], [3.0, 3.0]]))
    bursty = PhaseTrace(np.array([2.0, 2.0]), np.array([[6.0, 0.0], [0.0, 6.0]]))
    assert flat.mean_power_w == pytest.approx(bursty.mean_power_w)
    assert flat.peak_power_w.tolist() != bursty.peak_power_w.tolist()
    assert flat.energy_j() == pytest.approx(bursty.energy_j())


def test_phase_trace_validates_shape_and_sign():
    with pytest.raises(ValueError):
        PhaseTrace(np.array([1.0, 2.0]), np.array([[1.0, 1.0]]))     # phase count mismatch
    with pytest.raises(ValueError):
        PhaseTrace(np.array([-1.0]), np.array([[1.0]]))              # negative duration
    with pytest.raises(ValueError):
        PhaseTrace(np.array([1.0]), np.array([[-1.0]]))              # negative power
