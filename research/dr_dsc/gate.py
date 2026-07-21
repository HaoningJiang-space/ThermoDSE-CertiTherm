"""Continuous relaxation of discrete action selection over the FROZEN,
already-registered measurement library.

This module never chooses a final action set. It produces (a) a
differentiable worst-case coverage loss for training gate logits with
gradient descent, and (b) a cost-aware ranking usable to warm-start rounding.
Pure tensor ops -- no CertiTherm dependency, GPU-batchable, and the one part
of this prototype that's cheap to unit-test without a GPU (see
tests/test_gate_coverage.py).

Design note (corrected after peer review 2026-07-21): the separation
indicator `h` is NOT on the gradient path. `weight` and `delta` are frozen
constants (registered action vectors and exact-oracle witnesses), never
parameters, so the ONLY learnable quantity is the gate vector. The default
is therefore `hard_separation` -- the exact 0/1 predicate CertiTherm itself
uses -- and the relaxation lives purely in the gates. That makes the
objective exactly the multilinear extension of the underlying set-cover,
rather than a smoothed approximation of it.

`soft_separation` is retained for a future extension where the measurement
vectors themselves become continuous design variables. Its earlier form was
numerically broken (an action separating NOTHING scored 0.731); see its
docstring.
"""
from __future__ import annotations

import torch


def gate_probabilities(logits: torch.Tensor, temperature: float = 1.0) -> torch.Tensor:
    """g_a = sigmoid(logit_a / temperature), in (0, 1)."""
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    return torch.sigmoid(logits / temperature)


def separation_magnitude(delta: torch.Tensor, weight: torch.Tensor) -> torch.Tensor:
    """|w_a^T (p^S - p^R)| for every (witness, action) pair.

    delta:  (B, n)   witness power differences
    weight: (A, n)   registered measurement vectors
    returns (B, A)
    """
    return torch.einsum("an,bn->ba", weight, delta).abs()


def hard_separation(
    delta: torch.Tensor,
    weight: torch.Tensor,
    tolerance: torch.Tensor,
    sep_margin: float,
) -> torch.Tensor:
    """Exact 0/1 separation predicate: |w_a^T delta| > tolerance_a + sep_margin.

    This mirrors CertiTherm's own separation test, so the relaxation's notion
    of "action a separates witness b" agrees exactly with the exact oracle's.
    Returned as a float tensor so it composes with `soft_coverage`, but it
    carries no gradient (and needs none -- see the module docstring).
    """
    return (
        separation_magnitude(delta, weight) > tolerance.unsqueeze(0) + sep_margin
    ).to(delta.dtype)


def soft_separation(
    delta: torch.Tensor,
    weight: torch.Tensor,
    tolerance: torch.Tensor,
    sep_margin: float,
    smoothing: float,
    width: float | None = None,
) -> torch.Tensor:
    """Zero-preserving smooth relaxation of `hard_separation`.

    h_a(omega) = sigmoid((smooth_abs(w_a^T delta) - tolerance_a - sep_margin) / width)
    with the ZERO-PRESERVING smooth absolute value

        smooth_abs(x) = sqrt(x^2 + smoothing^2) - smoothing,

    so smooth_abs(0) == 0 exactly.

    The earlier implementation used `sqrt(x^2 + s^2)` WITHOUT subtracting `s`,
    and reused `s` as the sigmoid width. At x=0 that gave
    sigmoid((s - tol)/s) ~ sigmoid(1) = 0.731: an action that separates
    nothing was scored as 73% separating, and the function was flat across
    x in [0, 1e-6], i.e. blind at the 1e-8 tolerance scale it was meant to
    discriminate at. Caught in peer review before this code was ever run.

    `width` controls the sigmoid transition and defaults to `smoothing`.
    NOTE the inherent tension: a sigmoid centred at `tolerance` only returns
    ~0 at x=0 when `width` is small relative to `tolerance`. With a realistic
    tolerance of 1e-8 that forces a near-hard transition anyway -- which is
    precisely why `hard_separation` is the default. Do not reach for this
    function expecting a gentle gradient at the tolerance scale; it does not
    exist in this problem.
    """
    if smoothing <= 0:
        raise ValueError("smoothing must be positive")
    transition = smoothing if width is None else width
    if transition <= 0:
        raise ValueError("width must be positive")
    raw = torch.einsum("an,bn->ba", weight, delta)
    smooth_abs = torch.sqrt(raw * raw + smoothing * smoothing) - smoothing
    return torch.sigmoid(
        (smooth_abs - tolerance.unsqueeze(0) - sep_margin) / transition
    )


