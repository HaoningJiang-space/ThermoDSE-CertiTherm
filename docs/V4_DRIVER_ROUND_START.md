# method-freeze-v4 — round start: single provenance-bound `[L, U]` driver

**Branch:** `round/v4-upper-bound`
**Date:** 2026-07-23
**Status of prior work:** the strong-cut PoC (D3–D7) is accepted as *diagnostic*
signal. Two reviews (the freeze-v4 plan's Codex pass, and the two-part audit on
2026-07-23) converged on the same verdict:

> **algorithm direction ✓ · cross-candidate signal ✓ · certificate engineering ✗ · formal integration not started.**

This round does **not** chase exact optimum, add candidates, or add wall time. It
closes the *certificate-engineering* gap so the bounded-gap result can become an
auditable artifact instead of a hand-assembled pair of program outputs.

## Diagnostic baseline this round builds on (NON-CLAIM)

Raw remote logs, all MaxHS runs truncated at 1800 s (never exact-closed), all
deletions honouring `CERTITHERM_LP_WORKERS`:

| Candidate | MaxHS L (solver-asserted) | deletion U | ratio |
|---|---:|---:|---:|
| resnet50 c0 `arch_b` (ref, 2 h) | 1256 | 1502 | 1.20× |
| resnet50 c1 `arch_c` | 928 | 1091 (complete sweep) | 1.176× |
| resnet50 c2 `arch_a` | 1256 | ≤1546 (truncated) | ≤1.231× |
| transformer c0 `arch_b` | 1168 | ≤1478 (truncated) | ≤1.265× |

The ~1.2–1.3× pattern is real and not arch_b-specific, **but** every `L` is a
HiGHS-solver-asserted restricted-master dual truncated by an arbitrary wall
budget, every `[L, U]` is stitched by hand from two programs, and neither program
binds the instance it ran on. That is precisely what this round fixes.

## Single claim (falsifiable)

> A single fresh-clone driver `v4_driver`, given a frozen candidate instance,
> emits **one artifact** containing a `[L, U]` observation-contract interval where
> (a) `U` is an oracle-verified collision-free cover cost, (b) `L` is a
> **self-verified `weak_duality`** lower bound produced by the production
> `_self_verified_master_cost` / `_cost_lattice` certifier (the HiGHS dual is used
> only for search ordering, never as the reported certificate), and (c) both
> endpoints and every intermediate ledger are bound to one `InstanceReceipt`
> digest (registry SHA, action-ID ordering, operator SHA, tolerance, margin, Git
> SHA), so the artifact is reproducible and tamper-evident from the receipt alone.

Success = the driver produces such an artifact on all four dev candidates above,
and an independent re-load of the artifact re-derives the same interval and the
same receipt digest. It is **not** required that `L = U`; the deliverable is a
provenance-bound bounded-gap contract, described as such.

## Correctness gates (mandatory — any failure kills the round)

Derived one-for-one from the 2026-07-23 audit's four retained findings:

1. **Single-artifact binding (audit §1).** The `[L, U]` interval, both provenance
   records, and the cut ledger are emitted by one entrypoint into one artifact.
   No step consumes another step's output without checking the shared
   `InstanceReceipt` digest. A digest mismatch → structured `UNRESOLVED` + nonzero
   exit, never a silent proceed.
2. **Lower bound provenance (audit §2).** The reported `L` carries
   `bound_provenance == "weak_duality"` and equals `_self_verified_master_cost(...)`
   after lattice lifting. The raw HiGHS `mip_dual_bound` is recorded separately as
   `solver_asserted_milp_dual` and is *never* substituted for `L`. If the
   self-verified certifier cannot produce a finite bound, `L` is reported as
   `solver_asserted` **and the claim word "certified" is withheld** for that case.
3. **Lattice derived, not assumed (audit §3).** Exactness / closure tests use
   `_cost_lattice(costs)` (exact `Fraction`) — no `abs(L−cover)<0.5` integer
   assumption anywhere in the driver.
