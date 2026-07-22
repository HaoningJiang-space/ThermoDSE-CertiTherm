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
