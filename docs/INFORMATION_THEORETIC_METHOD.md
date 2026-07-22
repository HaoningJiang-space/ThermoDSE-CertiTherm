# Decision-Sufficient Observation Synthesis (DSOS)

Status: frozen algorithm for `method-freeze-v3.0`; its held-out split remains
unopened.

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

The edge set is continuous and is never enumerated. Ordered DSE first admits
an exact structural decomposition (Theorem 2). Each required candidate-local
subproblem then uses:

1. a cost-effectiveness greedy cover over the discovered witness cuts, used to
   accumulate cuts cheaply;
2. an exhaustive robust-SAFE × rejecting-model/peak-row LP separation oracle
   on that plan; and
3. a minimum-cost hitting-set MILP over every discovered cut, solved for
   **exact closure only when separation returns no collision**.

If the exact master then selects a different plan, that plan is separated
again before `OPTIMAL` is returned, so optimality is always proved against a
collision-free exact solution. If even the full library cannot separate a
collision, the result is `UNSYNTHESIZABLE` with that witness. Solver or replay
uncertainty returns `UNRESOLVED`, never a certificate.

> **Documentation correction, 2026-07-22.** This section previously stated
> that "every local iteration queries the optimum of the current finite
> master, not a heuristic surrogate". That was false of the implementation:
> `_solve_master` is reached only on the collision-free branch, while each
> ordinary iteration rebuilds the cover with `_greedy_cover`. Instrumentation
> on a 241-action instance recorded **one** `_solve_master` call across 5000
> iterations.
>
> That single solve is not by itself evidence of a weakened claim: one exact
> closure can suffice. Greedy accumulation preserves exactness by the standard
> argument — every globally feasible plan must cover every valid discovered
> cut, so the exact master's optimum over the discovered cuts lower-bounds the
> true optimum; if exhaustive separation then finds no collision for that same
> plan, it is itself feasible, and the two bounds meet. The code enforces the
> required sequence: when the master picks a plan different from the separated
> greedy cover, `exact_candidate` forces another separation of *that* plan
> before `OPTIMAL` is returned.
>
> So the correction is that the old prose misdescribed the **iteration
> policy**. The certificate remains exact **conditional on** `_solve_master`
> returning a true optimum over the accumulated cuts and the separation oracle
> being sound and exhaustive — both of which this document assumes elsewhere
> but neither of which the instrumentation above establishes. Stating flatly
> that "the prose, not the algorithm, was wrong" would overstate what has been
> shown, so it is not claimed here.
>
> If instead the original text described the intended contract, then the
> implementation — not this document — is what diverged, and that is a
> method-level decision rather than a documentation fix. Flagged in
> `ccfa.yaml` under `open_risks`.

A dedicated full-library pre-pass is unnecessary. Whenever a returned local
SAFE/REJECT witness is separated by no registered action, the corresponding
required subproblem is insufficient. One final global replay then constructs
the cross-decision witness without charging identifiable queries for an
exhaustive pre-pass.

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

### Theorem 2: ordered-decision decomposition

Let candidates \(0,\ldots,m-1\) be ordered by the non-thermal DSE objective,
with candidate-local world sets and candidate-local measurement actions.
Decision \(i<m\) means candidates \(k<i\) are REJECT and candidate \(i\) is
SAFE; decision \(m\) means every candidate is REJECT. For two reachable
decisions \(i<j\), their state pairs are SAFE/REJECT at candidate \(i\),
ANY/REJECT or ANY/SAFE between \(i\) and \(j\), and equal elsewhere.

Every pair containing ANY is confusable whenever its constrained state is
feasible: choose the same constrained power world on both sides. Equal states
are likewise confusable by diagonal coupling. Hence decisions \(i\) and \(j\)
are distinguishable if and only if the selected actions of candidate \(i\)
distinguish all of its SAFE/REJECT worlds.

Let \(R\) contain every reachable candidate decision \(i\) for which a later
decision is also reachable. Because action libraries are disjoint across
candidates,

\[
 C^\star_{\rm batch}=\sum_{i\in R} C^\star_i,
\]

where \(C^\star_i\) is the candidate-local minimum-cost SAFE/REJECT hitting
set. Necessity follows by pairing decision \(i\) with any later reachable
decision; sufficiency follows because every pair of reachable decisions is
separated at its earlier candidate. The decomposition therefore preserves
global optimality. \(\square\)

This result is specific to ordered first-feasible selection, independent
candidate power spaces, and candidate-local actions. Shared sensors or
cross-candidate physical coupling require the general global formulation.

### Theorem 3: exactness and finite termination of constraint generation

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

### Theorem 4: proof-carrying anytime interval

Let \(E_t\) be any set of collision cuts returned by the exact separation
oracle, and let \(C_t\) be their action-incidence matrix. Every globally
sufficient contract must cover every row of \(C_t\). Therefore the relaxed
cover optimum is a lower bound on the full-library optimum \(C^\star\).
CertiTherm evaluates the Lagrangian bound

\[
 L_t(y)=\mathbf 1^\top y+
 \sum_a \min\{0,c_a-(C_t^\top y)_a\},\qquad y\ge0,
\]

in exact rational arithmetic and converts it to binary64 with directed
downward rounding. Weak duality gives
\(L_t(y)\le C^\star\) for every nonnegative \(y\), even when the LP solver's
dual vector is inaccurate. Because every registered action cost is an integer
multiple of the exact cost lattice \(g\), every feasible contract cost lies in
\(g\mathbb Z\); hence

\[
 \widehat L_t=g\left\lceil L_t(y)/g\right\rceil\le C^\star.
\]

Independently, if exhaustive separation finds no cross-decision collision for
a selected contract \(S\), then \(S\) is feasible and
\(C^\star\le U=C(S)\). Thus every emitted finite interval satisfies

\[
 \widehat L_t\le C^\star\le U.
\]

The implementation keeps the largest valid lower bound seen and binds the
upper cost, registered action IDs, and policy source in one immutable
contract. Solver failure can remove or loosen a bound; it cannot manufacture a
certificate. An interval contradiction is reported as `UNRESOLVED` rather
than clipped. \(\square\)

The frozen controller uses one end-to-end budget. Uncertainty-width sequential
acquisition first searches for a collision-oracle-certified contract; exact
constraint generation receives only the measured remaining time. Fixed and
dual policies have independent comparison budgets and can never be substituted
into this controller's \(U\). Reports expose both orthogonal dimensions:
`plan_validity` says whether a replayable contract is certified, while
`cost_optimality` says whether its cost is self-verifiably optimal,
solver-attested, bounded by a finite gap, or not applicable.

### Lemma 4: diagonal coupling for equal candidate states

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
cost with zero MILP gap. This checks the decomposition against the unreduced
global collision oracle rather than against itself. The existing analytic
two-variable tests separately
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
