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
> (a) `U` is an oracle-verified collision-free cover cost, computed in exact
> rational arithmetic from the cover's action costs; (b) `L` is an
> **exact-arithmetic weak-duality lower bound** obtained by evaluating
> `_integer_lagrangian_bound` (or `_anytime_lower_bound`) on the LP dual marginals
> in `Fraction` and lattice-lifting it — a bound valid for *any* non-negative dual,
> so it never re-trusts the HiGHS basis; and (c) the interval, both provenance
> receipts, and the witness-carrying cut ledger are bound to one `InstanceReceipt`
> digest, so the artifact is **re-verifiable against canonical instance inputs**
> (registry, power polytope, semantic thermal family, operator SHA, tolerances) —
> not "reproducible from the receipt alone", since the receipt stores digests, not
> the inputs themselves.

The artifact is exactly one of two states:

- **`CERTIFIED_INTERVAL`** — `L` is exact-arithmetic weak-duality/lattice certified
  *and* `U` is oracle-verified *and* every ledger cut passed the independent
  cut-validity check. `L = U` (closure) is the special case detected by
  `_self_verified_master_cost`; it is not required.
- **`UNRESOLVED`** — anything else (solver failure, timeout, an unverifiable cut, a
  bound the exact certifier could not produce). A `solver_asserted` HiGHS dual may
  be *recorded for diagnostics*, but **is never published as an endpoint of the
  contract interval.**

Success = the driver produces a `CERTIFIED_INTERVAL` artifact on all four dev
candidates above, and an independent re-load re-derives the same interval, the
same receipt digest, and re-validates every cut. It is **not** required that
`L = U`; the deliverable is a provenance-bound *bounded-gap* contract, described
as such.

## Correctness gates (mandatory — any failure kills the round)

Derived from the two 2026-07-23 audits and the round-start peer review:

1. **Single-artifact binding (audit §1).** The `[L, U]` interval, both provenance
   receipts, and the cut ledger are emitted by one entrypoint into one artifact.
   No step consumes another step's output without checking the shared
   `InstanceReceipt` digest. A digest mismatch → structured `UNRESOLVED` + nonzero
   exit, never a silent proceed. The receipt binds registry (ordered
   id+cost+tolerance+vector), power polytope, **semantic `ThermalFamily`** (not just
   the operator NPZ bytes), operator source SHA, `margin_k`, `feas_tol`, and Git
   SHA; `verify()` re-checks *every* such field — including the live tolerances —
   against the running instance.
2. **Lower bound is exact and solver-independent (review F8/F10).** `L` is the
   `Fraction`-valued `_integer_lagrangian_bound(costs, cuts, dual)` (valid for any
   `y ≥ 0`), lattice-lifted via `_fraction_lower_float`; equivalently
   `_anytime_lower_bound` for the global bound. `_self_verified_master_cost` is used
   **only** to detect closure (`L = U`), never as the general bound. The scalar
   HiGHS `mip_dual_bound` is stored as `solver_asserted_milp_dual` for search
   ordering / diagnostics and is **never** an endpoint. A negative test must show a
   fabricated huge `mip_dual_bound` with a low exact Lagrangian does **not** inflate
   `L`.
3. **Cut validity — every ledger cut is a genuine necessary constraint (review
   F9).** `L`'s soundness is conditional on the cut set. Each ledger cut carries its
   generating SAFE/REJECT world-pair witness and cell identity. On reload an
   **independent validator** (not the derivation expression that produced it)
   re-checks: the witness's power feasibility in the polytope, its SAFE/REJECT
   classification under the thermal family, observation indistinguishability under
   the currently-selected actions, and recomputes the full separator set `S` from
   action tolerances — then confirms the ledger cut **equals `S` exactly**. On
   soundness: only a *strict subset* of `S` is unsound (it can inflate `L`); a
   superset is a valid-but-weaker constraint. We nonetheless adopt **exact
   equality** as a deliberately stronger, canonical ledger invariant, not because a
   superset is mathematically invalid. Any cut that fails → `UNRESOLVED`. Without
   this gate `L` is "self-verified given an *unverified* ledger", not a
   physical-instance certificate.
