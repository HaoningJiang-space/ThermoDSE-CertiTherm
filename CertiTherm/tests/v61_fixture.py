"""A SYNTHETIC schema-4 V6.1 manifest, for testing the validator only.

Not evidence, and never rendered into a document that claims anything. It exists because the
validator has to be exercised against every branch BEFORE a 66-minute claim-grade run is spent,
and a real manifest can only be produced by that run. Temperatures here are invented.

The shape is faithful: real component names would make it tempting to read numbers off it, so
the components are `a`/`b`/`c`, but the registered tuple (workload, architecture, model, step,
ambient, limit, and the registered block name) has to be the real one or `validate_gate` will
correctly refuse to apply the gate at all.
"""
from __future__ import annotations

import hashlib
import json
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRATION = ROOT / "docs/registration/v61_grid64_counterexample.json"

BLOCKS = ["blk_0", "mtxu_16", "blk_2", "blk_3", "blk_4"]
COMPONENTS = ["a", "b", "c"]
ENERGY = {"a": 0.010, "b": 0.005, "c": 0.002}
SCHEMA, GATE_POLICY = 5, 3
LIMIT, AMBIENT, QUANTUM = 330.0, 318.15, 0.01
RUN_T0 = 1_700_000_000.0

# tag -> (periodic peak, steady peak, cycles). Built so that: the full set is the only crossing
# row; every leave-one-out row clears the excess by more than one quantum; and no row is
# indeterminate.
# Leave-one-out removal deltas from the full row: dropping `a` costs 1.19 K, `b` 0.69 K and
# `c` 0.29 K -- all more than the +0.19 K excess plus one 0.01 K quantum, so the arithmetic
# branch of the leave-one-out prose is the one under test.
PEAKS = {
    "a": (326.50, 326.20, 8),
    "b": (321.00, 320.85, 8),
    "c": (320.40, 320.30, 8),
    "b-c": (329.00, 328.70, 16),      # full minus a
    "a-c": (329.50, 329.20, 16),      # full minus b
    "a-b": (329.90, 329.60, 16),      # full minus c
    "full": (330.19, 329.904867, 16),
}


def _tag(components):
    return "full" if set(components) == set(COMPONENTS) else "-".join(sorted(components))


def _vector(peak: float, hottest_index: int, gap: float = 0.02):
    """A temperature vector whose maximum is `peak` at `hottest_index`."""
    values = [peak - gap - 0.5 * i for i in range(len(BLOCKS))]
    values[hottest_index] = peak
    return values


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _subsets():
    out = []
    for k in range(1, len(COMPONENTS) + 1):
        out.extend(combinations(COMPONENTS, k))
    return out


def canonical_instance(m: dict) -> dict:
    """The canonical instance THIS fixture describes.

    Gate policy 3 binds the physical instance, and the committed registration pins the real
    233-block one. A synthetic manifest can only be validated against a synthetic canonical
    instance, so tests monkeypatch the registration with `registration(m)`.
    """
    full = m["rows"]["full"]
    return {
        "why": "synthetic", "provenance": "synthetic fixture; not evidence",
        "canonicalised_from": {"run_id": m["run"]["run_id"], "commit": m["commit"],
                               "manifest": "synthetic", "schema_version": SCHEMA},
        "input_hashes": dict(m["input_hashes"]),
        "hotspot_sha256": m["hotspot_sha256"],
        "block_registry_sha256": hashlib.sha256(
            "\n".join(full["block_ids"]).encode()).hexdigest(),
        "block_count": len(full["block_ids"]),
        "trace_sha256_by_subset": {t: r["trace_sha256"] for t, r in sorted(m["rows"].items())},
        "output_resolution_k": full["output_resolution_k"],
        "component_energy_j": dict(m["component_energy_j"]),
    }


def registration(m: dict) -> dict:
    """The pinned registration a synthetic manifest must be validated against."""
    reg = json.loads(REGISTRATION.read_text())
    reg["registered_tuple"] = dict(m["gate"]["registered_tuple"])
    reg["canonical_instance"] = canonical_instance(m)
    return reg


