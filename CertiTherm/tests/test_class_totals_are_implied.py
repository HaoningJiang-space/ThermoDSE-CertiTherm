"""Are the class-total rows a real constraint, or implied by the box they sit beside?

Peer review (Codex, 2026-08-05) argued they are redundant: each block already obeys
`p_i <= (1+s) * placed_i`, so summing within a class gives `sum_c p_i <= (1+s) * sum_c placed_i`,
which is exactly the row `activity_bounded_power_space` adds. If that holds, then
`constrain_class_totals=True` does not narrow the polytope, and the docstring's claim of "two
independent axes" is wrong.

This settles it by construction rather than by argument, and it matters twice over: a redundant
row is not merely clutter, it is a documented modelling axis that does not exist -- and
`_extreme_rows` is only valid where the box-with-total IS the feasible set, an assumption whose
justification rests on exactly this implication.
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.cross_grid_bound import _extreme_rows
from CertiTherm.measurements import activity_bounded_power_space

SPANS = (1e-3, 0.05, 0.30, 1.00)


@pytest.mark.parametrize("span", SPANS)
def test_the_class_rows_are_implied_by_the_box(span):
    """Every point of the box satisfies the class rows, so they cut nothing off."""
    blocks = [f"{p}_{i}" for p in ("mtxu", "vecu", "ubuf") for i in range(4)]
    rng = np.random.default_rng(0)
    placed = rng.uniform(0.2, 4.0, size=len(blocks))
    space = activity_bounded_power_space(blocks, placed, activity_span=span)
    lower = np.asarray(space.lower_w, dtype=float)
    upper = np.asarray(space.upper_w, dtype=float)
    a_ub = np.asarray(space.a_ub, dtype=float)
    b_ub = np.asarray(space.b_ub, dtype=float)
    assert a_ub.shape[0] > 0, "this test is vacuous without class rows to check"

    # The tightest a class row can be pushed from inside the box is with every member at its upper
    # bound. If even that satisfies the row, no point of the box can violate it.
    worst = a_ub @ upper
    assert np.all(worst <= b_ub + 1e-12), (
        f"a class row is violated at the box's own corner by {float(np.max(worst - b_ub)):.3e}; "
        "the row is NOT implied and the greedy in _extreme_rows is being used outside its validity"
    )


@pytest.mark.parametrize("span", SPANS)
def test_dropping_the_class_rows_changes_no_supremum(span):
    """The operational consequence: the certified quantity is identical with and without them."""
    blocks = [f"{p}_{i}" for p in ("mtxu", "vecu", "ubuf") for i in range(4)]
    rng = np.random.default_rng(1)
    placed = rng.uniform(0.2, 4.0, size=len(blocks))
    rows = rng.uniform(0.0, 3.0, size=(40, len(blocks)))
    total = float(placed.sum())

    with_rows = activity_bounded_power_space(blocks, placed, activity_span=span,
                                             constrain_class_totals=True)
    without = activity_bounded_power_space(blocks, placed, activity_span=span,
                                           constrain_class_totals=False)
    assert np.array_equal(with_rows.lower_w, without.lower_w)
    assert np.array_equal(with_rows.upper_w, without.upper_w)

    a = _extreme_rows(rows, np.asarray(with_rows.lower_w, dtype=float),
                      np.asarray(with_rows.upper_w, dtype=float), total)
    b = _extreme_rows(rows, np.asarray(without.lower_w, dtype=float),
                      np.asarray(without.upper_w, dtype=float), total)
    assert np.array_equal(a, b), "the flag changed a supremum, so the rows are not redundant"


def test_a_class_row_would_bind_if_the_cap_were_tighter_than_the_box():
    """The rows are redundant HERE, not in principle -- pin what would make them bite.

    A genuinely independent axis needs a class budget the per-block bounds do not already imply,
    e.g. a class span smaller than the block span. This constructs that case by hand and shows the
    row then cuts, which is what "two independent axes" would have to look like.
    """
    placed = np.array([2.0, 2.0, 1.0])
    member = np.array([1.0, 1.0, 0.0])          # a class of the first two blocks
    upper = placed * 1.30                        # block span 30 %
    tight_class_budget = float(member @ placed) * 1.05   # class span 5 %
    assert float(member @ upper) > tight_class_budget, (
        "the constructed class budget is not tighter than the box, so this test proves nothing"
    )
