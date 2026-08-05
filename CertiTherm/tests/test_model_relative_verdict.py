"""The verdict must carry its model, and the solver gap must never reach the slack silently."""

from __future__ import annotations

import pytest

from CertiTherm.model_relative_verdict import (
    CrossModelGap, ModelRelativeVerdict, ThermalModel,
)


def _hotspot():
    return ThermalModel(solver="hotspot", model_id="grid128-avg", package_id="default",
                        endpoint="tool_compatible", operator_sha256="a" * 64,
                        binary_sha256="b" * 64)


def _fem():
    return ThermalModel(solver="dolfinx", model_id="p1-cell128", package_id="default",
                        endpoint="tool_compatible", operator_sha256="c" * 64)


def _gap(delta=0.0708, row=4.9901, tight=1.8179, cases=("transformer/arch_b",)):
    return CrossModelGap(reference=_fem(), delta_certified_k=delta, row_wise_band_k=row,
                         tight_bound_k=tight, measured_on=cases)


def test_a_verdict_cannot_exist_without_a_model():
    with pytest.raises(TypeError):
        ModelRelativeVerdict(status="CERTIFIED", certified_peak_k=329.1,   # type: ignore[call-arg]
                             ceiling_k=329.94, case="x")


def test_a_model_without_an_operator_digest_is_refused():
    with pytest.raises(ValueError, match="operator_sha256"):
        ThermalModel(solver="hotspot", model_id="grid128-avg", package_id="default",
                     endpoint="tool_compatible", operator_sha256="short")


def test_the_sentence_always_names_the_model_and_never_stands_alone():
    verdict = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED",
                                   certified_peak_k=329.1662, ceiling_k=329.94,
                                   case="transformer/arch_b", gaps=(_gap(),))
    sentence = verdict.sentence()
    assert "hotspot/grid128-avg@default" in sentence, "the verdict does not name its model"
    assert "with respect to" in sentence
    assert "+0.0708" in sentence and "dolfinx" in sentence, (
        "the measured disagreement is not reported beside the verdict"
    )
    assert sentence.strip() != "CERTIFIED"


def test_the_gap_is_not_subtracted_from_the_slack():
    bare = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED", certified_peak_k=329.1662,
                                ceiling_k=329.94, case="c")
    with_gap = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED",
                                    certified_peak_k=329.1662, ceiling_k=329.94, case="c",
                                    gaps=(_gap(cases=("c",)),))
    assert with_gap.slack_k == pytest.approx(bare.slack_k), (
        "attaching a measured disagreement changed the slack; it is being folded in silently"
    )
    assert with_gap.as_dict()["slack_k"] == pytest.approx(bare.as_dict()["slack_k"])


def test_the_bound_restatement_is_a_different_object_with_a_different_model():
    verdict = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED",
                                   certified_peak_k=329.1662, ceiling_k=329.94,
                                   case="transformer/arch_b", gaps=(_gap(),))
    restated = verdict.verdict_if_gap_were_a_bound("dolfinx")
    assert restated.status == "UNRESOLVED", (
        "an upper bound above the ceiling means the bound FAILED TO CERTIFY; calling it REFUTED "
        "manufactures a refutation from a failed certification. This test asserted REFUTED until "
        "peer review pointed out the error -- a test can pin a defect as firmly as a feature."
    )
    assert restated.model.solver == "max(hotspot,dolfinx)", (
        "the restated verdict claims the original model; it is a claim about the PAIR"
    )
    assert verdict.status == "CERTIFIED", "the restatement mutated the original verdict"


def test_restating_against_a_model_never_compared_with_is_refused():
    verdict = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED", certified_peak_k=329.0,
                                   ceiling_k=329.94, case="c", gaps=(_gap(cases=("c",)),))
    with pytest.raises(ValueError, match="never compared"):
        verdict.verdict_if_gap_were_a_bound("3d-ice")


def test_a_gap_measured_on_ANOTHER_case_cannot_be_applied_to_this_one():
    """`measured_on` was required at construction and never checked at use -- the open back door."""
    verdict = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED", certified_peak_k=329.0,
                                   ceiling_k=329.94, case="resnet50/arch_a",
                                   gaps=(_gap(cases=("transformer/arch_b",)),))
    with pytest.raises(ValueError, match="not on 'resnet50/arch_a'"):
        verdict.verdict_if_gap_were_a_bound("dolfinx")


def test_a_bound_that_DOES_certify_is_reported_as_certified():
    """The other branch: a small gap on top of a large slack certifies the PAIR."""
    verdict = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED", certified_peak_k=322.0,
                                   ceiling_k=329.94, case="c",
                                   gaps=(_gap(tight=1.0, row=2.0, cases=("c",)),))
    restated = verdict.verdict_if_gap_were_a_bound("dolfinx")
    assert restated.status == "CERTIFIED"
    assert restated.certified_peak_k == pytest.approx(323.0)


