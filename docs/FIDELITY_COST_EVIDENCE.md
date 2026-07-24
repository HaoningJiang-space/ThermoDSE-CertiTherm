# Measured cost of the thermal fidelity ladder

> **CORRECTION (2026-07-25). The operator-build column below is WITHDRAWN.** It was an
> extrapolation `(n+1) x t_solve`, and it is wrong by ~84x. See
> "Withdrawn: the operator-build extrapolation" at the end. The per-solve measurements and
> the ~1968x fidelity span stand; every number derived from the extrapolation — 562x, 4.2x,
> 2.19 h per candidate, ~150 machine-hours at K=20 — does not. The tag
> `v5-fidelity-cost-measured` is left pointing at the original commit deliberately, so the
> error and its correction both remain in the record.

Answers the cheapest of the three go/no-go questions, and it needed no new
infrastructure: **is high-fidelity thermal analysis actually expensive enough that
choosing when to run it is worth anything?**

Until now every cost in `measurement_registry.tsv` was a hand-assigned `1/2/4/8`
(module-class actions are uniformly `1.0` across all 4159 rows), so the premise that cheap
analysis should be preferred over expensive analysis was unquantified — and so was the
"real report cost vs 1/2/4/8" ablation.

## Measurement

`research/triangle/fidelity_cost.py`, moe-server, clean clone at `ae323ea`, candidate
`arch_c` (`resnet50 c1`), **181 floorplan units**, 5 repetitions per model, HotSpot binary
built from the patched export. Inputs are materialised exactly as `experiments.py` does for
the operator build, so this is the cost of the analysis CertiTherm actually runs.

| model | solve median | solve range | ratio | ~~operator build~~ |
| --- | ---: | --- | ---: | ---: |
| `block` | **0.076 s** | 0.075–0.079 | 1.00x | ~~14 s~~ WITHDRAWN |
| `grid64-avg` | 10.263 s | 10.224–10.326 | **135x** | ~~1 868 s~~ WITHDRAWN |
| `grid128-avg` | 32.613 s | 32.533–33.987 | **430x** | ~~5 986 s~~ WITHDRAWN |
| `grid256-avg` | 149.251 s | 149.124–149.589 | **1968x** | ~~27 168 s~~ WITHDRAWN |

Repetition spread is well under 1% (e.g. 149.124–149.589 s), so the shared host's competing
load did not contaminate these numbers.

## What it establishes

**A single thermal solve spans ~1968x across the registered fidelity ladder**, with under
1% repetition spread. That is a large enough span to make selective fidelity activation
worth studying: the question "is high-fidelity thermal analysis expensive enough that
choosing when to run it matters?" is answered yes at the solve level.

That is the whole claim. It is a statement about **solve work**, not about elapsed time in
the production pipeline — see the withdrawal below.

## Withdrawn: the operator-build extrapolation

The first version of this document estimated operator-build cost as `(n+1) x t_solve` —
one full solve per floorplan unit — giving 14 s / 1868 s / 5986 s / 27168 s, and derived
562x, 4.2x, 2.19 h per candidate and ~150 machine-hours at K=20 from it. **All of those are
withdrawn.**

`docs/GPU_HOTSPOT_EVIDENCE.md` already contains *measured* CPU operator times on a
227-block candidate:

| grid | measured CPU operator | this doc's extrapolation | error |
| --- | ---: | ---: | ---: |
| 64x64 | **22.2157 s** | 1 868 s | **84.1x** |
| 128x128 | **71.7407 s** | 5 986 s | **83.4x** |

The two errors agree to within 1%, so this is systematic, not a candidate difference. The
cause is that the cost model was structurally wrong: `22.2157 s / 10.263 s ~= 2.2` solves'
worth of time completed 228 impulses, so grid operator construction is **not** one full
solve per block. The RC matrix assembly and factorisation happen once and are reused across
right-hand sides, and `build_operator` additionally runs a `ThreadPoolExecutor` over units.
Per-solve cost therefore cannot be multiplied by unit count.

