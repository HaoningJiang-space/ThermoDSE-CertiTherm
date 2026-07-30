"""The physical replay must use the binary and template the driver chose, and say so.

`replay_unsynth_witness` is the one place archiving can CHANGE a reported status: it re-runs an
UNSYNTHESIZABLE witness through HotSpot and can reject it. A replay against a different HotSpot than
the run used would either reject a valid witness or accept an invalid one, and the row would not say
which.

That path is unreachable without a real UNSYNTHESIZABLE plan, so extracting this module left two
free names -- `hotspot_binary` and `template_dir`, formerly driver globals -- that no test touched.
A blanket rename had turned them into a NameError reachable only in a claim-grade run. These tests
exercise the path with a stubbed `replay_power`, which is what makes that unrepeatable.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from CertiTherm import query_evidence
from CertiTherm.core import CandidateSpace, PowerPolytope, ThermalFamily


def _candidate(candidate_id: str = "arch_a", blocks: int = 2) -> CandidateSpace:
    response = np.full((1, blocks, blocks), 0.2)
    np.fill_diagonal(response[0], 2.0)
    return CandidateSpace(
        candidate_id=candidate_id,
        power=PowerPolytope.box_with_total(np.zeros(blocks), np.full(blocks, 4.0), 4.0),
        thermal=ThermalFamily(
            ("m0",), response, np.full((1, blocks), 300.0), 330.0, (), np.zeros(1)
        ),
    )


def _unsynth_plan(candidate_id: str = "arch_a") -> SimpleNamespace:
    pair = SimpleNamespace(
        candidate_id=candidate_id,
        left_power_w=np.array([1.0, 3.0]),
        right_power_w=np.array([3.0, 1.0]),
        left_state="safe",
        right_state="reject",
        left_model_id="m0",
        right_model_id="m0",
    )
    return SimpleNamespace(
        status="UNSYNTHESIZABLE",
        witnesses=(SimpleNamespace(candidates=(pair,)),),
    )


def test_a_plan_that_is_not_unsynthesizable_replays_nothing(tmp_path: Path) -> None:
    """Non-vacuity for the tests below: the early exit must be the reason, not a broken fixture."""

    rows, accepted = query_evidence.replay_unsynth_witness(
        "q0",
        SimpleNamespace(status="OPTIMAL", witnesses=()),
        [_candidate()],
        {},
        "default",
        tmp_path,
        hotspot_binary=tmp_path / "hotspot",
        template_dir=tmp_path,
    )
    assert rows == [] and accepted is True


def test_the_replay_uses_the_injected_binary_and_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression: these were free names after extraction, unreachable from any test.

    A stub records what the replay was actually handed. Asserting on the recorded paths is the only
    success condition, so a reversion to module globals -- or to no name at all -- fails here rather
    than in a claim-grade run.
    """

    seen: list[tuple[Path, Path]] = []

    def fake_replay(binary, config, floorplan, materials, *_args, **_kwargs):
        seen.append((Path(binary), Path(materials)))
        return np.array([305.0, 306.0])

    def fake_load_family(_path):
        candidate = _candidate()
        return candidate.thermal, ("b0", "b1")

    monkeypatch.setattr(query_evidence, "replay_power", fake_replay)
    monkeypatch.setattr(query_evidence, "load_family", fake_load_family)

    binary = tmp_path / "chosen-hotspot"
    template = tmp_path / "chosen-template"
    template.mkdir()
    rows, _accepted = query_evidence.replay_unsynth_witness(
        "q0",
        _unsynth_plan(),
        [_candidate()],
        {("arch_a", "default"): tmp_path / "operator.npz"},
        "default",
        tmp_path,
        hotspot_binary=binary,
        template_dir=template,
    )

    assert seen, "the replay never reached HotSpot, so this test proves nothing"
    for used_binary, used_materials in seen:
        assert used_binary == binary, (
            f"the replay used {used_binary}, not the binary the driver chose"
        )
        assert used_materials == template / "example.materials", (
            f"the replay used {used_materials}, not the template the driver chose"
        )
    assert rows, "a replayed witness must produce rows"


def test_the_driver_hands_over_its_own_resources() -> None:
    """The wrapper exists so the row records what the driver validated, not an import-time read."""

    import inspect

    from CertiTherm import experiments

    source = inspect.getsource(experiments._archive_query_evidence)
    for expected in (
        "hotspot_binary=HOTSPOT",
        "template_dir=TEMPLATE",
        "query_budget_s=QUERY_METHOD_TIMEOUT_S",
        "budget_is_frozen=_BUDGET_IS_FROZEN",
    ):
        assert expected in source, f"the driver's wrapper no longer passes {expected}"

    signature = inspect.signature(query_evidence.archive_query_evidence)
    for name in ("hotspot_binary", "template_dir", "query_budget_s", "budget_is_frozen"):
        parameter = signature.parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty, (
            f"{name} has a default, so a caller can silently get a different one than the run used"
        )
