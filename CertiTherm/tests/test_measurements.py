"""The activity envelope can be a POINT, and a driver that does not notice reports false comfort."""

from __future__ import annotations

import numpy as np

def test_a_one_block_per_class_design_has_a_singleton_envelope():
    """The class-total cap collapses the set to a point; the predicate must say so at every span."""
    from CertiTherm.measurements import activity_bounded_power_space, envelope_is_singleton

    # One block per content class, which is what a single-core architecture produces.
    blocks = ["mtxu_0", "vecu_0", "ubuf_0", "ibuf_0", "obuf_0"]
    placed = np.array([4.0, 1.0, 3.0, 0.5, 0.75])
    for span in (1e-3, 0.30, 2.0):
        space = activity_bounded_power_space(blocks, placed, activity_span=span)
        assert envelope_is_singleton(space), (
            f"span {span}: the envelope is a point and the predicate did not say so; a radius over "
            "it would report tolerance the design does not have"
        )
        assert np.allclose(space.upper_w, placed), "the class-total cap did not bind as expected"


def test_a_multi_core_design_has_a_genuine_envelope():
    """The predicate must not fire whenever a class has more than one member."""
    from CertiTherm.measurements import activity_bounded_power_space, envelope_is_singleton

    blocks = ["mtxu_0", "mtxu_1", "vecu_0", "vecu_1"]
    placed = np.array([4.0, 2.0, 1.0, 0.5])
    space = activity_bounded_power_space(blocks, placed, activity_span=0.30)
    assert not envelope_is_singleton(space)
    assert float(np.sum(space.upper_w)) > float(np.sum(placed)) + 1e-9
