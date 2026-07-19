"""Fail-closed LP oracle for content-bound spatial-power thermal decisions.

This module is the only floating-point solver kernel used by CertiTherm.  It
supports explicit obtainable observations ``A_eq p = b_eq``, registered
inequalities ``A_ub p <= b_ub``, and finite component bounds.  Both extremal
power witnesses are replayed directly before any status is returned.

The floating-point path is an operational solver, not the exact-rational G1
semantic oracle.  A solver or replay discrepancy therefore returns
``UNRESOLVED`` rather than a certificate.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np
import scipy
from scipy.optimize import linprog


ORACLE_SCHEMA_VERSION = "certitherm.linear-candidate-oracle.v1"

CERTIFIED_SAFE = "CERTIFIED_SAFE"
CERTIFIED_INFEASIBLE = "CERTIFIED_INFEASIBLE"
NON_IDENTIFIABLE = "NON_IDENTIFIABLE"
UNRESOLVED = "UNRESOLVED"


class OracleInputError(ValueError):
    """Raised internally when an input violates the frozen G2 contract."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def canonical_sha256(value: Any) -> str:
    """Return a stable SHA-256 digest of JSON-compatible scientific input."""

    encoded = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite_vector(value: Any, length: int, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (length,):
        raise OracleInputError(f"{name} must have shape ({length},)")
    if not np.all(np.isfinite(array)):
        raise OracleInputError(f"{name} contains a non-finite value")
    return array


def _finite_matrix(value: Any, columns: int, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != columns:
        raise OracleInputError(f"{name} must be a 2-D matrix with {columns} columns")
    if not np.all(np.isfinite(array)):
        raise OracleInputError(f"{name} contains a non-finite value")
    return array


@dataclass(frozen=True)
class NormalizedProblem:
    response_k_per_w: np.ndarray
    ambient_k: np.ndarray
    block_names: tuple[str, ...]
    a_eq: np.ndarray
    b_eq: np.ndarray
    a_ub: np.ndarray
    b_ub: np.ndarray
    lower_w: np.ndarray
    upper_w: np.ndarray
    input_digest: str
    zeroed_response_entries: int

    @property
    def dimension(self) -> int:
        return len(self.block_names)


def normalize_problem(
    response_k_per_w: Any,
    ambient_k: Any,
    observation: Mapping[str, Any],
    block_names: Sequence[str],
    *,
    validation_tolerance: float = 1e-10,
) -> NormalizedProblem:
    """Validate and canonicalize one compact candidate problem."""

    response = np.asarray(response_k_per_w, dtype=np.float64)
    if response.ndim != 2 or response.shape[0] == 0 or response.shape[0] != response.shape[1]:
        raise OracleInputError("thermal response must be a non-empty square matrix")
    if not np.all(np.isfinite(response)):
        raise OracleInputError("thermal response contains a non-finite value")
    n = response.shape[0]

    names = tuple(block_names)
    if len(names) != n or any(not isinstance(name, str) or not name.strip() for name in names):
        raise OracleInputError("block identities must be non-empty text and match the response")
    if len(names) != len(set(names)):
        raise OracleInputError("block identities must be unique")

    if not np.isfinite(validation_tolerance) or validation_tolerance <= 0:
        raise OracleInputError("validation tolerance must be positive and finite")
    if np.any(response < -validation_tolerance):
        raise OracleInputError("thermal response violates the registered monotonicity assumption")
    response = response.copy()
    tiny_negative = (response < 0.0) & (response >= -validation_tolerance)
    zeroed_response_entries = int(np.count_nonzero(tiny_negative))
    response[tiny_negative] = 0.0

    ambient_array = np.asarray(ambient_k, dtype=np.float64)
    if ambient_array.ndim == 0:
        ambient = np.full(n, float(ambient_array), dtype=np.float64)
    else:
        ambient = _finite_vector(ambient_array, n, "ambient_k")
    if not np.all(np.isfinite(ambient)) or np.any(ambient < 0.0):
        raise OracleInputError("ambient temperature must be finite and non-negative")

    if not isinstance(observation, Mapping):
        raise OracleInputError("observation must be a mapping")

    lower = _finite_vector(observation.get("per_block_lower", np.zeros(n)), n, "per_block_lower")
    if "per_block_upper" not in observation:
        raise OracleInputError("finite per_block_upper is required for a compact domain")
    upper = _finite_vector(observation["per_block_upper"], n, "per_block_upper")
    if np.any(lower < 0.0):
        raise OracleInputError("per-block lower bounds must be non-negative")
    if np.any(upper < lower):
        raise OracleInputError("a per-block upper bound is below its lower bound")

    if "A_eq" in observation or "b_eq" in observation:
        if "A_eq" not in observation or "b_eq" not in observation:
            raise OracleInputError("A_eq and b_eq must be supplied together")
        a_eq = _finite_matrix(observation["A_eq"], n, "A_eq")
        b_eq = _finite_vector(observation["b_eq"], a_eq.shape[0], "b_eq")
    elif "per_block_power" in observation:
        observed = _finite_vector(observation["per_block_power"], n, "per_block_power")
        if np.any(observed < 0.0):
            raise OracleInputError("observed power must be non-negative")
        a_eq = np.ones((1, n), dtype=np.float64)
        b_eq = np.array([float(np.sum(observed))], dtype=np.float64)
    else:
        raise OracleInputError("at least one obtainable equality observation is required")
    if a_eq.shape[0] == 0:
        raise OracleInputError("the observation set must contain at least one equality row")
    if np.any(a_eq < -validation_tolerance):
        raise OracleInputError("obtainable observation coefficients must be non-negative")
    if np.any(np.max(np.abs(a_eq), axis=1) <= validation_tolerance):
        raise OracleInputError("an observation row has no positive member")

    if "A_ub" in observation or "b_ub" in observation:
        if "A_ub" not in observation or "b_ub" not in observation:
            raise OracleInputError("A_ub and b_ub must be supplied together")
        a_ub = _finite_matrix(observation["A_ub"], n, "A_ub")
        b_ub = _finite_vector(observation["b_ub"], a_ub.shape[0], "b_ub")
    else:
        a_ub = np.empty((0, n), dtype=np.float64)
        b_ub = np.empty((0,), dtype=np.float64)

    digest_payload = {
        "schema_version": ORACLE_SCHEMA_VERSION,
        "response_k_per_w": response,
        "ambient_k": ambient,
        "block_names": names,
        "A_eq": a_eq,
        "b_eq": b_eq,
        "A_ub": a_ub,
        "b_ub": b_ub,
        "per_block_lower": lower,
        "per_block_upper": upper,
        "validation_tolerance": validation_tolerance,
    }
    return NormalizedProblem(
        response_k_per_w=response,
        ambient_k=ambient,
        block_names=names,
        a_eq=a_eq,
        b_eq=b_eq,
        a_ub=a_ub,
        b_ub=b_ub,
        lower_w=lower,
        upper_w=upper,
        input_digest=canonical_sha256(digest_payload),
        zeroed_response_entries=zeroed_response_entries,
    )


def replay_power_witness(
    problem: NormalizedProblem,
    power_w: Any,
    *,
    feasibility_tolerance: float,
) -> dict[str, Any]:
    """Replay domain membership and full peak temperature without a solver."""

    try:
        power = _finite_vector(power_w, problem.dimension, "power witness")
    except OracleInputError as exc:
        return {"valid": False, "reason": str(exc)}

    lower_violation = float(np.max(np.maximum(problem.lower_w - power, 0.0)))
    upper_violation = float(np.max(np.maximum(power - problem.upper_w, 0.0)))
    eq_residual = float(np.max(np.abs(problem.a_eq @ power - problem.b_eq)))
    if problem.a_ub.shape[0]:
        ub_violation = float(np.max(np.maximum(problem.a_ub @ power - problem.b_ub, 0.0)))
    else:
        ub_violation = 0.0
    temperatures = problem.ambient_k + problem.response_k_per_w @ power
    peak = float(np.max(temperatures))
    valid = max(lower_violation, upper_violation, eq_residual, ub_violation) <= feasibility_tolerance
    return {
        "valid": bool(valid),
        "peak_temperature_k": peak,
        "lower_bound_violation_w": lower_violation,
        "upper_bound_violation_w": upper_violation,
        "equality_residual_w": eq_residual,
        "inequality_violation_w": ub_violation,
    }


def _unresolved(reason: str, detail: str, *, input_digest: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": ORACLE_SCHEMA_VERSION,
        "status": UNRESOLVED,
        "reason": reason,
        "detail": detail,
    }
    if input_digest is not None:
        result["input_digest"] = input_digest
    return result


def solve_candidate_bounds(
    response_k_per_w: Any,
    ambient_k: Any,
    observation: Mapping[str, Any],
    block_names: Sequence[str],
    *,
    thermal_limit_k: float,
    nonthermal_feasible: bool = True,
    validation_tolerance: float = 1e-10,
    feasibility_tolerance: float = 1e-7,
    replay_tolerance_k: float = 1e-6,
    decision_tolerance_k: float = 1e-6,
) -> dict[str, Any]:
    """Solve and replay exact lower/upper peaks for one candidate.

    Equality at ``thermal_limit_k`` is feasible.  The returned lower and upper
    witnesses are always present for a resolved compact domain, regardless of
    the candidate status.
    """

    try:
        limit = float(thermal_limit_k)
        if not np.isfinite(limit) or limit < 0.0:
            raise OracleInputError("thermal_limit_k must be finite and non-negative")
        for name, value in (
            ("feasibility_tolerance", feasibility_tolerance),
            ("replay_tolerance_k", replay_tolerance_k),
            ("decision_tolerance_k", decision_tolerance_k),
        ):
            if not np.isfinite(value) or value <= 0:
                raise OracleInputError(f"{name} must be positive and finite")
        if not isinstance(nonthermal_feasible, (bool, np.bool_)):
            raise OracleInputError("nonthermal_feasible must be boolean")
        problem = normalize_problem(
            response_k_per_w,
            ambient_k,
            observation,
            block_names,
            validation_tolerance=validation_tolerance,
        )
    except (OracleInputError, TypeError, ValueError) as exc:
        return _unresolved("UNRESOLVED_INVALID_INPUT", str(exc))

    n = problem.dimension
    bounds = list(zip(problem.lower_w.tolist(), problem.upper_w.tolist()))

    # Explicitly distinguish an empty admissible set from an optimizer failure.
    try:
        feasibility = linprog(
            np.zeros(n),
            A_ub=problem.a_ub if problem.a_ub.shape[0] else None,
            b_ub=problem.b_ub if problem.a_ub.shape[0] else None,
            A_eq=problem.a_eq,
            b_eq=problem.b_eq,
            bounds=bounds,
            method="highs",
        )
    except Exception as exc:  # SciPy input/backend failures are fail-closed.
        return _unresolved("UNRESOLVED_SOLVER_STATUS", str(exc), input_digest=problem.input_digest)
    if not feasibility.success:
        reason = "UNRESOLVED_EMPTY_DOMAIN" if feasibility.status == 2 else "UNRESOLVED_SOLVER_STATUS"
        return _unresolved(reason, feasibility.message, input_digest=problem.input_digest)

    # lower = min_p max_r ambient[r] + R[r,:] p (epigraph LP).
    epigraph_a_ub = np.vstack(
        [
            np.column_stack([problem.a_ub, np.zeros(problem.a_ub.shape[0])]),
            np.column_stack([problem.response_k_per_w, -np.ones(n)]),
        ]
    )
    epigraph_b_ub = np.concatenate([problem.b_ub, -problem.ambient_k])
    epigraph_a_eq = np.column_stack([problem.a_eq, np.zeros(problem.a_eq.shape[0])])
    epigraph_objective = np.zeros(n + 1)
    epigraph_objective[-1] = 1.0
    try:
        lower_solution = linprog(
            epigraph_objective,
            A_ub=epigraph_a_ub,
            b_ub=epigraph_b_ub,
            A_eq=epigraph_a_eq,
            b_eq=problem.b_eq,
            bounds=bounds + [(None, None)],
            method="highs",
        )
    except Exception as exc:
        return _unresolved("UNRESOLVED_SOLVER_STATUS", str(exc), input_digest=problem.input_digest)
    if not lower_solution.success:
        return _unresolved(
            "UNRESOLVED_SOLVER_STATUS",
            f"lower minmax LP: {lower_solution.message}",
            input_digest=problem.input_digest,
        )
    lower_witness = np.asarray(lower_solution.x[:n], dtype=np.float64)
    lower_k = float(lower_solution.fun)

    # upper = max_r max_p ambient[r] + R[r,:] p.
    upper_values: list[float] = []
    upper_witnesses: list[np.ndarray] = []
    for row_index in range(n):
        try:
            upper_solution = linprog(
                -problem.response_k_per_w[row_index],
                A_ub=problem.a_ub if problem.a_ub.shape[0] else None,
                b_ub=problem.b_ub if problem.a_ub.shape[0] else None,
                A_eq=problem.a_eq,
                b_eq=problem.b_eq,
                bounds=bounds,
                method="highs",
            )
        except Exception as exc:
            return _unresolved("UNRESOLVED_SOLVER_STATUS", str(exc), input_digest=problem.input_digest)
        if not upper_solution.success:
            return _unresolved(
                "UNRESOLVED_SOLVER_STATUS",
                f"upper LP row {row_index}: {upper_solution.message}",
                input_digest=problem.input_digest,
            )
        upper_values.append(float(problem.ambient_k[row_index] - upper_solution.fun))
        upper_witnesses.append(np.asarray(upper_solution.x, dtype=np.float64))
    upper_index = int(np.argmax(upper_values))
    upper_k = upper_values[upper_index]
    upper_witness = upper_witnesses[upper_index]

    lower_replay = replay_power_witness(
        problem, lower_witness, feasibility_tolerance=feasibility_tolerance
    )
    upper_replay = replay_power_witness(
        problem, upper_witness, feasibility_tolerance=feasibility_tolerance
    )
    if not lower_replay.get("valid") or not upper_replay.get("valid"):
        return _unresolved(
            "UNRESOLVED_CERTIFICATE_FAILURE",
            f"domain replay failed: lower={lower_replay}, upper={upper_replay}",
            input_digest=problem.input_digest,
        )
    if abs(float(lower_replay["peak_temperature_k"]) - lower_k) > replay_tolerance_k:
        return _unresolved(
            "UNRESOLVED_CERTIFICATE_FAILURE",
            "lower witness peak does not match the minmax bound",
            input_digest=problem.input_digest,
        )
    if abs(float(upper_replay["peak_temperature_k"]) - upper_k) > replay_tolerance_k:
        return _unresolved(
            "UNRESOLVED_CERTIFICATE_FAILURE",
            "upper witness peak does not match the maximum bound",
            input_digest=problem.input_digest,
        )
    if lower_k > upper_k + replay_tolerance_k:
        return _unresolved(
            "UNRESOLVED_CERTIFICATE_FAILURE",
            "lower bound exceeds upper bound",
            input_digest=problem.input_digest,
        )

    can_be_feasible = bool(nonthermal_feasible and lower_k <= limit + decision_tolerance_k)
    can_be_infeasible = bool((not nonthermal_feasible) or upper_k > limit + decision_tolerance_k)
    if not nonthermal_feasible:
        status = CERTIFIED_INFEASIBLE
    elif upper_k <= limit + decision_tolerance_k:
        status = CERTIFIED_SAFE
    elif lower_k > limit + decision_tolerance_k:
        status = CERTIFIED_INFEASIBLE
    else:
        status = NON_IDENTIFIABLE

    return {
        "schema_version": ORACLE_SCHEMA_VERSION,
        "status": status,
        "input_digest": problem.input_digest,
        "lower_d": lower_k,
        "upper_d": upper_k,
        "thermal_limit_k": limit,
        "nonthermal_feasible": bool(nonthermal_feasible),
        "can_be_feasible": can_be_feasible,
        "can_be_infeasible": can_be_infeasible,
        "witness_lower": lower_witness.tolist(),
        "witness_upper": upper_witness.tolist(),
        "witness_safe": lower_witness.tolist() if can_be_feasible else None,
        "witness_infeas": upper_witness.tolist() if can_be_infeasible and nonthermal_feasible else None,
        "witness_safe_T": float(lower_replay["peak_temperature_k"]) if can_be_feasible else None,
        "witness_infeas_T": float(upper_replay["peak_temperature_k"])
        if can_be_infeasible and nonthermal_feasible
        else None,
        "lower_replay": lower_replay,
        "upper_replay": upper_replay,
        "tolerances": {
            "validation": validation_tolerance,
            "feasibility_w": feasibility_tolerance,
            "replay_k": replay_tolerance_k,
            "decision_k": decision_tolerance_k,
        },
        "normalization": {
            "thermal_entries_zeroed": problem.zeroed_response_entries,
        },
        "solver": {
            "name": "scipy.optimize.linprog/highs",
            "scipy_version": scipy.__version__,
            "numpy_version": np.__version__,
        },
    }

