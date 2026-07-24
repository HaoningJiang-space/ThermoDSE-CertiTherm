# Research Proposal: Decision-Complete Thermal Abstractions for Chiplet DSE

Status: research proposal; not an adopted claim contract

Target venues: DAC / ICCAD, with DATE as a narrower fallback

Working system name: CertiTherm

Working title:

> **CertiTherm: Proof-Carrying Decision-Complete Thermal Abstractions for
> Chiplet Design-Space Exploration**

## 1. Executive summary

Thermal-aware design-space exploration (DSE) optimizes architectures using
early-stage power and thermal abstractions. These abstractions intentionally
discard spatial detail because full placement- and route-aware analysis is
expensive or unavailable. Existing DSE work evaluates whether an optimizer
searches this abstract space efficiently, but does not ask whether the
abstraction itself contains enough information to determine the same
architecture choice as the underlying physical design.

This project proposes **decision completeness** as a correctness criterion for
thermal-DSE abstractions. Let \(p\) denote a physically realizable placed-power
state, \(h(p)\) the information visible to a DSE stage, and \(D(p)\) the
architecture decision under the registered non-thermal objective and thermal
constraints. An abstraction is decision-complete when

\[
  h(p)=h(q)\quad\Longrightarrow\quad D(p)=D(q)
  \qquad \forall p,q\in\mathcal P .
\]

If this implication fails, no optimizer that sees only \(h\)—regardless of
search algorithm, learning model, or compute budget—can be correct in both
worlds. CertiTherm returns the physical pair \((p,q)\) as an independently
replayable impossibility witness. If the abstraction is incomplete, CertiTherm
synthesizes a minimum-cost refinement from registered EDA reports so that the
refined abstraction becomes decision-complete. Numerical ambiguity remains
fail-closed.

The proposal changes the main question from “which power channels should be
measured?” to:

> **Does an early-stage EDA abstraction preserve the architecture decision,
> and what is the least refinement required to make it do so?**

The current Decision-Sufficient Observation Synthesis (DSOS) implementation is
the optimization engine for this proposal, not the proposal's scientific
identity. Its collision LPs, ordered decomposition, proof-carrying contracts,
and anytime lower/upper bounds are retained. Solver experiments such as
persistent lazy branch-and-cut remain implementation kill experiments and do
not become headline contributions unless they reduce oracle work materially.

## 2. Why this is a distinct EDA problem

### 2.1 What current DSE establishes

ThermoDSE and related chiplet-DSE systems search architecture, mapping,
communication, packaging, performance, energy, cost, and thermal design
variables. They establish that a search procedure can find attractive design
points under the model supplied to it.

### 2.2 What current DSE does not establish

They do not establish that two concrete physical states collapsed into the
same early-stage representation require the same design decision. Better
Bayesian optimization, simulated annealing, reinforcement learning, or a more
accurate surrogate cannot recover information that the representation removed.

This distinction separates:

- **optimization failure**: the optimizer fails to find the best decision
  represented by its model; and
- **information failure**: the model maps decision-incompatible physical
  worlds to the same observation.

CertiTherm targets the second failure class. This is complementary to, rather
than competitive with, ThermoDSE.

### 2.3 Why “save a few reports” is not the central claim

Reducing report cost is useful only if the uncertainty set, report semantics,
errors, and costs correspond to an actual EDA flow. The stronger contribution
is a correctness boundary for an abstraction:

1. a proof that the abstraction is decision-complete in a registered domain;
2. a concrete witness that it is not; or
3. a proof-carrying refinement contract that makes it complete.

Cost minimization then makes the refinement actionable, but is not the reason
the problem matters.

## 3. Formal problem

### 3.1 Registered instance

An instance contains:

- candidate designs \(\mathcal D\), ordered by a declared workload-specific
  non-thermal objective;
- a physically calibrated feasible-state family
  \(\mathcal P_d\) for each \(d\in\mathcal D\);
- a registered thermal-model family \(\mathcal T_d\), including numerical error
  contracts;
- a decision rule \(D\) that selects the first thermally certifiable candidate
  in objective order, or a declared rejection outcome;
- an initial abstraction \(h_0\);
- optional refinement features
  \(\mathcal A=\{a_1,\ldots,a_m\}\), with cost \(c_i\), error
  \(\epsilon_i\), provenance, and EDA-stage meaning.

A refinement \(S\subseteq\mathcal A\) observes

\[
 h_S(p)=\left(h_0(p),\{a_i^\top p:i\in S\}\right),
\]

with interval semantics

\[
  |\widehat z_i-a_i^\top p|\le\epsilon_i .
\]

