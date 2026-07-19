"""Independent witness replay for G3 suite artifacts.

Backends:
1. hotspot (built-in)
2. 3d-ice via external adapter script (optional)

The adapter is a user-provided executable that must accept:
  --config <config>
  --floorplan <output_3D.flp>
  --ptrace <witness.ptrace>
  --materials <example.materials>
  --steady-out <output steady file>
and return exit code 0 on success.
"""

from __future__ import annotations

import argparse
import json
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

from core.chiplet_eva import chiplet_evaluator  # type: ignore  # noqa: E402


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _flp_units(path: Path) -> list[str]:
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        parts = text.split()
        if len(parts) >= 5:
            names.append(parts[0])
    if not names:
        raise RuntimeError(f"no floorplan units found in {path}")
    return names


def _write_ptrace(path: Path, header: list[str], values: np.ndarray) -> None:
    with path.open("w", encoding="utf-8") as stream:
        stream.write("\t".join(header) + "\n")
        stream.write("\t".join(f"{float(v):.10f}" for v in values.tolist()) + "\n")


def _parse_steady(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            try:
                out[parts[0]] = float(parts[1])
            except ValueError:
                pass
    if not out:
        raise RuntimeError(f"steady output empty: {path}")
    return out


def _run_hotspot(
    hotspot_bin: Path,
    config: Path,
    floorplan: Path,
    ptrace: Path,
    materials: Path,
    steady_out: Path,
) -> None:
    cmd = [
        str(hotspot_bin),
        "-c",
        str(config),
        "-f",
        str(floorplan),
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
        raise RuntimeError("HotSpot produced no steady file")


def _run_3dice_adapter(
    adapter: Path,
    config: Path,
    floorplan: Path,
    ptrace: Path,
    materials: Path,
    steady_out: Path,
) -> None:
    cmd = [
        str(adapter),
        "--config",
        str(config),
        "--floorplan",
        str(floorplan),
        "--ptrace",
        str(ptrace),
        "--materials",
        str(materials),
        "--steady-out",
        str(steady_out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"3D-ICE adapter failed ({result.returncode}): {result.stderr[-400:]}")
    if not steady_out.is_file():
        raise RuntimeError("3D-ICE adapter produced no steady file")


def _replay_backend(
    backend: str,
    hotspot_bin: Path,
    adapter: Path | None,
    suite_artifact: dict[str, Any],
    package_cfgs: dict[str, Path],
    workspace: Path,
) -> dict[str, Any]:
    cases = []
    for entry in suite_artifact["entries"]:
        spatial = entry["variants"]["spatial_equivalence"]["result"]
        if spatial.get("status") != "NON_IDENTIFIABLE":
            continue
        package_id = entry["package_id"]
        cfg = package_cfgs[package_id]
        candidates = entry["variants"]["spatial_equivalence"]["inputs"]["candidates"]
        by_id = {c["candidate_id"]: c for c in candidates}
        thermal_limit = float(spatial["thermal_limit_k"])
        for tuple_index, witness_tuple in enumerate(spatial.get("witness_tuples", [])):
            candidate_checks = []
            for record in witness_tuple["candidates"]:
                candidate_id = record["candidate_id"]
                cand = by_id[candidate_id]
                power = np.asarray(record["power_w"], dtype=np.float64)
                block_names = list(cand["block_names"])
                sys_info = list(cand["sys_info"])

                sim_dir = workspace / backend / f"{entry['query_id']}_{tuple_index}_{candidate_id}"
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

                floorplan = sim_dir / "floorplan" / "output_3D.flp"
                flp_names = _flp_units(floorplan)
                power_map = dict(zip(block_names, power.tolist()))
                run_blocks = [name for name in flp_names if name in power_map]
                if not run_blocks:
                    raise RuntimeError("no overlapping blocks for witness replay")
                run_values = np.asarray([power_map[name] for name in run_blocks], dtype=np.float64)

                ptrace = sim_dir / "ptrace" / "witness.ptrace"
                _write_ptrace(ptrace, run_blocks, run_values)
                steady = sim_dir / "outputs" / f"{backend}.steady"
                if backend == "hotspot":
                    _run_hotspot(
                        hotspot_bin=hotspot_bin,
                        config=sim_dir / "example.config",
                        floorplan=floorplan,
                        ptrace=ptrace,
                        materials=sim_dir / "example.materials",
                        steady_out=steady,
                    )
                else:
                    if adapter is None:
                        raise RuntimeError("3D-ICE adapter path is required")
                    _run_3dice_adapter(
                        adapter=adapter,
                        config=sim_dir / "example.config",
                        floorplan=floorplan,
                        ptrace=ptrace,
                        materials=sim_dir / "example.materials",
                        steady_out=steady,
                    )
                temps = _parse_steady(steady)
                peak = max(temps.values())
                candidate_checks.append(
                    {
                        "candidate_id": candidate_id,
                        "peak_temperature_k": float(peak),
                        "thermally_feasible": bool(peak <= thermal_limit + 1e-7),
                    }
                )

            ordered = sorted(
                candidates, key=lambda item: (float(item["nonthermal_objective"]), int(item["tie_break_rank"]))
            )
            by_check = {item["candidate_id"]: item for item in candidate_checks}
            selected = "NO_FEASIBLE_DESIGN"
            for cand in ordered:
                if by_check[cand["candidate_id"]]["thermally_feasible"]:
                    selected = cand["candidate_id"]
                    break
            expected = witness_tuple.get("expected_outcome")
            cases.append(
                {
                    "query_id": entry["query_id"],
                    "tuple_index": tuple_index,
                    "suite_expected_outcome": expected,
                    "backend_selected_outcome": selected,
                    "match": bool(selected == expected),
                    "candidate_checks": candidate_checks,
                }
            )

    return {
        "backend": backend,
        "cases": cases,
        "all_match": all(item["match"] for item in cases) if cases else True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent replay for G3 witness tuples")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument(
        "--bundle-root",
        type=Path,
        default=REPO_ROOT / "CertiTherm" / "evidence" / "g3_2x2x2_real_bundle",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=THERMODSE_ROOT / "tmp_independent_replay",
    )
    parser.add_argument(
        "--hotspot-bin",
        type=Path,
        default=REPO_ROOT / "HotSpot" / "hotspot",
    )
    parser.add_argument(
        "--three-d-ice-adapter",
        type=Path,
        help="Executable adapter for 3D-ICE replay.",
    )
    args = parser.parse_args()

    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    package_cfgs = {
        "standard_sink_s06": args.bundle_root / "configs" / "standard_sink_s06.config",
        "enhanced_sink_s10": args.bundle_root / "configs" / "enhanced_sink_s10.config",
    }
    for path in package_cfgs.values():
        if not path.is_file():
            raise SystemExit(f"missing package config: {path}")

    report: dict[str, Any] = {
        "schema_version": "certitherm.g3-independent-thermal-replay.v1",
        "suite_artifact_sha256": artifact.get("artifact_sha256"),
        "backends": {},
    }

    hotspot_ok = args.hotspot_bin.is_file()
    if hotspot_ok:
        report["backends"]["hotspot"] = _replay_backend(
            backend="hotspot",
            hotspot_bin=args.hotspot_bin.resolve(),
            adapter=None,
            suite_artifact=artifact,
            package_cfgs=package_cfgs,
            workspace=args.workspace_root.resolve(),
        )
    else:
        report["backends"]["hotspot"] = {
            "status": "UNRESOLVED",
            "reason": f"missing hotspot binary: {args.hotspot_bin}",
        }

    if args.three_d_ice_adapter and args.three_d_ice_adapter.is_file():
        report["backends"]["3d-ice"] = _replay_backend(
            backend="3d-ice",
            hotspot_bin=args.hotspot_bin.resolve(),
            adapter=args.three_d_ice_adapter.resolve(),
            suite_artifact=artifact,
            package_cfgs=package_cfgs,
            workspace=args.workspace_root.resolve(),
        )
    else:
        report["backends"]["3d-ice"] = {
            "status": "UNRESOLVED",
            "reason": "3D-ICE adapter not provided or not executable",
        }

    _write_json(args.output.resolve(), report)
    print(f"Wrote independent replay report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

