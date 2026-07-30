"""Input validation and outer-timer fidelity for `call_under_budget`.

The containment contract itself -- the alarm never escaping, a nested call never cancelling its
caller's deadline -- is already covered in depth by `test_budget_containment.py`, which was written
from the v3.1 rehearsal failures. This file deliberately does NOT repeat those; it covers only the
two properties peer review found missing when the function moved into its own module, plus the
handler-restoration behaviour they depend on.

Both gaps have the same shape as bugs already fixed elsewhere in this package: a non-finite value
slipping through a comparison-based guard, and state mutated before the `try` that restores it.
"""

from __future__ import annotations

import signal

import pytest

from CertiTherm.budget_guard import call_under_budget


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), 0.0, -1.0])
def test_a_non_finite_or_nonpositive_budget_is_refused(bad: float) -> None:
    """NaN makes every comparison False, so `setitimer` would raise with the handler installed.

    Infinity is worse in kind: it arms a timer that never fires, which is a deadline that does not
    bind while looking like one. Neither is reachable from the CLI today, and both are one
    arithmetic slip away in a caller that computes a remaining budget.
    """

    with pytest.raises(ValueError, match="finite and positive"):
        call_under_budget(lambda: 1, bad, "x")


def test_a_refused_budget_leaves_the_signal_state_untouched() -> None:
    """Validation happens before any mutation, so a refusal cannot disturb an outer deadline."""

    before = signal.getsignal(signal.SIGALRM)
    with pytest.raises(ValueError):
        call_under_budget(lambda: 1, float("nan"), "x")
    assert signal.getsignal(signal.SIGALRM) is before
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
    # Non-vacuity: a valid budget does run, so the assertions above are about the refusal path and
    # not about this function being inert.
    assert call_under_budget(lambda: "ok", 5.0, "x")[0] == "ok"


def test_the_outer_repeat_interval_survives_the_call() -> None:
    """Restoring only the delay silently turned a periodic outer timer into a one-shot.

    `getitimer` returns `(delay, interval)`; only the delay was saved and handed back, so an
    enclosing periodic timer would fire once more and then never again.
    """

    signal.signal(signal.SIGALRM, lambda *_args: None)
    signal.setitimer(signal.ITIMER_REAL, 5.0, 2.5)
    try:
        call_under_budget(lambda: "x", 1.0, "x")
        delay, interval = signal.getitimer(signal.ITIMER_REAL)
        assert interval == pytest.approx(2.5), "the outer repeat interval was discarded"
        assert 0.0 < delay <= 5.0, "the outer delay was not handed back"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, signal.SIG_DFL)


def test_the_driver_still_exposes_the_name_its_callers_import() -> None:
    """Four callers import `_call_under_budget` from `experiments`; it is not monkeypatched."""

    from CertiTherm import budget_guard, experiments

    assert experiments._call_under_budget is budget_guard.call_under_budget
