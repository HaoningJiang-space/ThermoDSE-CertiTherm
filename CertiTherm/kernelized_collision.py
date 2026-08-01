"""The kernelized collision search: a research extension, not the certified oracle.

`_collision_search` in `synthesis` is the authoritative exhaustive oracle. This module holds
the optional accelerated path that uses a `VerifiedThermalKernel` to restrict the SAFE rows
and REJECT specs, plus the instrumentation counting how often it pays off. Its only
non-test consumer is `research/triangle/upper_bound.py`; nothing in `experiments.py`, exact
synthesis or the frozen policies reaches it.

Why it lives here rather than in `synthesis`. Peer review objected that the authoritative
oracle had come to call `_build_collision_problem`, whose `safe_row_indices` parameter exists
only for this extension -- the baseline was entering an extension-shaped interface, which
weakens the frozen-oracle audit boundary. The dependency now runs one way only: this module
imports the shared LP assembly and worker entry points from `synthesis`, and `synthesis`
imports nothing from here. Removing this file would leave the certified path intact.

The process-pool entry points (`_initialize_collision_worker`, `_solve_collision_worker`)
deliberately stay in `synthesis` and are imported: a spawn pool pickles them by qualified
name, so they must live in exactly one importable module and must not be wrapped.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from typing import Iterable, Optional, Sequence

import numpy as np

from .core import MeasurementAction, PowerPolytope, ThermalFamily, WorldPair
from .thermal_constraints import robust_safe_cell_rows
from .synthesis import (
    _build_collision_problem,
    _collision,
    _configured_workers,
    _initialize_collision_worker,
    _solve_collision_spec,
    _solve_collision_worker,
)
from .thermal_kernel import ThermalKernelError


def reset_kernel_oracle_stats() -> None:
    """Zero the counters.

    Restored after peer review pointed out that deleting it was an incomplete cleanup:
    the counters are process-global and cumulative, so a caller invoking a driver twice in
    one interpreter contaminated the second reading. A single CLI run gets a fresh process
    and does not need this; anything that runs the search more than once per process does.
    """

    for key in _KERNEL_ORACLE_STATS:
        _KERNEL_ORACLE_STATS[key] = 0


# Instrumentation for the item-2 gate: how many kernelized queries reach the pool
# (a NEGATIVE first-cell probe) vs resolve at the probe. Persistence only helps the
# pool-reaching ones. Additive; does not affect the frozen oracle or any verdict.
_KERNEL_ORACLE_STATS = {"queries": 0, "probe_resolved": 0, "pool_reached": 0, "sequential": 0}


def kernel_oracle_stats() -> dict:
    return dict(_KERNEL_ORACLE_STATS)


class KernelValidationError(Exception):
    """A kernelized collision witness failed validation against the FULL SAFE rows,
    so the kernel result cannot be trusted. The caller must re-run the authoritative
    baseline oracle. This is NOT an UnresolvedComputation -- the instance is fine,
    only the kernel short-cut is; degrade to baseline, do not fail closed."""


def _full_safe_satisfied(
    safe_world: np.ndarray, thermal: ThermalFamily, margin_k: float, tolerance: float
) -> bool:
    """True iff `safe_world` obeys EVERY (full, unkernelized) robust-SAFE row to
    tolerance. The kernel drops SAFE rows it proved redundant; this re-checks the
    dropped ones on the returned witness, so an audit/cache error that dropped a
    binding row is caught (defence-in-depth on top of the monotonicity theorem)."""
    rows, rhs = robust_safe_cell_rows(thermal, margin_k)
    return bool(np.all(rows @ np.asarray(safe_world, dtype=float) <= rhs + tolerance))


def _collision_search_kernelized(
    polytope: PowerPolytope,
    thermal: ThermalFamily,
    actions: Sequence[MeasurementAction],
    selected: Iterable[int],
    margin_k: float,
    feasibility_tolerance: float,
    workers: Optional[int],
    kernel,
) -> Optional[WorldPair]:
    """First collision using a VerifiedThermalKernel: the collision LP is built with
    only the kernel's SAFE-row subset and only the kernel's REJECT specs. Sibling of
    `_collision_search`, which remains the authoritative exhaustive fallback.

    This used to claim the fallback was "left byte-for-byte unchanged". That stopped being
    true when both searches were moved onto `_build_collision_problem`; the claim is
    withdrawn rather than restated, because what protects the fallback now is not textual
    identity but a field-by-field differential against its former inline construction over
    1 500 random instances. The remaining audit concern is real and unresolved: the
    authoritative oracle now calls a builder whose `safe_row_indices` parameter exists only
    for this extension. Moving the kernelized search into its own module -- so the
    dependency runs extension -> shared algebra rather than baseline -> extension-shaped
    interface -- is the fix, and is not done yet.

    NON-EXHAUSTIVE existence only (the deletion path): returns the first collision or
    None. A None result is trusted ONLY for a structurally valid, correctly bound,
    theorem-valid kernel: soundness rests on the monotonicity theorem, whose dominance
    is POINTWISE -- the same `p_unsafe` that rejects at a dropped cell also rejects at
    a retained cell, so the identical `(p_safe, p_unsafe)` pair (and its
    indistinguishability) is a collision at a retained cell; nothing transforms either
    world. A corrupted same-binding kernel could still return a false None (no witness
    to check), which is why the artifact is validated and bound. Every POSITIVE witness
    IS validated against the FULL SAFE rows; a failure raises `KernelValidationError`.
    Never used with `exhaustive=True` -- restricting specs changes the witness set."""
    kernel.validate_binding(polytope, thermal, margin_k, feasibility_tolerance)
    problem = _build_collision_problem(
        polytope, thermal, actions, selected, margin_k, feasibility_tolerance,
        safe_row_indices=kernel.safe_row_indices,           # SAFE-row subset
    )
    specs = tuple(kernel.reject_specs)                          # REJECT-cell subset (lexicographic)
    if not specs:
        # a valid artifact never has empty reject_specs; if one reaches here treat it
        # as a kernel fault (degrade to baseline), not a fail-closed UNRESOLVED.
        raise KernelValidationError("kernel has no reject specs to separate")
    worker_count = min(_configured_workers(workers), len(specs))

    def _validated(pair: Optional[WorldPair]) -> Optional[WorldPair]:
        if pair is not None and not _full_safe_satisfied(
            pair.safe_power_w, thermal, margin_k, feasibility_tolerance
        ):
            raise KernelValidationError(
                "kernel collision witness violates a full SAFE row; use the baseline")
        return pair

    _KERNEL_ORACLE_STATS["queries"] += 1
    if worker_count == 1:
        _KERNEL_ORACLE_STATS["sequential"] += 1
        for spec in specs:
            pair = _validated(_solve_collision_spec(problem, spec))
            if pair is not None:
                return pair
        return None

    probe = _validated(_solve_collision_spec(problem, specs[0]))
    if probe is not None:
        _KERNEL_ORACLE_STATS["probe_resolved"] += 1     # resolved without the pool
        return probe
    _KERNEL_ORACLE_STATS["pool_reached"] += 1           # a pool-using query (item-2 N)
    remaining = specs[1:]
    if not remaining:
        return None
    # item-2 prototype: CERTITHERM_ORACLE_BACKEND=thread shares the matrices with no
    # process spawn/pickle (review's preferred candidate at ~48 cells). Both backends
    # return the FIRST collision in canonical spec order (never completion order).
    if os.environ.get("CERTITHERM_ORACLE_BACKEND", "process") == "thread":
        from concurrent.futures import ThreadPoolExecutor
        # THREAD-SAFETY (review): threads share `problem` read-only.
        # `_solve_collision_spec` was audited reentrant -- it only READS problem.*
        # and builds fresh local arrays (concatenate/vstack/append/.copy()), never
        # mutating shared state, and returns None ONLY for a proved-infeasible status
        # (2), raising on any numerical/limit failure (no false None). As
        # defence-in-depth, mark the shared arrays non-writable so an accidental
        # in-place mutation (or a native call handed a writable buffer) fails loudly
        # instead of silently corrupting a concurrent solve. Process workers get
        # pickled COPIES, so this is only needed here.
        #
        # The list below is exactly the arrays this function ASSEMBLES. `response`,
        # `ambient` and `error_k` are absent because they are the ThermalFamily's own
        # arrays, sealed by `core._sealed` at construction -- a list here would have
        # protected this one call site, whereas sealing at the source protects every
        # holder of them. Peer review found those three unprotected when this list was
        # the only guard.
        for _arr in (
            problem.objective,
            problem.common_a_ub,
            problem.common_b_ub,
            problem.a_eq,
            problem.b_eq,
        ):
            _arr.flags.writeable = False
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            for item in pool.map(lambda s: _solve_collision_spec(problem, s), remaining):
                validated = _validated(item)
                if validated is not None:
                    return validated
        return None
    with ProcessPoolExecutor(
        max_workers=worker_count, mp_context=get_context("spawn"),
        initializer=_initialize_collision_worker, initargs=(problem,),
    ) as pool:
        for start in range(0, len(remaining), worker_count):
            batch = tuple(pool.map(_solve_collision_worker,
                                   remaining[start : start + worker_count]))
            for item in batch:
                if item is not None:
                    return _validated(item)
    return None


def first_collision(
    polytope: PowerPolytope,
    thermal: ThermalFamily,
    actions: Sequence[MeasurementAction],
    selected: Iterable[int],
    margin_k: float,
    feasibility_tolerance: float,
    workers: Optional[int] = None,
    kernel=None,
) -> Optional[WorldPair]:
    """Degrade-to-baseline entry for the deletion path: with `kernel=None` (default)
    this is exactly `_collision`. With a VerifiedThermalKernel it runs the kernelized
    sibling; on a binding mismatch or a positive-witness validation failure it falls
    back to the authoritative baseline `_collision`. Guarantee: a DETECTED kernel
    problem (bad binding, false positive) only makes the query slower, never wrong. A
    same-binding but corrupted kernel that returns a false None is NOT caught here --
    that is the artifact's binding/validity contract, not this fallback's job."""
    # Materialise `selected` ONCE: the kernel path consumes it building action rows,
    # and the baseline fallback must see the SAME actions (a one-shot iterator would
    # otherwise reach the baseline exhausted -> no actions -> a changed verdict).
    selected = tuple(selected)
    if kernel is None:
        return _collision(polytope, thermal, actions, selected, margin_k,
                          feasibility_tolerance, workers)
    try:
        return _collision_search_kernelized(polytope, thermal, actions, selected,
                                            margin_k, feasibility_tolerance, workers, kernel)
    except (KernelValidationError, ThermalKernelError):
        return _collision(polytope, thermal, actions, selected, margin_k,
                          feasibility_tolerance, workers)
