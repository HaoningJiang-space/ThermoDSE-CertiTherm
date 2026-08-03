# Every parameter the nuisance bound assumes is measurable, and all six cases now measure them

RESULT 2026-08-03, `moe-server`. NON-CLAIM: read from the six routed traces already on disk
(`/data/ziheng/certicheck/routed/*` and the V6.1 factorial's `arch_b`/transformer), no new solve.
Supersedes the one-case scope of `KAPPA_IS_MEASURED_AND_THE_SUPPORT_IS_WRONG.md`.
**No external review** — Codex quota-locked to 2026-08-08.

## What the nuisance construction assumes, and what the lowering says

`split_missing_heat.py` bounds the unplaced heat with three assumptions: it lands on the compute die,
its areal density is uniform (`kappa = 1`) or at worst `kappa` times uniform, and the four `eblk*`
frame strips take an area-weighted share. All three are now measured, per case, from a lowering that
reconciles its own energy receipts.

The block families are **pure** — `dram_*` receives only DRAM, `io_*` only NoC, `blockX_*`/`blockY_*`
only NoP — which is what makes a per-family read equal to a per-component read. Verified against
`arch_b`/transformer, where the V6.1 factorial's isolated single-component traces exist: this census
reproduces `13.7042 W`, `3.0750 W` and `8.9349 W` exactly.

## Six cases, duration-weighted mean power, `kappa` = max / mean within each family

| case | blocks | total | core | DRAM | NoC (`io_*`) | NoP (`blockXY_*`) | frame |
| --- | ---: | ---: | --- | --- | --- | --- | --- |
| `arch_a`/resnet50 | 243 | 28.22 W | 10.44 W, 104 live, κ 2.858 | 12.06 W, **4**, **κ 1.000** | 5.72 W, 64, κ 1.937 | **0 W** | **0 W** |
| `arch_a`/transformer | 243 | 40.26 W | 19.56 W, 95, κ 2.426 | 11.78 W, **4**, **κ 1.000** | 8.92 W, 64, κ 1.943 | **0 W** | **0 W** |
| `arch_b`/resnet50 | 233 | 44.79 W | 19.22 W, 100, κ 3.330 | 16.91 W, **4**, **κ 1.000** | 6.77 W, 52, κ 1.702 | 1.90 W, 5, **κ 2.268** | **0 W** |
| `arch_b`/transformer | 233 | 57.18 W | 31.47 W, 87, κ 2.713 | 13.70 W, **4**, **κ 1.000** | 8.93 W, 52, κ 1.896 | 3.08 W, 5, κ 2.140 | **0 W** |
| `arch_c`/resnet50 | 187 | 28.91 W | 12.07 W, 80, κ 3.328 | 11.10 W, **4**, **κ 1.000** | 2.84 W, 32, κ 1.694 | 2.90 W, 8, κ 1.653 | **0 W** |
| `arch_c`/transformer | 187 | 46.06 W | 23.51 W, 74, κ 2.940 | 12.63 W, **4**, **κ 1.000** | 4.61 W, 32, κ 1.690 | 5.30 W, 8, κ 1.659 | **0 W** |

## Four findings, in order of how much they change

**1. The frame carries zero in all six.** `NUISANCE_BOUND_IS_NOT_AN_ESCAPE.md` placed the missing heat
on `eblk0..3`; `THE_GENERATOR_PUTS_THE_MISSING_HEAT_CENTRALLY.md` refuted that by reading the
generator's column order. This is the same conclusion **measured** rather than read, on six cases and
from an independent lowering. The frame placement is thermally empty, and the `frame_fraction` split
in `split_missing_heat.py` — 19-25 % of the missing power — has no support in the physical routing.

**2. DRAM is exactly uniform over exactly four dies, in every case.** `kappa = 1.000` to three
decimals, on 4 blocks, six times. That is the single largest missing component (39-60 % of the total
power here), and its placement is the least uncertain thing in the whole construction. It is also
**off the compute die**, so its heat reaches the die only through the package — which is precisely why
the assumed on-die placement over-estimates.

**3. Every case's measured `kappa` is below its own critical value, and one is barely.**

| case | max nuisance `kappa` (DRAM/NoC/NoP) | `critical_kappa` | margin |
| --- | ---: | ---: | ---: |
| `arch_a`/* | 1.943 | inf | — |
| `arch_b`/resnet50 | 2.268 | 6.960 / 7.163 | comfortable |
| **`arch_b`/transformer** | **2.140** | **2.147 / 2.189** | **0.007, i.e. 0.3 %** |
| `arch_c`/* | 1.694 | inf | — |

So the `kappa` parameterisation is not a hedge — it is falsifiable and it was nearly falsified. The
one case whose certificate the guard-band separator rests on
(`PER_CASE_Q_WITHDRAWS_THE_PLACEMENT_FREE_REFUSAL.md`) survives by 0.3 % in a parameter that had no
measured value at all until today.

**4. `arch_a` emits no NoP heat whatsoever.** 44 `blockXY_*` blocks, all zero, on both workloads.
This is the routed lowering independently confirming the energy ledger's `nop_dict = 0` for that
architecture — two different paths through ThermoDSE agreeing that `arch_a` has no inter-chiplet
interconnect energy. Any construction that assumes a fixed NoP share, as
`central_share_uplift.py` did until this round, is wrong there by construction rather than by degree.

## What this does NOT establish

* **That the routed lowering is physically right.** It has its own modelling freedom —
  `io_die_aspect_ratio` is labelled *"a sensitivity parameter, not a discovered fact"* at
  `routed_trace.py:117`, the same-chiplet NoC split is a fixed 50/50, and the routing is X-then-Y
  deterministic rather than ThermoDSE's own. What is established is that the *lowering's* placement is
  measurable and reconciled, not that it is the truth.
* **That `kappa` transfers.** These are six development points. A design with a hot-spot-heavy DRAM
  access pattern could exceed them, and the certificate's job is to say so.
* **The core `kappa`.** 2.4-3.3 across the six, and it is listed only for scale: the core term is
  *placed*, not a nuisance, so its non-uniformity enters the certificate exactly and needs no bound.