def manifest(commit: str = "c" * 40) -> dict:
    reg = json.loads(REGISTRATION.read_text())
    tuple_ = dict(reg["registered_tuple"])
    hotspot = _h("hotspot-binary")
    inputs = {"config": _h("config"), "floorplan": _h("floorplan"),
              "materials": _h("materials"), "hotspot": hotspot}
    run_id = f"{commit[:8]}-grid64-max-0.5us-{int(RUN_T0)}"
    rows, t = {}, RUN_T0 + 1
    for i, sub in enumerate(_subsets()):
        tag = _tag(sub)
        periodic, steady, cycles = PEAKS[tag]
        started, ended = t, t + 10.0
        t = ended + 1
        attempts = [8] if cycles == 8 else [8, 16]
        invocations = []
        for j, (role, out) in enumerate(
                [("mean-steady", "mean.steady"), ("fixed-initial", "fixed-initial.ttrace")]
                + [(f"periodic-{n}", f"periodic-{n}.ttrace") for n in attempts]):
            invocations.append({
                "role": role,
                "argv": ["/staged/hotspot", "-c", "/staged/config", "-p", f"/w/{tag}.ptrace"],
                "returncode": 0,
                "started_unix": started + j, "ended_unix": started + j + 0.5,
                "output": out, "output_sha256": _h(f"{tag}:{out}"),
                "output_bytes": 1024 * (j + 1),
            })
        workspace = {rec["output"]: rec["output_sha256"] for rec in invocations}
        workspace.update({"mean.ptrace": _h(f"{tag}:mean.ptrace"),
                          "one-cycle.ptrace": _h(f"{tag}:one-cycle.ptrace")})
        for n in attempts:
            workspace[f"periodic-{n}.ptrace"] = _h(f"{tag}:periodic-{n}.ptrace")
        rows[tag] = {
            "schema_version": SCHEMA, "commit": commit, "dirty": [], "diff_sha256": None,
            "workload": tuple_["workload"], "arch": tuple_["arch"], "model": tuple_["model"],
            "max_step_us": tuple_["max_step_us"], "components": list(sub),
            "input_hashes": inputs, "hotspot_sha256": hotspot,
            "ambient_k": AMBIENT, "tolerance_k": QUANTUM,
            "io_aspect_ratio": tuple_["io_aspect_ratio"],
            "trace_sha256": _h(f"trace:{tag}"),
            "execution": {
                "dest_existed_before_run": False, "workspace_files_before_run": [],
                "started_unix": started, "ended_unix": ended, "wall_s": ended - started,
                "pid": 4242, "run_nonce": run_id,
                "invocations": invocations, "workspace_files": workspace,
            },
            "block_ids": list(BLOCKS),
            "periodic_block_peaks_k": _vector(periodic, BLOCKS.index(tuple_["hottest"])),
            "mean_steady_block_k": _vector(steady, BLOCKS.index(tuple_["hottest"])),
            "retained_source_energy_j": sum(ENERGY[c] for c in sub),
            "mean_steady_peak_k": steady, "mean_steady_hottest_block": tuple_["hottest"],
            "periodic_peak_k": periodic, "periodic_hottest_block": tuple_["hottest"],
            "fixed_initial_peak_k": AMBIENT + 2.0,
            "cycles": cycles, "step_s": 4.99e-7, "samples_per_cycle": 811,
            "boundary_residual_k": QUANTUM, "peak_residual_k": 0.0,
            "output_resolution_k": QUANTUM,
            "complete": True,
        }
    full = rows["full"]
    tuple_["binds_instance_hashes"] = True
    tuple_["canonical_trace_sha256"] = full["trace_sha256"]
    tuple_["canonical_input_hashes"] = dict(inputs)
    return {
        "commit": commit, "dirty": [], "model": tuple_["model"],
        "max_step_us": tuple_["max_step_us"], "workload": tuple_["workload"],
        "arch": tuple_["arch"], "input_hashes": inputs, "hotspot_sha256": hotspot,
        "thermal_limit_k": LIMIT, "ambient_k": AMBIENT,
        "superposition_worst_w": 0.0,
        "component_energy_j": dict(ENERGY),
        "full_source_energy_j": sum(ENERGY.values()),
        "rows": rows,
        "gate": {
            "registered_tuple": tuple_,
            "registration_id": reg["registration_id"],
            "registration_sha256": hashlib.sha256(REGISTRATION.read_bytes()).hexdigest(),
            "gate_policy_version": GATE_POLICY,
            "passed": True,
            "registered_block_periodic_k": full["periodic_peak_k"],
            "location_compatible_at_resolution": True,
            "argmax_equals": True,
            "steady_delta_k": abs(full["mean_steady_peak_k"] - tuple_["mean_steady_peak_k"]),
            "steady_gated": False,
            "steady_gate_note": "no repeatability-derived tolerance exists; reported, "
                                "not enforced",
        },
        "summary": {
            "all_rows_fresh": True, "reuse_disabled_by_policy": True,
            "source_identity_effect_on_uplift": "UNTESTED",
            "scope": "Synthetic fixture. Bounded to nothing; not evidence.",
        },
        "run": {
            "run_id": run_id, "started_unix": RUN_T0, "ended_unix": t + 10,
            "host": "fixture", "platform": "synthetic", "python": "3.8.10", "numpy": "1.24.4",
            "argv": ["fixture"], "schema_version": SCHEMA,
            "staged_inputs": {k: f"/staged/{k}" for k in inputs},
        },
        "raw_output_bundle": {
            "path": "/data/run/v61_hotspot_outputs.tar.gz", "sha256": _h("bundle"),
            "bytes": 4096, "members": sum(
                len([i for i in r["execution"]["invocations"]]) for r in rows.values()),
            "uncompressed_bytes": 40960, "in_repository": False,
            "note": "synthetic",
        },
        "provenance_end": {"commit": commit, "dirty": [], "diff_sha256": None},
        "provenance_stable": True,
        "complete": True,
    }


def set_peak(row: dict, semantics: str, peak: float, hottest_index: int = None,
             gap: float = 0.02) -> None:
    """Move one row's peak, keeping the vector and the stored scalars consistent.

    Tests that mutate only the vector, or only the scalar, trip the "stored scalar disagrees
    with its own vector" check first and therefore do not test what they claim to. Five did.
    """
    if hottest_index is None:
        hottest_index = BLOCKS.index(
            json.loads(REGISTRATION.read_text())["registered_tuple"]["hottest"])
    row[f"{semantics}_block_peaks_k" if semantics == "periodic"
        else "mean_steady_block_k"] = _vector(peak, hottest_index, gap)
    row[f"{semantics}_peak_k"] = peak
    row[f"{semantics}_hottest_block"] = BLOCKS[hottest_index]
