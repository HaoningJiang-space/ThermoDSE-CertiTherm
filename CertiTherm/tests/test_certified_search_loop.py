"""The search loop's one load-bearing invariant: an uncertified candidate never becomes the incumbent.

Tested with a synthetic scorer, so no simulator, no operator and no ThermoDSE are involved -- the
question is purely whether the constraint is hard. A penalised search would report the best objective
it saw, which is how a constrained problem silently becomes an unconstrained one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research" / "triangle" / "robustness"))


def _load():
    """Import the driver without executing its ThermoDSE-dependent module body twice."""
    import importlib.util

    path = (Path(__file__).resolve().parents[2] / "research" / "triangle" / "robustness"
            / "certified_search.py")
    source = path.read_text(encoding="utf-8")
    # Only the pure function is under test, and importing the module would drag in ThermoDSE. So the
    # function is compiled on its own -- which also proves it has no hidden module-level dependency.
    start = source.index("def coordinate_descent")
    end = source.index("class Evaluator:")
    namespace: dict = {}
    exec(compile(source[start:end], str(path), "exec"), namespace)   # noqa: S102 - test harness
    return namespace["coordinate_descent"]


coordinate_descent = _load()

FIELDS = ("a", "b")
ADMISSIBLE = {"a": ["0", "1", "2"], "b": ["0", "1", "2"]}


def _scorer(table):
    """`table[(a, b)] = (edyp, status)`; anything absent is UNRESOLVED."""
    seen = []

    def score(arch, tag):
        key = (arch["a"], arch["b"])
        seen.append(key)
        if key not in table:
            return None
        edyp, status = table[key]
        return {"edyp": edyp, "status": status, "design": dict(arch)}

    return score, seen


def test_a_cheaper_refuted_candidate_never_becomes_the_incumbent():
    table = {
        ("0", "0"): (10.0, "CERTIFIED"),      # baseline
        ("1", "0"): (1.0, "REFUTED"),         # much cheaper, infeasible -- must be ignored
        ("2", "0"): (9.0, "CERTIFIED"),
    }
    score, _seen = _scorer(table)
    incumbent, current, spent = coordinate_descent(
        {"a": "0", "b": "0"}, {"edyp": 10.0, "status": "CERTIFIED"},
        ADMISSIBLE, score, FIELDS, budget=20)
    assert incumbent["status"] == "CERTIFIED"
    assert incumbent["edyp"] == pytest.approx(9.0), (
        "the search took a refuted design because it was cheaper; the constraint is soft"
    )
    assert current["a"] == "2"


def test_an_uncertified_baseline_yields_no_incumbent_until_one_certifies():
    table = {("0", "0"): (10.0, "REFUTED"), ("1", "0"): (50.0, "CERTIFIED")}
    score, _seen = _scorer(table)
    incumbent, _current, _spent = coordinate_descent(
        {"a": "0", "b": "0"}, {"edyp": 10.0, "status": "REFUTED"},
        ADMISSIBLE, score, FIELDS, budget=20)
    assert incumbent is not None and incumbent["status"] == "CERTIFIED"
    assert incumbent["edyp"] == pytest.approx(50.0), (
        "a certified design must be accepted even when it is WORSE than a refuted baseline; "
        "otherwise the baseline's infeasible objective is silently the bar"
    )


def test_no_certified_candidate_anywhere_returns_none_rather_than_the_best_refuted():
    table = {("0", "0"): (10.0, "REFUTED"), ("1", "0"): (2.0, "REFUTED"),
             ("2", "0"): (1.0, "REFUTED")}
    score, _seen = _scorer(table)
    incumbent, _current, _spent = coordinate_descent(
        {"a": "0", "b": "0"}, {"edyp": 10.0, "status": "REFUTED"},
        ADMISSIBLE, score, FIELDS, budget=20)
    assert incumbent is None, "returning the cheapest refuted design would report an infeasible result"


def test_unresolved_candidates_are_skipped_not_counted_as_feasible():
    table = {("0", "0"): (10.0, "CERTIFIED")}          # every neighbour is UNRESOLVED
    score, _seen = _scorer(table)
    incumbent, current, _spent = coordinate_descent(
        {"a": "0", "b": "0"}, {"edyp": 10.0, "status": "CERTIFIED"},
        ADMISSIBLE, score, FIELDS, budget=20)
    assert incumbent["edyp"] == pytest.approx(10.0) and current == {"a": "0", "b": "0"}


def test_the_budget_is_respected_and_counts_the_baseline():
    table = {(a, b): (10.0 - int(a), "CERTIFIED") for a in "012" for b in "012"}
    score, seen = _scorer(table)
    _incumbent, _current, spent = coordinate_descent(
        {"a": "0", "b": "0"}, {"edyp": 10.0, "status": "CERTIFIED"},
        ADMISSIBLE, score, FIELDS, budget=4)
    assert spent <= 4, "the search exceeded its evaluation budget"
    assert len(seen) <= 3, "the baseline counts toward the budget, so at most 3 trials remain"


def test_improvement_must_be_strict_so_the_loop_terminates():
    """Equal-EDYP certified neighbours must not cycle the incumbent forever."""
    table = {(a, b): (5.0, "CERTIFIED") for a in "012" for b in "012"}
    score, _seen = _scorer(table)
    incumbent, _current, spent = coordinate_descent(
        {"a": "0", "b": "0"}, {"edyp": 5.0, "status": "CERTIFIED"},
        ADMISSIBLE, score, FIELDS, budget=100)
    assert incumbent["edyp"] == pytest.approx(5.0)
    assert spent < 100, "a non-strict improvement test let the search run to its budget"
