"""`@dataclass(frozen=True)` must mean the numbers too, not just the attribute names.

Frozen dataclasses stop an attribute from being REBOUND. They say nothing about the
contents of a NumPy array behind that attribute, and every numeric payload in `core` was
mutable in place -- the content the entire receipt chain is built on.

The concrete failure this closes: `_build_collision_problem` stores
`thermal.response_k_per_w` and `thermal.error_k` by reference, so a caller mutating the
family mid-solve changed what the collision LP saw between reject cells. The thread backend
froze five of the seven array fields as defence-in-depth and these two were not among them.
Extending that list would have patched one call site; sealing at construction removes the
hazard for every present and future consumer.

Sealing is in place, not by copying: a real operator response is (3, 237, 237) floats and
families are built per candidate, so a copy per construction is a real cost. The trade is
explicit -- handing an array to one of these dataclasses hands over ownership.
"""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.core import MeasurementAction, PowerPolytope, ThermalFamily

_N = 3


def _polytope() -> PowerPolytope:
    return PowerPolytope.box_with_total(np.zeros(_N), np.ones(_N), 2.0)


def _family() -> ThermalFamily:
    return ThermalFamily(("m0", "m1"), np.ones((2, 4, _N)), np.zeros(2), 350.0)


def _action() -> MeasurementAction:
    return MeasurementAction("a", np.ones(_N), 1.0, 1e-8, "c")


ARRAY_FIELDS = (
    ("PowerPolytope", _polytope, "lower_w"),
    ("PowerPolytope", _polytope, "upper_w"),
    ("PowerPolytope", _polytope, "a_eq"),
    ("PowerPolytope", _polytope, "b_eq"),
    ("ThermalFamily", _family, "response_k_per_w"),
    ("ThermalFamily", _family, "ambient_k"),
    ("ThermalFamily", _family, "error_k"),
    ("MeasurementAction", _action, "vector"),
)


@pytest.mark.parametrize(
    "label,build,field", ARRAY_FIELDS, ids=[f"{a}.{c}" for a, _b, c in ARRAY_FIELDS]
)
def test_array_payload_cannot_be_written_in_place(label, build, field) -> None:
    array = getattr(build(), field)
    assert array.size, f"{label}.{field} fixture is empty; it would pass vacuously"
    with pytest.raises(ValueError):
        array.flat[0] = 12345.0
    with pytest.raises(ValueError):
        array += 1.0


def test_a_caller_cannot_change_what_a_solver_already_holds() -> None:
    """The exact hazard, end to end: the collision LP holds the family's own arrays."""

    from CertiTherm.synthesis import _build_collision_problem

    family = _family()
    problem = _build_collision_problem(
        _polytope(), family, (_action(),), (0,), 0.1, 1e-10
    )
    assert problem.response is family.response_k_per_w, (
        "this test is only meaningful while the LP stores the family's array by reference; "
        "if that changed, the hazard is gone by a different route and this should be updated"
    )
    with pytest.raises(ValueError):
        family.response_k_per_w[0, 0, 0] = 999.0
    assert not problem.response.flags.writeable
    assert not problem.error_k.flags.writeable


def test_sealing_does_not_reject_construction_from_a_read_only_input() -> None:
    """Round-tripping through a second dataclass must not fail on an already-sealed array."""

    first = _family()
    second = ThermalFamily(
        first.model_ids, first.response_k_per_w, first.error_k, float(first.limit_k)
    )
    assert not second.response_k_per_w.flags.writeable


def test_a_caller_can_still_keep_a_writable_copy() -> None:
    """The documented escape hatch, so the ownership trade is actually usable."""

    source = np.ones((2, 4, _N))
    family = ThermalFamily(("m0", "m1"), source.copy(), np.zeros(2), 350.0)
    source[0, 0, 0] = 7.0
    assert source[0, 0, 0] == 7.0
    assert family.response_k_per_w[0, 0, 0] == 1.0
