"""The envelope's class-total cap can collapse it to a point; that must be a checked property.

`docs/ADVERSARIAL_SELF_REVIEW.md` E1 found this once, by noticing that one design's supremum was
constant across a 2000-fold widening of the span. Once is a discovery; the same fact holding over a
population is an invariant, and only the second kind survives a reviewer asking "how do you know it
does not happen elsewhere?"

The property: a design whose live blocks span **more than one content class** must have a genuine
envelope at every positive span, and a design whose live blocks are each alone in their class must
have a singleton — the class-total cap says so, and `envelope_is_singleton` must agree with the cap
rather than with a tolerance.
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.measurements import activity_bounded_power_space, envelope_is_singleton

SPANS = (1e-3, 0.05, 0.30, 1.00, 2.00)


def _blocks(prefixes, per_prefix):
    return [f"{p}_{i}" for p in prefixes for i in range(per_prefix)]


@pytest.mark.parametrize("span", SPANS)
def test_more_than_one_block_per_class_is_never_a_singleton(span):
    blocks = _blocks(("mtxu", "vecu", "ubuf"), 3)
    placed = np.linspace(0.5, 4.0, len(blocks))
    space = activity_bounded_power_space(blocks, placed, activity_span=span)
    assert not envelope_is_singleton(space), (
        f"span {span}: nine blocks in three classes collapsed to a point; the cap is binding where "
        "it should not, and every envelope quantity on such a design is a point evaluation"
    )
    assert float(np.sum(space.upper_w)) > float(np.sum(placed)) + 1e-12


@pytest.mark.parametrize("span", SPANS)
def test_one_block_per_class_is_ALWAYS_a_singleton(span):
    """Not a bug, and it must be detected at every span rather than at a lucky one."""
    blocks = _blocks(("mtxu", "vecu", "ubuf", "ibuf", "obuf"), 1)
    placed = np.array([4.0, 1.0, 3.0, 0.5, 0.75])
    space = activity_bounded_power_space(blocks, placed, activity_span=span)
    assert envelope_is_singleton(space), (
        f"span {span}: the class-total cap pins every coordinate here, and a driver that does not "
        "notice reports a robustness radius for a design tolerating nothing"
    )


def test_the_detector_does_not_depend_on_which_side_pins():
    """Either bound can collapse the set; a detector that checks one of them is half a detector."""
    blocks = ["mtxu_0", "mtxu_1"]
    placed = np.array([2.0, 2.0])
    space = activity_bounded_power_space(blocks, placed, activity_span=0.30)
    assert not envelope_is_singleton(space)
    # Pin from BELOW: lower bounds summing to the total leaves no slack either.
    from CertiTherm.core import PowerPolytope
    pinned = PowerPolytope(
        lower_w=placed.copy(), upper_w=placed * 1.3,
        a_eq=np.ones((1, 2)), b_eq=np.array([float(placed.sum())]),
        a_ub=np.empty((0, 2)), b_ub=np.empty(0),
    )
    assert envelope_is_singleton(pinned), "a set pinned by its LOWER bounds was not detected"
