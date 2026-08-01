"""Build finer grid operators on the GPU, so the 128 -> 256 term stops being an unmeasured tail.

`docs/ROBUST_FEASIBLE_FRONTIER.md` computes the model-error band from the operators the pipeline
already had -- `block`, `grid64`, `grid128` -- and lists as an open term the discrepancy between
`grid128` and anything finer. That term is not optional: the frontier treats `grid128` as the
reference, and a reference that is itself unconverged makes every band below it a lower bound.

Building it on the CPU is what made the question expensive: one HotSpot solve per block per model,
and a `grid256` solve is roughly four times a `grid128` one. The repository already carries a CUDA
HotSpot backend for exactly this -- `build_grid_operator_gpu`, gated behind `CERTITHERM_GPU_HOTSPOT`
and pinned by a `GPU_SHA256SUMS` receipt that `_verified_binary_digest` checks before use -- and the
machine has two idle A800s. This driver uses it, one architecture at a time, so several can be run
concurrently on separate devices.

The output is a family NPZ in the same format `load_family` reads, so the frontier probe consumes it
without knowing how it was produced.

## Why the receipt check matters here

The GPU and CPU paths must produce the same operator or the band measures the backend rather than
the grid. `GpuSelection` exists because the environment used to be read at five independent points,
so a cache signature could describe a CPU build while a GPU produced the operator. This driver takes
one snapshot and passes it down, and refuses to run if the binaries do not match their receipt.

NON-CLAIM diagnostic. Writes one family NPZ.

Usage (on moe-server, from the repo root):
    CERTITHERM_GPU_HOTSPOT=1 CERTITHERM_GPU_DEVICE=0 \\
    .venv/bin/python research/triangle/robustness/fine_operator.py <work-dir> <capture.npz> \\
        <out.npz> [models]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.experiments import GpuSelection, ROOT, _gpu_backend, _power_space, _rows
from CertiTherm.thermodse_bridge import write_hotspot_config as _configure
from CertiTherm.frozen_limits import THERMAL_LIMIT_K
from CertiTherm.hotspot import build_family, save_family
from CertiTherm.paths import HOTSPOT, TEMPLATE


def main() -> None:
    work = Path(sys.argv[1])
    capture = Path(sys.argv[2])
    out_path = Path(sys.argv[3])
    models = tuple((sys.argv[4] if len(sys.argv) > 4 else "grid256-avg").split(","))
    package_id = sys.argv[5] if len(sys.argv) > 5 else "default"

    # The pipeline's own `work/` directory is not kept alongside the operators, so the config is
    # rebuilt HERE THROUGH THE SAME FUNCTION rather than hand-copied. `write_hotspot_config` is
    # deterministic in the package row, so the rebuilt file is identical by construction; a copied
    # one only looks safer, and would silently pair this operator with a different package if the
    # wrong directory were reached for.
    packages = {row["package_id"]: row for row in _rows(ROOT / "experiments" / "packages.tsv")}
    if package_id not in packages:
        raise SystemExit(f"unknown package {package_id!r}; have {sorted(packages)}")
    work.mkdir(parents=True, exist_ok=True)
    config = work / "package.config"
    _configure(TEMPLATE / "example.config", config, packages[package_id])

    _space, blocks, _placed, floorplan_text = _power_space(capture)
    floorplan = work / "floorplan.flp"
    floorplan.write_text(floorplan_text, encoding="utf-8")

    gpu = GpuSelection.from_environment()
    backend = _gpu_backend(gpu)
    if backend is None:
        print(
            "CERTITHERM_GPU_HOTSPOT is not 1, so this will run on the CPU and take roughly four "
            "times as long per doubling of the grid",
            flush=True,
        )
    started = time.monotonic()
    family, built_blocks = build_family(
        HOTSPOT, config, floorplan, TEMPLATE / "example.materials",
        models, work / "fine-impulses", THERMAL_LIMIT_K, gpu_backend=backend,
    )
    if tuple(built_blocks) != tuple(blocks):
        raise SystemExit(
            "the fine operator resolves a different block set than the capture; a cross-grid band "
            "between different block sets is a difference between different quantities"
        )
    save_family(out_path, family, built_blocks)
    print(
        "%s: %s over %d blocks in %.0f s on %s -> %s"
        % (
            capture.stem, ",".join(models), len(built_blocks), time.monotonic() - started,
            f"GPU device {gpu.device}" if backend is not None else "CPU", out_path,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
