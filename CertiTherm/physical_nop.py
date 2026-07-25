"""Auditable replacement for the pinned ThermoDSE NoC/NoP route ledger.

The pinned implementation allocates ``link_hops`` with an ``x + 2`` row width but indexes
it with ``x``.  It also classifies chiplet boundaries with range arithmetic that misses an
adjacent boundary crossing.  Consequently latency, channel energy, and thermal placement
cannot share one spatial fact source.

This module keeps ThermoDSE's public ``Nop`` interface and cost constants, but makes the
route itself authoritative:

* unicast is deterministic X-then-Y routing;
* multicast is the union of those rooted paths (one charge per tree edge);
* every directed link has an unaliased ``(nx + 2)``-stride index;
* NoC/NoP counters and contention are derived from the same explicit edges.

The external DRAM edge remains a NoP edge in the raw route ledger.  ThermoDSE's existing
``get_tot_nop_hops`` convention subtracts exactly one such edge per DRAM access, leaving
DRAM-access energy as the characterized source for that external hop.
"""

from __future__ import annotations

from typing import Iterable, Tuple, Type

Coord = Tuple[int, int]
DirectedEdge = Tuple[Coord, Coord]


def _path(source: Coord, destination: Coord, nx: int) -> Tuple[DirectedEdge, ...]:
    x, y = source
    edges = []

    def horizontal(target_x):
        nonlocal x
        step = 1 if target_x > x else -1
        while x != target_x:
            nxt = (x + step, y)
            edges.append(((x, y), nxt))
            x += step

    def vertical(target_y):
        nonlocal y
        step = 1 if target_y > y else -1
        while y != target_y:
            nxt = (x, y + step)
            edges.append(((x, y), nxt))
            y += step

    # Never invent a vertical router column outside the package.
    if destination[0] in (0, nx + 1):
        vertical(destination[1])
        horizontal(destination[0])
    elif source[0] in (0, nx + 1):
        horizontal(destination[0])
        vertical(destination[1])
    else:
        horizontal(destination[0])
        vertical(destination[1])
    return tuple(edges)


def physical_nop_class(base_nop: Type[object]):
    """Return an idempotent physical-ledger subclass of the pinned ``Nop`` class."""

    if getattr(base_nop, "_certitherm_physical_ledger", False):
        return base_nop

    class PhysicalNop(base_nop):  # type: ignore[misc,valid-type]
        _certitherm_physical_ledger = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.nop_link_idx = sorted(self._physical_nop_link_indices())

        def get_link_idx(self, x, y, direction):
            if not (0 <= x < self.shape[0] + 2 and 0 <= y < self.shape[1]):
                raise ValueError(f"link source is outside the routed grid: {(x, y)}")
            if direction not in (self.RIGHT, self.DOWN, self.LEFT, self.UP):
                raise ValueError(f"unknown link direction: {direction}")
            return (y * (self.shape[0] + 2) + x) * 4 + direction

        def _chiplet_id(self, coord):
            x, y = coord
            if not (1 <= x <= self.shape[0] and 0 <= y < self.shape[1]):
                raise ValueError(f"coordinate is not a compute core: {coord}")
            return ((x - 1) // self.x_step, y // self.y_step)

        def _is_nop_edge(self, edge):
            a, b = edge
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
                raise ValueError(f"route edge is not adjacent: {edge}")
            if a[0] in (0, self.shape[0] + 1) or b[0] in (
                0,
                self.shape[0] + 1,
            ):
                return True
            return self._chiplet_id(a) != self._chiplet_id(b)

        def _direction(self, edge):
            (x0, y0), (x1, y1) = edge
            return {
                (1, 0): self.RIGHT,
                (-1, 0): self.LEFT,
                (0, -1): self.DOWN,
                (0, 1): self.UP,
            }[(x1 - x0, y1 - y0)]

        def _record_edges(self, edges: Iterable[DirectedEdge], size):
            total = 0
            for edge in edges:
                source, _ = edge
                index = self.get_link_idx(
                    source[0], source[1], self._direction(edge)
                )
                self.link_hops[index] += size
                if self._is_nop_edge(edge):
                    self.tot_nop_hops += size
                else:
                    self.tot_noc_hops += size
                total += 1
            return total * size

        def _physical_nop_link_indices(self):
            indices = set()
            nx, ny = self.shape
            for y in range(ny):
                for x in range(nx + 2):
                    source = (x, y)
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        destination = (x + dx, y + dy)
                        if not (
                            0 <= destination[0] < nx + 2
                            and 0 <= destination[1] < ny
                        ):
                            continue
                        if x in (0, nx + 1) and dx == 0:
                            continue
                        edge = (source, destination)
                        if self._is_nop_edge(edge):
                            indices.add(
                                self.get_link_idx(x, y, self._direction(edge))
                            )
            return indices

        def _unicastCalc(self, src_cidx, dst_cidx, size):
            return self._record_edges(
                _path(tuple(src_cidx), tuple(dst_cidx), self.shape[0]), size
            )

        def _multicastCalc(self, src_cidx, dst_cidx_list, size):
            tree = set()
            source = tuple(src_cidx)
            for destination in dst_cidx_list:
                tree.update(_path(source, tuple(destination), self.shape[0]))
            return self._record_edges(sorted(tree), size)

        def unicast(self, src_cidx, dst_cidx, size):
            self._unicastCalc(src_cidx, dst_cidx, size)

        def multicast(self, src_cidx, dst_cidx_list, size):
            self._multicastCalc(src_cidx, dst_cidx_list, size)

        def NoP_link_calc(self, src, dst):
            return sum(
                self._is_nop_edge(edge)
                for edge in _path(tuple(src), tuple(dst), self.shape[0])
            )

    PhysicalNop.__name__ = "PhysicalNop"
    PhysicalNop.__qualname__ = "PhysicalNop"
    return PhysicalNop


def install_physical_nop():
    """Install the physical route ledger in ThermoDSE's evaluator module."""

    from core import chiplet_eva  # type: ignore

    replacement = physical_nop_class(chiplet_eva.Nop)
    chiplet_eva.Nop = replacement
    return replacement
