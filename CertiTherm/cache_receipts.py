"""The receipt that decides whether an expensive artifact may be reused.

A cached capture or thermal operator is only reusable if everything that went into building it is
unchanged. That is what a receipt records: a content digest of the inputs, a digest of the source
that built them, and a digest of the artifact itself. `receipt_matches` recomputes all three and
compares the whole row, so a single differing field is a miss.

**The dangerous direction is a false HIT, not a false miss.** A false miss wastes a HotSpot
rebuild. A false hit reuses an operator built from different captures, binaries, materials, limits
or source logic, and the results downstream are then internally consistent while corresponding to
the wrong thermal operator -- which can enter claim-grade evidence unnoticed. Every comparison here
is therefore exact and total: no tolerances, no subset matching, no ignoring unknown columns.

`sha256_file` is injected rather than imported. It is the seam the tests replace to check that a
signature responds to its inputs, and injecting it keeps that seam working regardless of which
module a caller lives in -- a re-exported alias does not, because Python resolves a function's
globals where it was DEFINED. The callers in `experiments` pass their own module-level `_sha256`,
so `monkeypatch.setattr(experiments, "_sha256", ...)` still takes effect through them.

Layer position: depends on the `tabular` leaf and on nothing else in this package.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from .tabular import read_rows, write_rows

# Bumped when the receipt row's shape changes. Part of the compared row, so a receipt written
# under an older shape is a miss rather than a partial match.
CACHE_RECEIPT_SCHEMA = "certitherm-cache-v1"

Sha256File = Callable[[Path], str]


def canonical_sha256(payload: Mapping[str, object]) -> str:
    """A digest of a mapping that does not depend on key order or JSON whitespace.

    `sort_keys` and the compact separators are what make this reproducible across runs and
    Python versions; without them an input dict built in a different order would hash differently
    and every cache would miss.
    """

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_bundle_sha256(
    relative_paths: Sequence[str], *, root: Path, sha256_file: Sha256File
) -> str:
    """Digest of the source that BUILDS an artifact, keyed by repo-relative path.

    Callers must list every module whose behaviour the artifact or its validation depends on. A
    module left out means a change there does not move this digest, and a cache written under the
    old logic is then accepted under the new one -- the false-hit failure above.
    `tests/test_cache_source_bundle.py` enforces the membership rather than trusting the caller.
    """

    return canonical_sha256(
        {relative: sha256_file(root / relative) for relative in sorted(relative_paths)}
    )


def receipt_path(artifact: Path) -> Path:
    """The receipt sits beside its artifact under a suffixed name, never in a shared index.

    One file per artifact means deleting the artifact and deleting its claim to be valid are the
    same operation, and a half-written run cannot leave a receipt pointing at a file it never
    finished.
    """

    return artifact.with_name(f"{artifact.name}.receipt.tsv")


def write_receipt(
    artifact: Path,
    signature: Mapping[str, str],
    related: Optional[Mapping[str, Path]] = None,
    *,
    sha256_file: Sha256File,
) -> None:
    """Record the signature plus the artifact's own digest, and those of any related files."""

    related = {} if related is None else related
    row: dict[str, object] = {
        "schema": CACHE_RECEIPT_SCHEMA,
        **signature,
        "artifact_sha256": sha256_file(artifact),
    }
    row.update({f"{name}_sha256": sha256_file(path) for name, path in related.items()})
    write_rows(receipt_path(artifact), [row])


def receipt_matches(
    artifact: Path,
    signature: Mapping[str, str],
    related: Optional[Mapping[str, Path]] = None,
    *,
    sha256_file: Sha256File,
) -> bool:
    """True only if the receipt reproduces EXACTLY what a fresh build would record.

    Total dict equality, deliberately. An extra or missing column, a renamed field or a changed
    schema all read as a miss, because the alternative -- comparing only the fields both sides
    happen to have -- would let a receipt written by different logic pass.

    A missing artifact, a missing receipt, an unreadable receipt or a receipt with anything other
    than exactly one row are all misses too. Returning False rather than raising is right here:
    the caller's next move is to rebuild, and a corrupt receipt is not a reason to abort a run.
    """

    related = {} if related is None else related
    receipt = receipt_path(artifact)
    if not artifact.is_file() or not receipt.is_file():
        return False
    try:
        rows = read_rows(receipt)
        if len(rows) != 1:
            return False
        expected = {
            "schema": CACHE_RECEIPT_SCHEMA,
            **signature,
            "artifact_sha256": sha256_file(artifact),
            **{f"{name}_sha256": sha256_file(path) for name, path in related.items()},
        }
    except (OSError, ValueError):
        return False
    return rows[0] == expected
