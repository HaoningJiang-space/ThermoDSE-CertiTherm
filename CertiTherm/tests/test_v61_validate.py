"""The validator must recompute, not trust, and must refuse rather than raise.

Four generations of this code each trusted something it should have derived:

1. two booleans (`complete`, `gate.passed`) were checked and `summary.row_status`,
   `minimal_crossing_coalitions` and `leave_one_out` were printed verbatim;
2. those were recomputed, but the manifest's own `decision_ok`/`value_ok`/`location_ok` were
   still printed, and convergence was never validated at all -- a 16-cycle row with a 10 K
   residual passed;
3. the gate was recomputed but its location test was exact argmax equality, which depends on how
   an exact tie is broken, and most rows here are exact ties;
4. the tie set itself was producer-reported -- a list that could name any block, since nothing
   in it was tied to a temperature.

Schema 4 stores the per-block temperature VECTORS, so peaks, argmaxes, runners-up and tie sets
are all derived here. Each test below pins one refusal.

The fixture is synthetic (`v61_fixture.py`) and clearly labelled as such: a real schema-4
manifest can only come from a 66-minute claim-grade run, and the point of these tests is to be
sure of the validator BEFORE that run is spent.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import v61_fixture as FX                                   # noqa: E402
from research.triangle import v61_contract as C            # noqa: E402
from research.triangle import v61_validate as V           # noqa: E402

SCRIPT = ROOT / "research/triangle/v61_render_evidence.py"


@pytest.fixture
def man():
    return FX.manifest()


def _refuses(m, match):
    with pytest.raises(C.Refuse, match=match):
        V.build(m)


def _row(m, tag="a"):
    return m["rows"][tag]


# --- the fixture must pass, or every negative test is vacuous -------------------------

def test_the_synthetic_manifest_builds(man):
    v, g, ex = V.build(man)
    assert v["minimal"] == ["a+b+c"] and v["uniqueness_claimable"] is True
    assert g["decision_ok"] and g["value_ok"] and g["location_compatible"]
    assert len(ex["receipts"]) == len(v["rows"]) == 7
    assert v["indeterminate"] == []


def test_the_driver_writes_the_schema_the_validator_requires():
    from research.triangle import v61_frozen_factorial as F
    assert F.SCHEMA_VERSION == V.REQUIRED_SCHEMA
    assert F.GATE_POLICY_VERSION == V.REQUIRED_GATE_POLICY


def test_the_driver_reads_the_registered_tuple_rather_than_re_typing_it():
    """Two copies of one fact drift. The driver used to carry its own literal GATE dict."""
    from research.triangle import v61_frozen_factorial as F
    assert F.GATE is not None
    assert F.GATE == json.loads(C.REGISTRATION.read_text())["registered_tuple"]
    src = (ROOT / "research/triangle/v61_frozen_factorial.py").read_text()
    assert '"mean_steady_peak_k": 329.904867' not in src, "the tuple must not be re-typed"


# --- schema and gate policy are required, not sniffed ---------------------------------

def test_an_older_schema_is_refused(man):
    man["run"]["schema_version"] = 3
    _refuses(man, "accepts only schema 4")


def test_a_manifest_admitted_by_an_older_gate_policy_is_refused(man):
    """Gate policy 1 accepted exact argmax equality. A manifest it admitted must not be read
    under policy 2's claims."""
    man["gate"]["gate_policy_version"] = 1
    _refuses(man, "gate policy 1")


def test_the_archived_schema3_manifest_is_refused():
    legacy = ROOT / "artifacts_receipts/v61_cg3_schema3/v61_manifest.json"
    if not legacy.exists():
        pytest.skip("archived schema-3 manifest not present")
    _refuses(json.loads(legacy.read_text()), "accepts only schema 4")


# --- the gate: recomputed from temperatures, not from labels or lists -----------------

