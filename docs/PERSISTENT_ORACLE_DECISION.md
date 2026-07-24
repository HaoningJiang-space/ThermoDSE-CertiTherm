# Persistent oracle (item 2) — review disposition and measurement gate

The `CollisionOracleSession` design was peer-reviewed (2026-07-24). Verdict: **worth
prototyping, but do NOT commit to persistent processes until measured.** Recorded
here so item 2 is a measurement-gated prototype, not an assumed win.

## The make-or-break number: N (pool-using queries per run)

Each collision query first runs a local first-cell probe; only a NEGATIVE probe
reaches the pool. Persistence amortises the per-call pool-spawn `B` only over the
queries that actually reach the pool. Break-even (spawn `B`, per-query protocol
overhead `D`, teardown `E`):

    persistent session wins  iff  (N - 1)·B > N·D + E

where **N excludes every query resolved by the first-cell probe**. If `N ≤ 1`,
persistence is not worthwhile. So the FIRST step is to instrument a real deletion
run and count: probe-resolved vs pool-reaching queries. Only if `N ≫ 1` is a
persistent pool (or thread pool) worth building.

## Threaded alternative is a serious contender

If HiGHS releases the GIL and concurrent solves are thread-safe, a THREAD pool
shares all matrices with no spawn/pickle/process-dispatch — likely beating a
persistent process pool at ~48 cells. Must constrain solver-internal threading to
avoid oversubscription without changing the frozen solver contract. Threads still
cannot hard-cancel a native solve under SIGALRM, but they avoid the spawn deadlock.

## If built: required shape (review)

- Session-scoped (per candidate run), NOT a process-global registry. Owns an
  immutable snapshot of polytope + thermal + **actions** (currently missing) + margin
  + tolerance; records creating PID/thread; rejects use after fork/close/poison/
  concurrent caller.
- Coarse ORDERED cell chunks (~workers to 2–4×workers), not 48 tiny (selected,spec)
  tasks; each task assembles `common_a_ub` once and solves its chunk.
- Preserve the local first-cell probe (many calls avoid the pool entirely).
- Byte-identical verdicts: do not sort/dedupe `selected`; model-major/point-minor
  spec order; never select a witness by completion order; ordered replies
  `(query_id,start,count,results)` with FULL coverage validation before filtering
  None; any protocol failure → poison session, discard partials, rerun the COMPLETE
  frozen `_collision_search` (not the suffix); in tests, protocol mismatch is fatal.
- Three separate index spaces (action IDs / SAFE-row IDs / reject-spec IDs), each
  bounds/order/dupe-validated; returned collisions carry GLOBAL model/spec identity;
  `collisions()` always full SAFE + full specs; kernel subsetting stays
  non-exhaustive-only.
- SIGALRM: refuse construction under an armed `ITIMER_REAL`; warm the pool before
  the anytime alarm region; a timeout poisons the session and does NOT auto-rerun an
  expensive baseline after the deadline; fallback under an armed alarm uses frozen
  `_collision_search(..., workers=1)`.

## Claim-grade A/B to prove ≥5× (before any production commit)

To reach 5× the kernel+session must cut the kernel-only end-to-end by ≥15%
(`T_kernel = T_base/4.25`, need `T_kernel+session ≤ 0.85·T_kernel`). Paired,
randomized-order, same recorded query trace, session build+teardown INCLUDED:
1 frozen baseline · 2 kernel only · 3 session only · 4 kernel+process-session ·
5 kernel+thread-pool · 6 kernel workers=1. Record: pool spawns, probe-resolved vs
pool-reaching counts, tasks/cells per query, build/warm/teardown/total wall,
fallbacks/timeouts, an ordered collision-result digest, final U + cover.

**Do not commit persistent processes** unless the trace confirms `N ≥ 2` pool-using
queries/run AND the paired end-to-end clears 5× with identical output digests.

## Immediate next step

Instrument the deletion run to count N (probe-resolved vs pool-reaching), for both
the baseline and the kernelized path, on arch_c. That single cheap measurement
decides whether item 2 is a process pool, a thread pool, or not worth it — before
any oracle code is written.

## Gate result — N measured (arch_c, commit b461248)

Kernelized deletion run, LP_WORKERS=16:

    kernelized queries = 224
    probe_resolved     = 172   (resolved at the first-cell probe, no pool)
    POOL_REACHED (N)   = 52    (pool-using queries -- each a fresh spawn today)
    sequential         = 0

**N = 52 ≥ 2 → gate PASSED.** 77% of deletion tests resolve at the probe, but 52
reach the pool, so today's run pays ~52 fresh ProcessPoolExecutor spawns + matrix
re-pickles. Amortising those into ONE persistent/threaded pool is worth prototyping.

Next: prototype the THREADED backend first (review's preferred candidate at ~48
cells: shares matrices, no spawn/pickle), then paired A/B (baseline / kernel-only /
kernel+threads / kernel+persistent-process / kernel workers=1) on a clean checkout,
verifying identical U/cover/digests, targeting a ≥15% cut of the kernel-only time
(4.25× → ≥5×). Only commit a production backend if the A/B clears it.
