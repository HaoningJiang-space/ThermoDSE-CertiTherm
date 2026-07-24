# Deletion tuning — measured (NON-CLAIM)

Host: moe-server, 52 cores, **shared**. Competing load is recorded with each run and is
not negligible (another user's training job plus three multi-day pytest processes, load
average 6.8–9.8 during these runs). Absolute wall times are therefore diagnostic; the
comparisons are between arms measured under the same conditions.

## 1. Worker count — the "unused cores" assumption was wrong

`research/triangle/kernel_sweep.sh resnet50 1`, clean clone at `9bef385`, kernel-first
deletion with the thread backend.

| workers | HiGHS inner | wall | U | cover |
|---:|---:|---:|---:|---:|
| 8 | 1 | (see log) | 1091 | 143 |
| **16** | 1 | **56 s** | 1091 | 143 |
| 32 | 1 | 67 s | 1091 | 143 |
| 48 | 1 | 74 s | 1091 | 143 |
| 32 | 2 | 68 s | 1091 | 143 |

**Adding cores makes it slower.** The standing assumption — that only 16 of 52 cores were
used and a sweep would buy parallel speedup — is false. Once the thermal-frontier kernel
reduces a scan from ~681 to ~48 LPs, 48 workers spend more on scheduling than they recover.
`kernel built in 17s` is itself a third of the 56 s total at the optimum.

Every worker count returns the **identical** cover (143 actions, `U = 1091`, 73.6% of the
1482 full registry), which is the expected invariance: parallelism changes speed, not
answers.

Consequence: **16 workers is the tuned baseline**, and it is the number any new solver has
to beat. There is no parallel headroom left to harvest here.

## 2. Deletion order — the spectrum used to drive, not describe

`CERTITHERM_DELETION_ORDER` (added `9bef385`). `cost` offers actions for removal by cost
alone (expensive first). `spectral` ranks by `cost_i / leverage_i` — dear AND uninformative
first — where leverage is `channel_spectral_leverage`, the channel's coverage of thermally
amplified input-mode energy. That statistic has existed in the repository only as an
interpretability number; this is the first place it drives the algorithm.

Ordering **cannot** affect soundness: every removal is accepted only after an exact
collision test, and the final cover re-verify is always full and exhaustive. It affects
only which inclusion-minimal cover deletion lands on, and how fast.

Single run, `resnet50 c1` (arch_c), 16 workers:

| order | U | cover | oracle queries | full scans (`POOL_REACHED`) | wall |
|---|---:|---:|---:|---:|---:|
| cost | 1091 | 143 | 224 | 52 | 60 s |
| spectral | 1091 | 143 | **199** (−11%) | **25** (−52%) | **46 s** (−23%) |

`U` is unchanged, so on this instance the inclusion-minimal cover is reached either way and
ordering buys speed, not quality. The halving of full scans is the substantive part: a full
scan is the expensive path, and the spectral order reaches a refutation on the kernel more
often.

Channel leverage spans roughly 100x on this candidate (`min 9.87e-04`, `median 4.51e-03`,
`max 9.23e-02`), which is why the ordering has anything to work with.

**Status: one run on a shared host — not yet trustworthy.** A replicated A/B
(`research/triangle/deletion_order_ab.sh`, 4 candidates x 2 orders x 3 reps) is required
before this number is quotable, and is what the accompanying run produces.

## 3. What this does and does not support

Supports: the thermal spectrum carries actionable structure at the channel level, and using
it costs nothing in soundness. This matters more under a transient formulation, where the
REJECT cell set grows from `(model, point)` to `(model, point, time)` and LP-count
reduction moves from an optimisation to a feasibility prerequisite.

Does not support: any claim about `U` quality (unchanged here), any claim about candidates
other than arch_c until the replicated A/B lands, or any general statement about
parallelism on other machines.
