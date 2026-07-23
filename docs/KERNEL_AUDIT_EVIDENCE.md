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