### 3.2 Decision completeness

For a zero-error abstraction, define

\[
\mathrm{DC}(S)
\iff
\forall p,q\in\mathcal P:
h_S(p)=h_S(q)\Rightarrow D(p)=D(q).
\]

With observation and thermal-model error, equality is replaced by overlapping
observation intervals, and decisions must be separated by a registered robust
margin \(\rho\).

### 3.3 Three outputs

CertiTherm returns exactly one of:

1. **COMPLETE**: a replayable certificate that the abstraction is
   decision-complete;
2. **INCOMPLETE**: a pair of physically admissible worlds with indistinguishable
   observations and different decisions;
3. **UNRESOLVED**: numerical, solver, model, or budget uncertainty prevents a
   sound conclusion.

For refinement synthesis it additionally returns:

- an oracle-certified refinement \(S\) and cost \(U\);
- an independently checkable lower bound \(L\);
- the remaining interval \([L,U]\);
- archived collision witnesses and provenance.

“OPTIMAL” is used only when independent evidence closes \(L=U\).

## 4. Target theorems

The paper should carry a small set of load-bearing results rather than a large
collection of solver lemmas.

### Theorem 1: information impossibility

If there exist \(p,q\in\mathcal P\) such that

\[
h(p)=h(q),\qquad D(p)\ne D(q),
\]

then every deterministic decision procedure \(g\) using only \(h\) is wrong on
at least one of \(p\) and \(q\). Under the two-point distribution assigning
equal probability to the worlds, every randomized procedure has error at least
\(1/2\).

This theorem establishes that the failure cannot be repaired by replacing the
DSE optimizer.

### Theorem 2: confusability-hypergraph equivalence

Each decision-changing collision pair induces the set of registered refinement
features that separate it. A refinement is decision-complete if and only if it
hits every such set. Minimum-cost decision-complete refinement is therefore a
semi-infinite weighted hitting-set problem whose separation problem is a
continuous physical collision search.

### Theorem 3: ordered-decision decomposition

Under candidate-local, disjoint report libraries and the registered ordered
selection rule, the global refinement cost decomposes exactly into the sum of
required candidate-local optima. The assumptions must be explicit; otherwise
the result is not claimed.

### Theorem 4: robust soundness

If every observation interval and thermal response error lies within its
registered bound and the robust collision oracle finds no decision-changing
pair, the returned architecture decision is invariant over every admissible
physical world. Any boundary ambiguity produces `UNRESOLVED`.

### Theorem 5: anytime validity and finite-library termination

Every verified refinement is an upper bound. Every exact-Fraction weak-duality
certificate over validated witness cuts is a lower bound. With a finite
registered feature library and a progress rule that adds a new canonical cut
or terminates, the exact procedure terminates in finitely many refinements.
Finite termination does not imply practical closure within the wall-clock
budget.

## 5. Proposed system

### 5.1 Realizability-calibrated physical state set

The current total-power-plus-box polytope is useful as a conservative stress
model but is not sufficient as the only claim-grade physical domain. The
proposal requires a hierarchy:

1. **loose envelope**: nonnegative power, fixed total power, content bounds;
2. **structural envelope**: module, utilization, bandwidth, mapping, and
   scheduling couplings derived from the DSE model;
3. **trace-calibrated envelope**: legal multi-layer, multi-phase, and
   alternative-mapping traces, with a frozen held-out coverage check.

Results must report how incompleteness and refinement cost change across the
hierarchy. A finding that disappears outside the loose envelope is archived as
a conservatism result, not a physical decision failure.

The calibrated set should remain independently inspectable. A learned
generative world model may be used for stress-test proposals, but never defines
the only admissible set or validates its own witnesses.

### 5.2 Decision verifier

For a fixed abstraction \(S\), the verifier searches for two admissible worlds
that:

- satisfy the same registered observations within error;
- yield different SAFE/REJECT outcomes for a candidate or different final
  ordered decisions; and
- have a robust decision margin of at least \(\rho\).

For the current steady-state linear HotSpot family this is a collection of LPs.
Every reported witness is replayed through direct HotSpot. Unsupported physics
or calibration violations remain out of scope or produce `UNRESOLVED`.

### 5.3 Refinement synthesis

The current DSOS engine is retained:

1. propose a low-cost refinement;
2. search exhaustively for a decision-changing collision;
3. convert a validated witness into a canonical global separator cut;
4. update the weighted hitting-set master;
5. maintain a verified upper contract and independent lower bound.

The paper reports time to a certified refinement and time to a target gap.
Exact closure count is secondary.

