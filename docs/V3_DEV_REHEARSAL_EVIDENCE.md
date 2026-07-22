# Held-out v3 development rehearsal ledger

This ledger records method-freeze-v3 rehearsals on the development registry.
They are non-claim runs and cannot open or tune the held-out split. Raw bundles
remain on moe-server; their immutable manifests are bound below.

## R1 — infrastructure pass, endpoint-population failure

- Producer commit: `5370512387d62c0bbfc7c0c1e9b39365dedb8bc7`
- Profile / registry: `dev_v3` / `dev`
- Host / Python: `hpclab03` / `3.8.10`
- Budget: 150 seconds per method; deliberately not a frozen-budget result
- Fresh-clone checks: 147 tests passed; CPU HotSpot smoke and GPU parity passed
- Physical evidence: 9/9 operators, 270 direct replays, maximum residual
  0.00149192487 K against the frozen 0.01 K bound
- Schema evidence: 6/6 query rows and all 45 registered result columns
- Method outcome: 0/6 certified U, 0/6 finite L, 0 false certificates, and
  0 unexpected failures. All query methods ended by the declared timeout.
- Decision: **does not close precondition 3**. The run validates launch,
  deadline, physical, receipt, and serialization paths, but not value-bearing
  Anytime endpoints. Repeat the unchanged method on dev at the protocol's
  actual 1800-second budget; do not alter costs, ordering, thresholds, or the
  held-out registry.

Artifact bindings:

- `SHA256SUMS`: `cbd0c97e03f1fa29bfeee49429eb469c1a6269d71874dbc146d0bda98f476989`
- `results.tsv`: `75b927a2e951179a56ab861105d85e5bddbe69a457560a7be327f0353641d96b`
- `ARTIFACTS.tsv`: `e0c039b14d07feafcbda57a3bde80be7952de8783c0bdb8365a32b028e72c77e`
- Manifest verification: 47/47 files passed `sha256sum -c`

### R1 root cause, established after the fact

R1's "0/6 certified U, 0/6 finite L" was **budget starvation, not a wiring
defect**. `anytime_upper_seconds = 150.02` and `anytime_lower_seconds = 0.0` in
all six rows: `anytime_dsos` Phase 1 (width) consumed the entire 150 s budget,
so Phase 2 (exact) never started. The standalone exact method, running on its own
150 s, did report a lower bound of 1.0–2.0.

Two structural facts follow, and both are recorded here because they outlive R1:

1. The controller reserves **no** share for the lower-bound phase. Phase 1 takes
   all remaining time, so it can starve Phase 2 to zero. Pre-registering a staged
   allocation is a `method-freeze-v4` item.
2. `CERTITHERM_QUERY_WORKERS` is 3 for `dev`/`dev_v3` and frozen at 3 for
   `heldout_v3` (`experiments.py:95`, `2094`), but 1 for `heldout`
   (`experiments.py:2061`). **The same 1800 s budget therefore buys different
   amounts of work in the two splits.** This is the most likely explanation for
   width taking ~110 s standalone in the earlier dev run but exceeding 150 s under
   R1's controller on the same registry; it is a hypothesis pending a paired
   rerun, not an established cause.

## R2 — 1800 s budget, prediction registered before the result

**Registered 2026-07-22, while the run was still in operator generation and had
produced no `results.tsv`.** Recorded in advance so it cannot be fitted to the
outcome.

- Run: `certitherm-v3-rehearsal-1800-ae494e7`, PID 148449, started
  2026-07-22T14:32:02Z, `--split dev_v3 --output artifacts/v3-dev-rehearsal`.
- Producer commit: `ae494e7`.

Prediction (**speculative** — an extrapolation from one 150 s truncated run, not
a derivation):

- 6/6 queries report `certified_upper_bound = 4174` with
  `anytime_upper_source = width`.
- `certified_lower_bound <= 10`; `relative_gap > 99%`.
- 0/6 `OPTIMAL`; 0 false certificates.

Rationale: the controller grants Phase 2 only `1800 − width_seconds`, which is
*less* exact-search time than the standalone exact method already spent at 1800 s
without resolving. R2 therefore cannot be expected to close any gap.

A wrong prediction is itself a finding and must be recorded as such rather than
retrofitted.

**R2 will not close precondition 3 either way.** An interval whose lower bound is
uninformative is not a value-bearing Anytime endpoint. The open question it feeds
into is *why* the bound is tiny, for which three explanations are live:

