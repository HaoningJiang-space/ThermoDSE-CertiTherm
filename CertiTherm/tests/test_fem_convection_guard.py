"""The FEM's uniform Robin coefficient is only equivalent while HotSpot divides `r_convec` by area.

Nothing checked this, and the omission nearly cost a valid result: `r_convec` is named like a lumped
resistance and documented as "sink-to-ambient", so two rounds of analysis treated the name as the
specification, built an exact lumped-node FEM to "separate" a term that does not exist, and withdrew
a headline. `temperature_grid.c` and `temperature_block.c` both divide by cell area, which IS the
uniform Robin already in use.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RESEARCH = Path(__file__).resolve().parents[2] / "research" / "triangle" / "robustness"
sys.path.insert(0, str(_RESEARCH))

from fem_reference import _CONVECTION_ASSEMBLY, _assert_convection_is_distributed  # noqa: E402

_HOTSPOT_SOURCE = Path(__file__).resolve().parents[2] / "HotSpot"


def test_the_pinned_hotspot_still_distributes_the_convective_resistance() -> None:
    """The live check, against the real submodule. If this fails the band changed meaning."""

    found = _assert_convection_is_distributed(_HOTSPOT_SOURCE)
    assert set(found) == set(_CONVECTION_ASSEMBLY)


def test_a_hotspot_without_that_assembly_is_refused(tmp_path) -> None:
    """Fail CLOSED on a re-pin: refuse rather than silently measuring a boundary condition."""

    for name in _CONVECTION_ASSEMBLY:
        (tmp_path / name).write_text("/* a lumped node, with no per-area division */\n")
    with pytest.raises(SystemExit, match="no longer contains"):
        _assert_convection_is_distributed(tmp_path)


def test_a_missing_source_file_is_refused_rather_than_skipped(tmp_path) -> None:
    """An absent file is not evidence of agreement."""

    with pytest.raises(SystemExit, match="cannot be checked"):
        _assert_convection_is_distributed(tmp_path)
