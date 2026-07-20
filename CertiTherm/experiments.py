"""Frozen ThermoDSE/HotSpot experiment driver with resumable NPZ evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
from itertools import product
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from typing import Callable, Iterable, Mapping, Optional, TypeVar

import numpy as np

from .core import CandidateSpace, PowerPolytope
from .hotspot import build_family, load_family, replay_power, save_family
from .measurements import (
    build_measurement_library,
    coarse_power_space,
    content_upper_bounds,
)
from .policies import dual_price_greedy, sequential_early_stop, uncertainty_width_order
from .synthesis import synthesize_ordered_query


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "CertiTherm" / "evidence" / "thermodse_tmp_template"
THERMODSE = ROOT / "ThermoDSE"
HOTSPOT = ROOT / ".build" / "hotspot" / "hotspot"
MODELS = ("block", "grid64-avg", "grid128-avg")
THERMAL_LIMIT_K = 330.0
MODEL_ERROR_LIMIT_K = 0.01
CALIBRATION_SEEDS = (17, 23, 41)
CALIBRATION_VECTOR_IDS = (
    "placed",
    "bounded-uniform",
    *(f"bounded-random-{seed}" for seed in CALIBRATION_SEEDS),
)
QUERY_METHOD_TIMEOUT_S = 1800
_T = TypeVar("_T")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _architecture(row: dict[str, str]) -> list[float]:
    keys = (
        "chiplet_x",
        "chiplet_y",
        "cut_x",
        "cut_y",
        "interval",
        "mtxu_h",
        "mtxu_w",
        "ubuf",
        "nop_bw",
        "dram_bw",
    )
    return [float(row[key]) if key == "interval" else int(row[key]) for key in keys]


def _capture_metrics(capture: Path) -> dict[str, float]:
    with np.load(capture, allow_pickle=False) as data:
        latency = float(data["latency_ms"])
        energy = float(data["energy_mj"])
        die_yield = float(data["die_yield"])
    if min(latency, energy, die_yield) <= 0:
        raise RuntimeError(f"nonpositive objective metric in {capture.name}")
    return {
        "latency_ms": latency,
        "energy_mj": energy,
        "die_yield": die_yield,
        "edyp": latency * energy / die_yield,
    }


def _ordered_architectures(
    workload_id: str,
    architectures: Iterable[dict[str, str]],
    captures: Mapping[tuple[str, str], Path],
) -> list[dict[str, str]]:
    """Return the workload's true non-thermal ThermoDSE preference order."""

    return sorted(
        architectures,
        key=lambda arch: (
            _capture_metrics(captures[(workload_id, arch["architecture_id"])])["edyp"],
            arch["architecture_id"],
        ),
    )


def _configure(source: Path, output: Path, package: dict[str, str]) -> None:
    text = source.read_text(encoding="utf-8")
    for option in (
        "r_convec",
        "s_sink",
        "s_spreader",
        "t_spreader",
        "ambient",
        "init_temp",
        "t_sink",
        "t_interface",
    ):
        value = package["ambient"] if option == "init_temp" else package[option]
        pattern = rf"(?m)^(\s*-{re.escape(option)}\s+)\S+"
        text, count = re.subn(pattern, rf"\g<1>{value}", text, count=1)
        if count != 1:
            raise RuntimeError(f"template does not uniquely define -{option}")
    output.write_text(text, encoding="utf-8")


