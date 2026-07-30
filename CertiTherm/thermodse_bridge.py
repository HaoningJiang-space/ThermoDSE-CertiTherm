"""Everything that talks to the pinned ThermoDSE submodule, and nothing that decides anything.

ThermoDSE is a frozen dependency here: it supplies architecture candidates and a power map, and
this repository never modifies it. But reaching it is awkward -- its scripts `sys.path.append('..')`
and must run from inside their own directory, its HotSpot template was never committed, and its
evaluator reaches HotSpot by two separate routes that a capture has to close off. All of that
awkwardness is collected here so the driver does not carry it.

Two rules this module keeps:

* **It never decides what a capture's identity is.** `capture` receives an already-computed cache
  signature. The driver owns that -- architecture, workload, package, submodule revision -- and
  computing it here would mean importing the driver and closing a cycle.
* **It never disables HotSpot silently.** `hotspot_disabled` closes both of ThermoDSE's routes to
  HotSpot for a named region and restores them, so a capture that was supposed to be thermal
  cannot quietly produce a stale temperature.

`design_vector` is ThermoDSE's ten-element convention, in its order:
`[chiplet_x, chiplet_y, cut_x, cut_y, interval, mtxu_h, mtxu_w, ubuf, nop_bw, dram_bw]`. Upstream
duplicates that ordering in four optimizers; it exists once here.

Layer position: depends on the `cache_receipts` and `paths` modules and on nothing else in this
package. Do not add an import of `experiments`.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re
import shlex
import shutil
import sys
from typing import Mapping

import numpy as np

from . import cache_receipts
from .cache_receipts import Sha256File
from .paths import HOTSPOT, ROOT, TEMPLATE, THERMODSE


def apply_cli_options(source: Path, output: Path, package: dict[str, str]) -> None:
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


def prepare_simulation_dir(
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
    apply_cli_options(TEMPLATE / "example.config", sim / "example.config", package)
    if allow_hotspot:
        runner = ROOT / "CertiTherm" / "trace_runner.py"
        # --allow-unplaced is a DECLARED BOUNDARY, not a convenience. ThermoDSE emits an
        # `interposer` column holding all NoP power and no floorplan unit is named
        # `interposer`, so name alignment cannot place it: 10.90% of the dissipated energy
        # does not reach HotSpot. That was silent until `align_trace` was made fail-closed;
        # passing the flag here keeps the existing pipeline's boundary UNCHANGED while making
        # it visible in every run log, instead of relaxing the check for future work.
        # See docs/THERMODSE_ENDPOINT_AUDIT.md; removing the omission means placing NoP
        # power on real floorplan units, which changes the frozen thermal inputs.
        wrapper = (
            "#!/bin/sh\nexec "
            + shlex.quote(sys.executable)
            + " "
            + shlex.quote(str(runner))
            + ' "$@" --allow-unplaced --hotspot '
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


def build_evaluator(
    arch: dict[str, str],
    workload: dict[str, str],
    sim: Path,
    *,
    physical_nop: bool = False,
):
    """Build the pinned evaluator after installing narrow API shims."""

    thermodse_path = str(THERMODSE)
    if thermodse_path not in sys.path:
        sys.path.insert(0, thermodse_path)
    from core.chiplet_eva import chiplet_evaluator  # type: ignore

    install_compatibility_layer()
    if physical_nop:
        from .physical_nop import install_physical_nop

        install_physical_nop()

    evaluator = chiplet_evaluator(
        hotspot_path=str(HOTSPOT.parent),
        sim_path=str(sim),
        sys_info=design_vector(arch),
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


def install_compatibility_layer() -> None:
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

    # The pinned breadth-first traversal omits external inputs from its
    # initially satisfied dependency set. Recurrent networks therefore stall
    # even though Network itself explicitly supports external layers.
    original_traverse = Network.traverese_layer
    if not getattr(original_traverse, "_certitherm_handles_external", False):
        def traverse_with_external_inputs(self, check=False) -> None:
            self.layer_idx_bfs = type(self.layer_dict)()
            finished = {self.INPUT_LAYER_KEY, *self.ext_layers()}
            pending = [
                name for name in self.layer_dict if name != self.INPUT_LAYER_KEY
            ]
            depth = 0
            while pending:
                ready = []
                for name in pending:
                    dependencies = tuple(self.ifm_prevs_dict[name])
                    if self.wgt_prevs_dict[name] is not None:
                        dependencies += tuple(self.wgt_prevs_dict[name])
                    if all(dependency in finished for dependency in dependencies):
                        ready.append(name)
                if not ready:
                    raise RuntimeError(
                        "ThermoDSE network contains cyclic or unresolved dependencies: "
                        + ", ".join(pending)
                    )
                self.layer_idx_bfs[depth] = ready
                if check:
                    print(f"Depth {depth}: {ready}")
                finished.update(ready)
                pending = [name for name in pending if name not in finished]
                depth += 1
            self.depth = depth

        traverse_with_external_inputs._certitherm_handles_external = True  # type: ignore[attr-defined]
        Network.traverese_layer = traverse_with_external_inputs  # type: ignore[assignment]


def design_vector(row: dict[str, str]) -> list[float]:
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


def capture_metrics(capture: Path) -> dict[str, float]:
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


@contextmanager
def hotspot_disabled(evaluator):
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


def capture(
    arch: dict[str, str],
    workload: dict[str, str],
    package: dict[str, str],
    output: Path,
    *,
    signature: Mapping[str, str],
    sha256_file: Sha256File,
) -> Path:
    """Produce (or reuse) one frozen ThermoDSE power capture.

    `signature` arrives already computed rather than being built here. The driver owns what a
    capture's identity depends on -- architecture, workload, package, submodule revision -- and
    computing it here would make this module import the driver, closing a cycle. `sha256_file` is
    injected for the same reason `cache_receipts` injects it: it is the seam the tests replace.
    """

    capture = output / "captures" / f"{workload['workload_id']}--{arch['architecture_id']}.npz"
    if cache_receipts.receipt_matches(capture, signature, sha256_file=sha256_file):
        return capture
    capture.unlink(missing_ok=True)
    cache_receipts.receipt_path(capture).unlink(missing_ok=True)
    sim = prepare_simulation_dir(
        arch,
        workload,
        package,
        output,
        allow_hotspot=True,
    )
    evaluator = build_evaluator(arch, workload, sim)
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
    cache_receipts.write_receipt(capture, signature, sha256_file=sha256_file)
    return capture
