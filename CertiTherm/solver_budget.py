"""End-to-end deadlines for SciPy/HiGHS calls.

Python signals are only a fallback interrupt: a signal handler cannot run while
HiGHS is inside a long C++ presolve.  This module keeps the absolute Python
deadline in a context variable and also passes the remaining time to HiGHS's
native ``time_limit`` option.  The two mechanisms protect different layers;
neither changes the LP or MILP being solved.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import math
import signal
import time
from typing import Callable, Dict, Iterator, Mapping, Optional


@dataclass(frozen=True)
class _BudgetState:
    deadline_s: float
    return_reserve_s: float


_ACTIVE_BUDGET: ContextVar[Optional[_BudgetState]] = ContextVar(
    "certitherm_solver_budget",
    default=None,
)


def _return_reserve(seconds: float) -> float:
    """Leave a small, bounded interval for fail-closed result construction."""

    return min(1.0, max(0.01, 0.01 * seconds))


@contextmanager
def budget_scope(seconds: float) -> Iterator[None]:
    """Publish an absolute method deadline to every nested solver call.

    A nested scope may tighten an outer deadline but can never extend it.
    Signal installation remains in the experiment controller; keeping this
    context independent makes it usable by tests and library callers too.
    """

    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("solver budget must be finite and positive")
    proposed = _BudgetState(
        deadline_s=time.monotonic() + seconds,
        return_reserve_s=_return_reserve(seconds),
    )
    parent = _ACTIVE_BUDGET.get()
    state = (
        parent
        if parent is not None and parent.deadline_s <= proposed.deadline_s
        else proposed
    )
    token = _ACTIVE_BUDGET.set(state)
    try:
        yield
    finally:
        _ACTIVE_BUDGET.reset(token)


@contextmanager
def override_budget(seconds: float) -> Iterator[None]:
    """Install a FRESH deadline, ignoring any (possibly expired) parent.

    `budget_scope` only ever tightens toward the parent, so once a method's
    budget has expired nothing nested under it can run -- every solve raises
    "method budget exhausted before solver launch". That is correct while the
    method is executing, but wrong for the one bounded solve a timed-out run
    still owes: the final anytime-lower-bound refresh over the cuts already in
    hand. Starving it made a 300 s run report a lower bound of 5.0 when its
    accumulated cuts justified 20.1.

    This replaces the active deadline outright rather than tightening toward it,
    so the refresh gets a small, independent, still-fail-closed budget. Use it
    only for bounded, deterministic cleanup work after a deadline has passed.
    """

    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("solver budget must be finite and positive")
    state = _BudgetState(
        deadline_s=time.monotonic() + seconds,
        return_reserve_s=_return_reserve(seconds),
    )
    token = _ACTIVE_BUDGET.set(state)
    try:
        yield
    finally:
        _ACTIVE_BUDGET.reset(token)


def _signal_budget() -> Optional[_BudgetState]:
    """Fallback for callers that install ITIMER_REAL without ``budget_scope``."""

    try:
        remaining_s, _interval_s = signal.getitimer(signal.ITIMER_REAL)
    except (AttributeError, ValueError):
        return None
    if remaining_s <= 0:
        return None
    return _BudgetState(
        deadline_s=time.monotonic() + remaining_s,
        return_reserve_s=_return_reserve(remaining_s),
    )


def _current_budget() -> Optional[_BudgetState]:
    contextual = _ACTIVE_BUDGET.get()
    signalled = _signal_budget()
    if contextual is None:
        return signalled
    if signalled is None or contextual.deadline_s <= signalled.deadline_s:
        return contextual
    return signalled


def highs_options(
    options: Optional[Mapping[str, object]] = None,
    *,
    label: str = "HiGHS solve",
) -> Dict[str, object]:
    """Return solver options capped by the active end-to-end deadline."""

    merged: Dict[str, object] = dict(options or {})
    state = _current_budget()
    if state is None:
        return merged

    available_s = state.deadline_s - time.monotonic() - state.return_reserve_s
    if available_s <= 0:
        raise TimeoutError(f"{label}: method budget exhausted before solver launch")

    configured = merged.get("time_limit")
    if configured is not None:
        configured_s = float(configured)
        if not math.isfinite(configured_s) or configured_s <= 0:
            raise ValueError("HiGHS time_limit must be finite and positive")
        available_s = min(available_s, configured_s)
    merged["time_limit"] = available_s
    return merged


def run_highs(
    solver: Callable[..., object],
    *args: object,
    label: str,
    options: Optional[Mapping[str, object]] = None,
    **kwargs: object,
) -> object:
    """Run one SciPy HiGHS solve under the active native deadline.

    Only a native HiGHS time-limit result is translated to ``TimeoutError``.
    Infeasibility, numerical failure, and malformed inputs retain their normal
    status/exception semantics for the caller's fail-closed classifier.
    """

    result = solver(
        *args,
        options=highs_options(options, label=label),
        **kwargs,
    )
    status = getattr(result, "status", None)
    message = str(getattr(result, "message", ""))
    if status == 1 and "time limit reached" in message.lower():
        raise TimeoutError(f"{label}: native HiGHS time limit reached")
    return result