def _capture(
    arch: dict[str, str],
    workload: dict[str, str],
    package: dict[str, str],
    output: Path,
) -> Path:
    capture = output / "captures" / f"{workload['workload_id']}--{arch['architecture_id']}.npz"
    if capture.is_file():
        return capture
    sim = output / "work" / f"capture--{workload['workload_id']}--{arch['architecture_id']}"
    if sim.exists():
        shutil.rmtree(sim)
    shutil.copytree(TEMPLATE, sim)
    _configure(TEMPLATE / "example.config", sim / "example.config", package)
    runner = ROOT / "CertiTherm" / "trace_runner.py"
    wrapper = (
        "#!/bin/sh\nexec "
        + shlex.quote(sys.executable)
        + " "
        + shlex.quote(str(runner))
        + ' "$@" --hotspot '
        + shlex.quote(str(HOTSPOT))
        + "\n"
    )
    (sim / "run.sh").write_text(wrapper, encoding="utf-8")
    (sim / "run.sh").chmod(0o755)
    sys.path.insert(0, str(THERMODSE))
    from core.chiplet_eva import chiplet_evaluator  # type: ignore
    from core.layer import GemmLayer  # type: ignore

    # The base and Conv APIs default to one-byte words; the pinned Gemm
    # override accidentally dropped that default. Keep the submodule clean
    # and restore only the upstream interface convention at runtime.
    original_filter_size = GemmLayer.total_filter_size
    if original_filter_size.__defaults__ is None:
        GemmLayer.total_filter_size = (  # type: ignore[assignment]
            lambda self, word_bytes=1: original_filter_size(self, word_bytes)
        )

    evaluator = chiplet_evaluator(
        hotspot_path=str(HOTSPOT.parent),
        sim_path=str(sim),
        sys_info=_architecture(arch),
        thermal_map=False,
        baseline1=False,
        baseline2=False,
        baseline3=False,
        wkld_idpdt=False,
        clock_freq=1.8e9,
    )
    evaluator.nets = [workload["thermodse_name"]]
    evaluator.b_tot = [int(workload["b_tot"])]
    evaluator.b_exe = [int(workload["b_exe"])]
    evaluator.sparsty = [float(workload["sparsity"])]
    evaluator.generate_hardware()
    latency, energy, die_yield = evaluator.evaluate()
    trace = sim / "ptrace" / "name_aligned.ptrace"
    lines = [line.split() for line in trace.read_text(encoding="utf-8").splitlines()]
    if len(lines) != 2 or len(lines[0]) != len(lines[1]):
        raise RuntimeError("frozen workload capture requires exactly one aligned power sample")
    floorplan = sim / "floorplan" / "output_3D.flp"
    capture.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        capture,
        block_ids=np.asarray(lines[0]),
        placed_power_w=np.asarray(lines[1], dtype=float),
        floorplan_text=np.asarray(floorplan.read_text(encoding="utf-8")),
        latency_ms=np.asarray(latency),
        energy_mj=np.asarray(energy),
        die_yield=np.asarray(die_yield),
    )
    return capture


def _bounded_power(
    total_w: float, upper_w: np.ndarray, weights: np.ndarray
) -> np.ndarray:
    """Deterministically project positive weights onto a bounded simplex."""

    upper, weights = np.asarray(upper_w, dtype=float), np.asarray(weights, dtype=float)
    if (
        upper.shape != weights.shape
        or total_w <= 0
        or total_w > float(np.sum(upper))
        or np.any(upper < 0)
        or np.any(weights <= 0)
    ):
        raise ValueError("invalid bounded-simplex calibration inputs")
    low, high = 0.0, total_w / float(np.min(weights))
    for _ in range(80):
        scale = (low + high) / 2
        if float(np.sum(np.minimum(upper, scale * weights))) < total_w:
            low = scale
        else:
            high = scale
    power = np.minimum(upper, high * weights)
    residual = total_w - float(np.sum(power))
    available = np.flatnonzero(power < upper)
    if available.size:
        power[available[0]] += residual
    elif abs(residual) > 1e-10:
        raise RuntimeError("bounded-simplex projection did not conserve power")
    return power


