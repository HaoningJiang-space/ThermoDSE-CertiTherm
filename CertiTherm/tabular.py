"""Reading and writing the tab-separated tables this project keeps under version control.

Every registry, result table and manifest here is a TSV, and both halves of that had grown a
second implementation: `experiments._rows` read them, while `experiments._write_tsv` and
`gpu_benchmark._write_tsv` wrote them from two copies that were NOT equivalent. The
`experiments` copy took the column order from the union of every row's keys and accepted an
explicit `fieldnames`; the `gpu_benchmark` copy took it from the first row alone and accepted no
override.

The consequence of that difference is a REFUSAL, not a silent truncation -- `csv.DictWriter`
defaults to `extrasaction="raise"`, so the first-row rule rejects a later row carrying a field
the first row omitted. Peer review corrected an earlier version of this docstring which claimed
columns were dropped. Unifying on the union rule therefore turns a raise into a wider table,
which is a behaviour change and the preferable one; `gpu_benchmark`'s three tables build every
row from one literal dict shape inside a single loop, so their output is unchanged byte for byte.

Claim-grade schemas should still pass `fieldnames` explicitly. Union inference is for auxiliary
tables, where discovering the columns is better than pinning a list that can fall out of date.

Layer position: leaf. Imports nothing from this package.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence


def read_rows(path: Path) -> list[dict[str, str]]:
    """Every data row of a TSV, as dicts keyed by the header.

    Values stay strings. Callers that need numbers convert them, because the columns are not
    uniformly typed and a blanket conversion would turn a missing value into a silent zero.
    """

    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def write_rows(
    path: Path,
    rows: Iterable[Mapping[str, object]],
    *,
    fieldnames: Optional[Sequence[str]] = None,
) -> None:
    """Write rows as a TSV, with the column order pinned or taken from every row's keys.

    Columns default to the union of the keys of ALL rows, in first-seen order, not to the first
    row's keys: a later row carrying a field the first row omitted would otherwise be written
    without it and `csv.DictWriter` would raise on the extra key anyway.

    Refuses an empty sequence. A headerless TSV cannot be read back by `read_rows`, so writing
    one would turn "the run produced nothing" into a file that looks like a valid empty table.
    `RuntimeError` rather than `ValueError` because that is what the experiment driver's callers
    already handle.
    """

    materialised = list(rows)
    if not materialised:
        raise RuntimeError("refusing to write empty evidence table")
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = (
        list(fieldnames)
        if fieldnames is not None
        else list(dict.fromkeys(key for row in materialised for key in row))
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(materialised)