### 5.4 Abstraction frontier

Rather than returning only the zero-error endpoint, CertiTherm should expose a
decision-risk frontier:

\[
\mathcal F =
\left\{
\left(C(S),R(S)\right):S\subseteq\mathcal A
\right\},
\]

where \(R(S)\) is either:

- worst-case architecture regret;
- worst-case thermal violation;
- decision-set cardinality; or
- robust decision margin.

The zero-regret decision-complete contract is one point on this frontier. This
makes negative cases actionable: if exact decision completeness is too
expensive, the designer sees what residual decision risk is purchased at each
EDA effort level.

## 6. A better formulation: joint design–abstraction co-optimization

The strongest non-incremental extension is to choose the design and the
analysis fidelity jointly:

\[
\min_{d,S}
\quad
C_{\mathrm{EDA}}(S)
+ \lambda
\max_{p\in\mathcal P(S)}
\mathrm{Regret}(d,p)
\]

subject to a robust thermal-safety rule. A constrained alternative is

\[
\min_{d,S} C_{\mathrm{EDA}}(S)
\quad\text{s.t.}\quad
\max_{p\in\mathcal P(S)}
\mathrm{Regret}(d,p)\le r_{\max}.
\]

This formulation is more practically complete than certifying a nominal winner
after the fact. It treats analysis effort as a DSE resource alongside area,
energy, latency, yield, and thermal margin.

However, it is also close to established decision-dependent information
discovery and robust-selection formulations. It should therefore be an
extension, not the primary novelty claim, until an EDA-specific structural
result or decisive end-to-end benefit is demonstrated.

### Recommended scope decision

Use **decision-complete abstraction verification and synthesis** as the core
paper. Add the cost–regret frontier as a systems result. Promote full joint
co-optimization to the headline only if it demonstrates a non-obvious
architecture change or an EDA-specific tractable decomposition unavailable in
generic information-discovery methods.

## 7. Why alternative directions are weaker

### 7.1 Pure minimum sensor placement

Field-reconstruction sensor placement already has strong mutual-information,
submodular, differentiable, and learned approaches. Competing on reconstruction
error would discard CertiTherm's strongest feature: it does not need to recover
the full field, only preserve a design decision.

### 7.2 Generic information gain

Mutual information requires a prior and values reconstruction or uncertainty
reduction, not necessarily the elimination of decision-changing aliases.
Minimax information gain is a useful heuristic, but it does not by itself
provide decision-completeness certificates.

### 7.3 Standard CEGAR

Counterexample-guided refinement is established in formal verification,
including hardware verification. The novelty cannot be “we use
counterexamples.” It must be the new property and domain:

- the abstraction is a hierarchy of EDA power reports;
- counterexamples are paired physical worlds with different architecture
  decisions;
- refinement is cost-aware and thermally robust;
- the output is an EDA abstraction contract, not a smaller transition system.

### 7.4 Solver-first contribution

Lazy branch-and-cut, Farkas reformulations, GPU LP proposals, and kernelization
are valuable only insofar as they reduce time to a certified contract. They are
not a sufficient independent DAC/ICCAD contribution without a new structural
result.

### 7.5 Continuous spectral feature synthesis

Allowing arbitrary continuous spatial measurements could produce a cleaner
optimal-experiment-design problem and reveal decision-bearing thermal modes.
It is a high-risk theory direction because arbitrary linear channels may not
correspond to obtainable EDA reports. Use spectral modes to explain and design
the finite library, not to replace the claim-grade library unless a tool can
produce them.

## 8. Research questions

- **RQ1 — Existence:** How often are common early thermal-DSE abstractions
  decision-incomplete over physically realizable placed-power states?
- **RQ2 — Cause:** Which spatial, workload, package, mapping, and thermal-margin
  factors create decision aliases?
- **RQ3 — Refinement:** How much EDA information is required to make the
  abstraction decision-complete?
- **RQ4 — Value:** Does decision-complete refinement avoid wrong architecture
  commitments or reduce detailed-analysis effort in an end-to-end DSE flow?
- **RQ5 — Scalability:** How quickly can a proof-carrying solver return a
  certified contract and a useful optimality interval?

## 9. Experimental plan

### 9.1 Front ends and candidates

Primary integration uses ThermoDSE. For every workload, take a declared
top-\(K\) candidate frontier produced before final detailed thermal selection,
rather than a hand-written three-architecture order. If feasible, include a
second search front end, such as ThermoDSE's SA or RL baseline, while holding
the physical candidate set fixed. The purpose is to show that abstraction
failure is optimizer-independent.

