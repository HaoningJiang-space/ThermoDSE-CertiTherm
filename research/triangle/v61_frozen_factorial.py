"""V6.1 factorial from ONE frozen capture, with runtime provenance and an automatic gate.

Replaces `v61_factorial.sh`, whose evidence contract had five defects. All five are fixed
here, and each fix exists because the shell version's artifacts could only be graded
DIAGNOSTIC:

1. FIFTEEN INDEPENDENT CAPTURES. The shell driver invoked `complete_trace_probe.py` once per
   subset, so ThermoDSE ran 15 times and each run rewrote the shared floorplan and sim
   workspace. Here `capture_frozen_inputs()` runs ONCE and every subset is lowered from the
   same frozen objects, so the hazard is removed structurally rather than checked for.

2. CONCURRENCY RACE ON SHARED PATHS. Two drivers were run against one output directory,
   both rewriting `complete_floorplan_*.flp` and `work/capture--*`. Final hashes agreed and
   subset powers were exactly the sum of singletons, but no report recorded the hashes read
   AT RUN TIME, so a race could not be excluded. Every run now writes into its own directory
   and records the hash of every input as it reads it.

3. REUSE ON DIRECTORY EXISTENCE. `if [ -d "$DEST" ]` accepted partial, crashed or stale
   output. Reuse now requires a complete report whose recorded commit, dirty state, input
   hashes, model, step and component set all match the request.

4. NO GATE. The full-set row must reproduce the registered counterexample or no summary is
   emitted at all.

5. NO MACHINE-READABLE MANIFEST, and 25 reports of three different kinds were archived
   together. One manifest is written naming every row, its role, and its provenance.

Registered counterexample this must reproduce (docs/V6_PHYSICAL_TRACE_GATE.md):
Transformer/arch_b, grid64-max, ~0.5 us -> mean-steady 329.904867 K, periodic 330.19 K,
both at mtxu_16.

NON-CLAIM diagnostic until it has run from a clean revision in an isolated workspace.

Usage:
    python research/triangle/v61_frozen_factorial.py <out> [model] [step_us] [workload] [arch]
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.experiments import HOTSPOT, THERMAL_LIMIT_K
from CertiTherm.routed_trace import COMPONENTS, lower_routed_trace
from CertiTherm.transient import replay_periodic
from research.triangle.complete_trace_probe import capture_frozen_inputs
# One copy of the rules that decide evidence, shared with the renderer. The driver used to
# carry its own `classify` and `subset_tag`; they agreed by luck, and the gate's own decision
# did NOT agree with them.
from research.triangle.v61_contract import OUTPUT_RESOLUTION_K
from research.triangle.v61_contract import classify as _classify
from research.triangle.v61_contract import positional_script_argument as _argument
from research.triangle.v61_contract import subset_tag as _subset_tag

# Positional run parameters. `module_name=__name__` is what keeps these at their defaults on
# import: before it, `pytest -q CertiTherm/tests` bound MODEL to "CertiTherm/tests", and
# `pytest -q CertiTherm/tests -k anything` made `float(sys.argv[3])` raise during collection
# and took the whole suite down with it.
OUT = _argument(1, Path("artifacts/v61frozen"), Path, module_name=__name__)
MODEL = _argument(2, "grid64-max", module_name=__name__)
STEP_US = _argument(3, 0.5, float, module_name=__name__)
WORKLOAD = _argument(4, "transformer", module_name=__name__)
ARCH = _argument(5, "arch_b", module_name=__name__)
AMBIENT_K = 318.15

# The gate is registered for a COMPLETE tuple, not just a model. Applying it to any
# grid64-max run would compare a different workload/architecture against these values.
REGISTRATION_PATH = Path(__file__).resolve().parents[2] / \
    "docs/registration/v61_grid64_counterexample.json"
_REG = json.loads(REGISTRATION_PATH.read_text())
REGISTRATION_ID = _REG["registration_id"]
REGISTRATION_SHA256 = hashlib.sha256(REGISTRATION_PATH.read_bytes()).hexdigest()

# The registered tuple is READ from the pinned registration, not re-typed here: two copies of
# one fact drift, and a test is a weaker guarantee than not having a second copy.
#
# The gate binds NAMES and TEMPERATURES only. It deliberately does NOT bind a canonical trace
# or input hash, because none was ever preregistered: the registered values in
# docs/V6_PHYSICAL_TRACE_GATE.md were produced before this pipeline existed and no hash of that
# run's inputs survives. So the gate verifies THE PHENOMENON -- that this pipeline reproduces
# the documented crossing at a location indistinguishable from the documented one -- and NOT
# that the underlying registry, power trace or routing are unchanged. Closing that requires
# preregistering canonical_trace_sha256 from a run that is itself claim-grade: an open gap.
GATE = _REG["registered_tuple"]
# 3 added the per-row execution receipt and argmax tie evidence.
# 4 records the RAW per-block temperature vectors instead of derived tie scalars, one record
#   per HotSpot invocation instead of a count, and stops serialising interpretations the
#   consumer recomputes anyway (row_status, coalitions, leave-one-out, margins, top gaps).
# 5 retains the raw HotSpot outputs as one bundle outside the repository and records its hash,
#   size and member count, so the temperatures can be independently reparsed at all.
SCHEMA_VERSION = 5
# Versioned separately from the data schema, because "what fields does this manifest have" and
# "what predicate admitted it" are different questions with different audit trails.
# 2 replaces exact argmax equality -- which depended on how an exact tie was broken -- with
#   the registered block being indistinguishable from the maximum at the output resolution.
# 3 binds the physical instance: the staged inputs, the binary, the floorplan block registry,
#   every subset's power-trace hash and the source energy decomposition must all match the
#   canonical instance. Until now a changed registry under the same names would have passed.
GATE_POLICY_VERSION = 3
NO_REUSE = os.environ.get("V61_ALLOW_REUSE", "0") != "1"


def _plain(value):
    """Convert NumPy scalars/arrays deliberately. `default=str` would silently turn an
    unsupported numeric into a string, which is how a number becomes unusable evidence."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return _plain(value.tolist())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"refusing to serialise {type(value).__name__} into evidence")


