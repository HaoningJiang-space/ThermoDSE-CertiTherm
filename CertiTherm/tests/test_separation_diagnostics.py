"""Regression cover for the separation diagnostics.

These counters exist to answer "why is the certified lower bound small?", which
the endpoint columns alone cannot: a small bound is ambiguous between few
expensive rounds, a saturating dual, and a candidate schedule that never
reached most of its subproblems.

The cases that matter are therefore the interrupted and dominated ones, not a
clean completed run: a diagnostic that is only correct when nothing goes wrong
reports nothing about the runs it was built for.
"""
from __future__ import annotations

import numpy as np
import pytest

from CertiTherm import (
    CandidateSpace,
    MeasurementAction,
    PowerPolytope,
    ThermalFamily,
)
from CertiTherm.synthesis import (
    CutLedger,
    _insert_minimal_cut,
    synthesize_minimum_observation,
    synthesize_ordered_query,
)


def _two_candidate_instance():
    polytope = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    thermal = ThermalFamily(
        ("block",), np.array([[[2.0, 0.0]]]), np.array([0.0]), 1.0
    )
    candidates = (
        CandidateSpace("fast", polytope, thermal),
        CandidateSpace("slow", polytope, thermal),
    )
    actions = tuple(
        MeasurementAction(
            f"{candidate}-p{index}",
            np.eye(2)[index],
            candidate_id=candidate,
        )
        for candidate in ("fast", "slow")
        for index in range(2)
    )
    return candidates, actions


def test_ledger_separates_dominated_from_evicted() -> None:
    """The two rejection/removal reasons are distinct and must not be merged.

    A dominated cut is one we DECLINE to store because an existing cut is
    already stronger; an evicted cut is an existing one we DISCARD because the
    arriving cut is stronger. Counting both as "not added" would make the
    antichain look stagnant in the first case and shrinking in the second, and
    only the second is information gain.
    """

    cuts: list[np.ndarray] = []
    ledger = CutLedger()

    assert _insert_minimal_cut(cuts, np.array([1.0, 1.0, 0.0]), None, ledger)
    assert ledger.accepted == 1 and ledger.evicted == 0 and ledger.dominated == 0

    # Superset of an existing cut: weaker, so it is declined.
    assert not _insert_minimal_cut(cuts, np.array([1.0, 1.0, 1.0]), None, ledger)
    assert ledger.dominated == 1 and ledger.accepted == 1

    # Subset of an existing cut: strictly stronger, so it displaces it.
    assert _insert_minimal_cut(cuts, np.array([1.0, 0.0, 0.0]), None, ledger)
    assert ledger.accepted == 2 and ledger.evicted == 1

    assert len(cuts) == 1
    # The invariant the results table relies on: active is derived, never the
    # raw number of insertions.
    assert ledger.active == len(cuts) == ledger.accepted - ledger.evicted


def test_ledger_default_none_leaves_behaviour_unchanged() -> None:
    """Threading a ledger must not alter which cuts the antichain keeps."""

    for ledger in (None, CutLedger()):
        cuts: list[np.ndarray] = []
        _insert_minimal_cut(cuts, np.array([1.0, 1.0, 0.0]), None, ledger)
        _insert_minimal_cut(cuts, np.array([1.0, 1.0, 1.0]), None, ledger)
        _insert_minimal_cut(cuts, np.array([1.0, 0.0, 0.0]), None, ledger)
        assert len(cuts) == 1
        np.testing.assert_array_equal(cuts[0], [1.0, 0.0, 0.0])


def test_completed_plan_reports_consistent_cut_ledger() -> None:
    candidates, actions = _two_candidate_instance()
    plan = synthesize_minimum_observation(
        candidates[0].power,
        candidates[0].thermal,
        tuple(a for a in actions if a.candidate_id == "fast"),
    )

    assert plan.status == "OPTIMAL"
    assert plan.iterations >= 1
    assert plan.cuts_generated == plan.cuts_accepted + plan.cuts_dominated
    assert plan.cuts_active == plan.cuts_accepted - plan.cuts_evicted
    assert plan.cuts_active >= 1


