"""Regressions for name-aligned ptrace handling.

`align_trace` aligns by name rather than by position, which removes the
positional-truncation hazard but silently dropped any column naming no floorplan unit. On
real data that discarded 2.9824 W of 16.6644 W -- all NoP power, in an `interposer` column
with no matching floorplan unit -- while leaving a plausible-looking result.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from CertiTherm.trace_runner import align_trace, floorplan_units, unplaced_power


def _write(tmp_path: Path, floorplan_rows: str, header: str, row: str):
    flp = tmp_path / "f.flp"
    flp.write_text(floorplan_rows, encoding="utf-8")
    src = tmp_path / "p.ptrace"
    src.write_text(f"{header}\n{row}\n", encoding="utf-8")
    return src, flp


def test_unplaced_column_with_power_fails_closed(tmp_path):
    """The real defect: a powered column that no floorplan unit is named after."""
    src, flp = _write(tmp_path,
                      "a\t1\t1\t0\t0\nb\t1\t1\t1\t0\n",
                      "interposer\ta\tb", "2.9824\t1.0\t2.0")
    assert unplaced_power(src, flp) == pytest.approx({"interposer": 2.9824})
    with pytest.raises(ValueError, match="name no floorplan unit"):
        align_trace(src, flp, tmp_path / "out.ptrace")


def test_unplaced_column_may_be_accepted_as_a_declared_boundary(tmp_path):
    src, flp = _write(tmp_path,
                      "a\t1\t1\t0\t0\nb\t1\t1\t1\t0\n",
                      "interposer\ta\tb", "2.9824\t1.0\t2.0")
    dropped = align_trace(src, flp, tmp_path / "out.ptrace", allow_unplaced=True)
    assert dropped == pytest.approx({"interposer": 2.9824})
    out = (tmp_path / "out.ptrace").read_text(encoding="utf-8").splitlines()
    assert out[0].split() == ["a", "b"]              # aligned to floorplan order
    assert out[1].split() == ["1.0", "2.0"]


def test_zero_power_unplaced_column_is_not_an_error(tmp_path):
    """`interposer_e0..e3` are literal zeros; dropping them discards no heat."""
    src, flp = _write(tmp_path,
                      "a\t1\t1\t0\t0\n",
                      "interposer_e0\ta", "0.0000\t1.5")
    assert unplaced_power(src, flp) == {}
    assert align_trace(src, flp, tmp_path / "out.ptrace") == {}


def test_a_column_nonzero_in_any_row_is_caught(tmp_path):
    """Multi-row traces: zero in the first sample must not mask later power."""
    flp = tmp_path / "f.flp"
    flp.write_text("a\t1\t1\t0\t0\n", encoding="utf-8")
    src = tmp_path / "p.ptrace"
    src.write_text("ghost\ta\n0.0000\t1.0\n0.5000\t1.0\n", encoding="utf-8")
    assert unplaced_power(src, flp) == pytest.approx({"ghost": 0.5})
    with pytest.raises(ValueError, match="name no floorplan unit"):
        align_trace(src, flp, tmp_path / "out.ptrace")


def test_missing_floorplan_unit_still_fails(tmp_path):
    """The pre-existing check must keep working: alignment cannot invent a column."""
    src, flp = _write(tmp_path, "a\t1\t1\t0\t0\nmissing\t1\t1\t1\t0\n", "a", "1.0")
    with pytest.raises(ValueError, match="misses 1 floorplan units"):
        align_trace(src, flp, tmp_path / "out.ptrace")


def test_floorplan_units_skips_comments_and_short_rows(tmp_path):
    flp = tmp_path / "f.flp"
    flp.write_text("# comment\n\na\t1\t1\t0\t0\nshort\t1\t1\n", encoding="utf-8")
    assert floorplan_units(flp) == ["a"]
