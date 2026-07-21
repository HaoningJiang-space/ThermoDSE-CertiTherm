"""Command-line entry points for reproducible operator building and synthesis."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Sequence

import numpy as np

from .core import MeasurementAction, PowerPolytope
from .gpu_hotspot import GpuHotSpotBackend
from .hotspot import build_family, load_family, save_family
from .synthesis import synthesize_minimum_observation


def _build(args: argparse.Namespace) -> None:
    if bool(args.gpu_exporter) != bool(args.gpu_solver):
        raise SystemExit("--gpu-exporter and --gpu-solver must be specified together")
    gpu_backend = (
        GpuHotSpotBackend(
            Path(args.gpu_exporter), Path(args.gpu_solver), args.gpu_device
        )
        if args.gpu_exporter
        else None
    )
    family, blocks = build_family(
        Path(args.hotspot),
        Path(args.config),
        Path(args.floorplan),
        Path(args.materials),
        args.models.split(","),
        Path(args.workspace),
        args.limit_k,
        gpu_backend=gpu_backend,
    )
    save_family(Path(args.output), family, blocks)


def _load_case(path: Path) -> tuple[PowerPolytope, Sequence[MeasurementAction]]:
    with np.load(path, allow_pickle=False) as data:
        polytope = PowerPolytope(
            data["lower_w"],
            data["upper_w"],
            data["a_eq"],
            data["b_eq"],
            data["a_ub"],
            data["b_ub"],
        )
        vectors = data["action_vectors"]
        ids = data["action_ids"].tolist()
        costs = data["action_costs"]
        tolerances = data["action_tolerances"]
    actions = tuple(
        MeasurementAction(action_id, vector, float(cost), float(tolerance))
        for action_id, vector, cost, tolerance in zip(ids, vectors, costs, tolerances)
    )
    return polytope, actions


def _synthesize(args: argparse.Namespace) -> None:
    thermal, _ = load_family(Path(args.family))
    polytope, actions = _load_case(Path(args.case))
    plan = synthesize_minimum_observation(
        polytope,
        thermal,
        actions,
        margin_k=args.margin_k,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = (
        "status",
        "selected_actions",
        "exact_cost",
        "lower_bound",
        "relaxation_bound",
        "optimality_gap",
        "iterations",
        "message",
    )
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerow(
            {
                "status": plan.status,
                "selected_actions": ",".join(plan.selected_action_ids),
                "exact_cost": plan.exact_cost,
                "lower_bound": plan.lower_bound,
                "relaxation_bound": plan.relaxation_bound,
                "optimality_gap": plan.optimality_gap,
                "iterations": plan.iterations,
                "message": plan.message,
            }
        )
    if plan.witnesses:
        np.savez_compressed(
            output.with_suffix(".witnesses.npz"),
            safe_power_w=np.stack([w.safe_power_w for w in plan.witnesses]),
            unsafe_power_w=np.stack([w.unsafe_power_w for w in plan.witnesses]),
            safe_model_id=np.asarray([w.safe_model_id for w in plan.witnesses]),
            unsafe_model_id=np.asarray([w.unsafe_model_id for w in plan.witnesses]),
            unsafe_point=np.asarray([w.unsafe_point for w in plan.witnesses]),
        )
    if plan.status == "UNRESOLVED":
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser(prog="certitherm")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-family")
    build.add_argument("--hotspot", required=True)
    build.add_argument("--config", required=True)
    build.add_argument("--floorplan", required=True)
    build.add_argument("--materials", required=True)
    build.add_argument("--models", default="block,grid64-avg,grid128-avg")
    build.add_argument("--workspace", required=True)
    build.add_argument("--limit-k", type=float, required=True)
    build.add_argument("--output", required=True)
    build.add_argument("--gpu-exporter")
    build.add_argument("--gpu-solver")
    build.add_argument("--gpu-device", type=int, default=0)
    build.set_defaults(run=_build)
    synth = sub.add_parser("synthesize")
    synth.add_argument("--family", required=True)
    synth.add_argument("--case", required=True)
    synth.add_argument("--output", required=True)
    synth.add_argument("--margin-k", type=float, default=1e-4)
    synth.set_defaults(run=_synthesize)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
