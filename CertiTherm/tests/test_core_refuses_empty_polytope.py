"""An empty `PowerPolytope` must be refused at construction, not discovered downstream.

Every consumer of an empty polytope returns a confident wrong answer rather than an error.
`sup` over an empty set is `-inf`, so a cross-operator band computed over one is `-inf`, and
`thermal_constraints` SUBTRACTS the band from the SAFE right-hand side -- an empty polytope
therefore certifies everything. That is the fail-open direction and it is silent, which is
why the check belongs in `__post_init__` beside the bounds check rather than in a caller.

`_refuse_empty_rows` is deliberately NECESSARY-not-sufficient: it tests each row against the
box in isolation, so jointly-contradictory rows still pass. These tests pin that boundary in
both directions, because a test suite that only showed the rejections would read as a claim
that the check decides emptiness.
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.core import PowerPolytope

_N = 3


def _box(lower=0.0, upper=1.0):
    return np.full(_N, lower), np.full(_N, upper)


def test_total_above_what_the_box_can_reach_is_refused():
    lower, upper = _box()
    with pytest.raises(ValueError, match=r"a_eq row 0 makes the polytope empty"):
        PowerPolytope.box_with_total(lower, upper, 3.5)


def test_total_below_what_the_box_can_reach_is_refused():
    lower, upper = _box(lower=0.5)
    with pytest.raises(ValueError, match=r"a_eq row 0 makes the polytope empty"):
        PowerPolytope.box_with_total(lower, upper, 1.0)


def test_the_message_names_the_reachable_range_and_the_demand():
    """A refusal that does not say WHICH number is wrong sends the reader back to the code."""

    lower, upper = _box()
    with pytest.raises(ValueError) as excinfo:
        PowerPolytope.box_with_total(lower, upper, 3.5)
    message = str(excinfo.value)
    assert "[0, 3]" in message and "3.5" in message


def test_an_inequality_no_point_of_the_box_can_satisfy_is_refused():
    lower, upper = _box(lower=1.0, upper=2.0)
    with pytest.raises(ValueError, match=r"a_ub row 0 makes the polytope empty"):
        PowerPolytope(
            lower_w=lower,
            upper_w=upper,
            a_eq=np.empty((0, _N)),
            b_eq=np.empty(0),
            a_ub=np.ones((1, _N)),
            b_ub=np.array([2.0]),
        )


def test_a_reachable_total_is_accepted():
    lower, upper = _box()
    space = PowerPolytope.box_with_total(lower, upper, 2.0)
    assert space.dimension == _N


def test_the_endpoints_of_the_reachable_range_are_accepted():
    """`<=` on both sides, not `<`: a total exactly at a corner is attainable."""

    lower, upper = _box()
    assert PowerPolytope.box_with_total(lower, upper, 0.0).dimension == _N
    assert PowerPolytope.box_with_total(lower, upper, 3.0).dimension == _N


def test_negative_coefficients_use_the_opposite_bound():
    """The greedy fill must send a negative coefficient to the UPPER bound for the minimum.

    Written because a sign slip here fails open: it would compute a range wider than the box
    can reach, so the check would accept an empty set rather than reject a nonempty one.
    """

    lower, upper = np.zeros(_N), np.array([1.0, 1.0, 1.0])
    row = np.array([1.0, -1.0, 0.0])  # reachable range over the box is exactly [-1, 1]
    for target in (-1.0, 0.0, 1.0):
        PowerPolytope(
            lower_w=lower,
            upper_w=upper,
            a_eq=row[None, :],
            b_eq=np.array([target]),
            a_ub=np.empty((0, _N)),
            b_ub=np.empty(0),
        )
    for target in (-1.5, 1.5):
        with pytest.raises(ValueError, match="makes the polytope empty"):
            PowerPolytope(
                lower_w=lower,
                upper_w=upper,
                a_eq=row[None, :],
                b_eq=np.array([target]),
                a_ub=np.empty((0, _N)),
                b_ub=np.empty(0),
            )


def test_jointly_contradictory_rows_still_pass_because_the_check_is_per_row():
    """The documented limit of the check, pinned so nobody reads it as deciding emptiness.

    `p0 + p1 = 2` and `p0 + p1 = 0` are each individually reachable over the unit box and
    together are unsatisfiable. Construction succeeds. If this test ever starts failing
    because the check became exact, that is a real improvement -- delete the test and say so
    in the docstring of `_refuse_empty_rows`, which currently promises the opposite.
    """

    lower, upper = _box()
    rows = np.array([[1.0, 1.0, 0.0], [1.0, 1.0, 0.0]])
    space = PowerPolytope(
        lower_w=lower,
        upper_w=upper,
        a_eq=rows,
        b_eq=np.array([2.0, 0.0]),
        a_ub=np.empty((0, _N)),
        b_ub=np.empty(0),
    )
    assert space.dimension == _N
