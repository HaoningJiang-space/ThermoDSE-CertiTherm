"""The envelope properties a module-granularity coarsening would rest on, pinned first.

`docs/MODULE_GRANULARITY_ANALYSIS.md` proposes replacing per-block evaluation points with
per-module ones, and its soundness rests on three paired inequalities. Nothing implements the
coarsening yet. These tests exist BEFORE it, because the most expensive error in this project
was a structural argument that carried four commits and five reported numbers before anything
checked it (`docs/PER_CELL_DECOMPOSITION_RETRACTED.md`).

The properties, for a module whose blocks have rows `R` and ambients `a`, and non-negative
power `p`:

  * SAFE needs the elementwise MAX row and the LARGEST ambient. "Module envelope below the
    limit" must then imply every block in it is below.
  * REJECT needs the elementwise MIN row and the SMALLEST ambient. "Module envelope above the
    limit" must then imply some block in it is above.
  * Using the MAX envelope for both -- the tempting shortcut, since SAFE stays sound -- must
    NOT be usable, because the coarse safe set is then a strict subset of the true one and
    coarse collisions no longer cover true ones.

Every test here asserts non-vacuity first. An earlier ad-hoc check of exactly these properties
reported "confirmed" from four all-zero counters: the fixture's limit sat far above anything
the power box could reach, so every sample was safe under both classifications and nothing was
compared. A fixture that cannot fail proves nothing, and that check is now part of the tests
rather than a habit.
"""

from __future__ import annotations

import numpy as np
import pytest

LIMIT_MARGIN = 0.1
MODEL_ERROR = 0.05


def _module(seed: int, blocks: int = 4, dimension: int = 5):
    """Rows, ambients and a limit placed INSIDE the achievable peak range.

    The limit is the median achievable peak, so both classifications are populated. Inheriting
    a limit the power box cannot reach is what made the earlier ad-hoc check vacuous.
    """

    rng = np.random.default_rng(seed)
    rows = rng.uniform(0.5, 3.0, (blocks, dimension))
    ambient = rng.uniform(300.0, 320.0, blocks)
    peaks = [
        float((rows @ rng.uniform(0, 1, dimension) + ambient).max()) for _ in range(2000)
    ]
    return rows, ambient, float(np.median(peaks)), rng


def _true_safe(rows, ambient, limit, power):
    return bool(np.all(rows @ power + ambient <= limit - LIMIT_MARGIN - MODEL_ERROR))


