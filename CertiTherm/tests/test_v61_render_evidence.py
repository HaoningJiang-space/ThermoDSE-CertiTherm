"""The evidence generator must recompute, not trust, the manifest's `summary`.

The first version checked two booleans (`complete`, `gate.passed`) and then printed
`summary.row_status`, `summary.minimal_crossing_coalitions`, `summary.leave_one_out` and
`summary.evidence_grade` verbatim -- the exact fields a paper table rests on. It also carried
four bare literals (a "1.9-5.0%" range, two grid128 block names) inside a document whose first
paragraph claimed no number was hand-transcribed.

Each test below pins one of those defects. The fixture is the real archived claim-grade
manifest, so a test cannot pass against a manifest shape that the driver does not produce.
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

MANIFEST = ROOT / "artifacts_receipts/v61_claimgrade/v61_manifest.json"
SCRIPT = ROOT / "research/triangle/v61_render_evidence.py"

pytestmark = pytest.mark.skipif(not MANIFEST.exists(),
                                reason="archived claim-grade manifest not present")


@pytest.fixture
def man():
    return json.loads(MANIFEST.read_text())


def _refuses(m, match):
    with pytest.raises(R.Refuse, match=match):
        R.validate(m)


# --- the archived manifest must actually pass, or every negative test is vacuous ------

def test_the_archived_manifest_validates(man):
    v = R.validate(man)
    assert v["minimal"] == ["core+dram+noc+nop"]
    assert v["quantum"] > 0
    assert set(v["comps"]) == {"core", "dram", "noc", "nop"}


# --- the two booleans, which were the ONLY previous check -----------------------------

@pytest.mark.parametrize("patch", [{"complete": False}, {"complete": None}])
def test_refuses_an_incomplete_manifest(man, patch):
    man.update(patch)
    _refuses(man, "complete=")


def test_refuses_a_failed_gate(man):
    man["gate"]["passed"] = False
    _refuses(man, "gate.passed=False")


# --- recomputation: the summary is no longer trusted ---------------------------------

def test_refuses_when_summary_row_status_disagrees_with_the_rows(man):
    """A summary that calls the crossing row `below` must not be renderable."""
    man["summary"]["row_status"]["full"] = "below"
    _refuses(man, "recomputed row_status disagrees")


def test_refuses_when_summary_hides_a_crossing_coalition(man):
    man["summary"]["minimal_crossing_coalitions"] = []
    _refuses(man, "minimal crossing coalitions disagree")


def test_refuses_when_summary_leave_one_out_is_edited(man):
    man["summary"]["leave_one_out"]["nop"]["below_limit"] = False
    _refuses(man, "leave-one-out nop")


def test_refuses_when_summary_claims_no_indeterminate_row_but_one_exists(man):
    """Sit a row exactly on the limit: it becomes indeterminate and the summary is stale."""
    man["rows"]["core-dram-noc"]["periodic_peak_k"] = man["thermal_limit_k"]
    man["rows"]["core-dram-noc"]["margin_to_limit_k"] = 0.0
    _refuses(man, "recomputed row_status disagrees")


# --- subset enumeration ---------------------------------------------------------------

def test_refuses_a_missing_subset(man):
    del man["rows"]["noc-nop"]
    del man["summary"]["row_status"]["noc-nop"]
    _refuses(man, "non-empty subsets")


def test_refuses_a_row_whose_components_do_not_match_its_key(man):
    man["rows"]["noc-nop"]["components"] = ["core", "noc"]
    _refuses(man, "do not tag to its own key")


# --- per-row integrity ----------------------------------------------------------------

def test_refuses_a_non_finite_result(man):
    man["rows"]["core"]["periodic_peak_k"] = float("nan")
    _refuses(man, "is not finite")


def test_refuses_an_unconverged_row(man):
    man["rows"]["core"]["cycles"] = 1
    _refuses(man, "unconverged")


def test_refuses_an_incomplete_row(man):
    man["rows"]["core"]["complete"] = False
    _refuses(man, "row is not complete")


def test_refuses_rows_built_with_different_binaries(man):
    man["rows"]["core"]["hotspot_sha256"] = "d" * 64
    _refuses(man, "hotspot_sha256 differs")


def test_refuses_rows_with_different_staged_inputs(man):
    man["rows"]["core"]["input_hashes"]["config"] = "d" * 64
    _refuses(man, "staged input hashes differ")


def test_refuses_when_two_rows_share_a_trace(man):
    """Equal trace hashes would mean one masked trace was replayed for two subsets."""
    man["rows"]["core"]["trace_sha256"] = man["rows"]["noc"]["trace_sha256"]
    _refuses(man, "share a trace hash")


def test_per_row_trace_hashes_are_expected_to_differ(man):
    """The converse: distinct traces per subset is correct, not a violation."""
    hashes = {r["trace_sha256"] for r in man["rows"].values()}
    assert len(hashes) == len(man["rows"])
    R.validate(man)


def test_refuses_when_the_energy_ledger_does_not_reproduce_a_row(man):
    man["component_energy_j"]["nop"] *= 1.01
    _refuses(man, "retained energy != sum of its components")


def test_refuses_a_margin_that_disagrees_with_the_limit(man):
    man["rows"]["full"]["margin_to_limit_k"] = 99.0
    _refuses(man, "margin_to_limit_k disagrees")


# --- the exact quantisation boundary --------------------------------------------------

@pytest.mark.parametrize("periodic,expect", [
    (330.01, "crossing"),
    (330.00, "indeterminate"),   # the ambiguous case the old doc did not state
    (329.995, "indeterminate"),
    (329.99, "below"),
    (329.98, "below"),
    (330.02, "crossing"),
])
def test_classification_boundary_is_exact(periodic, expect):
    assert R.classify(periodic, 330.0, 0.01) == expect


# --- external facts must be re-checkable, not bare literals ---------------------------

def test_external_fact_refuses_a_value_its_source_no_longer_states():
    with pytest.raises(R.Refuse, match="matches"):
        R.external_fact("earlier_binary_hash_doc", "`" + "f" * 64 + "`", "a bogus hash")


def test_external_fact_refuses_an_ambiguous_pattern():
    """A pattern matching several lines could silently pick the wrong row."""
    with pytest.raises(R.Refuse, match="matches"):
        R.external_fact("grid128_doc", r"\|", "a pattern that matches every table row")


def test_external_fact_returns_the_grid128_blocks_and_a_citation():
    (steady, periodic), cite = R.external_fact(
        "grid128_doc", r"grid128-max.*?\(`(\w+)`\).*?\(`(\w+)`\)", "grid128 blocks")
    assert steady.startswith("ubuf_") and periodic.startswith("ubuf_")
    assert cite.startswith("docs/V6_PHYSICAL_TRACE_GATE.md:")


# --- end to end: the document is generated, and its numbers move with the rows --------

def _render(manifest: dict, tmp_path: Path) -> str:
    tmp_path.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "m.json"
    src.write_text(json.dumps(manifest))
    out = tmp_path / "doc.md"
    p = subprocess.run([sys.executable, str(SCRIPT), str(src), str(out)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert p.returncode == 0, p.stdout + p.stderr
    return out.read_text()


def test_render_emits_the_document(man, tmp_path):
    text = _render(man, tmp_path)
    assert "unique minimal crossing coalition in this factorial" in text
    assert "reported-argmax changes" in text
    assert "registry-instance-unbound" in text
    # the necessity claim must be labelled as arithmetic, not presented as a finding
    assert "arithmetic consequence" in text
    # and the removal deltas must be in the table
    assert "removal delta (K)" in text


def test_render_refuses_and_writes_nothing_when_validation_fails(man, tmp_path):
    man["summary"]["row_status"]["full"] = "below"
    src = tmp_path / "m.json"
    src.write_text(json.dumps(man))
    out = tmp_path / "doc.md"
    p = subprocess.run([sys.executable, str(SCRIPT), str(src), str(out)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert p.returncode == 2
    assert not out.exists(), "a refused render must not leave a partial document"


def test_the_uplift_ratio_range_is_computed_not_a_literal(man, tmp_path):
    """The old generator hard-coded "1.9-5.0%". Perturbing a row must move the printed range."""
    base = _render(man, tmp_path / "a")
    assert "1.89%" in base and "5.02%" in base
    hot = copy.deepcopy(man)
    r = hot["rows"]["noc"]                                  # the widest-ratio row
    r["periodic_peak_k"] = round(r["mean_steady_peak_k"] + 0.60, 2)
    r["margin_to_limit_k"] = hot["thermal_limit_k"] - r["periodic_peak_k"]
    hot["summary"]["uplift_k"]["noc"] = round(r["periodic_peak_k"] - r["mean_steady_peak_k"], 4)
    moved = _render(hot, tmp_path / "b")
    assert "5.02%" not in moved, "the range was transcribed, not computed"
    rise = r["mean_steady_peak_k"] - hot["ambient_k"]
    want = 100 * (r["periodic_peak_k"] - r["mean_steady_peak_k"]) / rise
    assert f"{want:.2f}%" in moved, f"expected the recomputed {want:.2f}% ratio"


def test_the_grid128_blocks_are_read_from_their_source(man, tmp_path):
    text = _render(man, tmp_path)
    assert "docs/V6_PHYSICAL_TRACE_GATE.md:" in text, "the citation must be printed"
    assert "externally supplied, not from this manifest" in text


def test_the_document_does_not_claim_fresh_execution_is_proven(man, tmp_path):
    """`all_rows_fresh` echoes a module constant; printing it as evidence overstated it."""
    text = _render(man, tmp_path)
    assert "asserted by policy, not proven" in text
    assert "15 solver executions from 15 reads of a cache" in text


def test_the_document_does_not_present_near_exact_agreement_as_repeatability(man, tmp_path):
    text = _render(man, tmp_path)
    assert "not repeatability evidence" in text
    assert "byte-identical" in text
    # and the delta must be printed with enough precision to be non-zero
    assert "1.245e-07" in text, "0.000000 hid a nonzero residual behind %.6f"