def test_a_gap_without_named_cases_is_refused():
    with pytest.raises(ValueError, match="measured_on is empty"):
        CrossModelGap(reference=_fem(), delta_certified_k=0.07, row_wise_band_k=5.0,
                      tight_bound_k=1.8, measured_on=())


def test_a_tight_aggregation_above_the_row_wise_one_is_refused():
    with pytest.raises(ValueError, match="exceeds the row-wise"):
        CrossModelGap(reference=_fem(), delta_certified_k=0.07, row_wise_band_k=1.0,
                      tight_bound_k=2.0, measured_on=("c",))


@pytest.mark.parametrize("field_name", ["delta_certified_k", "row_wise_band_k", "tight_bound_k"])
def test_a_non_finite_gap_is_refused(field_name):
    kwargs = {"reference": _fem(), "delta_certified_k": 0.07, "row_wise_band_k": 5.0,
              "tight_bound_k": 1.8, "measured_on": ("c",)}
    kwargs[field_name] = float("nan")
    with pytest.raises(ValueError, match="cannot be reported"):
        CrossModelGap(**kwargs)


@pytest.mark.parametrize("status,peak", [("CERTIFIED", 331.0), ("REFUTED", 320.0)])
def test_a_status_contradicting_its_own_numbers_is_refused(status, peak):
    with pytest.raises(ValueError, match="contradicts its own numbers"):
        ModelRelativeVerdict(model=_hotspot(), status=status, certified_peak_k=peak,
                             ceiling_k=329.94, case="c")


def test_the_serialised_form_marks_the_gap_as_a_measurement():
    verdict = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED", certified_peak_k=329.0,
                                   ceiling_k=329.94, case="c", gaps=(_gap(cases=("c",)),))
    payload = verdict.as_dict()
    assert "cross_model_gaps" in payload and "model" in payload
    assert payload["cross_model_gaps"][0]["note"].startswith("MEASURED")
    assert payload["cross_model_gaps"][0]["measured_on"] == ["c"]


def test_an_unresolved_restatement_reports_the_BOUND_not_the_original_peak():
    """Otherwise it prints a positive slack on a verdict that failed to certify.

    The first fix for the REFUTED/UNRESOLVED error carried the original peak, so the returned
    verdict said `slack = +0.7738 K` while being UNRESOLVED precisely because the bound exceeded
    the ceiling. A reader sees room where there is none.
    """
    verdict = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED",
                                   certified_peak_k=329.1662, ceiling_k=329.94,
                                   case="transformer/arch_b", gaps=(_gap(),))
    restated = verdict.verdict_if_gap_were_a_bound("dolfinx")
    assert restated.status == "UNRESOLVED"
    assert restated.certified_peak_k == pytest.approx(329.1662 + 1.8179)
    assert restated.slack_k < 0.0, (
        "an UNRESOLVED restatement reported POSITIVE slack; it is unresolved because the bound "
        "exceeded the ceiling, so the number a reader sees must say that"
    )


def test_a_pair_over_two_packages_or_endpoints_is_refused():
    """Combining models that observe different things describes neither."""
    other = ThermalModel(solver="dolfinx", model_id="p1", package_id="standard",
                         endpoint="tool_compatible", operator_sha256="d" * 64)
    gap = CrossModelGap(reference=other, delta_certified_k=0.07, row_wise_band_k=2.0,
                        tight_bound_k=1.0, measured_on=("c",))
    verdict = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED", certified_peak_k=322.0,
                                   ceiling_k=329.94, case="c", gaps=(gap,))
    with pytest.raises(ValueError, match="package_id"):
        verdict.verdict_if_gap_were_a_bound("dolfinx")


def test_the_pair_digest_is_a_real_digest_and_separates_different_pairs():
    """It used to be two TRUNCATED hashes joined by '+', which is the SHA-256 of nothing."""
    v = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED", certified_peak_k=322.0,
                             ceiling_k=329.94, case="c",
                             gaps=(_gap(tight=1.0, row=2.0, cases=("c",)),))
    a = v.verdict_if_gap_were_a_bound("dolfinx").model.operator_sha256
    assert len(a) == 64 and all(ch in "0123456789abcdef" for ch in a)
    # A different bound is a different hypothetical claim and must not share an identity.
    w = ModelRelativeVerdict(model=_hotspot(), status="CERTIFIED", certified_peak_k=322.0,
                             ceiling_k=329.94, case="c",
                             gaps=(_gap(tight=1.5, row=2.0, cases=("c",)),))
    assert w.verdict_if_gap_were_a_bound("dolfinx").model.operator_sha256 != a


def test_only_a_certified_verdict_can_be_restated():
    verdict = ModelRelativeVerdict(model=_hotspot(), status="REFUTED", certified_peak_k=331.0,
                                   ceiling_k=329.94, case="c",
                                   gaps=(_gap(tight=1.0, row=2.0, cases=("c",)),))
    with pytest.raises(ValueError, match="only a CERTIFIED verdict"):
        verdict.verdict_if_gap_were_a_bound("dolfinx")
