"""A run must not inherit evidence from whatever was in its output directory before.

Six of the result tables are written only when they have rows, while the checksum and artifact scans
walk the whole output directory. So a re-run into a directory that already held one of them kept the
stale file and recorded it as this run's evidence -- silent contamination across invocations, and
exactly the kind of thing that reads as a legitimate artifact afterwards.

Peer review found it. These tests pin the property rather than the implementation: after the write
phase, "this table has no rows" and "this file does not exist" must be the same statement.
"""

from __future__ import annotations

import inspect

from CertiTherm import experiments

# The tables written under `if rows:`. Kept as data so a seventh conditional table added without
# clearing it fails here.
_CONDITIONAL_TABLES = (
    "measurement_registry.tsv",
    "spectral_envelopes.tsv",
    "plans.tsv",
    "witnesses.tsv",
    "witness_replays.tsv",
    "FAILURES.tsv",
)


def _cleared_names() -> set:
    """The exact tuple the clearing loop iterates, read from the AST rather than by substring.

    Parsed, not grepped: a substring search over the function body would also match the comment
    above the loop and the writes below it, and would then pass while clearing nothing.
    """

    import ast

    tree = ast.parse(inspect.getsource(experiments.run).lstrip())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == "conditional"
        ):
            return {
                element.value
                for element in node.iter.elts
                if isinstance(element, ast.Constant)
            }
    raise AssertionError("run() no longer clears its conditional tables")


def test_every_conditionally_written_table_is_cleared_first() -> None:
    """The clearing set and the conditionally-written set must be identical."""

    source = inspect.getsource(experiments.run)
    written = {name for name in _CONDITIONAL_TABLES if f'output / "{name}"' in source}
    assert written == set(_CONDITIONAL_TABLES), (
        f"the fixture no longer matches the writes in run(): {sorted(written)}"
    )
    assert _cleared_names() == set(_CONDITIONAL_TABLES), (
        "a table written conditionally but not cleared leaves a stale copy from an earlier run to "
        f"be checksummed as this run's evidence: {sorted(set(_CONDITIONAL_TABLES) - _cleared_names())}"
    )


def test_unconditional_tables_are_not_cleared() -> None:
    """Non-vacuity: clearing everything would be a blunter change that hides a missing write.

    `results.tsv`, `candidate_order.tsv` and `REPORT.md` are always written, so deleting them first
    accomplishes nothing and would turn a write that failed to happen into a silently absent file.
    """

    cleared = _cleared_names()
    for always_written in ("results.tsv", "candidate_order.tsv", "REPORT.md"):
        assert always_written not in cleared
