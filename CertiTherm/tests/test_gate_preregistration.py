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
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / "docs/registration/v7_independent_model_gate.json"
CCFA = ROOT / "ccfa.yaml"

pytestmark = pytest.mark.skipif(not PREREG.exists(), reason="gate preregistration not present")


def _prereg() -> dict:
    return json.loads(PREREG.read_text())


def _entry() -> dict:
    experiments = yaml.safe_load(CCFA.read_text())["experiments"]
    return next(e for e in experiments if e["id"] == "INDEPENDENT-MODEL-GATE")


def test_the_state_machine_points_at_this_exact_preregistration():
    """If the artifact is edited, this fails -- which is the whole point."""
    live = hashlib.sha256(PREREG.read_bytes()).hexdigest()
    assert _entry()["preregistration_sha256"] == live, (
        "docs/registration/v7_independent_model_gate.json has changed since ccfa.yaml recorded "
        "its hash. Either restore it or register a new preregistered attempt with its own hash; "
        "do not silently re-point the state machine.")


def test_no_result_may_be_recorded_while_the_state_is_unrun():
    p = _prereg()
    if p["state"] != "PREREGISTERED_UNRUN":
        pytest.skip("the gate has run; this invariant applies before execution")
    assert p["prior_prediction"]["actual_outcome"] is None
    assert _entry()["status"] == "preregistered_unrun"


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
    experiments = yaml.safe_load(CCFA.read_text())["experiments"]
    v61 = next(e for e in experiments if e["id"] == "V6-1")
    assert "OUT OF FAMILY" in v61["disposition"]
    assert "cannot enter a DSOS certificate" in v61["disposition"]
    assert "out_of_family" in _prereg()["instance"]


def test_the_allowed_conclusions_refuse_the_obvious_overclaims():
    allowed = _prereg()["allowed_conclusions"]
    for forbidden in ("NOT certificate evidence", "NOT a multi-workload result",
                      "NOT a general transient theorem"):
        assert forbidden in allowed["positive"], forbidden
    assert "does NOT establish that transient boundary flips are absent" in allowed["negative"]
