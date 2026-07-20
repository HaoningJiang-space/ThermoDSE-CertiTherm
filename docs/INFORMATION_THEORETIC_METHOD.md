# Decision-Sufficient Observation Synthesis (DSOS)

Status: method freeze candidate v1; claims require the held-out protocol.

## Why ordinary information gain is not the right primitive

The admissible placed-power set \(P\) is a continuous polytope, so
\(\log |P|\) is undefined. Shannon mutual information also requires a
defensible prior over physical worlds. CertiTherm instead asks a zero-error
question: which observations eliminate every pair of worlds that imply
different DSE decisions?

For a selected action set \(S\), two worlds are confusable when both obey the
registered power constraints and model family, have different thermal
decisions, and

\[
  |a^\top(p_1-p_2)| \le \eta_a \quad \forall a\in S .
\]

The unresolved cross-decision pairs are the edges of a decision-confusability
graph. Certifying a decision is equivalent to removing every such edge.

## Exact batch limit

For finite obtainable action library \(\mathcal A\), DSOS solves

\[
 C^\star_{\rm batch} =
 \min_{x\in\{0,1\}^{|\mathcal A|}}\sum_a c_a x_a
 \quad\text{s.t.}\quad
 \sum_{a\ {\rm separates}\ e}x_a\ge1
 \quad\text{for every confusable edge }e .
\]

The edge set is continuous and is never enumerated. The implementation
alternates:

1. a minimum-cost hitting-set MILP over discovered witness cuts; and
2. an exhaustive safe-model × unsafe-model × peak-row LP separation oracle.

If the LP finds a collision, its separating actions form a necessary master
cut. If it finds none, the current plan is feasible and the exact MILP bound
proves global optimality for the registered library. If even the full library
cannot separate a collision, the result is `UNSYNTHESIZABLE` with that
witness. Solver or replay uncertainty returns `UNRESOLVED`, never a
certificate.

This is a non-incremental algorithm: it synthesizes the entire least-cost
observation contract before any physical measurement value is known. The
subsequent LP decision verifier consumes that contract.

## Information–certification score

For scale, the master LP relaxation assigns dual price \(\lambda_e\) to each
unresolved decision-confusability cut. The principled greedy score is

\[
  {\rm InfoCertGain}(a)=
  \frac{\sum_{e:\,a\ {\rm separates}\ e}\lambda_e}{c_a}.
\]

It measures paid reduction of zero-error *decision* uncertainty, rather than
generic uncertainty width. It is an approximation and must be reported
against \(C^\star_{\rm batch}\), not presented as the theoretical limit.

## Adaptive finite-alphabet limit

For an explicitly finite/quantized world set, `CertiTherm/adaptive.py` also
solves the exact minimax Bellman recurrence

\[
 V(W)=
 \begin{cases}
 0,&\text{all worlds in }W\text{ have one decision},\\
 \min_a\left[c_a+\max_z V(W_{a,z})\right],&\text{otherwise}.
 \end{cases}
\]

This is the adaptive theoretical limit for that declared quantization. It is
used for small calibration cases and lower-level insight only. The continuous
held-out claim remains the exact non-adaptive DSOS limit; no finite
quantization is allowed to masquerade as a continuous-world proof.

## Scope of the theorem

The result is conditional on:

- the registered compact power polytope;
- the finite, provenance-bound HotSpot model family;
- the finite obtainable measurement library, costs, and tolerances;
- the thermal margin and numerical tolerances.

It is not an assertion about all possible sensors or silicon truth. A
cross-model flip at identical full power is reported as
`MODEL_NON_IDENTIFIABLE`; no power sensor is allowed to hide it.

## Model family

The main family is HotSpot-only:

- block;
- grid 64×64 with block-average mapping;
- grid 128×128 with block-average mapping.

Block average is linear in grid-cell temperatures; HotSpot's max mapping is
not and is therefore forbidden in the LP operator. The exported build applies
an output-format-only patch from two to ten decimal places before its binary
digest is recorded. Grid 256×256 is calibration-only. Every model receives a separate impulse
operator and provenance digest. There is no fitted `POWER_SCALE`, no 3D-ICE
equivalence claim, and no silent conversion between stacks.