def write_json(path: Path, payload) -> None:
    """Atomic write: a truncated manifest must never look like a complete one."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_plain(payload), indent=2), encoding="utf-8")
    tmp.replace(path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage_inputs(paths: dict, staging: Path) -> tuple:
    """Copy every input into an immutable staging area and hash the STAGED bytes.

    Hashing the live files once before up to 15 replays leaves a TOCTOU window: any of them
    could change after the hash and before or during a replay, and the hashes are not even an
    atomic snapshot of each other. Replays consume these copies instead, so what was hashed
    is exactly what was read.
    """
    staging.mkdir(parents=True, exist_ok=True)
    staged, hashes = {}, {}
    for name, src in paths.items():
        dst = staging / f"{name}{Path(src).suffix}"
        shutil.copy2(src, dst)
        # Data is read-only so accidents become errors; an EXECUTABLE must stay executable.
        # A uniform 0o444 here made the staged HotSpot binary unrunnable, which would have
        # killed the first replay with Permission denied.
        executable = os.access(src, os.X_OK)
        os.chmod(dst, 0o555 if executable else 0o444)
        if executable and not os.access(dst, os.X_OK):
            raise RuntimeError(f"staged executable {name} is not executable")
        staged[name] = dst
        hashes[name] = sha256(dst)
    return staged, hashes


def verify_staged(staged: dict, hashes: dict) -> None:
    """Re-hash the staged inputs; any change invalidates every row already produced."""
    for name, path in staged.items():
        now = sha256(path)
        if now != hashes[name]:
            raise RuntimeError(
                f"staged input {name} changed during the run ({hashes[name][:12]} -> "
                f"{now[:12]}); every row in this run is void")


def git_state():
    """Commit plus dirty state. Return codes are CHECKED: a failing git call previously
    yielded an empty commit and a clean-looking tree."""
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if head.returncode != 0 or dirty.returncode != 0 or not head.stdout.strip():
        raise RuntimeError("git provenance unavailable; refusing to produce evidence")
    lines = [l for l in dirty.stdout.splitlines() if l.strip()]
    # For a dirty tree, hash the actual diff and untracked contents: identical filenames can
    # hold different code, so the path list alone is not a provenance key.
    diff = subprocess.run(["git", "diff", "HEAD"], capture_output=True, text=True)
    diff_sha = hashlib.sha256(diff.stdout.encode()).hexdigest() if lines else None
    return head.stdout.strip(), lines, diff_sha


def subset_tag(sub) -> str:
    return _subset_tag(sub, COMPONENTS)


def reusable(dest: Path, want: dict) -> bool:
    """Reuse only a COMPLETE report whose provenance matches the request.

    Directory existence is not evidence: a crashed run leaves a directory, and a stale one
    leaves a report computed from different inputs.
    """
    report = dest / "v61_row.json"
    if not report.is_file():
        return False
    try:
        got = json.loads(report.read_text())
    except Exception:
        return False
    if not got.get("complete"):
        return False
    keys = ("schema_version", "commit", "dirty", "diff_sha256", "workload", "arch",
            "model", "max_step_us", "components", "input_hashes", "hotspot_sha256",
            "ambient_k", "tolerance_k", "io_aspect_ratio", "trace_sha256")
    if not all(got.get(k) == want.get(k) for k in keys):
        return False
    # A matching fingerprint is not enough: the stored RESULT must also be usable.
    for f in ("mean_steady_peak_k", "periodic_peak_k", "step_s", "boundary_residual_k",
              "peak_residual_k"):
        v = got.get(f)
        if not isinstance(v, (int, float)) or not np.isfinite(v):
            return False
    if got.get("cycles", 0) < 2:
        return False
    # A row without an execution receipt cannot support the fresh-execution statement the
    # manifest makes about it, so it is not reusable even if every number matches.
    ex = got.get("execution") or {}
    if not isinstance(ex, dict) or not isinstance(ex.get("invocations"), list):
        return False
    # mean-steady + fixed-initial + at least one periodic attempt.
    if len(ex["invocations"]) < 3 or not ex.get("workspace_files"):
        return False
    # The raw observation, not just its summary: a row whose vectors are missing cannot have
    # its tie set or its location predicate recomputed.
    for f in ("block_ids", "periodic_block_peaks_k", "mean_steady_block_k"):
        if not isinstance(got.get(f), list) or not got[f]:
            return False
    return True


def main() -> None:
    run_started = time.time()
    commit, dirty, diff_sha = git_state()
    # One nonce for the whole run, stamped into every row receipt and into the manifest, so a
    # row cannot silently belong to a different execution than the manifest that reports it.
    run_nonce = f"{commit[:8]}-{MODEL}-{STEP_US:g}us-{int(run_started)}"
    if OUT.exists() and any(OUT.iterdir()) and NO_REUSE:
        print(f"FAIL: {OUT} already exists and is non-empty. A claim-grade run must start in "
              f"a NEW workspace so no row can be inherited; set V61_ALLOW_REUSE=1 only for a "
              f"deliberate diagnostic continuation.")
        sys.exit(2)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"### commit={commit[:8]} dirty={len(dirty)} model={MODEL} "
          f"step={STEP_US}us {WORKLOAD}/{ARCH} ###")
    if dirty:
        print(f"  WARNING: {len(dirty)} dirty file(s); this run is DIAGNOSTIC, not "
              f"claim-grade. Claim-grade requires a clean committed revision.")

    # ---- ONE capture, frozen ------------------------------------------------------
    frozen = capture_frozen_inputs(OUT / "capture", WORKLOAD, ARCH, 1.0)
    sim = frozen["sim"]
    flp = OUT / "capture" / f"frozen_floorplan_{WORKLOAD}_{ARCH}.flp"
    flp.write_text(frozen["augmented"].text, encoding="utf-8")
    staged, input_hashes = stage_inputs({
        "floorplan": flp,
        "config": Path(sim) / "example.config",
        "materials": Path(sim) / "example.materials",
        "hotspot": Path(HOTSPOT),
    }, OUT / "staged")
    hotspot_sha = input_hashes["hotspot"]
    print(f"  frozen capture: {frozen['core'].trace.n_phases} phases, "
          f"{len(frozen['augmented'].block_ids)} blocks, {len(frozen['events'])} events")
    for k, v in input_hashes.items():
        print(f"    {k:11s} {v[:16]}...  (staged read-only)")

    # ---- lower every non-empty subset from the SAME frozen objects ---------------
    subsets = [sub for k in range(1, len(COMPONENTS) + 1)
               for sub in itertools.combinations(COMPONENTS, k)]
    rows, singles = {}, {}
    for sub in subsets:
        routed = lower_routed_trace(
            frozen["core"], floorplan=frozen["augmented"], events=frozen["events"],
            compute_shape=frozen["shape"], chiplet_cuts=frozen["cuts"],
            noc_hop_cost_pj=frozen["noc_hop_cost_pj"],
            nop_hop_cost_pj=frozen["nop_hop_cost_pj"],
            batch_factor=frozen["batch_factor"], components=sub)
        rows[sub] = routed
        if len(sub) == 1:
            singles[sub[0]] = routed.trace.powers_w

    # ---- the identity that retroactively validated the previous artifacts --------
    # Codified rather than assumed: with one frozen capture it should be exact by
    # construction, so any deviation means the masking itself is wrong.
    # An exact-zero threshold would be wrong: production accumulates core first and then
    # per-edge deposits in EVENT order, while this check sums 2-4 whole arrays, so the two
    # associations can differ by an ULP even when the mask is a pure deposition gate. The
    # bound is derived from the magnitude actually present, not chosen as a decimal epsilon.
    worst, bound = 0.0, 0.0
    for sub, routed in rows.items():
        if len(sub) < 2:
            continue
        expected = sum(singles[name] for name in sub)
        worst = max(worst, float(np.abs(routed.trace.powers_w - expected).max()))
        scale = float(np.abs(expected).max())
        bound = max(bound, len(sub) * np.spacing(scale) if scale else 0.0)
    print(f"  superposition identity (subset == sum of singletons): worst {worst:.3e} W, "
          f"ULP bound {bound:.3e} W")
    if worst > bound:
        print("FAIL: masked subsets exceed the ULP bound on the sum of their singletons; "
              "the mask is not a pure deposition gate"); sys.exit(3)

    # ---- replay each row into its OWN directory ---------------------------------
    manifest = {"commit": commit, "dirty": dirty, "model": MODEL,
                "max_step_us": STEP_US, "workload": WORKLOAD, "arch": ARCH,
                "input_hashes": input_hashes, "hotspot_sha256": hotspot_sha,
                "thermal_limit_k": THERMAL_LIMIT_K, "ambient_k": AMBIENT_K,
                "superposition_worst_w": worst,
                "component_energy_j": dict(rows[tuple(COMPONENTS)].component_energy_j),
                "full_source_energy_j": rows[tuple(COMPONENTS)].full_source_energy_j,
                "rows": {}}
    for sub in subsets:
        tag = subset_tag(sub)
        dest = OUT / f"row_{tag}_{MODEL}_{STEP_US:g}us"
        tr = rows[sub].trace
        trace_sha = hashlib.sha256(
            np.ascontiguousarray(tr.durations_s).tobytes()
            + np.ascontiguousarray(tr.powers_w).tobytes()
            + "\n".join(frozen["augmented"].block_ids).encode()).hexdigest()
        want = {"schema_version": SCHEMA_VERSION, "commit": commit, "dirty": dirty,
                "diff_sha256": diff_sha, "workload": WORKLOAD, "arch": ARCH,
                "model": MODEL, "max_step_us": STEP_US, "components": list(sub),
                "input_hashes": input_hashes, "hotspot_sha256": hotspot_sha,
                "ambient_k": AMBIENT_K, "tolerance_k": OUTPUT_RESOLUTION_K,
                "io_aspect_ratio": 1.0,
                "trace_sha256": trace_sha}
        if reusable(dest, want):
            row = json.loads((dest / "v61_row.json").read_text())
            print(f"  {tag:22s} reused (provenance verified)")
        else:
            # Pre-run proof that nothing was inherited: record whether the row directory and
            # its HotSpot workspace existed BEFORE this row ran. An exactly-reproduced number
            # cannot distinguish a fresh solver run from a reused one, so the receipt has to
            # come from the process, not from the result.
            existed_before = dest.exists()
            workspace_before = sorted(p.name for p in (dest / "hotspot").glob("*")
                                      if p.is_file()) if (dest / "hotspot").is_dir() else []
            dest.mkdir(parents=True, exist_ok=True)
            started = time.time()
            r = replay_periodic(
                binary=staged["hotspot"], config=staged["config"],
                floorplan=staged["floorplan"],
                materials=staged["materials"], model_id=MODEL,
                block_ids=frozen["augmented"].block_ids, trace=rows[sub].trace,
                workspace=dest / "hotspot", max_step_s=STEP_US * 1e-6,
                fixed_initial_k=AMBIENT_K, tolerance_k=OUTPUT_RESOLUTION_K)
            ended = time.time()
            raw = sorted(p for p in (dest / "hotspot").glob("*") if p.is_file())
            row = dict(want)
            row.update({
                "execution": {
                    # Pre-run proof that nothing was inherited. An exactly reproduced number
                    # cannot distinguish a fresh solver run from a reused one, so the receipt
                    # has to come from the process, not from the result.
                    "dest_existed_before_run": bool(existed_before),
                    "workspace_files_before_run": workspace_before,
                    "started_unix": started, "ended_unix": ended,
                    "wall_s": ended - started, "pid": os.getpid(),
                    "run_nonce": run_nonce,
                    # One record per HotSpot process: role, argv, return code, wall window, and
                    # the output it wrote with that file's sha256 and byte size. A consumer no
                    # longer has to INFER the process count from the converged cycle count --
                    # an inference that hard-coded replay_periodic's doubling schedule.
                    "invocations": [dict(rec) for rec in r.invocations],
                    # Every file in the workspace, including the .ptrace inputs the driver
                    # wrote. Kept separate from the per-invocation outputs above, because
                    # counting all of them as "HotSpot outputs" was wrong.
                    "workspace_files": {p.name: sha256(p) for p in raw},
                },
                # The RAW observation. The peak, the argmax, the runner-up and the tie set are
                # all derivable from these, and a consumer that recomputes them does not have
                # to trust a producer-reported tie list that nothing tied to a temperature.
                "block_ids": list(r.block_ids),
                "periodic_block_peaks_k": list(r.periodic_block_peaks_k),
                "mean_steady_block_k": list(r.mean_steady_block_k),
                "retained_source_energy_j": rows[sub].source_energy_j,
                # Scalars kept for readability. Validated against the vectors above, so they
                # cannot disagree with the observation they summarise.
                "mean_steady_peak_k": r.mean_steady_peak_k,
                "mean_steady_hottest_block": r.mean_steady_hottest_block,
                "periodic_peak_k": r.periodic_peak_k,
                "periodic_hottest_block": r.periodic_hottest_block,
                "fixed_initial_peak_k": r.fixed_initial_peak_k,
                "cycles": r.cycles, "step_s": r.step_s,
                "samples_per_cycle": r.samples_per_cycle,
                "boundary_residual_k": r.boundary_residual_k,
                "peak_residual_k": r.peak_residual_k,
                "output_resolution_k": r.temperature_output_resolution_k,
                "complete": True,
            })
            # Any change to a staged input voids every row, so check after each replay too.
            verify_staged(staged, input_hashes)
            write_json(dest / "v61_row.json", row)
            print(f"  {tag:22s} steady {row['mean_steady_peak_k']:.6f} K  periodic "
                  f"{row['periodic_peak_k']:.2f} K  at {row['periodic_hottest_block']:11s} "
                  f"cyc={row['cycles']} hs={r.hotspot_invocations} "
                  f"files={len(raw)} gap={r.periodic_top_gap_k:.2f}K "
                  f"ties={len(r.periodic_tie_blocks)}")
        manifest["rows"][tag] = row

    # ---- GATE: the full row must reproduce the registered counterexample ---------
    full = manifest["rows"]["full"]
    registered = (WORKLOAD == GATE["workload"] and ARCH == GATE["arch"]
                  and MODEL == GATE["model"] and STEP_US == GATE["max_step_us"]
                  and AMBIENT_K == GATE["ambient_k"])
    if registered:
        res = full["output_resolution_k"]
        steady_delta = abs(full["mean_steady_peak_k"] - GATE["mean_steady_peak_k"])
        # The DECISION uses the same quantisation-aware rule as every row. It used to be a bare
        # `periodic >= limit`, so a full row at exactly the limit could pass a gate that the
        # classification calls undecidable.
        decision_ok = (full["mean_steady_peak_k"] < THERMAL_LIMIT_K
                       and _classify(full["periodic_peak_k"], THERMAL_LIMIT_K, res) == "crossing")
        value_ok = abs(full["periodic_peak_k"] - GATE["periodic_peak_k"]) <= res + 1e-9
        # LOCATION, from temperatures rather than from a label. Exact argmax equality made the
        # gate depend on how an exact tie was broken -- and 11 of 15 rows are exact ties, so a
        # refactor of the argmax flipped one label with every temperature unchanged. The
        # defensible predicate is that the registered block cannot be distinguished from the
        # maximum at HotSpot's output resolution. It is compatibility, NOT spatial reproduction.
        registered_block_k = full["periodic_block_peaks_k"][
            full["block_ids"].index(GATE["hottest"])] if GATE["hottest"] in full["block_ids"] \
            else None
        location_compatible = (registered_block_k is not None
                               and 0.0 <= full["periodic_peak_k"] - registered_block_k
                               <= res + 1e-9)
        argmax_equals = full["periodic_hottest_block"] == GATE["hottest"]
        ok = decision_ok and value_ok and location_compatible
        manifest["gate"] = {
            "registered_tuple": GATE,
            "registration_id": REGISTRATION_ID,
            "registration_sha256": REGISTRATION_SHA256,
            # Versioned separately from the data schema: "what fields does this manifest have"
            # and "what predicate admitted it" are different questions.
            "gate_policy_version": GATE_POLICY_VERSION,
            "passed": bool(ok),
            "registered_block_periodic_k": registered_block_k,
            "location_compatible_at_resolution": bool(location_compatible),
            "argmax_equals": bool(argmax_equals),
            "steady_delta_k": steady_delta,
            "steady_gated": False,
            "steady_gate_note": "no repeatability-derived tolerance exists; reported, "
                                "not enforced",
        }
        print(f"\n  GATE (registered tuple): {'PASS' if ok else 'FAIL'}")
        print(f"    decision  steady<330 and periodic>=330 : {decision_ok}")
        print(f"    value     periodic {full['periodic_peak_k']:.2f} vs registered "
              f"{GATE['periodic_peak_k']:.2f} K (+/-{res}) : {value_ok}")
        print(f"    location  registered {GATE['hottest']} at "
              f"{registered_block_k if registered_block_k is None else round(registered_block_k, 2)} K "
              f"vs peak {full['periodic_peak_k']:.2f} K (<= {res} K) : {location_compatible}"
              f"   [argmax_equals={argmax_equals}, not gated]")
        print(f"    steady delta {steady_delta:.6f} K (reported, NOT gated)")
        if not ok:
            # summary is NULL, not a string. A consumer that merely checks for the key
            # would otherwise read a failure as a success -- which is exactly the wrong
            # judgement I previously described as a guarantee.
            manifest["summary"] = None
            manifest["suppression_reason"] = (
                "the gate did not reproduce the registered counterexample, so no row may "
                "be read")
            manifest["complete"] = False
            write_json(OUT / "v61_manifest.json", manifest)
            print("  GATE FAILED: summary is null, complete=false. Read NO row.")
            sys.exit(4)
    else:
        manifest["gate"] = {"registered_tuple": GATE, "passed": None,
                            "note": f"UNGATED EXPLORATORY RUN: {WORKLOAD}/{ARCH}/{MODEL}/"
                                    f"{STEP_US}us does not match the registered tuple, so "
                                    f"there is no counterexample to reproduce. Results are "
                                    f"not comparable with the registered case."}
        print(f"\n  UNGATED EXPLORATORY RUN: {WORKLOAD}/{ARCH}/{MODEL}/{STEP_US}us is not "
              f"the registered tuple. No gate applies and no registered comparison is made.")

    # ---- console reporting: derived HERE for the log, and deliberately NOT serialised ----
    # The manifest used to store row_status, indeterminate_rows, crossing_subsets,
    # minimal_crossing_coalitions, leave_one_out and uplift_k. The consumer recomputes all of
    # them from the rows anyway, so serialising them created two representations of one fact and
    # a policing problem: the renderer had to compare its recomputation against a stored copy it
    # could not trust. Rows are the authority; interpretations are the consumer's job.
    def classify(row):
        return _classify(row["periodic_peak_k"], THERMAL_LIMIT_K, row["output_resolution_k"])
    status = {subset_tag(sub): classify(manifest["rows"][subset_tag(sub)]) for sub in subsets}
    indet = [t for t, v in status.items() if v == "indeterminate"]
    if indet:
        print(f"  NOTE: {len(indet)} row(s) sit within one {OUTPUT_RESOLUTION_K} K quantum of "
              f"the limit and are INDETERMINATE: {indet}")
    crossing = {frozenset(sub) for sub in subsets if status[subset_tag(sub)] == "crossing"}
    minimal = sorted(("+".join(sorted(c)) for c in crossing
                      if not any(o < c for o in crossing)), key=len)
    loo = {drop: manifest["rows"][subset_tag(tuple(c for c in COMPONENTS if c != drop))]
           for drop in COMPONENTS}

    # Freshness is a CONJUNCTION, not a nonce match. Nonce equality alone would call a row
    # fresh that had inherited a populated workspace.
    def is_fresh(r) -> bool:
        ex = r.get("execution") or {}
        return (ex.get("run_nonce") == run_nonce
                and ex.get("dest_existed_before_run") is False
                and not ex.get("workspace_files_before_run")
                and bool(ex.get("invocations"))
                and run_started <= ex.get("started_unix", 0)
                <= ex.get("ended_unix", 0) <= time.time())

    manifest["summary"] = {
        # The only summary fields left are ones no consumer can derive from the rows.
        "all_rows_fresh": all(is_fresh(r) for r in manifest["rows"].values()),
        "reuse_disabled_by_policy": bool(NO_REUSE),
        "source_identity_effect_on_uplift": "UNTESTED",
        "scope": ("Conditional necessity is bounded to THIS fixed trace, fixed routing and "
                  "timing, an additive deposition intervention, and the HotSpot model. It is "
                  "not general physical causality and says nothing about temperature-"
                  "dependent power feedback."),
    }
    print(f"\n  minimal crossing coalitions: {minimal or '(none)'}")
    for drop, row in loo.items():
        st = classify(row)
        print(f"    full-minus-{drop:5s} periodic {row['periodic_peak_k']:.2f} K -> "
              f"{'BELOW' if st == 'below' else st.upper()}  (delta "
              f"{manifest['rows']['full']['periodic_peak_k'] - row['periodic_peak_k']:+.2f} K)")
    # ---- retain the raw HotSpot outputs as ONE bundle, outside the repository -------------
    # Hashes without bytes cannot be reparsed by anyone. The bundle is not committed: measured
    # at 14.3 MB gzipped for 353 MB of ttrace/steady text, against a 1.1 MB repository pack.
    bundle_path = OUT / "v61_hotspot_outputs.tar.gz"
    produced = sorted(p for tag in manifest["rows"]
                      for p in (OUT / f"row_{tag}_{MODEL}_{STEP_US:g}us" / "hotspot").glob("*")
                      if p.is_file() and p.suffix != ".ptrace")
    with tarfile.open(bundle_path, "w:gz") as bundle:
        for path in produced:
            bundle.add(path, arcname=str(path.relative_to(OUT)))
    manifest["raw_output_bundle"] = {
        "path": str(bundle_path), "sha256": sha256(bundle_path),
        "bytes": bundle_path.stat().st_size, "members": len(produced),
        "uncompressed_bytes": sum(p.stat().st_size for p in produced),
        "in_repository": False,
        "note": ("Retained so the temperatures can be independently reparsed. Lives on the "
                 "run host's data volume, which is shared and periodically cleaned -- the hash "
                 "identifies the bytes, it does not guarantee they still exist."),
    }
    print(f"\n  raw output bundle: {len(produced)} files, "
          f"{bundle_path.stat().st_size/1e6:.1f} MB gzipped from "
          f"{sum(p.stat().st_size for p in produced)/1e6:.1f} MB, sha "
          f"{manifest['raw_output_bundle']['sha256'][:12]}")

    manifest["run"] = {
        "run_id": run_nonce,
        "started_unix": run_started, "ended_unix": time.time(),
        "host": platform.node(), "platform": platform.platform(),
        "python": platform.python_version(), "numpy": np.__version__,
        "argv": list(sys.argv), "schema_version": SCHEMA_VERSION,
        "staged_inputs": {k: str(v) for k, v in staged.items()},
    }
    # Re-verify provenance at the END: recording only the start state would miss a commit
    # or working-tree change made while the run was in flight.
    end_commit, end_dirty, end_diff = git_state()
    manifest["provenance_end"] = {"commit": end_commit, "dirty": end_dirty,
                                  "diff_sha256": end_diff}
    stable = (end_commit == commit and end_dirty == dirty and end_diff == diff_sha)
    manifest["provenance_stable"] = bool(stable)
    verify_staged(staged, input_hashes)          # and the inputs one final time
    if not stable:
        manifest["summary"] = None
        manifest["suppression_reason"] = (
            f"git state changed during the run ({commit[:8]}/{len(dirty)} dirty -> "
            f"{end_commit[:8]}/{len(end_dirty)} dirty); rows are not attributable to one "
            f"revision")
        manifest["complete"] = False
        write_json(OUT / "v61_manifest.json", manifest)
        print("  PROVENANCE CHANGED MID-RUN: summary is null, complete=false.")
        sys.exit(5)
    manifest["complete"] = True
    write_json(OUT / "v61_manifest.json", manifest)
    print(f"\n  wrote {OUT / 'v61_manifest.json'}  (complete=true, "
          f"gate.passed={manifest['gate'].get('passed')})")
    print("  A CONSUMER MUST CHECK complete is true AND gate.passed is true. Neither alone "
          "is sufficient.")
    print("  Conclusions are bounded to THIS candidate, threshold, HotSpot model and "
          "discretisation. No independent signoff model has validated them.")


if __name__ == "__main__":
    main()
