"""One call, under a deadline that neither escapes nor releases its caller's.

Two containment properties, both of which the implementation below previously broke and both of
which are load-bearing for the anytime gate. They are documented on the function because the
reasoning is what makes the three-layer defence look like anything other than paranoia.

Signals are process-global and only deliverable to the main thread, so this cannot be made
thread-safe -- `signal.signal` raises outside the main thread, before anything is armed, which is
the right failure. The driver oversubscribes PROCESSES, never threads, which is what makes it
usable at all.

Layer position: depends on the `solver_budget` leaf and on nothing else in this package.
`_budgeted_call` stays in `experiments` because tests patch it there.
"""

from __future__ import annotations

import signal
import time
from typing import Callable, Optional, TypeVar

from .solver_budget import budget_scope

_T = TypeVar("_T")


def call_under_budget(
    function: Callable[[], _T], budget_s: float, message: str
) -> tuple[Optional[_T], float, str]:
    """Run one call under a signal fallback and a native-solver deadline.

    Two containment properties, both of which this function previously broke.

    **The alarm must never escape.** Callers treat an escaping exception as a
    worker-protocol failure, which `_unexpected_method_failures` counts as
    UNEXPECTED and `AnytimeGateSummary.passes` hard-fails on -- so an ordinary
    timeout leaking out can fail a whole gate run. The timer used to stay armed
    until the `finally`, leaving the interval between entering the `finally` and
    disarming unguarded (the `except` has already been passed by then).
    Microseconds normally, but the v3.1 scheduler oversubscribes ~45 processes
    onto 52 cores, and a process descheduled in that interval sits there for
    milliseconds. It showed up on 2 of 6 rehearsal rows.

    Three defences, because none alone is airtight in pure Python: disarm
    *inside* the guarded region so a racing alarm is still caught; gate the
    handler on a completion flag so a later delivery is a no-op; and wrap the
    whole thing so anything that still escapes is converted rather than raised.
    The third matters for one residual sequence the first two cannot close -- a
    NON-timeout exception raised close to the deadline, with the alarm then
    delivered during the few bytecodes of the `except` body before it disarms.

    **The budget must actually bind.** Disarming unconditionally on exit meant a
    nested call that finished early cancelled its caller's deadline, after which
    the outer function ran unbounded and reported success -- measured at 3.01 s
    against a 0.3 s budget. The outer timer is therefore saved on entry and
    restored on exit, less the time this call consumed.
    """

    finished = False

    def expire(_signum, _frame) -> None:
        # A delivery after the guarded region is spent -- nothing left to
        # interrupt, and raising here would escape past every handler.
        if finished:
            return
        raise TimeoutError(message)

    def guarded() -> tuple[Optional[_T], float, str]:
        nonlocal finished
        try:
            with budget_scope(budget_s):
                value = function()
            # Disarmed INSIDE the try: an alarm racing this call is still
            # caught below and reported as an ordinary timeout.
            signal.setitimer(signal.ITIMER_REAL, 0)
            finished = True
            return value, time.perf_counter() - started, ""
        except Exception as exc:
            signal.setitimer(signal.ITIMER_REAL, 0)
            finished = True
            return None, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"

    # An outer budget still owns whatever time remains on it; this call may
    # tighten that deadline but must never extend or discard it.
    outer_remaining = signal.getitimer(signal.ITIMER_REAL)[0]
    effective = max(budget_s, 0.001)
    if outer_remaining > 0.0:
        effective = min(effective, outer_remaining)

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, effective)
    started = time.perf_counter()
    try:
        return guarded()
    except TimeoutError:
        return None, time.perf_counter() - started, f"TimeoutError: {message}"
    finally:
        finished = True
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if outer_remaining > 0.0:
            # Hand the outer deadline back, minus what this call used. An
            # already-expired outer budget must fire promptly rather than be
            # silently dropped, so it is rearmed at the smallest positive value.
            rest = outer_remaining - (time.perf_counter() - started)
            signal.setitimer(signal.ITIMER_REAL, rest if rest > 0.0 else 1e-6)
