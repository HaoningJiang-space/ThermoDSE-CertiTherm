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


def test_unmeasured_time_is_reported_missing_not_zero() -> None:
    """A worker that died without reporting has unknown elapsed time.

    Recording 0.0 put a false number into the evidence table: the v3.1
    rehearsal showed `width_seconds = 0.0` for a method that had consumed its
    full 150 s budget.
    """

    from CertiTherm.experiments import TimedResult, _optional_seconds

    assert _optional_seconds(TimedResult(None, None, "worker died")) == ""
    assert _optional_seconds(TimedResult(None, 12.5, "")) == 12.5
    assert _optional_seconds(TimedResult(None, 0.0, "")) == 0.0


def test_containment_failure_keeps_child_side_elapsed_time() -> None:
    """An escape must still report how long the method actually ran.

    The parent cannot measure it: futures are consumed in schedule order, so
    parent-side timing would include queueing and waiting on earlier futures.
    """

    import CertiTherm.experiments as experiments

    def exploding(_query, _method):
        _spin(0.15)
        raise RuntimeError("containment breached")

    original = experiments._dispatch_prepared_method
    experiments._dispatch_prepared_method = exploding
    try:
        result = experiments._evaluate_prepared_method((object(), "width"))
    finally:
        experiments._dispatch_prepared_method = original

    assert result.value is None
    assert result.seconds is not None and result.seconds >= 0.1
    # Labelled as a containment failure, NOT relabelled as an ordinary timeout:
    # the gate depends on telling those apart.
    assert result.error.startswith("method containment failure")


def test_alarm_during_exception_handling_does_not_escape(monkeypatch) -> None:
    """The one window the inner defences cannot close.

    A NON-timeout exception raised close to the deadline, with the alarm then
    delivered during the few bytecodes of the `except` body before it disarms.
    Pure Python cannot make that sequence atomic, so an outer guard converts it
    instead of letting it propagate.

    Simulated by delaying the disarm that the `except` body performs, which is
    what a descheduled process looks like to a pending signal.
    """

    real_setitimer = signal.setitimer
    widen = {"armed": True}

    def slow_setitimer(which, value, *rest):
        if widen["armed"] and value == 0:
            widen["armed"] = False
            _spin(0.3)
        return real_setitimer(which, value, *rest)

    def raises_other() -> None:
        _spin(0.05)
        raise ValueError("a different failure near the deadline")

    monkeypatch.setattr(signal, "setitimer", slow_setitimer)

    value, seconds, error = _call_under_budget(
        raises_other, 0.2, "exception-window budget exhausted"
    )

    assert value is None
    # Either the original error or the timeout is a legitimate report; raising
    # is not.
    assert error.startswith("ValueError") or error.startswith("TimeoutError")