### 9.2 Physical domain

- multiple workloads from distinct families;
- multiple architectures spanning floorplan shape and chiplet partition;
- multiple package/sink regimes;
- multiple legal mappings or schedules per workload–architecture pair;
- per-layer or per-phase power traces rather than one aligned sample only;
- direct HotSpot replay for every final witness;
- frozen observation errors and thermal-model error bounds.

### 9.3 Baselines

Decision and abstraction baselines:

- nominal single-map thermal DSE;
- uniform or total-power abstraction;
- full post-route report library;
- random and cost-ordered refinement;
- uncertainty-width refinement;
- dual/witness-directed refinement;
- mutual-information or variance-reduction selection when a prior is
  available;
- reconstruction-driven sensor placement as a conceptual upper-cost baseline,
  not a directly equivalent competitor.

Optimization baselines:

- current outer IHS/DSOS;
- tuned outer-loop implementation;
- persistent lazy branch-and-cut only after its kill gates pass;
- greedy verified upper contract;
- exact master on small instances;
- brute-force ground truth on tiny instances.

### 9.4 Metrics

Scientific metrics:

- fraction of abstractions that are decision-complete;
- nominal-decision error, false-safe rate, and architecture regret;
- robust decision margin;
- witness replay validity;
- sensitivity to physical-state-set hierarchy;
- held-out coverage of the calibrated physical envelope.

EDA metrics:

- number and measured runtime of report/tool stages;
- cost of the certified abstraction relative to full detailed analysis;
- DSE candidates eliminated or protected;
- final EDYP/yield/thermal regret;
- end-to-end time and memory.

Proof metrics:

- certified \(L\), verified \(U\), \(U/L\), and time-to-gap;
- exact closure count;
- number of physical collision LPs;
- certificate and witness size;
- numerical `UNRESOLVED` rate.

### 9.5 Required ablations

1. loose versus structural versus trace-calibrated physical sets;
2. exact observations versus realistic error bands;
3. zero decision margin versus \(\rho\)-robust completeness;
4. artificial ordinal costs versus measured tool costs and cost intervals;
5. three fixed candidates versus a true top-\(K\) DSE frontier;
6. one thermal model versus the registered HotSpot family;
7. refinement synthesis versus full field reconstruction;
8. solver accelerations measured by oracle LP count, not only wall time.

### 9.6 Failure analysis

Archive and explain:

- abstractions already complete without refinement;
- physically valid aliases that no registered report separates;
- findings present only in the loose envelope;
- model disagreement;
- contracts requiring nearly the full registry;
- timeouts with useful and useless gaps;
- cases where the cost–regret frontier offers no advantage.

## 10. Claim gates

The following gates determine whether the proposal supports a strong paper.
They are targets, not current results.

### G-A: physical reality

- The claim-grade state family contains held-out legal traces under a frozen
  coverage rule.
- Decision-changing witnesses replay through the independent truth backend.
- The central aliasing result persists in the structural or trace-calibrated
  envelope, not only the loose box.

Failure consequence: narrow the paper to conservative abstraction auditing or
pivot away from physical decision failures.

### G-B: decision significance

- A nontrivial fraction of nominal choices changes across physically legal
  states, or a defensible phase boundary shows when this happens.
- The effect produces measurable thermal violation or objective regret.

Failure consequence: the problem is mathematically valid but not sufficiently
important for the intended venue.

### G-C: refinement value

- Zero invalid certificates.
- Certified refinements materially reduce measured detailed-analysis effort or
  expose a useful cost–regret frontier.
- Results generalize across workload, architecture, and package axes.

Failure consequence: retain the verifier as a diagnostic tool, but withdraw
minimum-cost operational claims.

### G-D: algorithmic viability

- Most claim-grade queries return a certified refinement within the DSE budget.
- Every timeout preserves a valid interval or a clearly labeled unresolved
  result.
- Any new solver backend must reduce oracle LP work by at least 50% or deliver
  at least 2x time-to-same-bound before it becomes a named method contribution.

Failure consequence: publish the abstraction result with heuristic contracts
only if the proof claim remains intact; otherwise redesign the oracle.

### G-E: novelty boundary

- The paper explicitly differentiates from thermal DSE, DDID, decision-robust
  feature acquisition, sensor placement, and CEGAR.
- A focused current search finds no prior work that verifies and synthesizes
  decision-complete physical abstractions for chiplet thermal DSE with
  proof-carrying continuous-world witnesses.

Failure consequence: narrow to the strongest EDA-specific theorem or system
result rather than renaming a generic information-acquisition method.

