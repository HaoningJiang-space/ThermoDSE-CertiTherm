"""Content-addressed thermal operators: exact reuse only, and the hit rate is reported not assumed.

A thermal response matrix `R` is a property of a GEOMETRY -- floorplan, package, grid model -- and of
nothing else. Two designs that induce byte-identical floorplans under the same package and model share
`R` exactly; two that do not, do not, and `docs/DIRECTION_FIXED_GEOMETRY.md` measured what pretending
otherwise costs: 0.69-2.44 K of reuse error against a 0.25-1.06 K model-form band, one to ten times
the term the method exists to measure.

So this library is keyed by the **content digest of the floorplan text**, not by an architecture
identifier, a parameter tuple, or anything a caller could get wrong. A hit is an exact reuse and a
miss is a rebuild; there is no approximate hit and no similarity threshold, because the failure mode
of a near-hit is a certificate built on the wrong operator, which enters evidence looking correct.

**The hit rate is a measured property of the population, not a design goal.** Over the 61 archive
designs it is 0.0 % -- 61 designs, 61 distinct floorplans -- and only one of the ten design fields
(`interval`) leaves the floorplan invariant. The library still earns its place: it makes revisiting a
geometry free inside a search loop, it makes the accounting explicit, and it makes cross-geometry
reuse impossible by construction rather than by discipline.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


def geometry_key(floorplan_text: str, package_id: str, model_id: str) -> str:
    """The identity of an operator: what it was built ON, digested.

    The three components are joined with a separator that cannot occur in any of them, so no pair of
    distinct inputs can produce one key by concatenation.
    """
    if "\x00" in package_id or "\x00" in model_id:
        raise ValueError("package or model identifier contains the key separator")
    payload = "\x00".join((floorplan_text, package_id, model_id)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class LibraryStats:
    hits: int = 0
    misses: int = 0
    build_seconds: float = 0.0
    lookup_seconds: float = 0.0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def as_dict(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "hit_rate": self.hit_rate,
                "build_seconds": self.build_seconds, "lookup_seconds": self.lookup_seconds}


@dataclass
class OperatorLibrary:
    """On-disk, content-addressed. `build` is injected so this module never imports a solver."""

    root: Path
    package_id: str = "default"
    model_id: str = "grid128-avg"
    stats: LibraryStats = field(default_factory=LibraryStats)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, floorplan_text: str) -> Path:
        return self.root / f"{geometry_key(floorplan_text, self.package_id, self.model_id)}.npz"

    def get(self, floorplan_text: str, blocks):
        """`(rows, ambient)` if this exact geometry is stored, else `None`.

        The stored block list is compared against the caller's. A stored operator whose block order
        differs is a DIFFERENT operator for the same floorplan text, which would mean the floorplan
        no longer determines the ordering -- so it is refused rather than reordered, because
        reordering silently would produce a plausible wrong answer.
        """
        target = self.path_for(floorplan_text)
        if not target.exists():
            return None
        with np.load(target, allow_pickle=False) as data:
            stored = [str(b) for b in data["block_ids"]]
            if stored != list(blocks):
                raise ValueError(
                    f"{target.name} stores {len(stored)} blocks in a different order than the "
                    f"caller's {len(list(blocks))}; the floorplan text no longer determines the "
                    "block ordering and the operator cannot be reused"
                )
            rows = np.asarray(data["response_k_per_w"], dtype=float)[0]
            ambient = np.asarray(data["ambient_k"], dtype=float)[0]
        if not (np.all(np.isfinite(rows)) and np.all(np.isfinite(ambient))):
            raise ValueError(f"{target.name} carries a non-finite entry; a stored operator that "
                             "cannot be checked is not reused")
        return rows, ambient

    def put(self, floorplan_text: str, blocks, rows, ambient) -> Path:
        target = self.path_for(floorplan_text)
        rows = np.asarray(rows, dtype=float)
        ambient = np.asarray(ambient, dtype=float)
        if rows.ndim != 2 or ambient.shape != (rows.shape[0],):
            raise ValueError(f"rows {rows.shape} and ambient {ambient.shape} disagree")
        if rows.shape[1] != len(list(blocks)):
            raise ValueError("the operator has a different column count than the block list")
        if not (np.all(np.isfinite(rows)) and np.all(np.isfinite(ambient))):
            raise ValueError("refusing to store a non-finite operator")
        np.savez_compressed(
            target, model_ids=np.asarray([self.model_id]), response_k_per_w=rows[None, :, :],
            ambient_k=ambient[None, :], block_ids=np.asarray(list(blocks)),
            package_id=np.asarray([self.package_id]),
        )
        return target

    def get_or_build(self, floorplan_text: str, blocks, build):
        """`(rows, ambient, was_hit)`. `build()` takes no arguments and returns `(rows, ambient)`."""
        import time

        started = time.monotonic()
        found = self.get(floorplan_text, blocks)
        self.stats.lookup_seconds += time.monotonic() - started
        if found is not None:
            self.stats.hits += 1
            return found[0], found[1], True
        started = time.monotonic()
        rows, ambient = build()
        self.stats.build_seconds += time.monotonic() - started
        self.stats.misses += 1
        self.put(floorplan_text, blocks, rows, ambient)
        return np.asarray(rows, dtype=float), np.asarray(ambient, dtype=float), False

    def write_manifest(self, path: Path) -> None:
        entries = sorted(p.name for p in self.root.glob("*.npz"))
        Path(path).write_text(json.dumps(
            {"package_id": self.package_id, "model_id": self.model_id,
             "operators": len(entries), "entries": entries,
             "stats": self.stats.as_dict()}, indent=1, sort_keys=True), encoding="utf-8")
