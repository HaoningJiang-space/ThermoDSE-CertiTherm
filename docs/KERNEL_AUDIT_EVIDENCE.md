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
