"""The bridge must never leave ThermoDSE half-patched, and must never hide a thermal route.

`hotspot_disabled` mutates attributes on a submodule this repository does not own. The failure
that matters is a mutation surviving the region: a later capture would then silently skip HotSpot
and report whatever temperature was lying around as if it had been measured. So restoration is
tested on the normal path, the exception path, under nesting, and when the second mutation itself
fails -- the case an earlier version could not survive, because both assignments happened before
the `try`.

`core.chiplet_eva` is a real ThermoDSE module that needs the submodule on `sys.path`, so these
tests substitute a stand-in rather than importing it. The point under test is the mutation
protocol, not ThermoDSE.
"""

from __future__ import annotations

import sys
import types

import pytest

from CertiTherm import thermodse_bridge


class _Generator:
    def run_hotspot(self, *_args, **_kwargs):
        return "real-hotspot"


class _Evaluator:
    def __init__(self) -> None:
        self.flp_generator = _Generator()


def _original_find_hotpoint(*_args, **_kwargs) -> float:
    return 12.5


@pytest.fixture
def stub_core(monkeypatch: pytest.MonkeyPatch):
    """A stand-in `core.chiplet_eva` whose `find_hotpoint` is identifiable."""

    module = types.ModuleType("core.chiplet_eva")
    module.find_hotpoint = _original_find_hotpoint
    package = types.ModuleType("core")
    package.chiplet_eva = module
    monkeypatch.setitem(sys.modules, "core", package)
    monkeypatch.setitem(sys.modules, "core.chiplet_eva", module)
    return module


def test_both_routes_are_closed_inside_and_reopened_after(stub_core) -> None:
    """Non-vacuity first: assert the routes are genuinely open before and closed inside."""

    evaluator = _Evaluator()
    assert evaluator.flp_generator.run_hotspot() == "real-hotspot"
    assert stub_core.find_hotpoint() == 12.5

    with thermodse_bridge.hotspot_disabled(evaluator):
        assert evaluator.flp_generator.run_hotspot() is None, "the binary route stayed open"
        inside = stub_core.find_hotpoint()
        assert inside != inside, "the readback route must return NaN, not a plausible number"

    assert evaluator.flp_generator.run_hotspot() == "real-hotspot"
    assert stub_core.find_hotpoint() == 12.5


def test_an_exception_inside_the_region_still_reopens_both_routes(stub_core) -> None:
    """A failed capture must not leave the next one silently non-thermal."""

    evaluator = _Evaluator()
    with pytest.raises(ZeroDivisionError):
        with thermodse_bridge.hotspot_disabled(evaluator):
            raise ZeroDivisionError
    assert evaluator.flp_generator.run_hotspot() == "real-hotspot"
    assert stub_core.find_hotpoint() == 12.5


def test_nesting_restores_in_reverse_order(stub_core) -> None:
    """Each level saves what it found, which may be the outer level's replacement."""

    evaluator = _Evaluator()
    with thermodse_bridge.hotspot_disabled(evaluator):
        outer = evaluator.flp_generator.run_hotspot
        with thermodse_bridge.hotspot_disabled(evaluator):
            assert evaluator.flp_generator.run_hotspot is not outer
        assert evaluator.flp_generator.run_hotspot is outer, "the inner exit skipped a level"
    assert evaluator.flp_generator.run_hotspot() == "real-hotspot"


def test_a_failure_between_the_two_mutations_leaves_nothing_patched(stub_core) -> None:
    """The hole the rewrite closed: a partial mutation must not escape the error path.

    The second `setattr` is made to fail. An earlier version assigned both attributes BEFORE
    entering the `try`, so this left the floorplan generator patched with no `finally` to undo it,
    and the next capture in the same process would have skipped HotSpot without saying so.
    """

    evaluator = _Evaluator()

    class _Rejecting(types.ModuleType):
        find_hotpoint = staticmethod(_original_find_hotpoint)

        def __setattr__(self, name, value):
            if name == "find_hotpoint":
                raise RuntimeError("read-only module attribute")
            super().__setattr__(name, value)

    rejecting = _Rejecting("core.chiplet_eva")
    package = types.ModuleType("core")
    package.chiplet_eva = rejecting
    sys.modules["core"], sys.modules["core.chiplet_eva"] = package, rejecting
    try:
        with pytest.raises(RuntimeError, match="read-only"):
            with thermodse_bridge.hotspot_disabled(evaluator):
                pytest.fail("the region must not be entered when a route cannot be closed")
    finally:
        sys.modules.pop("core", None)
        sys.modules.pop("core.chiplet_eva", None)
    assert evaluator.flp_generator.run_hotspot() == "real-hotspot", (
        "the first route stayed patched after the second could not be closed"
    )


