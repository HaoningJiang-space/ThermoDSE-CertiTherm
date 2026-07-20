# CertiTherm Research Insight, Corrected After Integrity Audit

## The insight that survives

Early chiplet DSE observes aggregate hardware quantities but acts on a
fine-spatial thermal field. Many placed power maps can therefore be consistent
with the same available observation. The publishable question is not whether
one guessed map has low temperature error. It is:

> Does every fine-power realization consistent with the obtainable hardware
> observations lead to the same architecture-selection outcome?

This is a decision-verification problem. It makes the observation interface,
the admissible realization set, the architecture query, and the proof object
first-class EDA artifacts.

## Why the finite-sample route is no longer the main method

The earlier Phase 2 story proposed replacing uniform temperature with the
maximum of `K` synthetic HotSpot samples. That route is killed as the primary
DAC/ICCAD/DATE contribution:

- a finite sample maximum is neither a supremum nor a safety certificate;
- no distribution-free `1/K` worst-case error theorem follows from the stated
  assumptions;
- the old injector interpreted a type-major, nine-component ptrace as a
  chip-major, six-component ptrace;
- the old multiplier did not conserve the aggregate component powers that the
  DSE supposedly knows;
- stale global backup state and skipped thermal failures could change results;
- the constraint wrapper classified a failed thermal run as feasible.

The corrected implementation is useful only as a deterministic,
power-conserving **sampled stress baseline**. Its results cannot certify a
design and cannot support a zero-false-positive claim.

## Exact decision-identifiability semantics

For candidate architecture `d`, let its obtainable observation define a compact
admissible fine-power set

```text
P_d = {p | A_d p = z_d, B_d p <= b_d, l_d <= p <= u_d}.
```

For one frozen monotone linear thermal operator,

```text
T_d(p) = max_r (ambient_d,r + K_d,r p).
```

The exact lower and upper peaks are

```text
lower_d = min_{p in P_d} T_d(p),
upper_d = max_{p in P_d} T_d(p).
```

With equality at the thermal limit defined as feasible:

```text
candidate d can be feasible   iff lower_d <= limit,
candidate d can be infeasible iff upper_d > limit.
```

For candidates in deterministic nonthermal-objective order, outcome `d_j` is
reachable exactly when `d_j` can be feasible and every earlier candidate can
be infeasible. `NO_FEASIBLE_DESIGN` is reachable exactly when every candidate
can be infeasible. One reachable outcome yields `CERTIFIED`; two or more yield
`NON_IDENTIFIABLE` plus two complete observation-equivalent power tuples that
replay to different decisions. Missing compactness, invalid input, incomplete
search, solver failure, or invalid proof yields `UNRESOLVED`.

## What has actually been validated

The sibling ChipletThermalEnvelope project has closed the synthetic semantic
gate, not the physical paper gate:

- G0 bound the feasible scope and resource envelope for small exact cases;
- the main G1 exact-rational oracle emits primal/dual LP certificates and
  decision-changing witness tuples;
- an independently written implementation and SciPy/HiGHS parity tests provide
  separate checks;
- adversarial replay rejects stale digests and forged primal, dual, and witness
  objects;
- the full remote regression passed before migration.

These results establish that the semantics are implementable and replayable.
They do **not** establish placed-power identifiability, DNN generality, minimum
information, scalable runtime, or an EDA paper contribution.

## The strongest honest paper route

The paper should be framed as **observation-aware thermal decision
verification for chiplet DSE**:

1. Define typed, physically obtainable power observations and their admissible
   fine-power equivalence classes.
2. Certify whether the architecture decision is invariant over each class; if
   not, emit a sharp pair of observation-equivalent decision-flipping maps.
3. Use certificate width and witness support to select an EDA-specific next
   measurement only after the physical G2 gate succeeds.

The first contribution is a problem/semantic contribution; the second is an
exact and replayable method contribution; the third remains conditional. A
generic active-learning, VOI, DDID, or CEGAR claim is out of scope because the
generic ideas have substantial prior art.

## The decisive next experiment

The next positive result must come from content-bound placed-power cases. For
at least two DNN families, two non-isomorphic architecture families, and two
package regimes, the same aggregate observation must admit both:

- a replayable certificate when all fine maps preserve one decision; and
- a replayable witness pair when two fine maps preserve the observation but
  change the chosen architecture.

If neither occurs under realistic observation sets, narrow or kill the paper.
Temperature deltas from unconstrained synthetic multipliers are no longer a
success criterion.

## G3 repair boundary (2026-07-20)

The later eight-row G3 pilot is also excluded from claims. It reused one
aggregate ptrace under two DNN labels, reused architecture-only thermal
operators under two package labels, and compared `1.5x` and `5x` nested
component-bound sets. Candidate safety becoming ambiguous under a larger set
is not an architecture-selection flip and is not an error rate.

The replacement G3 object is four workload-family × package queries, each over
the same architecture candidate pool. Every candidate binds separate point,
placed-reference, and spatial-domain evidence. All three variants execute the
same cross-candidate selection semantics.

**Update (2026-07-20):** those content-bound physical bundles now exist and
replay — the real 2×2×2 suite passes G3-A (breadth), G3-B (dual-backend
physical replay), and G3-C (four frozen baselines + systems cost). The
authoritative gate ledger is
`results/G3_REAL_2x2x2_CONSOLIDATED_REPORT.md`; baseline evidence is in
`results/G3_BASELINE_REPORT.md`. G4 remains open.
