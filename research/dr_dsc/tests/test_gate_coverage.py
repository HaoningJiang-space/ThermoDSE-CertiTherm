"""Self-contained, torch-only sanity checks for the gate/coverage layer
-- no CertiTherm/scipy dependency, so these are the cheapest to run first.
Run with: python -m pytest research/dr_dsc/tests/test_gate_coverage.py -q

The separation tests below exist because the ORIGINAL Stage A suite tested
only gate_probabilities/soft_coverage/soft_min and therefore completely
missed a critical defect in soft_separation (an action separating nothing
scored 0.731). Stage A is supposed to isolate pure-math bugs; it can only do
that if it covers every pure-math function.
"""
from __future__ import annotations

import pytest
import torch

from research.dr_dsc.gate import (
    gate_probabilities,
    hard_separation,
    separation_magnitude,
    soft_coverage,
    soft_min,
    soft_separation,
)

DTYPE = torch.float64


def _fixture():
    # 2 actions over 2 blocks; action 0 reads block 0, action 1 reads block 1.
    weight = torch.tensor([[1.0, 0.0], [0.0, 1.0]], dtype=DTYPE)
    tolerance = torch.tensor([1e-8, 1e-8], dtype=DTYPE)
    return weight, tolerance


# --------------------------------------------------------------------------
# separation predicates -- the layer where the original bug lived
# --------------------------------------------------------------------------


def test_hard_separation_is_exactly_the_oracle_predicate() -> None:
    weight, tolerance = _fixture()
    # witness 0: differs only in block 0 -> action 0 separates, action 1 does not
    # witness 1: differs in neither -> nothing separates
    delta = torch.tensor([[0.2, 0.0], [0.0, 0.0]], dtype=DTYPE)
    h = hard_separation(delta, weight, tolerance, sep_margin=1e-9)
    assert torch.equal(h, torch.tensor([[1.0, 0.0], [0.0, 0.0]], dtype=DTYPE))


def test_hard_separation_respects_the_tolerance_boundary() -> None:
    weight, tolerance = _fixture()
    # 1e-9 is below tolerance+margin (1.1e-8); 1e-7 is above it.
    delta = torch.tensor([[1e-9, 0.0], [1e-7, 0.0]], dtype=DTYPE)
    h = hard_separation(delta, weight, tolerance, sep_margin=1e-9)
    assert h[0, 0] == 0.0, "sub-tolerance difference must NOT count as separating"
    assert h[1, 0] == 1.0, "above-tolerance difference must count as separating"


def test_soft_separation_is_zero_preserving_at_zero() -> None:
    """REGRESSION: the original form returned sigmoid(1)=0.731 here, scoring a
    completely non-separating action as 73% separating.

    Note the residual limitation, which is inherent rather than a bug: a
    sigmoid centred at `tolerance` with width >> tolerance can only reach ~0.5
    at zero, not ~0. Driving it to ~0 requires width << tolerance (second
    assertion). This is exactly why `hard_separation` is what train.py uses.
    """
    weight, tolerance = _fixture()
    delta = torch.tensor([[0.0, 0.0]], dtype=DTYPE)

    wide = soft_separation(delta, weight, tolerance, sep_margin=1e-9, smoothing=1e-3)
    assert torch.all(wide < 0.5), f"zero separation must not score >= 0.5, got {wide}"

    narrow = soft_separation(
        delta, weight, tolerance, sep_margin=1e-9, smoothing=1e-3, width=1e-10
    )
    assert torch.all(narrow < 1e-6), (
        f"with width << tolerance, zero separation must score ~0, got {narrow}"
    )


def test_soft_separation_is_monotone_in_magnitude() -> None:
    weight, tolerance = _fixture()
    delta = torch.tensor([[0.0, 0.0], [1e-4, 0.0], [1e-2, 0.0], [1.0, 0.0]], dtype=DTYPE)
    h = soft_separation(delta, weight, tolerance, sep_margin=1e-9, smoothing=1e-6)
    column = h[:, 0]
    assert torch.all(column[1:] >= column[:-1]), f"not monotone: {column}"
    assert column[-1] > 0.99, "a clearly separating action must saturate high"


