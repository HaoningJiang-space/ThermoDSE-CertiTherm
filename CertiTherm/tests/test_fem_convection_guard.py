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


def test_the_fragment_surviving_only_in_a_COMMENT_does_not_satisfy_the_check(tmp_path) -> None:
    """A tripwire that a comment can satisfy is not a check on the assembly.

    The first version matched `"model->config.r_convec *"` alone, which appears in prose and says
    nothing about the division by cell area -- it would have passed a lumped-node HotSpot.
    """

    for name, fragments in _CONVECTION_ASSEMBLY.items():
        body = "\n".join(f"/* {f} */" for f in fragments)
        (tmp_path / name).write_text(body + "\nint main(void){return 0;}\n")
    with pytest.raises(SystemExit, match="outside comments"):
        _assert_convection_is_distributed(tmp_path)


def test_the_division_itself_must_be_present_not_merely_the_symbol(tmp_path) -> None:
    """`r_convec` appearing somewhere is not evidence that it is divided by cell area."""

    (tmp_path / "temperature_grid.c").write_text(
        "double x = model->config.r_convec * 1.0;  /* a lumped node */\n"
    )
    (tmp_path / "temperature_block.c").write_text(
        "r_amb = r_convec * (s_sink * s_sink) / area;\n"
    )
    with pytest.raises(SystemExit, match="cw \\* ch"):
        _assert_convection_is_distributed(tmp_path)
