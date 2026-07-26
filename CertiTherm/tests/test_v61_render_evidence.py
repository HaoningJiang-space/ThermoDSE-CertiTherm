"""The evidence generator must recompute, not trust, and must refuse rather than raise.

Three generations of this generator each trusted something it should have derived:

1. it checked two booleans (`complete`, `gate.passed`) and printed `summary.row_status`,
   `minimal_crossing_coalitions` and `leave_one_out` verbatim -- the fields a paper table
   rests on;
2. it then recomputed those but still printed the manifest's own `decision_ok` / `value_ok` /
   `location_ok`, so an edited manifest could assert a passing gate over untouched rows, and
   it validated no convergence at all -- a 16-cycle row with a 10 K residual passed;
3. it carried four bare literals under an opening line claiming nothing was hand-transcribed.

Every test below pins one of those, or one of the fail-open holes found with them: prose
asserting uniqueness that validation never required, `all_rows_fresh` not required to be true,
argmax "relocation" decided from one endpoint, and a `KeyError` escaping instead of a refusal.

The fixture is the real archived schema-3 claim-grade manifest, so no test can pass against a
manifest shape the driver does not produce.
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

from research.triangle import v61_render_evidence as R

MANIFEST = ROOT / "artifacts_receipts/v61_cg3_schema3/v61_manifest.json"
LEGACY = ROOT / "artifacts_receipts/v61_claimgrade/v61_manifest.json"
SCRIPT = ROOT / "research/triangle/v61_render_evidence.py"

pytestmark = pytest.mark.skipif(not MANIFEST.exists(),
                                reason="archived schema-3 manifest not present")


@pytest.fixture
def man():
    return json.loads(MANIFEST.read_text())


def _refuses(m, match):
    with pytest.raises(R.Refuse, match=match):
        R.build(m)


def _row(m, tag="core"):
    return m["rows"][tag]


# --- the fixture must pass, or every negative test is vacuous -------------------------

def test_the_archived_schema3_manifest_builds(man):
    view, gate, ex = R.build(man)
    assert view["minimal"] == ["core+dram+noc+nop"]
    assert view["uniqueness_claimable"] is True
    assert gate["decision_ok"] and gate["value_ok"] and gate["argmax_equals"]
    assert len(ex["receipts"]) == len(view["rows"]) == 15


def test_the_registration_is_pinned_and_matches_the_driver():
    """The driver's GATE and the pinned registration are two copies of one fact. Nothing but
    a test stops them drifting, and the renderer recomputes the gate from the pinned copy."""
    from research.triangle import v61_frozen_factorial as F
    pinned = json.loads(R.REGISTRATION.read_text())
    assert pinned["registered_tuple"] == F.GATE, \
        "docs/registration/ and the driver's GATE dict have drifted apart"


# --- schema is required, not sniffed --------------------------------------------------

def test_the_schema2_manifest_is_refused_not_silently_downgraded(man):
    """It renders a document that cannot support the execution or relocation claims, so it is
    a historical artefact, not an input. Feature-sniffing let it through before."""
    if not LEGACY.exists():
        pytest.skip("legacy manifest not present")
    _refuses(json.loads(LEGACY.read_text()), "renders only schema 3")


def test_a_receipt_bearing_manifest_that_lies_about_its_schema_is_refused(man):
    man["run"]["schema_version"] = 2
    _refuses(man, "renders only schema 3")


def test_a_row_that_lies_about_its_schema_is_refused(man):
    _row(man)["schema_version"] = 2
    _refuses(man, "schema_version differs from the full row")


# --- the two booleans, which were once the ONLY check ---------------------------------

@pytest.mark.parametrize("patch", [{"complete": False}, {"complete": None}])
def test_refuses_an_incomplete_manifest(man, patch):
    man.update(patch)
    _refuses(man, "complete=")


def test_refuses_a_failed_gate(man):
    man["gate"]["passed"] = False
    _refuses(man, "gate.passed=False")


# --- provenance: printed as CLEAN without ever being checked --------------------------

def test_refuses_a_dirty_tree(man):
    man["dirty"] = ["CertiTherm/transient.py"]
    _refuses(man, "requires a clean tree")


def test_refuses_an_unstable_provenance(man):
    man["provenance_stable"] = False
    _refuses(man, "requires a clean tree")


def test_refuses_when_the_run_ended_on_a_different_commit(man):
    man["provenance_end"]["commit"] = "d" * 40
    _refuses(man, "end-of-run provenance does not match")


def test_refuses_when_a_row_was_produced_from_a_different_tree(man):
    _row(man)["dirty"] = ["something.py"]
    _refuses(man, "dirty differs from the full row")


def test_refuses_when_the_staged_binary_hash_contradicts_the_recorded_one(man):
    man["input_hashes"]["hotspot"] = "d" * 64
    _refuses(man, "staged hotspot hash disagrees")


def test_refuses_when_top_level_metadata_disagrees_with_the_rows(man):
    man["workload"] = "resnet50"
    _refuses(man, "top-level workload disagrees with the rows")


# --- convergence, which was not validated at all -------------------------------------

def test_refuses_an_unconverged_row_despite_a_healthy_cycle_count(man):
    """The hole: only finiteness and `cycles >= 2` were checked, so a 16-cycle row with a
    10 K residual rendered as evidence."""
    _row(man, "full")["peak_residual_k"] = 10.0
    _refuses(man, "residual 10.0 K exceeds")


def test_refuses_a_tolerance_finer_than_the_output_resolution(man):
    for r in man["rows"].values():
        r["tolerance_k"] = 0.001
    _refuses(man, "finer than the")


def test_refuses_a_step_larger_than_requested(man):
    _row(man)["step_s"] = 1.0
    _refuses(man, "is not in \\(0, the requested")


@pytest.mark.parametrize("field", ["step_s", "mean_steady_peak_k", "periodic_peak_k",
                                   "boundary_residual_k", "peak_residual_k"])
def test_refuses_a_non_finite_number(man, field):
    _row(man)[field] = float("nan")
    _refuses(man, "not a finite number")


def test_refuses_an_invalid_samples_per_cycle(man):
    _row(man)["samples_per_cycle"] = 0
    _refuses(man, "samples_per_cycle")


def test_refuses_a_steady_peak_below_ambient(man):
    """The uplift ratio divides by the rise above ambient; a non-positive rise made it
    meaningless or a crash rather than a refusal."""
    _row(man)["mean_steady_peak_k"] = man["ambient_k"] - 1.0
    _refuses(man, "not above ambient")


# --- a missing field must Refuse, not raise KeyError ---------------------------------

@pytest.mark.parametrize("field", ["components", "cycles", "periodic_tie_blocks",
                                   "periodic_top_gap_k", "execution",
                                   "retained_source_energy_j"])
def test_a_missing_row_field_is_a_refusal_not_a_traceback(man, field):
    del _row(man)[field]
    with pytest.raises(R.Refuse):
        R.build(man)


# --- enumeration and the ledger ------------------------------------------------------

def test_refuses_a_missing_subset(man):
    del man["rows"]["noc-nop"]
    _refuses(man, "non-empty subsets")


def test_refuses_a_row_whose_components_do_not_match_its_key(man):
    man["rows"]["noc-nop"]["components"] = ["core", "noc"]
    _refuses(man, "do not tag to its own key")


def test_refuses_when_the_energy_ledger_does_not_reproduce_a_row(man):
    man["component_energy_j"]["nop"] *= 1.01
    _refuses(man, "retained energy")


def test_refuses_a_non_positive_component_energy(man):
    man["component_energy_j"]["nop"] = 0.0
    _refuses(man, "non-positive energy")


def test_refuses_when_two_rows_share_a_trace_hash(man):
    man["rows"]["core"]["trace_sha256"] = man["rows"]["noc"]["trace_sha256"]
    _refuses(man, "same trace hash")


# --- the gate is recomputed, not read ------------------------------------------------

def test_refuses_a_manifest_whose_registered_tuple_drifted_from_the_pinned_one(man):
    man["gate"]["registered_tuple"]["periodic_peak_k"] = 331.0
    _refuses(man, "differs from the pinned registration")


def test_refuses_a_forged_gate_verdict_over_untouched_rows(man):
    """The blocker: `location_ok` was printed verbatim, so flipping it changed the document
    without changing a single temperature."""
    man["gate"]["location_ok"] = False
    _refuses(man, "location_ok disagrees with recomputation")


def test_refuses_a_forged_gate_value_verdict(man):
    man["gate"]["value_ok"] = False
    _refuses(man, "value_ok disagrees with recomputation")


def test_refuses_a_forged_steady_delta(man):
    man["gate"]["steady_delta_k"] = 0.0
    _refuses(man, "steady delta disagrees")


def test_the_gate_decision_uses_the_same_quantisation_rule_as_every_row(man):
    """The driver gated on `periodic >= 330`, while classification needs `>= 330.01`. A row at
    exactly the limit must NOT count as a crossing in the recomputed decision."""
    limit = man["thermal_limit_k"]
    full = _row(man, "full")
    full["periodic_peak_k"] = limit
    full["periodic_second_peak_k"] = limit
    full["periodic_top_gap_k"] = 0.0
    man["gate"]["value_ok"] = False          # keep the stored copy consistent
    # This test originally expected only a refusal and found a hole instead: nothing required
    # the RECOMPUTED verdicts to hold when the manifest says the gate passed.
    _refuses(man, "reports gate.passed but recomputation gives")
    assert R.classify(limit, limit, 0.01) == "indeterminate"
    assert R.classify(limit + 0.01, limit, 0.01) == "crossing"
    assert R.classify(limit - 0.01, limit, 0.01) == "below"


# --- execution receipts --------------------------------------------------------------

def test_refuses_a_row_belonging_to_another_run(man):
    _row(man)["execution"]["run_nonce"] = "some-other-run"
    _refuses(man, "belongs to a different execution")


def test_refuses_a_row_whose_directory_already_existed(man):
    _row(man)["execution"]["dest_existed_before_run"] = True
    _refuses(man, "already existed before the row ran")


def test_refuses_a_row_whose_workspace_was_not_empty(man):
    _row(man)["execution"]["workspace_files_before_run"] = ["periodic-8.ttrace"]
    _refuses(man, "was not empty before the row ran")


def test_refuses_a_receipt_without_a_pid(man):
    _row(man)["execution"]["pid"] = None
    _refuses(man, "no valid PID")


def test_refuses_a_wall_time_that_disagrees_with_its_own_window(man):
    _row(man)["execution"]["wall_s"] = 1.0
    _refuses(man, "wall_s disagrees")


def test_refuses_a_row_that_ran_outside_the_run_window(man):
    _row(man)["execution"]["ended_unix"] = man["run"]["ended_unix"] + 3600
    _refuses(man, "wall window is outside")


def test_refuses_an_invocation_count_that_does_not_match_the_cycle_count(man):
    """`>= 3` accepted anything. The count is now pinned to the cycle doubling: 2 fixed solves
    plus one attempt per doubling from 8."""
    _row(man, "full")["execution"]["hotspot_invocations"] = 3     # full converged at 16 -> 4
    _refuses(man, "does not match the 4 implied")


def test_refuses_a_malformed_output_hash(man):
    ex = _row(man)["execution"]
    ex["raw_outputs"][sorted(ex["raw_outputs"])[0]] = "not-a-hash"
    _refuses(man, "malformed sha256")


def test_refuses_a_missing_converged_ttrace(man):
    ex = _row(man, "full")["execution"]
    del ex["raw_outputs"]["periodic-16.ttrace"]
    _refuses(man, "each invocation writes one")


def test_refuses_a_missing_mean_steady_output(man):
    ex = _row(man, "full")["execution"]
    ex["raw_outputs"]["extra.ttrace"] = ex["raw_outputs"].pop("mean.steady")
    _refuses(man, "mean-steady or fixed-initial output is missing")


def test_ptrace_inputs_are_not_counted_as_hotspot_outputs(man):
    """The document claimed every hashed file was an artefact HotSpot produced. Half of them
    are the ptrace inputs the driver wrote."""
    _, _, ex = R.build(man)
    r = ex["receipts"]["full"]
    assert r["hotspot_outputs"] == r["hotspot_invocations"] == 4
    assert r["driver_inputs"] == 4


# --- tie evidence, both semantics ----------------------------------------------------

@pytest.mark.parametrize("sem", ["periodic", "mean_steady"])
def test_refuses_an_inconsistent_top_gap(man, sem):
    _row(man)[f"{sem}_top_gap_k"] = 9.0
    _refuses(man, f"{sem} top gap disagrees")


@pytest.mark.parametrize("sem", ["periodic", "mean_steady"])
def test_refuses_an_argmax_absent_from_its_own_tie_set(man, sem):
    _row(man)[f"{sem}_tie_blocks"] = ["some_other_block"]
    _refuses(man, "not in its own tie set")


@pytest.mark.parametrize("sem", ["periodic", "mean_steady"])
def test_refuses_a_duplicated_tie_set(man, sem):
    b = _row(man)[f"{sem}_hottest_block"]
    _row(man)[f"{sem}_tie_blocks"] = [b, b]
    _refuses(man, "empty or has duplicates")


def test_refuses_a_runner_up_above_the_peak(man):
    r = _row(man)
    r["periodic_second_peak_k"] = r["periodic_peak_k"] + 1.0
    r["periodic_top_gap_k"] = -1.0
    _refuses(man, "runner-up exceeds the peak")


def test_a_label_change_needs_both_endpoints_resolvable(man):
    """Deciding relocation from the periodic gap alone would call a change resolvable even
    when the steady endpoint was itself a tie."""
    _, _, ex = R.build(man)
    assert ex["moves"], "the fixture has label changes to reason about"
    assert all(not mv["resolved"] for mv in ex["moves"]), \
        "every label change in this run is a tie broken differently"

    m2 = copy.deepcopy(man)
    tag = ex["moves"][0]["tag"]
    r = m2["rows"][tag]
    # make ONLY the periodic endpoint resolvable; relocation must still be refused as such
    r["periodic_second_peak_k"] = r["periodic_peak_k"] - 0.5
    r["periodic_top_gap_k"] = 0.5
    r["periodic_tie_blocks"] = [r["periodic_hottest_block"]]
    _, _, ex2 = R.build(m2)
    moved = [mv for mv in ex2["moves"] if mv["tag"] == tag][0]
    assert moved["resolved"] is False, \
        "the steady endpoint is still tied, so this is not a relocation"


# --- prose must follow validation ----------------------------------------------------

def _render(manifest: dict, tmp_path: Path) -> str:
    tmp_path.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "m.json"
    src.write_text(json.dumps(manifest))
    out = tmp_path / "doc.md"
    p = subprocess.run([sys.executable, str(SCRIPT), str(src), str(out)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert p.returncode == 0, p.stdout + p.stderr
    return out.read_text()


def test_uniqueness_prose_is_conditional_on_validation(man, tmp_path):
    """"with no indeterminate row" and "unique" were printed unconditionally while validation
    required neither."""
    text = _render(man, tmp_path / "a")
    assert "unique minimal crossing coalition" in text

    m2 = copy.deepcopy(man)
    # Two INCOMPARABLE crossing subsets. Pushing a subset of `full` over the limit would not
    # do it: `full` would simply stop being minimal, leaving exactly one minimal coalition.
    for tag in ("core-dram", "noc-nop"):
        r = m2["rows"][tag]
        r["periodic_peak_k"] = 330.50
        r["periodic_second_peak_k"] = 330.50
        r["periodic_top_gap_k"] = 0.0
    view, _, _ = R.build(m2)
    assert len(view["minimal"]) == 2
    assert view["uniqueness_claimable"] is False
    text2 = _render(m2, tmp_path / "b")
    assert "Uniqueness is **not** claimable" in text2
    assert "unique minimal crossing coalition" not in text2


def test_leave_one_out_prose_uses_the_quantum_aware_rule(man, tmp_path):
    """`min(delta) > excess` is not enough: a removal only just larger than the excess can
    land the row on the undecidable boundary."""
    text = _render(man, tmp_path / "a")
    assert "at least a full 0.01 K quantum more than that excess" in text

    m2 = copy.deepcopy(man)
    full, q = m2["rows"]["full"]["periodic_peak_k"], m2["rows"]["full"]["output_resolution_k"]
    r = m2["rows"]["core-dram-noc"]                    # delta just over the excess, under +q
    r["periodic_peak_k"] = round(full - (full - m2["thermal_limit_k"]) - q / 2, 3)
    r["periodic_second_peak_k"] = r["periodic_peak_k"]
    r["periodic_top_gap_k"] = 0.0
    text2 = _render(m2, tmp_path / "b")
    assert "not purely arithmetic" in text2


def test_the_document_does_not_call_the_receipts_proof(man, tmp_path):
    text = _render(man, tmp_path)
    assert "not proof of execution" in text
    assert "A *dishonest* producer is not" in text
    assert "self-attested" in text


def test_the_document_states_the_argmax_is_mostly_unresolvable(man, tmp_path):
    text = _render(man, tmp_path)
    assert "11 of 15" in text
    assert "The location check is not a location claim" in text
    assert "tie broken differently" in text


def test_the_document_never_claims_independent_numerical_confirmation(man, tmp_path):
    text = _render(man, tmp_path)
    assert "not an independent numerical confirmation" in text
    assert "1.245e-07" in text, "%.6f hid a nonzero residual as 0.000000"


def test_external_facts_come_from_the_pinned_registration_not_a_regex(man, tmp_path):
    text = _render(man, tmp_path)
    assert "docs/V6_PHYSICAL_TRACE_GATE.md:148" in text        # grid128 row
    assert "docs/GPU_HOTSPOT_EVIDENCE.md:86" in text           # earlier binary
    assert not hasattr(R, "EXTERNAL"), "prose regex parsing should be gone"


def test_a_missing_registration_is_a_refusal(man, monkeypatch, tmp_path):
    monkeypatch.setattr(R, "REGISTRATION", tmp_path / "absent.json")
    _refuses(man, "pinned registration")


# --- the committed document must be this generator's output ---------------------------

def test_the_committed_document_regenerates_byte_for_byte(tmp_path):
    """The committed document had drifted from the generator: its schema-2 paragraph was
    reworded after the document was committed, so the claimed generation chain was broken."""
    doc = ROOT / "docs/V6_1_CAUSAL_ISOLATION.md"
    if not doc.exists():
        pytest.skip("evidence document not present")
    out = tmp_path / "regen.md"
    p = subprocess.run([sys.executable, str(SCRIPT), str(MANIFEST), str(out)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert p.returncode == 0, p.stdout + p.stderr
    assert out.read_text() == doc.read_text(), (
        "docs/V6_1_CAUSAL_ISOLATION.md is not the output of the current generator; "
        "regenerate it instead of editing it")


# --- pinned citations drift the moment the cited document is edited --------------------

def test_a_stale_cited_line_is_a_refusal(man, monkeypatch, tmp_path):
    """This is not hypothetical: inserting a correction paragraph above the cited table
    shifted every line number in the registration by one, within an hour of writing it. A
    wrong citation prints silently, so it has to refuse."""
    pinned = json.loads(R.REGISTRATION.read_text())
    pinned["grid128_row"]["line"] = 1
    fake = tmp_path / "registration.json"
    fake.write_text(json.dumps(pinned))
    monkeypatch.setattr(R, "REGISTRATION", fake)
    _refuses(man, "no longer contains")


def test_a_line_past_the_end_of_the_file_is_a_refusal(man, monkeypatch, tmp_path):
    pinned = json.loads(R.REGISTRATION.read_text())
    pinned["grid64_source"]["line"] = 10 ** 6
    fake = tmp_path / "registration.json"
    fake.write_text(json.dumps(pinned))
    monkeypatch.setattr(R, "REGISTRATION", fake)
    _refuses(man, "past the end")


def test_a_missing_cited_document_is_a_refusal(man, monkeypatch, tmp_path):
    pinned = json.loads(R.REGISTRATION.read_text())
    pinned["earlier_hotspot_binary_sha256"]["document"] = "docs/does-not-exist.md"
    fake = tmp_path / "registration.json"
    fake.write_text(json.dumps(pinned))
    monkeypatch.setattr(R, "REGISTRATION", fake)
    _refuses(man, "cited document")


def test_the_live_citations_all_resolve():
    """Guards the committed registration against the next edit to either cited document."""
    pinned = json.loads(R.REGISTRATION.read_text())
    reg = pinned["registered_tuple"]
    R.check_citation(pinned["grid64_source"],
                     [reg["hottest"], reg["periodic_peak_k"], reg["mean_steady_peak_k"]])
    R.check_citation(pinned["grid128_row"], [pinned["grid128_row"]["steady_block"],
                                             pinned["grid128_row"]["periodic_block"]])
    R.check_citation(pinned["earlier_hotspot_binary_sha256"],
                     [pinned["earlier_hotspot_binary_sha256"]["sha256"]])
