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

**On this candidate, under these conditions, 16 workers beat 32 and 48.** The standing
assumption — that a sweep would obviously buy parallel speedup — is not supported here.
This is NOT a claim that 16 is optimal or that no parallel headroom exists: the sweep is one
candidate, one run per point, no repetitions or error bars, on a loaded shared host, and it
never tested 4/12/20/24. The 8-worker point was also lost to output filtering. Kernel
compression varies strongly by candidate (16.4x / 2.43x / 1.51x / 1.16x measured
previously), so a candidate whose scan stays near ~580 LPs could well use more workers.

A plausible mechanism, untested: once the thermal-frontier kernel reduces a scan from ~681
to ~48 LPs, high worker counts may spend more on scheduling than they recover. `kernel built
in 17s` is a third of the 56 s total at the best point, which is an Amdahl limit for an
instance this small but not necessarily for longer deletion workloads.

Every worker count returns the **identical** cover (143 actions, `U = 1091`, 73.6% of the
1482 full registry). That shows determinism under parallelism; it says nothing about which
worker count is best.

Consequence: **16 workers is the tuned baseline for this candidate**, and it is the number
a new solver has to beat here. Whether parallel headroom remains on low-compression
candidates is untested.

## 2. Deletion order — the spectrum used to drive, not describe

`CERTITHERM_DELETION_ORDER` (added `9bef385`). `cost` offers actions for removal by cost
alone (expensive first). `spectral` ranks by `cost_i / leverage_i` — dear AND uninformative
first — where leverage is `channel_spectral_leverage`, the channel's coverage of thermally
amplified input-mode energy. That statistic has existed in the repository only as an
interpretability number; this is the first place it drives the algorithm.

Ordering **cannot** affect soundness: every removal is accepted only after an exact
collision test, and the final cover re-verify is always full and exhaustive. It affects
only which inclusion-minimal cover deletion lands on, and how fast.

Counterbalanced paired A/B, run `ab-1fce5e2-20260724T182649Z`, 16 arms (2 repetitions x 4
candidates x 2 orders), 16 workers, budget scoped to the deletion sweep, every arm's
manifest validated for `completed_sweep`. Each candidate got one cost-first and one
spectral-first pair, so slot position is balanced within every candidate.

### PRIMARY — deterministic counters (identical across repetitions, 4/4 candidates)

| candidate | queries cost -> spectral | full scans cost -> spectral | U | cover |
|---|---:|---:|---:|---:|
| resnet50 c0 | 276 -> 257 (**-19**) | 53 -> 38 (**-15**) | 1383 both | 179 both |
| resnet50 c1 | 224 -> 199 (**-25**) | 52 -> 25 (**-27**) | 1091 both | 143 both |
| resnet50 c2 | 283 -> 259 (**-24**) | 55 -> 39 (**-16**) | 1457 both | 188 both |
| transformer c0 | 276 -> 257 (**-19**) | 64 -> 39 (**-25**) | 1383 both | 179 both |

Every counter is bit-identical between repetition 1 and repetition 2, for both orders, on
all four candidates. Spectral ordering reduces oracle queries on 4/4 and full scans on 4/4.
The largest full-scan reduction is on `resnet50 c1` (-52%); the largest on the hardest
candidate, `transformer c0`, is -39%.

### SECONDARY — paired CPU-seconds (not a significance claim at n=2)

Per-process user+system CPU-seconds, which unlike wall time distinguish "did less work"
from "waited less for CPU":

| candidate | cost/spectral ratio (median) | range |
|---|---:|---|
| resnet50 c0 | 1.146 | 1.116 – 1.175 |
| resnet50 c1 | 1.402 | 1.365 – 1.438 |
| resnet50 c2 | 1.177 | 1.170 – 1.185 |
| transformer c0 | 1.222 | 1.214 – 1.230 |

Spectral consumed less CPU on 4/4 candidates in both slot positions. No p-value or
confidence interval is computed: two pairs per candidate cannot support one.

### Equal cost, different cover — on 4/4 candidates, and the difference is INTRA-CLASS

| candidate | U | cover size | Hamming | Jaccard |
|---|---:|---:|---:|---:|
| resnet50 c0 | 1383 | 179 | 20 | 0.8942 |
| resnet50 c1 | 1091 | 143 | 16 | 0.8940 |
| resnet50 c2 | 1457 | 188 | 18 | 0.9086 |
| transformer c0 | 1383 | 179 | 20 | 0.8942 |

Composition by action class is **identical** in every case — same number of `module`,
`chiplet`, `placement_region` and `post_route` actions in both covers. The entire
difference is *which* `post_route` actions are kept.

That sharpens the earlier statement. The degeneracy lives strictly **inside one action
class**, and the `1/2/4/8` lattice assigns one cost per class, so it cannot possibly
distinguish these covers. It also makes a testable prediction: replacing the lattice with a
measured cost vector will dissolve the tie **only if post-route report cost varies within
the class** (with region size, block count, or which blocks are involved). If every
post-route report really does cost the same, the tie is structural, not an artefact of
quantisation.

## 3. What this does and does not support

Supports: the thermal spectrum carries actionable structure at the channel level, and using
it costs nothing in soundness. This matters more under a transient formulation, where the
REJECT cell set grows from `(model, point)` to `(model, point, time)` and LP-count
reduction moves from an optimisation to a feasibility prerequisite.

Does not support: any claim about `U` quality -- it is unchanged on all four candidates,
though the cover changes; any inferential timing claim, since n=2 pairs per candidate; any
statement about candidates outside this dev registry or about other machines; and nothing
about whether the spectral ordering would still help once the cost lattice is replaced by
measured costs, which could change which actions are offered first.

One rep-3 arm was in flight when the run was stopped at the approved 16-arm point. It has no
manifest and is excluded; it is an incomplete arm, not a truncated result.
