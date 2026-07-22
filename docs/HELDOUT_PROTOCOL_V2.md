# Frozen Held-out Protocol v2 — Budgeted Anytime Synthesis

Freeze ID: `method-freeze-v2.1`
Freeze date: 2026-07-22
State: **OPENED_INVALID / PILOT_ONLY — this split is burned and must not
produce claim-grade results.**

## Incident, 2026-07-22

A `--split heldout_v2 --frozen` run executed for ~52 minutes and generated
held-out physical data before being stopped. Everything below that says the
split is unopened was true when written and is false now.

It is invalid on three independent grounds, any one of which is sufficient:

1. **Dirty worktree.** Run from baseline `89318c7` plus uncommitted changes
   (diff digest `6e133bc8f22c93b2`), not a clean revision or fresh clone.
2. **The algorithm changed after opening.** Commits `47577e3` (wire the
   Anytime-DSOS controller into the driver) and `bc96f23` (default separation
   to sequential) both postdate the launch. A held-out result must come from a
   revision frozen before the split is opened; this one cannot be attributed to
   any single method.
3. **Known gaps were still open.** The controller did not record the width
   action IDs behind its upper bound, so the contract is not replayable from
   the artifact; `bound_provenance` / `plan_validity` / `cost_optimality` came
   from a separate full-budget exact run rather than the same Anytime-DSOS
   invocation; `relative_gap` computed `(U-L)/U` while this document specifies
   `U/L`; and `--frozen` did not enforce the 1800 s budget, so an environment
   variable could produce a short-budget run labelled as frozen.

It produced 12 workload captures and 10 operators but **no `results.tsv`** — no
query conclusion, contract, bound or witness. Nothing is retracted because
nothing was concluded.

The artifacts are **retained, not deleted**, at
`/data/ziheng/experiments/certitherm-INVALID-heldout-v2-20260722` with the
launch-time diff and an `INCIDENT.md`. Deleting them would hide the incident;
for review integrity an honest record beats a clean-looking history.

**Consequence.** `arch_g/h/i` and the v2 workloads have been touched by an
out-of-protocol run. Claim-grade results require a new split under
`method-freeze-v3` with, at minimum, entirely new architectures. v2.1 is
retained below as the specification that v3 will inherit, not as a live gate.

## Why a new freeze rather than an edit to v1

`method-freeze-v1` is preserved unchanged in `HELDOUT_PROTOCOL.md`. Its
exact-closure gate is recorded as **failed on dev** and that record stands.

The dev matrix returned `{OPTIMAL: 0, UNSYNTHESIZABLE: 0, UNRESOLVED: 6}`: all
six queries exhausted the 1800 s budget. v1's criterion — "resolvable or proved
non-identifiable: at least 8 of 12 queries" — is operationalised in the report
code as `exact_status == OPTIMAL`, so dev scores 0/6 against it.

There is a natural reading under which dev is **6/6**: every query produced an
oracle-certified contract, just not a proof of its minimality. Choosing that
reading *after seeing dev* would be exactly the post-hoc protocol tuning this
project forbids. So v1 keeps its operational definition and its failure, and
v2 states a different research question up front.

**v2 must not be evaluated on v1's held-out split.** A new split is required
(see Separation) precisely so that no v2 endpoint is chosen with knowledge of
v1 held-out data.

## Research question

v1 asked: can the minimum-cost observation contract be computed exactly?
Dev answered: not within a practical budget on real operators.

v2 asks the question dev actually exposed:

> Under a fixed budget, can a proof-carrying method return an oracle-certified
> observation contract together with an independently verifiable bound on how
> far its cost can be from optimal?

This is a weaker claim than v1's and is stated as such. It is not a retreat to
heuristics: the contract is still verified by the exact collision oracle, and
the lower bound is still independently checkable.

## The separation dev established, which v2 is built to measure

Dev showed the two halves of the problem have very different difficulty:

- **Finding a sufficient contract is easy.** width reached cost 4174 in ~120 s
  and dual 4100–4132 in ~1100 s, against a 5250 full registry — a ~20.5% and
  ~21.3–21.9% reduction respectively.
- **Proving minimality is hard.** The exact path spent 1800 s on every query
  and closed none.

Note that dual buys only ~1–1.8% over width for ~9x the runtime, so dual is a
Pareto point, not a headline. v2 reports the cost–runtime frontier rather than
a single policy.

## Budget definition — what "under a fixed budget" means