def test_the_gate_passes_on_a_tie_where_exact_argmax_equality_would_fail(man):
    """The whole point of gate policy 2. Make another block tie the registered one so the argmax
    label moves to it; the registered block is still indistinguishable from the maximum, so the
    gate must pass and report the label mismatch without gating on it."""
    full = man["rows"]["full"]
    i_reg = full["block_ids"].index(man["gate"]["registered_tuple"]["hottest"])
    other = 0 if i_reg != 0 else 1
    full["periodic_block_peaks_k"][other] = full["periodic_block_peaks_k"][i_reg]
    full["periodic_hottest_block"] = full["block_ids"][min(i_reg, other)]
    v, g, ex = V.build(man)
    assert g["location_compatible"] is True
    assert g["argmax_equals"] is (min(i_reg, other) == i_reg)
    assert g["registered_is_resolvable"] is False
    assert "full" in ex["tied_rows"]


def test_the_gate_refuses_when_the_registered_block_is_more_than_a_quantum_below_the_peak(man):
    full = man["rows"]["full"]
    i_reg = full["block_ids"].index(man["gate"]["registered_tuple"]["hottest"])
    full["periodic_block_peaks_k"][i_reg] -= 0.5          # peak moves to another block
    full["periodic_peak_k"] = max(full["periodic_block_peaks_k"])
    full["periodic_hottest_block"] = full["block_ids"][
        full["periodic_block_peaks_k"].index(full["periodic_peak_k"])]
    man["gate"]["location_compatible_at_resolution"] = False
    _refuses(man, "recomputation gives")


def test_a_producer_reported_tie_list_cannot_influence_the_gate(man):
    """A tie list is no longer read at all -- the predicate uses the registered block's own
    temperature, so adding a bogus tie field changes nothing."""
    man["rows"]["full"]["periodic_tie_blocks"] = ["blk_3", "blk_4"]
    v, g, ex = V.build(man)
    assert g["location_compatible"] is True
    assert "blk_3" not in v["full"]["periodic"]["ties"]


def test_the_gate_refuses_a_forged_location_verdict(man):
    man["gate"]["location_compatible_at_resolution"] = False
    _refuses(man, "stored location verdict disagrees")


def test_the_gate_refuses_a_forged_steady_delta(man):
    man["gate"]["steady_delta_k"] = 0.0
    _refuses(man, "steady delta disagrees")


def test_the_gate_refuses_a_registered_tuple_that_drifted(man):
    man["gate"]["registered_tuple"] = dict(man["gate"]["registered_tuple"], hottest="blk_4")
    _refuses(man, "differs from the pinned registration")


def test_the_gate_refuses_a_run_that_is_not_the_registered_candidate(man):
    man["workload"] = "resnet50"
    _refuses(man, "workload differs from the full row")


def test_the_gate_refuses_when_the_registered_block_is_not_in_the_registry(man):
    hottest = man["gate"]["registered_tuple"]["hottest"]
    for r in man["rows"].values():
        r["block_ids"] = [b if b != hottest else "renamed" for b in r["block_ids"]]
        r["periodic_hottest_block"] = "renamed"
        r["mean_steady_hottest_block"] = "renamed"
    _refuses(man, "not in this run's block registry")


def test_the_decision_uses_the_same_quantisation_rule_as_every_row(man):
    """Gate policy 1's decision was a bare `periodic >= limit`, so a full row at exactly the
    limit passed a gate that classification calls undecidable."""
    limit = man["thermal_limit_k"]
    full = man["rows"]["full"]
    i = full["block_ids"].index(man["gate"]["registered_tuple"]["hottest"])
    full["periodic_block_peaks_k"][i] = limit
    full["periodic_peak_k"] = limit
    _refuses(man, "recomputation gives")
    assert C.classify(limit, limit, 0.01) == "indeterminate"
    assert C.classify(limit + 0.01, limit, 0.01) == "crossing"
    assert C.classify(limit - 0.01, limit, 0.01) == "below"


# --- the stored scalars must agree with the vectors they summarise --------------------

def test_a_stored_peak_that_contradicts_its_own_vector_is_refused(man):
    _row(man)["periodic_peak_k"] += 1.0
    _refuses(man, "stored periodic peak disagrees with its own temperature vector")


