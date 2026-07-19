"""Build and run a real 2x2x2 CertiTherm G3 suite.

This script constructs a content-bound experimental matrix:
  2 DNN families x 2 non-isomorphic architectures x 2 package regimes.

For each workload/package stratum, it emits:
  - a query spec (certitherm.g2-query-spec.v2),
  - candidate-bound point/placed/spatial inputs,
  - per-stratum manifest with SHA-256 digests.

It then executes the G3 suite runner and writes:
  - suite artifact + suite replay receipt,
  - per-case query artifact digests and replay status,
  - independent HotSpot replay checks for spatial witness tuples.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
THERMODSE_ROOT = REPO_ROOT / "ThermoDSE"
TMP_TEMPLATE = THERMODSE_ROOT / "tmp"

sys.path.insert(0, str(THERMODSE_ROOT))
sys.path.insert(0, str(REPO_ROOT / "CertiTherm" / "exact"))

from core.chiplet_eva import chiplet_evaluator  # type: ignore  # noqa: E402
from evidence import replay_artifact, sha256_file  # type: ignore  # noqa: E402
from g3_full_empirical import (  # type: ignore  # noqa: E402
    execute_g3_suite,
    load_g3_suite,
    replay_g3_suite_artifact,
)


ARCHS: dict[str, dict[str, Any]] = {
    "arch_4x4_mesh_fullcut": {
        "architecture_family": "mesh_fullcut",
        "sys_info": [4, 4, 4, 4, 0.0005, 112, 128, 4194304, 64, 128],
        "standard_R": REPO_ROOT / "CertiTherm" / "exact" / "R_4x4.npy",
        "standard_meta": REPO_ROOT / "CertiTherm" / "exact" / "R_4x4_meta.json",
    },
    "arch_5x4_rect_struct": {
        "architecture_family": "rect_struct",
        "sys_info": [5, 4, 5, 4, 0.001, 144, 128, 2097152, 144, 128],
        "standard_R": REPO_ROOT / "CertiTherm" / "exact" / "R_5x4.npy",
        "standard_meta": REPO_ROOT / "CertiTherm" / "exact" / "R_5x4_meta.json",
    },
}

WORKLOADS: dict[str, dict[str, Any]] = {
    "cnn": {
        "workload_id": "resnet50",
        "net_name": "resnet50",
        "b_tot": 2,
        "b_exe": 2,
        "sparsity": 0.217,
    },
    "attention": {
        "workload_id": "transformer",
        "net_name": "transformer",
        "b_tot": 1,
        "b_exe": 1,
        "sparsity": 0.0,
    },
}

PACKAGES: dict[str, dict[str, Any]] = {
    "standard_sink_s06": {
        "config_src": REPO_ROOT
        / "CertiTherm"
        / "evidence"
        / "g3_2x2x2_bundle"
        / "configs"
        / "standard.config",
    },
    "enhanced_sink_s10": {
        "config_src": REPO_ROOT
        / "CertiTherm"
        / "evidence"
        / "g3_2x2x2_bundle"
        / "configs"
        / "enhanced.config",
    },
}


def _component_group(name: str) -> str:
    if name.startswith("io_"):
        parts = name.split("_")
        if len(parts) >= 3:
            return "_".join(parts[:2])
    if "_" in name and name.rsplit("_", 1)[1].isdigit():
        return name.rsplit("_", 1)[0]
    return name


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_meta(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_ptrace(path: Path) -> tuple[list[str], np.ndarray]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        raise RuntimeError(f"ptrace missing rows: {path}")
    header = lines[0].strip().split("\t")
    row = np.asarray([float(item) for item in lines[1].strip().split("\t")], dtype=np.float64)
    if len(header) != row.shape[0]:
        raise RuntimeError(f"ptrace header/value mismatch: {path}")
    if not np.all(np.isfinite(row)) or np.any(row < 0.0):
        raise RuntimeError(f"ptrace contains invalid values: {path}")
    return header, row


def _write_ptrace(path: Path, header: list[str], values: np.ndarray) -> None:
    with path.open("w", encoding="utf-8") as stream:
        stream.write("\t".join(header) + "\n")
        stream.write("\t".join(f"{float(v):.10f}" for v in values.tolist()) + "\n")


def _parse_steady(path: Path) -> dict[str, float]:
    temps: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        try:
            temps[parts[0]] = float(parts[1])
        except ValueError:
            continue
    if not temps:
        raise RuntimeError(f"steady file has no temperatures: {path}")
    return temps


def _flp_units(path: Path) -> list[str]:
    units: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        parts = text.split()
        if len(parts) >= 5:
            units.append(parts[0])
    if not units:
        raise RuntimeError(f"no floorplan units found in {path}")
    return units


def _run_hotspot_block(
    hotspot_bin: Path,
    config: Path,
    flp: Path,
    ptrace: Path,
    materials: Path,
    steady_out: Path,
) -> None:
    steady_out.parent.mkdir(parents=True, exist_ok=True)
    if steady_out.exists():
        steady_out.unlink()
    cmd = [
        str(hotspot_bin),
        "-c",
        str(config),
        "-f",
        str(flp),
        "-p",
        str(ptrace),
        "-materials_file",
        str(materials),
        "-model_type",
        "block",
        "-steady_file",
        str(steady_out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"HotSpot failed ({result.returncode}): {result.stderr[-400:]}")
    if not steady_out.is_file():
        raise RuntimeError("HotSpot produced no steady output")


def _probe_flp_units(
    arch_name: str,
    sys_info: list[Any],
    workspace_root: Path,
    hotspot_root: Path,
) -> list[str]:
    sim_path = workspace_root / f"{arch_name}_flp_probe"
    if sim_path.exists():
        shutil.rmtree(sim_path)
    shutil.copytree(TMP_TEMPLATE, sim_path)
    ev = chiplet_evaluator(
        hotspot_path=str(hotspot_root),
        sim_path=str(sim_path),
        sys_info=sys_info,
        thermal_map=False,
        baseline1=False,
        baseline2=False,
        baseline3=False,
        wkld_idpdt=False,
        clock_freq=1.8e9,
    )
    ev.generate_hardware()
    return _flp_units(sim_path / "floorplan" / "output_3D.flp")


def _capture_workload_power(
    arch_name: str,
    sys_info: list[Any],
    workload_key: str,
    capture_root: Path,
    hotspot_root: Path,
) -> dict[str, Any]:
    workload = WORKLOADS[workload_key]
    sim_path = capture_root / f"{arch_name}_{workload_key}"
    if sim_path.exists():
        shutil.rmtree(sim_path)
    shutil.copytree(TMP_TEMPLATE, sim_path)

    ev = chiplet_evaluator(
        hotspot_path=str(hotspot_root),
        sim_path=str(sim_path),
        sys_info=sys_info,
        thermal_map=False,
        baseline1=False,
        baseline2=False,
        baseline3=False,
        wkld_idpdt=False,
        clock_freq=1.8e9,
    )
    ev.nets = [workload["net_name"]]
    ev.b_tot = [workload["b_tot"]]
    ev.b_exe = [workload["b_exe"]]
    ev.sparsty = [workload["sparsity"]]
    ev.generate_hardware()
    # For point/placed capture we only need EDYP + ptrace, not a thermal solve.
    # Avoid path-sensitive run.sh failures in temporary capture directories.
    if hasattr(ev, "flp_generator") and hasattr(ev.flp_generator, "run_hotspot"):
        ev.flp_generator.run_hotspot = lambda *args, **kwargs: None
    delay, energy, die_yield = ev.evaluate()
    edyp = float(energy * delay / die_yield)

    ptrace = sim_path / "ptrace" / "cores_3D.ptrace"
    header, placed = _parse_ptrace(ptrace)

    # ThermoDSE point estimate: per-component averages from placed totals.
    groups: dict[str, list[int]] = {}
    for idx, name in enumerate(header):
        groups.setdefault(_component_group(name), []).append(idx)
    point = np.zeros_like(placed)
    for indices in groups.values():
        values = placed[indices]
        avg = float(np.mean(values))
        point[indices] = avg
    if not np.all(np.isfinite(point)) or np.any(point < 0.0):
        raise RuntimeError("point estimate construction failed")

    placement_file = sim_path / "floorplan" / "output_3D.flp"
    placement_sha = sha256_file(placement_file)
    return {
        "block_names": header,
        "placed_power": placed,
        "point_power": point,
        "edyp": edyp,
        "placement_file": placement_file,
        "placement_sha256": placement_sha,
    }


def _compute_response_matrix(
    arch_name: str,
    sys_info: list[Any],
    block_names: list[str],
    package_name: str,
    config_path: Path,
    workspace_root: Path,
    hotspot_bin: Path,
) -> tuple[np.ndarray, float, list[str]]:
    sim_path = workspace_root / f"{arch_name}_{package_name}_response"
    if sim_path.exists():
        shutil.rmtree(sim_path)
    shutil.copytree(TMP_TEMPLATE, sim_path)

    # Replace package config.
    shutil.copy2(config_path, sim_path / "example.config")

    ev = chiplet_evaluator(
        hotspot_path=str(hotspot_bin.parent),
        sim_path=str(sim_path),
        sys_info=sys_info,
        thermal_map=False,
        baseline1=False,
        baseline2=False,
        baseline3=False,
        wkld_idpdt=False,
        clock_freq=1.8e9,
    )
    ev.generate_hardware()

    flp = sim_path / "floorplan" / "output_3D.flp"
    materials = sim_path / "example.materials"
    ptrace = sim_path / "ptrace" / "matrix_probe.ptrace"
    steady = sim_path / "outputs" / "matrix_probe.steady"

    flp_units = _flp_units(flp)
    if set(flp_units).issubset(set(block_names)):
        run_blocks = flp_units
    elif set(block_names).issubset(set(flp_units)):
        run_blocks = block_names
    else:
        raise RuntimeError(
            f"response block mismatch for {arch_name}/{package_name}: "
            f"flp={len(flp_units)} requested={len(block_names)}"
        )

    n = len(run_blocks)
    zero = np.zeros(n, dtype=np.float64)
    _write_ptrace(ptrace, run_blocks, zero)
    _run_hotspot_block(hotspot_bin, sim_path / "example.config", flp, ptrace, materials, steady)
    ambient_map = _parse_steady(steady)
    ambient = float(np.mean([ambient_map[name] for name in run_blocks if name in ambient_map]))

    R = np.zeros((n, n), dtype=np.float64)
    for j in range(n):
        basis = np.zeros(n, dtype=np.float64)
        basis[j] = 1.0
        _write_ptrace(ptrace, run_blocks, basis)
        _run_hotspot_block(
            hotspot_bin, sim_path / "example.config", flp, ptrace, materials, steady
        )
        temps = _parse_steady(steady)
        for i, name in enumerate(run_blocks):
            R[i, j] = float(temps.get(name, ambient) - ambient)
        if (j + 1) % 25 == 0 or j + 1 == n:
            print(f"[matrix] {arch_name}/{package_name}: {j + 1}/{n}", flush=True)
    return R, ambient, run_blocks


def _build_spatial_observation(block_names: list[str], point: np.ndarray, placed: np.ndarray) -> dict[str, Any]:
    groups: dict[str, list[int]] = {}
    for idx, name in enumerate(block_names):
        groups.setdefault(_component_group(name), []).append(idx)
    A_eq = []
    b_eq = []
    for indices in groups.values():
        row = [0.0] * len(block_names)
        for idx in indices:
            row[idx] = 1.0
        A_eq.append(row)
        b_eq.append(float(np.sum(placed[indices])))
    upper = np.maximum(np.maximum(placed, point * 5.0), point * 1.05)
    lower = np.zeros(len(block_names), dtype=np.float64)
    return {
        "A_eq": A_eq,
        "b_eq": b_eq,
        "per_block_power": point.tolist(),
        "per_block_lower": lower.tolist(),
        "per_block_upper": upper.tolist(),
    }


def _aggregate_file_manifest(root: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Build real 2x2x2 G3 suite bundle")
    parser.add_argument(
        "--bundle-root",
        type=Path,
        default=REPO_ROOT / "CertiTherm" / "evidence" / "g3_2x2x2_real_bundle",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=THERMODSE_ROOT / "tmp_g3_build",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/tmp/certitherm_g3_real_outputs"),
    )
    parser.add_argument(
        "--hotspot-bin",
        type=Path,
        default=REPO_ROOT / "HotSpot" / "hotspot",
    )
    parser.add_argument(
        "--thermal-limit-k",
        type=float,
        default=348.0,
    )
    parser.add_argument(
        "--force-recompute-response",
        action="store_true",
        help="Recompute all package response matrices even if cached in bundle.",
    )
    args = parser.parse_args()

    bundle = args.bundle_root.resolve()
    workspace = args.workspace_root.resolve()
    output_root = args.output_root.resolve()
    hotspot_bin = args.hotspot_bin.resolve()

    if not hotspot_bin.is_file():
        raise SystemExit(f"HotSpot binary not found: {hotspot_bin}")

    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "configs").mkdir(parents=True, exist_ok=True)
    (bundle / "architectures").mkdir(parents=True, exist_ok=True)
    (bundle / "queries").mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    # Copy package configs into bundle for content binding.
    package_cfg_paths: dict[str, Path] = {}
    for pkg, info in PACKAGES.items():
        dst = bundle / "configs" / f"{pkg}.config"
        shutil.copy2(Path(info["config_src"]), dst)
        package_cfg_paths[pkg] = dst

    # Build responses and workload powers.
    arch_responses: dict[tuple[str, str], dict[str, Any]] = {}
    power_records: dict[tuple[str, str], dict[str, Any]] = {}

    for arch_name, arch_info in ARCHS.items():
        standard_R = np.load(arch_info["standard_R"], allow_pickle=False)
        standard_meta = _load_meta(Path(arch_info["standard_meta"]))
        block_names = list(standard_meta["blocks"])
        ambient_standard = float(standard_meta["T_ambient"])
        flp_unit_names = _probe_flp_units(
            arch_name=arch_name,
            sys_info=list(arch_info["sys_info"]),
            workspace_root=workspace / "probe",
            hotspot_root=hotspot_bin.parent,
        )
        flp_unit_set = set(flp_unit_names)

        for pkg in PACKAGES:
            dst_dir = bundle / "architectures" / arch_name / pkg
            dst_dir.mkdir(parents=True, exist_ok=True)
            r_path = dst_dir / "R.npy"
            meta_path = dst_dir / "R_meta.json"
            use_cached = r_path.is_file() and meta_path.is_file() and not args.force_recompute_response
            if use_cached:
                R = np.load(r_path, allow_pickle=False)
                cached_meta = _load_meta(meta_path)
                cached_blocks = list(cached_meta.get("blocks", []))
                if set(cached_blocks) != flp_unit_set:
                    use_cached = False
                elif R.shape != (len(cached_blocks), len(cached_blocks)):
                    use_cached = False
            if use_cached:
                ambient = float(_load_meta(meta_path)["T_ambient"])
            else:
                if pkg == "standard_sink_s06":
                    if set(block_names) == flp_unit_set and standard_R.shape == (
                        len(block_names),
                        len(block_names),
                    ):
                        R = standard_R.copy()
                        ambient = ambient_standard
                        meta_blocks = block_names
                    else:
                        R, ambient, std_blocks = _compute_response_matrix(
                            arch_name=arch_name,
                            sys_info=list(arch_info["sys_info"]),
                            block_names=block_names,
                            package_name=pkg,
                            config_path=package_cfg_paths[pkg],
                            workspace_root=workspace,
                            hotspot_bin=hotspot_bin,
                        )
                        meta_blocks = std_blocks
                else:
                    R, ambient, enhanced_blocks = _compute_response_matrix(
                        arch_name=arch_name,
                        sys_info=list(arch_info["sys_info"]),
                        block_names=block_names,
                        package_name=pkg,
                        config_path=package_cfg_paths[pkg],
                        workspace_root=workspace,
                        hotspot_bin=hotspot_bin,
                    )
                    meta_blocks = enhanced_blocks
                np.save(r_path, R)
                _write_json(
                    meta_path,
                    {
                        "sys_info": arch_info["sys_info"],
                        "T_ambient": ambient,
                        "blocks": meta_blocks,
                        "temperature_points": meta_blocks,
                        "shape": [int(R.shape[0]), int(R.shape[1])],
                        "R_lambda_max": float(np.linalg.norm(R, 2)),
                        "R_1norm": float(np.linalg.norm(R, 1)),
                    },
                )
            arch_responses[(arch_name, pkg)] = {
                "R_path": r_path,
                "meta_path": meta_path,
                "R_sha256": sha256_file(r_path),
                "meta": _load_meta(meta_path),
            }

        for wk in WORKLOADS:
            power_records[(arch_name, wk)] = _capture_workload_power(
                arch_name=arch_name,
                sys_info=list(arch_info["sys_info"]),
                workload_key=wk,
                capture_root=workspace / "capture",
                hotspot_root=hotspot_bin.parent,
            )

    # Stable objective order per workload/candidate, shared across package strata.
    objective_map: dict[tuple[str, str], tuple[float, int]] = {}
    for wk in WORKLOADS:
        scored = []
        for arch_name in ARCHS:
            scored.append((arch_name, float(power_records[(arch_name, wk)]["edyp"])))
        scored.sort(key=lambda item: item[1])
        for rank, (arch_name, score) in enumerate(scored):
            objective_map[(wk, arch_name)] = (score, rank)

    suite_queries: list[dict[str, Any]] = []
    workload_order = ["cnn", "attention"]
    package_order = ["standard_sink_s06", "enhanced_sink_s10"]

    for wk in workload_order:
        wk_id = WORKLOADS[wk]["workload_id"]
        for pkg in package_order:
            stratum_dir = bundle / "queries" / f"{wk}_{pkg}"
            stratum_dir.mkdir(parents=True, exist_ok=True)
            candidates = []

            for arch_name, arch_info in ARCHS.items():
                resp = arch_responses[(arch_name, pkg)]
                power = power_records[(arch_name, wk)]
                meta = resp["meta"]
                expected_blocks = list(meta["blocks"])
                source_blocks = power["block_names"]
                if not set(expected_blocks).issubset(set(source_blocks)):
                    raise RuntimeError(
                        f"block set mismatch for {arch_name}/{wk}: "
                        f"expected subset size={len(expected_blocks)} got={len(source_blocks)}"
                    )
                placed_map = dict(zip(source_blocks, power["placed_power"].tolist()))
                point_map = dict(zip(source_blocks, power["point_power"].tolist()))
                placed = np.asarray([placed_map[name] for name in expected_blocks], dtype=np.float64)
                point = np.asarray([point_map[name] for name in expected_blocks], dtype=np.float64)

                candidate_dir = stratum_dir / arch_name
                candidate_dir.mkdir(parents=True, exist_ok=True)
                response_npy = candidate_dir / "response.npy"
                response_meta = candidate_dir / "thermal_metadata.json"
                observation_json = candidate_dir / "observation.json"
                point_npy = candidate_dir / "point_power.npy"
                placed_npy = candidate_dir / "placed_power.npy"

                shutil.copy2(resp["R_path"], response_npy)
                np.save(point_npy, point)
                np.save(placed_npy, placed)
                _write_json(response_meta, resp["meta"])

                placed_sha = sha256_file(placed_npy)
                point_sha = sha256_file(point_npy)
                response_sha = sha256_file(response_npy)
                cfg_sha = sha256_file(package_cfg_paths[pkg])
                observation = _build_spatial_observation(expected_blocks, point, placed)
                provenance = {
                    "workload_id": wk_id,
                    "workload_family": wk,
                    "architecture_id": arch_name,
                    "architecture_family": arch_info["architecture_family"],
                    "package_id": pkg,
                    "power_source": placed_npy.name,
                    "power_source_sha256": placed_sha,
                    "placed_power_sha256": placed_sha,
                    "placement_sha256": power["placement_sha256"],
                    "thermal_backend": "hotspot-block-model",
                    "thermal_config_sha256": cfg_sha,
                    "thermal_operator_sha256": response_sha,
                }
                _write_json(
                    observation_json,
                    {
                        "schema_version": "certitherm.placed-power-observation.v1",
                        "block_names": expected_blocks,
                        "observation": observation,
                        "provenance": provenance,
                    },
                )
                _write_json(
                    candidate_dir / "case_manifest.json",
                    {
                        "schema_version": "certitherm.g3-case-manifest.v1",
                        "case_id": f"{wk}::{pkg}::{arch_name}",
                        "workload_family": wk,
                        "workload_id": wk_id,
                        "package_id": pkg,
                        "architecture_id": arch_name,
                        "files": [
                            {
                                "path": response_npy.relative_to(stratum_dir).as_posix(),
                                "sha256": response_sha,
                            },
                            {
                                "path": response_meta.relative_to(stratum_dir).as_posix(),
                                "sha256": sha256_file(response_meta),
                            },
                            {
                                "path": observation_json.relative_to(stratum_dir).as_posix(),
                                "sha256": sha256_file(observation_json),
                            },
                            {
                                "path": point_npy.relative_to(stratum_dir).as_posix(),
                                "sha256": point_sha,
                            },
                            {
                                "path": placed_npy.relative_to(stratum_dir).as_posix(),
                                "sha256": placed_sha,
                            },
                        ],
                    },
                )

                score, tie_rank = objective_map[(wk, arch_name)]
                candidates.append(
                    {
                        "candidate_id": arch_name,
                        "nonthermal_objective": score,
                        "tie_break_rank": tie_rank,
                        "response_npy": response_npy.relative_to(stratum_dir).as_posix(),
                        "thermal_metadata_json": response_meta.relative_to(stratum_dir).as_posix(),
                        "observation_json": observation_json.relative_to(stratum_dir).as_posix(),
                        "point_power_npy": point_npy.relative_to(stratum_dir).as_posix(),
                        "point_power_semantics": "original_thermodse_point_estimate",
                        "placed_power_npy": placed_npy.relative_to(stratum_dir).as_posix(),
                        "area_mm2": 1.0,
                    }
                )

            query_json = stratum_dir / "query.json"
            _write_json(
                query_json,
                {
                    "schema_version": "certitherm.g2-query-spec.v2",
                    "query_id": f"g3-real-{wk}-{pkg}",
                    "thermal_limit_k": args.thermal_limit_k,
                    "evidence_class": "physical_placed_power",
                    "candidates": sorted(candidates, key=lambda item: item["tie_break_rank"]),
                },
            )
            _write_json(
                stratum_dir / "manifest.json",
                {
                    "schema_version": "certitherm.g3-case-manifest.v1",
                    "workload_family": wk,
                    "workload_id": wk_id,
                    "package_id": pkg,
                    "files": _aggregate_file_manifest(stratum_dir),
                },
            )
            suite_queries.append(
                {
                    "workload_family": wk,
                    "workload_id": wk_id,
                    "package_id": pkg,
                    "query_spec": query_json.relative_to(bundle).as_posix(),
                }
            )

    suite_path = bundle / "suite.json"
    _write_json(
        suite_path,
        {
            "schema_version": "certitherm.g3-suite.v1",
            "suite_id": "g3_real_2x2x2_content_bound",
            "evidence_class": "physical_placed_power",
            "workload_families": workload_order,
            "architecture_families": sorted({info["architecture_family"] for info in ARCHS.values()}),
            "package_regimes": package_order,
            "queries": sorted(
                suite_queries,
                key=lambda item: (workload_order.index(item["workload_family"]), package_order.index(item["package_id"])),
            ),
        },
    )

    loaded = load_g3_suite(suite_path)
    artifact = execute_g3_suite(
        loaded,
        source_commit=subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        argv=[sys.executable, *sys.argv],
        environment={
            "python": sys.version,
            "hostname": os.uname().nodename,
            "hotspot_bin": str(hotspot_bin),
        },
    )
    receipt = replay_g3_suite_artifact(artifact)
    artifact_path = output_root / "g3_suite_artifact.json"
    receipt_path = output_root / "g3_suite_receipt.json"
    _write_json(artifact_path, artifact)
    _write_json(receipt_path, receipt)

    # Per-case replay summary with embedded artifact SHA and replay status.
    case_records: list[dict[str, Any]] = []
    case_matrix_records: list[dict[str, Any]] = []
    for entry in artifact["entries"]:
        per_variant = {}
        for variant_name, variant_artifact in entry["variants"].items():
            variant_receipt = replay_artifact(variant_artifact)
            per_variant[variant_name] = {
                "artifact_sha256": variant_artifact.get("artifact_sha256"),
                "replay_status": variant_receipt.get("status"),
                "query_status": variant_artifact.get("result", {}).get("status"),
                "reachable_outcomes": variant_artifact.get("result", {}).get("reachable_outcomes"),
            }
        case_records.append(
            {
                "query_id": entry["query_id"],
                "workload_family": entry["workload_family"],
                "workload_id": entry["workload_id"],
                "package_id": entry["package_id"],
                "variants": per_variant,
            }
        )
        # 2x2x2 = 8 case rows indexed by architecture inside each stratum.
        by_variant_bounds = {}
        for variant_name, variant_artifact in entry["variants"].items():
            result = variant_artifact.get("result", {})
            bounds = result.get("candidate_bounds", [])
            bound_map = {item.get("candidate_id"): item for item in bounds if isinstance(item, dict)}
            by_variant_bounds[variant_name] = {
                "query_artifact_sha256": variant_artifact.get("artifact_sha256"),
                "query_replay_status": replay_artifact(variant_artifact).get("status"),
                "query_status": result.get("status"),
                "bound_by_candidate": bound_map,
            }
        for arch_name in ARCHS:
            case_matrix_records.append(
                {
                    "case_id": f"{entry['workload_family']}::{entry['package_id']}::{arch_name}",
                    "workload_family": entry["workload_family"],
                    "workload_id": entry["workload_id"],
                    "package_id": entry["package_id"],
                    "architecture_id": arch_name,
                    "point_estimate": by_variant_bounds["point_estimate"],
                    "placed_reference": by_variant_bounds["placed_reference"],
                    "spatial_equivalence": by_variant_bounds["spatial_equivalence"],
                }
            )
    _write_json(output_root / "g3_case_query_artifact_receipts.json", case_records)
    _write_json(output_root / "g3_case_matrix_index.json", case_matrix_records)

    # Independent HotSpot witness replay for NON_IDENTIFIABLE spatial cases.
    witness_replays: list[dict[str, Any]] = []
    for entry in artifact["entries"]:
        spatial = entry["variants"]["spatial_equivalence"]["result"]
        if spatial.get("status") != "NON_IDENTIFIABLE":
            continue
        pkg = entry["package_id"]
        cfg = package_cfg_paths[pkg]
        thermal_limit = float(entry["variants"]["spatial_equivalence"]["inputs"]["thermal_limit_k"])
        candidates = entry["variants"]["spatial_equivalence"]["inputs"]["candidates"]
        by_id = {cand["candidate_id"]: cand for cand in candidates}
        for tuple_idx, witness_tuple in enumerate(spatial.get("witness_tuples", [])):
            candidate_checks = []
            for cand in witness_tuple.get("candidates", []):
                cand_id = cand["candidate_id"]
                cand_input = by_id[cand_id]
                block_names = list(cand_input["block_names"])
                power = np.asarray(cand["power_w"], dtype=np.float64)
                sys_info = list(cand_input.get("sys_info", []))
                sim_dir = workspace / "witness_replay" / f"{entry['query_id']}_{tuple_idx}_{cand_id}"
                if sim_dir.exists():
                    shutil.rmtree(sim_dir)
                shutil.copytree(TMP_TEMPLATE, sim_dir)
                shutil.copy2(cfg, sim_dir / "example.config")
                ev = chiplet_evaluator(
                    hotspot_path=str(hotspot_bin.parent),
                    sim_path=str(sim_dir),
                    sys_info=sys_info,
                    thermal_map=False,
                    baseline1=False,
                    baseline2=False,
                    baseline3=False,
                    wkld_idpdt=False,
                    clock_freq=1.8e9,
                )
                ev.generate_hardware()
                flp_path = sim_dir / "floorplan" / "output_3D.flp"
                flp_units = _flp_units(flp_path)
                power_map = dict(zip(block_names, power.tolist()))
                run_blocks = [name for name in flp_units if name in power_map]
                if not run_blocks:
                    raise RuntimeError("witness replay block mapping is empty")
                run_power = np.asarray([power_map[name] for name in run_blocks], dtype=np.float64)
                ptrace = sim_dir / "ptrace" / "witness.ptrace"
                _write_ptrace(ptrace, run_blocks, run_power)
                steady = sim_dir / "outputs" / "witness.steady"
                _run_hotspot_block(
                    hotspot_bin,
                    sim_dir / "example.config",
                    flp_path,
                    ptrace,
                    sim_dir / "example.materials",
                    steady,
                )
                temps = _parse_steady(steady)
                peak = max(float(v) for v in temps.values())
                candidate_checks.append(
                    {
                        "candidate_id": cand_id,
                        "peak_temperature_k": peak,
                        "thermally_feasible": bool(peak <= thermal_limit + 1e-7),
                    }
                )
            selected = "NO_FEASIBLE_DESIGN"
            ordered = sorted(
                candidates,
                key=lambda item: (float(item["nonthermal_objective"]), int(item["tie_break_rank"])),
            )
            by_check = {item["candidate_id"]: item for item in candidate_checks}
            for cand in ordered:
                check = by_check[cand["candidate_id"]]
                if check["thermally_feasible"]:
                    selected = cand["candidate_id"]
                    break
            witness_replays.append(
                {
                    "query_id": entry["query_id"],
                    "tuple_index": tuple_idx,
                    "suite_expected_outcome": witness_tuple.get("expected_outcome"),
                    "hotspot_selected_outcome": selected,
                    "match": bool(selected == witness_tuple.get("expected_outcome")),
                    "candidate_checks": candidate_checks,
                }
            )
    _write_json(
        output_root / "g3_independent_hotspot_witness_replay.json",
        {
            "schema_version": "certitherm.g3-independent-hotspot-replay.v1",
            "suite_artifact_sha256": artifact.get("artifact_sha256"),
            "cases": witness_replays,
            "all_match": all(case["match"] for case in witness_replays) if witness_replays else True,
            "note": "3D-ICE backend replay not executed in this environment.",
        },
    )

    print(f"Built suite: {suite_path}")
    print(f"Suite artifact: {artifact_path}")
    print(f"Suite receipt: {receipt_path}")
    print(f"Per-case receipt index: {output_root / 'g3_case_query_artifact_receipts.json'}")
    print(f"Independent HotSpot witness replay: {output_root / 'g3_independent_hotspot_witness_replay.json'}")
    print(f"G3 suite replay status: {receipt.get('status')}")
    return 0 if receipt.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
