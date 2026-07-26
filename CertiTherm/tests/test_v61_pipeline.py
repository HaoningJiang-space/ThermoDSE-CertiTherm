"""Tests for the V6.1 factorial pipeline's evidence contract.

These did not exist, which is why two CERTAIN-crash defects passed a 322/322 run: the
launch used a `nohup PYTHONPATH=. ...` prefix that nohup cannot parse, and `stage_inputs`
chmod'ed every staged file to 0o444 including the HotSpot binary that is then executed.
A suite that never imports or exercises the pipeline cannot support it.

Each test below corresponds to a defect that actually shipped.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from research.triangle import v61_frozen_factorial as F


# --- stage_inputs: the permission defect --------------------------------------------

def test_staged_executable_stays_executable(tmp_path):
    """The shipped bug: a uniform 0o444 made the staged HotSpot binary unrunnable, so the
    first replay would have died with Permission denied."""
    exe = tmp_path / "fakebin"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    data = tmp_path / "cfg.config"
    data.write_text("k v\n", encoding="utf-8")

    staged, hashes = F.stage_inputs({"hotspot": exe, "config": data}, tmp_path / "staged")
    assert os.access(staged["hotspot"], os.X_OK), "staged executable must remain executable"
    assert not os.access(staged["config"], os.W_OK), "staged data must be read-only"
    assert not os.access(staged["hotspot"], os.W_OK), "staged executable must not be writable"
    assert set(hashes) == {"hotspot", "config"}


def test_staged_executable_actually_runs(tmp_path):
    """Stronger than the permission bit: the staged copy must be executable in practice."""
    exe = tmp_path / "fakebin"
    exe.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    exe.chmod(0o755)
    staged, _ = F.stage_inputs({"hotspot": exe}, tmp_path / "staged")
    assert subprocess.run([str(staged["hotspot"])]).returncode == 7


def test_staged_hashes_are_of_the_staged_bytes(tmp_path):
    """Hashing the live file would leave a TOCTOU window; the hash must describe the copy."""
    src = tmp_path / "d.config"
    src.write_text("original\n", encoding="utf-8")
    staged, hashes = F.stage_inputs({"config": src}, tmp_path / "staged")
    src.write_text("mutated after staging\n", encoding="utf-8")     # live file changes
    F.verify_staged(staged, hashes)                                 # staged copy unaffected
    assert F.sha256(staged["config"]) == hashes["config"]


def test_verify_staged_fails_closed_when_a_staged_input_changes(tmp_path):
    src = tmp_path / "d.config"
    src.write_text("a\n", encoding="utf-8")
    staged, hashes = F.stage_inputs({"config": src}, tmp_path / "staged")
    os.chmod(staged["config"], 0o644)
    staged["config"].write_text("b\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="changed during the run"):
        F.verify_staged(staged, hashes)


# --- the launch defect --------------------------------------------------------------

def test_nohup_cannot_parse_an_assignment_prefix():
    """Pins the actual shipped failure. `nohup PYTHONPATH=. cmd` is not a valid launch;
    the env prefix must go through `env`. The run silently produced no process at all."""
    bad = subprocess.run("nohup PYTHONPATH=. true 2>&1", shell=True,
                         capture_output=True, text=True)
    assert "failed to run command" in (bad.stdout + bad.stderr)
    good = subprocess.run("nohup env PYTHONPATH=. true 2>&1", shell=True,
                          capture_output=True, text=True)
    assert "failed to run command" not in (good.stdout + good.stderr)


def test_module_is_importable_with_repo_root_on_the_path():
    """A smoke check that the entry point resolves at all, which the missing suite skipped."""
    assert callable(F.main) and callable(F.stage_inputs)
    assert F.SCHEMA_VERSION >= 2
    assert F.NO_REUSE is True, "claim-grade runs must not inherit rows by default"


# --- the gate's fail-closed contract ------------------------------------------------

def test_gate_declares_that_it_does_not_bind_the_registered_instance():
    """The gate checks names and temperatures only. It must SAY so, because a changed
    registry under the same workload/arch names would otherwise pass silently."""
    assert F.GATE["binds_instance_hashes"] is False
    assert F.GATE["canonical_trace_sha256"] is None
    for key in ("workload", "arch", "model", "max_step_us", "ambient_k"):
        assert key in F.GATE, "the gate must key on the complete registered tuple"


def test_gate_steady_tolerance_is_not_invented():
    """1e-6 K was invented and must gate nothing.

    An earlier version of this test grepped the source for "1e-6" and failed on
    `max_step_s = STEP_US * 1e-6`, a microsecond-to-second conversion with nothing to do
    with tolerances. Assert on BEHAVIOUR: the gate carries no steady tolerance, and the
    steady value is reported rather than enforced.
    """
    assert F.GATE["steady_tolerance_k"] is None
    src = (ROOT / "research/triangle/v61_frozen_factorial.py").read_text()
    # the steady value must be reported, and explicitly marked as not enforced
    assert '"steady_gated": False' in src
    assert "steady_delta_k" in src
    # and no comparison may gate it
    assert "mean_steady_peak_k\"] - GATE[\"mean_steady_peak_k\"]) <= " not in src


# --- reuse validation ---------------------------------------------------------------

def _want():
    return {"schema_version": F.SCHEMA_VERSION, "commit": "c" * 40, "dirty": [],
            "diff_sha256": None, "workload": "transformer", "arch": "arch_b",
            "model": "grid64-max", "max_step_us": 0.5, "components": ["core"],
            "input_hashes": {"config": "h"}, "hotspot_sha256": "hs",
            "ambient_k": 318.15, "tolerance_k": 0.01, "io_aspect_ratio": 1.0,
            "trace_sha256": "t"}


def _row(**over):
    row = dict(_want())
    row.update(complete=True, mean_steady_peak_k=329.9, periodic_peak_k=330.19,
               step_s=5e-7, boundary_residual_k=0.01, peak_residual_k=0.0, cycles=16)
    row.update(over)
    return row


@pytest.mark.parametrize("over,reason", [
    ({"complete": False}, "incomplete row"),
    ({"mean_steady_peak_k": float("nan")}, "non-finite result"),
    ({"cycles": 1}, "unconverged"),
    ({"commit": "d" * 40}, "different commit"),
    ({"trace_sha256": "other"}, "different trace"),
    ({"schema_version": 1}, "older schema"),
    ({"input_hashes": {"config": "other"}}, "different input"),
])
def test_reuse_is_refused_for(tmp_path, over, reason):
    (tmp_path / "v61_row.json").write_text(json.dumps(_row(**over)))
    assert not F.reusable(tmp_path, _want()), f"must refuse to reuse: {reason}"


def test_a_matching_row_without_process_evidence_is_no_longer_reusable(tmp_path):
    """Under schema 3 a complete, fingerprint-matching row is still refused if it carries no
    execution receipt: the numbers alone cannot show the solver ran. The positive case is
    `test_reuse_is_accepted_for_a_row_with_an_execution_receipt` below."""
    (tmp_path / "v61_row.json").write_text(json.dumps(_row()))
    assert not F.reusable(tmp_path, _want())


def test_reuse_is_refused_when_the_row_is_unreadable(tmp_path):
    (tmp_path / "v61_row.json").write_text("{ not json")
    assert not F.reusable(tmp_path, _want())


# --- serialisation must not launder a value -----------------------------------------

def test_serialisation_converts_numpy_and_refuses_the_unknown():
    assert F._plain(np.float64(2.5)) == 2.5
    assert isinstance(F._plain(np.float64(2.5)), float)
    assert F._plain(np.array([1.0, 2.0])) == [1.0, 2.0]
    assert F._plain({"p": Path("/x")}) == {"p": "/x"}
    with pytest.raises(TypeError, match="refusing to serialise"):
        F._plain(object())


def test_manifest_write_is_atomic(tmp_path):
    dest = tmp_path / "m.json"
    F.write_json(dest, {"a": np.float64(1.0)})
    assert json.loads(dest.read_text()) == {"a": 1.0}
    assert not list(tmp_path.glob("*.tmp")), "no temporary file may survive"


# --- import safety: module-level argv parsing ---------------------------------------

def test_importing_the_probe_does_not_reinterpret_the_callers_argv():
    """The shipped crash: complete_trace_probe parsed sys.argv at module level, so importing
    it from the factorial driver made `float(sys.argv[4])` read the driver's workload name
    and die with "could not convert string to float: 'transformer'". Import must be free of
    argv side effects."""
    import importlib
    saved = sys.argv
    try:
        sys.argv = ["driver", "out", "grid64-max", "0.5", "transformer", "arch_b"]
        mod = importlib.import_module("research.triangle.complete_trace_probe")
        importlib.reload(mod)                     # re-execute module level under this argv
        assert mod.IO_ASPECT_RATIO == 1.0, "must keep its default, not parse the caller's argv"
        assert mod.WORKLOAD == "resnet50"
        assert mod.COMPONENTS is None
        assert callable(mod.capture_frozen_inputs)
    finally:
        sys.argv = saved


# --- schema 4: the reuse fingerprint must require the raw observation ------------------
# `all_rows_fresh` once echoed the NO_REUSE module constant, so it asserted the driver's
# intention and proved nothing. Under schema 4 a row is reusable only if it carries the raw
# per-block vectors and one record per HotSpot invocation.

def test_schema_and_gate_policy_are_versioned_separately():
    """"What fields does this manifest have" and "what predicate admitted it" are different
    questions: gate policy 2 replaced exact argmax equality with resolution compatibility
    without changing a single field."""
    assert F.SCHEMA_VERSION == 4
    assert F.GATE_POLICY_VERSION == 2


def _v4_row(**over):
    row = _row()
    row.update(
        schema_version=F.SCHEMA_VERSION,
        block_ids=["blk_0", "mtxu_16"],
        periodic_block_peaks_k=[329.0, 330.19],
        mean_steady_block_k=[329.0, 329.9],
        execution={"dest_existed_before_run": False,
                   "workspace_files_before_run": [],
                   "started_unix": 1.0, "ended_unix": 2.0, "wall_s": 1.0,
                   "pid": 123, "run_nonce": "n",
                   "invocations": [{"role": "mean-steady"}, {"role": "fixed-initial"},
                                   {"role": "periodic-8"}, {"role": "periodic-16"}],
                   "workspace_files": {"mean.steady": "h1", "periodic-16.ttrace": "h2"}})
    row.update(over)
    return row


def test_reuse_is_accepted_for_a_row_with_receipts_and_vectors(tmp_path):
    (tmp_path / "v61_row.json").write_text(json.dumps(_v4_row()))
    assert F.reusable(tmp_path, _want())


@pytest.mark.parametrize("over,reason", [
    ({"execution": None}, "no receipt at all"),
    ({"execution": {}}, "empty receipt"),
    ({"execution": dict(_v4_row()["execution"], invocations=[{"role": "mean-steady"}])},
     "too few invocations for one replay"),
    ({"execution": dict(_v4_row()["execution"], invocations="four")},
     "invocations is not a list"),
    ({"execution": dict(_v4_row()["execution"], workspace_files={})},
     "no workspace file hashed"),
    ({"periodic_block_peaks_k": []}, "no periodic temperature vector"),
    ({"block_ids": None}, "no block registry"),
    ({"mean_steady_block_k": None}, "no steady temperature vector"),
])
def test_reuse_is_refused_without_the_raw_observation(tmp_path, over, reason):
    (tmp_path / "v61_row.json").write_text(json.dumps(_v4_row(**over)))
    assert not F.reusable(tmp_path, _want()), f"must refuse to reuse: {reason}"


# --- one copy of the rules that decide evidence ---------------------------------------

def test_the_driver_and_the_renderer_share_one_classification_rule():
    """They each carried their own `classify`. The copies agreed by luck; the gate's own
    decision agreed with neither, which is how a row at exactly the limit could pass a gate
    that classification calls undecidable."""
    from research.triangle import v61_contract as C
    assert F._classify is C.classify
    assert F.subset_tag(F.COMPONENTS) == C.subset_tag(F.COMPONENTS, F.COMPONENTS) == "full"
    src = (ROOT / "research/triangle/v61_frozen_factorial.py").read_text()
    assert 'return "crossing"' not in src, "the driver must not keep a second classifier"


def test_the_output_quantum_is_not_a_bare_literal_in_the_driver():
    from research.triangle import v61_contract as C
    src = (ROOT / "research/triangle/v61_frozen_factorial.py").read_text()
    assert 'tolerance_k": 0.01' not in src and "tolerance_k=0.01" not in src
    assert F.GATE["tolerance_k"] == C.OUTPUT_RESOLUTION_K


def test_the_shared_quantum_comes_from_the_transient_engine():
    """Not a third independent constant: the convergence guard and the classification must be
    unable to disagree."""
    from research.triangle import v61_contract as C
    from CertiTherm.transient import OUTPUT_RESOLUTION_K
    assert C.OUTPUT_RESOLUTION_K is OUTPUT_RESOLUTION_K
