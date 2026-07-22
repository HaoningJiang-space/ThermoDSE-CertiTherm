"""Containment contract for `_call_under_budget`.

Two properties, both violated in production before this file existed:

1. The budget's own `TimeoutError` must never escape. It is converted into a
   returned error tuple, and every caller relies on that -- `_evaluate_query_batch`
   labels anything that escapes as `method worker failure`, which
   `_unexpected_method_failures` then counts as an UNEXPECTED failure, and
   `AnytimeGateSummary.passes` hard-fails on a single unexpected failure. So an
   ordinary timeout escaping containment can fail a gate run outright.

2. The budget must actually be enforced. A nested call must not silently cancel
   an outer deadline, or a method can overrun its budget without limit and
   report success.

Both were found by probing the v3.1 15-worker rehearsal, which recorded
`uncertainty_width=method worker failure: TimeoutError: 150.0s method budget
exhausted` on 2 of 6 rows.
"""
from __future__ import annotations

import signal
import time

import pytest

from CertiTherm.experiments import _call_under_budget


def _spin(seconds: float) -> None:
    """Busy-wait. Deliberately not `sleep`: the failures involve signal
    delivery against a *running* thread, and sleeping changes that."""

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        pass


@pytest.fixture(autouse=True)
def _disarm():
    yield
    signal.setitimer(signal.ITIMER_REAL, 0)


def test_alarm_during_cleanup_does_not_escape(monkeypatch) -> None:
    """An alarm landing in the `finally` must not propagate.

    The timer stays armed until the `finally` disarms it, so the interval
    between entering the `finally` and that call completing is unguarded --
    the `except` has already been passed. Normally that is microseconds, but
    under the v3.1 scheduler's 45-way process oversubscription a descheduled
    process can sit there for milliseconds, which is why this showed up on 2 of
    6 rows rather than never.

    The window is widened deterministically here by making the disarm slow,
    which is precisely what being descheduled looks like to a pending signal.
    """

    real_setitimer = signal.setitimer
    widen = {"armed": True}

    def slow_setitimer(which, value, *rest):
        # Only the first disarm is slowed, and only when it is a disarm.
        if widen["armed"] and value == 0:
            widen["armed"] = False
            _spin(0.25)
        return real_setitimer(which, value, *rest)

    monkeypatch.setattr(signal, "setitimer", slow_setitimer)

    value, seconds, error = _call_under_budget(
        lambda: _spin(0.05), 0.2, "cleanup-window budget exhausted"
    )

    # Whether it reports success or a timeout depends on exactly where the
    # alarm lands, and both are legitimate. What is NOT legitimate is raising.
    assert seconds >= 0.0
    assert error == "" or error.startswith("TimeoutError")


def test_nested_call_does_not_cancel_the_outer_budget() -> None:
    """A completed inner budget must not disarm the outer one.

    `_call_under_budget` disarms unconditionally on exit, so an inner call that
    finishes early leaves the outer deadline unarmed and the outer function then
    runs unbounded. Measured: a 0.2 s outer budget ran 3.01 s and reported no
    error at all.
    """

    def outer() -> None:
        _call_under_budget(lambda: _spin(0.01), 5.0, "inner budget")
        _spin(3.0)

    started = time.monotonic()
    value, seconds, error = _call_under_budget(outer, 0.3, "outer budget exhausted")
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, (
        f"outer budget of 0.3s was not enforced: ran {elapsed:.2f}s. "
        "A nested call disarmed the outer timer."
    )
    assert error.startswith("TimeoutError")


def test_ordinary_overrun_is_still_contained() -> None:
    """The base case must keep working after the containment fix."""

    value, seconds, error = _call_under_budget(
        lambda: _spin(5.0), 0.2, "plain budget exhausted"
    )
    assert value is None
    assert error == "TimeoutError: plain budget exhausted"
    assert 0.0 < seconds < 3.0


def test_successful_call_reports_no_error_and_leaves_no_timer() -> None:
    value, seconds, error = _call_under_budget(
        lambda: "ok", 5.0, "unused budget message"
    )
    assert value == "ok"
    assert error == ""
    # A leftover armed timer would fire inside whatever runs next in this
    # process -- the worker reuse case.
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0.0


def test_a_timeout_cannot_leak_into_the_next_call_in_the_same_process() -> None:
    """Workers are persistent and handle many tasks in sequence."""

    _call_under_budget(lambda: _spin(5.0), 0.2, "first task budget")
    value, seconds, error = _call_under_budget(lambda: "second", 5.0, "second task")
    assert value == "second"
    assert error == ""
