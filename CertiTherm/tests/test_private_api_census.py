"""Pin the private coupling surface that the decomposition is about to move.

`experiments.py` and `synthesis.py` export sixty private symbols across module boundaries.
Python resolves a function's globals in the module where it was DEFINED, so relocating one
of them changes two things no ordinary test failure announces:

  * a compatibility alias keeps `from .experiments import _x` working but does NOT restore
    `monkeypatch.setattr(experiments, "_x", ...)`, because the moved caller looks `_x` up in
    its new module;
  * four of the sixty are reached only by `research/` scripts, which the suite never runs.
    For those, "443 passed" is evidence of nothing.

So this file asserts the surface itself. It is deliberately a coupling ledger rather than a
behavioural test: when a refactor moves one of these, the failure here is the intended
prompt to decide -- supported API, temporary alias, or migrate the callers -- instead of
discovering months later that a research entrypoint stopped resolving.

Regenerate the census with `python -m CertiTherm.tools.private_api_census`.
"""

from __future__ import annotations

import pathlib

import pytest

from CertiTherm import experiments, synthesis
from CertiTherm.tools.private_api_census import collect

CENSUS = pathlib.Path(__file__).resolve().parents[2] / "experiments/private_api_census.tsv"

# The four symbols no test exercises. They are listed explicitly, rather than derived, so
# that a symbol silently GAINING or LOSING test coverage shows up as a failure here too --
# a derived list would quietly absorb either change.
RESEARCH_ONLY = {
    ("experiments", "_capture"),
    ("experiments", "_configure"),
    ("experiments", "_thermodse_evaluator"),
    ("synthesis", "_collision_search"),
}

_MODULES = {"experiments": experiments, "synthesis": synthesis}


def _census_rows() -> dict:
    rows = {}
    for line in CENSUS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.startswith("module\t") or not line.strip():
            continue
        module, symbol, callers, kinds, files = line.split("\t")
        rows[(module, symbol)] = {
            "callers": int(callers),
            "kinds": tuple(kinds.split("+")),
            "files": tuple(files.split(",")),
        }
    return rows


def test_every_censused_symbol_still_resolves() -> None:
    """The whole point: a move that drops one of these fails HERE, loudly."""

    missing = [
        f"{module}.{symbol}"
        for (module, symbol) in _census_rows()
        if not hasattr(_MODULES[module], symbol)
    ]
    assert not missing, (
        "these private symbols are imported from outside their module but no longer "
        f"resolve there: {sorted(missing)}"
    )


def test_the_committed_census_matches_the_tree() -> None:
    """A stale ledger is worse than none: it would assert a surface that no longer exists."""

    live = {key: len(entry["callers"]) for key, entry in collect().items()}
    recorded = {key: row["callers"] for key, row in _census_rows().items()}
    assert live == recorded, (
        "experiments/private_api_census.tsv is stale; regenerate it with "
        "`python -m CertiTherm.tools.private_api_census`"
    )


@pytest.mark.parametrize("module,symbol", sorted(RESEARCH_ONLY))
def test_research_only_symbols_are_still_callable(module: str, symbol: str) -> None:
    """These four have no test coverage at all, so resolution is the only guarantee left.

    Asserting `callable` rather than behaviour is honest about what this can check: the
    suite cannot run the research drivers, so it can only certify that the name a research
    script imports still exists and is a function.
    """

    attribute = getattr(_MODULES[module], symbol, None)
    assert attribute is not None, f"{module}.{symbol} no longer resolves"
    assert callable(attribute), f"{module}.{symbol} is no longer callable"


def test_research_only_set_matches_the_census() -> None:
    """Keep the hard-coded set above honest against the regenerated ledger."""

    from_census = {
        key for key, row in _census_rows().items() if row["kinds"] == ("research",)
    }
    assert from_census == RESEARCH_ONLY, (
        "the set of test-uncovered private symbols changed; update RESEARCH_ONLY "
        f"deliberately. census={sorted(from_census)}"
    )