- **(c) cross-candidate starvation** — `synthesize_ordered_query`
  (`synthesis.py:1243-1331`) iterates required candidates sequentially and
  returns on the first non-`OPTIMAL` one, so every later required candidate
  contributes **zero** to the query bound even though Theorem 2 permits summing
  candidate-local optima over disjoint libraries;
- **(a)** per-round cost at dev scale;
- **(b)** LP dual saturation as cuts overlap.

These are not currently distinguishable from the emitted evidence:
`QueryObservationPlan.iterations` is computed (`synthesis.py:1256`) and then
dropped — it is not among the 45 result columns.

**R2 was terminated before it produced any `results.tsv`** and is therefore not
evidence; see `TERMINATED.md` in its run directory. The prediction above stands
untested. It was superseded by the diagnostic run below, which answers the same
question far more cheaply.

## D1 — 150 s diagnostic run: ~1,400 cuts yield a bound of 2

Producer commit `8eec010` (`round/v3-separation-diagnostics`), dev registry,
150 s budget, non-claim. Purpose: populate the separation diagnostics added in
`4635fe2` and distinguish hypotheses (a)/(b)/(c).

| workload/package | iters | candidates done | cuts generated | accepted | active | bound |
|---|---:|---:|---:|---:|---:|---:|
| resnet50/default | 4 | 0 of 3 | 1917 | 1719 | 1599 | 2.0 |
| resnet50/standard | 4 | 0 of 3 | 1902 | 1574 | 1412 | 1.5 |
| resnet50/enhanced | 4 | 0 of 3 | 1902 | 1599 | 1385 | 1.0 |
| transformer/default | 4 | 0 of 3 | 2031 | 1446 | 1272 | 2.0 |
| transformer/standard | 4 | 0 of 3 | 2025 | 1201 | 966 | 1.0 |
| transformer/enhanced | 4 | 0 of 3 | 2028 | 1215 | 940 | 1.0 |

**Finding: roughly 1,400 active cuts yield a lower bound of 2.0.**

### What this establishes

- **Hypothesis (a), too few rounds — refuted.** Cut generation is productive:
  ~500 cuts per iteration, ~1,900 generated in 150 s. Scarcity is not the issue.
  Every performance round so far — the 32× pool-churn fix, the GPU separation
  gate, the 15-worker scheduler — accelerated cut *production*, which this table
  shows was never the constraint.
- **Hypothesis (c), candidate starvation — present.** `candidates_completed =
  0 of 3` in every row, always stopping at candidate 0. Round-robin scheduling
  is unlikely to repair an orders-of-magnitude weakness, but it would protect
  against one pathological candidate monopolising the budget.

### Correction, 2026-07-23 — claims withdrawn after peer review

The first version of this section drew three conclusions that do not follow from
the measurement. They are recorded here rather than deleted.

1. **"Integrality gap of roughly 700×" — withdrawn.** It divided the 4,174
   `width` cost by three candidates to infer a candidate-local optimum of
   ~1,400. That is not legitimate: 4,174 is a feasible *upper bound* for the
   whole query, and Theorem 2 licenses summing candidate-local optima, not
   averaging one plan across candidates, which differ in library and difficulty.
2. **"`lp_relaxation_bound == milp_lower_bound` confirms saturation" —
   withdrawn.** Both fields are written from the same `_anytime_lower_bound`
   call; `_solve_master` never ran. Their equality is schema aliasing, not two
   solvers agreeing. (See the `milp_lower_bound` naming defect below.)
3. **"Bound saturation confirmed and dominant" — withdrawn as stated.** It
   presumes the answer. `C*` is unknown: the interval is `[2, 4174]` and nothing
   measured says where in it the truth lies. If `C*` were small, the width/dual/
   fixed contracts would simply be badly suboptimal and the bound would not be
   weak at all.

### The one structural result that does survive

Dual feasibility gives `Σ_{e: a separates e} y_e ≤ c_a` per action; summing over
actions gives `Σ_e y_e·|S_e| ≤ Σ_a c_a = C_total`, and `L(y) ≤ 1ᵀy`. Hence

> `L ≤ C_total / s_min`, for `s_min` the smallest cut support.

This is independent of `C*`. With `C_total = 5250`, a reported `L = 2` implies
average cut support `≥ 2,625` actions. Conversely, certifying any *large* `C*`
requires near-singleton cuts: proving action `a` necessary means exhibiting two
worlds that **only `a`** separates.

So *if* `C*` is large, cut support is the binding constraint and no amount of
MILP closure, faster LP, GPU, or scheduling changes it. The antecedent is
unverified.

### Next experiment — a primal–dual–integer triangle, not another gate

