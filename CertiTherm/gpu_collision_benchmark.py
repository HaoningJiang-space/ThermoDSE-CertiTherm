"""Adversarial parity and throughput probe for the CUDA LP proposer."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import time

import numpy as np
from scipy.optimize import linprog

from .collision_proof import LinearFeasibilitySystem, ProposalKind
from .gpu_collision import SharedCollisionBatch, propose_collision_batch


_BATCH_SIZES = (1, 7, 31, 32, 33, 127, 128, 129, 541)


def _fixture(cells: int) -> SharedCollisionBatch:
    variables = 8
    common = LinearFeasibilitySystem(
        -np.eye(variables),
        np.zeros(variables),
        np.ones((1, variables)),
        np.ones(1),
        np.zeros(variables),
        np.ones(variables),
    )
    rows = np.zeros((cells, variables))
    rows[:, 0] = 1.0
    # Odd cells are infeasible (x0 <= -0.1 together with x0 >= 0);
    # even cells admit the initialization-near uniform simplex point.
    rhs = np.where(np.arange(cells) % 2, -0.1, 0.2)
    return SharedCollisionBatch(common, rows, rhs)


def _cpu_status(batch: SharedCollisionBatch):
    statuses = []
    started = time.perf_counter()
    for cell in range(batch.cells):
        system = batch.system(cell)
        result = linprog(
            np.zeros(system.variables),
            A_ub=system.a_ub,
            b_ub=system.b_ub,
            A_eq=system.a_eq,
            b_eq=system.b_eq,
            bounds=tuple(zip(system.lower, system.upper)),
            method="highs",
        )
        if result.status not in (0, 2):
            raise RuntimeError(f"CPU parity LP unresolved: {result.message}")
        statuses.append(ProposalKind.FEASIBLE if result.status == 0 else ProposalKind.INFEASIBLE)
    return tuple(statuses), 1000.0 * (time.perf_counter() - started)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    args = parser.parse_args()
    rows = []
    for cells in _BATCH_SIZES:
        batch = _fixture(cells)
        expected, cpu_ms = _cpu_status(batch)
        _proposals, checks, receipt = propose_collision_batch(
            batch, args.solver, device=args.device
        )
        wrong = sum(
            check.accepted and check.kind != expected[cell]
            for cell, check in enumerate(checks)
        )
        if wrong:
            raise RuntimeError(f"GPU verifier admitted {wrong} incorrect cells")
        rows.append(
            {
                "cells": cells,
                "feasible_accepted": receipt.feasible_accepted,
                "infeasible_accepted": receipt.infeasible_accepted,
                "fallback": receipt.fallback,
                "cpu_ms": cpu_ms,
                "gpu_solver_ms": receipt.solver_ms,
                "gpu_wall_ms": receipt.wall_ms,
                "solver_speedup": cpu_ms / receipt.solver_ms,
                "wall_speedup": cpu_ms / receipt.wall_ms,
                "wrong_accepted": wrong,
            }
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(args.output.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