def _operator(
    arch: dict[str, str],
    package: dict[str, str],
    captures: Iterable[Path],
    output: Path,
) -> Path:
    target = output / "operators" / f"{arch['architecture_id']}--{package['package_id']}.npz"
    captures = tuple(captures)
    calibration_path = target.with_suffix(".calibration.tsv")
    expected_rows = len(captures) * (2 + len(CALIBRATION_SEEDS)) * len(MODELS)
    if target.is_file() and calibration_path.is_file():
        cached = _rows(calibration_path)
        if len(cached) == expected_rows and {
            row["vector_id"] for row in cached
        } == set(CALIBRATION_VECTOR_IDS):
            return target
    target.unlink(missing_ok=True)
    calibration_path.unlink(missing_ok=True)
    work = output / "work" / f"operator--{arch['architecture_id']}--{package['package_id']}"
    work.mkdir(parents=True, exist_ok=True)
    with np.load(captures[0], allow_pickle=False) as data:
        floorplan = work / "floorplan.flp"
        floorplan.write_text(str(data["floorplan_text"]), encoding="utf-8")
    config = work / "package.config"
    _configure(TEMPLATE / "example.config", config, package)
    family, blocks = build_family(
        HOTSPOT,
        config,
        floorplan,
        TEMPLATE / "example.materials",
        MODELS,
        work / "impulses",
        THERMAL_LIMIT_K,
    )
    calibration = []
    rejected = []
    for capture_index, capture in enumerate(captures):
        with np.load(capture, allow_pickle=False) as data:
            placed_power = np.asarray(data["placed_power_w"], dtype=float)
        upper = content_upper_bounds(blocks, placed_power)
        vectors = [
            ("placed", placed_power),
            (
                "bounded-uniform",
                _bounded_power(
                    float(np.sum(placed_power)), upper, np.ones(upper.size)
                ),
            ),
        ]
        for seed in CALIBRATION_SEEDS:
            vectors.append(
                (
                    f"bounded-random-{seed}",
                    _bounded_power(
                        float(np.sum(placed_power)),
                        upper,
                        np.random.default_rng(seed).lognormal(size=upper.size),
                    ),
                )
            )
        for vector_id, power in vectors:
            digest = hashlib.sha256(np.asarray(power, dtype="<f8").tobytes()).hexdigest()
            for model_index, model_id in enumerate(family.model_ids):
                direct = replay_power(
                    HOTSPOT,
                    config,
                    floorplan,
                    TEMPLATE / "example.materials",
                    model_id,
                    blocks,
                    power,
                    work
                    / "calibration"
                    / f"{capture_index}--{vector_id}--{model_id}",
                )
                predicted = (
                    family.ambient_k[model_index]
                    + family.response_k_per_w[model_index] @ power
                )
                error = float(np.max(np.abs(direct - predicted)))
                calibration.append(
                    {
                        "capture": capture.name,
                        "vector_id": vector_id,
                        "power_sha256": digest,
                        "model_id": model_id,
                        "max_abs_error_k": error,
                        "registered_error_k": MODEL_ERROR_LIMIT_K,
                        "bound_status": (
                            "PASS" if error <= MODEL_ERROR_LIMIT_K else "REJECT"
                        ),
                    }
                )
                if error > MODEL_ERROR_LIMIT_K:
                    rejected.append((capture.name, vector_id, model_id, error))
    _write_tsv(calibration_path, calibration)
    if rejected:
        worst = max(rejected, key=lambda item: item[-1])
        raise RuntimeError(
            "frozen 0.01 K error contract rejected "
            f"{len(rejected)} replay(s); worst={worst[0]}/{worst[1]}/"
            f"{worst[2]}:{worst[3]:.6g} K"
        )
    family = type(family)(
        family.model_ids,
        family.response_k_per_w,
        family.ambient_k,
        family.limit_k,
        family.provenance_sha256,
        np.full(len(family.model_ids), MODEL_ERROR_LIMIT_K),
    )
    save_family(target, family, blocks)
    return target


def _power_space(
    capture: Path,
) -> tuple[PowerPolytope, tuple[str, ...], np.ndarray, str]:
    with np.load(capture, allow_pickle=False) as data:
        blocks = tuple(data["block_ids"].tolist())
        placed = np.asarray(data["placed_power_w"], dtype=float)
        floorplan_text = str(data["floorplan_text"])
    return (
        coarse_power_space(placed, content_upper_bounds(blocks, placed)),
        blocks,
        placed,
        floorplan_text,
    )


