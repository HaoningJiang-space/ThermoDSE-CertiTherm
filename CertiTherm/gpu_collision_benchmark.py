"""Adversarial parity and throughput probe for the CUDA LP proposer."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import time

import numpy as np
from scipy.optimize import linprog

from .core import CandidateSpace, MeasurementAction, PowerPolytope, ThermalFamily
from .collision_proof import LinearFeasibilitySystem, ProposalKind
from .gpu_collision import SharedCollisionBatch, propose_collision_batch
from .gpu_collision_broker import CollisionBroker
from .synthesis import _state_collision


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


def _claim_path_parity(solver: Path, socket_path: Path) -> None:
    power = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    candidate = CandidateSpace(
        "candidate",
        power,
        ThermalFamily(
            ("block",),
            np.array([[[2.0, 0.0], [2.0, 0.0]]]),
            np.zeros((1, 2)),
            1.0,
        ),
    )
    actions = (
        MeasurementAction(
            "p0", np.array([1.0, 0.0]), candidate_id="candidate"
        ),
    )
    previous = {
        name: os.environ.get(name)
        for name in (
            "CERTITHERM_GPU_SEPARATION",
            "CERTITHERM_GPU_COLLISION_SOCKET",
            "CERTITHERM_GPU_COLLISION_SOLVER",
        )
    }
    try:
        os.environ["CERTITHERM_GPU_SEPARATION"] = "0"
        cpu_open = _state_collision(candidate, actions, (), "SAFE", "REJECT", 1e-4, 1e-10)
        cpu_closed = _state_collision(candidate, actions, (0,), "SAFE", "REJECT", 1e-4, 1e-10)
        os.environ.update(
            {
                "CERTITHERM_GPU_SEPARATION": "1",
                "CERTITHERM_GPU_COLLISION_SOCKET": str(socket_path),
                "CERTITHERM_GPU_COLLISION_SOLVER": str(solver),
            }
        )
        gpu_open = _state_collision(candidate, actions, (), "SAFE", "REJECT", 1e-4, 1e-10)
        gpu_closed = _state_collision(candidate, actions, (0,), "SAFE", "REJECT", 1e-4, 1e-10)
        if (cpu_open is None) != (gpu_open is None) or (cpu_closed is None) != (gpu_closed is None):
            raise RuntimeError("GPU claim-path collision result disagrees with HiGHS")
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    args = parser.parse_args()
    rows = []
    with CollisionBroker(args.solver, args.device) as broker:
        for cells in _BATCH_SIZES:
            batch = _fixture(cells)
            expected, cpu_ms = _cpu_status(batch)
            _proposals, checks, receipt = propose_collision_batch(
                batch,
                args.solver,
                device=args.device,
                broker_socket=broker.socket_path,
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
        _claim_path_parity(args.solver.resolve(), broker.socket_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(args.output.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
