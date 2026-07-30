"""Frozen ThermoDSE/HotSpot experiment driver with resumable NPZ evidence."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
from dataclasses import dataclass
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
from .solver_budget import budget_scope
from .synthesis import synthesize_ordered_query
from . import cache_receipts as _cache_receipts
from . import query_evidence as _query_evidence
from .budget_guard import call_under_budget as _call_under_budget
from .cache_receipts import CACHE_RECEIPT_SCHEMA, canonical_sha256 as _canonical_sha256
from .digest import sha256_file as _sha256
from .paths import HOTSPOT, ROOT, SUBMODULE_PATHS, TEMPLATE, THERMODSE
from .query_evidence import (
    PreparedQuery,
    QueryEvidence,
    QueryMethodResults,
    TimedResult,
    anytime_plan_row as _anytime_plan_row,
    failed_query_methods as _failed_query_methods,
    ordered_outcome as _ordered_outcome,
    placed_evidence as _placed_evidence,
    replay_unsynth_witness as _replay_unsynth_witness,
    save_unsynth_witness as _save_unsynth_witness,
    unexpected_method_failures as _unexpected_method_failures,
)
from .result_schema import (
    ANYTIME_RESULT_FIELDS as _ANYTIME_RESULT_FIELDS,
    AnytimeResult,
    BASE_RESULT_FIELDS as _BASE_RESULT_FIELDS,
    BUDGET_IS_FROZEN as _BUDGET_IS_FROZEN,
    CertifiedContract,
    DIAGNOSTIC_RESULT_FIELDS as _DIAGNOSTIC_RESULT_FIELDS,
    FROZEN_QUERY_BUDGET_S,
    POLICY_RESULT_FIELDS as _POLICY_RESULT_FIELDS,
    QUERY_METHOD_TIMEOUT_S,
    RESULT_SCHEMA_VERSION,
    anytime_result_fields as _anytime_result_fields,
    diagnostic_result_fields as _diagnostic_result_fields,
    optional_seconds as _optional_seconds,
    result_fieldnames as _result_fieldnames,
)
from .thermodse_bridge import (
    build_thermodse_evaluator as _thermodse_evaluator,
    capture_thermodse_power as _bridge_capture,
    design_vector as _architecture,
    hotspot_disabled as _hotspot_disabled,
    install_compatibility_layer as _install_thermodse_compatibility,
    load_capture_metrics as _capture_metrics,
    prepare_simulation_dir as _prepare_thermodse_sim,
    write_hotspot_config as _configure,
)
from .frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K
from .split_protocol import (
    ANYTIME_SPLITS as _ANYTIME_SPLITS,
    BURNED_SPLITS as _BURNED_SPLITS,
    DEVELOPMENT_SPLITS as _DEVELOPMENT_SPLITS,
    FREEZE_ID as _SPLIT_FREEZE_ID,
    FROZEN_ENABLED_SPLITS as _FROZEN_ENABLED_SPLITS,
    FROZEN_ONLY_SPLITS as _FROZEN_ONLY_SPLITS,
    HELDOUT_SPLITS as _HELDOUT_SPLITS,
    PROTOCOL_STATE as _SPLIT_PROTOCOL_STATE,
    registry_split as _registry_split,
)
from .run_report import (
    AnytimeGateSummary,
    summarize_anytime_gate as _summarize_anytime_gate,
    write_run_report as _write_report,
)
from .tabular import read_rows as _rows, write_rows as _write_tsv


GPU_HOTSPOT_BUILD = ROOT / ".build" / "hotspot-gpu-export"
GPU_HOTSPOT_EXPORTER = GPU_HOTSPOT_BUILD / "hotspot"
GPU_HOTSPOT_SOLVER = ROOT / ".build" / "hotspot-cuda" / "certitherm_hotspot_cuda"
MODELS = ("block", "grid64-avg", "grid128-avg")
RESULT_ARTIFACT_NAMES = frozenset(
    {
        "results.tsv",
        "plans.tsv",
        "REPORT.md",
        "witnesses.tsv",
        "witness_replays.tsv",
        "spectral_envelopes.tsv",
    }
)
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
QUERY_WORKERS = int(os.environ.get("CERTITHERM_QUERY_WORKERS", "3"))
if QUERY_WORKERS < 1:
    raise RuntimeError("CERTITHERM_QUERY_WORKERS must be a positive integer")
METHOD_WORKERS = int(os.environ.get("CERTITHERM_METHOD_WORKERS", "0"))
if METHOD_WORKERS < 0:
    raise RuntimeError("CERTITHERM_METHOD_WORKERS must be non-negative")
FROZEN_V3_QUERY_WORKERS = 3
FROZEN_V3_METHOD_WORKERS = 15
FROZEN_NUMERIC_THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
)
FROZEN_V3_ENVIRONMENT = {
    **{name: "1" for name in FROZEN_NUMERIC_THREAD_VARIABLES},
    "CERTITHERM_LP_WORKERS": "1",
    "CERTITHERM_METHOD_WORKERS": "15",
    "CERTITHERM_GPU_HOTSPOT": "1",
    "CERTITHERM_GPU_DEVICE": "0",
    "CUDA_VISIBLE_DEVICES": "0",
}
_T = TypeVar("_T")


class NonthermalCandidateInvalid(RuntimeError):
    """A candidate completed evaluation but produced inadmissible metrics."""


def _is_archivable_operator_failure(error: BaseException) -> bool:
    """Separate physical/infrastructure failures from programming defects.

    A model disagreement, process failure, missing file, or timeout remains a
    row in the evidence bundle. Errors such as ``NameError``, ``TypeError``,
    ``KeyError``, and invalid-array ``ValueError`` stay loud: treating those as
    a scientific ``UNRESOLVED`` result could let broken code satisfy a partial
    coverage gate.
    """

    return isinstance(
        error,
        (OSError, RuntimeError, subprocess.SubprocessError),
    )


@dataclass(frozen=True)
class GpuSelection:
    """One reading of the GPU configuration, shared by the cache identity and the build.

    `CERTITHERM_GPU_HOTSPOT` was read at four independent points and `CERTITHERM_GPU_DEVICE` at
    three, so the operator cache signature and the backend that actually built the operator each
    consulted the environment separately. Nothing tied the two readings together: a signature could
    describe a CPU build while the operator was produced on the GPU, or the reverse, and the receipt
    would look entirely consistent. That is the false-hit direction -- results internally coherent
    but attributed to the wrong operator.

    Peer review named the hazard; the five call sites were what made it concrete. One snapshot per
    run is the fix, and `enabled`/`device` must be read from HERE by both consumers.
    """

    enabled: bool
    device: int

    @classmethod
    def from_environment(cls) -> "GpuSelection":
        return cls(
            enabled=os.environ.get("CERTITHERM_GPU_HOTSPOT", "0") == "1",
            device=int(os.environ.get("CERTITHERM_GPU_DEVICE", "0")),
        )


def _gpu_backend(selection: GpuSelection) -> Optional[GpuHotSpotBackend]:
    """Build the GPU backend for a given selection, or None when it is disabled.

    `selection` is REQUIRED. It defaulted to a fresh environment read so existing callers kept
    working, and peer review was right that an ambient fallback inside a core helper is a liability:
    it is precisely how the identity and the build came to disagree in the first place, and a default
    lets a future caller reintroduce that without writing anything that looks wrong.
    """

    if not selection.enabled:
        return None
    receipt = GPU_HOTSPOT_BUILD / "GPU_SHA256SUMS"
    _verified_binary_digest(GPU_HOTSPOT_EXPORTER, receipt)
    _verified_binary_digest(GPU_HOTSPOT_SOLVER, receipt)
    return GpuHotSpotBackend(
        GPU_HOTSPOT_EXPORTER,
        GPU_HOTSPOT_SOLVER,
        device=selection.device,
    )



# --- cache receipts -------------------------------------------------------
# The implementations live in `cache_receipts`; these wrappers exist to keep the injection seam
# resolving HERE. Tests replace `experiments._sha256`, and Python resolves a function's globals in
# the module where it was DEFINED -- so a plain re-export would have left those patches with no
# effect on the moved code, silently. Peer review named this as the reason to wrap rather than
# alias. `_canonical_sha256` needs no wrapper: it injects nothing.


def _source_bundle_sha256(relative_paths: Sequence[str]) -> str:
    return _cache_receipts.source_bundle_sha256(
        relative_paths, root=ROOT, sha256_file=_sha256
    )


def _cache_receipt_path(artifact: Path) -> Path:
    return _cache_receipts.receipt_path(artifact)


def _write_cache_receipt(
    artifact: Path,
    signature: Mapping[str, str],
    related: Optional[Mapping[str, Path]] = None,
) -> None:
    _cache_receipts.write_receipt(artifact, signature, related, sha256_file=_sha256)


def _cache_receipt_matches(
    artifact: Path,
    signature: Mapping[str, str],
    related: Optional[Mapping[str, Path]] = None,
) -> bool:
    return _cache_receipts.receipt_matches(
        artifact, signature, related, sha256_file=_sha256
    )



def _capture(
    arch: dict[str, str],
    workload: dict[str, str],
    package: dict[str, str],
    output: Path,
) -> Path:
    """Compute this capture's cache identity here, then hand the work to the bridge.

    A wrapper rather than a re-export: it resolves `_sha256` in THIS module, so the existing
    `monkeypatch.setattr(experiments, "_sha256", ...)` still reaches the moved implementation.
    Eleven research probes call this four-argument form, which is why the shape is unchanged.
    """

    return _bridge_capture(
        arch,
        workload,
        package,
        output,
        signature=_capture_cache_signature(arch, workload, package),
        sha256_file=_sha256,
    )



def _archive_query_evidence(query, methods, *, split, operators, output):
    """Hand the driver's own runtime resources to the evidence writer.

    A wrapper, not a re-export: the HotSpot binary, the template directory and the effective query
    budget are the driver's to decide, and the row must record the budget the driver validated
    rather than whatever the environment said at import. One test calls this five-argument form.
    """

    return _query_evidence.archive_query_evidence(
        query,
        methods,
        split=split,
        operators=operators,
        output=output,
        hotspot_binary=HOTSPOT,
        template_dir=TEMPLATE,
        query_budget_s=QUERY_METHOD_TIMEOUT_S,
        budget_is_frozen=_BUDGET_IS_FROZEN,
    )


def _capture_cache_signature(
    arch: Mapping[str, str],
    workload: Mapping[str, str],
    package: Mapping[str, str],
) -> dict[str, str]:
    inputs = {
        "architecture": dict(arch),
        "workload": dict(workload),
        "package": dict(package),
        "thermodse_sha": _git_revision(THERMODSE),
    }
    return {
        "kind": "thermodse-capture",
        # digest.py is in the bundle because the receipt logic EXECUTES it: the builder
        # digest, the cached-file digests and the validation all go through
        # digest.sha256_file. Omitting it would let a change to how this repository hashes
        # leave builder_sha256 untouched, and a cache written under the old rule would be
        # accepted under the new one.
        "builder_sha256": _source_bundle_sha256(
            (
                "CertiTherm/digest.py",
                "CertiTherm/experiments.py",
                # tabular.py for the same reason as digest.py: the receipt is WRITTEN and
                # VALIDATED through it, so a change to the column rule would let a cache written
                # under the old rule pass validation under the new one. Peer review caught this
                # after the writer moved out of this file -- the bundle still named only the
                # module the logic used to live in.
                "CertiTherm/cache_receipts.py",
                # The capture's CONTENT is produced by the bridge, and the paths it reads the
                # ThermoDSE tree and the HotSpot template from live in paths.py. Both are
                # behaviour-bearing for this artifact, so a change there must move this digest --
                # the same omission peer review found when the TSV writer moved out.
                "CertiTherm/paths.py",
                "CertiTherm/tabular.py",
                "CertiTherm/thermodse_bridge.py",
                # run.sh execs trace_runner.py, so the capture's power map is produced by it.
                # Peer review found this still missing after the bridge moved: a changed
                # trace-alignment rule would have left builder_sha256 fixed.
                "CertiTherm/trace_runner.py",
                "requirements.lock",
            )
        ),
        "input_sha256": _canonical_sha256(inputs),
    }


def _operator_cache_signature(
    arch: Mapping[str, str],
    package: Mapping[str, str],
    captures: Sequence[Path],
    gpu: GpuSelection,
) -> dict[str, str]:
    # The SAME snapshot the backend is built from. Required, not defaulted: reading the environment
    # here is exactly what allowed the identity and the build to disagree.
    gpu_enabled = gpu.enabled
    inputs: dict[str, object] = {
        "architecture": dict(arch),
        "package": dict(package),
        "captures": {path.name: _sha256(path) for path in captures},
        "hotspot_sha": _git_revision(ROOT / "HotSpot"),
        "hotspot_binary_sha256": _verified_binary_digest(
            HOTSPOT,
            HOTSPOT.parent / "SHA256SUMS",
        ),
        "materials_sha256": _sha256(TEMPLATE / "example.materials"),
        "config_template_sha256": _sha256(TEMPLATE / "example.config"),
        "models": MODELS,
        "thermal_limit_k": THERMAL_LIMIT_K,
        "error_limit_k": MODEL_ERROR_LIMIT_K,
        "calibration_vectors": CALIBRATION_VECTOR_IDS,
        "gpu_enabled": gpu_enabled,
    }
    if gpu_enabled:
        gpu_receipt = GPU_HOTSPOT_BUILD / "GPU_SHA256SUMS"
        inputs.update(
            {
                "gpu_exporter_sha256": _verified_binary_digest(
                    GPU_HOTSPOT_EXPORTER,
                    gpu_receipt,
                ),
                "gpu_solver_sha256": _verified_binary_digest(
                    GPU_HOTSPOT_SOLVER,
                    gpu_receipt,
                ),
                "gpu_device": gpu.device,
            }
        )
    return {
        "kind": "hotspot-operator",
        "builder_sha256": _source_bundle_sha256(
            (
                "CertiTherm/core.py",
                # See _capture_cache_signature: the hashing this receipt is built from
                # lives here, so it has to be part of what the receipt is bound to.
                "CertiTherm/digest.py",
                "CertiTherm/experiments.py",
                "CertiTherm/gpu_hotspot.py",
                "CertiTherm/hotspot.py",
                "CertiTherm/measurements.py",
                # See _capture_cache_signature: the receipt is written and validated through
                # cache_receipts over tabular, and paths.py decides WHICH HotSpot binary and
                # template the inputs above are read from.
                "CertiTherm/cache_receipts.py",
                "CertiTherm/paths.py",
                "CertiTherm/tabular.py",
                "requirements.lock",
            )
        ),
        "input_sha256": _canonical_sha256(inputs),
    }


def _git_revision(path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _verified_binary_digest(binary: Path, receipt: Path) -> str:
    """Return a binary digest only when its bootstrap receipt still matches."""

    if not binary.is_file() or not receipt.is_file():
        raise RuntimeError("HotSpot build or bootstrap digest receipt is missing")
    entries = []
    for line in receipt.read_text(encoding="utf-8").splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) == 2 and Path(fields[1].lstrip("*")).name == binary.name:
            entries.append(fields[0])
    if len(entries) != 1:
        raise RuntimeError(
            "HotSpot bootstrap receipt does not identify the binary uniquely"
        )
    actual = _sha256(binary)
    if entries[0] != actual:
        raise RuntimeError("HotSpot binary no longer matches its bootstrap receipt")
    return actual






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
    *,
    gpu: GpuSelection,
) -> Path:
    target = output / "operators" / f"{arch['architecture_id']}--{package['package_id']}.npz"
    captures = tuple(captures)
    calibration_path = target.with_suffix(".calibration.tsv")
    # ONE reading of the GPU configuration for this operator: the cache identity below and the
    # backend that builds it further down must not consult the environment separately, or a
    # signature can describe a CPU build while a GPU produced the operator.
    signature = _operator_cache_signature(arch, package, captures, gpu)
    expected_rows = len(captures) * (2 + len(CALIBRATION_SEEDS)) * len(MODELS)
    if _cache_receipt_matches(
        target,
        signature,
        {"calibration": calibration_path},
    ):
        cached = _rows(calibration_path)
        if len(cached) == expected_rows and {
            row["vector_id"] for row in cached
        } == set(CALIBRATION_VECTOR_IDS):
            return target
    target.unlink(missing_ok=True)
    calibration_path.unlink(missing_ok=True)
    _cache_receipt_path(target).unlink(missing_ok=True)
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
        gpu_backend=_gpu_backend(gpu),
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
    _write_cache_receipt(
        target,
        signature,
        {"calibration": calibration_path},
    )
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


# Bumped whenever the result-table contract changes shape. Explicit, because
# adding or removing a column silently changes what a downstream reader can
# assume -- and one column here (`milp_lower_bound`) already carries a name
# that misdescribes its contents for compatibility reasons.
#   1 -> pre-diagnostics (method-freeze-v1 through v3.1 rehearsals)
#   2 -> adds separation diagnostics and explicit bound provenance

# Separation diagnostics. These answer "why is the lower bound small?", which
# the endpoint columns alone cannot: a small `certified_lower_bound` is
# ambiguous between few expensive rounds, a saturating dual, and a candidate
# schedule that never reached most of its subproblems. They are observational
# only -- no status, bound, or gate condition reads them.




def _measurement_costs() -> dict[str, float]:
    rows = _rows(ROOT / "experiments" / "measurements.tsv")
    return {row["action_class"]: float(row["cost"]) for row in rows}




def _budgeted_call(
    function: Callable[[], _T], budget_s: float
) -> tuple[Optional[_T], float, str]:
    """Run one phase under an explicit share of an end-to-end budget."""

    return _call_under_budget(
        function,
        budget_s,
        f"{budget_s:.0f}s budget exhausted",
    )






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
    # `NaN <= 0` is False, so the positivity test alone let a NaN budget through to
    # `_budgeted_call`, whose own `remaining <= 1.0` also passes it. Timeout and certification
    # behaviour then become undefined. Peer review found this one; it is the fourth instance of the
    # same comparison-based hole in this package.
    if not math.isfinite(budget_s) or budget_s <= 0:
        raise ValueError(f"budget_s must be finite and positive, got {budget_s}")
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
















def _timed_call(function: Callable[[], _T]) -> TimedResult[_T]:
    """Run one query method with a fail-closed wall-clock budget."""

    value, seconds, error = _call_under_budget(
        function,
        QUERY_METHOD_TIMEOUT_S,
        f"{QUERY_METHOD_TIMEOUT_S}s method budget exhausted",
    )
    return TimedResult(value, seconds, error)


def _run_query_method(
    candidates: Sequence[CandidateSpace],
    actions: Sequence[MeasurementAction],
    fixed_order: Sequence[int],
    method: str,
):
    """The single definition of how each query method is invoked.

    Both evaluation paths route through here: the batch path, which runs all five for one
    query, and the per-method path, which runs one. They previously each spelled out all
    five invocations, so a change to how a method is called had to be made twice and
    nothing checked that it was.

    Only `anytime` is unbudgeted here -- `anytime_dsos` owns one end-to-end budget and
    subdivides it internally, so wrapping it in `_timed_call` would impose a second.
    """

    if method == "anytime":
        return anytime_dsos(candidates, actions, QUERY_METHOD_TIMEOUT_S)
    if method == "width":
        return _timed_call(
            lambda: sequential_early_stop(
                candidates,
                actions,
                uncertainty_width_order(candidates, actions),
            )
        )
    if method == "dual":
        return _timed_call(lambda: dual_price_greedy(candidates, actions))
    if method == "fixed":
        return _timed_call(
            lambda: sequential_early_stop(candidates, actions, fixed_order)
        )
    if method == "exact":
        return _timed_call(lambda: synthesize_ordered_query(candidates, actions))
    raise ValueError(f"unknown query method: {method}")


def _evaluate_query_methods(
    candidates: tuple[CandidateSpace, ...],
    actions: Sequence[MeasurementAction],
    fixed_order: Sequence[int],
    *,
    include_anytime: bool,
) -> QueryMethodResults:
    """Run exact, matched baselines, and Anytime-DSOS with explicit budgets.

    Evaluation order is exact -> fixed -> width -> dual -> anytime. It is NOT because the
    five share a deadline -- each `_timed_call` opens a fresh full `QUERY_METHOD_TIMEOUT_S`
    and `anytime_dsos` owns a separate end-to-end budget, and no outer budget is installed
    by `_evaluate_prepared_query`. What the order does bind is process-global state that
    accumulates across the five (solver caches, kernel-oracle counters) and the machine
    load each leaves behind, so it is fixed for reproducibility rather than for correctness.
    """

    def run(method: str):
        return _run_query_method(candidates, actions, fixed_order, method)

    exact = run("exact")
    fixed = run("fixed")
    width = run("width")
    dual = run("dual")
    anytime = run("anytime") if include_anytime else None
    return QueryMethodResults(exact, fixed, width, dual, anytime)


def _evaluate_prepared_query(
    job: tuple[PreparedQuery, bool],
) -> QueryMethodResults:
    """Process-pool entry point; one worker owns one query and its timers."""

    query, include_anytime = job
    return _evaluate_query_methods(
        query.candidates,
        query.actions,
        query.fixed_order,
        include_anytime=include_anytime,
    )


_METHOD_PRIORITY = ("anytime", "width", "dual", "fixed", "exact")


def _method_schedule(
    query_count: int, include_anytime: bool
) -> tuple[tuple[int, str], ...]:
    """Flatten query methods in the frozen upper-bound-first priority order."""

    methods = _METHOD_PRIORITY if include_anytime else _METHOD_PRIORITY[1:]
    return tuple(
        (query_index, method)
        for method in methods
        for query_index in range(query_count)
    )


def _evaluate_prepared_method(
    job: tuple[PreparedQuery, str],
):
    """Process-pool entry point for one independently budgeted method."""

    query, method = job
    started = time.perf_counter()
    try:
        return _dispatch_prepared_method(query, method)
    except Exception as exc:
        # `_call_under_budget` is supposed to convert every ordinary exception
        # into a returned tuple, so reaching here is a containment failure and
        # stays labelled as one -- it must NOT be relabelled as an ordinary
        # timeout, which would erase the distinction the gate depends on. What
        # is preserved is the child-side elapsed time: the parent cannot
        # measure it (futures are consumed in schedule order, so parent timing
        # includes queueing), and fabricating 0.0 put a false number into the
        # evidence table.
        elapsed = time.perf_counter() - started
        error = f"method containment failure: {type(exc).__name__}: {exc}"
        if method == "anytime":
            return AnytimeResult(None, None, None, None, errors=(error,))
        return TimedResult(None, elapsed, error)


def _dispatch_prepared_method(query: PreparedQuery, method: str):
    """Run one method for one prepared query. Every branch is independently budgeted.

    Kept as a two-argument function taking the whole `PreparedQuery` because it is the
    seam the containment tests substitute; the invocation itself lives in
    `_run_query_method`, which the batch path shares.
    """

    return _run_query_method(
        query.candidates, query.actions, query.fixed_order, method
    )






def _evaluate_query_batch(
    queries: Sequence[PreparedQuery],
    *,
    include_anytime: bool,
    workers: int,
    method_workers: int,
) -> tuple[QueryMethodResults, ...]:
    """Evaluate independent queries in one persistent process pool.

    Both worker counts are REQUIRED. They defaulted to `QUERY_WORKERS` and `METHOD_WORKERS`, which
    a default argument evaluates once at DEFINITION time -- so `monkeypatch.setattr(experiments,
    "METHOD_WORKERS", ...)` changed what the run receipt recorded while execution kept using the
    value frozen into the signature. `run` supplied `workers` explicitly but not `method_workers`,
    so that mismatch was one patch away from being real. Peer review found it.

    `method_workers` is a scheduler SELECTOR, not merely a count: zero -- its own default -- keeps
    the query-level path below, and any nonzero value routes the whole batch through
    `_evaluate_method_batch` instead. Passing a plausible-looking 1 or 2 silently changes which
    scheduler runs, which is worth knowing before treating it as a tuning knob.

    The old failed parallel path built a spawn-context pool inside every
    separation iteration. Here the pool is created exactly once for the whole
    experiment and each task runs a complete query. Futures are consumed in
    registry order, so scheduling cannot reorder evidence rows. A worker or
    pool failure becomes an explicit unresolved row; KeyboardInterrupt and
    other BaseException control flow still propagate.
    """

    if workers < 1:
        raise ValueError("query workers must be positive")
    if method_workers < 0:
        raise ValueError("method workers must be non-negative")
    if not queries:
        return ()
    if method_workers:
        return _evaluate_method_batch(
            queries,
            include_anytime=include_anytime,
            workers=method_workers,
        )
    jobs = tuple((query, include_anytime) for query in queries)
    if workers == 1:
        return tuple(_evaluate_prepared_query(job) for job in jobs)
    context = multiprocessing.get_context("spawn")
    try:
        with ProcessPoolExecutor(
            max_workers=min(workers, len(jobs)),
            mp_context=context,
        ) as pool:
            futures = [pool.submit(_evaluate_prepared_query, job) for job in jobs]
            results = []
            for future in futures:
                try:
                    results.append(future.result())
                except Exception as exc:
                    error = f"query worker failure: {type(exc).__name__}: {exc}"
                    results.append(
                        _failed_query_methods(
                            error,
                            include_anytime=include_anytime,
                        )
                    )
            return tuple(results)
    except Exception as exc:
        error = f"query pool failure: {type(exc).__name__}: {exc}"
        return tuple(
            _failed_query_methods(error, include_anytime=include_anytime)
            for _query in queries
        )


def _evaluate_method_batch(
    queries: Sequence[PreparedQuery],
    *,
    include_anytime: bool,
    workers: int,
) -> tuple[QueryMethodResults, ...]:
    """Evaluate methods as independent tasks in one persistent spawn pool."""

    if workers < 1:
        raise ValueError("method workers must be positive")
    schedule = _method_schedule(len(queries), include_anytime)
    slots: list[dict[str, object]] = [dict() for _query in queries]
    context = multiprocessing.get_context("spawn")
    try:
        with ProcessPoolExecutor(
            max_workers=min(workers, len(schedule)),
            mp_context=context,
        ) as pool:
            futures = [
                pool.submit(_evaluate_prepared_method, (queries[index], method))
                for index, method in schedule
            ]
            for (index, method), future in zip(schedule, futures):
                try:
                    slots[index][method] = future.result()
                except Exception as exc:
                    # The worker died without reporting -- process kill, pickling
                    # failure, pool breakage. Its elapsed time is genuinely
                    # unknown here, so it is recorded as missing rather than as
                    # a fabricated 0.0. Parent-side timing would be wrong too:
                    # futures are consumed in schedule order, so it would
                    # include queueing and waiting on earlier futures.
                    error = f"method worker failure: {type(exc).__name__}: {exc}"
                    slots[index][method] = (
                        AnytimeResult(None, None, None, None, errors=(error,))
                        if method == "anytime"
                        else TimedResult(None, None, error)
                    )
    except Exception as exc:
        error = f"method pool failure: {type(exc).__name__}: {exc}"
        return tuple(
            _failed_query_methods(error, include_anytime=include_anytime)
            for _query in queries
        )

    results = []
    for slot in slots:
        missing = [
            method
            for method in _METHOD_PRIORITY
            if method != "anytime" or include_anytime
            if method not in slot
        ]
        if missing:
            results.append(
                _failed_query_methods(
                    f"method pool omitted: {','.join(missing)}",
                    include_anytime=include_anytime,
                )
            )
            continue
        results.append(
            QueryMethodResults(
                exact=slot["exact"],
                fixed=slot["fixed"],
                width=slot["width"],
                dual=slot["dual"],
                anytime=slot.get("anytime"),
            )
        )
    return tuple(results)






















def _query_worker_count(split: str) -> int:
    """Keep legacy v1 serial while v3 uses its preregistered scheduler."""

    return 1 if split == "heldout" else QUERY_WORKERS


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
    if split == "heldout_v3" and QUERY_WORKERS != FROZEN_V3_QUERY_WORKERS:
        raise ValueError(
            f"heldout_v3 requires exactly {FROZEN_V3_QUERY_WORKERS} query workers; "
            f"got {QUERY_WORKERS}"
        )
    if split == "heldout_v3" and METHOD_WORKERS != FROZEN_V3_METHOD_WORKERS:
        raise ValueError(
            f"heldout_v3 requires exactly {FROZEN_V3_METHOD_WORKERS} method "
            f"workers; got {METHOD_WORKERS}"
        )
    if split == "heldout_v3":
        # ONE reading per variable. The comprehension read each twice -- once to compare and once to
        # report -- so a value that changed between the two reads produced a diagnostic naming a
        # value that had never failed the comparison, or omitted a variable that had. Peer review
        # raised it. The snapshot is also what a caller would need in order to record the
        # environment it actually validated.
        observed = {
            name: os.environ.get(name, "<unset>") for name in FROZEN_V3_ENVIRONMENT
        }
        invalid_environment = {
            name: observed[name]
            for name, expected in FROZEN_V3_ENVIRONMENT.items()
            if observed[name] != expected
        }
        if invalid_environment:
            raise ValueError(
                "heldout_v3 requires its frozen execution environment; "
                f"got {invalid_environment}"
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


def _canonical_producer(split: str, frozen: bool) -> str:
    command = (
        f"python -m CertiTherm.experiments --split {split} "
        "--output <artifact-root>"
    )
    return command + (" --frozen" if frozen else "")


def _artifact_role(path: Path) -> str:
    if path.name == "RUN_RECEIPT.tsv":
        return "receipt"
    if (
        path.name in RESULT_ARTIFACT_NAMES
        or "witnesses" in path.parts
        or "witness_replays" in path.parts
    ):
        return "result"
    return "scientific_input"


def _run_receipt(
    split: str,
    frozen: bool,
    started_at: datetime,
    hotspot_digest: str,
    gpu: GpuSelection,
    git_sha: str,
    completed_at: datetime,
) -> dict[str, object]:
    """Build one complete, path-private provenance row for an artifact.

    `gpu` is the run's single snapshot. This function used to read
    `CERTITHERM_GPU_HOTSPOT` twice and `CERTITHERM_GPU_DEVICE` once on its own, so the receipt
    described a configuration read at receipt-writing time rather than the one every operator was
    built under -- and its two readings of the same variable were not even tied to each other.
    Environment variables do not change inside a process, so this was never reachable by accident;
    the point is that nothing enforced it. The default keeps existing test callers working.
    """


    registries = {
        name: _sha256(ROOT / "experiments" / f"{name}.tsv")
        for name in ("architectures", "workloads", "packages", "measurements")
    }
    submodules = {
        f"{name.lower()}_sha": _git_revision(ROOT / name)
        for name in SUBMODULE_PATHS
    }
    query_workers = _query_worker_count(split)
    method_workers = METHOD_WORKERS
    numeric_threads = {
        name.lower(): os.environ.get(name, "")
        for name in FROZEN_NUMERIC_THREAD_VARIABLES
    }
    gpu_digests = {}
    if gpu.enabled:
        gpu_receipt = GPU_HOTSPOT_BUILD / "GPU_SHA256SUMS"
        gpu_digests = {
            "gpu_exporter_sha256": _verified_binary_digest(
                GPU_HOTSPOT_EXPORTER,
                gpu_receipt,
            ),
            "gpu_solver_sha256": _verified_binary_digest(
                GPU_HOTSPOT_SOLVER,
                gpu_receipt,
            ),
            "gpu_device": str(gpu.device),
            "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES", ""),
        }
    return {
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "freeze_id": _SPLIT_FREEZE_ID[split],
        "protocol_state": _SPLIT_PROTOCOL_STATE[split],
        "split": split,
        "registry_split": _registry_split(split),
        "frozen": int(frozen),
        "query_budget_s": QUERY_METHOD_TIMEOUT_S,
        "budget_is_frozen": int(_BUDGET_IS_FROZEN),
        "query_workers": query_workers,
        "method_workers": method_workers,
        "query_parallelism": (
            "persistent-method-spawn-pool"
            if method_workers
            else "serial"
            if query_workers == 1
            else "persistent-query-spawn-pool"
        ),
        "lp_separation_workers": os.environ.get("CERTITHERM_LP_WORKERS", "1"),
        **numeric_threads,
        # The SAME revision the artifact rows record. Read twice, RUN_RECEIPT.tsv and
        # ARTIFACTS.tsv could claim different revisions for one bundle.
        "git_sha": git_sha,
        **submodules,
        "hotspot_binary_sha256": hotspot_digest,
        **gpu_digests,
        "operator_backend": (
            "gpu-proposal+cpu-hotspot-calibration" if gpu.enabled else "cpu-hotspot"
        ),
        **{f"{name}_registry_sha256": digest for name, digest in registries.items()},
        "host": socket.gethostname(),
        "python": sys.version.split()[0],
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": completed_at.isoformat(),
        "producer": _canonical_producer(split, frozen),
    }


def _assert_repository_unchanged_by_run() -> None:
    """Refuse to seal a bundle if the experiment changed the working tree.

    A dirty tree means the revision the receipt is about to record is not the revision that produced
    the evidence. Called before the receipt, the checksums and the artifact manifest are written:
    running it afterwards left a failed run looking like a sealed one.
    """

    status = subprocess.run(
        ["git", "status", "--porcelain", "--ignore-submodules=none"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise RuntimeError(f"repository became dirty during experiment:\n{status}")


@dataclass(frozen=True)
class RunEvidence:
    """Every row collection one run produced, named once so the write phase takes one argument.

    A frozen record rather than a mutable context bag. Peer review warned that one large mutable
    context makes the dependency flow LESS explicit than a long parameter list; the difference is
    that this one cannot be added to by the phase that consumes it.
    """

    results: list
    order_rows: list
    registry_rows: list
    spectral_rows: list
    plan_rows: list
    witness_rows: list
    witness_replay_rows: list
    failures: list


def _write_run_outputs(
    output: Path,
    split: str,
    operators: Mapping[tuple[str, str], Path],
    evidence: RunEvidence,
) -> None:
    """Write every scientific table and the report, and nothing that seals the bundle.

    Split from sealing on purpose. These files are the run's FINDINGS; the receipt, the checksums and
    the manifest are claims ABOUT those findings, and the integrity gate has to sit between the two.
    """

    _write_tsv(
        output / "results.tsv",
        evidence.results,
        fieldnames=_result_fieldnames(split),
    )
    # Every table below is written only when it has rows, and the checksum and artifact scans that
    # follow walk the whole output directory. A re-run into a directory that already held one of
    # these would therefore keep the STALE file and record it as this run's evidence. Peer review
    # found it. Removing them first makes "no rows" and "no file" the same statement.
    for conditional in (
        "measurement_registry.tsv",
        "spectral_envelopes.tsv",
        "plans.tsv",
        "witnesses.tsv",
        "witness_replays.tsv",
        "FAILURES.tsv",
    ):
        (output / conditional).unlink(missing_ok=True)
    _write_tsv(output / "candidate_order.tsv", evidence.order_rows)
    if evidence.registry_rows:
        _write_tsv(output / "measurement_registry.tsv", evidence.registry_rows)
    if evidence.spectral_rows:
        _write_tsv(output / "spectral_envelopes.tsv", evidence.spectral_rows)
    if evidence.plan_rows:
        _write_tsv(output / "plans.tsv", evidence.plan_rows)
    if evidence.witness_rows:
        _write_tsv(output / "witnesses.tsv", evidence.witness_rows)
    if evidence.witness_replay_rows:
        _write_tsv(output / "witness_replays.tsv", evidence.witness_replay_rows)
    if evidence.failures:
        _write_tsv(output / "FAILURES.tsv", evidence.failures)
    _write_report(
        output / "REPORT.md",
        split,
        operators,
        evidence.results,
        evidence.order_rows,
        evidence.failures,
        evidence.spectral_rows,
    )


def _seal_run_artifacts(
    output: Path,
    split: str,
    frozen: bool,
    started_at: datetime,
    hotspot_digest: str,
    gpu: GpuSelection,
) -> None:
    """Gate the tree, then stamp the receipt, the checksums and the manifest.

    Nothing here is a finding. Everything here is a claim that the findings were produced by a known
    revision under a known configuration -- which is why the gate comes first, and why a failure now
    leaves the directory unsealed instead of sealed-but-wrong.
    """

    # The integrity gate runs BEFORE the bundle is sealed. It used to run last, after the receipt,
    # the checksums and the artifact manifest were already on disk -- so a run that FAILED this gate
    # left an output directory that looked like a complete, sealed evidence bundle. Peer review found
    # it. Everything scientific has been written by this point, so the gate still covers the whole
    # experiment; what changes is that a dirty repository now prevents the bundle from ever looking
    # sealed.
    _assert_repository_unchanged_by_run()
    git_sha = _git_revision(ROOT)
    completed_at = datetime.now(timezone.utc)
    _write_tsv(
        output / "RUN_RECEIPT.tsv",
        [
            _run_receipt(
                split, frozen, started_at, hotspot_digest, gpu, git_sha, completed_at
            )
        ],
    )
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
                    "role": _artifact_role(path.relative_to(output)),
                    "path": str(path.relative_to(output)),
                    "sha256": _sha256(path),
                    "git_sha": git_sha,
                    "producer": _canonical_producer(split, frozen),
                }
            )
    _write_tsv(output / "ARTIFACTS.tsv", artifacts)


def _build_operators(
    architectures: Sequence[Mapping[str, str]],
    packages: Sequence[Mapping[str, str]],
    workloads: Sequence[Mapping[str, str]],
    captures: Mapping[tuple[str, str], Path],
    output: Path,
    gpu: GpuSelection,
) -> tuple[dict[tuple[str, str], Path], list[dict[str, object]]]:
    """Build every (architecture, package) thermal operator, collecting the physical failures.

    Returns `(operators, failures)`. A physical or infrastructure failure becomes a row rather than
    an exception -- `_is_archivable_operator_failure` decides which is which, and a programming
    defect still propagates, because treating a NameError as a scientific UNRESOLVED result would let
    broken code satisfy a coverage gate.

    `gpu` is the run's single snapshot, passed through to every operator so that each one's cache
    identity and the run receipt describe the same configuration.
    """

    failures: list[dict[str, object]] = []
    operators: dict[tuple[str, str], Path] = {}
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
                gpu=gpu,
            ), None
        except Exception as exc:  # archive physical/timeout failures unchanged
            if not _is_archivable_operator_failure(exc):
                raise
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
    return operators, failures


@dataclass(frozen=True)
class PreparedRun:
    """Everything the preparation phase produced, before any method has been evaluated.

    `result_rows` is not empty at this point: a candidate whose operator failed to build already has
    an UNRESOLVED row, and those rows have to reach the result table alongside the evaluated ones.
    They are sorted into registry order at the end regardless of which phase produced them.
    """

    queries: list
    result_rows: list
    order_rows: list
    registry_rows: list
    spectral_rows: list


def _prepare_queries(
    split: str,
    registry_split: str,
    architectures: Sequence[Mapping[str, str]],
    packages: Sequence[Mapping[str, str]],
    workloads: Sequence[Mapping[str, str]],
    captures: Mapping[tuple[str, str], Path],
    operators: Mapping[tuple[str, str], Path],
    measurement_costs: Mapping[str, float],
) -> PreparedRun:
    """Turn built operators into ordered queries, with their spectral and measurement registries.

    This is where a candidate becomes a `CandidateSpace`: its power polytope, its thermal family, its
    obtainable action library, and the EDYP order the query will be asked in. The spectral envelope is
    computed here too, and its exactness checked -- a full-rank envelope with a non-finite or nonzero
    certified tail stops the run rather than being recorded.

    A candidate whose operator is missing produces an UNRESOLVED result row instead of an exception,
    which is why `result_rows` comes back non-empty in that case.
    """

    result_rows: list = []
    order_rows: list = []
    registry_rows: list = []
    spectral_rows: list = []
    spectra: dict = {}
    prepared_queries: list = []
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
                result_rows.append(
                    {
                        "result_schema_version": RESULT_SCHEMA_VERSION,
                        "freeze_id": _SPLIT_FREEZE_ID[split],
                        "split": split,
                        "registry_split": registry_split,
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
                    # Finiteness BEFORE the exactness comparison. `NaN > 1e-7` is False, so a
                    # non-finite tail passed the full-rank check and was then recorded in
                    # spectral_envelopes.tsv as a certified bound. Peer review found this; it is the
                    # same comparison-based hole as load_capture_metrics, CertifiedContract,
                    # anytime_dsos and the cover search.
                    if not np.isfinite(tail):
                        raise RuntimeError(
                            f"spectral envelope for {candidate_id} produced a non-finite "
                            f"certified tail {tail}"
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
            prepared_queries.append(
                PreparedQuery(
                    query_id=query_id,
                    workload_id=workload["workload_id"],
                    package_id=package["package_id"],
                    candidates=tuple(candidates),
                    actions=tuple(actions),
                    fixed_order=fixed_order,
                    placed_by_candidate=placed_by_candidate,
                )
            )

    # The same two counts the receipt records. `method_workers` was previously left to a
    # definition-time default, so a patched METHOD_WORKERS moved the receipt without moving
    # execution.
    return PreparedRun(
        queries=prepared_queries,
        result_rows=result_rows,
        order_rows=order_rows,
        registry_rows=registry_rows,
        spectral_rows=spectral_rows,
    )


def run(split: str, output: Path, frozen: bool) -> None:
    started_at = datetime.now(timezone.utc)
    # ONE reading of the GPU configuration for the whole run. Every operator's cache identity and
    # the run receipt must describe the same configuration; taking separate readings meant nothing
    # enforced that the receipt described what the operators were actually built under. Environment
    # variables do not change inside a process, so this was not reachable by accident -- but the
    # invariant was held by nothing, and `_run_receipt` alone read one of them twice.
    gpu = GpuSelection.from_environment()
    _validate_run_request(split, frozen)
    if frozen:
        _assert_clean_revision()
    if not HOTSPOT.is_file() or not THERMODSE.is_dir():
        raise RuntimeError("run make bootstrap before experiments")
    hotspot_digest = _verified_binary_digest(
        HOTSPOT,
        HOTSPOT.parent / "SHA256SUMS",
    )
    output.mkdir(parents=True, exist_ok=True)
    registry_split = _registry_split(split)
    architectures = sorted(
        (
            row
            for row in _rows(ROOT / "experiments" / "architectures.tsv")
            if row["split"] == registry_split
        ),
        key=lambda row: int(row["rank"]),
    )
    packages = _rows(ROOT / "experiments" / "packages.tsv")
    measurement_costs = _measurement_costs()
    workloads = [
        row
        for row in _rows(ROOT / "experiments" / "workloads.tsv")
        if row["split"] == registry_split
    ]
    default_package = next(row for row in packages if row["package_id"] == "default")
    captures = {
        (workload["workload_id"], arch["architecture_id"]): _capture(
            arch, workload, default_package, output
        )
        for workload in workloads
        for arch in architectures
    }
    operators, failures = _build_operators(
        architectures, packages, workloads, captures, output, gpu
    )
    plan_rows, witness_rows, witness_replay_rows = [], [], []
    prepared = _prepare_queries(
        split,
        registry_split,
        architectures,
        packages,
        workloads,
        captures,
        operators,
        measurement_costs,
    )
    prepared_queries = prepared.queries
    results = prepared.result_rows
    order_rows = prepared.order_rows
    registry_rows = prepared.registry_rows
    spectral_rows = prepared.spectral_rows
    method_batches = _evaluate_query_batch(
        prepared_queries,
        include_anytime=split in _ANYTIME_SPLITS,
        workers=_query_worker_count(split),
        method_workers=METHOD_WORKERS,
    )
    if len(method_batches) != len(prepared_queries):
        raise RuntimeError("query evaluator returned an incomplete result batch")
    for query, methods in zip(prepared_queries, method_batches):
        evidence = _archive_query_evidence(
            query,
            methods,
            split=split,
            operators=operators,
            output=output,
        )
        results.append(evidence.result)
        plan_rows.extend(evidence.plans)
        witness_rows.extend(evidence.witnesses)
        witness_replay_rows.extend(evidence.witness_replays)
        failures.extend(evidence.failures)

    query_order = {}
    for workload in workloads:
        for package in packages:
            key = workload["workload_id"], package["package_id"]
            query_order[key] = len(query_order)
    results.sort(
        key=lambda row: query_order[(str(row["workload"]), str(row["package"]))]
    )

    _write_run_outputs(
        output,
        split,
        operators,
        RunEvidence(
            results=results,
            order_rows=order_rows,
            registry_rows=registry_rows,
            spectral_rows=spectral_rows,
            plan_rows=plan_rows,
            witness_rows=witness_rows,
            witness_replay_rows=witness_replay_rows,
            failures=failures,
        ),
    )
    _seal_run_artifacts(output, split, frozen, started_at, hotspot_digest, gpu)