4. **Exact rational endpoints (review F11).** `U` is recomputed from the cover's
   action IDs as `Σ Fraction(float(cost))`; `L ≤ U` and closure are decided in
   rational arithmetic. No `abs(L−cover)<0.5` integer assumption; `_cost_lattice`
   derives the lattice from the registry. Floats are presentation-only.
5. **Fresh-clone fail-closed (audit §3).** A missing or instance-mismatched cut
   ledger yields structured `UNRESOLVED` + nonzero exit (not `print + return 0`).
   The ledger persists cuts + costs + witnesses **plus** the `InstanceReceipt`
   digest; load validates it against the current instance or refuses.
6. **Run identity bound too — `RunReceipt` (review F5).** A second mandatory digest
   covers the algorithm controls that move the interval at fixed instance:
   `collision_objective` + weights, fallback policy, oracle solver options, numeric
   acceptance thresholds, deletion order, time budget, worker count, and the
   HiGHS/dependency versions. Both `InstanceReceipt` and `RunReceipt` digests are
   bound into the ledger and the final artifact. `InstanceReceipt` stays
   mathematical instance identity only.
7. **Claim-grade worktree (review F6).** A claim-grade run requires a valid HEAD
   commit and a clean *relevant* worktree; a dirty tree or a failed Git lookup →
   `UNRESOLVED`, not an artifact with `git_sha = None`. The receipt records the Git
   tree/commit; non-claim diagnostic runs may omit it and are labelled as such.
8. **Atomic, self-validating publication (review F12/F14).** The artifact is
   written to a temp file in the destination, flushed/fsync'd, **reloaded and fully
   re-validated** (receipt, `RunReceipt`, every cut witness, exact `L`, exact `U`,
   top-level digest), then atomically renamed. A worker crash / SIGALRM / partial
   write must leave **no** artifact with usable interval fields.
9. **Worker parity as a multi-cover artifact (audit §4 / review F12).** A committed
   `parity.json` shows `CERTITHERM_LP_WORKERS=1` vs `16` agree on the canonical
   cell-status map and feasibility verdict across **several** frozen covers (full
   registry, sparse, known-collision, no-collision, numerically hard cells) on each
   instance — not one fixture. Any worker exception / missing / duplicate / unknown
   cell → `UNRESOLVED`. Parallelism changes *speed only*, proven by artifact.
10. **Fail-closed vocabulary throughout.** Every timeout / numerical disagreement →
    `UNRESOLVED`; an empty-separator witness → `UNSYNTHESIZABLE` (the driver stops,
    unlike the PoC); a full-registry UB is reported only after exhaustive
    verification. No fabricated feasible/infeasible verdict.

## Canonical artifact schema (review F14 — the verification target)

One self-verifying artifact an *independent* verifier can check with **no MILP
result**:

- `InstanceReceipt` (semantic instance hashes) + `RunReceipt` (algorithm/env
  hashes) + source-file/Git provenance;
- exact costs and ordered action IDs (rational);
- each cut with its physical SAFE/REJECT world-pair witness and cell identity;
- the rational non-negative dual vector used for `L`;
- the exact recomputed `Fraction` Lagrangian value and its lattice lift → `L`;
- the `U` cover action IDs and the exhaustive oracle status ledger → `U`;
- a top-level digest over all of the above.

The verifier re-validates witnesses + cuts, evaluates the dual bound in rational
arithmetic, derives `U` from the action IDs, checks `L ≤ U`, and verifies the
top-level digest. `mip_dual_bound` is diagnostic only; a lower bound stronger than
the LP/lattice lift, if ever needed, requires a proof-producing B&B object, not a
bare solver claim.

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
- a published `L` that is not reproduced by an *independent* re-evaluation of the
  exact `Fraction` Lagrangian bound on the recorded dual;
