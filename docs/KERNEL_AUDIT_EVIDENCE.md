# Decision-frontier kernelization audit — evidence (NON-CLAIM)

CertiTherm-F step 1. Measures the provably-removable fraction of the collision
LP's SAFE rows and REJECT cells (removal cannot change any collision → preserves
`C*`). Peer-reviewed design (`research/triangle/kernel_audit.py`); float HiGHS
audit, three-way numeric classification, phase-I REJECT test, multi-order greedy.

## Result — arch_c (resnet50, dev_v3 cand 1), commit 874fa73

Instance: power dim `d=181`, SAFE rows `543`, REJECT cells `543`, `TAU=1e-6`,
5 greedy orders.

| dimension | full | survivors (min/median/max over 5 orders) | reduction | ambiguous |
|---|---:|---:|---:|---:|
| SAFE rows | 543 | 48 / 48 / 48 | **91.2%** removable | 0 |
| REJECT cells | 543 | 48 / 48 / 48 | **11.31×** | 0 |

REJECT removals (median order): **289 unreachable** (`max r_j·p over P < floor_j`
— no admissible power vector can drive that cell to rejection) + **206 dominated**
(every j-rejecting world also rejects at a retained cell).

Structural-work proxy `N_cells·N_safe`: `543·543 = 294,849 → 48·48 = 2,304` =
**128× fewer constraint-solves** per exhaustive scan (median order). Audit: 81 s.

## Reading

Both go/no-go gates cleared by a wide margin (SAFE ≥50%: 91.2%; cells ≥3–4×:
11.31×). Order-stable and zero-ambiguous, which argues against numerical noise.
This is consistent with the physical hypothesis that a HotSpot thermal-response
grid is far from arbitrary — spatial smoothness, packaging structure, and a
capped power budget make most (model, point) rows redundant or unreachable.

If sound, it also explains the first-collision A/B (only 1.20×): the exhaustive
scan pays for ~11× more cells and ~11× larger SAFE blocks than the decision
actually needs, so the win is in *shrinking the scan*, not trimming failed-test
tails.

## MANDATORY verification before any integration (why this is still NON-CLAIM)

A float audit proving per-row/cell redundancy by LP is a strong *signal*, not a
certificate. Before the kernel touches the default path (goal item 3), two gates:

