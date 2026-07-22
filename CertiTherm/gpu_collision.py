"""Proof-gated adapter for the batched FP64 CUDA collision proposer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
import subprocess
import tempfile
import time
from typing import Tuple

import numpy as np

from .collision_proof import (
    CollisionProposal,
    LinearFeasibilitySystem,
    ProofCheck,
    ProposalKind,
    verify_proposal,
)


_INPUT_HEADER = struct.Struct("<8sIIQQQQQQdd")
_OUTPUT_HEADER = struct.Struct("<8sIIQQQQQd")


@dataclass(frozen=True)
class SharedCollisionBatch:
    """LP cells sharing all rows except one inequality per cell."""

    common: LinearFeasibilitySystem
    spec_rows: np.ndarray
    spec_rhs: np.ndarray

    def __post_init__(self) -> None:
        rows = np.asarray(self.spec_rows, dtype=float)
        rhs = np.asarray(self.spec_rhs, dtype=float)
        if rows.shape != (rhs.size, self.common.variables) or not rhs.size:
            raise ValueError("reject-cell rows have inconsistent dimensions")
        if not np.all(np.isfinite(rows)) or not np.all(np.isfinite(rhs)):
            raise ValueError("reject-cell rows must be finite")
        rows = rows.copy()
        rhs = rhs.copy()
        rows.flags.writeable = rhs.flags.writeable = False
        object.__setattr__(self, "spec_rows", rows)
        object.__setattr__(self, "spec_rhs", rhs)

    @property
    def cells(self) -> int:
        return self.spec_rhs.size

    def system(self, cell: int) -> LinearFeasibilitySystem:
        return LinearFeasibilitySystem(
            np.vstack((self.common.a_ub, self.spec_rows[cell])),
            np.append(self.common.b_ub, self.spec_rhs[cell]),
            self.common.a_eq,
            self.common.b_eq,
            self.common.lower,
            self.common.upper,
        )


@dataclass(frozen=True)
class GpuCollisionReceipt:
    cells: int
    feasible_accepted: int
    infeasible_accepted: int
    fallback: int
    iterations: int
    solver_ms: float
    wall_ms: float
    max_reported_violation: float


def _write_input(
    path: Path,
    batch: SharedCollisionBatch,
    max_iterations: int,
    check_interval: int,
    feasibility_tolerance: float,
    step_scale: float,
) -> None:
    common = batch.common
    header = _INPUT_HEADER.pack(
        b"CTCLP01\0",
        1,
        8,
        common.variables,
        common.b_ub.size,
        common.b_eq.size,
        batch.cells,
        max_iterations,
        check_interval,
        feasibility_tolerance,
        step_scale,
    )
    arrays = (
        common.a_ub,
        common.b_ub,
        common.a_eq,
        common.b_eq,
        common.lower,
        common.upper,
        batch.spec_rows,
        batch.spec_rhs,
    )
    with path.open("wb") as stream:
        stream.write(header)
        for array in arrays:
            stream.write(np.asarray(array, dtype="<f8", order="C").tobytes())


def _read_output(path: Path, batch: SharedCollisionBatch):
    with path.open("rb") as stream:
        header = stream.read(_OUTPUT_HEADER.size)
        if len(header) != _OUTPUT_HEADER.size:
            raise RuntimeError("truncated GPU collision output")
        magic, version, scalar, cells, variables, inequalities, equalities, iterations, solver_ms = (
            _OUTPUT_HEADER.unpack(header)
        )
        expected = (
            cells * 4
            + cells * 8
            + variables * cells * 8
            + inequalities * cells * 8
            + cells * 8
            + equalities * cells * 8
        )
        payload = stream.read()
    if magic[:7] != b"CTCLPO1" or version != 1 or scalar != 8:
        raise RuntimeError("unsupported GPU collision output format")
    if (cells, variables, inequalities, equalities) != (
        batch.cells,
        batch.common.variables,
        batch.common.b_ub.size,
        batch.common.b_eq.size,
    ) or len(payload) != expected:
        raise RuntimeError("GPU collision output dimensions disagree with request")
    offset = 0

    def take(dtype, count):
        nonlocal offset
        size = np.dtype(dtype).itemsize * count
        values = np.frombuffer(payload, dtype=dtype, count=count, offset=offset).copy()
        offset += size
        return values

    kinds = take("<i4", cells)
    violations = take("<f8", cells)
    primal = take("<f8", variables * cells).reshape(variables, cells)
    dual = take("<f8", inequalities * cells).reshape(inequalities, cells)
    spec_dual = take("<f8", cells)
    eq_dual = take("<f8", equalities * cells).reshape(equalities, cells)
    values = (violations, primal, dual, spec_dual, eq_dual)
    if not all(np.all(np.isfinite(value)) for value in values):
        raise RuntimeError("GPU collision output is non-finite")
    return kinds, values, int(iterations), float(solver_ms)


def propose_collision_batch(
    batch: SharedCollisionBatch,
    solver: Path,
    *,
    device: int = 0,
    max_iterations: int = 20_000,
    check_interval: int = 100,
    feasibility_tolerance: float = 1e-11,
    verification_tolerance: float = 1e-10,
    step_scale: float = 0.9,
) -> Tuple[Tuple[CollisionProposal, ...], Tuple[ProofCheck, ...], GpuCollisionReceipt]:
    """Run approximate GPU search, then independently verify every proposal."""

    if not Path(solver).is_file() or device < 0:
        raise ValueError("GPU collision solver and non-negative device are required")
    if max_iterations <= 0 or check_interval <= 0:
        raise ValueError("GPU iteration controls must be positive")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="certitherm-collision-") as directory:
        input_path = Path(directory) / "input.bin"
        output_path = Path(directory) / "output.bin"
        _write_input(
            input_path,
            batch,
            max_iterations,
            check_interval,
            feasibility_tolerance,
            step_scale,
        )
        result = subprocess.run(
            [str(solver), str(input_path), str(output_path), str(device)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0 or not output_path.is_file():
            raise RuntimeError("GPU collision proposal failed: " + result.stderr[-800:])
        kinds, values, iterations, solver_ms = _read_output(output_path, batch)
    violations, primal, dual, spec_dual, eq_dual = values
    proposals = []
    checks = []
    for cell, kind in enumerate(kinds):
        if kind == 1:
            proposal = CollisionProposal(
                ProposalKind.FEASIBLE, primal=primal[:, cell]
            )
        elif kind == 2:
            equality = eq_dual[:, cell]
            ray = np.concatenate(
                (
                    dual[:, cell],
                    spec_dual[cell : cell + 1],
                    np.maximum(equality, 0.0),
                    np.maximum(-equality, 0.0),
                )
            )
            proposal = CollisionProposal(ProposalKind.INFEASIBLE, ray=ray)
        else:
            proposal = CollisionProposal(ProposalKind.UNKNOWN)
        check = verify_proposal(batch.system(cell), proposal, verification_tolerance)
        proposals.append(proposal)
        checks.append(check)
    feasible = sum(check.accepted and check.kind == ProposalKind.FEASIBLE for check in checks)
    infeasible = sum(check.accepted and check.kind == ProposalKind.INFEASIBLE for check in checks)
    receipt = GpuCollisionReceipt(
        cells=batch.cells,
        feasible_accepted=feasible,
        infeasible_accepted=infeasible,
        fallback=batch.cells - feasible - infeasible,
        iterations=iterations,
        solver_ms=solver_ms,
        wall_ms=1000.0 * (time.perf_counter() - started),
        max_reported_violation=float(np.max(violations)),
    )
    return tuple(proposals), tuple(checks), receipt
