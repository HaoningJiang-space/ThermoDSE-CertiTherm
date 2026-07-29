"""One definition of "the SHA-256 of a file".

Seven modules -- `experiments`, `hotspot`, `gpu_hotspot`, `gpu_benchmark`, `transient`,
`instance_receipt` and the V6.1 factorial driver -- each carried a byte-identical copy of the
same streaming loop. Every receipt in this repository is chained on that digest, so it is the
one function whose behaviour must not be allowed to drift between copies: two implementations
of a content digest cannot be checked against each other, they can only silently disagree.

This module deliberately has no dependency on anything else in `CertiTherm`. It sits at the
bottom of the layer stack so that any module may import it without creating a cycle.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Union

# Streamed rather than read whole: operator NPZ exports and HotSpot grid dumps are large
# enough that reading them into memory is a real cost. The chunk size is part of no contract
# -- SHA-256 of a byte stream does not depend on how the stream was chunked -- so changing it
# cannot change any digest this repository has ever recorded.
_CHUNK_BYTES = 1 << 20


def sha256_file(path: Union[str, Path]) -> str:
    """Hex SHA-256 of a file's bytes.

    Accepts `str` as well as `Path`; one of the seven copies did and six did not, and callers
    relied on both.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()
