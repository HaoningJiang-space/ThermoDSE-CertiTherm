"""Compatibility interface for the fail-closed CertiTherm LP oracle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

try:  # Script execution and test-path execution are both supported.
    from .linear_oracle import UNRESOLVED, solve_candidate_bounds
except ImportError:  # pragma: no cover - exercised by direct CLI execution.
    from linear_oracle import UNRESOLVED, solve_candidate_bounds


def _invalid_area(detail: str) -> dict[str, Any]:
    return {
        "schema_version": "certitherm.linear-candidate-oracle.v1",
        "status": UNRESOLVED,
        "reason": "UNRESOLVED_INVALID_INPUT",
        "detail": detail,
    }


def decide(
    sys_info: Sequence[Any],
    R: Any,
    T_ambient: Any,
    observation: Mapping[str, Any],
    block_names: Sequence[str],
    T_budget: float = 348.0,
    A_budget_m2: float = 3e-4,
    area_mm2: float | None = None,
) -> dict[str, Any]:
    """Return candidate thermal bounds with compatibility field names.

    ``sys_info`` is retained for callers and provenance but is not an LP
    variable.  Area infeasibility is a deterministic nonthermal constraint.
    """

    del sys_info
    try:
        area_budget = float(A_budget_m2)
        if not np.isfinite(area_budget) or area_budget < 0.0:
            return _invalid_area("A_budget_m2 must be finite and non-negative")
        if area_mm2 is None:
            area_value = None
            area_ok = True
        else:
            area_value = float(area_mm2)
            if not np.isfinite(area_value) or area_value < 0.0:
                return _invalid_area("area_mm2 must be finite and non-negative")
            area_ok = area_value * 1e-6 <= area_budget + 1e-12
    except (TypeError, ValueError) as exc:
        return _invalid_area(str(exc))

    result = solve_candidate_bounds(
        R,
        T_ambient,
        observation,
        block_names,
        thermal_limit_k=T_budget,
        nonthermal_feasible=area_ok,
    )
    result["A_budget_mm2"] = area_budget * 1e6
    result["area_mm2"] = area_value
    result["area_ok"] = bool(area_ok)
    if result.get("status") != UNRESOLVED:
        result["witness_safe_verified_T"] = result.get("witness_safe_T")
        result["witness_infeas_verified_T"] = result.get("witness_infeas_T")
    return result


def decide_simple(
    sys_info: Sequence[Any],
    R: Any,
    T_ambient: Any,
    block_names: Sequence[str],
    uniform_powers: Sequence[float],
    T_budget: float = 348.0,
    A_budget_m2: float = 3e-4,
    area_mm2: float | None = None,
    content_factor: float = 5.0,
) -> dict[str, Any]:
    """Legacy total-power observation helper used by the synthetic pilot."""

    try:
        powers = np.asarray(uniform_powers, dtype=np.float64)
        factor = float(content_factor)
    except (TypeError, ValueError) as exc:
        return _invalid_area(str(exc))
    if powers.ndim != 1 or not np.all(np.isfinite(powers)) or np.any(powers < 0.0):
        return _invalid_area("uniform_powers must be a finite non-negative vector")
    if not np.isfinite(factor) or factor < 1.0:
        return _invalid_area("content_factor must be finite and at least one")
    observation = {
        "per_block_power": powers.tolist(),
        "per_block_upper": (factor * powers).tolist(),
        "per_block_lower": [0.0] * len(powers),
    }
    return decide(
        sys_info,
        R,
        T_ambient,
        observation,
        block_names,
        T_budget=T_budget,
        A_budget_m2=A_budget_m2,
        area_mm2=area_mm2,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--R-matrix", required=True, type=Path)
    parser.add_argument("--R-meta", required=True, type=Path)
    parser.add_argument("--uniform-ptrace", type=Path)
    parser.add_argument("--content-factor", type=float, default=5.0)
    parser.add_argument("--T-budget", type=float, default=348.0)
    parser.add_argument("--area-mm2", type=float)
    args = parser.parse_args()

    response = np.load(args.R_matrix, allow_pickle=False)
    metadata = json.loads(args.R_meta.read_text(encoding="utf-8"))
    if args.uniform_ptrace:
        lines = args.uniform_ptrace.read_text(encoding="utf-8").splitlines()
        if len(lines) < 2:
            raise SystemExit("ptrace must contain a header and one power row")
        powers = [float(value) for value in lines[1].strip().split("\t")]
    else:
        powers = [1.0] * response.shape[0]
    result = decide_simple(
        metadata.get("sys_info", []),
        response,
        metadata["T_ambient"],
        metadata["blocks"],
        powers,
        T_budget=args.T_budget,
        area_mm2=args.area_mm2,
        content_factor=args.content_factor,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") != UNRESOLVED else 2


if __name__ == "__main__":
    raise SystemExit(main())
