"""Energy-conserving periodic HotSpot transient replay."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import time
from typing import Sequence, Tuple

import numpy as np

from .hotspot import HotSpotModel
from .phase_trace import PhaseTrace
from .digest import sha256_file as _sha256

# Pinned HotSpot's write_vals() serialises temperatures with two decimals, so 0.01 K is the
# finest distinction any of its output can express. Named once because both the convergence
# guard and the tie analysis depend on the same quantum.
OUTPUT_RESOLUTION_K = 0.01


def resample_uniform(
    trace: PhaseTrace, max_step_s: float
) -> Tuple[float, np.ndarray]:
    """Average a piecewise-constant phase trace into exact uniform time bins."""

    if not np.isfinite(max_step_s) or max_step_s <= 0.0:
        raise ValueError("max_step_s must be finite and positive")
    total_s = trace.total_time_s
    samples = int(np.ceil(total_s / max_step_s))
    step_s = total_s / samples
    output = np.zeros((samples, trace.dimension), dtype=float)
    phase_edges = np.concatenate(([0.0], np.cumsum(trace.durations_s)))
    bin_edges = np.linspace(0.0, total_s, samples + 1)

    phase = 0
    for sample in range(samples):
        left, right = bin_edges[sample], bin_edges[sample + 1]
        cursor = left
        while cursor < right - 1e-18:
            while phase + 1 < len(phase_edges) and phase_edges[phase + 1] <= cursor + 1e-18:
                phase += 1
            overlap_end = min(right, phase_edges[phase + 1])
            output[sample] += (
                (overlap_end - cursor) / step_s
            ) * trace.powers_w[phase]
            cursor = overlap_end
    source_j = trace.energy_j()
    resampled_j = output.sum(axis=0) * step_s
    if not np.allclose(resampled_j, source_j, rtol=1e-11, atol=1e-18):
        raise RuntimeError("uniform resampling did not conserve per-block energy")
    return step_s, output


def _write_ptrace(
    path: Path, block_ids: Sequence[str], powers_w: np.ndarray, repeats: int = 1
) -> None:
    if repeats < 1:
        raise ValueError("ptrace repeat count must be positive")
    with path.open("w", encoding="utf-8") as stream:
        stream.write("\t".join(block_ids) + "\n")
        rows = tuple(
            "\t".join(f"{value:.12g}" for value in row) + "\n"
            for row in powers_w
        )
        for _ in range(repeats):
            stream.writelines(rows)


def _parse_ttrace(path: Path, block_ids: Sequence[str]) -> np.ndarray:
    with path.open("r", encoding="utf-8") as stream:
        header = tuple(stream.readline().split())
    if header != tuple(block_ids):
        raise RuntimeError("HotSpot transient output changed the block registry")
    values = np.loadtxt(path, skiprows=1)
    values = np.atleast_2d(values)
    if values.shape[1] != len(block_ids) or not np.all(np.isfinite(values)):
        raise RuntimeError("HotSpot transient output is malformed")
    return values


def _parse_steady(path: Path, block_ids: Sequence[str]) -> np.ndarray:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        try:
            values[fields[0]] = float(fields[1])
        except ValueError:
            continue
    missing = [name for name in block_ids if name not in values]
    if missing:
        raise RuntimeError(f"HotSpot steady output misses {len(missing)} blocks")
    output = np.asarray([values[name] for name in block_ids])
    if not np.all(np.isfinite(output)):
        raise RuntimeError("HotSpot steady output contains non-finite temperature")
    return output


def _within_output_tolerance(residual_k: float, tolerance_k: float) -> bool:
    """Compare decimal HotSpot output with only a binary-roundoff allowance."""

    return residual_k <= tolerance_k + 1e-9


def _peak_and_ties(
    per_block_k: "np.ndarray", block_ids: Sequence[str], resolution_k: float
) -> tuple:
    """Return (winner index, runner-up temperature, tie set) for one temperature vector.

    The tie set is every block within one output quantum of the maximum, INCLUDING the
    winner. With a 0.01 K reported resolution, two blocks inside that band are not
    distinguishable, so a change of reported argmax between them is not evidence that a
    peak moved. The runner-up is the largest value outside the winner's own entry.
    """
    values = np.asarray(per_block_k, dtype=float).reshape(-1)
    if values.size != len(block_ids):
        raise ValueError("temperature vector does not match the block list")
    winner = int(np.argmax(values))
    peak = float(values[winner])
    # A STABLE sort, so the tie listing is reproducible and its order is documented: hottest
    # first, then block order among equal values. With an unstable sort the order among exact
    # ties is arbitrary, and exact ties are the common case here -- 11 of 15 V6.1 subsets.
    ties = tuple(
        str(block_ids[i])
        for i in np.argsort(-values, kind="stable")
        if peak - float(values[i]) <= resolution_k + 1e-9
    )
    others = np.delete(values, winner)
    runner_up = float(others.max()) if others.size else peak
    return winner, runner_up, ties


def _run_hotspot(
    *,
    binary: Path,
    config: Path,
    floorplan: Path,
    materials: Path,
    model: HotSpotModel,
    ptrace: Path,
    output: Path = None,
    steady: Path = None,
    init_file: Path = None,
    init_temp_k: float = None,
    sampling_interval_s: float = None,
    timeout_s: float = 900.0,
    role: str = "",
) -> dict:
    """Run one HotSpot process and return a record of what it did.

    Returns the role, the argv, the return code, the wall window, and the output path with its
    SHA-256 and byte size. A consumer previously had to INFER how many processes ran from the
    converged cycle count -- which hard-codes this function's doubling schedule into the
    consumer, so changing `initial_cycles` would have made a valid receipt look invalid.
    """
    command = [
        str(binary),
        "-c",
        str(config),
        "-f",
        str(floorplan),
        "-p",
        str(ptrace),
        "-materials_file",
        str(materials),
        "-model_type",
        model.model_type,
    ]
    if model.model_type == "grid":
        command += [
            "-grid_rows",
            str(model.grid_rows),
            "-grid_cols",
            str(model.grid_cols),
            "-grid_map_mode",
            model.grid_map_mode,
        ]
    if output is not None:
        command += ["-o", str(output)]
    if steady is not None:
        command += ["-steady_file", str(steady)]
    if init_file is not None:
        command += ["-init_file", str(init_file)]
    if init_temp_k is not None:
        command += ["-init_temp", f"{init_temp_k:.12g}"]
    if sampling_interval_s is not None:
        command += ["-sampling_intvl", f"{sampling_interval_s:.12g}"]
    started = time.time()
    result = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_s,
    )
    ended = time.time()
    if result.returncode:
        raise RuntimeError(
            f"HotSpot transient failed ({result.returncode}): {result.stderr[-1000:]}"
        )
    # The single file this invocation was asked to write. Recorded by name, hash and size so a
    # consumer validates the artefact set instead of re-deriving the schedule that produced it.
    produced = output if output is not None else steady
    record = {
        "role": role,
        "argv": [str(part) for part in command],
        "returncode": result.returncode,
        "started_unix": started,
        "ended_unix": ended,
        "output": produced.name if produced is not None else None,
        "output_sha256": _sha256(produced) if produced is not None else None,
        "output_bytes": produced.stat().st_size if produced is not None else None,
    }
    if produced is not None and not produced.is_file():
        raise RuntimeError(f"HotSpot returned 0 but did not write {produced}")
    return record


@dataclass(frozen=True)
class PeriodicTransientResult:
    """Raw observations from one periodic replay, plus everything derivable from them.

    The per-block temperature VECTORS are the raw observation; the peak, the argmax, the
    runner-up and the resolution-aware tie set are all properties computed from them. They
    used to be stored fields, which meant a consumer had to trust a producer-reported tie
    list -- a list that could name any block, since nothing tied it back to a temperature.
    Storing 233 floats instead makes every tie claim recomputable.
    """

    step_s: float
    samples_per_cycle: int
    cycles: int
    boundary_residual_k: float
    peak_residual_k: float
    fixed_initial_peak_k: float
    fixed_initial_hottest_block: str
    # Aligned with `block_ids`: the maximum over the converged cycle, and the time-mean steady
    # temperature, for every block.
    block_ids: tuple
    periodic_block_peaks_k: tuple
    mean_steady_block_k: tuple
    # One record per HotSpot process this replay ran: role, argv, return code, wall window, and
    # the output it wrote with that file's SHA-256 and size. Required, with no default: a
    # default would let a caller print a fabricated empty list as if nothing was recorded.
    invocations: tuple
    temperature_output_resolution_k: float = OUTPUT_RESOLUTION_K

    def _view(self, values):
        winner, runner_up, ties = _peak_and_ties(
            np.asarray(values), self.block_ids, self.temperature_output_resolution_k
        )
        return float(values[winner]), str(self.block_ids[winner]), runner_up, ties

    @property
    def hotspot_invocations(self) -> int:
        return len(self.invocations)

    @property
    def periodic_peak_k(self) -> float:
        return self._view(self.periodic_block_peaks_k)[0]

    @property
    def periodic_hottest_block(self) -> str:
        return self._view(self.periodic_block_peaks_k)[1]

    @property
    def periodic_second_peak_k(self) -> float:
        return self._view(self.periodic_block_peaks_k)[2]

    @property
    def periodic_tie_blocks(self) -> tuple:
        return self._view(self.periodic_block_peaks_k)[3]

    @property
    def periodic_top_gap_k(self) -> float:
        return self.periodic_peak_k - self.periodic_second_peak_k

    @property
    def mean_steady_peak_k(self) -> float:
        return self._view(self.mean_steady_block_k)[0]

    @property
    def mean_steady_hottest_block(self) -> str:
        return self._view(self.mean_steady_block_k)[1]

    @property
    def mean_steady_second_peak_k(self) -> float:
        return self._view(self.mean_steady_block_k)[2]

    @property
    def mean_steady_tie_blocks(self) -> tuple:
        return self._view(self.mean_steady_block_k)[3]

    @property
    def mean_steady_top_gap_k(self) -> float:
        return self.mean_steady_peak_k - self.mean_steady_second_peak_k

    def temperature_of(self, block: str) -> float:
        """The periodic temperature of one named block, for the gate's location predicate."""
        try:
            return float(self.periodic_block_peaks_k[self.block_ids.index(block)])
        except ValueError:
            raise KeyError(f"{block!r} is not in this replay's block registry")


