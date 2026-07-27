"""The independent-model gate's preregistration must stay a preregistration.

A preregistration that can be edited after seeing results is not one. These tests make the
guards mechanical instead of an honour system:

- `ccfa.yaml`'s recorded hash must equal the artifact's, so the state machine cannot point at a
  preregistration that has since been rewritten;
- `actual_outcome` must stay null while the state is `PREREGISTERED_UNRUN`, and the prior block
  must be labelled so no consumer can read it as evidence;
- the cited contract is bound by section heading AND document hash, never by line number -- a
  line reference in this project's other registration was stale within an hour of being written,
  because a paragraph was inserted above the cited table;
- the decision rule must be exhaustive, ordered, and validation-first.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

# No YAML parser: PyYAML is not in the pinned requirements.lock, and adding it would change the
# frozen environment that every claim-grade run bootstraps. The two facts these tests need out of
# ccfa.yaml are a 64-hex hash and the presence of specific text, both of which a targeted match
# reads reliably. Hand-rolling a YAML parser would be a second implementation acting as its own
# oracle.

ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / "docs/registration/v7_independent_model_gate.json"
CCFA = ROOT / "ccfa.yaml"

pytestmark = pytest.mark.skipif(not PREREG.exists(), reason="gate preregistration not present")


def _prereg() -> dict:
    return json.loads(PREREG.read_text())


def _ccfa() -> str:
    return CCFA.read_text(encoding="utf-8")


def _recorded_prereg_hash() -> str:
    found = re.findall(r'preregistration_sha256:\s*"([0-9a-f]{64})"', _ccfa())
    assert len(found) == 1, f"expected exactly one recorded preregistration hash, got {found}"
    return found[0]


def _recorded_mapping_hash() -> str:
    found = re.findall(r'stack_mapping_sha256:\s*"([0-9a-f]{64})"', _ccfa())
    assert len(found) == 1, f"expected exactly one recorded mapping hash, got {found}"
    return found[0]


def _gate_status() -> str:
    block = _ccfa().split('- id: "INDEPENDENT-MODEL-GATE"', 1)
    assert len(block) == 2, "ccfa.yaml does not register INDEPENDENT-MODEL-GATE"
    found = re.search(r'status:\s*"([A-Za-z_.0-9]+)"', block[1])
    assert found, "the gate entry records no status"
    return found.group(1)


def test_the_state_machine_points_at_this_exact_preregistration():
    """If the artifact is edited, this fails -- which is the whole point."""
    live = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    assert _recorded_prereg_hash() == live, (
        "docs/registration/v7_independent_model_gate.json has changed since ccfa.yaml recorded "
        "its hash. Either restore it or register a new preregistered attempt with its own hash; "
        "do not silently re-point the state machine.")


def test_no_result_may_be_recorded_before_the_gate_runs():
    p = _prereg()
    if p["state"] != "PREREGISTERED_UNRUN":
        pytest.skip("the gate has run; this invariant applies before execution")
    assert p["prior_prediction"]["actual_outcome"] is None
    # the mapping was rejected before use, so the gate is registered but not runnable
    assert _gate_status() in ("preregistered_unrun", "mapping_rejected_pending_revision",
                              "CLAIM_WITHDRAWN_WITHOUT_INDEPENDENT_VERDICT")


def test_a_rejected_mapping_records_why_and_keeps_the_artifact_unedited():
    """The point of hashing the mapping is that it cannot be revised in place. A rejection is
    recorded beside it; a corrected mapping is a new attempt with its own hash."""
    ccfa = _ccfa()
    if "REJECTED_BEFORE_USE" not in ccfa:
        pytest.skip("no mapping rejection recorded")
    assert "docs/V7_GATE_MAPPING_REVIEW.md" in ccfa
    assert (ROOT / "docs/V7_GATE_MAPPING_REVIEW.md").is_file()
    # and the artifact itself must still hash to what was registered
    assert _recorded_mapping_hash() == hashlib.sha256(MAPPING.read_bytes()).hexdigest()


def test_the_prior_cannot_be_read_as_a_result():
    prior = _prereg()["prior_prediction"]
    assert prior["type"] == "preregistered_prior_NOT_A_RESULT"
    assert "never be overwritten" in prior["invariant"]
    # its rationale must claim fragility, not direction -- the reviewer's correction
    assert "does NOT predict the direction" in prior["rationale"]
    assert prior["confidence"] == "low"


def test_the_contract_citation_is_bound_by_hash_not_line_number():
    c = _prereg()["contract"]
    doc = ROOT / c["document"]
    assert doc.is_file()
    assert hashlib.sha256(doc.read_bytes()).hexdigest() == c["document_sha256"], (
        f"{c['document']} changed after the gate was preregistered; the stop rule this gate "
        f"answers to is no longer the one that was registered")
    assert c["section"] in doc.read_text(), "the cited section heading no longer exists"
    assert "line" not in c or not str(c.get("line", "")).isdigit()


def test_the_pinned_instance_hashes_still_match():
    """The gate must answer about the instance it was registered against."""
    inst = _prereg()["instance"]
    for path_key, hash_key in (("manifest", "manifest_sha256"),
                               ("floorplan", "floorplan_sha256")):
        path = ROOT / inst[path_key]
        assert path.is_file(), f"{inst[path_key]} is missing"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == inst[hash_key]


def test_the_decision_rule_is_ordered_exhaustive_and_validation_first():
    rule = _prereg()["decision_rule"]
    outcomes = [b["outcome"] for b in rule["branches"]]
    # validation precedes classification: a NaN makes every numeric predicate false
    assert outcomes[0] == "INVALID_OR_UNRESOLVED"
    assert rule["precedence"][0] == "INVALID_OR_UNRESOLVED"
    assert rule["branches"][-1]["condition"] == "otherwise", "the rule must be exhaustive"
    assert set(outcomes) <= set(rule["precedence"])
    # every outcome must have a stated consequence
    consequences = _prereg()["consequences"]
    for outcome in set(outcomes):
        base = outcome.replace("INVALID_OR_", "")
        assert outcome in consequences or base in consequences, f"{outcome} has no consequence"


def test_the_positive_verdict_uses_the_conservative_bound_directions():
    """An earlier draft said "the LOWER convergence bound must satisfy S < 330 <= P", which is
    sign-wrong for S and would have admitted a positive verdict on an unresolved steady value."""
    branches = {b["outcome"]: b["condition"] for b in _prereg()["decision_rule"]["branches"]}
    positive = branches["FLIP_REPRODUCES"]
    assert "S_U <" in positive and "P_L >=" in positive, positive
    assert "conservative_direction" in _prereg()["decision_rule"]


def test_the_ratio_is_diagnostic_only_and_says_why():
    """R = U/(limit-S) has a pole at the decision boundary AND is algebraically equivalent to
    P >= limit for S < limit, so it carries no decision information at all."""
    ref = _prereg()["hotspot_reference"]
    assert "DIAGNOSTIC ONLY" in ref["ratio_note"]
    assert "algebraically equivalent" in ref["ratio_note"]
    # A standalone `R` token must not appear in any branch CONDITION. Substring matching is too
    # loose here: "R >=" occurs inside "P_LOWER >= 330".
    import re
    for branch in _prereg()["decision_rule"]["branches"]:
        assert not re.search(r"\bR\b", branch["condition"]), branch["condition"]


def test_no_fitted_calibration_is_permitted():
    """The deleted POWER_SCALE=16 adapter existed to force absolute agreement. The guard must
    name it, so nobody reinvents it."""
    guards = " ".join(_prereg()["guards"])
    assert "POWER_SCALE is 1 by construction" in guards
    assert "POWER_SCALE=16" in guards
    assert "unit conversion is not calibration" in guards
    # and ambiguity must be a robustness set, not a search
    assert "never tried in sequence" in guards


def test_the_out_of_family_disposition_is_stated_in_both_places():
    ccfa = _ccfa()
    v61 = ccfa.split('- id: "V6-1"', 1)
    assert len(v61) == 2, "ccfa.yaml does not register V6-1"
    entry = v61[1].split('- id: "', 1)[0]
    assert "OUT OF FAMILY" in entry
    assert "cannot enter a DSOS certificate" in entry
    assert "out_of_family" in _prereg()["instance"]


def test_the_allowed_conclusions_refuse_the_obvious_overclaims():
    allowed = _prereg()["allowed_conclusions"]
    for forbidden in ("NOT certificate evidence", "NOT a multi-workload result",
                      "NOT a general transient theorem"):
        assert forbidden in allowed["positive"], forbidden
    assert "does NOT establish that transient boundary flips are absent" in allowed["negative"]


# --- the frozen stack mapping ----------------------------------------------------------
# The one decision that can make the gate meaningless. Frozen and hashed before any gate
# output is examined, so post-hoc tuning is detectable.

MAPPING = ROOT / "docs/registration/v7_gate_stack_mapping.json"


def _mapping() -> dict:
    return json.loads(MAPPING.read_text())


def _manifest() -> dict:
    return json.loads((ROOT / _prereg()["instance"]["manifest"]).read_text())


@pytest.mark.skipif(not MAPPING.exists(), reason="stack mapping not present")
def test_no_hash_in_the_mapping_is_transcribed():
    """An earlier draft of this file carried two hashes I typed from a rendered document that
    shows only the first 16 characters, inventing the remaining 48. Correct prefix, correct
    length, valid hex, entirely fabricated -- a prefix check would have passed them. Every hash
    must equal what the manifest actually records."""
    src, manifest = _mapping()["sources"], _manifest()
    assert src["hotspot_config_sha256"] == manifest["input_hashes"]["config"]
    assert src["hotspot_materials_sha256"] == manifest["input_hashes"]["materials"]
    assert src["hotspot_binary_sha256"] == manifest["hotspot_sha256"]
    assert hashlib.sha256((ROOT / src["floorplan"]).read_bytes()).hexdigest() \
        == src["floorplan_sha256"]


@pytest.mark.skipif(not MAPPING.exists(), reason="stack mapping not present")
def test_the_state_machine_points_at_this_exact_mapping():
    assert _recorded_mapping_hash() == hashlib.sha256(MAPPING.read_bytes()).hexdigest()


@pytest.mark.skipif(not MAPPING.exists(), reason="stack mapping not present")
def test_the_mapping_points_at_this_exact_preregistration():
    assert _mapping()["preregistration_sha256"] == hashlib.sha256(PREREG.read_bytes()).hexdigest()


@pytest.mark.skipif(not MAPPING.exists(), reason="stack mapping not present")
def test_the_mesh_reproduces_the_hotspot_grid_exactly():
    """This is what makes the two observation operators comparable at all."""
    g = _mapping()["geometry"]
    assert g["cell_length_um"] * 64 == pytest.approx(g["chip_length_um"], rel=0, abs=1e-9)
    assert g["cell_width_um"] * 64 == pytest.approx(g["chip_width_um"], rel=0, abs=1e-9)
    assert _mapping()["numerics"]["output_quantity"] == "MAXIMUM", (
        "AVERAGE would be a different observation operator than HotSpot's grid_map_mode=max")


@pytest.mark.skipif(not MAPPING.exists(), reason="stack mapping not present")
def test_the_boundary_preserves_total_conductance_not_per_area_htc():
    """Preserving HotSpot's per-area HTC over its 60 mm sink would leave 1.08 W/K of a 10.00 W/K
    heat path -- silently removing 90% of the cooling."""
    b, g = _mapping()["boundary"], _mapping()["geometry"]
    area_m2 = (g["chip_length_um"] * 1e-6) * (g["chip_width_um"] * 1e-6)
    conductance = b["heat_transfer_coefficient_w_per_m2_k"] * area_m2
    assert conductance == pytest.approx(1.0 / 0.10, rel=1e-9), (
        f"effective conductance {conductance} W/K != HotSpot's 1/r_convec = 10.0 W/K")
    # the two unit systems must agree
    assert b["heat_transfer_coefficient_w_per_um2_k"] == pytest.approx(
        b["heat_transfer_coefficient_w_per_m2_k"] * 1e-12, rel=1e-12)
    assert "rejected_alternative" in b, "the rejected derivation must stay visible"


@pytest.mark.skipif(not MAPPING.exists(), reason="stack mapping not present")
def test_the_secondary_path_is_absent_because_the_config_disables_it():
    m = _mapping()
    assert m["passive_layers_below"] == []
    assert "-model_secondary 0" in m["below_note"]
    assert "determination, not a choice" in m["below_note"]


@pytest.mark.skipif(not MAPPING.exists(), reason="stack mapping not present")
def test_material_properties_are_unit_converted_not_reassigned():
    """W/(m K) -> W/(um K) is 1e-6; J/(m^3 K) -> J/(um^3 K) is 1e-18. Silicon 130 / 1630300 and
    copper 400 / 3.55e6 come from the pinned materials file."""
    die = _mapping()["die"]
    assert die["thermal_conductivity_w_per_um_k"] == pytest.approx(130.0 * 1e-6, rel=1e-12)
    assert die["volumetric_heat_capacity_j_per_um3_k"] == pytest.approx(1630300.0 * 1e-18,
                                                                       rel=1e-12)
    above = {layer["layer_id"]: layer for layer in _mapping()["passive_layers_above"]}
    assert above["tim"]["thermal_conductivity_w_per_um_k"] == pytest.approx(4.0e-6, rel=1e-12)
    for copper in ("spreader", "sink"):
        assert above[copper]["thermal_conductivity_w_per_um_k"] == pytest.approx(400.0e-6,
                                                                                rel=1e-12)
    assert above["spreader"]["thickness_um"] == 1000.0 and above["sink"]["thickness_um"] == 6900.0


@pytest.mark.skipif(not MAPPING.exists(), reason="stack mapping not present")
def test_the_robustness_set_has_at_least_two_members_and_is_not_a_search():
    r = _mapping()["robustness_set"]
    assert len(r["members"]) >= 2
    assert "BOTH members to reproduce" in r["why"]
    assert "never in sequence" in r["why"]


@pytest.mark.skipif(not MAPPING.exists(), reason="stack mapping not present")
def test_fitted_calibration_is_prohibited_here_too():
    p = " ".join(_mapping()["prohibitions"])
    assert "POWER_SCALE is 1 by construction" in p
    assert "not calibration" in p


# --- the terminal outcome and the locality result --------------------------------------
# The gate closed without a verdict. The one thing that must never drift is the WORDING: no
# 3D-ICE or FEM run happened, so nothing here may be presented as a convergence result.

DOC = ROOT / "docs/V7_TRANSIENT_LOCALITY.md"


def test_the_gate_closed_without_a_verdict():
    assert _gate_status() == "CLAIM_WITHDRAWN_WITHOUT_INDEPENDENT_VERDICT"
    ccfa = _ccfa()
    assert "MODEL-ROBUST SUPPORT COULD NOT BE ESTABLISHED" in ccfa
    assert "NOT because an independent model" in ccfa
    assert "not a convergence result" in ccfa


@pytest.mark.skipif(not DOC.exists(), reason="locality report not present")
def test_the_withdrawal_is_never_phrased_as_a_refutation():
    doc = DOC.read_text()
    assert "No 3D-ICE or FEM run was performed and no gate output exists" in doc
    assert "not because an independent model disproved it" in doc
    assert "Nothing here is a convergence result" in doc
    for forbidden in ("3D-ICE disproved", "FEM disproved", "refuted by an independent",
                      "independent model showed"):
        assert forbidden.lower() not in doc.lower(), forbidden


@pytest.mark.skipif(not DOC.exists(), reason="locality report not present")
def test_every_number_in_the_report_is_recomputed_not_transcribed():
    """The report is generated. Regenerating it must reproduce the committed file byte for byte,
    which is the only way to know no figure was typed in by hand."""
    import subprocess
    out = ROOT / "docs/V7_TRANSIENT_LOCALITY.md"
    p = subprocess.run([sys.executable, str(ROOT / "research/triangle/v7_locality_report.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert p.returncode == 0, p.stderr
    assert p.stdout == out.read_text(), (
        "docs/V7_TRANSIENT_LOCALITY.md is not the output of v7_locality_report.py; regenerate it "
        "instead of editing it")


MANIFEST_S5 = ROOT / "artifacts_receipts/v61_cg5_schema5/v61_manifest.json"


@pytest.mark.skipif(not MANIFEST_S5.exists(), reason="schema-5 manifest not present")
def test_the_locality_measurement_holds_and_is_quantisation_safe():
    """The load-bearing measurement: adding 45% of the dissipated energy moves the steady rise by
    3.6 K and the uplift by at most one or two output quanta."""
    sys.path.insert(0, str(ROOT / "research/triangle"))
    from research.triangle.v7_locality_report import analyse
    a = analyse()
    assert 0.44 < a["added_energy_frac"] < 0.46
    assert a["d_rise_k"] > 3.0, "the steady rise must move substantially"
    # the raw uplift change is only a couple of quanta, so the claim is an upper bound
    assert a["d_uplift_quanta"] < 3.0, "if this grows, the bound-based phrasing must be revisited"
    assert a["sensitivity_ratio"] > 100.0
    # and the correlation split is the sharper statement
    assert a["corr_core_energy_rise"] > 0.9
    assert abs(a["corr_core_energy_uplift"]) < 0.5, "uplift must show no energy trend"


def test_the_penetration_depth_is_below_the_die_thickness():
    """The explanation offered for the measurement. delta < t_die is why remote sources cannot
    contribute local ripple."""
    from research.triangle.v7_locality_report import analyse, penetration_depth_m
    a = analyse()
    assert a["delta_si_um"] < a["t_die_um"], "the argument requires the wave to stay inside the die"
    assert a["delta_tim_um"] < a["tim_thickness_um"]
    # the formula, checked independently of the report
    import math
    expected = math.sqrt(2.0 * (a["k_si"] / a["c_si"]) / a["omega"]) * 1e6
    assert a["delta_si_um"] == pytest.approx(expected, rel=1e-12)


@pytest.mark.skipif(not DOC.exists(), reason="locality report not present")
def test_the_report_states_its_scope_limits():
    doc = DOC.read_text()
    assert "out of the certified family" in doc
    assert "none of this is certificate evidence" in doc
    assert "1-D" in doc or "one-dimensional" in doc
    assert "no cross-workload predictor is claimed" in doc
    assert "No independent thermal model has validated any number" in doc
