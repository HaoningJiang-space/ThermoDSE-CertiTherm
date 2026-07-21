# Decision-Sufficient Observation Synthesis (DSOS)

Status: method freeze candidate v1; claims require the held-out protocol.

## Why ordinary information gain is not the right primitive

The admissible placed-power set \(P\) is a continuous polytope, so
\(\log |P|\) is undefined. Shannon mutual information also requires a
defensible prior over physical worlds. CertiTherm instead asks a zero-error
question: which observations eliminate every pair of worlds that imply
different DSE decisions?

For a selected action set \(S\), two worlds are confusable when both obey the
registered power constraints and robust model envelope, have different thermal
decisions, and

\[
  |a^\top(p_1-p_2)| \le \eta_a \quad \forall a\in S .
\]

Let the vertices of the decision-confusability graph be registered physical
worlds. Two vertices share an edge exactly when they induce different ordered
DSE decisions. An action \(a\) covers edge \(e=(w_1,w_2)\) when its two
outcomes differ by more than the registered measurement tolerance. Certifying
a decision is equivalent to covering every such edge.

## Exact batch limit

For finite obtainable action library \(\mathcal A\), DSOS solves

\[
 C^\star_{\rm batch} =
 \min_{x\in\{0,1\}^{|\mathcal A|}}\sum_a c_a x_a
 \quad\text{s.t.}\quad
 \sum_{a\ {\rm separates}\ e}x_a\ge1
 \quad\text{for every confusable edge }e .
\]

The edge set is continuous and is never enumerated. The implementation uses:

1. a minimum-cost hitting-set MILP over every discovered witness cut; and
2. an exhaustive robust-SAFE × rejecting-model/peak-row LP separation oracle
   on the current exact MILP plan.

Every iteration therefore queries the optimum of the current finite master,
not a heuristic surrogate. If that plan has no collision, its lower bound and
primal feasibility prove global optimality. If even the full library cannot separate a
collision, the result is `UNSYNTHESIZABLE` with that witness. Solver or replay
uncertainty returns `UNRESOLVED`, never a certificate.

A dedicated full-library pre-pass is unnecessary. Whenever a returned
cross-decision witness is separated by no registered action, that witness
already proves that the full library is insufficient. Avoiding the pre-pass
removes one exhaustive oracle call from every identifiable query without
changing the master, proof, or failure semantics.

Every thermal decision uses the joint fail-closed upper envelope
\(\max_m(T_m+\epsilon_m)\). SAFE therefore requires every registered
model/point to obey
\(T_m\le T_{\rm limit}-\delta-\epsilon_m\); REJECT needs one registered
model/point with
\(T_m\ge T_{\rm limit}+\delta-\epsilon_m\). The two cells share the same
upper-bound convention and cannot overlap. The registered LP
feasibility tolerance is \(10^{-10}\), one order tighter than the
\(10^{-9}\) action-separation guard.

This is a non-incremental algorithm: it synthesizes the entire least-cost
observation contract before any physical measurement value is known. The
subsequent LP decision verifier consumes that contract.

### Theorem 1: confusability graph–hitting set equivalence

For a compact registered world set \(W\), finite action library
\(\mathcal A\), deterministic linear action outcomes with registered
tolerances, and decision map \(d:W\rightarrow D\), an action subset \(S\)
identifies the decision for every obtainable observation if and only if \(S\)
is a hitting set of all cross-decision edges:

\[
 \forall (w_1,w_2)\in W^2,\quad
 d(w_1)\ne d(w_2)
 \Longrightarrow
 \exists a\in S:\ |a(w_1)-a(w_2)|>\eta_a.
\]

**Proof.** If an edge is not hit, its endpoints have different decisions but
identical registered observations, so no verifier can distinguish them.
Conversely, if every edge is hit, any two worlds consistent with one
observation have the same decision. That common decision is therefore
well-defined and certifiable. The minimum-cost sufficient batch is exactly
the minimum-cost hitting set. \(\square\)

### Theorem 2: exactness and finite termination of constraint generation

At exact-closure iteration \(t\), the master contains a finite subset \(E_t\)
of valid cross-decision edges. Its optimum \(L_t\) is a lower bound on
\(C^\star_{\rm batch}\), because it relaxes the full edge set. If the
continuous LP oracle returns no collision for master plan \(S_t\), \(S_t\)
hits the full edge set and hence is feasible. Thus
\(L_t=C(S_t)=C^\star_{\rm batch}\).

If either greedy or exact-plan separation returns edge \(e_t\), the added cut contains exactly the
registered actions that separate \(e_t\). It is necessary for every feasible
plan and is violated by the queried selection, so that selection can never
recur. There are only
\(2^{|\mathcal A|}\) selections. Therefore the procedure terminates after at
most \(2^{|\mathcal A|}\) oracle iterations with either:

- a globally optimal feasible plan; or
- an edge separated by no registered action, proving `UNSYNTHESIZABLE`.

An implementation iteration cap or a solver failure weakens this to
`UNRESOLVED`; it never weakens into a certificate. \(\square\)

### Lemma 3: diagonal coupling for equal candidate states

For one candidate whose required state is identical in two compared query
outcomes (`SAFE/SAFE`, `REJECT/REJECT`, or `ANY/ANY`), a confusable composite
pair exists for that candidate if and only if the single state is feasible.
Choose the same admissible power world on both sides. Every
registered action then agrees automatically. Conversely, either side of any
pair is itself a feasible single-state world.

The oracle therefore performs one single-world feasibility search for an
equal-state candidate. A differing state pair uses one robust SAFE polytope
and enumerates only the disjunctive rejecting model/peak rows. This is an
exact reduction, not pruning.

The implementation reports three different quantities. The exact plan cost
is a primal feasible bound, the solved binary master value is the MILP lower
bound, and the continuous master relaxation is a generally weaker LP lower
bound. A completed exact run must have primal-minus-MILP gap zero within the
registered numerical tolerance.

### Finite exhaustive validation

`test_query_constraint_generation_matches_all_subset_enumeration` enumerates
all \(2^{|\mathcal A|}\) batch subsets on a hand-specified ordered
two-candidate instance, calls the continuous collision oracle for every
subset, and checks that DSOS returns exactly the cheapest feasible subset
cost with zero MILP gap. The existing analytic two-variable tests separately
check the known one-channel optimum and a full-library collision. These
tests validate the implementation route; they do not replace Theorems 1–2.

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

This is the adaptive theoretical limit only for that declared finite
quantization. The recurrence terminates because every informative action
strictly reduces the current world subset and there are at most \(2^{|W|}\)
subsets. It is used for small calibration cases and lower-level insight only.
The continuous held-out claim remains the exact **non-adaptive batch** DSOS
limit; no finite quantization is allowed to masquerade as a continuous-world
adaptive proof.

## Scope of the theorem

The result is conditional on:

- the registered compact power polytope;
- the finite, provenance-bound HotSpot robust envelope;
- the finite obtainable measurement library, costs, and tolerances;
- the thermal margin and numerical tolerances.

It is not an assertion about all possible sensors or silicon truth. Individual
HotSpot models may disagree at identical power; that disagreement is archived,
while the active decision conservatively takes their upper envelope. No power
sensor is asked to infer a simulator-model label.

The word “limit” in all continuous-world result tables therefore means:
minimum non-adaptive batch cost under the finite, provenance-bound registered
channel library. It does not mean the unrestricted sensor-design limit or the
continuous-world adaptive limit.

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
