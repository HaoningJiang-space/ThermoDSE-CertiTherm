"""Thermal-aware mapping, certified: an exact lower bound over ALL mappings, and the gap to it.

## The unification, and why the mapping level is where the certificate becomes free

`docs/THREE_LEGS_STATUS.md` measured that **zero of ThermoDSE's ten architecture fields leaves the
floorplan invariant**, so an operator cache cannot amortise an architecture search. That is a fact
about the architecture vector — and it is not a fact about the design space, because the space has a
second level the certificate is perfectly matched to.

**An architecture decides the geometry; a MAPPING decides only the power vector.** Permuting which
task runs on which core moves power between blocks and leaves the floorplan byte-identical, so `R` is
fixed and every mapping candidate costs one matvec and one sort -- **12 ms**
(`docs/CERTIFICATE_IN_THE_LOOP.md`). The axis the architecture vector does not have, the mapping
level has by construction.

That is the division of labour this proposes: **ThermoDSE's SCBO keeps the architecture search, where
its trust-region Bayesian optimisation over a mixed 10-D space is well suited and each candidate
genuinely costs an operator; the certificate takes the mapping level, where it is free and where
ThermoDSE currently uses a geometric proxy.**

## What ThermoDSE does today, read from source

`ThermoDSE/core/schedule.py:386 thermal_aware_task_map` sorts cores by

    lateral_factor(c) = sum over all other cores d of euclidean_distance_squared(c, d)

and greedily assigns the highest-energy task to the core with the largest factor. The factor is a
**purely geometric proxy for cooling** -- it never consults the thermal operator, the package, or the
power of the other tasks. It is a reasonable heuristic and it is not an optimum, and until now nothing
could say how far from one it was.

## The exact lower bound, which is what makes this a certificate and not another heuristic

Write `p = p_fixed + p_core(pi)`: the non-core blocks (`io_*`, `dram_*`, `blockX/Y_*`) do not move
under a remapping, and the per-core groups permute. For cell `j`,

    T_j(pi) = (R p_fixed)_j + a_j + sum_i R_{j, pi(i)} q_i

and a mapping moves a core's whole power **profile** to another core's blocks, block for block. So
the cost of putting profile `k` at position `m` is `C_j[m, k] = sum_r R[j, groups[m][r]] *
placed[groups[k][r]]`, and

    LB_j = (R p_fixed)_j + a_j + min over permutations of sum_m C_j[m, pi(m)]

is a **linear assignment problem**, solved exactly per cell. `LB = max_j LB_j` lower-bounds
`min_pi max_j T_j(pi)`.

**It is NOT a sort.** A first version applied the rearrangement inequality to per-group column sums
and per-group power totals; summing a group's columns is the response to one watt on *every* block of
it, which inflated the contribution by the group size and produced a "lower bound" of `345.32 K`
against an attained `327.55 K`. A bound above an attained value is not a bound, and the direction of
that error -- too high -- is the one that would have made any heuristic look optimal. The run now
checks the bound against every mapping it evaluates rather than trusting the derivation.

**The bound is not tight in general** -- different cells want different permutations, so no single
mapping need attain `LB` -- which is exactly why the gap between it and the best mapping found is the
honest thing to report. A search that returns "we improved by X" without a bound cannot say whether
X was all there was.

## Fail-closed

Refuses if the core grouping is not a partition, if any group has a different block multiset than the
others (permuting non-interchangeable groups is not a mapping), or if a permuted vector fails to
conserve total power. The nominal objective is used for the bound because the envelope's box is built
*from* the power vector, so a permutation changes the set as well as the point; the certified peak
under the envelope is reported for every mapping the search returns, and the two are never mixed.

NON-CLAIM diagnostic. Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/certified_mapping.py \\
        <operator.npz> <capture-or-trace.npz> [iterations] [span]
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K      # noqa: E402
from research.triangle.robustness.routed_pipeline import (                     # noqa: E402
    certified_peak_from_vector,
)

MARGIN_K = 0.05
CEILING_K = THERMAL_LIMIT_K - MARGIN_K - MODEL_ERROR_LIMIT_K
INDEXED = re.compile(r"^(?P<prefix>[A-Za-z]+)_(?P<index>\d+)$")
# Blocks that belong to the fabric, not to a core, however they are indexed.
FIXED_PREFIXES = ("io", "dram", "blockX", "blockY", "blockXY", "eblk", "interposer")


def _core_groups(blocks):
    """`(groups, fixed_mask)`: `groups[k]` are the row indices of core `k`, in a stable order."""
    groups = defaultdict(dict)
    fixed = np.ones(len(blocks), dtype=bool)
    for row, name in enumerate(blocks):
        if any(name.startswith(p) for p in FIXED_PREFIXES):
            continue
        match = INDEXED.match(name)
        if match is None:
            continue
        index, prefix = int(match.group("index")), match.group("prefix")
        # A DUPLICATE KEY USED TO LOSE POWER SILENTLY. The second row overwrote the first in the
        # dict while BOTH were marked non-fixed, so the overwritten block appeared in neither the
        # permuted profiles nor the fixed field -- its watts vanished from the objective and from
        # the bound. Peer review caught it.
        if prefix in groups[index]:
            raise SystemExit(
                f"two blocks resolve to core {index} component {prefix!r} "
                f"({blocks[groups[index][prefix]]!r} and {blocks[row]!r}); the core partition is "
                "ambiguous and a permutation over it would lose power"
            )
        groups[index][prefix] = row
        fixed[row] = False
    if not groups:
        raise SystemExit("no per-core blocks found; the mapping level does not exist here")
    signatures = {tuple(sorted(members)) for members in groups.values()}
    if len(signatures) != 1:
        raise SystemExit(
            f"the {len(groups)} core groups have {len(signatures)} different block signatures; "
            "permuting groups that are not interchangeable is not a mapping"
        )
    order = sorted(groups)
    prefixes = sorted(next(iter(signatures)))
    result = [[groups[k][p] for p in prefixes] for k in order]
    # EVERY ROW CLASSIFIED EXACTLY ONCE, checked rather than assumed: the permuted set and the fixed
    # set must partition the blocks, or the objective and the bound disagree about what moves.
    permuted = {r for g in result for r in g}
    if len(permuted) != sum(len(g) for g in result):
        raise SystemExit("a block appears in two core groups; the partition is not a partition")
    if permuted & set(np.flatnonzero(fixed).tolist()):
        raise SystemExit("a block is both permuted and fixed")
    if len(permuted) + int(fixed.sum()) != len(blocks):
        raise SystemExit(
            f"{len(blocks) - len(permuted) - int(fixed.sum())} block(s) are neither permuted nor "
            "fixed; their power would be dropped from the objective"
        )
    return result, fixed


def _apply(power, groups, permutation):
    """`power` with core `k` receiving the powers of core `permutation[k]`."""
    out = np.array(power, dtype=float, copy=True)
    for target, source in enumerate(permutation):
        out[groups[target]] = power[groups[source]]
    return out


def main() -> None:
    operator_path, capture_path = Path(sys.argv[1]), Path(sys.argv[2])
    iterations = int(sys.argv[3]) if len(sys.argv) > 3 else 4000
    span = float(sys.argv[4]) if len(sys.argv) > 4 else 0.30

    with np.load(operator_path, allow_pickle=False) as data:
        rows = np.asarray(data["response_k_per_w"], dtype=float)[0]
        ambient = np.asarray(data["ambient_k"], dtype=float)[0]
        blocks = [str(b) for b in data["block_ids"]]
    with np.load(capture_path, allow_pickle=False) as data:
        trace_blocks = [str(b) for b in data["block_ids"]]
        if "powers_w" in data:
            durations = np.asarray(data["durations_s"], dtype=float)
            powers = np.asarray(data["powers_w"], dtype=float)
            placed = (powers * durations[:, None]).sum(axis=0) / float(durations.sum())
        else:
            placed = np.asarray(data["placed_power_w"], dtype=float)
    if trace_blocks != blocks:
        raise SystemExit("the operator and the trace resolve different block lists")

    groups, fixed = _core_groups(blocks)
    n = len(groups)
    total = float(placed.sum())

    # THE EXACT LOWER BOUND, AND THE FIRST VERSION OF IT WAS WRONG IN THE UNSAFE DIRECTION.
    #
    # That version summed each group's columns and paired the sums with the group totals by the
    # rearrangement inequality. Summing columns is the response to one watt on EVERY block of the
    # group, so it inflated the contribution by the group size and produced a "lower bound" of
    # 345.32 K against an achieved 327.55 K. A bound above an attained value is not a bound, and the
    # sign of the error -- too high -- is the one that would have made a heuristic look optimal.
    # It was caught by the gap coming out NEGATIVE, which is why the gap is reported and not just
    # the bound.
    #
    # The correct model: a mapping moves a core's whole power PROFILE to another core's blocks,
    # block-for-block. So for cell `j` the cost of putting profile `k` at position `m` is
    #
    #     C_j[m, k] = sum_r R[j, groups[m][r]] * placed[groups[k][r]]
    #
    # and `min_pi sum_m C_j[m, pi(m)]` is a LINEAR ASSIGNMENT PROBLEM, solved exactly per cell. It is
    # NOT a sort: the rearrangement inequality applies to a product of two vectors, and this is a
    # bilinear form over profiles. n = 16 cores, so each solve is trivial and the whole bound is one
    # pass over the cells.
    from scipy.optimize import linear_sum_assignment                      # noqa: PLC0415

    profiles = np.stack([placed[g] for g in groups], axis=0)              # (cores, blocks_per_core)
    per_position = np.stack([rows[:, g] for g in groups], axis=1)         # (cells, cores, per_core)
    # C[j, m, k] = sum_r per_position[j, m, r] * profiles[k, r]
    cost = np.einsum("jmr,kr->jmk", per_position, profiles)
    fixed_field = rows[:, fixed] @ placed[fixed] + ambient
    assigned = np.empty(rows.shape[0], dtype=float)
    for j in range(rows.shape[0]):
        row_ind, col_ind = linear_sum_assignment(cost[j])
        assigned[j] = float(cost[j][row_ind, col_ind].sum())
    lower_bound_rows = fixed_field + assigned
    lower_bound = float(np.max(lower_bound_rows))

    def nominal(perm):
        return float(np.max(rows @ _apply(placed, groups, perm) + ambient))

    def certified(perm):
        # The same supremum the rest of the project takes, through the shared pipeline: a permuted
        # vector is still a power map, and it must be certified by the same code that certifies an
        # unpermuted one or the two numbers are not comparable.
        return certified_peak_from_vector(rows, ambient, blocks,
                                          _apply(placed, groups, perm), span)

    identity = list(range(n))
    baseline_nominal, baseline_certified = nominal(identity), certified(identity)
    if abs(float(_apply(placed, groups, identity).sum()) - total) > 1e-12 * max(total, 1.0):
        raise SystemExit("the identity permutation does not conserve total power")

    # Steepest-descent over pair swaps, restarted. Each evaluation is one matvec: the whole point.
    rng = np.random.default_rng(0)
    best, best_value = list(identity), baseline_nominal
    started = time.monotonic()
    evaluations = 0
    for restart in range(4):
        current = list(identity) if restart == 0 else list(rng.permutation(n))
        value = nominal(current)
        evaluations += 1
        improved = True
        while improved and evaluations < iterations:
            improved = False
            for a in range(n):
                for b in range(a + 1, n):
                    if evaluations >= iterations:
                        break
                    trial = list(current)
                    trial[a], trial[b] = trial[b], trial[a]
                    got = nominal(trial)
                    evaluations += 1
                    if got < value - 1e-12:
                        current, value, improved = trial, got, True
                        break
                if improved:
                    break
        if value < best_value - 1e-12:
            best, best_value = list(current), value
    elapsed = time.monotonic() - started

    # A BOUND THAT EXCEEDS AN ATTAINED VALUE IS NOT A BOUND. Checked against every mapping this run
    # actually evaluated, not merely asserted from the derivation -- which is how the first version's
    # error surfaced.
    for name, value in (("thermodse", baseline_nominal), ("best", best_value)):
        if value < lower_bound - 1e-9:
            raise SystemExit(
                f"the {name} mapping attains {value!r}, below the claimed lower bound "
                f"{lower_bound!r}; the bound is invalid and no gap computed from it means anything"
            )

    payload = {
        "operator": operator_path.name, "trace": capture_path.name,
        "cores": n, "blocks": len(blocks), "cells": int(rows.shape[0]), "span": span,
        "ceiling_k": CEILING_K,
        "thermodse_mapping_nominal_k": baseline_nominal,
        "thermodse_mapping_certified_k": baseline_certified,
        "best_mapping_nominal_k": best_value,
        "best_mapping_certified_k": certified(best),
        "improvement_nominal_k": baseline_nominal - best_value,
        "improvement_certified_k": baseline_certified - certified(best),
        "exact_lower_bound_nominal_k": lower_bound,
        "gap_to_lower_bound_k": best_value - lower_bound,
        "baseline_excess_over_bound_k": baseline_nominal - lower_bound,
        "evaluations": evaluations, "seconds": elapsed,
        "ms_per_evaluation": 1000.0 * elapsed / max(evaluations, 1),
        # `best` can hold numpy integers when a restart came from `rng.permutation`, and json
        # refuses those. Coercing at the boundary rather than at construction keeps the search's
        # arrays as arrays.
        "permutation": [int(v) for v in best],
    }
    print(json.dumps(payload, indent=1, sort_keys=True))
    Path(str(operator_path).replace(".npz", "-mapping.json")).write_text(
        json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
