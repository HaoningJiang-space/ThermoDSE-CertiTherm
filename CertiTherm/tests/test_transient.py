"""Pure tests for transient time discretization."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.hotspot import HotSpotModel
from CertiTherm.phase_trace import PhaseTrace
from CertiTherm.transient import (
    OUTPUT_RESOLUTION_K,
    PeriodicTransientResult,
    _parse_steady,
    _peak_and_ties,
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


def test_grid_max_model_is_explicit_not_an_implicit_avg():
    model = HotSpotModel.parse("grid64-max")
    assert model.model_type == "grid"
    assert model.grid_rows == model.grid_cols == 64
    assert model.grid_map_mode == "max"


# --- resolution-aware peak/tie analysis ------------------------------------------------
# A reported argmax block name cannot distinguish a relocated peak from a tie broken
# differently, because HotSpot serialises temperature to 0.01 K. Three of fifteen V6.1
# subsets changed their reported argmax between semantics and the evidence to judge them
# did not exist.

def test_tie_set_holds_every_block_within_one_quantum():
    winner, runner_up, ties = _peak_and_ties(
        np.asarray([320.0, 330.005, 330.01, 330.002, 329.998]),
        ("a", "b", "c", "d", "e"),
        OUTPUT_RESOLUTION_K,
    )
    assert winner == 2                                   # 330.01 is the maximum
    assert runner_up == pytest.approx(330.005)
    assert set(ties) == {"b", "c", "d"}                  # all within 0.01 K of the peak
    assert ties[0] == "c", "the tie set must be ordered hottest first"
    assert "a" not in ties
    assert "e" not in ties, "0.012 K below the peak is outside the quantum"


def test_a_resolvable_peak_has_a_singleton_tie_set():
    winner, runner_up, ties = _peak_and_ties(
        np.asarray([300.0, 330.5]), ("cool", "hot"), OUTPUT_RESOLUTION_K
    )
    assert winner == 1 and ties == ("hot",)
    assert runner_up == pytest.approx(300.0)


def test_peak_and_ties_refuses_a_mismatched_block_list():
    with pytest.raises(ValueError, match="does not match the block list"):
        _peak_and_ties(np.asarray([1.0, 2.0]), ("only_one",), OUTPUT_RESOLUTION_K)


def test_output_resolution_is_named_once():
    """The convergence guard and the tie analysis must use the same quantum, or a run could
    claim convergence at a resolution finer than the one it calls a tie."""
    assert OUTPUT_RESOLUTION_K == 0.01
    assert PeriodicTransientResult.__dataclass_fields__[
        "temperature_output_resolution_k"].default == OUTPUT_RESOLUTION_K


def test_invocation_count_has_no_default():
    """A default of 0 would let a caller print a fabricated count as if it were measured."""
    import dataclasses
    field = PeriodicTransientResult.__dataclass_fields__["hotspot_invocations"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING


def test_the_tie_set_order_is_stable_and_documented():
    """Exact ties are the common case (11 of 15 V6.1 subsets), and an unstable sort left
    their order arbitrary. Hottest first, then block order among equal values."""
    winner, _, ties = _peak_and_ties(
        np.asarray([330.0, 330.0, 330.0, 320.0]), ("d", "c", "b", "a"), OUTPUT_RESOLUTION_K
    )
    assert winner == 0, "argmax takes the first maximum in block order"
    assert ties == ("d", "c", "b"), "block order among exact ties, not an arbitrary permutation"
