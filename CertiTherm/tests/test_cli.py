"""`python -m CertiTherm.cli` is a public entry point with no internal callers, so nothing else
would notice if it broke.

That is not hypothetical here. `python -m CertiTherm.experiments` was silently deleted by a
refactor and six hundred tests stayed green, because no test ran a module as a script. `cli.py` is
in exactly the same position -- documented in README.md and CLAUDE.md, imported by nobody -- so it
gets the same coverage.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from CertiTherm import cli
from CertiTherm.tabular import read_rows

_ROOT = Path(__file__).resolve().parents[2]


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "CertiTherm.cli", *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )


def test_the_module_is_runnable_and_names_both_subcommands() -> None:
    result = _run("--help")
    assert result.returncode == 0, f"the entry point failed: {result.stderr[-400:]}"
    assert "build-family" in result.stdout and "synthesize" in result.stdout


@pytest.mark.parametrize("subcommand", ["build-family", "synthesize"])
def test_each_subcommand_parses(subcommand: str) -> None:
    """A subcommand listed in the top-level help but broken below it is worse than absent."""

    result = _run(subcommand, "--help")
    assert result.returncode == 0, f"{subcommand} --help failed: {result.stderr[-400:]}"
    assert "--output" in result.stdout


def test_no_subcommand_is_refused() -> None:
    """Non-vacuity: the parser must reject as well as accept."""

    assert _run().returncode != 0


def test_the_plan_table_goes_through_the_one_tsv_writer(tmp_path: Path) -> None:
    """`cli` held a third hand-rolled DictWriter; it now uses `tabular.write_rows`.

    Asserted through a round trip rather than by reading the source: the column order must be the
    declared one, and `read_rows` must be able to read back what was written -- which is the whole
    reason for having one writer.
    """

    class _Plan:
        status = "OPTIMAL"
        selected_action_ids = ("a0", "a1")
        exact_cost = 3.0
        lower_bound = 3.0
        relaxation_bound = 2.5
        optimality_gap = 0.0
        iterations = 4
        message = "done"
        witnesses = ()

    output = tmp_path / "plan.tsv"
    cli._write_plan(_Plan(), output)  # type: ignore[attr-defined]
    rows = read_rows(output)
    assert len(rows) == 1
    assert list(rows[0]) == [
        "status", "selected_actions", "exact_cost", "lower_bound",
        "relaxation_bound", "optimality_gap", "iterations", "message",
    ]
    assert rows[0]["selected_actions"] == "a0,a1"
    assert rows[0]["status"] == "OPTIMAL"