def soft_coverage(gates: torch.Tensor, h: torch.Tensor, eps: float = 1e-12) -> torch.Tensor:
    """C_g(omega) = 1 - prod_a (1 - g_a * h_a(omega)), the multilinear extension
    of "at least one selected action separates this witness".

    Computed as 1 - exp(sum log1p(-g*h)) for numerical stability. `log1p` is
    accurate for small `g*h` where `log(1 - g*h)` loses precision.

    The clamp bounds `g*h` strictly below 1 so the log stays finite; it also
    flattens the gradient once a term saturates, which is deliberate (a fully
    covered witness should stop pulling on its gates) but means gradients
    vanish in the saturated region.

    gates: (A,)   h: (B, A)   ->   (B,)
    """
    product = torch.clamp(gates.unsqueeze(0) * h, max=1.0 - eps)
    log_uncovered = torch.log1p(-product).sum(dim=-1)
    return 1.0 - torch.exp(log_uncovered)


def soft_min(values: torch.Tensor, beta: float) -> torch.Tensor:
    """Conservative soft-min: -1/beta * logsumexp(-beta * values) <= values.min(),
    tightening monotonically to the true min as beta -> inf. Using this (not a
    plain mean) for the worst-case witness is what keeps the loss fail-closed
    in spirit -- optimizing average coverage would silently trade away a
    single hard-to-cover witness for many easy ones.

    CAVEAT: the bound slackens as the pool grows. For B identical values v it
    returns v - log(B)/beta, so `history` traces are NOT comparable across
    rounds that added witnesses. Compare within a round, or renormalize.
    """
    if beta <= 0:
        raise ValueError("beta must be positive (soft_min is a lower bound only for beta > 0)")
    return -torch.logsumexp(-beta * values, dim=0) / beta


def action_scores(
    separation: torch.Tensor,
    dual_plus: torch.Tensor,
    dual_minus: torch.Tensor,
    thermal_influence: torch.Tensor,
    cost: torch.Tensor,
) -> torch.Tensor:
    """score_a = |w_a^T(p^S-p^R)| * |lambda_a^+ - lambda_a^-| * thermal_influence_a / cost_a.

    A diagnostic / gate-logit-initialization heuristic (not the training
    loss): favors actions that separate the current worst witness by a wide
    margin, carry high dual sensitivity in the collision LP, sit on a
    thermally influential block, and cost little.
    """
    return separation.abs() * (dual_plus - dual_minus).abs() * thermal_influence / cost.clamp(min=1e-12)


def project_budget(gates: torch.Tensor, cost: torch.Tensor, budget: float, iters: int = 60) -> torch.Tensor:
    """Euclidean projection of `gates` onto {0<=g<=1, cost^T g <= budget} via
    bisection on the dual variable mu>=0 (KKT: g = clip(gates - mu*cost, 0, 1),
    and cost^T g is monotonically non-increasing in mu). Not currently wired
    into train.py's loop (kept as a standalone, independently testable
    building block -- see README.md).
    """
    clipped = torch.clamp(gates, 0.0, 1.0)
    if torch.dot(cost, clipped) <= budget:
        return clipped
    lo = torch.zeros((), dtype=gates.dtype, device=gates.device)
    hi = (gates.abs().max() + 1.0) / cost.clamp(min=1e-12).min()
    for _ in range(iters):
        mu = (lo + hi) / 2.0
        spend = torch.dot(cost, torch.clamp(gates - mu * cost, 0.0, 1.0))
        lo, hi = (mu, hi) if spend > budget else (lo, mu)
    return torch.clamp(gates - hi * cost, 0.0, 1.0)