def _write_tsv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    rows = list(rows)
    if not rows:
        raise RuntimeError("refusing to write empty evidence table")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        fieldnames = list(
            dict.fromkeys(key for row in rows for key in row)
        )
        writer = csv.DictWriter(stream, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _measurement_costs() -> dict[str, float]:
    rows = _rows(ROOT / "experiments" / "measurements.tsv")
    return {row["action_class"]: float(row["cost"]) for row in rows}


def _timed_call(function: Callable[[], _T]) -> tuple[Optional[_T], float, str]:
    """Run one query method with a fail-closed wall-clock budget."""

    def expire(_signum, _frame) -> None:
        raise TimeoutError(f"{QUERY_METHOD_TIMEOUT_S}s method budget exhausted")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, QUERY_METHOD_TIMEOUT_S)
    started = time.perf_counter()
    try:
        return function(), time.perf_counter() - started, ""
    except Exception as exc:
        return None, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _placed_outcomes(
    candidates: Iterable[CandidateSpace],
    placed_by_candidate: Mapping[str, np.ndarray],
    margin_k: float = 1e-4,
) -> tuple[str, ...]:
    state_sets = []
    candidates = tuple(candidates)
    for candidate in candidates:
        power = placed_by_candidate[candidate.candidate_id]
        thermal = candidate.thermal
        states = set()
        for model_index, (model, error) in enumerate(
            zip(thermal.response_k_per_w, thermal.error_k)
        ):
            peak = float(
                np.max(thermal.ambient_k[model_index] + model @ power)
            )
            if peak <= thermal.limit_k - margin_k + error:
                states.add("SAFE")
            if peak >= thermal.limit_k + margin_k - error:
                states.add("UNSAFE")
        if not states:
            states.add("NUMERICAL_GAP")
        state_sets.append(tuple(sorted(states)))
    outcomes = set()
    for states in product(*state_sets):
        decision = "NO_FEASIBLE_CANDIDATE"
        for candidate, state in zip(candidates, states):
            if state == "SAFE":
                decision = candidate.candidate_id
                break
            if state == "NUMERICAL_GAP":
                decision = "UNRESOLVED"
                break
        outcomes.add(decision)
    return tuple(sorted(outcomes))


def _save_unsynth_witness(path: Path, plan) -> bool:
    if plan.status != "UNSYNTHESIZABLE" or not plan.witnesses:
        return False
    witness = plan.witnesses[-1]
    payload: dict[str, np.ndarray] = {
        "left_decision": np.asarray(witness.left_decision),
        "right_decision": np.asarray(witness.right_decision),
    }
    for index, pair in enumerate(witness.candidates):
        prefix = f"candidate_{index}"
        payload[f"{prefix}_id"] = np.asarray(pair.candidate_id)
        payload[f"{prefix}_left_power_w"] = pair.left_power_w
        payload[f"{prefix}_right_power_w"] = pair.right_power_w
        payload[f"{prefix}_left_state"] = np.asarray(pair.left_state)
        payload[f"{prefix}_right_state"] = np.asarray(pair.right_state)
        payload[f"{prefix}_left_model"] = np.asarray(pair.left_model_id)
        payload[f"{prefix}_right_model"] = np.asarray(pair.right_model_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **payload)
    return True


