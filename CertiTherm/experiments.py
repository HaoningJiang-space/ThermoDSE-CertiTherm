"""Frozen ThermoDSE/HotSpot experiment driver with resumable NPZ evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Dict, Iterable

import numpy as np

from .core import CandidateSpace, MeasurementAction, PowerPolytope
from .hotspot import build_family, load_family, replay_power, save_family
from .policies import dual_price_greedy, sequential_early_stop, uncertainty_width_order
from .synthesis import synthesize_ordered_query


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "CertiTherm" / "evidence" / "thermodse_tmp_template"
THERMODSE = ROOT / "ThermoDSE"
HOTSPOT = ROOT / ".build" / "hotspot" / "hotspot"
MODELS = ("block", "grid64-avg", "grid128-avg")
THERMAL_LIMIT_K = 330.0


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


def _operator(
    arch: dict[str, str],
    package: dict[str, str],
    capture: Path,
    output: Path,
) -> Path:
    target = output / "operators" / f"{arch['architecture_id']}--{package['package_id']}.npz"
    if target.is_file():
        return target
    work = output / "work" / f"operator--{arch['architecture_id']}--{package['package_id']}"
    work.mkdir(parents=True, exist_ok=True)
    with np.load(capture, allow_pickle=False) as data:
        floorplan = work / "floorplan.flp"
        floorplan.write_text(str(data["floorplan_text"]), encoding="utf-8")
        placed_power = np.asarray(data["placed_power_w"], dtype=float)
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
    for model_index, model_id in enumerate(family.model_ids):
        direct = replay_power(
            HOTSPOT,
            config,
            floorplan,
            TEMPLATE / "example.materials",
            model_id,
            blocks,
            placed_power,
            work / "calibration" / model_id,
        )
        predicted = (
            family.ambient_k[model_index]
            + family.response_k_per_w[model_index] @ placed_power
        )
        error = float(np.max(np.abs(direct - predicted)))
        calibration.append(
            {"model_id": model_id, "max_abs_error_k": error, "limit_k": 1e-5}
        )
        if error > 1e-5:
            raise RuntimeError(f"{model_id} impulse superposition error is {error:.6g} K")
    save_family(target, family, blocks)
    _write_tsv(target.with_suffix(".calibration.tsv"), calibration)
    return target


def _power_space(capture: Path) -> tuple[PowerPolytope, tuple[str, ...], np.ndarray]:
    with np.load(capture, allow_pickle=False) as data:
        blocks = tuple(data["block_ids"].tolist())
        placed = np.asarray(data["placed_power_w"], dtype=float)
    groups: Dict[str, list[int]] = {}
    for index, block in enumerate(blocks):
        groups.setdefault(re.sub(r"_\d+$", "", block), []).append(index)
    a_eq, b_eq, upper = [], [], np.zeros(len(blocks))
    for indices in groups.values():
        row = np.zeros(len(blocks))
        row[indices] = 1.0
        total = float(np.sum(placed[indices]))
        a_eq.append(row)
        b_eq.append(total)
        upper[indices] = total
    return (
        PowerPolytope(
            np.zeros(len(blocks)),
            upper,
            np.asarray(a_eq),
            np.asarray(b_eq),
            np.empty((0, len(blocks))),
            np.empty(0),
        ),
        blocks,
        placed,
    )


def _write_tsv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    rows = list(rows)
    if not rows:
        raise RuntimeError("refusing to write empty evidence table")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def run(split: str, output: Path, frozen: bool) -> None:
    if frozen and split != "heldout":
        raise ValueError("--frozen is reserved for the held-out split")
    if not HOTSPOT.is_file() or not THERMODSE.is_dir():
        raise RuntimeError("run make bootstrap before experiments")
    output.mkdir(parents=True, exist_ok=True)
    architectures = sorted(
        _rows(ROOT / "experiments" / "architectures.tsv"), key=lambda row: int(row["rank"])
    )
    packages = _rows(ROOT / "experiments" / "packages.tsv")
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
    operators = {
        (arch["architecture_id"], package["package_id"]): _operator(
            arch,
            package,
            captures[(workloads[0]["workload_id"], arch["architecture_id"])],
            output,
        )
        for arch in architectures
        for package in packages
    }
    results = []
    for workload in workloads:
        for package in packages:
            candidates, actions = [], []
            placed_by_candidate = {}
            for arch in architectures:
                candidate_id = arch["architecture_id"]
                power, blocks, placed = _power_space(
                    captures[(workload["workload_id"], candidate_id)]
                )
                family, operator_blocks = load_family(
                    operators[(candidate_id, package["package_id"])]
                )
                if blocks != operator_blocks:
                    raise RuntimeError("power/operator block identity mismatch")
                candidates.append(CandidateSpace(candidate_id, power, family))
                placed_by_candidate[candidate_id] = placed
                actions.extend(
                    MeasurementAction(
                        f"{candidate_id}::{block}",
                        np.eye(len(blocks))[index],
                        candidate_id=candidate_id,
                    )
                    for index, block in enumerate(blocks)
                )
            exact = synthesize_ordered_query(candidates, actions)
            fixed = sequential_early_stop(candidates, actions, tuple(range(len(actions))))
            width = sequential_early_stop(
                candidates, actions, uncertainty_width_order(candidates, actions)
            )
            dual = dual_price_greedy(candidates, actions)
            results.append(
                {
                    "freeze_id": "method-freeze-v1",
                    "split": split,
                    "workload": workload["workload_id"],
                    "package": package["package_id"],
                    "exact_status": exact.status,
                    "exact_cost": exact.exact_cost,
                    "milp_lower_bound": exact.lower_bound,
                    "lp_relaxation_bound": exact.relaxation_bound,
                    "optimality_gap": exact.optimality_gap,
                    "fixed_cost": fixed.cost,
                    "width_cost": width.cost,
                    "dual_cost": dual.cost,
                    "full_registry_cost": sum(action.cost for action in actions),
                    "witnesses": len(exact.witnesses),
                }
            )
    result_path = output / "results.tsv"
    _write_tsv(result_path, results)
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
        if path.is_file() and "work" not in path.parts
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
        if path.is_file() and "work" not in path.parts:
            artifacts.append(
                {
                    "role": "result" if path == result_path else "scientific_input",
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