Worse for the withdrawn numbers: the frozen v3 configuration sets
`CERTITHERM_GPU_HOTSPOT=1`, so `grid64`/`grid128` operators are built on the **GPU**
(0.8412 s and 3.0795 s measured), with CPU HotSpot used for `block`, calibration and
replay. The elapsed cost of the production path is thus another order of magnitude away
again from the withdrawn CPU-serial figure.

## Two different cost axes — do not substitute one for the other

The first version said the "real report cost" ablation should use numbers like these. That
was wrong. They are different objects:

| axis | what it is | what was measured |
| --- | --- | --- |
| `C_report(a \| f)` | **observation acquisition** — module / chiplet / placement-region / post-route report | the frozen, uncalibrated `1/2/4/8` |
| `C_model(f)` | **fidelity activation** — standing up and calibrating a thermal model | this document (solve level only) |

So this measurement shows the `1/2/4/8` weights are uncalibrated, but it **cannot replace
them**. The correct object is two-layer,

    C(S, F) = sum_{f in F} C_model(f) + sum_{a in S} C_report(a | f)

where model cost is a one-off amortised across queries and workloads while report cost is
incremental. This makes the method richer rather than poorer: the decision is a joint
choice of analysis fidelity *and* observation refinement, not a reweighting of actions.

## What it does NOT establish

- Nothing about analyses further up the proposed ladder — placed transient power,
  fine RC/DSS transient, FEM/3D-ICE signoff — none of which are implemented here.
- Nothing about licence, queue, or engineer time in a real EDA flow; this is wall time of
  one open-source solver on one machine.
- Nothing about how *often* the coarse model suffices. A large ratio makes the question
  worth asking; it does not answer it. That is what the reachable-set and decision-margin
  work has to establish.
- One candidate, one package, one floorplan size (181 units). Grid solve cost is expected
  to scale with grid size rather than unit count, so the ratio should be stable across
  candidates, but that is an expectation, not a measurement.

## The safe wording

> On one 181-unit physical candidate, CPU HotSpot solve time rises from 0.076 s for the
> block model to 149.251 s for `grid256`, a 1968x span with under 1% repetition spread.
> This establishes substantial potential value for selective fidelity activation.
> End-to-end savings under the parallel, GPU-assisted production pipeline remain to be
> measured.

Do **not** write: "up to 562x end-to-end", "always-full costs 2.19 h per candidate",
"K=20 needs ~150 hours", or "the 1/2/4/8 action costs have been calibrated".

## Gates

| gate | state |
| --- | --- |
| is there a large compute span across thermal fidelities? | **closed, positive** |
| is multi-fidelity worth proposing at all? | **closed, positive** |
| what does the *production* path actually cost end to end? | open |
| how often is the coarse model already sufficient? | open — **now the decisive question** |
| are the `1/2/4/8` report costs real? | open |
| cost of transient / FEM / signoff analyses further up the ladder | open |

## Next measurement (supersedes the extrapolation)

Instrument `build_family()` itself rather than extrapolating a solve, on **at least three
candidates with different block counts**, reporting elapsed wall time, CPU core-seconds and
GPU-seconds separately for each of:

| path | must report |
| --- | --- |
| serial CPU | elapsed, CPU-seconds |
| production CPU parallel | cold-cache elapsed, worker count, CPU-seconds |
| frozen GPU + CPU calibration | export, GPU solve, CPU replay, I/O, total elapsed |
| warm-cache reuse | marginal query cost and the amortisation point |

covering zero/impulse construction, calibration vectors, independent CPU replays and
artifact serialisation, with cold and warm cache kept separate. Only then is
`real full-family cost / real block-only cost` answerable.

Reproduce the (solve-level only) measurement here:

    python research/triangle/fidelity_cost.py artifacts/diag150b resnet50 1 5
