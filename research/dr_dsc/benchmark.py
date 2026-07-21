"""Realistic-scale comparison: learned proposal vs plain greedy vs exact optimum.

The toy fixtures in tests/ prove only that the loop runs. They cannot show
whether the LEARNED gate ordering beats plain cost-effectiveness greedy,
because on 2-action instances greedy is trivially optimal. This script builds
a realistically-shaped instance and measures the one number that matters:

    does the learned ordering reach a lower cost than greedy,
    and how do both compare to the exact MILP optimum?

WHAT IS REAL HERE:
  - the floorplan (a real ThermoDSE-generated 3D floorplan, 227+ blocks);
  - the action library, built by CertiTherm's OWN
    `measurements.build_measurement_library` -- real module/chiplet/region/
    post-route grouping at the real frozen costs 1/2/4/8;
  - the power polytope, built by CertiTherm's own `coarse_power_space` /
    `content_upper_bounds`;
  - the exact oracle and the exact MILP, unmodified.

WHAT IS SYNTHETIC (and must be labelled as such in any writeup):
  - the placed power vector (per-module-type budgets, deterministic);
  - the thermal response operator: a spatial-decay kernel over real floorplan
    geometry, NOT a HotSpot-built operator. Building real operators takes ~1h
    per architecture/package and is not needed to answer the ordering
    question, which depends on the action/witness structure rather than on
    exact Kelvin values.

So: valid for comparing SEARCH STRATEGIES against each other on realistic
structure. NOT valid as thermal evidence, and not claim-grade.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Sequence

import numpy as np

from CertiTherm.core import CandidateSpace, MeasurementAction, ThermalFamily
from CertiTherm.measurements import (
    build_measurement_library,
    coarse_power_space,
    content_upper_bounds,
)

from .oracle import action_geometry, find_witness

COSTS = {"module": 1.0, "chiplet": 2.0, "placement_region": 4.0, "post_route": 8.0}


def read_floorplan(path: Path) -> tuple[list[str], np.ndarray]:
    """Return (block names, centre coordinates) from a HotSpot .flp."""
    names, centres = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        f = line.split()
        if len(f) >= 5 and not f[0].startswith("#"):
            names.append(f[0])
            centres.append((float(f[3]) + float(f[1]) / 2, float(f[4]) + float(f[2]) / 2))
    return names, np.asarray(centres)


def synthetic_power(blocks: Sequence[str], total_w: float = 40.0) -> np.ndarray:
    """Deterministic per-module-type power split. Synthetic, not measured."""
    weights = []
    for block in blocks:
        stem = block.split("_", 1)[0].rstrip("0123456789")
        weights.append(
            {"mtxu": 4.0, "vecu": 2.0, "ubuf": 1.5, "ibuf": 1.0, "obuf": 1.0}.get(stem, 0.3)
        )
    weights = np.asarray(weights)
    return weights / weights.sum() * total_w


def synthetic_thermal(
    centres: np.ndarray,
    points: int,
    limit_k: float,
    ambient_k: float = 318.15,
    decay_m: float = 0.0012,
) -> ThermalFamily:
    """Spatial-decay response over REAL geometry. Synthetic operator.

    EXPONENTIAL decay, deliberately. The first version used a rational
    kernel 0.9/(1+d/lambda) with lambda=4mm, which gave a max/min response
    ratio of only 5.4x across a 20mm die: every block heated every thermal
    point substantially, so certifying the peak required pinning nearly all
    227 blocks and NO method converged (exact DSOS returned UNRESOLVED after
    250 iterations / 716s, and both heuristics ran out of rounds).

    That was an artifact of the kernel, not a property of thermal DSE. Real
    HotSpot operators are strongly local -- a block mostly heats itself and
    its neighbours -- which is what makes a handful of aggregate observations
    informative at all. exp(-d/lambda) with a ~1mm length reproduces that
    locality and gives a realistic dynamic range.
    """
    hotspots = np.linspace(0, len(centres) - 1, points).astype(int)
    responses = []
    for scale in (1.0, 1.6):  # two "models" = two conduction strengths
        rows = []
        for r in hotspots:
            dist = np.linalg.norm(centres - centres[r], axis=1)
            rows.append(0.9 * scale * np.exp(-dist / decay_m))
        responses.append(np.stack(rows))
    return ThermalFamily(
        model_ids=("tight", "loose"),
        response_k_per_w=np.stack(responses),
        ambient_k=np.array([ambient_k, ambient_k]),
        limit_k=limit_k,
        error_k=np.array([0.01, 0.01]),
    )


def build_instance(flp: Path, points: int, limit_k: float, arch: dict, decay_m: float = 0.0012) -> tuple:
    blocks, centres = read_floorplan(flp)
    placed = synthetic_power(blocks)
    polytope = coarse_power_space(placed, content_upper_bounds(blocks, placed))
    thermal = synthetic_thermal(centres, points, limit_k, decay_m=decay_m)
    actions = build_measurement_library(
        "cand", blocks, flp.read_text(encoding="utf-8"), arch, COSTS
    )
    return CandidateSpace("cand", polytope, thermal), actions, blocks


def greedy_baseline(candidate, actions, max_rounds: int) -> tuple[tuple[int, ...], int]:
    """Plain cost-effectiveness greedy over the SAME constraint-generation loop.

    Identical oracle, identical stopping rule, identical witness pool -- the
    ONLY difference from DR-DSC is that action order comes from
    coverage/cost instead of from a learned gate. That isolates the learned
    ordering as the single independent variable.
    """
    vectors, tolerances, costs = action_geometry(actions)
    selected: tuple[int, ...] = ()
    witnesses: list[np.ndarray] = []
    checks = 0
    for _ in range(max_rounds):
        witness = find_witness(candidate, actions, selected)
        checks += 1
        if witness is None:
            break
        witnesses.append(witness.delta_w)
        deltas = np.stack(witnesses)
        cover = np.abs(deltas @ vectors.T) > (tolerances[None, :] + 1e-9)
        chosen: list[int] = []
        uncovered = np.ones(len(witnesses), dtype=bool)
        while uncovered.any():
            gain = cover[uncovered].sum(axis=0) / costs
            gain[chosen] = -np.inf
            best = int(np.argmax(gain))
            if gain[best] <= 0:
                break
            chosen.append(best)
            uncovered &= ~cover[:, best]
        selected = tuple(sorted(chosen))
    return selected, checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flp", required=True)
    parser.add_argument("--points", type=int, default=6)
    parser.add_argument("--limit-k", type=float, default=345.0)
    parser.add_argument("--decay-m", type=float, default=0.0012)
    parser.add_argument("--max-rounds", type=int, default=12)
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--probe", action="store_true", help="print instance size and exit")
    parser.add_argument(
        "--exact",
        action="store_true",
        help="run the EXACT DSOS path instead of the heuristics. Answers the prior "
        "question both heuristics raise by failing to converge: is this instance "
        "synthesizable at all, and at what cost?",
    )
    args = parser.parse_args()

    arch = {"chiplet_x": "7", "chiplet_y": "3", "cut_x": "1", "cut_y": "1"}
    candidate, actions, blocks = build_instance(
        Path(args.flp), args.points, args.limit_k, arch, args.decay_m
    )
    _, _, costs = action_geometry(actions)
    by_cost: dict[float, int] = {}
    for c in costs:
        by_cost[float(c)] = by_cost.get(float(c), 0) + 1
    print(f"blocks={len(blocks)} actions={len(actions)} "
          f"thermal_points={args.points} models={len(candidate.thermal.model_ids)}")
    print(f"actions by cost: {dict(sorted(by_cost.items()))}")
    if args.probe:
        return

    print("\n--- feasibility of the query (is there anything to separate?) ---")
    t0 = time.time()
    w = find_witness(candidate, list(actions), ())
    print(f"empty-selection witness: {'FOUND' if w else 'none'} ({time.time()-t0:.1f}s)")
    if w is None:
        print("instance is trivially certified -- raise --limit-k tension and retry")
        return

    if args.exact:
        from CertiTherm.synthesis import synthesize_minimum_observation

        print("\n--- EXACT DSOS (ground truth) ---")
        t0 = time.time()
        plan = synthesize_minimum_observation(
            candidate.power, candidate.thermal, actions, max_iterations=args.max_rounds
        )
        print(
            f"status={plan.status} cost={plan.exact_cost} lower_bound={plan.lower_bound} "
            f"gap={plan.optimality_gap} iterations={plan.iterations} "
            f"n_selected={len(plan.selected_action_ids)} time={time.time()-t0:.1f}s"
        )
        print(f"message: {plan.message}")
        return

    print("\n--- greedy baseline ---")
    t0 = time.time()
    g_sel, g_checks = greedy_baseline(candidate, list(actions), args.max_rounds)
    g_time = time.time() - t0
    g_cost = float(costs[list(g_sel)].sum()) if g_sel else 0.0
    g_ok = find_witness(candidate, list(actions), g_sel) is None
    print(f"greedy: cost={g_cost} n={len(g_sel)} verified={g_ok} "
          f"oracle_checks={g_checks} time={g_time:.1f}s")

    print("\n--- DR-DSC learned proposal ---")
    from .train import train_gate  # imported late so --probe needs no torch

    t0 = time.time()
    r = train_gate(
        candidate, actions, max_rounds=args.max_rounds, steps_per_round=args.steps
    )
    d_time = time.time() - t0
    print(f"dr-dsc: cost={r.proxy_cost} n={len(r.selected)} "
          f"verified={r.state_pair_verified} stop={r.stop_reason} "
          f"oracle_checks={r.oracle_checks} time={d_time:.1f}s")

    print("\n=== VERDICT ===")
    if g_cost and r.proxy_cost:
        delta = (r.proxy_cost - g_cost) / g_cost * 100
        print(f"learned vs greedy cost: {r.proxy_cost} vs {g_cost} ({delta:+.1f}%)")
        print("learned ordering helps" if delta < 0 else
              "learned ordering does NOT beat greedy" if delta > 0 else "tie")


if __name__ == "__main__":
    main()
