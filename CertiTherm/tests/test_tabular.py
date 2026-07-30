"""The one TSV writer must keep the STRONGER of the two behaviours it replaced.

`experiments._write_tsv` and `gpu_benchmark._write_tsv` were not equivalent. The experiments copy
took the column order from the union of every row's keys and accepted an explicit `fieldnames`;
the gpu_benchmark copy used the first row's keys alone.

The difference shows up as a REFUSAL, not a truncation: `csv.DictWriter` defaults to
`extrasaction="raise"`, so the first-row rule rejects a later row carrying a field the first row
omitted. That is verified below rather than asserted in prose, because an earlier version of this
file's docstring claimed columns were silently dropped and peer review corrected it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from CertiTherm.tabular import read_rows, write_rows


def test_the_first_row_rule_would_have_raised_on_a_wider_later_row(tmp_path: Path) -> None:
    """The replaced behaviour, exercised directly, so the docstring above is not taken on trust."""

    import csv

    path = tmp_path / "firstrow.tsv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["a"], delimiter="\t")
        writer.writeheader()
        with pytest.raises(ValueError, match="fields not in fieldnames"):
            writer.writerow({"a": 1, "b": 2})


def test_a_field_only_a_later_row_carries_is_still_a_column(tmp_path: Path) -> None:
    """The whole reason the union behaviour survived the merge."""

    path = tmp_path / "rows.tsv"
    write_rows(path, [{"a": 1}, {"a": 2, "b": 3}])
    header = path.read_text(encoding="utf-8").splitlines()[0].split("\t")
    assert header == ["a", "b"], (
        "the first-row rule would have written only column 'a' and DictWriter would then have "
        "raised on the extra key in row two"
    )
    assert read_rows(path) == [{"a": "1", "b": ""}, {"a": "2", "b": "3"}]


def test_explicit_fieldnames_pin_the_order_and_the_set(tmp_path: Path) -> None:
    """The result tables declare their schema; discovered order is not good enough there."""

    path = tmp_path / "rows.tsv"
    write_rows(path, [{"b": 1, "a": 2}], fieldnames=("a", "b", "c"))
    assert path.read_text(encoding="utf-8").splitlines()[0].split("\t") == ["a", "b", "c"]
    assert read_rows(path) == [{"a": "2", "b": "1", "c": ""}]


def test_writing_no_rows_is_refused(tmp_path: Path) -> None:
    """A headerless TSV reads back as a valid empty table, hiding a run that produced nothing."""

    path = tmp_path / "empty.tsv"
    with pytest.raises(RuntimeError, match="empty evidence table"):
        write_rows(path, [])
    assert not path.exists(), "a refused write must not leave a file behind"


def test_a_round_trip_preserves_every_value_as_text(tmp_path: Path) -> None:
    """Values stay strings on the way back; a blanket cast would make a blank field a zero."""

    path = tmp_path / "rows.tsv"
    write_rows(path, [{"n": 0, "x": 1.5, "s": "", "t": "text"}])
    assert read_rows(path) == [{"n": "0", "x": "1.5", "s": "", "t": "text"}]


def test_both_former_callers_now_resolve_to_this_writer() -> None:
    """Two definitions of one writer is a policing problem; assert there is only one left."""

    from CertiTherm import experiments, gpu_benchmark, tabular

    assert experiments._write_tsv is tabular.write_rows
    assert gpu_benchmark._write_tsv is tabular.write_rows
    assert experiments._rows is tabular.read_rows