def test_a_stored_argmax_that_contradicts_its_own_vector_is_refused(man):
    _row(man)["periodic_hottest_block"] = "blk_4"
    _refuses(man, "stored periodic argmax disagrees")


def test_a_vector_of_the_wrong_length_is_refused(man):
    _row(man)["periodic_block_peaks_k"] = [330.0]
    _refuses(man, "temperatures for")


@pytest.mark.parametrize("field", ["periodic_block_peaks_k", "mean_steady_block_k"])
def test_a_non_finite_temperature_is_refused(man, field):
    _row(man)[field][0] = float("nan")
    _refuses(man, "not a finite number")


# --- convergence ----------------------------------------------------------------------

def test_an_unconverged_row_with_a_healthy_cycle_count_is_refused(man):
    _row(man, "full")["peak_residual_k"] = 10.0
    _refuses(man, "residual 10.0 K exceeds")


def test_a_tolerance_finer_than_the_output_resolution_is_refused(man):
    for r in man["rows"].values():
        r["tolerance_k"] = 0.001
    _refuses(man, "finer than the")


def test_a_step_larger_than_requested_is_refused(man):
    _row(man)["step_s"] = 1.0
    _refuses(man, r"is not in \(0, the requested")


def test_an_invalid_samples_per_cycle_is_refused(man):
    _row(man)["samples_per_cycle"] = 0
    _refuses(man, "samples_per_cycle")


def test_a_steady_peak_below_ambient_is_refused(man):
    r = _row(man)
    r["mean_steady_block_k"] = [man["ambient_k"] - 1.0] * len(r["block_ids"])
    r["mean_steady_peak_k"] = man["ambient_k"] - 1.0
    _refuses(man, "is not above ambient")


# --- provenance -----------------------------------------------------------------------

@pytest.mark.parametrize("patch,match", [
    ({"dirty": ["x.py"]}, "requires a clean tree"),
    ({"provenance_stable": False}, "requires a clean tree"),
    ({"complete": False}, "complete="),
])
def test_provenance_preconditions(man, patch, match):
    man.update(patch)
    _refuses(man, match)


def test_a_run_that_ended_on_another_commit_is_refused(man):
    man["provenance_end"]["commit"] = "d" * 40
    _refuses(man, "end-of-run provenance does not match")


def test_a_row_from_a_different_tree_state_is_refused(man):
    _row(man)["dirty"] = ["x.py"]
    _refuses(man, "dirty differs from the full row")


def test_a_binary_hash_that_contradicts_the_staged_hash_is_refused(man):
    man["input_hashes"]["hotspot"] = "d" * 64
    _refuses(man, "staged hotspot hash disagrees")


def test_a_malformed_hash_is_refused(man):
    man["input_hashes"]["hotspot"] = "not-a-hash"
    man["hotspot_sha256"] = "not-a-hash"
    _refuses(man, "is not a sha256")


# --- enumeration and the ledger -------------------------------------------------------

def test_a_missing_subset_is_refused(man):
    del man["rows"]["a-b"]
    _refuses(man, "non-empty subsets")


def test_a_row_whose_components_do_not_match_its_key_is_refused(man):
    man["rows"]["a-b"]["components"] = ["a", "c"]
    _refuses(man, "do not tag to its own key")


def test_a_ledger_that_does_not_reproduce_a_row_is_refused(man):
    man["component_energy_j"]["c"] *= 1.01
    _refuses(man, "retained energy")


def test_a_non_positive_component_energy_is_refused(man):
    man["component_energy_j"]["c"] = 0.0
    _refuses(man, "non-positive energy")


def test_two_rows_sharing_a_trace_hash_is_refused(man):
    man["rows"]["a"]["trace_sha256"] = man["rows"]["b"]["trace_sha256"]
    _refuses(man, "same trace hash")


# --- per-invocation receipts ----------------------------------------------------------

def test_a_row_belonging_to_another_run_is_refused(man):
    _row(man)["execution"]["run_nonce"] = "other-run"
    _refuses(man, "belongs to a different execution")


