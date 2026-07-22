"""Fail-closed guards for claim-grade experiment launches."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from CertiTherm import experiments


def test_frozen_run_rejects_budget_override() -> None:
    with pytest.raises(ValueError, match="exactly 1800s"):
        experiments._validate_run_request("heldout", True, budget_s=700.0)


def test_burned_split_cannot_be_relabelled_as_frozen_evidence() -> None:
    with pytest.raises(ValueError, match="OPENED_INVALID"):
        experiments._validate_run_request("heldout_v2", True, budget_s=1800.0)


def test_nonfrozen_dev_rehearsal_remains_available() -> None:
    experiments._validate_run_request("dev", False, budget_s=25.0)


def test_registered_v1_frozen_request_is_admitted() -> None:
    experiments._validate_run_request("heldout", True, budget_s=1800.0)


def test_unknown_split_is_rejected_before_creating_output() -> None:
    with pytest.raises(ValueError, match="unregistered experiment split"):
        experiments._validate_run_request("typo", False, budget_s=1800.0)


def test_frozen_run_rejects_dirty_worktree(monkeypatch) -> None:
    monkeypatch.setattr(
        experiments.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=" M CertiTherm/core.py\n"),
    )
    with pytest.raises(RuntimeError, match="requires a clean revision"):
        experiments._assert_clean_revision()
