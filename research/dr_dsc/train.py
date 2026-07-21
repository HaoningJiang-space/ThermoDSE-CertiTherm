"""Outer training loop: adversarial constraint generation with a
gradient-trained gate replacing `CertiTherm.synthesis._greedy_cover`'s
deterministic heuristic as the pre-exact-closure proposal generator.

Loop:
  1. the exact oracle (oracle.find_witness) finds a surviving collision
     against the CURRENT rounded action selection -- treated as a fixed
     constant, no gradient flows through it;
  2. gate logits take gradient steps to increase the soft, worst-case
     coverage (gate.soft_min) of every witness collected so far, minus a
     cost term;
  3. gates are rounded to a discrete selection and re-checked exactly; a
     still-surviving collision becomes a new pooled witness (back to 1),
     otherwise the discrete selection is exact-verified and the loop stops.

This is **constraint generation with stop-gradient witnesses**, NOT a Danskin
gradient. `_state_collision` solves a zero-objective *feasibility* LP and
returns an arbitrary surviving collision -- it does not minimize the outer
coverage objective, so there is no inner argmin for an envelope theorem to
apply to. (Corrected after peer review 2026-07-21; the code is unchanged by
this correction, only the justification is stated honestly. Earning a real
Danskin gradient would require defining and solving an inner problem aligned
with the outer loss.) Exact re-verification is what preserves safety here,
and it does so regardless of the gradient's provenance.

This never emits CERTIFIED itself. Callers must take `result.selected`, map
it to global action IDs, and confirm through CertiTherm.synthesis for
anything claim-adjacent. UNVERIFIED -- see README.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

import numpy as np
import torch

from CertiTherm.core import CandidateSpace, MeasurementAction

from .gate import gate_probabilities, hard_separation, soft_coverage, soft_min
from .oracle import Witness, action_geometry, find_witness, local_actions
from .rounding import greedy_cover_rounding


@dataclass
class GateTrainingResult:
    """Result of one candidate/state-pair proposal run.

    `selected` holds CANDIDATE-LOCAL action indices (positions in
    `oracle.local_actions(actions, candidate)`), NOT global indices into the
    caller's full action library. Map them before use elsewhere.

    `state_pair_verified` means only: the exact oracle found no surviving
    collision for THIS candidate and THIS (left_state, right_state) pair
    under `selected`. It is NOT certification of the ordered multi-candidate
    query -- only `CertiTherm.synthesis.synthesize_ordered_query` can do that.
    """

    selected: Tuple[int, ...]
    proxy_cost: float
    training_rounds: int
    oracle_checks: int
    witness_pool_size: int
    state_pair_verified: bool
    stop_reason: str
    history: List[float] = field(default_factory=list)


def _is_new_witness(witness: Witness, pool: Sequence[Witness], atol: float) -> bool:
    return not any(
        np.allclose(witness.delta_w, seen.delta_w, atol=atol, rtol=0.0) for seen in pool
    )


def train_gate(
    candidate: CandidateSpace,
    actions: Sequence[MeasurementAction],
    left_state: str = "SAFE",
    right_state: str = "REJECT",
    *,
    budget: float | None = None,
    cost_penalty: float = 0.25,
    temperature: float = 0.2,
    sep_margin: float = 1e-9,
    beta: float = 20.0,
    steps_per_round: int = 200,
    max_rounds: int = 25,
    lr: float = 0.05,
    witness_atol: float = 1e-12,
    device: str = "cpu",
    dtype: torch.dtype = torch.float64,
    seed: int = 0,
) -> GateTrainingResult:
    """Train gate logits to propose a low-cost separating action set.

    `cost_penalty` weights a cost term against worst-case coverage. It
    defaults to 0.25 and is applied to costs NORMALIZED by their maximum, so
    the largest possible per-action penalty is `cost_penalty` itself. It must
    stay below 1: covering a witness raises worst-case coverage by at most 1,
    so a normalized penalty >= 1 would make buying the action never
    worthwhile and the loop would never converge.

    A zero `cost_penalty` (the previous default) makes the objective
    monotonically increasing in every gate with nothing opposing it -- every
    gate saturates to 1 and rounding selects the ENTIRE library. That is a
    valid separating set, so the exact oracle confirms it and the run "looks"
    successful while being useless. Caught in peer review before first run.
    """
    if not 0.0 <= cost_penalty < 1.0:
        raise ValueError("cost_penalty must be in [0, 1); see the docstring")
    if max_rounds < 1 or steps_per_round < 1:
        raise ValueError("max_rounds and steps_per_round must be >= 1")

    torch.manual_seed(seed)
    local = local_actions(actions, candidate)
    if not local:
        raise ValueError("candidate has no registered local actions")

    vectors_np, tolerances_np, costs_np = action_geometry(local)
    weight = torch.as_tensor(vectors_np, device=device, dtype=dtype)
    tolerance = torch.as_tensor(tolerances_np, device=device, dtype=dtype)
    cost = torch.as_tensor(costs_np, device=device, dtype=dtype)
    normalized_cost = cost / cost.max()

    logits = torch.zeros(len(local), device=device, dtype=dtype, requires_grad=True)
    optimizer = torch.optim.Adam([logits], lr=lr)

    witnesses: List[Witness] = []
    history: List[float] = []
    selected: Tuple[int, ...] = ()
    checked: set[Tuple[int, ...]] = set()
    verified = False
    stop_reason = "max_rounds_exhausted"
    oracle_checks = 0
    training_rounds = 0

    for _ in range(max_rounds):
        witness = find_witness(candidate, local, selected, left_state, right_state)
        oracle_checks += 1
        checked.add(selected)
        if witness is None:
            verified = True
            stop_reason = "verified"
            break

        if not _is_new_witness(witness, witnesses, witness_atol):
            # The oracle re-returned a witness we already have: training is not
            # moving the selection anywhere new. Report it rather than padding
            # the pool with duplicates, which would also drag soft_min down by
            # log(B)/beta and corrupt the history trace.
            stop_reason = "stagnated_duplicate_witness"
            break
        witnesses.append(witness)

        deltas = torch.as_tensor(
            np.stack([w.delta_w for w in witnesses]), device=device, dtype=dtype
        )
        h = hard_separation(deltas, weight, tolerance, sep_margin)
        if not bool(h.any(dim=-1).all()):
            # Some pooled witness is separated by NO registered action. No gate
            # assignment can cover it; this is the prototype's analogue of the
            # exact path's UNSYNTHESIZABLE, and must not be trained through.
            stop_reason = "structurally_unseparable"
            break

        for _ in range(steps_per_round):
            optimizer.zero_grad()
            gates = gate_probabilities(logits, temperature)
            coverage = soft_coverage(gates, h)
            worst = soft_min(coverage, beta)
            loss = -worst + cost_penalty * torch.dot(normalized_cost, gates)
            loss.backward()
            optimizer.step()
            history.append(float(worst.detach()))
        training_rounds += 1

        with torch.no_grad():
            gates = gate_probabilities(logits, temperature)
        selected = greedy_cover_rounding(
            gates.detach().cpu().numpy(),
            costs_np,
            h.detach().cpu().numpy(),
            budget=budget,
        )

    # The loop checks `selected` at the TOP of each iteration, so a selection
    # produced by the final round's rounding would otherwise never be checked
    # and would be reported unverified -- a false negative.
    if not verified and selected not in checked:
        oracle_checks += 1
        if find_witness(candidate, local, selected, left_state, right_state) is None:
            verified = True
            stop_reason = "verified_on_final_check"

    proxy_cost = float(costs_np[list(selected)].sum()) if selected else 0.0
    return GateTrainingResult(
        selected=selected,
        proxy_cost=proxy_cost,
        training_rounds=training_rounds,
        oracle_checks=oracle_checks,
        witness_pool_size=len(witnesses),
        state_pair_verified=verified,
        stop_reason=stop_reason,
        history=history,
    )