v1 gave each method its own 1800 s. Combining the exact path's lower bound with
width's upper bound under that scheme would NOT describe a single 1800 s
algorithm; it would be a post-hoc pairing of two independently budgeted runs,
and reporting it as one anytime method would overstate what was measured.

v2.1 therefore freezes a **single 1800 s end-to-end budget per query** for the
Anytime-DSOS method:

1. width runs first and produces an oracle-certified contract, giving `U`;
2. the exact/IHS engine spends the REMAINING budget raising the certified
   lower bound `L`;
3. at any point the method returns `L <= C* <= U` with the plan, the bound
   provenance, the proof kind, the absolute gap and `U/L`.

`fixed` and `dual` remain **independent baselines with their own budgets**.
They do not contribute to the Anytime-DSOS interval and their costs must not be
substituted into `U`. If a baseline happens to find a cheaper certified
contract, that is reported in the Pareto comparison, not folded into the
method's result.

A run whose `U` and `L` come from separately budgeted executions must be
labelled as such and is not admissible as an Anytime-DSOS result.

## Frozen endpoints

Primary:

1. **Zero false certificates.** Any `CERTIFIED`/`OPTIMAL` result contradicted
   by replay is a hard failure, independent of every other number.
2. **Certified-contract coverage** — fraction of queries returning an
   oracle-verified contract within budget.
3. **Certified optimality interval** — for each query, the verified upper bound
   `U`, the independently checkable lower bound `L`, the absolute gap `U − L`
   and the ratio `U/L`.
4. **Self-verifiability split** — how many certificates carry
   `cost_optimality = PROVEN_SELF_VERIFIABLE` (checkable from the returned
   numbers) versus `PROVEN_SOLVER_ATTESTED` (closed by an unproved solver dual
   bound).

Secondary:

5. Exact closure count, as a secondary result rather than the gate.
6. Gap-versus-time curve, or area under it, per query.
7. Cost–runtime Pareto comparison of fixed, width and dual.
8. Non-identifiability witnesses, where the full library cannot separate.

## Pass conditions, declared before opening the split

- False certificates: **exactly zero**. No trade against any other endpoint.
- Certified-contract coverage: **at least 10 of 12** queries.
- Median certified upper bound: **at least 15% below the full registry cost.**
- At least **6 of 12** queries report a finite `U − L`, i.e. both a certified
  contract and a non-trivial lower bound.
- A run that returns a contract but no bound counts toward coverage and **not**
  toward the interval criterion.

These thresholds are set from dev's observed behaviour and are frozen now.
Missing them is a negative result to be reported, not a reason to adjust them.

## What must not be claimed

- Not "the minimum-cost contract" unless `U = L` for that query.
- Not `U − L` as an optimality gap when `U` is an uncertified candidate cover;
  only an oracle-verified contract supplies a valid `U`.
- Not solver-independence for `PROVEN_SOLVER_ATTESTED` results.
- Not any statement about unrestricted sensors, continuous-adaptive limits, or
  silicon truth. All results are relative to the registered finite channel
  library, the HotSpot model family, and the frozen margins and tolerances.
- Not that collision separation is solver-independent. Master optimality can be
  independently checked when a lattice or rational certificate closes it, but
  `no collision` still rests on the LP solver reporting infeasibility under the
  registered tolerances.

## Separation

Development remains ResNet-50 and Transformer on the three dev architectures
and three package regimes.

**Disjointness rule, stated per axis.** v2.1 supersedes v2's blanket "disjoint
from both the dev set and the v1 held-out set", which contradicted this
document's own workload decision below.

- **Architectures MUST be set-disjoint** from dev and from v1 held-out. This is
  where the split's novelty lives.
- **Workloads MAY reuse v1's held-out workloads**, on the recorded condition
  that v1's held-out was never opened and no v1 held-out result exists.

The earlier draft called the reuse "vacuously disjoint". That was wrong and is
withdrawn: set-disjointness is factually **violated** on the workload axis. The
defensible claim is narrower — no information flows, because there is no v1
held-out result for information to flow from. If v1's held-out is ever opened,
this permission lapses and v2.1 results become non-comparable to any later v1
result on shared workloads. The v2 architectures are registered in `experiments/architectures.tsv` under
`split = heldout_v2`, **before any v2 run**:

| id | grid | cut | interval | mtxu | ubuf | nop_bw | dram_bw |
|---|---|---|---|---|---|---|---|
| arch_g | 6x4 | 3x1 | 0.0009 | 128x176 | 2097152 | 176 | 160 |
| arch_h | 3x8 | 1x4 | 0.0021 | 176x112 | 524288 | 96 | 192 |
| arch_i | 9x2 | 3x2 | 0.0013 | 144x160 | 2097152 | 224 | 96 |