def test_query_sums_candidate_ledgers_and_records_full_schedule() -> None:
    candidates, actions = _two_candidate_instance()
    plan = synthesize_ordered_query(candidates, actions)

    assert plan.status == "OPTIMAL"
    assert plan.candidates_required >= 1
    # A completed query stopped at no candidate, and completed all of them.
    assert plan.candidates_completed == plan.candidates_required
    assert plan.candidate_at_stop is None
    assert plan.cuts_active == plan.cuts_accepted - plan.cuts_evicted
    assert plan.cuts_accepted >= 1


def test_interrupted_candidate_still_reports_its_separation_work() -> None:
    """A timeout must not erase the work already done.

    This is the regression that matters: `iterations=0` with an empty ledger on
    an interrupted run is indistinguishable from a run that never started, and
    that ambiguity is exactly what these columns exist to remove.
    """

    candidates, actions = _two_candidate_instance()
    plan = synthesize_minimum_observation(
        candidates[0].power,
        candidates[0].thermal,
        tuple(a for a in actions if a.candidate_id == "fast"),
        max_iterations=1,
    )

    assert plan.status == "UNRESOLVED"
    # It ran, and it says so.
    assert plan.iterations >= 1
    assert plan.cuts_generated >= 1
    assert plan.cuts_active == plan.cuts_accepted - plan.cuts_evicted


def test_query_level_failure_preserves_partial_schedule_and_bound() -> None:
    """The query-level handler must not discard completed candidates.

    It previously returned `iterations=0` with no bound and no schedule state,
    which is the same evidence-destroying failure mode that had already been
    fixed one level down. A wall-clock interrupt landing between candidates is
    precisely the case the anytime path exists to report on.
    """

    candidates, actions = _two_candidate_instance()
    calls = {"n": 0}
    real = synthesize_minimum_observation

    def fail_after_first(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise TimeoutError("budget exhausted between candidates")
        return real(*args, **kwargs)

    import CertiTherm.synthesis as synthesis

    original = synthesis.synthesize_minimum_observation
    synthesis.synthesize_minimum_observation = fail_after_first
    try:
        plan = synthesize_ordered_query(candidates, actions)
    finally:
        synthesis.synthesize_minimum_observation = original

    assert plan.status == "UNRESOLVED"
    assert plan.candidates_completed >= 1
    assert plan.candidates_required >= plan.candidates_completed
    # The first candidate's proof work survives the failure of the second.
    assert plan.iterations >= 1
    assert plan.cuts_accepted >= 1
    # A partial sum over completed candidates is still a valid lower bound.
    if plan.lower_bound is not None:
        assert plan.lower_bound > 0


def test_diagnostics_are_present_in_the_result_schema() -> None:
    """The counters must reach the results file, not stop at the dataclass.

    This project has repeatedly built a mechanism and left it unwired to the
    path that matters; `iterations` was computed and dropped before every
    emitted column for exactly that reason.
    """

    from CertiTherm.experiments import (
        _DIAGNOSTIC_RESULT_FIELDS,
        _diagnostic_result_fields,
        _result_fieldnames,
    )

    for split in ("dev", "dev_v3"):
        fields = _result_fieldnames(split)
        for name in _DIAGNOSTIC_RESULT_FIELDS:
            assert name in fields, f"{name} missing from {split} schema"

    candidates, actions = _two_candidate_instance()
    plan = synthesize_ordered_query(candidates, actions)
    row = _diagnostic_result_fields(plan)
    assert set(row) == set(_DIAGNOSTIC_RESULT_FIELDS)
    assert row["exact_iterations"] == plan.iterations
    assert row["exact_cuts_active"] == plan.cuts_active

    # A method that never produced a plan reports blank, not zero: zero would
    # assert "ran and did nothing", a different claim from "never reported".
    blank = _diagnostic_result_fields(None)
    assert set(blank.values()) == {""}