def replay_periodic(
    *,
    binary: Path,
    config: Path,
    floorplan: Path,
    materials: Path,
    model_id: str,
    block_ids: Sequence[str],
    trace: PhaseTrace,
    workspace: Path,
    max_step_s: float,
    fixed_initial_k: float,
    tolerance_k: float = 0.01,
    initial_cycles: int = 8,
    max_cycles: int = 128,
) -> PeriodicTransientResult:
    """Replay one trace from a common fixed state and to a periodic orbit."""

    if (
        not np.isfinite(fixed_initial_k)
        or fixed_initial_k <= 0.0
        or not np.isfinite(tolerance_k)
        or tolerance_k <= 0.0
    ):
        raise ValueError("initial temperature and convergence tolerance must be positive")
    # Pinned HotSpot's write_vals() serializes transient temperatures to 0.01 K.
    # Refuse a convergence claim finer than the observable output.
    if tolerance_k < OUTPUT_RESOLUTION_K:
        raise ValueError("convergence tolerance is below HotSpot's 0.01 K output resolution")
    if initial_cycles < 2 or max_cycles < initial_cycles:
        raise ValueError("periodic replay cycle bounds are invalid")
    paths = tuple(
        Path(path).resolve() for path in (binary, config, floorplan, materials)
    )
    if any(not path.is_file() for path in paths):
        raise FileNotFoundError("HotSpot transient inputs must exist")
    workspace.mkdir(parents=True, exist_ok=True)
    model = HotSpotModel.parse(model_id)
    step_s, samples = resample_uniform(trace, max_step_s)

    invocations = []
    mean_ptrace = workspace / "mean.ptrace"
    mean_steady = workspace / "mean.steady"
    _write_ptrace(mean_ptrace, block_ids, trace.mean_power_w[None, :])
    invocations.append(_run_hotspot(
        binary=paths[0],
        config=paths[1],
        floorplan=paths[2],
        materials=paths[3],
        model=model,
        ptrace=mean_ptrace,
        steady=mean_steady,
        role="mean-steady",
    ))
    mean_temperatures = _parse_steady(mean_steady, block_ids)

    one_cycle = workspace / "one-cycle.ptrace"
    fixed_ttrace = workspace / "fixed-initial.ttrace"
    _write_ptrace(one_cycle, block_ids, samples)
    invocations.append(_run_hotspot(
        binary=paths[0],
        config=paths[1],
        floorplan=paths[2],
        materials=paths[3],
        model=model,
        ptrace=one_cycle,
        output=fixed_ttrace,
        init_temp_k=fixed_initial_k,
        sampling_interval_s=step_s,
        role="fixed-initial",
    ))
    fixed = _parse_ttrace(fixed_ttrace, block_ids)

    cycles = initial_cycles
    while True:
        periodic_ptrace = workspace / f"periodic-{cycles}.ptrace"
        periodic_ttrace = workspace / f"periodic-{cycles}.ttrace"
        _write_ptrace(periodic_ptrace, block_ids, samples, repeats=cycles)
        invocations.append(_run_hotspot(
            binary=paths[0],
            config=paths[1],
            floorplan=paths[2],
            materials=paths[3],
            model=model,
            ptrace=periodic_ptrace,
            output=periodic_ttrace,
            init_file=mean_steady,
            sampling_interval_s=step_s,
            role=f"periodic-{cycles}",
        ))
        temperatures = _parse_ttrace(periodic_ttrace, block_ids)
        expected_rows = cycles * len(samples)
        if len(temperatures) != expected_rows:
            raise RuntimeError("HotSpot transient output row count is incomplete")
        last = temperatures[-len(samples) :]
        previous = temperatures[-2 * len(samples) : -len(samples)]
        boundary_residual = float(
            np.max(
                np.abs(
                    temperatures[-1]
                    - temperatures[-len(samples) - 1]
                )
            )
        )
        peak_residual = abs(float(last.max()) - float(previous.max()))
        # Decimal ttrace values such as 0.01 can round a few ulps above their
        # registered output-resolution threshold in binary floating point.
        if _within_output_tolerance(
            max(boundary_residual, peak_residual), tolerance_k
        ):
            break
        if cycles >= max_cycles:
            raise RuntimeError(
                "periodic transient did not converge: "
                f"boundary={boundary_residual:.6g} K, peak={peak_residual:.6g} K"
            )
        cycles = min(max_cycles, cycles * 2)

    fixed_flat = int(np.argmax(fixed))
    # Per-block maximum over the converged cycle. The same winner as an argmax over the whole
    # (sample, block) matrix, but it is the vector -- not a derived label -- that gets recorded.
    periodic_per_block = np.asarray(last, dtype=float).max(axis=0)
    return PeriodicTransientResult(
        step_s=step_s,
        samples_per_cycle=len(samples),
        cycles=cycles,
        boundary_residual_k=boundary_residual,
        peak_residual_k=peak_residual,
        fixed_initial_peak_k=float(fixed.flat[fixed_flat]),
        fixed_initial_hottest_block=str(block_ids[fixed_flat % len(block_ids)]),
        block_ids=tuple(str(b) for b in block_ids),
        periodic_block_peaks_k=tuple(float(v) for v in periodic_per_block),
        mean_steady_block_k=tuple(float(v) for v in mean_temperatures),
        invocations=tuple(invocations),
        temperature_output_resolution_k=OUTPUT_RESOLUTION_K,
    )
