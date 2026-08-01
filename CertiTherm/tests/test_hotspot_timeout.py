"""The solve timeout is a hung-process guard, not a physical bound, so it has to move with the grid."""

from __future__ import annotations

import pytest

from CertiTherm.hotspot import _solve_timeout_s


def test_the_default_timeout_is_the_historical_value() -> None:
    assert _solve_timeout_s() == 300.0


def test_the_timeout_is_overridable_because_a_finer_grid_legitimately_takes_longer(monkeypatch) -> None:
    """A `grid512` build on the CPU reference exceeded 300 s for a 43-block design and was recorded
    as UNRESOLVED. That is fail-closed and correct, but the guard was hard-coded so the only way to
    finish the design was to edit the source."""

    monkeypatch.setenv("CERTITHERM_HOTSPOT_TIMEOUT_S", "1800")
    assert _solve_timeout_s() == 1800.0


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "soon"])
def test_a_timeout_that_is_not_a_positive_finite_number_refuses(monkeypatch, value) -> None:
    """`inf` would disable the guard entirely and a hung solve would hang the run forever."""

    monkeypatch.setenv("CERTITHERM_HOTSPOT_TIMEOUT_S", value)
    with pytest.raises(ValueError, match="CERTITHERM_HOTSPOT_TIMEOUT_S"):
        _solve_timeout_s()