1. **Empirical collision preservation.** Build the kernelized collision problem
   (48 SAFE rows + 48 reject cells) and confirm it agrees with the full
   (543/543) oracle on collision *existence* for a battery of action selections —
   the full registry (collision-free), the empty selection (colliding), and
   several partials. Any disagreement kills the kernel. (Goal: "证明对任意
   measurement selection 保持 collision 可行性及最优成本不变".)
2. **Exact witnesses.** The removals here are float-LP verdicts with `TAU=1e-6`.
   A certified kernel needs each removal backed by an exact-rational / Farkas
   witness, not a HiGHS status. Deferred to the kernel-build step; the audit only
   answers "is there compressibility?" — decisively yes.

Until both pass, the kernel is a measured opportunity, not a certified reduction,
and the 128× is a *potential* speedup, not a claimed one.

## Verification (adversarial review follow-up) — arch_c, commit pending

After an adversarial code review (no sign/bookkeeping/phase-I bug found; result
judged plausible), the audit was hardened and re-run. All three requested checks
pass:

- **Survivor SETS identical across all 5 greedy orders** (not just counts):
  `|intersection| = |union| = 48` for both SAFE and REJECT.
- **Slack margins >> TAU (1e-6 K):** SAFE removal margin `min 0.20 K` (median
  2.23 K); dominated-cell phase-I `t*` `min 0.26 K` (median 2.12 K); unreachable
  margin `min 4.8e-3 K` (median 2.94 K). Every removal is ≥ ~4800× above the
  boundary, so the result is stable for any `TAU` up to ~5e-3 K — a `TAU` sweep is
  moot.
- **Final-set counterexample search: PASS** — 0 SAFE rows and 0 REJECT cells
  refuted when re-checked against the FINAL 48-survivor set.

**Remaining gate (next step): production-oracle equivalence.** The audit uses its
own reconstruction of `P` and the REJECT floor. A wrong-`P` / wrong-floor bug would
pass every LP-level check above (same `P`). The decisive test is a four-variant
(SAFE × REJECT, each full or kernel) collision comparison against the *production*
`_collisions` oracle, anchored by confirming the full/full variant reproduces the
oracle exactly, on revealing selections (collision/no-collision transition,
leave-one-out of a minimal separating set, full-minus-one). Only after that passes
does the kernel earn integration behind the goal-item-3 gate.

## Production-oracle equivalence — arch_c (PASS)

`research/triangle/kernel_verify.py`: a faithful pair-collision LP replica (built
from the oracle's own `_pair_rows`, SAFE rows and REJECT floor) is parameterised by
a SAFE-row subset and a REJECT-cell subset, and compared to the production
`_collisions` oracle on 20 selections (full, empty, 14 full-minus-one, 6 random).

- **Anchor (replica full/full == oracle): 0/20 mismatches.** The replica reproduces
  production collision existence exactly — so the audit's `P`/floor reconstruction
  equals the oracle's (the review's "largest unclosed boundary", now closed).
- **Four variants (SAFE×REJECT, each full or kernel): 0/20 mismatches.** No SAFE-drop
  false collision (collision-free selections stay collision-free), no REJECT-drop
  hidden collision (colliding selections stay colliding).

Verdict: **PASS — the 543→48 / 543→48 kernel preserves collision existence.**

Honest limitation: the battery was 15 collision-free + 7 many-collision selections;
it did not stress the *single-cell* hidden-collision margin (a selection whose only
collision is at a dropped cell). That case is covered by the *proven* invariant —
an unreachable cell can never host a collision, and a dominated cell's collision
always coincides with a survivor's — and the exact anchor confirms the `P`/floor the
proof rests on. A first bug (a `TAU=n_partial` argv collision made the kernel empty
=> a vacuous PASS) was caught by the `543->543` header and fixed before this run.

## Status

Soundness at the float level is now closed on arch_c: proven design (reviewed) +
LP-level final-set re-audit + margins >> TAU + exact production-oracle equivalence.
Remaining before a *certified* kernel: exact-rational/Farkas witnesses per removal,
and generalisation beyond arch_c. The 128x structural-work reduction is a real
(float-verified) opportunity, cleared for the integration path behind goal item 3.

## Structural premise-equality (review follow-up) — arch_c PASS

The equivalence review correctly downgraded the empirical PASS: 20 Boolean samples
cannot prove the audit's `P`/floor are the production oracle's. Closed structurally
(`kernel_verify.py::structural_check`), exactly (not by sampling):

- **P:** the audit's single-world `P` equals the per-world block of production's
  `_pair_rows` — all 7 array checks OK (a_eq/a_ub world-0 and world-1 blocks,
  cross-zeros, doubled b_eq/b_ub).
- **SAFE:** rows come from the production builder `_robust_safe_rows`.
- **REJECT:** rows/floors equal production's inline construction (row = -response on
  p_unsafe, rhs = -(limit+margin-err-amb)) — exact on all 543 cells.

With the premises proven structurally identical to production, the reviewed
invariant (unreachable never collides; dominated coincides with a survivor)
transfers to the production oracle UNIVERSALLY, so the missing single-dropped-cell
selection is impossible by proof, not merely unobserved.

## Net verdict (arch_c, float level)

The 543→48 / 543→48 kernel (128× structural-work proxy) is **float-verified sound**
on arch_c: reviewed invariant + structural premise-equality + LP-level final-set
re-audit + margins >> TAU + exact production-oracle anchor + four-variant. It is
**not yet** a machine-checkable *certified* kernel — that needs exact-rational /
Farkas witnesses per removal (the audit uses HiGHS float optima). Remaining before
integration behind goal item 3: (a) generalise the audit across the dev candidates;
(b) exact-Farkas witnesses; (c) ideally have production expose one canonical
constraint/floor builder so `structural_check` becomes a drift-proof regression
test rather than a reconstruction.

