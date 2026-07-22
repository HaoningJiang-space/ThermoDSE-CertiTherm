"""Native HiGHS deadlines must preserve the outer fail-closed budget."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from CertiTherm.solver_budget import budget_scope, highs_options, run_highs


def test_active_budget_caps_highs_without_dropping_existing_options() -> None:
    with budget_scope(10.0):
        options = highs_options({"mip_rel_gap": 0.0})

    assert options["mip_rel_gap"] == 0.0
    assert 0.0 < float(options["time_limit"]) < 10.0


def test_explicit_tighter_solver_limit_is_preserved() -> None:
    with budget_scope(10.0):
        options = highs_options({"time_limit": 0.25})

    assert options["time_limit"] == pytest.approx(0.25)


def test_native_highs_timeout_has_the_expected_exception_type() -> None:
    def timed_out(*_args, **_kwargs):
        return SimpleNamespace(status=1, message="Time limit reached. (HiGHS)")

    with budget_scope(10.0), pytest.raises(TimeoutError, match="native HiGHS"):
        run_highs(timed_out, label="fixture LP")


def test_solver_receives_a_native_limit_from_the_outer_budget() -> None:
    received = {}

    def solved(*_args, **kwargs):
        received.update(kwargs["options"])
        return SimpleNamespace(status=0, message="optimal")

    with budget_scope(3.0):
        result = run_highs(solved, label="fixture LP")

    assert result.status == 0
    assert 0.0 < float(received["time_limit"]) < 3.0