def test_an_unimportable_thermodse_refuses_before_mutating_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the region cannot be made non-thermal it must not run at all."""

    monkeypatch.setitem(sys.modules, "core", None)
    evaluator = _Evaluator()
    with pytest.raises(ImportError):
        with thermodse_bridge.hotspot_disabled(evaluator):
            pytest.fail("entered the region without closing either route")
    assert evaluator.flp_generator.run_hotspot() == "real-hotspot"


def test_the_design_vector_keeps_thermodses_ten_element_ordering() -> None:
    """Upstream duplicates this ordering in four optimizers; it exists once here."""

    row = {
        "chiplet_x": "2", "chiplet_y": "3", "cut_x": "1", "cut_y": "1",
        "interval": "0.5", "mtxu_h": "16", "mtxu_w": "32", "ubuf": "64",
        "nop_bw": "128", "dram_bw": "256",
    }
    vector = thermodse_bridge.design_vector(row)
    assert vector == [2, 3, 1, 1, 0.5, 16, 32, 64, 128, 256]
    assert isinstance(vector[4], float), "interval is the only float in the convention"
    assert all(isinstance(v, int) for i, v in enumerate(vector) if i != 4)


def test_a_missing_or_non_numeric_registry_field_fails_closed() -> None:
    """A silently defaulted design field would evaluate a different architecture than registered."""

    complete = {
        "chiplet_x": "2", "chiplet_y": "3", "cut_x": "1", "cut_y": "1",
        "interval": "0.5", "mtxu_h": "16", "mtxu_w": "32", "ubuf": "64",
        "nop_bw": "128", "dram_bw": "256",
    }
    with pytest.raises(KeyError):
        thermodse_bridge.design_vector({k: v for k, v in complete.items() if k != "ubuf"})
    with pytest.raises(ValueError):
        thermodse_bridge.design_vector({**complete, "nop_bw": "wide"})


def test_a_registry_id_that_escapes_the_run_directory_is_refused(tmp_path) -> None:
    """The directory this builds is DELETED, so its name may not be attacker- or typo-controlled.

    Peer review raised it: `workload_id` and `architecture_id` become a path component and the
    function rmtree's the result. A slash or `..` would hand rmtree a target nobody intended, and
    a registry can acquire a bad identifier by accident.
    """

    good_arch = {"architecture_id": "arch_a"}
    good_workload = {"workload_id": "resnet50"}
    for arch_id, workload_id in (
        ("../escape", "resnet50"),
        ("arch_a", "../.."),
        ("arch/a", "resnet50"),
        ("arch_a", "res net"),
    ):
        with pytest.raises(ValueError, match="registry identifiers must match"):
            thermodse_bridge.prepare_simulation_dir(
                {"architecture_id": arch_id},
                {"workload_id": workload_id},
                {},
                tmp_path,
                allow_hotspot=False,
            )
    # Non-vacuity: the accepted pair gets past the name check and fails later, on the missing
    # template -- so the refusals above are caused by the names and not by the fixture.
    with pytest.raises((FileNotFoundError, KeyError)):
        thermodse_bridge.prepare_simulation_dir(
            good_arch, good_workload, {}, tmp_path, allow_hotspot=False
        )


def test_a_non_finite_or_nonpositive_objective_is_refused(tmp_path) -> None:
    """`min(...) <= 0` let NaN through, and `hotspot_disabled` yields NaN on purpose.

    So a NaN objective is reachable rather than hypothetical, and it would have propagated into
    `edyp` and from there into evidence.
    """

    import numpy as np

    def _capture_file(name, latency=1.0, energy=2.0, die_yield=0.5):
        path = tmp_path / name
        np.savez(
            path,
            latency_ms=np.asarray(latency),
            energy_mj=np.asarray(energy),
            die_yield=np.asarray(die_yield),
        )
        return path.with_suffix(".npz")

    good = thermodse_bridge.load_capture_metrics(_capture_file("good"))
    assert good["edyp"] == pytest.approx(1.0 * 2.0 / 0.5), "the fixture must have a valid case"

    with pytest.raises(RuntimeError, match="non-finite latency_ms"):
        thermodse_bridge.load_capture_metrics(_capture_file("nan", latency=float("nan")))
    with pytest.raises(RuntimeError, match="non-finite energy_mj"):
        thermodse_bridge.load_capture_metrics(_capture_file("inf", energy=float("inf")))
    with pytest.raises(RuntimeError, match="nonpositive die_yield"):
        thermodse_bridge.load_capture_metrics(_capture_file("zero", die_yield=0.0))


def test_a_non_finite_design_field_is_refused() -> None:
    """`float("nan")` and `float("inf")` both parse; the evaluator must not receive either."""

    complete = {
        "chiplet_x": "2", "chiplet_y": "3", "cut_x": "1", "cut_y": "1",
        "interval": "0.5", "mtxu_h": "16", "mtxu_w": "32", "ubuf": "64",
        "nop_bw": "128", "dram_bw": "256",
    }
    assert thermodse_bridge.design_vector(complete)[4] == 0.5
    for bad in ("nan", "inf", "-inf"):
        with pytest.raises(ValueError, match="is not finite"):
            thermodse_bridge.design_vector({**complete, "interval": bad})


def test_a_core_package_outside_the_submodule_is_refused(monkeypatch) -> None:
    """`sys.path.insert` does not displace an already-imported `core` of the same name."""

    impostor = types.ModuleType("core")
    impostor.__file__ = "/somewhere/else/core/__init__.py"
    monkeypatch.setitem(sys.modules, "core", impostor)
    with pytest.raises(RuntimeError, match="not inside the pinned ThermoDSE submodule"):
        thermodse_bridge.install_compatibility_layer()