def _write_report(
    path: Path,
    split: str,
    operators: Mapping[tuple[str, str], Path],
    results: Iterable[dict[str, object]],
    order_rows: Iterable[dict[str, object]],
    failures: Iterable[dict[str, object]],
) -> None:
    rows, failures = list(results), list(failures)
    statuses = {
        status: sum(row.get("exact_status") == status for row in rows)
        for status in ("OPTIMAL", "UNSYNTHESIZABLE", "UNRESOLVED")
    }
    resolved = [
        row
        for row in rows
        if row.get("exact_status") == "OPTIMAL"
        and row.get("exact_cost") is not None
    ]
    savings = [
        1 - float(row["exact_cost"]) / float(row["full_registry_cost"])
        for row in resolved
    ]
    false_certificates = sum(
        int(row.get("false_certificate") or 0) for row in rows
    )
    comparable = [
        row for row in resolved if row.get("dual_cost") != "" and row.get("width_cost") != ""
    ]
    dual_wins = sum(
        float(row["dual_cost"]) < float(row["width_cost"])
        for row in comparable
    )
    calibration_errors = []
    for operator in operators.values():
        for row in _rows(operator.with_suffix(".calibration.tsv")):
            calibration_errors.append(float(row["max_abs_error_k"]))
    lines = [
        f"# CertiTherm {split} gate report",
        "",
        f"- Physical operators admitted: {len(operators)}",
        f"- Exact status: {statuses}",
        f"- Placed-reference false certificates: {false_certificates}",
        (
            f"- Maximum direct-replay residual: {max(calibration_errors):.9g} K "
            f"(frozen bound {MODEL_ERROR_LIMIT_K:.3g} K)"
            if calibration_errors
            else "- Maximum direct-replay residual: unavailable"
        ),
        (
            f"- Median exact saving vs full registry: {np.median(savings):.1%}"
            if savings
            else "- Median exact saving vs full registry: unavailable"
        ),
        f"- Dual policy beats width: {dual_wins}/{len(comparable)} comparable queries",
        f"- Archived failures: {len(failures)}",
        "",
        "## Workload-specific EDYP order",
        "",
        "| Workload | Rank | Architecture | EDYP |",
        "|---|---:|---|---:|",
    ]
    for row in order_rows:
        lines.append(
            f"| {row['workload']} | {row['objective_rank']} | "
            f"{row['architecture']} | {float(row['edyp']):.9g} |"
        )
    lines += [
        "",
        "The exact cost is the registered finite-library non-adaptive batch "
        "optimum, not an unrestricted or continuous-adaptive sensor limit.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def run(split: str, output: Path, frozen: bool) -> None:
    if frozen and split != "heldout":
        raise ValueError("--frozen is reserved for the held-out split")
    if not HOTSPOT.is_file() or not THERMODSE.is_dir():
        raise RuntimeError("run make bootstrap before experiments")
    output.mkdir(parents=True, exist_ok=True)
    architectures = sorted(
        (
            row
            for row in _rows(ROOT / "experiments" / "architectures.tsv")
            if row["split"] == split
        ),
        key=lambda row: int(row["rank"]),
    )
    packages = _rows(ROOT / "experiments" / "packages.tsv")
    measurement_costs = _measurement_costs()
    workloads = [
        row for row in _rows(ROOT / "experiments" / "workloads.tsv") if row["split"] == split
    ]
    default_package = next(row for row in packages if row["package_id"] == "default")
    captures = {
        (workload["workload_id"], arch["architecture_id"]): _capture(
            arch, workload, default_package, output
        )
        for workload in workloads
        for arch in architectures
    }
    failures, operators = [], {}
    for arch in architectures:
        for package in packages:
            key = arch["architecture_id"], package["package_id"]
            try:
                operators[key] = _operator(
                    arch,
                    package,
                    [
                        captures[(workload["workload_id"], arch["architecture_id"])]
                        for workload in workloads
                    ],
                    output,
                )
            except Exception as exc:  # archive physical/timeout failures unchanged
                failures.append(
                    {
                        "stage": "operator",
                        "workload": "ALL",
                        "architecture": key[0],
                        "package": key[1],
                        "failure_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
    results, order_rows, registry_rows, plan_rows, witness_rows = [], [], [], [], []
    for workload in workloads:
        ordered_arches = _ordered_architectures(
            workload["workload_id"], architectures, captures
        )
        for rank, arch in enumerate(ordered_arches):
            metrics = _capture_metrics(
                captures[(workload["workload_id"], arch["architecture_id"])]
            )
            order_rows.append(
                {
                    "workload": workload["workload_id"],
                    "objective_rank": rank,
                    "architecture": arch["architecture_id"],
                    **metrics,
                }
            )
        for package in packages:
            candidates, actions = [], []
            placed_by_candidate = {}
            missing = [
                arch["architecture_id"]
                for arch in ordered_arches
                if (arch["architecture_id"], package["package_id"]) not in operators
            ]
            if missing:
                results.append(
                    {
                        "freeze_id": "method-freeze-v1",
                        "split": split,
                        "workload": workload["workload_id"],
                        "package": package["package_id"],
                        "objective": "EDYP_ASCENDING",
                        "candidate_order": ";".join(
                            arch["architecture_id"] for arch in ordered_arches
                        ),
                        "exact_status": "UNRESOLVED",
                        "failure": f"missing operators: {','.join(missing)}",
                    }
                )
                continue
            for arch in ordered_arches:
                candidate_id = arch["architecture_id"]
                power, blocks, placed, floorplan_text = _power_space(
                    captures[(workload["workload_id"], candidate_id)]
                )
                family, operator_blocks = load_family(
                    operators[(candidate_id, package["package_id"])]
                )
                if blocks != operator_blocks:
                    raise RuntimeError("power/operator block identity mismatch")
                candidates.append(CandidateSpace(candidate_id, power, family))
                placed_by_candidate[candidate_id] = placed
                candidate_actions = build_measurement_library(
                    candidate_id,
                    blocks,
                    floorplan_text,
                    arch,
                    measurement_costs,
                )
                actions.extend(candidate_actions)
                for action in candidate_actions:
                    action_class = action.action_id.split("::")[1]
                    registry_rows.append(
                        {
                            "split": split,
                            "workload": workload["workload_id"],
                            "package": package["package_id"],
                            "candidate": candidate_id,
                            "action_id": action.action_id,
                            "action_class": action_class,
                            "cost": action.cost,
                            "support_size": int(np.count_nonzero(action.vector)),
                        }
                    )
            query_id = f"{workload['workload_id']}--{package['package_id']}"
            candidate_rank = {
                candidate.candidate_id: rank
                for rank, candidate in enumerate(candidates)
            }
            fixed_order = tuple(
                sorted(
                    range(len(actions)),
                    key=lambda index: (
                        actions[index].cost,
                        candidate_rank[actions[index].candidate_id],
                        actions[index].action_id,
                    ),
                )
            )
            exact, exact_seconds, exact_error = _timed_call(
                lambda: synthesize_ordered_query(candidates, actions)
            )
            fixed, fixed_seconds, fixed_error = _timed_call(
                lambda: sequential_early_stop(candidates, actions, fixed_order)
            )
            width, width_seconds, width_error = _timed_call(
                lambda: sequential_early_stop(
                    candidates,
                    actions,
                    uncertainty_width_order(candidates, actions),
                )
            )
            dual, dual_seconds, dual_error = _timed_call(
                lambda: dual_price_greedy(candidates, actions)
            )
            method_errors = {
                name: error
                for name, error in (
                    ("exact_dsos", exact_error),
                    ("fixed_early_stop", fixed_error),
                    ("uncertainty_width", width_error),
                    ("dual_price", dual_error),
                )
                if error
            }
            for method, error in method_errors.items():
                failures.append(
                    {
                        "stage": method,
                        "workload": workload["workload_id"],
                        "architecture": "ORDERED_SET",
                        "package": package["package_id"],
                        "failure_type": error.split(":", 1)[0],
                        "message": error,
                    }
                )
            witness_path = output / "witnesses" / f"{query_id}.npz"
            if exact is not None and _save_unsynth_witness(witness_path, exact):
                witness_rows.append(
                    {
                        "query_id": query_id,
                        "status": exact.status,
                        "left_decision": exact.witnesses[-1].left_decision,
                        "right_decision": exact.witnesses[-1].right_decision,
                        "path": str(witness_path.relative_to(output)),
                    }
                )
            for policy_name, policy in (
                ("exact_dsos", exact),
                ("fixed_early_stop", fixed),
                ("uncertainty_width", width),
                ("dual_price", dual),
            ):
                if policy is None:
                    continue
                selected = policy.selected_action_ids
                plan_rows.append(
                    {
                        "query_id": query_id,
                        "policy": policy_name,
                        "status": policy.status,
                        "cost": (
                            policy.exact_cost
                            if policy_name == "exact_dsos"
                            else policy.cost
                        ),
                        "selected_count": len(selected),
                        "selected_action_ids": ";".join(selected),
                    }
                )
            placed_outcomes = _placed_outcomes(candidates, placed_by_candidate)
            results.append(
                {
                    "freeze_id": "method-freeze-v1",
                    "split": split,
                    "workload": workload["workload_id"],
                    "package": package["package_id"],
                    "objective": "EDYP_ASCENDING",
                    "candidate_order": ";".join(
                        candidate.candidate_id for candidate in candidates
                    ),
                    "exact_status": exact.status if exact else "UNRESOLVED",
                    "exact_cost": exact.exact_cost if exact else "",
                    "milp_lower_bound": exact.lower_bound if exact else "",
                    "lp_relaxation_bound": (
                        exact.relaxation_bound if exact else ""
                    ),
                    "optimality_gap": exact.optimality_gap if exact else "",
                    "fixed_status": fixed.status if fixed else "UNRESOLVED",
                    "fixed_cost": fixed.cost if fixed else "",
                    "width_status": width.status if width else "UNRESOLVED",
                    "width_cost": width.cost if width else "",
                    "dual_status": dual.status if dual else "UNRESOLVED",
                    "dual_cost": dual.cost if dual else "",
                    "exact_seconds": exact_seconds,
                    "fixed_seconds": fixed_seconds,
                    "width_seconds": width_seconds,
                    "dual_seconds": dual_seconds,
                    "full_registry_cost": sum(action.cost for action in actions),
                    "witnesses": len(exact.witnesses),
                    "placed_reachable_outcomes": ";".join(placed_outcomes),
                    "placed_outcome_count": len(placed_outcomes),
                    "false_certificate": (
                        int(len(placed_outcomes) != 1)
                        if exact is not None and exact.status == "OPTIMAL"
                        else ""
                    ),
                    "failure": "; ".join(
                        f"{method}={error}" for method, error in method_errors.items()
                    ),
                }
            )
    result_path = output / "results.tsv"
    _write_tsv(result_path, results)
    _write_tsv(output / "candidate_order.tsv", order_rows)
    if registry_rows:
        _write_tsv(output / "measurement_registry.tsv", registry_rows)
    if plan_rows:
        _write_tsv(output / "plans.tsv", plan_rows)
    if witness_rows:
        _write_tsv(output / "witnesses.tsv", witness_rows)
    if failures:
        _write_tsv(output / "FAILURES.tsv", failures)
    _write_report(
        output / "REPORT.md",
        split,
        operators,
        results,
        order_rows,
        failures,
    )
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    scientific_paths = [
        path
        for path in sorted(output.rglob("*"))
        if (
            path.is_file()
            and "work" not in path.parts
            and path.name not in {"SHA256SUMS", "ARTIFACTS.tsv"}
        )
    ]
    sums = output / "SHA256SUMS"
    sums.write_text(
        "".join(
            f"{_sha256(path)}  {path.relative_to(output)}\n"
            for path in scientific_paths
        ),
        encoding="utf-8",
    )
    artifacts = []
    for path in sorted(output.rglob("*")):
        if (
            path.is_file()
            and "work" not in path.parts
            and path.name != "ARTIFACTS.tsv"
        ):
            artifacts.append(
                {
                    "role": (
                        "result"
                        if path.name
                        in {
                            "results.tsv",
                            "plans.tsv",
                            "REPORT.md",
                            "witnesses.tsv",
                        }
                        or "witnesses" in path.parts
                        else "scientific_input"
                    ),
                    "path": str(path.relative_to(output)),
                    "sha256": _sha256(path),
                    "git_sha": git_sha,
                    "producer": f"make {'heldout' if frozen else 'reproduce-dev'}",
                }
            )
    _write_tsv(output / "ARTIFACTS.tsv", artifacts)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--ignore-submodules=none"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise RuntimeError(f"repository became dirty during experiment:\n{status}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "heldout"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frozen", action="store_true")
    args = parser.parse_args()
    run(args.split, args.output, args.frozen)


if __name__ == "__main__":
    main()