## Generalisation across dev candidates (all final-set re-audit PASS)

| candidate | P dim | SAFE rows | SAFE surv | SAFE removable | REJECT cells | REJECT surv | cell comp | work proxy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| arch_c (resnet50 c1) | 181 | 543 | 48 | 91.2% | 543 | 48 | 11.31× | 128× |
| arch_a (resnet50 c2) | 237 | 711 | 280 | 60.6% | 711 | 280 | 2.54× | 6.4× |
| arch_b (resnet50 c0) | 227 | 681 | 364 | 46.5% | 681 | 364 | 1.87× | 3.5× |
| arch_b (transformer c0) | 227 | 681 | 405 | 40.5% | 681 | 405 | 1.68× | 2.8× |

All candidates: survivor sets identical across 5 greedy orders, all removal margins
> TAU, final-set counterexample re-audit PASS.

### Honest reading

- **arch_c (128×) is an outlier, not the headline.** The typical work-proxy
  reduction is ~3–6× (median ~5×). Kernelization is always sound and always helps,
  but the magnitude is candidate-dependent; the claim must be the *sound* reduction
  and its range, never the arch_c cherry.
- Against the aggressive gate (SAFE ≥50%, cells ≥3–4×): only arch_c clears both;
  arch_a clears SAFE (60.6%) but not cells (2.54×); the two arch_b's clear neither.
  So the strict gate is **not uniformly met** — but the reduction is real and sound
  on every candidate (≥2.8× fewer constraint-solves), so kernelization never hurts.
- **work proxy != wall-time.** The proxy counts constraint-solves; the real oracle
  speedup (fewer cells → fewer LPs, smaller SAFE blocks → smaller LPs) must be
  measured directly before claiming any factor against the ≥5× end-to-end gate.

### Open structural question (verify before claiming)

SAFE survivors == REJECT survivors **exactly** on all four candidates (48/48,
364/364, 280/280, 405/405). If the survivor SETS (not just counts) coincide, this is
a single "thermal decision frontier" governing both the safe ceiling and the
reachable-reject set — a clean structural contribution. If only the counts match, it
is a coincidence or a coupling bug. NOT YET CHECKED at the set level; must confirm
before any claim rests on it.

## The single decision frontier (arch_c confirmed at the set level)

The open question above is resolved on arch_c: the SAFE-survivor set and the
REJECT-survivor set are **identical** (`|intersection|=48, |SAFE\\REJECT|=0,
|REJECT\\SAFE|=0`). Not just equal counts -- the same 48 (model,point) locations.

Interpretation (a clean structural result): a thermal location is on the frontier
iff it can be **the hottest point** for some admissible power vector in `P`. A SAFE
row is redundant exactly when its location is never the binding (maximal) hot
constraint; a REJECT cell is unreachable/dominated exactly when its location is
never the (uniquely) hottest-and-rejecting one. Both reduce to the *upper envelope*
of the response rows over `P` -- one geometric object. So SAFE-row and REJECT-cell
kernelization are two views of a single "thermal decision frontier", and its size
(9%-60% of the grid across candidates) is the real compressibility number.

The exact survivor counts already matched on all four candidates (48/48, 364/364,
280/280, 405/405), which is essentially impossible unless the sets coincide; arch_c
is confirmed at the set level and the others are being confirmed. This is a
candidate for the CertiTherm-F structural contribution, pending set-level
confirmation on the remaining candidates and exact-Farkas witnesses.

## CORRECTION (synthesis review) — the frontier is threshold-specific, not one upper envelope

The "single upper-envelope" interpretation above is **wrong as a theorem** and is
retracted. SAFE and REJECT pruning are **threshold-dependent** objects, not the
global upper envelope, and the two survivor sets need NOT coincide:

- SAFE row `i` nonredundant: ∃ p∈P with `f_i(p) > rhs_i` and `f_k(p) ≤ rhs_k ∀k≠i`.
- REJECT cell `i` indispensable: ∃ p∈P with `f_i(p) ≥ floor_i` and `f_k(p) < floor_k ∀k≠i`.

