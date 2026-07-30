"""The declared columns and the record they serialise must not drift apart.

A column added to one without the other is not a test failure. It is a result table whose reader
sees a different schema than the writer wrote, and the reader's missing field reads as empty rather
than as an error. These tests pin the relationships that make such an edit visible.
"""

from __future__ import annotations

import pytest

from CertiTherm import result_schema
from CertiTherm.split_protocol import ANYTIME_SPLITS, DEVELOPMENT_SPLITS, HELDOUT_SPLITS

_ALL_SPLITS = tuple(DEVELOPMENT_SPLITS) + tuple(HELDOUT_SPLITS)


@pytest.mark.parametrize("split", _ALL_SPLITS)
def test_no_split_declares_a_duplicate_column(split: str) -> None:
    """A repeated name makes `csv.DictWriter` write one column and drop the other silently."""

    fields = result_schema.result_fieldnames(split)
    assert fields, f"{split} declared no result columns"
    assert len(fields) == len(set(fields)), (
        f"{split} repeats: {sorted({f for f in fields if list(fields).count(f) > 1})}"
    )


@pytest.mark.parametrize("split", _ALL_SPLITS)
def test_the_base_columns_are_present_for_every_split(split: str) -> None:
    """Every result table must be readable by a consumer that only knows the base schema."""

    assert set(result_schema.BASE_RESULT_FIELDS) <= set(
        result_schema.result_fieldnames(split)
    )


@pytest.mark.parametrize("split", _ALL_SPLITS)
def test_anytime_columns_appear_exactly_for_the_anytime_splits(split: str) -> None:
    """Non-vacuity in both directions: present where used, absent where not.

    Asserting only the presence half would pass a schema that gave every split every column,
    which is how a v1 table would silently acquire v2 endpoints it never computed.
    """

    fields = set(result_schema.result_fieldnames(split))
    anytime = set(result_schema.ANYTIME_RESULT_FIELDS)
    if split in ANYTIME_SPLITS:
        assert anytime <= fields, f"{split} is an anytime split but lacks {sorted(anytime - fields)}"
    else:
        assert not (anytime & fields), (
            f"{split} is not an anytime split but declares {sorted(anytime & fields)}"
        )


def test_at_least_one_split_falls_on_each_side_of_the_anytime_split() -> None:
    """Otherwise the test above would only ever exercise one of its two branches."""

    assert any(s in ANYTIME_SPLITS for s in _ALL_SPLITS)
    assert any(s not in ANYTIME_SPLITS for s in _ALL_SPLITS)


def test_every_declared_column_is_named_by_one_of_the_field_groups() -> None:
    """A column that belongs to no group has no owner, so nothing says when to bump the version."""

    groups = (
        set(result_schema.BASE_RESULT_FIELDS)
        | set(result_schema.POLICY_RESULT_FIELDS)
        | set(result_schema.ANYTIME_RESULT_FIELDS)
        | set(result_schema.DIAGNOSTIC_RESULT_FIELDS)
    )
    for split in _ALL_SPLITS:
        orphans = set(result_schema.result_fieldnames(split)) - groups
        assert not orphans, f"{split} declares ungrouped columns: {sorted(orphans)}"


def test_optional_seconds_writes_blank_not_zero_for_an_unmeasured_duration() -> None:
    """0.0 would read back as an instantaneous success -- the one reading the data cannot support."""

    class _Timed:
        def __init__(self, seconds):
            self.seconds = seconds

    assert result_schema.optional_seconds(_Timed(None)) == ""
    assert result_schema.optional_seconds(_Timed(0.0)) == 0.0
    assert result_schema.optional_seconds(_Timed(1.25)) == pytest.approx(1.25)


def test_the_frozen_budget_flag_reflects_the_preregistered_value() -> None:
    """An artifact produced under a shortened budget must not pass as claim-grade."""

    assert result_schema.FROZEN_QUERY_BUDGET_S == 1800.0
    expected = abs(result_schema.QUERY_METHOD_TIMEOUT_S - 1800.0) < 1e-9
    assert result_schema.BUDGET_IS_FROZEN is expected


def test_the_driver_still_exposes_the_names_its_callers_import() -> None:
    """Tests import AnytimeResult and CertifiedContract from `experiments`; keep that working."""

    from CertiTherm import experiments

    assert experiments.AnytimeResult is result_schema.AnytimeResult
    assert experiments.CertifiedContract is result_schema.CertifiedContract
    assert experiments.RESULT_SCHEMA_VERSION == result_schema.RESULT_SCHEMA_VERSION
    assert experiments._ANYTIME_RESULT_FIELDS is result_schema.ANYTIME_RESULT_FIELDS


def test_a_non_finite_certified_cost_is_refused() -> None:
    """`NaN < 0` is False, so nonnegativity alone admitted NaN and infinity.

    The derived gap and ratio would then serialise NaN while `interval_violation` stayed empty --
    a row that looks non-violating while carrying no meaningful certified upper bound. Same hole
    as the one closed in `load_capture_metrics`; peer review found this one.
    """

    assert result_schema.CertifiedContract("exact", ("a",), 3.0).cost == 3.0
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="must be finite"):
            result_schema.CertifiedContract("exact", ("a",), bad)
    with pytest.raises(ValueError, match="nonnegative"):
        result_schema.CertifiedContract("exact", ("a",), -1.0)


def test_the_serialiser_records_the_budget_it_is_given_not_a_module_global() -> None:
    """The validated budget and the recorded budget must be the same number.

    `_validate_run_request` accepts an explicitly supplied budget, so a serialiser reading the
    import-time environment could stamp `budget_is_frozen=1` on a run that used something else.
    Keyword-only and without a default, so the driver has to hand over what it validated.
    """

    from types import SimpleNamespace

    anytime = result_schema.AnytimeResult(
        contract=result_schema.CertifiedContract("exact", ("a",), 3.0),
        proof_search=SimpleNamespace(
            status="OPTIMAL",
            lower_bound=3.0,
            relaxation_bound=3.0,
            bound_provenance="weak_duality",
            cost_optimality="PROVEN_SELF_VERIFIABLE",
        ),
        upper_seconds=1.0,
        lower_seconds=1.0,
    )
    rehearsal = result_schema.anytime_result_fields(
        anytime, query_budget_s=300.0, budget_is_frozen=False
    )
    assert rehearsal["query_budget_s"] == 300.0
    assert rehearsal["budget_is_frozen"] == 0, (
        "a shortened budget must not be stamped as frozen evidence"
    )
    frozen = result_schema.anytime_result_fields(
        anytime, query_budget_s=1800.0, budget_is_frozen=True
    )
    assert frozen["budget_is_frozen"] == 1

    with pytest.raises(TypeError):
        result_schema.anytime_result_fields(anytime)  # type: ignore[call-arg]
