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

Single run, `resnet50 c1` (arch_c), 16 workers:

| order | U | cover | oracle queries | full scans (`POOL_REACHED`) | wall |
|---|---:|---:|---:|---:|---:|
| cost | 1091 | 143 | 224 | 52 | 60 s |
| spectral | 1091 | 143 | **199** (−11%) | **25** (−52%) | **46 s** (−23%) |

`U` is unchanged — but **the covers are NOT the same set**. Comparing the manifest
`cover_action_ids` directly on `resnet50 c1`: both orders return 143 actions at `U = 1091`,
yet **8 actions differ in each direction** (`cost` keeps `module::mtxu`,
`post_route::ibuf_12`, `post_route::io_0_0`...; `spectral` keeps `module::vecu`,
`post_route::ibuf_15`, `post_route::io_3_13`...).

So the earlier reading — "the inclusion-minimal cover is unique, ordering only buys speed" —
was wrong. The correct statement:

> Cost-first and spectral-first deletion reach two distinct inclusion-minimal FEASIBLE
> covers with identical surrogate cost `U = 1091` and cardinality 143, differing by eight
> actions in each direction. This demonstrates order sensitivity and degeneracy among
> feasible upper-bound endpoints under the current `1/2/4/8` cost lattice. It does **not**
> establish multiplicity of globally optimal covers.

**A stronger claim was made and is withdrawn.** An earlier version called this "direct
evidence that the optimal cost face is degenerate" and tied it to the MaxHS plateau at
`L = 1256`. That is wrong twice over: `upper_bound.py` produces an inclusion-minimal cover,
not a minimum-cost one, and `U = 1091` on `arch_c` is an unclosed interval endpoint with no
optimality proof; while `L = 1256` is a plateau on a DIFFERENT candidate (`arch_b`). Joining
them mixes evidence across instances.

What the finding is actually worth:

1. deletion ordering changes the SEMANTIC composition of the contract while leaving the
   hand-assigned scalar cost untouched;
2. the current `1/2/4/8` lattice cannot distinguish these different contracts at all;
3. under measured acquisition cost, noise, or reuse cost, the equal-cost relation may well
   dissolve — in which case one of the two covers is genuinely cheaper.

The next results table must therefore report Jaccard/Hamming distance between the two
covers, their composition by action class and fidelity, and the cost difference recomputed
under a MEASURED cost vector rather than the frozen lattice.

The substantive speed evidence is the DETERMINISTIC counters, not wall time: oracle queries
and `POOL_REACHED` are exact counts unaffected by host load, and they drop consistently
(224->199, 276->257, 283->259; 52->25, 64->39, 55->39). Wall time on a host at load 6.8-9.8
is the weaker signal and should not lead.

Channel leverage spans roughly 100x on this candidate (`min 9.87e-04`, `median 4.51e-03`,
`max 9.23e-02`), which is why the ordering has anything to work with.

**Status: not yet quotable.** Two defects in the current A/B design:

1. **Not counterbalanced.** The script runs all `cost` candidates and then all `spectral`
   candidates within each repetition, so `spectral` is always later in wall-clock time and
   is confounded with drifting host load, thermal state and cache warmth. Order must
   alternate (AB/BA) per candidate and repetition.
2. **One repetition so far**, no confidence intervals, no per-run resource telemetry.

The deterministic query/scan counts are far more robust to both defects than the wall-time
deltas, and are what should carry the claim if they persist across repetitions.

## 3. What this does and does not support

Supports: the thermal spectrum carries actionable structure at the channel level, and using
it costs nothing in soundness. This matters more under a transient formulation, where the
REJECT cell set grows from `(model, point)` to `(model, point, time)` and LP-count
reduction moves from an optimisation to a feasibility prerequisite.

Does not support: any claim about `U` quality (unchanged, though the cover CHANGES); any
claim about candidates other than arch_c until the counterbalanced replicated A/B lands; any
general statement about parallelism on other machines or other candidates; and no wall-time
speedup figure at all until the A/B is counterbalanced and repeated.
