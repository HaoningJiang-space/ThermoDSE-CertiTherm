# Pushing the method to its limit: the certificate is 0.17 %, so optimise the operator or nothing

METHOD 2026-08-05, from measurements already in this repository. **No external review** — Codex
quota-locked to 2026-08-08.

## The cost split decides the question, and it is measured end to end

From two independent certificate-constrained searches (`CERTIFIED_SEARCH_RESULT.md`):

| | `arch_b` run | `arch_a`/resnet50 run |
| --- | ---: | ---: |
| operator builds | **1 526 s (91.8 %)** | **10 100 s (99.5 %)** |
| ThermoDSE evaluations | 134 s | 190 s |
| **the certificate itself** | **2.786 s (0.17 %)** | **4.982 s (0.049 %)** |

**Optimising the certificate optimises 0.17 % of the run.** Leg 1's 12 ms per candidate is already
past the point of mattering. The only lever that changes anything is the operator, and everything
below is about it.

## What has already been taken

**Process-level parallelism: 15.0×, bit-identical.** `cell_operator` issued N independent HotSpot
subprocesses from a Python `for` loop — one core of fifty-two. At 16 workers the 233-block operator
went `1 333 s → 89 s` with `max|Δ| = 0.000e+00` on every entry
(`THE_IMPULSE_LOOP_IS_PARALLEL.md`). That is the whole of the easy factor: the loop is now bounded by
cores, and the host has 52.

**The library: exact reuse, and its hit rate is a property of the population, not of the cache.**
0 % within an architecture search — **zero of ten design fields leaves the floorplan invariant** — and
100 % on a re-analysis of designs already evaluated (the span sweep, 12/12). No caching strategy
changes the first number; it is a fact about the design vector.

## Where the remaining factor is, and the measurement that says so

HotSpot solves N **independent** problems: cost `O(N)` in solver invocations. The FEM reference does
**one** assembly, **one** cuDSS factorisation, and N right-hand sides — and
`FEM_COST_IS_NOT_ON_THE_GPU.md` measured where its time goes: **the GPU solve is 0.2 %**, against
35 % mesh construction, 30 % per-problem postprocess, 21 % RHS assembly. The factorisation, the part
that would scale with N in a naive solver, is **2 %** and is paid once.

So the two cost curves have different shapes:

| | HotSpot impulse loop | GPU-batched FEM |
| --- | --- | --- |
| per extra block | one more full solve | one more RHS — 0.2 % of the run is *all* the solves |
| dominant cost | N solves | mesh + postprocess |

Measured, and this is every point I have:

| blocks | HotSpot | FEM (`CELL_ENDPOINT=128`) |
| ---: | ---: | ---: |
| 187 | 113 s @ 10 workers | — |
| 181 | — | **108, 142, 144 s** (three cases) |
| 233 | **140 s** @ 10 workers, 89 s @ 16, **1 333 s serial** | — |
| 243 | 424 s @ 8 workers | — |

**The crossover claim I first wrote here is withdrawn, because these points cannot support it.** All
three FEM runs are at **181 blocks** — I have no second block count for the FEM, so its slope in `N`
is **unmeasured**, and "above a few hundred blocks the FEM wins" was an extrapolation from a curve
with one point on it. This project has a standing rule against exactly that, quoted three sections
below in the very list of what to build, and I broke it in the paragraph above.

What the points *do* support: at ~200 blocks the two are **the same order** (113–140 s against
108–144 s), and HotSpot's spread across architectures at fixed worker count (113 s at 187 blocks,
424 s at 243) is larger than the gap between the methods — so per-solve cost varies more with the
floorplan than with the block count, and even HotSpot's own slope in `N` is not clean.

## The soundness condition, and it is the reason this is proposable at all

Swapping the operator inside the search changes the object being searched, which is exactly what
`CLAUDE.md` forbids doing casually — the endpoint must stay HotSpot's or the number is not comparable
with `CELL_ENDPOINT_RESULT.md`. The escape is a **two-tier** scheme, not a substitution:

* **search** on the FEM operator, which is cheap and whose disagreement with HotSpot on the certified
  quantity is **measured at `≤ 0.071 K`** across three cases (`E_TOTAL_AT_THE_CELL_ENDPOINT.md`);
* **certify** the survivors on the pinned HotSpot operator, which is the declared model
  (`A_VERDICT_IS_RELATIVE_TO_A_DECLARED_MODEL.md`).

This is sound **if the search's feasible set contains the certifier's**, i.e. if the search never
discards a design HotSpot would certify. That requires a bound on the gap in the *permissive*
direction, and the tight one-maximum form gives it: `0.75–1.82 K` on the legacy captures. Widening
the search's ceiling by that band makes the tier sound at the cost of admitting designs that later
fail — which is the right direction, because a search that over-admits wastes operator builds while
one that under-admits **loses the answer**.

> **The `0.071 K` figure must not be used here.** It is a measurement on three designs, not a bound
> (`model_relative_verdict.CrossModelGap` refuses to let it be transferred). The `1.82 K` tight bound
> is what the tier may rely on.

## What the ceiling then is

With the operator on the GPU and the certificate free, a search's cost becomes **one ThermoDSE
evaluation per candidate — 7 s** — plus one FEM operator per distinct geometry. And zero of ten design
fields is geometry-invariant, so distinct geometries equal candidates: **the floor is ThermoDSE
itself.**

That is the honest end of this road. Past it the lever is no longer thermal:

* **the mapping level is already there.** `R` is fixed under a permutation, so a mapping candidate
  costs 0.79–2.9 ms and needs no ThermoDSE call at all
  (`CERTIFIED_MAPPING_AND_THE_UNIFICATION.md`). The architecture level pays 7 s per candidate; the
  mapping level pays a millisecond. **Any performance argument for this method should be made at the
  level where it is three orders of magnitude, not the one where it is 15 ×.**
* **and the mapping level's own ceiling is known**: ThermoDSE's geometric heuristic is within
  `0.08–0.25 K` of the exact optimum on five of six designs. There is no factor left there either —
  only on the one design that fails, where it is `1.65 K` away.

## What to build, in order

1. **Measure the FEM's slope in `N`.** Every FEM cell operator built so far is at 181 blocks, so its
   cost curve has one point and no crossover can be claimed. Two more block counts settle it, and
   until they exist the two methods are only known to be the same order at ~200 blocks.
2. **A two-tier search behind the soundness condition above**, with the search ceiling widened by the
   tight bound and every survivor re-certified on HotSpot. Report how many survivors fail, because
   that count *is* the tier's cost.
3. **Nothing further on the certificate.** 0.17 %.
