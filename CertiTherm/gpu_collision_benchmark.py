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
from .gpu_collision_broker import CollisionBroker
from .synthesis import _pair_rows, _state_constraints, _state_specs
from .experiments import (
    _measurement_costs,
    _ordered_architectures,
    _power_space,
    _rows,
)
from .hotspot import load_family
from .measurements import build_measurement_library


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


def _real_negative_tail(root: Path) -> SharedCollisionBatch:
    """Rebuild one registered full-observation negative tail from artifacts."""

    registry = Path(__file__).resolve().parents[1] / "experiments"
    architectures = sorted(
        (row for row in _rows(registry / "architectures.tsv") if row["split"] == "dev"),
        key=lambda row: int(row["rank"]),
    )
    captures = {
        ("resnet50", row["architecture_id"]):
        root / "captures" / f"resnet50--{row['architecture_id']}.npz"
        for row in architectures
    }
    architecture = _ordered_architectures("resnet50", architectures, captures)[0]
    candidate_id = architecture["architecture_id"]
    power, blocks, _placed, floorplan = _power_space(
        captures[("resnet50", candidate_id)]
    )
    thermal, operator_blocks = load_family(
        root / "operators" / f"{candidate_id}--standard.npz"
    )
    if blocks != operator_blocks:
        raise RuntimeError("real collision corpus block registry disagrees")
    actions = build_measurement_library(
        candidate_id, blocks, floorplan, architecture, _measurement_costs()
    )
    n = power.dimension
    a_eq, b_eq, a_ub, b_ub = _pair_rows(power)
    safe_rows, safe_rhs = _state_constraints(
        thermal, "SAFE", -1, -1, 0, 1e-4
    )
    chunks, rhs_chunks = [a_ub, safe_rows], [b_ub, safe_rhs]
    for action in actions:
        delta = np.concatenate((action.vector, -action.vector))
        chunks.append(np.vstack((delta, -delta)))
        rhs_chunks.append(np.full(2, action.tolerance))
    specs = tuple(_state_specs(thermal, "REJECT"))
    rows_and_rhs = [
        _state_constraints(thermal, "REJECT", model, point, 1, 1e-4)
        for model, point in specs
    ]
    bounds = tuple(zip(power.lower_w, power.upper_w)) * 2
    common = LinearFeasibilitySystem(
        np.vstack(chunks),
        np.concatenate(rhs_chunks),
        a_eq,
        b_eq,
        np.asarray([bound[0] for bound in bounds]),
        np.asarray([bound[1] for bound in bounds]),
    )
    return SharedCollisionBatch(
        common,
        np.vstack([row[0] for row, _rhs in rows_and_rhs]),
        np.asarray([rhs[0] for _row, rhs in rows_and_rhs]),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--real-artifact-root", type=Path)
    parser.add_argument("--real-iterations", type=int, default=1000)
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
        if args.real_artifact_root is not None:
            real_batch = _real_negative_tail(args.real_artifact_root)
            _proposals, _checks, real_receipt = propose_collision_batch(
                real_batch,
                args.solver,
                device=args.device,
                max_iterations=args.real_iterations,
                broker_socket=broker.socket_path,
            )
            print(f"real_negative_tail\t{real_receipt}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    print(args.output.read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