4. **Fresh-clone fail-closed (audit §3).** A missing or instance-mismatched cut
   ledger yields structured `UNRESOLVED` + nonzero exit (not `print + return 0`).
   The cut ledger persists cuts + costs **plus** the `InstanceReceipt` digest; load
   validates it against the current instance or refuses.
5. **Worker parity as an artifact (audit §4).** A committed `parity.json` shows
   `CERTITHERM_LP_WORKERS=1` vs `16` on one frozen input produce the identical
   collision set and identical final feasibility verdict, with both sides hashed.
   Parallelism is allowed to change *speed only*, proven by artifact, not comment.
6. **Fail-closed vocabulary throughout.** Every timeout / numerical disagreement →
   `UNRESOLVED`; an empty-separator witness → `UNSYNTHESIZABLE` (the driver stops,
   unlike the PoC); a full-registry UB is reported only after exhaustive
   verification. No fabricated feasible/infeasible verdict.

## Performance gates (secondary — measured, not kill conditions this round)

Reported on the four dev candidates at the registered budget, but do **not** kill
the round (they gate the *later* held-out claim, not this engineering round):
`L(t)`, `U(t)`, time-to-target-gap, oracle calls, cut count, unknown cells,
false-certificate count (must be 0).

## Kill / rollback

The zero-objective feasibility oracle remains the always-available default; any of
these reverts to it and ends the round:

- any single-artifact / receipt-binding gate cannot be met (endpoints stay
  hand-stitched);
- a reported `L` labelled `certified`/`weak_duality` that is not reproduced by an
  independent re-load of `_self_verified_master_cost`;
- any `L > verified U` on a frozen input;
- worker parity fails (1 vs 16 disagree on collision existence or feasibility);
- a fresh clone with a missing/mismatched ledger proceeds instead of failing
  closed.

## Scope discipline

- **In scope:** `InstanceReceipt`, provenance-bound cut ledger, the single
  `v4_driver` wiring master → oracle verify → deletion → one artifact, reusing the
  production `_self_verified_master_cost` / `_cost_lattice` certifier, and the
  parity artifact.
- **Out of scope this round:** integrating a versioned `collision_objective` into
  the frozen `synthesis.py` oracle (plan Part B item 4 — a later round);
  the `cost ≤ L` diversification lever against degeneracy (deferred fork B); any
  held-out execution; cuOpt/GPU in the certifier (excluded).
- **No new candidates, no added wall time.** The two running deletions finish and
  are archived as diagnostic (D8); nothing beyond them is launched at claim grade.

## Requested dissents (≥3, per CCFA)

1. **Receipt completeness.** Does the `InstanceReceipt` digest bind *everything*
   that could change the interval — is there a field (e.g. the power-polytope
   constraints, the margin sign convention, float endianness in the vector hash)
   whose change would not alter the digest yet would alter `[L, U]`?
2. **"weak_duality" honesty.** Is feeding the strong-cut MILP dual into
   `_self_verified_master_cost` actually a *self-verified* certificate, or does it
   silently re-trust HiGHS (e.g. if the exact dual is reconstructed from the same
   solver's basis)? If the latter, gate 2 is not met and the word "certified"
   stays off.
3. **Fail-closed reachability.** Are there paths (worker pool crash, SIGALRM,
   partial ledger write) where the driver emits a `[L, U]` artifact without a
   valid receipt, i.e. the binding is bypassable under failure?
4. **Parity sufficiency.** Does agreement on one frozen input generalise, or could
   worker count change the collision set on a *different* selection (e.g.
   nondeterministic LP tie-breaking under threads)?

## Verification

- All correctness gates as tests in `CertiTherm/tests`, run on a fresh moe-server
  clone from a clean committed revision via
  `.claude/skills/moe-server-remote/scripts/remote_exec.sh`.
- One Codex peer-review pass on this round-start before the driver is built, and
  one on the driver + artifact before merge to `master`.
- D8 (the diagnostic table above, finalised once the two deletions complete) is
  recorded in `docs/V3_DEV_REHEARSAL_EVIDENCE.md` as NON-CLAIM.