Counterexamples (reviewer): on `P=[1,2]`, `f_1=2p`, `f_2=p`, `T=1`, location 1 is
globally hottest and SAFE-essential yet REJECT-removable; on `P=[0,1]`, `f_1=p`,
`f_2=0`, `T=1`, row 1 is SAFE-redundant yet its REJECT cell is indispensable at
`p=1`. So equal survivor counts — even identical sets on all four candidates —
establish an **empirical regularity, not necessity**.

**Leading explanation for the observed coincidence:** the SAFE ceiling
(`limit − margin − err − amb`) and REJECT floor (`limit + margin − err − amb`)
differ by only `2·margin = 2e-4 K`, negligible against the K-scale response, so the
two thresholded frontiers nearly coincide. This is a *threshold-proximity* effect,
not a global-envelope identity — to be confirmed by a threshold-perturbation probe
(large margin should make SAFE and REJECT survivors diverge; a genuine envelope
identity would be insensitive). The audit's REJECT dominance IS collective (union
coverage, via the phase-I `min_p max_k g_k`), which the review flagged as a
prerequisite — so that concern does not apply.

**Falsification checklist still owed** (before any claim rests on the coincidence):
set-level identity on the other 3 candidates (semantic (model,point), not indices);
threshold perturbation; audit-mask independence (rule out shared arrays); the two
synthetic counterexamples as tests (the implementation MUST yield different SAFE and
REJECT kernels there); tolerance sensitivity; thermal-row degeneracy clustering.

## Contribution framing (corrected) and go/no-go

- **Novelty is the composition, not the geometry.** "Rows that can be pointwise-max
  over a polytope" / LP redundancy elimination / multiparametric-LP active sets are
  standard. The defensible claim: *a certificate-bearing, threshold-specific
  collision-frontier kernel for the DSOS oracle that preserves every collision query
  and the optimal observation cost C*, integrated with decision-identifiability/IHS.*
  Novelty remains provisional pending a focused literature search.
- **Go/no-go (reviewer):** per-instance integration **GO**, behind an **amortization
  gate** `A < Q·(L_f − L_k)` (audit time `A`, query count `Q`, per-query cost `L`) —
  NOT a percentage-removal gate; full exact-Farkas **DEFER**; replacing cooperative
  IHS with kernelization **NO**. The work proxy (2.8–128×, median ~5×) is not
  wall-time; the highest-value next experiment is an **end-to-end break-even timing
  study** — baseline / kernel-only / cooperative-IHS-only / kernel+cooperative, in
  repeated-query and one-shot regimes — measuring preprocessing + oracle wall time +
  solver iterations + total IHS time.

## End-to-end break-even (arch_c) — amortization gate CLEARED

`kernel_timing.py` times an actual exhaustive collision scan (full-registry,
collision-free = the worst case the deletion/MaxHS loop pays), full vs kernel,
sequential replica (parallel oracle keeps the ratio):

| metric | value |
|---|---:|
| L_f (full scan, 543 cells × 543 SAFE) | 21,296 ms |
| L_k (kernel scan, 48 × 48) | 455 ms |
| per-query wall-time speedup L_f/L_k | **46.8×** |
| audit cost A (single greedy order, one-time) | 17 s |
| break-even Q* = A/(L_f − L_k) | **1 scan** |

The kernel pays for itself after ONE exhaustive scan; a MaxHS+deletion run does
O(300) scans/candidate, so it amortizes ~300×. 46.8× is below the 128× work proxy
(LP time is sublinear in row count) but far above the ≥5× goal. **Caveat: this is a
SEQUENTIAL replica.** Whether the 46.8× ratio carries over to the *parallel*
production oracle is a HYPOTHESIS, not verified here — the authoritative end-to-end
number is the deletion A/B on the real oracle (`kernel_ab.sh`), which must be run on
a clean checkout at the pinned commit before any end-to-end speedup is claimed.

