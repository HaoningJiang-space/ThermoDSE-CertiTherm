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
from typing import Mapping, Union

import numpy as np

from . import cache_receipts
from .cache_receipts import Sha256File
from .paths import HOTSPOT, ROOT, TEMPLATE, THERMODSE

# Registry identifiers become path components of a directory this module deletes.
_SAFE_IDENTITY = re.compile(r"[A-Za-z0-9._-]+")


def write_hotspot_config(source: Path, output: Path, package: dict[str, str]) -> None:
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
    # Registry IDs become a path component of a directory this function DELETES. A slash or a
    # `..` would place that directory outside `output/work` and hand rmtree a target nobody
    # intended -- and a registry can acquire a bad identifier by accident, so trusting it is not
    # a reason to skip the check. Peer review raised this; the containment assertion below is the
    # belt to the slug rule's braces, because a slug rule can be relaxed later.
    identity = f"{kind}--{workload['workload_id']}--{arch['architecture_id']}"
    if not _SAFE_IDENTITY.fullmatch(identity):
        raise ValueError(
            f"refusing to build a work directory named {identity!r}: registry identifiers must "
            "match [A-Za-z0-9._-]+ so they cannot escape the run's own directory"
        )
    work = (output / "work").resolve()
    sim = (work / identity).resolve()
    if sim.parent != work:
        raise ValueError(f"resolved work directory {sim} is not directly under {work}")
    if sim.exists():
        shutil.rmtree(sim)
    shutil.copytree(TEMPLATE, sim)
    write_hotspot_config(TEMPLATE / "example.config", sim / "example.config", package)
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


def build_thermodse_evaluator(
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

    import core  # type: ignore

    # `sys.path.insert(0, THERMODSE)` does not displace an already-imported `core`, so a
    # previously loaded unrelated package of that name would have this function patch the wrong
    # module -- silently, since both patches are conditional and would simply not apply. Peer
    # review raised it; the provenance is now asserted instead of assumed.
    origin = getattr(core, "__file__", None)
    if origin is None or THERMODSE not in Path(origin).resolve().parents:
        raise RuntimeError(
            f"the imported `core` package resolves to {origin}, which is not inside the pinned "
            f"ThermoDSE submodule at {THERMODSE}"
        )

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


def design_vector(row: dict[str, str]) -> list[Union[int, float]]:
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
    # Nine ints and one float, which is why the annotation is not `list[float]`: the split is
    # ThermoDSE's convention and collapsing it would change what the pinned evaluator receives.
    # `float("nan")` and `float("inf")` both parse, so finiteness is checked rather than assumed;
    # a missing key raises KeyError and a malformed number ValueError, both fail-closed already.
    vector: list[Union[int, float]] = [
        float(row[key]) if key == "interval" else int(row[key]) for key in keys
    ]
    for key, value in zip(keys, vector):
        if not np.isfinite(value):
            raise ValueError(f"design field {key}={row[key]!r} is not finite")
    return vector


def load_capture_metrics(capture: Path) -> dict[str, float]:
    with np.load(capture, allow_pickle=False) as data:
        latency = float(data["latency_ms"])
        energy = float(data["energy_mj"])
        die_yield = float(data["die_yield"])
    # `min(...) <= 0` alone lets NaN through, because every comparison with NaN is False, and
    # `hotspot_disabled` deliberately yields NaN temperatures -- so a NaN objective is reachable,
    # not hypothetical. Positive infinity passed too. Both would propagate into `edyp` and from
    # there into evidence, so finiteness is checked before sign.
    for name, value in (("latency_ms", latency), ("energy_mj", energy), ("die_yield", die_yield)):
        if not np.isfinite(value):
            raise RuntimeError(f"non-finite {name}={value} in {capture.name}")
        if value <= 0:
            raise RuntimeError(f"nonpositive {name}={value} in {capture.name}")
    return {
        "latency_ms": latency,
        "energy_mj": energy,
        "die_yield": die_yield,
        "edyp": latency * energy / die_yield,
    }


@contextmanager
def hotspot_disabled(evaluator):
    """Close BOTH of ThermoDSE's routes to HotSpot for a narrow region, and always reopen them.

    Two routes, because closing one is not enough: the floorplan generator invokes the binary,
    and `chiplet_eva.find_hotpoint` reads a temperature back. A region that closed only the first
    would still return whatever temperature happened to be lying around, so a capture that was
    meant to be non-thermal could report a stale peak as if it had been measured. The second
    route is replaced with NaN rather than a plausible number for the same reason.

    Restoration is driven off a list of what was actually mutated, and every mutation happens
    inside the `try`. Assigning both attributes before entering it left a window where the first
    could succeed and the second raise, escaping with the generator still patched and no `finally`
    to undo it -- a partial mutation leaking out of an error path. Nested use is safe: each level
    saves what it found, which may be the outer level's replacement, and restores in LIFO order.

    An unimportable `core.chiplet_eva` raises before anything is mutated, which is the right
    failure: the region cannot be made non-thermal, so it must not run.

    **Single-threaded use only, and that is a prohibition rather than a guarantee.**
    `find_hotpoint` is a module attribute, so two overlapping regions in different threads share
    it: the first to exit would reopen the readback route while the second still needs it closed,
    and a capture would silently become thermal again. Different evaluator objects do not help --
    the second route is global either way. The experiment driver isolates candidates by PROCESS,
    which is what makes this safe today; a future thread pool over captures would need a lock here
    or the region moved into the child.
    """

    from core import chiplet_eva as evaluator_module  # type: ignore

    def skip_hotspot(*_args, **_kwargs) -> None:
        return None

    def unavailable_temperature(*_args, **_kwargs) -> float:
        return float("nan")

    generator = evaluator.flp_generator
    restore: list[tuple[object, str, object]] = []
    try:
        for owner, name, replacement in (
            (generator, "run_hotspot", skip_hotspot),
            (evaluator_module, "find_hotpoint", unavailable_temperature),
        ):
            restore.append((owner, name, getattr(owner, name)))
            setattr(owner, name, replacement)
        yield
    finally:
        # Every restore is attempted, independently. A first version restored in a plain loop and
        # a test found the hole: one failing restore aborted the rest, so the route that COULD
        # have been reopened stayed closed. An error path must not be able to raise before it has
        # finished undoing what it did.
        failures: list[str] = []
        for owner, name, original in reversed(restore):
            try:
                setattr(owner, name, original)
            except Exception as exc:  # noqa: BLE001 - recorded, then reported below
                failures.append(f"{name}: {exc}")
        if failures and sys.exc_info()[0] is None:
            # Only when nothing else is propagating. Raising here while unwinding would mask the
            # real failure with its own consequence.
            raise RuntimeError(
                "ThermoDSE HotSpot routes could not be reopened: " + "; ".join(failures)
            )


def capture_thermodse_power(
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
    evaluator = build_thermodse_evaluator(arch, workload, sim)
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