def test_a_pre_existing_directory_is_refused(man):
    _row(man)["execution"]["dest_existed_before_run"] = True
    _refuses(man, "already existed before the row ran")


def test_a_populated_workspace_is_refused(man):
    _row(man)["execution"]["workspace_files_before_run"] = ["periodic-8.ttrace"]
    _refuses(man, "was not empty before the row ran")


def test_a_receipt_without_a_pid_is_refused(man):
    _row(man)["execution"]["pid"] = None
    _refuses(man, "no valid PID")


def test_a_wall_time_that_disagrees_with_its_window_is_refused(man):
    _row(man)["execution"]["wall_s"] = 1.0
    _refuses(man, "wall_s disagrees")


def test_a_row_outside_the_run_window_is_refused(man):
    _row(man)["execution"]["ended_unix"] = man["run"]["ended_unix"] + 3600
    _refuses(man, "wall window is outside")


def test_the_first_two_roles_must_be_the_fixed_solves(man):
    inv = _row(man)["execution"]["invocations"]
    inv[0], inv[1] = inv[1], inv[0]
    _refuses(man, "not the mean-steady and")


def test_a_non_doubling_periodic_sequence_is_refused(man):
    """The sequence is validated as RECORDED, not inferred from the cycle count -- inferring it
    hard-coded replay_periodic's schedule into the consumer."""
    ex = _row(man, "full")["execution"]
    ex["invocations"][2]["role"] = "periodic-5"
    _refuses(man, "not a doubling sequence")


def test_the_last_periodic_attempt_must_match_the_converged_cycle_count(man):
    _row(man, "full")["cycles"] = 32
    _refuses(man, "converged at 32")


def test_an_unexpected_role_is_refused(man):
    _row(man)["execution"]["invocations"][2]["role"] = "warmup"
    _refuses(man, "unexpected invocation role")


def test_a_nonzero_return_code_is_refused(man):
    _row(man)["execution"]["invocations"][0]["returncode"] = 1
    _refuses(man, "cannot contain a failed invocation")


def test_two_invocations_claiming_one_output_is_refused(man):
    inv = _row(man)["execution"]["invocations"]
    inv[1]["output"] = inv[0]["output"]
    _refuses(man, "already written by another")


def test_an_output_hash_that_disagrees_with_the_workspace_is_refused(man):
    ex = _row(man)["execution"]
    ex["invocations"][0]["output_sha256"] = "e" * 64
    _refuses(man, "recorded output hash disagrees")


def test_an_output_missing_from_the_workspace_is_refused(man):
    ex = _row(man)["execution"]
    del ex["workspace_files"][ex["invocations"][0]["output"]]
    _refuses(man, "not among the hashed workspace files")


def test_an_invocation_claiming_a_ptrace_input_as_its_output_is_refused(man):
    """The document once counted the driver's own .ptrace inputs as HotSpot outputs."""
    ex = _row(man)["execution"]
    ex["invocations"][0]["output"] = "mean.ptrace"
    ex["invocations"][0]["output_sha256"] = ex["workspace_files"]["mean.ptrace"]
    _refuses(man, "claims a .ptrace input as its own output")


def test_ptrace_inputs_are_counted_separately_from_outputs(man):
    _, _, ex = V.build(man)
    r = ex["receipts"]["full"]
    assert r["hotspot_invocations"] == r["hotspot_outputs"] == 4
    assert r["driver_inputs"] == 4


def test_a_freshness_claim_that_disagrees_with_the_receipts_is_refused(man):
    man["summary"]["all_rows_fresh"] = False
    _refuses(man, "all_rows_fresh")


# --- a missing field must Refuse, not raise KeyError ---------------------------------

@pytest.mark.parametrize("field", ["components", "cycles", "execution", "block_ids",
                                   "periodic_block_peaks_k", "mean_steady_block_k",
                                   "retained_source_energy_j", "trace_sha256"])
def test_a_missing_row_field_is_a_refusal_not_a_traceback(man, field):
    del _row(man)[field]
    with pytest.raises(C.Refuse):
        V.build(man)


