"""Tests for the single-source physical ThermoDSE route ledger."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from CertiTherm.physical_nop import physical_nop_class


THERMODSE = Path(__file__).resolve().parents[2] / "ThermoDSE"
if str(THERMODSE) not in sys.path:
    sys.path.insert(0, str(THERMODSE))

from core.nop import Nop  # type: ignore  # noqa: E402


def _nop():
    cls = physical_nop_class(Nop)
    return cls(
        100,
        100,
        100,
        [(0, 0), (0, 3), (5, 0), (5, 3)],
        9.0,
        3.0,
        64.0,
        (4, 4),
        2,
        2,
    )


def test_link_index_uses_allocated_x_plus_two_stride():
    nop = _nop()
    assert nop.get_link_idx(4, 0, nop.RIGHT) != nop.get_link_idx(
        0, 1, nop.RIGHT
    )
    assert max(
        nop.get_link_idx(x, y, direction)
        for x in range(6)
        for y in range(4)
        for direction in range(4)
    ) == len(nop.link_hops) - 1


def test_adjacent_chiplet_boundary_is_nop_not_noc():
    nop = _nop()
    nop.unicast((2, 0), (3, 0), 10.0)
    assert nop.get_tot_nop_hops() == pytest.approx(10.0)
    assert nop.get_tot_noc_hops() == pytest.approx(0.0)

    nop.clear()
    nop.unicast((1, 0), (2, 0), 10.0)
    assert nop.get_tot_nop_hops() == pytest.approx(0.0)
    assert nop.get_tot_noc_hops() == pytest.approx(10.0)


def test_multicast_energy_and_contention_share_the_union_tree():
    nop = _nop()
    nop.multicast((1, 0), [(4, 0), (4, 3)], 5.0)

    # Rooted XY union: three horizontal plus three vertical edges.  It crosses
    # one x chiplet cut and one y chiplet cut.
    assert nop.get_tot_nop_hops() == pytest.approx(2 * 5.0)
    assert nop.get_tot_noc_hops() == pytest.approx(4 * 5.0)
    assert sum(nop.link_hops) == pytest.approx(6 * 5.0)
    charged = {index for index, hops in enumerate(nop.link_hops) if hops}
    assert len(charged & set(nop.nop_link_idx)) == 2
