"""`python -m CertiTherm.experiments` must exist and must reach `run`.

It stopped existing for six commits. An extraction rebuilt the module as `lines[:cut] + call` and
never reappended the tail, so `main` and the `__main__` guard were dropped -- and
`make reproduce-dev`, which invokes exactly this, silently did nothing. Every one of six hundred
tests stayed green, because not one of them ran the module as a script.

So this file runs it as a script. A missing entry point is not a subtle failure to detect; it is a
failure nobody was looking for.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from CertiTherm import experiments
from CertiTherm.split_protocol import DEVELOPMENT_SPLITS, HELDOUT_SPLITS

_ROOT = Path(__file__).resolve().parents[2]


def test_the_module_is_runnable_as_a_script() -> None:
    """`--help` exercises import, `main`, and the parser without starting a run."""

    result = subprocess.run(
        [sys.executable, "-m", "CertiTherm.experiments", "--help"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"the entry point failed: {result.stderr[-400:]}"
    assert "--split" in result.stdout and "--output" in result.stdout
    assert "--frozen" in result.stdout


def test_every_registered_split_is_accepted_by_the_parser() -> None:
    """A split the protocol declares but the CLI rejects cannot be run at all."""

    result = subprocess.run(
        [sys.executable, "-m", "CertiTherm.experiments", "--help"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    for split in tuple(DEVELOPMENT_SPLITS) + tuple(HELDOUT_SPLITS):
        assert split in result.stdout, f"{split} is registered but the CLI will not accept it"


def test_an_unregistered_split_is_refused_before_anything_runs(tmp_path: Path) -> None:
    """Non-vacuity: the parser must reject as well as accept, or the test above proves nothing."""

    result = subprocess.run(
        [
            sys.executable, "-m", "CertiTherm.experiments",
            "--split", "not-a-split", "--output", str(tmp_path / "out"),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not (tmp_path / "out").exists(), "a refused run created its output directory"


def test_main_hands_the_parsed_arguments_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The parser existing is not the same as it being wired to `run`."""

    seen: list[tuple] = []
    monkeypatch.setattr(experiments, "run", lambda *args: seen.append(args))
    monkeypatch.setattr(
        sys, "argv", ["experiments", "--split", "dev", "--output", "/tmp/x", "--frozen"]
    )
    experiments.main()
    assert seen == [("dev", Path("/tmp/x"), True)]