On one persisted candidate cut matrix: validate the cuts, solve the restricted
master as a primal LP, run `_anytime_lower_bound` and check it does not exceed
that optimum, solve the restricted master as a MILP, and record the support
distribution `|S_e|` against the predicted `≥ 2,625`.

This separates two explanations that currently look identical: a genuinely weak
relaxation, versus **a defect in the bound implementation**. Thousands of cuts
yielding 2 is unusual enough that implementation error must be excluded before
any structural claim is made. The MILP's role here is diagnostic — it reveals
whether the integer optimum over discovered cuts is 2, 15, or 1000.

The restricted-master MILP optimum *is* a valid lower bound on the full integer
optimum (relaxing the cut set enlarges the feasible region), provided the cuts
are globally valid, columns and costs match the candidate-local problem, only a
solver-certified bound is used on timeout, and candidate-local values are summed
only where Theorem 2 applies.

### Inference boundary

The measured facts are only the counters and bounds tabulated above. That the
separation LP uses a zero objective (`synthesis.py:598`) is a fact; that this
*causes* large-support cuts is a hypothesis, not a diagnosis — a zero-objective
LP returns an implementation-dependent basic solution, and basic solutions lie
on many constraint boundaries rather than deep in the interior. The 10–41%
domination rate is evidence of redundancy, which has several possible causes.

## D2 — 150 s acceptance run after the scheduler fixes

Producer commit range `4635fe2..4d1e0f7` on `round/v3-separation-diagnostics`,
dev registry, 150 s budget, non-claim. Purpose: verify the three defects found
while auditing `certitherm-v31-rehearsal-150-05d11ae` are closed.

| criterion | before | after |
|---|---:|---:|
| `unexpected_failure` rows | 2 of 6 | **0 of 6** |
| fabricated `*_seconds = 0.0` | 2 | **0** |
| `exact_lower_bound_provenance` | absent | `weak_duality` (6/6) |
| `result_schema_version` | absent | `2` |

The two rows that previously reported `width_seconds = 0.0` now report ~150 s,
which is what they actually consumed.

**The diagnostics are byte-identical to D1** — iterations 4, active cuts
1599/1412/1385/1272/966/940, bounds 2.0/1.5/1.0/2.0/1.0/1.0. The fixes changed
what is *reported*, not what is *computed*, which is the intended blast radius
for a containment-and-honesty round.

`exact_lower_bound_provenance = weak_duality` on every row is the direct
confirmation of the naming defect: the column called `milp_lower_bound` never
once held a MILP bound.

### Defects closed

1. **A budget `TimeoutError` could escape containment.** The interval timer
   stayed armed until the `finally`, and the `finally` itself is not inside the
   `try` — so an alarm delivered there propagated past the `except` that had
   already been passed. Callers label an escaping exception a worker-protocol
   failure, `_unexpected_method_failures` counts that as UNEXPECTED, and
   `AnytimeGateSummary.passes` hard-fails on a single unexpected failure. **An
   ordinary timeout could therefore fail an entire gate run.**

   Reproduced deterministically by slowing the disarm, which is what a
   descheduled process looks like to a pending signal — and which explains the
   2-of-6 rate that seemed implausible for a microsecond window: the v3.1
   scheduler oversubscribes ~45 processes onto 52 cores.

2. **A nested `_call_under_budget` silently cancelled the outer budget**, since
   the inner `finally` disarmed unconditionally. Measured: a 0.3 s outer budget
   ran **3.01 s and reported success**. Found while probing defect 1, not
   suspected beforehand. A method could have overrun 1800 s without limit.

3. **An unmeasured time was reported as `0.0`.** Elapsed time is now taken in
   the worker, so even a containment failure reports real child-side time;
   parent-side timing would be wrong because futures are consumed in schedule
   order and would include queueing. A worker that dies without reporting now
   yields a blank, not a zero.

The strict failure classification was deliberately **not** relaxed. Treating a
worker-surfaced `TimeoutError` as expected would have masked defect 1 rather
than fixing it; a method timeout and a containment failure stay distinguishable.

### Review status

External peer review was **unavailable** for the fixes from `3f42332` onward —
the Codex reviewer hit its usage limit mid-round (resets 2026-07-29) and no
second reviewer is configured. The earlier analysis in D1 *was* reviewed, and
that review is what produced the withdrawals recorded above. The fixes were
self-reviewed against an explicit risk list, which is how the residual
`except`-body escape window was found, but that is not equivalent and these
commits should be re-reviewed when the reviewer is available.