@pytest.mark.parametrize("field", ["role", "returncode", "output", "output_sha256",
                                   "output_bytes", "argv"])
def test_a_missing_invocation_field_is_a_refusal_not_a_traceback(man, field):
    del _row(man)["execution"]["invocations"][2][field]
    with pytest.raises(C.Refuse):
        V.build(man)


# --- citations ------------------------------------------------------------------------

def test_a_stale_cited_line_is_a_refusal(man, monkeypatch, tmp_path):
    """Adding a paragraph above a cited table shifted every line number in the registration by
    one, within an hour of it being written. A wrong citation prints silently."""
    pinned = json.loads(C.REGISTRATION.read_text())
    pinned["grid128_row"]["line"] = 1
    fake = tmp_path / "registration.json"
    fake.write_text(json.dumps(pinned))
    monkeypatch.setattr(C, "REGISTRATION", fake)
    monkeypatch.setattr(V, "REGISTRATION", fake)
    _refuses(man, "no longer contains")


def test_the_live_citations_all_resolve():
    pinned = C.load_registration()
    reg = pinned["registered_tuple"]
    C.check_citation(pinned["grid64_source"],
                     [reg["hottest"], reg["periodic_peak_k"], reg["mean_steady_peak_k"]])
    C.check_citation(pinned["grid128_row"], [pinned["grid128_row"]["steady_block"],
                                             pinned["grid128_row"]["periodic_block"]])
    C.check_citation(pinned["earlier_hotspot_binary_sha256"],
                     [pinned["earlier_hotspot_binary_sha256"]["sha256"]])


# --- the document follows the validation ---------------------------------------------

def _render(m: dict, tmp_path: Path) -> str:
    tmp_path.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "m.json"
    src.write_text(json.dumps(m))
    out = tmp_path / "doc.md"
    p = subprocess.run([sys.executable, str(SCRIPT), str(src), str(out)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert p.returncode == 0, p.stdout + p.stderr
    return out.read_text()


def test_a_refused_manifest_writes_no_document(man, tmp_path):
    man["rows"]["full"]["periodic_peak_k"] += 1.0
    src = tmp_path / "m.json"
    src.write_text(json.dumps(man))
    out = tmp_path / "doc.md"
    p = subprocess.run([sys.executable, str(SCRIPT), str(src), str(out)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert p.returncode == 2 and not out.exists()


def test_uniqueness_prose_is_conditional(man, tmp_path):
    text = _render(man, tmp_path / "a")
    assert "unique minimal crossing coalition" in text

    m2 = copy.deepcopy(man)
    for tag in ("a", "b-c"):                 # two incomparable crossing subsets
        r = m2["rows"][tag]
        i = r["block_ids"].index(m2["gate"]["registered_tuple"]["hottest"])
        r["periodic_block_peaks_k"][i] = 330.50
        r["periodic_peak_k"] = 330.50
    v, _, _ = V.build(m2)
    assert len(v["minimal"]) == 2 and v["uniqueness_claimable"] is False
    text2 = _render(m2, tmp_path / "b")
    assert "Uniqueness is **not** claimable" in text2
    assert "unique minimal crossing coalition" not in text2


def test_leave_one_out_prose_uses_the_quantum_aware_rule(man, tmp_path):
    assert "at least a full 0.01 K quantum more than that excess" in _render(man, tmp_path / "a")
    m2 = copy.deepcopy(man)
    r = m2["rows"]["a-b"]                    # delta over the excess but under excess + quantum
    i = r["block_ids"].index(m2["gate"]["registered_tuple"]["hottest"])
    r["periodic_block_peaks_k"][i] = 329.995
    r["periodic_peak_k"] = 329.995
    assert "not purely arithmetic" in _render(m2, tmp_path / "b")


def test_the_document_hedges_what_it_cannot_re_derive(man, tmp_path):
    text = _render(man, tmp_path)
    assert "not proof of execution" in text
    assert "A **dishonest** one is not" in text
    assert "producer-attested" in text
    assert "not an independent numerical confirmation" in text
    assert "compatibility test, not spatial reproduction" in text