Verified disjoint from dev (7x3/1x1, 4x5/2x1, 4x4/2x2) and from v1 held-out
(5x6/1x2, 8x1/8x1, 4x2/4x2), both by grid/cut geometry and by full parameter
vector. They deliberately span cut orientations absent from both earlier sets:
a 3x1 horizontal cut, a 1x4 vertical cut, and a wide 9x2 grid.

**Precondition 1 checked 2026-07-22 — PASSED.** All three vectors are
realizable in ThermoDSE and their EDYP ordering is non-degenerate, on
resnet50 / package `default`:

| id | latency (ms) | energy (mJ) | yield | EDYP |
|---|---:|---:|---:|---:|
| arch_h | 0.4500 | 8.267 | 0.9571 | 3.887 |
| arch_g | 0.4563 | 9.402 | 0.9143 | 4.692 |
| arch_i | 0.7084 | 9.850 | 0.9661 | 7.223 |

Relative separations 20.7% and 53.9%, both far above the 1% degeneracy
threshold, so no vector needs replacing. Recorded here so the check cannot be
silently re-run later with a different outcome.

Scope of what this check may influence: the ONLY sanctioned decision it feeds
is binary — replace a vector if infeasible or degenerate. Nothing else about
these numbers may be used to select or tune a v2 endpoint. The split remains
UNOPENED: no DSOS query has been run against it, and no thermal feasibility or
observation-synthesis result exists for these architectures.

## Artifact contract

Unchanged from v1, plus per query: `certified_upper_bound`, `lower_bound`,
`absolute_gap`, `relative_gap`, `bound_provenance`, `plan_validity`,
`cost_optimality`, and the wall-clock at which each was last updated.

A timed-out query must archive its interval rather than reporting nothing. That
was not true before 2026-07-22: the driver's SIGALRM escaped the synthesis
boundary and the whole result was discarded, which is why v1's dev bound
columns are empty. Any v2 run must be executed with that fix present.

## Status

No v2 held-out result exists and the split has not been opened. The split is
now DEFINED and registered (see Separation), which is a different thing from
being opened: the vectors are fixed and recorded, and no query has been run
against them.

This document freezes the question, the endpoints and the pass conditions
before any of that happens, which is the only property that makes the eventual
result meaningful.

**Attempted 2026-07-22 and correctly refused.** A `--split heldout_v2 --frozen`
run aborted immediately with "refusing to write empty evidence table": the
driver found zero workloads for this split, so zero queries were built. No
operator, capture, query result or observation contract was produced, and the
empty scaffolding was removed. The split therefore remains UNOPENED.

The cause is a gap in this preregistration: architectures were registered but
**workloads were not**. `experiments/workloads.tsv` is also split-keyed, and
v2 has no entry there. Registering only half a split is a preregistration that
cannot be honoured, and the driver's refusal to emit an empty evidence table is
what caught it.

**Workload decision, recorded 2026-07-22 before any v2 result exists.**
v2 uses `mobilenetv2`, `unet`, `yolov2` and `googlenet` — the same four
workloads v1 reserved.

The argument, stated explicitly rather than assumed: v1's held-out was **never
opened** and **no v1 held-out result exists**, so those workloads carry zero
information. This document's per-axis rule permits the reuse
explicitly rather than claiming the sets are disjoint when they are not. The
*architecture* axis is where genuine novelty is required and arch_g/h/i supply
it, verified disjoint from both earlier sets.

What preregistration protects against here is selecting workloads to flatter a
result. That is impossible in this instance: zero v2 results exist to select
toward, and this commitment is recorded before the first query runs. Deferring
the choice would add no scientific protection, only delay.

The resulting matrix is 4 workloads x 3 architectures x 3 packages = 36 cases
grouped into 12 ordered three-candidate queries, matching v1's shape so the two
freezes remain comparable.

Remaining preconditions before a v2 run:

1. ~~Confirm ThermoDSE feasibility and non-degenerate EDYP ordering~~ — DONE
   2026-07-22, passed; see Separation.
2. ~~Register the v2 workloads~~ — DONE 2026-07-22, see Separation.
3. Build the physical HotSpot operators for the v2 architecture x package grid,
   with the direct-replay error contract enforced as in v1.
4. Execute with the timeout-preservation fix present, so a budget-exhausted
   query archives its bound instead of discarding it. (Verified in place.)
