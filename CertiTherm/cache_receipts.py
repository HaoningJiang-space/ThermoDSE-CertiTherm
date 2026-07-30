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

# Columns the receipt owns. A signature that redefined one of them would silently replace a field
# the comparison depends on -- `schema` is expanded after the fixed value, so a signature key of
# that name wins, and a related file named `artifact` generates `artifact_sha256` and displaces the
# artifact's own digest. Both would remove a check from the row while leaving it looking complete,
# which is the false-hit direction. Peer review raised it; the API refuses rather than documents it.
_RESERVED_COLUMNS = frozenset({"schema", "artifact_sha256"})


def _reject_column_collisions(
    signature: Mapping[str, str], related: Mapping[str, Path]
) -> None:
    """Refuse a request whose names would displace a column the comparison depends on.

    Checked BEFORE any file access, so `receipt_matches` cannot answer False for a request it
    could never have evaluated: a missing receipt is a cache miss, an unusable request is not.
    """

    clashing = sorted(_RESERVED_COLUMNS & set(signature))
    if clashing:
        raise ValueError(f"signature may not define reserved receipt columns: {clashing}")
    related_columns = {f"{name}_sha256" for name in related}
    displaced = sorted(related_columns & (_RESERVED_COLUMNS | set(signature)))
    if displaced:
        raise ValueError(f"related file names generate colliding columns: {displaced}")
    if len(related_columns) != len(related):
        raise ValueError("two related files generate the same receipt column")


def _row(
    signature: Mapping[str, str],
    artifact_digest: str,
    related_digests: Mapping[str, str],
) -> dict[str, object]:
    """Assemble the receipt row. Collisions are already refused by the caller."""

    row: dict[str, object] = {
        "schema": CACHE_RECEIPT_SCHEMA,
        **signature,
        "artifact_sha256": artifact_digest,
    }
    row.update({f"{name}_sha256": digest for name, digest in related_digests.items()})
    return row


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
    _reject_column_collisions(signature, related)
    row = _row(
        signature,
        sha256_file(artifact),
        {name: sha256_file(path) for name, path in related.items()},
    )
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

    A COLLIDING signature or related name is different and does raise. That is the caller passing
    an unusable request, not a damaged cache, and turning it into a miss would hide a receipt whose
    columns no longer mean what the comparison assumes.
    """

    related = {} if related is None else related
    _reject_column_collisions(signature, related)
    receipt = receipt_path(artifact)
    if not artifact.is_file() or not receipt.is_file():
        return False
    try:
        rows = read_rows(receipt)
        if len(rows) != 1:
            return False
        expected = _row(
            signature,
            sha256_file(artifact),
            {name: sha256_file(path) for name, path in related.items()},
        )
    except OSError:
        return False
    return rows[0] == expected