- any ledger cut that fails the independent cut-validity check yet contributes to
  `L`;
- any `L > verified U` on a frozen input (in rational arithmetic);
- a `solver_asserted` HiGHS dual published as an endpoint of the contract interval;
- worker parity fails (1 vs 16 disagree on cell-status or feasibility on any tested
  cover);
- a fresh clone with a missing/mismatched ledger, or a dirty claim-grade worktree,
  proceeds instead of failing closed.

## Scope discipline

- **In scope:** `InstanceReceipt` + `RunReceipt`, the witness-carrying,
  provenance-bound cut ledger and its independent validator, the single
  `v4_driver` wiring master → oracle verify → deletion → one atomically-published
  artifact, reusing the production `_integer_lagrangian_bound` /
  `_anytime_lower_bound` / `_cost_lattice` certifier, and the multi-cover parity
  artifact.
- **Out of scope this round:** integrating a versioned `collision_objective` into
  the frozen `synthesis.py` oracle (plan Part B item 4 — a later round);
  the `cost ≤ L` diversification lever against degeneracy (deferred fork B); any
  held-out execution; cuOpt/GPU in the certifier (excluded).
- **No new candidates, no added wall time.** The two running deletions finish and
  are archived as diagnostic (D8); nothing beyond them is launched at claim grade.

## Requested dissents (≥3, per CCFA)

1. **Receipt completeness.** With the `RunReceipt` added, is there *still* a knob
   that moves `[L, U]` at fixed instance yet is bound by neither digest (e.g. a
   BLAS thread count that changes LP tie-breaking, an env var read by the oracle)?
2. **Cut-validity independence.** Is the reload cut validator genuinely independent
   of the derivation that produced the cut, or does it share the same masking
   expression (so a systematic derivation bug would pass its own check)?
3. **Exact-`L` honesty.** Is `_integer_lagrangian_bound` on the recorded dual truly
   solver-independent end-to-end, including how the dual vector is *captured* from
   HiGHS (rounding, sign, ordering) before it is fed in? Could a mis-captured dual
   ever *raise* the bound rather than only loosen it?
4. **Atomic-publish reachability.** Are there still paths (fsync failure, rename
   across filesystems, a crash between reload-validate and rename) where a
   partially-usable artifact survives, or where a valid run is lost as `UNRESOLVED`?
5. **Parity sufficiency.** Do the chosen frozen covers actually exercise the
   nondeterministic cells, or could a different selection still diverge under
   threads?

## Verification

- All correctness gates as tests in `CertiTherm/tests`, run on a fresh moe-server
  clone from a clean committed revision via
  `.claude/skills/moe-server-remote/scripts/remote_exec.sh`. Residual scaffold
  tests still owed with the driver: cut tampering, partial-write recovery, and
  exact re-derivation of `L` and `U` end-to-end.
- One Codex peer-review pass on this round-start (this revision) before the driver
  is built, and one on the driver + artifact before merge to `master`.
- D8 (the diagnostic table above, finalised once the two deletions complete) is
  recorded in `docs/V3_DEV_REHEARSAL_EVIDENCE.md` as NON-CLAIM.

## Change log

- **v2 (2026-07-23):** revised after the round-start peer review. Corrected the `L`
  path (exact `_integer_lagrangian_bound`/`_anytime_lower_bound`, not
  `_self_verified_master_cost`, which is closure-only; never the scalar
  `mip_dual_bound`); added the cut-validity gate (F9), exact rational endpoints
  (F11), `RunReceipt` (F5), claim-grade worktree gate (F6), atomic self-validating
  publication (F12/F14), multi-cover parity, the two-state artifact contract, and
  the canonical artifact schema. Scaffold code fixes F2/F3/F4/F7/F12a already
  landed (`993a55a`).