def test_soft_separation_approaches_hard_as_smoothing_shrinks() -> None:
    """smoothing=1e-11, not 1e-9: at 1e-9 the zero row still scores 1.67e-5,
    which exceeds atol here. Verified numerically before this test was run."""
    weight, tolerance = _fixture()
    delta = torch.tensor([[0.2, 0.0], [0.0, 0.0]], dtype=DTYPE)
    hard = hard_separation(delta, weight, tolerance, sep_margin=1e-9)
    soft = soft_separation(delta, weight, tolerance, sep_margin=1e-9, smoothing=1e-11)
    assert torch.allclose(soft, hard, atol=1e-6, rtol=0.0)


def test_separation_magnitude_is_absolute_and_sign_agnostic() -> None:
    weight, tolerance = _fixture()
    delta = torch.tensor([[0.3, 0.0], [-0.3, 0.0]], dtype=DTYPE)
    magnitude = separation_magnitude(delta, weight)
    assert torch.allclose(magnitude[0], magnitude[1], rtol=0.0, atol=1e-12)


def test_soft_separation_rejects_nonpositive_scales() -> None:
    weight, tolerance = _fixture()
    delta = torch.tensor([[0.2, 0.0]], dtype=DTYPE)
    with pytest.raises(ValueError):
        soft_separation(delta, weight, tolerance, sep_margin=1e-9, smoothing=0.0)
    with pytest.raises(ValueError):
        soft_separation(delta, weight, tolerance, sep_margin=1e-9, smoothing=1e-3, width=0.0)


# --------------------------------------------------------------------------
# coverage / soft-min
# --------------------------------------------------------------------------


def test_soft_coverage_matches_hard_or_at_saturated_gates() -> None:
    h = torch.tensor([[1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=DTYPE)
    gates = torch.tensor([1.0, 0.0], dtype=DTYPE)  # only action 0 "selected"
    coverage = soft_coverage(gates, h)
    expected = torch.tensor([1.0, 1.0, 0.0], dtype=DTYPE)
    # rtol=0 so the eps clamp cannot hide behind allclose's default 1e-5 rtol.
    assert torch.allclose(coverage, expected, atol=1e-9, rtol=0.0)


def test_soft_coverage_needs_both_actions_for_full_witness_pool() -> None:
    h = torch.tensor([[1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=DTYPE)
    gates = torch.tensor([1.0, 1.0], dtype=DTYPE)
    coverage = soft_coverage(gates, h)
    assert torch.all(coverage > 1.0 - 1e-6)


def test_soft_coverage_matches_direct_product_at_fractional_gates() -> None:
    h = torch.tensor([[1.0, 1.0], [1.0, 0.0]], dtype=DTYPE)
    gates = torch.tensor([0.3, 0.7], dtype=DTYPE)
    coverage = soft_coverage(gates, h)
    expected = torch.tensor(
        [1.0 - (1 - 0.3) * (1 - 0.7), 1.0 - (1 - 0.3)], dtype=DTYPE
    )
    assert torch.allclose(coverage, expected, atol=1e-12, rtol=0.0)


def test_soft_coverage_gradient_is_finite_and_positive() -> None:
    h = torch.tensor([[1.0, 1.0]], dtype=DTYPE)
    gates = torch.tensor([0.4, 0.6], dtype=DTYPE, requires_grad=True)
    soft_coverage(gates, h).sum().backward()
    assert torch.all(torch.isfinite(gates.grad))
    assert torch.all(gates.grad > 0), "more gate must mean more coverage"


def test_soft_min_lower_bounds_true_min_and_tightens_with_beta() -> None:
    values = torch.tensor([0.2, 0.9, 0.5], dtype=DTYPE)
    loose = soft_min(values, beta=1.0)
    tight = soft_min(values, beta=1000.0)
    true_min = values.min()
    assert loose <= true_min + 1e-9
    assert tight <= true_min + 1e-9
    assert (true_min - tight).abs() < (true_min - loose).abs()


def test_soft_min_rejects_nonpositive_beta() -> None:
    values = torch.tensor([0.2, 0.9], dtype=DTYPE)
    with pytest.raises(ValueError):
        soft_min(values, beta=0.0)


def test_gate_probabilities_are_monotone_in_logit_and_bounded() -> None:
    logits = torch.tensor([-5.0, 0.0, 5.0], dtype=DTYPE)
    gates = gate_probabilities(logits, temperature=1.0)
    assert gates[0] < gates[1] < gates[2]
    assert torch.all((gates > 0.0) & (gates < 1.0))


def test_gate_probabilities_rejects_nonpositive_temperature() -> None:
    with pytest.raises(ValueError):
        gate_probabilities(torch.zeros(2, dtype=DTYPE), temperature=0.0)
