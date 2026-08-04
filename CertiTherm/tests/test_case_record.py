"""The case contract: declared cases are read exactly, and what is not read is COUNTED."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research" / "triangle" / "robustness"))

from case_record import CASE_RECORD_KEY, CaseRecord, attach, read_cases  # noqa: E402


def _write(tmp_path, name, payload):
    (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")


def test_a_declared_payload_is_read_exactly(tmp_path):
    record = CaseRecord(case="c", nominal_peak_k=320.0, certified_peak_k=321.5, ceiling_k=329.94)
    _write(tmp_path, "a.json", attach({"other": 1}, [record]))
    found, legacy, skipped, _refused = read_cases(tmp_path)
    assert len(found) == 1 and legacy == 0 and not skipped
    assert found[0].uplift_k == pytest.approx(1.5)


def test_a_legacy_payload_is_read_but_COUNTED(tmp_path):
    _write(tmp_path, "b.json", {"case": "c", "nominal_peak_k": 320.0, "certified_peak_k": 321.0})
    found, legacy, skipped, _refused = read_cases(tmp_path)
    assert len(found) == 1 and legacy == 1, (
        "a legacy read must be counted; an uncounted one is how four fifths of a population "
        "stayed invisible"
    )


def test_a_file_that_yields_nothing_is_counted_not_assumed_empty(tmp_path):
    _write(tmp_path, "c.json", {"unrelated": [1, 2, 3]})
    found, legacy, skipped, _refused = read_cases(tmp_path)
    assert not found and legacy == 0 and len(skipped) == 1


def test_an_empty_declaration_is_a_DECLARATION_not_a_gap(tmp_path):
    """A driver saying "I have no cases" must not be counted as a file that failed to parse."""
    _write(tmp_path, "d.json", {CASE_RECORD_KEY: [], "status": "SINGLETON_ENVELOPE"})
    found, legacy, skipped, _refused = read_cases(tmp_path)
    assert not found and legacy == 0 and not skipped


def test_a_certified_peak_below_its_nominal_is_refused():
    with pytest.raises(ValueError, match="below nominal"):
        CaseRecord(case="c", nominal_peak_k=321.0, certified_peak_k=320.0)


@pytest.mark.parametrize("field", ["nominal_peak_k", "certified_peak_k"])
def test_a_non_finite_peak_is_refused(field):
    kwargs = {"case": "c", "nominal_peak_k": 320.0, "certified_peak_k": 321.0}
    kwargs[field] = float("nan")
    with pytest.raises(ValueError, match="UNRESOLVED"):
        CaseRecord(**kwargs)


def test_the_curve_fallback_matches_the_span_exactly(tmp_path):
    """Reading a different span would mix envelopes across a population without saying so."""
    _write(tmp_path, "e.json", {"case": "c", "nominal_peak_k": 320.0,
                                "curve": [{"span": 0.05, "peak_k": 320.2},
                                          {"span": 0.30, "peak_k": 321.0}]})
    found, _legacy, _skipped = read_cases(tmp_path, span=0.30)
    assert found[0].certified_peak_k == pytest.approx(321.0)
    none_found, _l, skipped, _r = read_cases(tmp_path, span=0.70)
    assert not none_found and len(skipped) == 1, "a missing span must not fall back to a nearby one"


def test_a_declaration_is_exclusive_so_the_legacy_counter_can_fall(tmp_path):
    """A migrated driver that still writes the old keys must not be counted twice.

    The legacy counter is the one number that measures migration progress. If a declared payload
    were ALSO scanned by the legacy table, every migrated case would be counted once exactly and
    once as legacy, and the counter would stop falling as drivers migrate -- the metric lying about
    its own subject.
    """
    record = CaseRecord(case="c", nominal_peak_k=320.0, certified_peak_k=321.0)
    payload = attach({"nominal_peak_k": 320.0, "certified_peak_k": 321.0}, [record])
    _write(tmp_path, "f.json", payload)
    found, legacy, skipped, _refused = read_cases(tmp_path)
    assert len(found) == 1, "the declared case was read twice"
    assert legacy == 0, "a declared payload was also scanned by the legacy table"
    assert not skipped
