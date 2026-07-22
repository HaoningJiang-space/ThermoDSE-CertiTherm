"""Frozen ThermoDSE/HotSpot experiment driver with resumable NPZ evidence."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import csv
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
from dataclasses import dataclass
import signal
import subprocess
import sys
import time
from typing import Callable, Generic, Iterable, Mapping, Optional, Sequence, TypeVar

import numpy as np

from .core import (
    CandidateSpace,
    MeasurementAction,
    PowerPolytope,
    QueryObservationPlan,
)
from .gpu_hotspot import GpuHotSpotBackend
from .hotspot import build_family, load_family, replay_power, save_family
from .measurements import (
    build_measurement_library,
    coarse_power_space,
    content_upper_bounds,
)
from .policies import (
    PolicyResult,
    dual_price_greedy,
    sequential_early_stop,
    uncertainty_width_order,
)
from .spectral import (
    audit_ranks,
    certified_tail_bound_k,
    channel_spectral_leverage,
    thermal_spectrum,
)
from .synthesis import synthesize_ordered_query


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "CertiTherm" / "evidence" / "thermodse_tmp_template"
THERMODSE = ROOT / "ThermoDSE"
HOTSPOT = ROOT / ".build" / "hotspot" / "hotspot"
GPU_HOTSPOT_EXPORTER = ROOT / ".build" / "hotspot-gpu-export" / "hotspot"
GPU_HOTSPOT_SOLVER = ROOT / ".build" / "hotspot-cuda" / "certitherm_hotspot_cuda"
MODELS = ("block", "grid64-avg", "grid128-avg")
THERMAL_LIMIT_K = 330.0
MODEL_ERROR_LIMIT_K = 0.01
HOTSPOT_TOTAL_WORKERS = min(48, os.cpu_count() or 1)
OPERATOR_WORKERS = min(3, HOTSPOT_TOTAL_WORKERS)
HOTSPOT_WORKERS = max(1, HOTSPOT_TOTAL_WORKERS // OPERATOR_WORKERS)
CALIBRATION_SEEDS = (17, 23, 41)
CALIBRATION_VECTOR_IDS = (
    "placed",
    "bounded-uniform",
    *(f"bounded-random-{seed}" for seed in CALIBRATION_SEEDS),
)
# Frozen at 1800s by method-freeze-v1 and v2.1. The override exists ONLY for
# schema rehearsals, which verify that the artifact columns populate correctly
# without paying the full budget. A rehearsal is not evidence: any run whose
# budget differs from 1800 must be labelled as such and must never be reported
# against a frozen pass condition.
QUERY_METHOD_TIMEOUT_S = float(os.environ.get("CERTITHERM_QUERY_BUDGET_S", "1800"))
FROZEN_QUERY_BUDGET_S = 1800.0
_BUDGET_IS_FROZEN = abs(QUERY_METHOD_TIMEOUT_S - FROZEN_QUERY_BUDGET_S) < 1e-9
_T = TypeVar("_T")


class NonthermalCandidateInvalid(RuntimeError):
    """A candidate completed evaluation but produced inadmissible metrics."""


def _gpu_backend() -> Optional[GpuHotSpotBackend]:
    if os.environ.get("CERTITHERM_GPU_HOTSPOT", "0") != "1":
        return None
    return GpuHotSpotBackend(
        GPU_HOTSPOT_EXPORTER,
        GPU_HOTSPOT_SOLVER,
        device=int(os.environ.get("CERTITHERM_GPU_DEVICE", "0")),
    )


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


def _prepare_thermodse_sim(
    arch: dict[str, str],
    workload: dict[str, str],
    package: dict[str, str],
    output: Path,
    *,
    allow_hotspot: bool,
) -> Path:
    """Create one isolated ThermoDSE work directory and backend entrypoint."""

    kind = "capture" if allow_hotspot else "precheck"
    sim = output / "work" / f"{kind}--{workload['workload_id']}--{arch['architecture_id']}"
    if sim.exists():
        shutil.rmtree(sim)
    shutil.copytree(TEMPLATE, sim)
    _configure(TEMPLATE / "example.config", sim / "example.config", package)
    if allow_hotspot:
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
    else:
        for stale_temperature in (sim / "outputs").glob("*.steady"):
            stale_temperature.unlink()
        wrapper = (
            "#!/bin/sh\n"
            "echo 'HotSpot is forbidden during the non-thermal precheck' >&2\n"
            "exit 97\n"
        )
    (sim / "run.sh").write_text(wrapper, encoding="utf-8")
    (sim / "run.sh").chmod(0o755)
    return sim


def _thermodse_evaluator(
    arch: dict[str, str],
    workload: dict[str, str],
    sim: Path,
):
    """Build the pinned evaluator after installing narrow API shims."""

    thermodse_path = str(THERMODSE)
    if thermodse_path not in sys.path:
        sys.path.insert(0, thermodse_path)
    from core.chiplet_eva import chiplet_evaluator  # type: ignore

    _install_thermodse_compatibility()

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
    return evaluator


def _install_thermodse_compatibility() -> None:
    """Repair two pinned-upstream API drifts without modifying the submodule."""

    from core.layer import GemmLayer  # type: ignore
    from core.network import Network  # type: ignore

    # The base and Conv APIs default to one-byte words; the pinned Gemm
    # override accidentally dropped that default. Keep the submodule clean
    # and restore only the upstream interface convention at runtime.
    original_filter_size = GemmLayer.total_filter_size
    if original_filter_size.__defaults__ is None:
        def filter_size_with_default(self, word_bytes=1):
            return original_filter_size(self, word_bytes)

        GemmLayer.total_filter_size = filter_size_with_default  # type: ignore[assignment]

    # Two bundled upstream network definitions still use the predecessor
    # keyword `prevs`; the pinned Network implementation renamed it to
    # `ifm_prevs`. Preserve one implementation and expose only that alias.
    original_add = Network.add
    if not getattr(original_add, "_certitherm_accepts_prevs", False):
        def add_with_prevs(
            self,
            layer_name,
            layer,
            ifm_prevs=None,
            wgt_prevs=None,
            *,
            prevs=None,
        ):
            if prevs is not None:
                if ifm_prevs is not None:
                    raise TypeError("specify only one of prevs and ifm_prevs")
                ifm_prevs = prevs
            return original_add(self, layer_name, layer, ifm_prevs, wgt_prevs)

        add_with_prevs._certitherm_accepts_prevs = True  # type: ignore[attr-defined]
        Network.add = add_with_prevs  # type: ignore[assignment]


def _capture(
    arch: dict[str, str],
    workload: dict[str, str],
    package: dict[str, str],
    output: Path,
) -> Path:
    capture = output / "captures" / f"{workload['workload_id']}--{arch['architecture_id']}.npz"
    if capture.is_file():
        return capture
    sim = _prepare_thermodse_sim(
        arch,
        workload,
        package,
        output,
        allow_hotspot=True,
    )
    evaluator = _thermodse_evaluator(arch, workload, sim)
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


@contextmanager
def _hotspot_disabled(evaluator):
    """Disable both ThermoDSE routes to HotSpot for a narrow code region."""

    from core import chiplet_eva as evaluator_module  # type: ignore

    original_run_hotspot = evaluator.flp_generator.run_hotspot
    original_find_hotpoint = evaluator_module.find_hotpoint

    def skip_hotspot(*_args, **_kwargs) -> None:
        return None

    def unavailable_temperature(*_args, **_kwargs) -> float:
        return float("nan")

    evaluator.flp_generator.run_hotspot = skip_hotspot
    evaluator_module.find_hotpoint = unavailable_temperature
    try:
        yield
    finally:
        evaluator.flp_generator.run_hotspot = original_run_hotspot
        evaluator_module.find_hotpoint = original_find_hotpoint


def evaluate_nonthermal_candidate(
    arch: dict[str, str],
    workload: dict[str, str],
    package: dict[str, str],
    output: Path,
) -> dict[str, float]:
    """Evaluate EDYP inputs while making any HotSpot invocation fail closed.

    The pinned ThermoDSE evaluator calls HotSpot even with `thermal_map=False`.
    A pre-open feasibility check must not produce a held-out temperature, so it
    disables the Python call and installs a shell sentinel as a second guard.
    The temporary power/floorplan intermediates are deleted before return.
    """

    sim = _prepare_thermodse_sim(
        arch,
        workload,
        package,
        output,
        allow_hotspot=False,
    )
    try:
        evaluator = _thermodse_evaluator(arch, workload, sim)
        evaluator.generate_hardware()
        with _hotspot_disabled(evaluator):
            latency, energy, die_yield = evaluator.evaluate()
        if any((sim / "outputs").glob("*.steady")):
            raise RuntimeError("non-thermal precheck produced a HotSpot output")
        metrics = {
            "latency_ms": float(latency),
            "energy_mj": float(energy),
            "die_yield": float(die_yield),
        }
        if min(metrics.values()) <= 0 or not all(
            np.isfinite(value) for value in metrics.values()
        ):
            raise NonthermalCandidateInvalid(
                "non-thermal precheck produced non-positive or non-finite metrics"
            )
        metrics["edyp"] = (
            metrics["latency_ms"]
            * metrics["energy_mj"]
            / metrics["die_yield"]
        )
        return metrics
    finally:
        shutil.rmtree(sim, ignore_errors=True)


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
    workers: int = HOTSPOT_WORKERS,
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
        workers=workers,
        gpu_backend=_gpu_backend(),
    )
    jobs = []
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
                jobs.append(
                    (
                        capture_index,
                        capture.name,
                        vector_id,
                        digest,
                        model_index,
                        model_id,
                        power,
                    )
                )

    def calibrate(job):
        capture_index, capture_name, vector_id, digest, model_index, model_id, power = job
        direct = replay_power(
            HOTSPOT,
            config,
            floorplan,
            TEMPLATE / "example.materials",
            model_id,
            blocks,
            power,
            work / "calibration" / f"{capture_index}--{vector_id}--{model_id}",
        )
        predicted = (
            family.ambient_k[model_index]
            + family.response_k_per_w[model_index] @ power
        )
        error = float(np.max(np.abs(direct - predicted)))
        return {
            "capture": capture_name,
            "vector_id": vector_id,
            "power_sha256": digest,
            "model_id": model_id,
            "max_abs_error_k": error,
            "registered_error_k": MODEL_ERROR_LIMIT_K,
            "bound_status": "PASS" if error <= MODEL_ERROR_LIMIT_K else "REJECT",
        }

    with ThreadPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
        calibration = list(pool.map(calibrate, jobs))
    rejected = [
        (
            row["capture"],
            row["vector_id"],
            row["model_id"],
            row["max_abs_error_k"],
        )
        for row in calibration
        if row["bound_status"] == "REJECT"
    ]
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


def _budgeted_call(
    function: Callable[[], _T], budget_s: float
) -> tuple[Optional[_T], float, str]:
    """Run one call under an explicit wall-clock budget.

    Same fail-closed contract as `_timed_call` but with the budget passed in,
    so a controller can split ONE budget across phases instead of each method
    silently receiving a fresh full budget.
    """

    def expire(_signum, _frame) -> None:
        raise TimeoutError(f"{budget_s:.0f}s budget exhausted")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, max(budget_s, 0.001))
    started = time.perf_counter()
    try:
        return function(), time.perf_counter() - started, ""
    except Exception as exc:
        return None, time.perf_counter() - started, f"{type(exc).__name__}: {exc}"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@dataclass(frozen=True)
class CertifiedContract:
    """One oracle-certified upper bound and the actions that replay it."""

    source: str
    action_ids: tuple[str, ...]
    cost: float

    def __post_init__(self) -> None:
        if self.source not in ("width", "exact"):
            raise ValueError(f"unsupported contract source {self.source}")
        if self.cost < 0:
            raise ValueError("certified contract cost must be nonnegative")


@dataclass(frozen=True)
class AnytimeResult:
    """Proof state returned by one end-to-end Anytime-DSOS budget.

    `contract` is the only source of an upper bound.  Keeping its cost, action
    IDs and source in one object prevents a result row from combining a number
    from one policy with a plan from another.  `proof_search` is the exact/IHS
    phase that supplies the lower bound and, when it closes, the optimality
    proof.

    Therefore `lower_bound <= C* <= upper_bound` is a genuine interval rather
    than a pairing of two independently budgeted runs. That distinction is the
    whole point of method-freeze-v2.1's budget clause: reporting a `U` from one
    1800s run beside an `L` from another describes no single algorithm.
    """

    contract: Optional[CertifiedContract]
    proof_search: Optional[QueryObservationPlan]
    upper_seconds: float
    lower_seconds: float
    errors: tuple[str, ...] = ()

    @property
    def upper_bound(self) -> Optional[float]:
        return None if self.contract is None else self.contract.cost

    @property
    def upper_action_ids(self) -> tuple[str, ...]:
        return () if self.contract is None else self.contract.action_ids

    @property
    def upper_source(self) -> str:
        return "none" if self.contract is None else self.contract.source

    @property
    def lower_bound(self) -> Optional[float]:
        return None if self.proof_search is None else self.proof_search.lower_bound

    @property
    def error(self) -> str:
        return "; ".join(self.errors)

    @property
    def approximation_ratio(self) -> Optional[float]:
        """Certified multiplicative bound U/L; one means proven optimal."""
        if (
            self.upper_bound is None
            or self.lower_bound is None
            or self.interval_violation
        ):
            return None
        if self.lower_bound > 0:
            return self.upper_bound / self.lower_bound
        if self.upper_bound == 0:
            return 1.0
        return None

    @property
    def relative_gap(self) -> Optional[float]:
        """Standard lower-bound-relative gap, equal to U/L - 1."""
        ratio = self.approximation_ratio
        return None if ratio is None else max(0.0, ratio - 1.0)

    @property
    def absolute_gap(self) -> Optional[float]:
        if (
            self.upper_bound is None
            or self.lower_bound is None
            or self.interval_violation
        ):
            return None
        return max(0.0, self.upper_bound - self.lower_bound)

    @property
    def interval_violation(self) -> str:
        if (
            self.upper_bound is not None
            and self.proof_search is not None
            and self.proof_search.status == "UNSYNTHESIZABLE"
        ):
            return "certified upper plan conflicts with UNSYNTHESIZABLE result"
        if self.upper_bound is None or self.lower_bound is None:
            return ""
        slack = 1e-6 * max(1.0, abs(self.upper_bound))
        if self.lower_bound > self.upper_bound + slack:
            return f"L={self.lower_bound} exceeds U={self.upper_bound}"
        return ""

    @property
    def bound_provenance(self) -> str:
        if self.lower_bound is None or self.proof_search is None:
            return ""
        return self.proof_search.bound_provenance or ""

    @property
    def plan_validity(self) -> str:
        if self.interval_violation:
            return "UNRESOLVED"
        if self.upper_bound is not None:
            return "CERTIFIED"
        if (
            self.proof_search is not None
            and self.proof_search.status == "UNSYNTHESIZABLE"
        ):
            return "UNSYNTHESIZABLE"
        return "UNRESOLVED"

    @property
    def cost_optimality(self) -> str:
        if self.interval_violation:
            return "UNKNOWN"
        if (
            self.proof_search is not None
            and self.proof_search.status == "UNSYNTHESIZABLE"
        ):
            return "NOT_APPLICABLE"
        if (
            self.proof_search is not None
            and self.proof_search.status == "OPTIMAL"
            and self.upper_source == "exact"
        ):
            return self.proof_search.cost_optimality
        if self.upper_bound is not None and self.lower_bound is not None:
            return "BOUNDED_GAP"
        return "UNKNOWN"


def _certified_contract(
    actions: Sequence[MeasurementAction],
    *,
    status: str,
    action_ids: tuple[str, ...],
    claimed_cost: Optional[float],
    source: str,
) -> CertifiedContract:
    """Validate and bind a certified plan before it can become an upper bound."""

    if status not in ("CERTIFIED", "OPTIMAL") or claimed_cost is None:
        raise RuntimeError(f"{source} did not return a certified upper plan")
    if len(set(action_ids)) != len(action_ids):
        raise RuntimeError(f"{source} upper plan contains duplicate actions")

    action_costs = {action.action_id: action.cost for action in actions}
    if len(action_costs) != len(actions):
        raise ValueError("measurement action IDs must be unique")
    try:
        replayed_cost = sum(action_costs[action_id] for action_id in action_ids)
    except KeyError as exc:
        raise RuntimeError(
            f"{source} upper plan contains unregistered action {exc.args[0]}"
        ) from exc

    slack = 1e-9 * max(1.0, abs(claimed_cost), abs(replayed_cost))
    if abs(replayed_cost - claimed_cost) > slack:
        raise RuntimeError(
            f"{source} upper cost {claimed_cost} does not match replayed "
            f"action cost {replayed_cost}"
        )
    return CertifiedContract(source, tuple(action_ids), float(claimed_cost))


def anytime_dsos(
    candidates: tuple[CandidateSpace, ...],
    actions: Sequence[MeasurementAction],
    budget_s: float,
) -> AnytimeResult:
    """Anytime-DSOS under one end-to-end budget (method-freeze-v2.1).

    Phase 1 lets the width policy use the current remaining budget to obtain an
    oracle-certified contract, giving a real upper bound.  It normally returns
    early; Phase 2 then receives exactly the remaining wall-clock time.  There
    is no fixed fraction that can starve the upper-bound phase.

    `fixed` and `dual` are deliberately NOT consulted: they are independent
    baselines, and substituting a cheaper baseline contract into `U` would make
    this a combination of separately budgeted runs again.
    """

    started = time.perf_counter()
    if budget_s <= 0:
        raise ValueError("budget_s must be positive")
    contract: Optional[CertifiedContract] = None
    width, upper_seconds, upper_error = _budgeted_call(
        lambda: sequential_early_stop(
            candidates, actions, uncertainty_width_order(candidates, actions)
        ),
        budget_s,
    )
    if width is not None and width.status == "CERTIFIED":
        contract = _certified_contract(
            actions,
            status=width.status,
            action_ids=width.selected_action_ids,
            claimed_cost=width.cost,
            source="width",
        )

    remaining = budget_s - (time.perf_counter() - started)
    if remaining <= 1.0:
        return AnytimeResult(
            contract=contract,
            proof_search=None,
            upper_seconds=upper_seconds,
            lower_seconds=0.0,
            errors=(
                upper_error or "budget consumed by the upper-bound phase",
            ),
        )

    proof_search, lower_seconds, lower_error = _budgeted_call(
        lambda: synthesize_ordered_query(candidates, actions), remaining
    )
    if proof_search is not None and proof_search.status == "OPTIMAL":
        exact_contract = _certified_contract(
            actions,
            status=proof_search.status,
            action_ids=proof_search.selected_action_ids,
            claimed_cost=proof_search.exact_cost,
            source="exact",
        )
        if contract is None or exact_contract.cost <= contract.cost:
            contract = exact_contract

    return AnytimeResult(
        contract=contract,
        proof_search=proof_search,
        upper_seconds=upper_seconds,
        lower_seconds=lower_seconds,
        errors=tuple(error for error in (upper_error, lower_error) if error),
    )


def _anytime_plan_row(query_id: str, result: AnytimeResult) -> dict[str, object]:
    """Serialize the replayable contract without duplicating field logic."""

    return {
        "query_id": query_id,
        "policy": "anytime_dsos",
        "status": result.plan_validity,
        "cost": result.upper_bound if result.upper_bound is not None else "",
        "selected_count": len(result.upper_action_ids),
        "selected_action_ids": ";".join(result.upper_action_ids),
        "lower_bound": result.lower_bound if result.lower_bound is not None else "",
        "cost_optimality": result.cost_optimality,
    }


def _anytime_result_fields(result: AnytimeResult) -> dict[str, object]:
    """Serialize every v2+ endpoint from the same Anytime-DSOS result."""

    def optional(value: Optional[float]) -> object:
        return "" if value is None else value

    return {
        "certified_upper_bound": optional(result.upper_bound),
        "certified_lower_bound": optional(result.lower_bound),
        "absolute_gap": optional(result.absolute_gap),
        "relative_gap": optional(result.relative_gap),
        "approximation_ratio": optional(result.approximation_ratio),
        "interval_violation": result.interval_violation,
        "anytime_upper_source": result.upper_source,
        "anytime_upper_seconds": result.upper_seconds,
        "anytime_lower_seconds": result.lower_seconds,
        "anytime_error": result.error,
        "query_budget_s": QUERY_METHOD_TIMEOUT_S,
        "budget_is_frozen": int(_BUDGET_IS_FROZEN),
        "bound_provenance": result.bound_provenance,
        "plan_validity": result.plan_validity,
        "cost_optimality": result.cost_optimality,
    }


@dataclass(frozen=True)
class TimedResult(Generic[_T]):
    """One independently budgeted method result and its execution receipt."""

    value: Optional[_T]
    seconds: float
    error: str


@dataclass(frozen=True)
class QueryMethodResults:
    """All methods evaluated for one ordered DSE query."""

    exact: TimedResult[QueryObservationPlan]
    fixed: TimedResult[PolicyResult]
    width: TimedResult[PolicyResult]
    dual: TimedResult[PolicyResult]
    anytime: Optional[AnytimeResult]

    @property
    def errors(self) -> dict[str, str]:
        methods = (
            ("exact_dsos", self.exact),
            ("fixed_early_stop", self.fixed),
            ("uncertainty_width", self.width),
            ("dual_price", self.dual),
        )
        return {name: run.error for name, run in methods if run.error}


def _timed_call(function: Callable[[], _T]) -> TimedResult[_T]:
    """Run one query method with a fail-closed wall-clock budget."""

    def expire(_signum, _frame) -> None:
        raise TimeoutError(f"{QUERY_METHOD_TIMEOUT_S}s method budget exhausted")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, QUERY_METHOD_TIMEOUT_S)
    started = time.perf_counter()
    try:
        return TimedResult(function(), time.perf_counter() - started, "")
    except Exception as exc:
        return TimedResult(
            None,
            time.perf_counter() - started,
            f"{type(exc).__name__}: {exc}",
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _evaluate_query_methods(
    candidates: tuple[CandidateSpace, ...],
    actions: Sequence[MeasurementAction],
    fixed_order: Sequence[int],
    *,
    include_anytime: bool,
) -> QueryMethodResults:
    """Run exact, matched baselines, and Anytime-DSOS with explicit budgets."""

    exact = _timed_call(lambda: synthesize_ordered_query(candidates, actions))
    fixed = _timed_call(
        lambda: sequential_early_stop(candidates, actions, fixed_order)
    )
    width = _timed_call(
        lambda: sequential_early_stop(
            candidates,
            actions,
            uncertainty_width_order(candidates, actions),
        )
    )
    dual = _timed_call(lambda: dual_price_greedy(candidates, actions))
    anytime = (
        anytime_dsos(candidates, actions, QUERY_METHOD_TIMEOUT_S)
        if include_anytime
        else None
    )
    return QueryMethodResults(exact, fixed, width, dual, anytime)


def _ordered_outcome(
    candidates: tuple[CandidateSpace, ...], states: Iterable[str]
) -> str:
    for candidate, state in zip(candidates, states):
        if state == "SAFE":
            return candidate.candidate_id
        if state == "NUMERICAL_GAP":
            return "UNRESOLVED"
    return "NO_FEASIBLE_CANDIDATE"


def _placed_evidence(
    candidates: Iterable[CandidateSpace],
    placed_by_candidate: Mapping[str, np.ndarray],
    margin_k: float = 1e-4,
) -> dict[str, object]:
    candidates = tuple(candidates)
    model_ids = candidates[0].thermal.model_ids
    if any(candidate.thermal.model_ids != model_ids for candidate in candidates):
        raise ValueError("ordered candidates must share one thermal model registry")
    per_model_states = {model_id: [] for model_id in model_ids}
    robust_states = []
    for candidate in candidates:
        power = placed_by_candidate[candidate.candidate_id]
        thermal = candidate.thermal
        upper_peaks = []
        for model_index, model_id in enumerate(model_ids):
            peak = float(
                np.max(
                    thermal.ambient_k[model_index]
                    + thermal.response_k_per_w[model_index] @ power
                )
                + thermal.error_k[model_index]
            )
            upper_peaks.append(peak)
            per_model_states[model_id].append(
                "SAFE"
                if peak <= thermal.limit_k - margin_k
                else "REJECT"
                if peak >= thermal.limit_k + margin_k
                else "NUMERICAL_GAP"
            )
        robust_peak = max(upper_peaks)
        robust_states.append(
            "SAFE"
            if robust_peak <= thermal.limit_k - margin_k
            else "REJECT"
            if robust_peak >= thermal.limit_k + margin_k
            else "NUMERICAL_GAP"
        )
    model_outcomes = tuple(
        (model_id, _ordered_outcome(candidates, states))
        for model_id, states in per_model_states.items()
    )
    return {
        "robust_outcome": _ordered_outcome(candidates, robust_states),
        "model_outcomes": model_outcomes,
        "model_disagreement": int(len({outcome for _, outcome in model_outcomes}) > 1),
    }


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


def _replay_unsynth_witness(
    query_id: str,
    plan,
    candidates: Iterable[CandidateSpace],
    operators: Mapping[tuple[str, str], Path],
    package_id: str,
    output: Path,
) -> tuple[list[dict[str, object]], bool]:
    if plan.status != "UNSYNTHESIZABLE" or not plan.witnesses:
        return [], True
    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    rows, payload, accepted = [], {}, True
    for pair in plan.witnesses[-1].candidates:
        candidate = candidate_map[pair.candidate_id]
        family, blocks = load_family(operators[(pair.candidate_id, package_id)])
        for side, power, state, model_id in (
            ("left", pair.left_power_w, pair.left_state, pair.left_model_id),
            ("right", pair.right_power_w, pair.right_state, pair.right_model_id),
        ):
            if model_id == "UNCONSTRAINED":
                continue
            replay_models = (
                family.model_ids if model_id == "ROBUST_ENVELOPE" else (model_id,)
            )
            for replay_model in replay_models:
                model_index = family.model_ids.index(replay_model)
                work = (
                    output
                    / "work"
                    / f"operator--{pair.candidate_id}--{package_id}"
                )
                direct = replay_power(
                    HOTSPOT,
                    work / "package.config",
                    work / "floorplan.flp",
                    TEMPLATE / "example.materials",
                    replay_model,
                    blocks,
                    power,
                    output
                    / "work"
                    / "witness-replay"
                    / query_id
                    / pair.candidate_id
                    / side
                    / replay_model,
                )
                predicted = (
                    family.ambient_k[model_index]
                    + family.response_k_per_w[model_index] @ power
                )
                error = float(np.max(np.abs(direct - predicted)))
                current_pass = error <= float(family.error_k[model_index])
                accepted &= current_pass
                key = f"{pair.candidate_id}--{side}--{replay_model}"
                payload[f"{key}--direct_temperature_k"] = direct
                payload[f"{key}--predicted_temperature_k"] = predicted
                rows.append(
                    {
                        "query_id": query_id,
                        "candidate": pair.candidate_id,
                        "side": side,
                        "registered_state": state,
                        "model_role": model_id,
                        "model_id": replay_model,
                        "predicted_peak_k": float(np.max(predicted)),
                        "direct_peak_k": float(np.max(direct)),
                        "max_abs_error_k": error,
                        "registered_error_k": float(family.error_k[model_index]),
                        "replay_status": "PASS" if current_pass else "REJECT",
                    }
                )
    if payload:
        replay_path = output / "witness_replays" / f"{query_id}.npz"
        replay_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(replay_path, **payload)
    return rows, accepted


@dataclass(frozen=True)
class AnytimeGateSummary:
    """Frozen v2+ endpoints computed directly from result rows."""

    queries: int
    frozen_budget_rows: int
    certified_contracts: int
    finite_intervals: int
    false_certificates: int
    median_upper_saving: Optional[float]
    self_verifiable: int
    solver_attested: int
    bounded_gap: int

    @property
    def passes(self) -> bool:
        return (
            self.queries == 12
            and self.frozen_budget_rows == self.queries
            and self.false_certificates == 0
            and self.certified_contracts >= 10
            and self.median_upper_saving is not None
            and self.median_upper_saving >= 0.15
            and self.finite_intervals >= 6
        )


def _optional_float(row: Mapping[str, object], field: str) -> Optional[float]:
    value = row.get(field)
    return None if value in (None, "") else float(value)


def _summarize_anytime_gate(
    rows: Iterable[Mapping[str, object]],
) -> AnytimeGateSummary:
    rows = list(rows)
    certified = [
        row
        for row in rows
        if row.get("plan_validity") == "CERTIFIED"
        and _optional_float(row, "certified_upper_bound") is not None
        and not row.get("interval_violation")
    ]
    savings = []
    for row in certified:
        upper = _optional_float(row, "certified_upper_bound")
        full = _optional_float(row, "full_registry_cost")
        if upper is not None and full is not None and full > 0:
            savings.append(1.0 - upper / full)
    finite_intervals = sum(
        row.get("plan_validity") == "CERTIFIED"
        and _optional_float(row, "certified_upper_bound") is not None
        and _optional_float(row, "certified_lower_bound") is not None
        and not row.get("interval_violation")
        for row in rows
    )
    false_certificates = sum(
        bool(row.get("interval_violation"))
        or bool(int(row.get("false_certificate") or 0))
        for row in rows
    )
    optimality = [row.get("cost_optimality") for row in rows]
    return AnytimeGateSummary(
        queries=len(rows),
        frozen_budget_rows=sum(
            int(row.get("budget_is_frozen") or 0) == 1 for row in rows
        ),
        certified_contracts=len(certified),
        finite_intervals=finite_intervals,
        false_certificates=false_certificates,
        median_upper_saving=(float(np.median(savings)) if savings else None),
        self_verifiable=optimality.count("PROVEN_SELF_VERIFIABLE"),
        solver_attested=optimality.count("PROVEN_SOLVER_ATTESTED"),
        bounded_gap=optimality.count("BOUNDED_GAP"),
    )


def _write_report(
    path: Path,
    split: str,
    operators: Mapping[tuple[str, str], Path],
    results: Iterable[dict[str, object]],
    order_rows: Iterable[dict[str, object]],
    failures: Iterable[dict[str, object]],
    spectral_rows: Iterable[dict[str, object]],
) -> None:
    rows, failures, spectral_rows = (
        list(results),
        list(failures),
        list(spectral_rows),
    )
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
    model_disagreements = sum(
        int(row.get("placed_model_disagreement") or 0) for row in rows
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
    full_tail = [
        float(row["certified_peak_tail_k"])
        for row in spectral_rows
        if int(row["rank"]) == int(row["dimension"])
    ]
    anytime_gate = _summarize_anytime_gate(rows)
    protocol_state = _SPLIT_PROTOCOL_STATE.get(split, "UNREGISTERED")
    if protocol_state == "FROZEN_ACTIVE":
        anytime_verdict = "PASS" if anytime_gate.passes else "FAIL"
    else:
        anytime_verdict = f"NOT_SCORED ({protocol_state})"
    lines = [
        f"# CertiTherm {split} gate report",
        "",
        f"- Physical operators admitted: {len(operators)}",
        f"- Direct operator replays: {len(calibration_errors)}",
        f"- Certified spectral-envelope records: {len(spectral_rows)}",
        (
            f"- Maximum full-rank spectral residual: {max(full_tail):.9g} K"
            if full_tail
            else "- Maximum full-rank spectral residual: unavailable"
        ),
        f"- Exact status: {statuses}",
        f"- Internal false/contradictory certificates: {false_certificates}",
        f"- Archived placed-reference model disagreements: {model_disagreements}",
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
        "## Proof-carrying Anytime-DSOS gate",
        "",
        f"- Protocol state: {protocol_state}",
        f"- Gate verdict: {anytime_verdict}",
        (
            f"- Frozen-budget rows: "
            f"{anytime_gate.frozen_budget_rows}/{anytime_gate.queries}"
        ),
        (
            f"- Certified-contract coverage: "
            f"{anytime_gate.certified_contracts}/{anytime_gate.queries}"
        ),
        (
            f"- Finite certified intervals: "
            f"{anytime_gate.finite_intervals}/{anytime_gate.queries}"
        ),
        f"- False/contradictory certificates: {anytime_gate.false_certificates}",
        (
            f"- Median certified-U saving vs full registry: "
            f"{anytime_gate.median_upper_saving:.1%}"
            if anytime_gate.median_upper_saving is not None
            else "- Median certified-U saving vs full registry: unavailable"
        ),
        (
            "- Cost proof classes: "
            f"self-verifiable={anytime_gate.self_verifiable}, "
            f"solver-attested={anytime_gate.solver_attested}, "
            f"bounded-gap={anytime_gate.bounded_gap}"
        ),
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
        "## Query evidence",
        "",
        "| Workload | Package | Exact | Exact cost | Anytime U | Anytime L | U/L | Validity | Optimality | Fixed | Width | Dual | Full |",
        "|---|---|---|---:|---:|---:|---:|---|---|---:|---:|---:|---:|",
    ]
    numeric = lambda value: (
        "" if value in (None, "") else f"{float(value):.9g}"
    )
    for row in rows:
        lines.append(
            f"| {row['workload']} | {row['package']} | {row['exact_status']} | "
            f"{numeric(row.get('exact_cost'))} | "
            f"{numeric(row.get('certified_upper_bound'))} | "
            f"{numeric(row.get('certified_lower_bound'))} | "
            f"{numeric(row.get('approximation_ratio'))} | "
            f"{row.get('plan_validity', '')} | "
            f"{row.get('cost_optimality', '')} | "
            f"{numeric(row.get('fixed_cost'))} | "
            f"{numeric(row.get('width_cost'))} | "
            f"{numeric(row.get('dual_cost'))} | "
            f"{numeric(row.get('full_registry_cost'))} |"
        )
    lines += [
        "",
        "The exact cost is the registered finite-library non-adaptive batch "
        "optimum, not an unrestricted or continuous-adaptive sensor limit.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# Splits whose results are preregistered and must never be used for tuning.
# `heldout` is method-freeze-v1's split; `heldout_v2` is method-freeze-v2's,
# registered in experiments/architectures.tsv and disjoint from both dev and
# v1. They are listed together so a future split cannot be added to the CLI
# without also being recognised as frozen here.
_HELDOUT_SPLITS = ("heldout", "heldout_v2", "heldout_v3")
_BURNED_SPLITS = frozenset({"heldout_v2"})
_FROZEN_ONLY_SPLITS = frozenset({"heldout_v3"})
_FROZEN_ENABLED_SPLITS = frozenset({"heldout"})
_ANYTIME_SPLITS = frozenset({"dev", "heldout_v2", "heldout_v3"})
_SPLIT_PROTOCOL_STATE = {
    "dev": "DEVELOPMENT_REHEARSAL",
    "heldout": "LEGACY_V1",
    "heldout_v2": "OPENED_INVALID",
    "heldout_v3": "DEFINED_UNOPENED",
}

# Which frozen protocol each split is evidence for. Hard-coding
# "method-freeze-v1" at the row level silently mislabelled every non-v1 run as
# v1 evidence, which is an evidence-integrity defect rather than a cosmetic one:
# an artifact table is only meaningful if it names the protocol whose
# preregistered endpoints it was produced under.
_SPLIT_FREEZE_ID = {
    "dev": "method-freeze-v1",
    "heldout": "method-freeze-v1",
    "heldout_v2": "method-freeze-v2.1",
    "heldout_v3": "method-freeze-v3.0",
}


def _validate_run_request(
    split: str,
    frozen: bool,
    budget_s: Optional[float] = None,
) -> None:
    """Reject requests that cannot produce protocol-valid evidence."""

    if split not in _SPLIT_FREEZE_ID:
        raise ValueError(f"unregistered experiment split {split}")
    if not frozen:
        if split in _FROZEN_ONLY_SPLITS:
            raise ValueError(f"{split} can only run through its frozen protocol")
        return
    if split not in _HELDOUT_SPLITS:
        raise ValueError("--frozen is reserved for a held-out split")
    if split in _BURNED_SPLITS:
        raise ValueError(
            f"{split} is OPENED_INVALID / PILOT_ONLY and cannot be frozen evidence"
        )
    if split not in _FROZEN_ENABLED_SPLITS:
        raise ValueError(f"{split} is not admitted for frozen execution yet")
    actual_budget = QUERY_METHOD_TIMEOUT_S if budget_s is None else budget_s
    if (
        not np.isfinite(actual_budget)
        or abs(actual_budget - FROZEN_QUERY_BUDGET_S) >= 1e-9
    ):
        raise ValueError(
            f"frozen runs require exactly {FROZEN_QUERY_BUDGET_S:.0f}s per query; "
            f"got {actual_budget}"
        )


def _assert_clean_revision() -> None:
    """Require a committed, attribution-safe worktree before frozen evidence."""

    status = subprocess.run(
        ["git", "status", "--porcelain", "--ignore-submodules=none"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise RuntimeError(f"frozen run requires a clean revision:\n{status}")


def run(split: str, output: Path, frozen: bool) -> None:
    _validate_run_request(split, frozen)
    if frozen:
        _assert_clean_revision()
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
    operator_jobs = [
        (
            (arch["architecture_id"], package["package_id"]),
            arch,
            package,
            [
                captures[(workload["workload_id"], arch["architecture_id"])]
                for workload in workloads
            ],
        )
        for arch in architectures
        for package in packages
    ]

    def build_operator(job):
        key, arch, package, operator_captures = job
        try:
            return key, _operator(
                arch,
                package,
                operator_captures,
                output,
            ), None
        except Exception as exc:  # archive physical/timeout failures unchanged
            return key, None, exc

    with ThreadPoolExecutor(max_workers=OPERATOR_WORKERS) as pool:
        operator_results = pool.map(build_operator, operator_jobs)
        for key, path, error in operator_results:
            if error is None:
                operators[key] = path
                continue
            failures.append(
                {
                    "stage": "operator",
                    "workload": "ALL",
                    "architecture": key[0],
                    "package": key[1],
                    "failure_type": type(error).__name__,
                    "message": str(error),
                }
            )
    results, order_rows, registry_rows, spectral_rows = [], [], [], []
    spectra = {}
    plan_rows, witness_rows, witness_replay_rows = [], [], []
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
                        "freeze_id": _SPLIT_FREEZE_ID[split],
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
                spectrum_key = candidate_id, package["package_id"]
                spectrum = spectra.get(spectrum_key)
                if spectrum is None:
                    spectrum = thermal_spectrum(family)
                    spectra[spectrum_key] = spectrum
                for rank in audit_ranks(power.dimension):
                    tail = certified_tail_bound_k(power, family, spectrum, rank)
                    spectral_rows.append(
                        {
                            "split": split,
                            "workload": workload["workload_id"],
                            "package": package["package_id"],
                            "candidate": candidate_id,
                            "dimension": power.dimension,
                            "rank": rank,
                            "retained_operator_energy": spectrum.retained_energy(rank),
                            "certified_peak_tail_k": tail,
                        }
                    )
                    if rank == power.dimension and tail > 1e-7:
                        raise RuntimeError("full-rank spectral envelope is not exact")
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
                            "thermal_spectral_leverage": channel_spectral_leverage(
                                action, spectrum
                            ),
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
            methods = _evaluate_query_methods(
                candidates,
                actions,
                fixed_order,
                include_anytime=split in _ANYTIME_SPLITS,
            )
            exact = methods.exact.value
            fixed = methods.fixed.value
            width = methods.width.value
            dual = methods.dual.value
            anytime = methods.anytime
            method_errors = methods.errors
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
            exact_status = exact.status if exact else "UNRESOLVED"
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
                replay_rows, replay_pass = _replay_unsynth_witness(
                    query_id,
                    exact,
                    candidates,
                    operators,
                    package["package_id"],
                    output,
                )
                witness_replay_rows.extend(replay_rows)
                witness_rows[-1]["physical_replay_status"] = (
                    "PASS" if replay_pass else "REJECT"
                )
                if not replay_pass:
                    exact_status = "UNRESOLVED"
                    error = "witness direct replay violates frozen error contract"
                    method_errors["exact_dsos_replay"] = error
                    failures.append(
                        {
                            "stage": "exact_dsos_replay",
                            "workload": workload["workload_id"],
                            "architecture": "ORDERED_SET",
                            "package": package["package_id"],
                            "failure_type": "ErrorContractViolation",
                            "message": error,
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
                        "status": (
                            exact_status
                            if policy_name == "exact_dsos"
                            else policy.status
                        ),
                        "cost": (
                            policy.exact_cost
                            if policy_name == "exact_dsos"
                            else policy.cost
                        ),
                        "selected_count": len(selected),
                        "selected_action_ids": ";".join(selected),
                    }
                )
            placed = _placed_evidence(candidates, placed_by_candidate)

            if anytime is not None:
                plan_rows.append(_anytime_plan_row(query_id, anytime))

            results.append(
                {
                    "freeze_id": _SPLIT_FREEZE_ID[split],
                    "split": split,
                    "workload": workload["workload_id"],
                    "package": package["package_id"],
                    "objective": "EDYP_ASCENDING",
                    "candidate_order": ";".join(
                        candidate.candidate_id for candidate in candidates
                    ),
                    "exact_status": exact_status,
                    "exact_cost": exact.exact_cost if exact else "",
                    "milp_lower_bound": exact.lower_bound if exact else "",
                    "lp_relaxation_bound": (
                        exact.relaxation_bound if exact else ""
                    ),
                    "optimality_gap": exact.optimality_gap if exact else "",
                    # v1 does not silently acquire the later Anytime method.
                    **(
                        _anytime_result_fields(anytime)
                        if anytime is not None
                        else {}
                    ),
                    "fixed_status": fixed.status if fixed else "UNRESOLVED",
                    "fixed_cost": fixed.cost if fixed else "",
                    "width_status": width.status if width else "UNRESOLVED",
                    "width_cost": width.cost if width else "",
                    "dual_status": dual.status if dual else "UNRESOLVED",
                    "dual_cost": dual.cost if dual else "",
                    "exact_seconds": methods.exact.seconds,
                    "fixed_seconds": methods.fixed.seconds,
                    "width_seconds": methods.width.seconds,
                    "dual_seconds": methods.dual.seconds,
                    "full_registry_cost": sum(action.cost for action in actions),
                    "witnesses": len(exact.witnesses) if exact else 0,
                    "placed_robust_outcome": placed["robust_outcome"],
                    "placed_model_outcomes": ";".join(
                        f"{model}={outcome}"
                        for model, outcome in placed["model_outcomes"]
                    ),
                    "placed_model_disagreement": placed["model_disagreement"],
                    "false_certificate": (
                        int(bool(anytime.interval_violation))
                        if anytime is not None
                        else 0
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
    if spectral_rows:
        _write_tsv(output / "spectral_envelopes.tsv", spectral_rows)
    if plan_rows:
        _write_tsv(output / "plans.tsv", plan_rows)
    if witness_rows:
        _write_tsv(output / "witnesses.tsv", witness_rows)
    if witness_replay_rows:
        _write_tsv(output / "witness_replays.tsv", witness_replay_rows)
    if failures:
        _write_tsv(output / "FAILURES.tsv", failures)
    _write_report(
        output / "REPORT.md",
        split,
        operators,
        results,
        order_rows,
        failures,
        spectral_rows,
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
                            "witness_replays.tsv",
                            "spectral_envelopes.tsv",
                        }
                        or "witnesses" in path.parts
                        or "witness_replays" in path.parts
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
    parser.add_argument(
        "--split", choices=("dev",) + _HELDOUT_SPLITS, required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frozen", action="store_true")
    args = parser.parse_args()
    run(args.split, args.output, args.frozen)


if __name__ == "__main__":
    main()
