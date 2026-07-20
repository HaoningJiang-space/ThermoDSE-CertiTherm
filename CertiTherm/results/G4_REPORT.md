# G4 acquisition gate: closure report

Status: **G4 PASS (empirical gate); registered single-action check is an exhaustive negative**
Date: 2026-07-20
Source commit: `d7409653...` (clean-clone claim-grade runs)
Suite: `g3_real_2x2x2_content_bound` (artifact `69c46a9b…`, replay PASS)

This report supersedes the 2026-07-20 "implementation authored but
unexecuted" status. The G4 contract question is:

> Given a replay-valid `NON_IDENTIFIABLE` architecture query, its two
> decision-changing witness tuples, and a content-bound registry of obtainable
> measurement actions with declared costs, find the cheapest registered action
> whose two witness-conditioned **complete architecture queries** are both
> certified and reproduce the two distinct witness outcomes.

Two claim-grade evidence sets were produced from a fresh clean clone
(`/tmp/certitherm_g4_clone` at `d740965`), writing only outside Git
(`/tmp/g4_outputs/`), each with a passing replay receipt.

## 1. Registered single-action acquisition (implementation-level check)

Registry: `certitherm.g4-measurement-registry.v1`,
`physical_measurement_family`, 180 per-block placed-power channel actions per
stratum (100 on arch_5x4_rect_struct + 80 on arch_4x4_mesh_fullcut — the exact
undetermined set of the frozen fixed-refinement baseline), one channel = one
expensive physical query. Source placed-power reports are SHA-256-bound inside
each registry bundle (`/tmp/g4_registry/…`).

| Query | Registered | Evaluated | Indistinguishable | Separating, not confirming | Status | Replay |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| g3-real-attention-standard_sink_s06 | 180 | 180 | 114 | 66 | NO_REGISTERED_WITNESS_CONFIRMING_ACTION | PASS |
| g3-real-attention-enhanced_sink_s10 | 180 | 180 | 113 | 67 | NO_REGISTERED_WITNESS_CONFIRMING_ACTION | PASS |

This is an exhaustive registered negative, not a machinery failure: **no
single per-block channel can confirm this witness pair.** Both candidates
straddle the 330 K limit (arch_5x4 ∈ [323.07, 332.16], arch_4x4 ∈ [323.05,
331.26] on s06), so certifying `arch_5x4` needs upper_5x4 ≤ 330 and
certifying `arch_4x4` needs lower_5x4 > 330 *and* upper_4x4 ≤ 330. A
single-candidate action cannot deliver the second pair of bounds at once. The
machinery's positive confirmation ability is established at synthetic-fixture
level (`test_g4_acquisition.py`, two WITNESS_PAIR_CONFIRMED cases).

## 2. Matched policy comparison (empirical gate)

Three policies over the two physical NON_IDENTIFIABLE strata, one registered
per-block channel family, one cost unit, stopping at the first `CERTIFIED`
complete query; correctness = certified outcome equals the placed-power
physical reference (`arch_5x4_rect_struct` on both strata).

| Policy | s06 channels | s10 channels | Total | vs fixed | Correctness |
| --- | ---: | ---: | ---: | ---: | --- |
| Fixed uniform refinement | 180 | 180 | 360 | — | 2/2 |
| Uncertainty-width refinement | 29 | 29 | 58 | −83.9% | 2/2 |
| Decision-witness-directed | 38 | 39 | 77 | −78.6% | 2/2 |

Policy-comparison artifact `e8f713b6…`, replay receipt PASS, matched
correctness coverage: true.

Solver-side cost per stratum: fixed 1 query solve (1.4 s); width 30 solves
plus 9,628 interval-ranking LPs (≈66 s); witness-directed 39–40 solves with
zero ranking LPs (≈56 s) because its ranking is read directly from the stored
witness tuples — a free byproduct of certification.

Channel placement: witness-directed puts 100% of channels (38/38, 39/39) on
the decision-carrying candidate arch_5x4; uncertainty-width spends 13/29
channels on the decision-irrelevant arch_4x4 before converging.

## Gate accounting

| Contract requirement | Outcome |
| --- | --- |
| Fewer expensive queries than fixed refinement at matched correctness/coverage | **PASS** — 58 and 77 vs 360 channels at 2/2 matched correctness |
| Implementation-level single-action check | Registered exhaustive negative ×2 (physics: cross-candidate straddle); positive control at synthetic-test level |
| EDA-specific mechanism (not generic policy tuning) | Ranking signal is the decision-witness pair stored in the parent certificate — no generic acquisition heuristic |
| Frozen nonclaims | No global/least-information optimality claimed; costs valid only inside the registered per-block family under the declared cost model |

**G4 verdict: PASS.** With G3 full PASS already on record, every gate in the
research contract (G1–G4) is now closed. The authoritative gate ledger is
`results/G3_REAL_2x2x2_CONSOLIDATED_REPORT.md`.

## Artifacts (external, self-authenticating)

| Object | Path | SHA-256 (prefix) | Replay |
| --- | --- | --- | --- |
| G4 acquisition artifact s06 | /tmp/g4_outputs/g4_artifact_s06.json | 6dc11454 | PASS |
| G4 acquisition artifact s10 | /tmp/g4_outputs/g4_artifact_s10.json | 4ac55954 | PASS |
| Policy comparison artifact | /tmp/g4_outputs/g4_policy_artifact.json | e8f713b6 | PASS |
| Registry bundle s06 | /tmp/g4_registry/attention-standard_sink_s06/ | d5217ed5 (registry) | self-verified |
| Registry bundle s10 | /tmp/g4_registry/attention-enhanced_sink_s10/ | fb2af825 (registry) | self-verified |

In-repo summary: `results/G4_POLICY_COMPARISON_20260720.json`.
