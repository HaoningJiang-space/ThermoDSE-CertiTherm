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

## Backend A/B result — thread beats process 4.9x; kernel+thread = 21x end-to-end

Clean checkout 8b09994, arch_c, kernelized first-collision deletion, LP_WORKERS=16,
both to completion, identical U=1091 / cover=143:

| config | wall | note |
|---|---:|---|
| baseline (no kernel, process) | 1238 s | claim-grade reference |
| kernel + process | 290 s | 4.27x (kernel lever) |
| kernel + thread | 59 s | **4.9x thread-on-kernel; 21x combined end-to-end** |

The 52 pool-reaching queries each spawned a fresh ProcessPoolExecutor + re-pickled
the matrices (~230 s total); the ThreadPoolExecutor shares the matrices with no
spawn, so kernel+thread is 4.9x faster than kernel+process and **21x vs the
no-kernel baseline** -- clearing the >=5x goal by a wide margin, with identical
U/cover (sound). HiGHS releases the GIL enough that threads win at ~48 cells.

**Caveats (honest):**
- The thread backend is a MEASUREMENT prototype. Before production it needs the
  review's hardening: ordered-reply/coverage validation, poison-on-failure, the
  SIGALRM lifecycle rules, and a HiGHS-internal-thread oversubscription check.
- 59 s includes the one-time 17 s kernel build.
- Decomposition owed: the thread lever removes per-query pool spawns, which is
  compression-INDEPENDENT, so it should generalise across candidates better than
  the kernel lever. A no-kernel+thread config (the review's config 3) would
  separate the two; the thread backend is currently only in the kernelized sibling,
  not the frozen baseline path.

## Thread-backend review — soundness fixes applied

Peer review (2026-07-24) confirmed the ordered `Executor.map` returns the canonical
first collision, exception propagation to the fallback works, and the 21x arithmetic
is honest as "combined kernel+thread vs no-kernel-process". It said thread soundness
hinges on reentrancy of the concurrent solve, not on ordering. Applied:

- **Reentrancy audit (the crux):** `_solve_collision_spec` only READS `problem.*`
  and builds fresh local arrays (concatenate/vstack/append/.copy()); it never
  mutates shared state and passes arrays to the pure `scipy.linprog`. Documented in
  the thread branch.
- **False-None already prevented:** it returns None ONLY for a proved-infeasible
  status (2) and RAISES on any other status (numerical/iteration/limit) -- so a
  numerical failure degrades to baseline, never a silent SAFE verdict.
- **Read-only shared arrays (defence-in-depth):** the thread branch marks
  objective/common_a_ub/common_b_ub/a_eq/b_eq non-writable so an accidental in-place
  mutation fails loudly. Scoped to the thread path (process workers get pickled
  copies, so shared mutation cannot occur there).
- **Differential test (stronger than U/cover):** thread backend (workers=2) vs the
  sequential ground truth (workers=1) must agree on existence AND the canonical
  colliding spec, for every selection, on a 2-hot-spot instance that exercises the
  pool path. `test_thread_backend_matches_sequential`, 4 selections, green.
- **Claim wording** kept to the review-approved form: "~21x combined kernel+thread
  vs the no-kernel process baseline" -- NOT "threading gives 21x".

### Qualification still owed before a publication claim / full production
- Pin HiGHS to 1 internal thread and benchmark outer×inner (16×1 / 8×2 / 4×4);
  determinism must come from strict status handling + witness validation, not
  byte-identical witnesses.
- Repeated trials with variance; pinned hardware/software.
- Optional decomposition (no-kernel+thread) for clean factorial attribution.
- Keep the thread backend OPT-IN (env-gated) until the above closes.

## Kernel-first MaxHS — the lower-bound step change (DIAGNOSTIC)

arch_c, ~600 s budget each, VERIFY_WORKERS=8, kernel-first verify OFF vs ON:

| config | rounds in budget | L reached | wall |
|---|---:|---:|---:|
| kernel-first OFF | 23 | 896 | 605 s |
| kernel-first ON | **174** | **960** | 622 s (incl. 18 s kernel build) |

**7.6x more rounds in the same budget, and a strictly better bound.** The old D8
run needed 1800 s to reach L=928 on this candidate; kernel-first reaches L=960 in
600 s -- better bound on a 3x smaller budget. This is the lower-bound counterpart to
the 21x deletion result: the verify no longer pays ~681 strong LPs per refuted
round, only ~48.

Combined pipeline implication: L=960 with U=1091 is a **1.136x gap**, reached in
~600 s (MaxHS) + 59 s (kernel+thread deletion) ~= 11 min, versus ~1800 s + 1238 s
~= 51 min before. The 1.2x-gap threshold (L >= 1091/1.2 = 909) is crossed well
before the 600 s mark, so **time-to-1.2x-gap is plausibly under the 10 min gate** --
to be confirmed by a clean run that stops at the gap rather than at a wall budget.

**NOT claim-grade:** this ran on a DIRTY checkout (HEAD 5f18f98 with the two maxhs
files checked out at 2caeb68, dirty=2) and under contention from the concurrent
comprehensive eval. A clean claim-grade re-run at a single pinned commit, with a
stop-at-gap criterion and no competing load, is owed before this becomes a claim.
