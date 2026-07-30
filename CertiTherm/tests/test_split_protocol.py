"""The split tables must agree with each other, and the driver must still read them.

Extracting these four tables out of `experiments.py` is only safe if the names the research tree
and the older tests reach for still resolve there. That is asserted here rather than assumed,
because a re-export that quietly stopped existing would show up as an AttributeError deep inside
a probe rather than as a test failure.
"""

from __future__ import annotations

import pytest

from CertiTherm import experiments, split_protocol


def test_the_three_tables_name_exactly_the_declared_splits() -> None:
    """The guard that runs at import, restated so a reader sees what it protects.

    A split registered in two tables and missing from the third would report a real protocol
    state beside an UNREGISTERED freeze ID, so the artifact would carry a contradiction rather
    than an obvious gap.
    """

    declared = split_protocol._known_splits()
    assert declared, "a fixture with no declared splits could not detect a mismatch"
    assert set(split_protocol.PROTOCOL_STATE) == declared
    assert set(split_protocol.FREEZE_ID) == declared
    assert set(split_protocol.REGISTRY_SPLITS) <= declared
    for group in (
        split_protocol.BURNED_SPLITS,
        split_protocol.FROZEN_ONLY_SPLITS,
        split_protocol.FROZEN_ENABLED_SPLITS,
        split_protocol.ANYTIME_SPLITS,
    ):
        assert group <= declared


@pytest.mark.parametrize(
    "split,registry,state,freeze",
    [
        ("dev", "dev", "DEVELOPMENT", "method-freeze-v1"),
        ("dev_v3", "dev", "DEVELOPMENT_REHEARSAL", "method-freeze-v3.1"),
        ("heldout", "heldout", "FROZEN_HELDOUT", "method-freeze-v1"),
        ("heldout_v2", "heldout_v2", "BURNED_HELDOUT", "method-freeze-v2.1"),
        ("heldout_v3", "heldout_v3", "FROZEN_HELDOUT", "method-freeze-v3.1"),
    ],
)
def test_each_registered_split_resolves_to_its_frozen_triple(
    split: str, registry: str, state: str, freeze: str
) -> None:
    """Only `dev_v3` reads another split's rows; everything else maps to itself."""

    assert split_protocol.registry_split(split) == registry
    assert split_protocol.protocol_state(split) == state
    assert split_protocol.freeze_id(split) == freeze


def test_an_unknown_split_reports_unregistered_rather_than_raising() -> None:
    """A report has to print the gap. Raising here would kill the report that names it."""

    assert split_protocol.registry_split("not-a-split") == "not-a-split"
    assert split_protocol.protocol_state("not-a-split") == "UNREGISTERED"
    assert split_protocol.freeze_id("not-a-split") == "UNREGISTERED"


def test_the_driver_still_exposes_the_names_the_research_tree_imports() -> None:
    """18 callers import `_registry_split` from `experiments`; they must keep working."""

    assert experiments._registry_split("dev_v3") == "dev"
    assert experiments._SPLIT_FREEZE_ID["dev_v3"] == "method-freeze-v3.1"
    assert experiments._SPLIT_PROTOCOL_STATE["dev_v3"] == "DEVELOPMENT_REHEARSAL"
    assert "dev_v3" in experiments._ANYTIME_SPLITS
    assert experiments._SPLIT_FREEZE_ID is split_protocol.FREEZE_ID, (
        "the re-export must be the same object, not a copy that can drift"
    )


def test_the_frozen_limits_are_one_definition_shared_by_both_readers() -> None:
    """They were two equal literals in two modules; equality by accident is not a check."""

    from CertiTherm import frozen_limits, gpu_benchmark

    assert experiments.THERMAL_LIMIT_K is frozen_limits.THERMAL_LIMIT_K
    assert gpu_benchmark.THERMAL_LIMIT_K is frozen_limits.THERMAL_LIMIT_K
    assert experiments.MODEL_ERROR_LIMIT_K is frozen_limits.MODEL_ERROR_LIMIT_K
    assert gpu_benchmark.ERROR_LIMIT_K is frozen_limits.MODEL_ERROR_LIMIT_K