def _true_reject(rows, ambient, limit, power):
    return bool(np.any(rows @ power + ambient >= limit + LIMIT_MARGIN - MODEL_ERROR))


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_upper_envelope_is_fail_closed_for_safe(seed: int) -> None:
    """Max row and max ambient: coarsely safe must imply every block truly safe."""

    rows, ambient, limit, rng = _module(seed)
    upper, upper_ambient = rows.max(axis=0), float(ambient.max())
    coarse_safe = true_safe = violations = 0
    for _ in range(3000):
        power = rng.uniform(0, 1, rows.shape[1])
        coarse = bool(upper @ power + upper_ambient <= limit - LIMIT_MARGIN - MODEL_ERROR)
        truth = _true_safe(rows, ambient, limit, power)
        coarse_safe += coarse
        true_safe += truth
        violations += coarse and not truth
    assert coarse_safe > 0, "no sample was coarsely safe; the fixture cannot detect a failure"
    assert true_safe > 0, "no sample was truly safe; the fixture is degenerate"
    assert violations == 0, (
        f"{violations} samples were coarsely safe with a block above the limit; the upper "
        "envelope is not fail-closed for SAFE and the coarsening would certify falsely"
    )


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4, 5])
def test_the_lower_envelope_is_too_weak_to_populate_reject(seed: int) -> None:
    """The finding that kills the proposal, and the reason it is not a fixture problem.

    The lower envelope is elementwise MIN over a module's rows, so it is far below any single
    row. Measured across six modules its temperature rise is a median 47% of the true peak
    rise, which means a power map would need roughly twice the power it actually takes to
    reject before the envelope agreed. Under a bounded power polytope the coarse REJECT set is
    then nearly empty -- no reject worlds, no collisions, and a coarsened instance that
    certifies at zero cost while proving nothing.

    Soundness was never the problem: the lower envelope IS fail-closed for REJECT. It is
    useless, which a soundness argument alone would never have revealed. That is why this was
    written as a test before the coarsening was implemented.
    """

    rows, ambient, limit, rng = _module(seed)
    lower = rows.min(axis=0)
    power = rng.uniform(0, 1, (4000, rows.shape[1]))
    true_rise = (power @ rows.T).max(axis=1)
    lower_rise = power @ lower
    ratio = float(np.median(lower_rise) / np.median(true_rise))
    assert 0.0 < ratio < 0.75, (
        f"the lower envelope reached {ratio:.0%} of the true peak rise; if it were close to "
        "the truth the proposal would be viable and this test should be revisited"
    )

    lower_ambient = float(ambient.min())
    rejects = sum(
        bool(lower @ p + lower_ambient >= limit + LIMIT_MARGIN - MODEL_ERROR)
        for p in power[:2000]
    )
    truly = sum(_true_reject(rows, ambient, limit, p) for p in power[:2000])
    assert truly > 0, "the fixture has no truly rejecting world; it cannot show the gap"
    assert rejects == 0, (
        f"the lower envelope rejected {rejects} worlds where it was expected to reject none; "
        "the emptiness finding does not hold on this fixture"
    )


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_the_upper_envelope_shortcut_loses_true_safe_worlds(seed: int) -> None:
    """Why 'upper envelope for both' cannot be used, even though SAFE stays sound.

    The coarse safe set is a STRICT subset of the true one, so true collisions involving the
    lost worlds never appear in the coarse problem and separating every coarse collision
    implies nothing about the true instance.
    """

    rows, ambient, limit, rng = _module(seed)
    upper, upper_ambient = rows.max(axis=0), float(ambient.max())
    lost = coarse_only = 0
    for _ in range(3000):
        power = rng.uniform(0, 1, rows.shape[1])
        coarse = bool(upper @ power + upper_ambient <= limit - LIMIT_MARGIN - MODEL_ERROR)
        truth = _true_safe(rows, ambient, limit, power)
        lost += truth and not coarse
        coarse_only += coarse and not truth
    assert coarse_only == 0, "the upper envelope admitted an unsafe world as safe"
    assert lost > 0, (
        "the coarse safe set matched the true one on this fixture, so it shows nothing "
        "about the shortcut; a fixture where they coincide cannot support the rejection"
    )


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_the_upper_envelope_shortcut_also_invents_reject_worlds(seed: int) -> None:
    """The other half of non-comparability, which the SAFE-loss test alone does not show.

    Peer review corrected the reason this shortcut is rejected. Losing true-safe worlds shows
    the upper/upper collision set is not a superset; it does not show it is not a subset
    either. The missing half is that the upper envelope also calls worlds rejecting that no
    block rejects, which manufactures collisions with no counterpart in the true problem.

    With both halves the two collision sets are incomparable in either direction, so the
    upper/upper instance is neither a sufficient plan nor a lower bound -- a strictly stronger
    conclusion than "it loses safe worlds".
    """

    rows, ambient, limit, rng = _module(seed)
    upper, upper_ambient = rows.max(axis=0), float(ambient.max())
    power = rng.uniform(0, 1, (6000, rows.shape[1]))

    invented = sum(
        bool(upper @ p + upper_ambient >= limit + LIMIT_MARGIN - MODEL_ERROR)
        and not _true_reject(rows, ambient, limit, p)
        for p in power
    )
    assert invented > 0, (
        "no world rejected coarsely without rejecting truly; this fixture cannot show that "
        "the upper envelope invents reject worlds"
    )