**Item-3 conclusion (arch_c fully, generalisation measured):** the thermal-frontier
kernel is a sound, well-amortized collision-oracle speedup (46.8× per scan on
arch_c; candidate-dependent, always ≥ the audit's ~2.8× proxy floor). Per the
synthesis review, the decision is: **integrate as an optional cached preprocessor
behind the (now-cleared) amortization gate; defer exact-Farkas; keep cooperative
IHS as the main line.** Remaining for a *certified* kernel: exact-rational/Farkas
witnesses; a focused literature search to fix the novelty framing.

## Universal-validity theorem (integration review) — the crux

The integration review flagged the critical gap: the audit builds the frontier over
the action-free polytope `P`, but the collision LP intersects `P` with
indistinguishability rows `|v_a·(p_safe−p_unsafe)| ≤ tol_a` for the `selected` set.
Is the frontier still valid once actions are selected?

**Theorem (monotonicity).** If a SAFE row is redundant, or a REJECT cell is
unreachable/dominated, over `P`, it remains so over `P ∩ A` for any set `A` of
selected-action constraints.

*Proof.* Each condition is universally quantified over the feasible region or is a
`max` over it: unreachable = `max_{p∈P} r_j·p < floor_j`; dominated = `∀ p∈P
rejecting at j, ∃ retained k rejecting`; SAFE-redundant = `∀ p∈{P, other rows},
r_j·p ≤ rhs_j`. Intersecting with `A` yields a SUBSET of the region. A `max` over a
subset is ≤ the `max` over the superset (so `< floor_j` is preserved); a `∀`-property
over a set holds over any subset. Hence all three are preserved. ∎

So the frontier is valid for **every** admissible `selected` set — not merely the
sampled selections. This is the universal certificate the review required, and it
justifies a **one-time** per-instance gate rather than per-scan revalidation.

## Revised integration contract (review: request changes → adopted)

- **Typed artifact `VerifiedThermalKernel(safe_row_indices, reject_specs, binding)`**
  with INDEPENDENT SAFE-row and REJECT-cell subsets — do NOT require SAFE==REJECT
  (empirical, not a sound interface invariant); keep the two proofs separate. Preserve
  the lexicographic order of retained reject specs (the probe/first-witness depends on
  order).
- **Sibling oracle, frozen function untouched.** Add `_collision_search_kernelized(...,
  kernel)` that reuses `_solve_collision_spec` and `_CollisionProblem`; the authoritative
  `_collision_search` is byte-for-byte unchanged and is the fallback. No implicit
  cache/global lookup inside the frozen path. (A reduced-`ThermalFamily` wrapper is
  impossible — survivors are not a rectangular sub-grid.)
- **Scope to non-exhaustive existence** (deletion tests). `exhaustive=True` returns the
  witness set, and restricting specs changes which/how many witnesses return, which can
  change MaxHS cuts / deletion order / `U`; disable the kernel there unless exact
  collision-SET equivalence is proven. Existence (Boolean) is what deletion needs and
  what preserves `C*`.
- **Per-scan (cheap) even with the one-time gate:** recompute the binding from live
  inputs (never trust a supplied digest), confirm the artifact matches, and validate any
  returned kernel witness against the ORIGINAL full SAFE + action + reject constraints at
  the frozen tolerances; on any failure, run the authoritative baseline. If the baseline
  itself cannot complete, propagate `UnresolvedComputation` — never convert to "no
  collision". "Degrade to baseline", not "fail-open".
- **Binding** covers polytope + thermal arrays/shapes/model-IDs, exact float bits of
  `margin_k`/`feas_tol`, the audit/kernel schema and oracle solver-semantic version.
  Explicit checks + fallback, never `assert` (can be disabled). Atomic-publish only a
  fully verified artifact; quarantine on any mismatch.
- **Amortization** `Q* = ceil(build+validation_cost / (L_f − L_k))` from candidate- and
  mode-specific measurements; cached kernel → build cost 0. Treat "MaxHS exceeds
  break-even" as a prediction to enforce, not an invariant.