## 11. Current assets and evidence gaps

Reusable assets already present:

- workload-specific non-thermal candidate ordering;
- linear HotSpot block/grid operator family;
- frozen direct-replay error contract;
- hierarchical module/chiplet/region/post-route report library;
- exact continuous collision LPs;
- ordered decomposition;
- proof-carrying witness and contract data structures;
- independently certified weak-duality lower bounds;
- oracle-certified upper contracts;
- fresh-clone and provenance infrastructure;
- retained negative GPU and solver results.

Evidence that does **not** yet establish this proposal:

- the current power set starts from one placed trace per candidate and a loose
  total-power/content envelope;
- report costs 1/2/4/8 are ordinal, not measured EDA costs;
- the default observation tolerance is not calibrated to a tool flow;
- current candidates are a small fixed set rather than a true top-\(K\)
  ThermoDSE frontier;
- exact DSOS does not close on the development queries within 1800 seconds;
- the current v3 held-out split is unopened;
- HotSpot agreement establishes registered-model consistency, not silicon
  truth.

These are proposal work packages, not writing problems.

## 12. Work packages and stopping rules

### WP0: close the current solver round

Run the registered lazy-B&C Gates B and C. Stop if the Amdahl or real-query
gate fails. Do not allow solver exploration to delay physical calibration.

### WP1: physical-state audit

Collect multi-phase and alternative legal mapping traces. Implement the
structural and trace-calibrated envelopes. Quantify held-out coverage and how
the existing G3/G4 conclusions change.

### WP2: abstraction-completeness study

Generate top-\(K\) candidate frontiers and measure decision aliasing across
state-set hierarchies. Produce the phase diagram over power uncertainty,
thermal margin, and package.

### WP3: robust refinement

Calibrate observation errors and measured/report-cost intervals. Promote
\(\rho\)-robust decision completeness and the cost–regret frontier into the
claim path.

### WP4: end-to-end DSE integration

Insert CertiTherm between candidate generation and final detailed thermal
selection. Measure avoided wrong choices, detailed analyses, runtime, and
regret.

### WP5: final held-out evaluation

Freeze one final method and one untouched split only after WP1–WP4 pass. Do not
open another held-out split to diagnose an implementation problem that a dev
rehearsal could catch.

## 13. Expected contributions

If all gates pass, the paper can honestly claim:

1. **Problem and finding:** thermal DSE can fail because its abstraction is
   decision-incomplete, a failure no stronger optimizer can repair.
2. **Theory and method:** a formal decision-completeness criterion, physical
   impossibility witnesses, and proof-carrying minimum-cost abstraction
   refinement under continuous uncertainty and bounded model error.
3. **EDA system:** an end-to-end integration that co-designs DSE fidelity with
   architecture selection and reduces real detailed-analysis effort without
   invalid certification.

The headline should not be an exact-MILP speedup, a GPU thermal backend, or an
invented normalized-cost saving. Those remain enabling results.

## 14. Reviewer-facing risks

| Risk | Type | Closing evidence |
|---|---|---|
| The uncertainty set contains impossible power maps | requires new result | structural/trace-calibrated envelope and held-out coverage |
| This is generic DDID or CEGAR with thermal terminology | design-fixable + needs-search | EDA-specific property, robust continuous witnesses, exact differentiation |
| Full analysis is cheap, so refinement is unnecessary | requires new result | measured tool-stage cost and end-to-end flow study |
| Three candidates do not represent DSE | evidence-fixable | true top-\(K\) frontiers and a second optimizer front end |
| Report costs and errors are artificial | requires new result | calibrated cost/error intervals and sensitivity |
| Exact optimization does not scale | design-fixable | anytime contracts, time-to-gap, oracle reduction, honest limits |
| HotSpot is not physical truth | scope + evidence-fixable | explicit registered-model scope and optional independent sensitivity |
| The proposal is too broad for one paper | writing/design-fixable | core on decision completeness; joint co-optimization remains extension |

## 15. Final recommendation

The best current route is not to replace DSOS with another combinatorial
solver. It is to change what DSOS is understood to solve:

> **CertiTherm verifies whether an EDA thermal abstraction is capable of
> supporting a chiplet architecture decision, produces an impossibility
> witness when it is not, and synthesizes the least robust refinement that
> makes it decision-complete.**

The stronger joint architecture–analysis formulation should be implemented
only after the abstraction result is physically validated. It is a valuable
extension and a possible future headline, but making it the immediate core
would increase overlap with generic information-discovery optimization before
the project's unique EDA contribution is secured.
