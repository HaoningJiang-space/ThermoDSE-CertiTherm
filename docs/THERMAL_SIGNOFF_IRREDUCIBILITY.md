# Thermal feasibility sign-off does not coarsen

NON-CLAIM diagnostic evidence, 2026-07-29, dev split only. Two independent measurements on
the same instance agree that a zero-error thermal-feasibility certificate needs per-block
resolution, and that the cheap coarse instrumentation cannot substitute for it.

Instance: `transformer` / `default` / `arch_b`, 227 blocks, 3 registered HotSpot models,
243 obtainable actions, library cost 1846. Produced by
`research/triangle/cut_strength_probe.py` and `artifacts/dev/spectral_envelopes.tsv`.

## The measurement library is a hierarchy, and the coarse end is nearly free

| class | actions | unit cost | blocks per action | total cost | share of library cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| `chiplet` | 2 | 2.0 | 112 | 4 | 0.2% |
| `placement_region` | 4 | 4.0 | 57 | 16 | 0.9% |
| `module` | 10 | 1.0 | 20 | 10 | 0.5% |
| `post_route` | 227 | 8.0 | **1** | 1816 | **98.4%** |

A whole-chiplet read covers 112 blocks at a quarter the price of one per-block extraction.
If coarse observation could carry a certificate, it would be almost free to do so.

## It cannot. Measurement 1: what the certified plan actually buys

A greedy cover over 190 discovered separator cuts certifies this candidate at cost 1450:

| class | bought | of available | cost |
| --- | ---: | ---: | ---: |
| `chiplet` | 2 | **100%** | 4 |
| `placement_region` | 4 | **100%** | 16 |
| `module` | 6 | 60% | 6 |
| `post_route` | **178** | **78.4%** | 1424 |

Every chiplet read and every region read is taken -- they are nearly free, so the plan takes
all of them -- and the requirement barely moves: per-block extraction is still needed on four
blocks in five. 98.2% of the plan's cost is per-block work.

## Measurement 2: the operator's energy compresses, its peak does not

From `spectral_envelopes.tsv` for the same instance:

| retained rank | retained operator energy | certified peak tail bound |
| ---: | ---: | ---: |
| 8 | 0.427 | 72.4 K |
| 32 | 0.757 | 66.3 K |
| 64 | 0.909 | 49.9 K |
| 128 | 0.983 | **20.7 K** |
| 227 | 1.000 | 1.9e-13 K |

Discarding 1.7% of the operator energy still admits a 20.7 K worst-case peak error, against a
0.01 K model-error contract and sub-kelvin decision margins.

The reason is not a loose bound. Peak temperature is a worst-case functional over a power
polytope: an adversarial power map may place all of its mass on exactly the modes the
truncation discarded. Diffusion smooths the *response*, not the *adversary*.

## Why the two measurements are not the same observation

They could have disagreed. The first is combinatorial -- which actions a cover needs, given
the discovered confusable pairs. The second is spectral -- how much of the response operator
survives truncation, independent of any action library or any cut. That they agree is the
evidence; either alone would be weaker.

## What this rules out, and what it leaves open

Ruled out on this instance: any claim that coarse thermal instrumentation, spectral
truncation, or a low-rank surrogate can carry a zero-error feasibility certificate at a
materially lower cost. The saving available over extracting everything is bounded by the
structure, not by search quality -- the certified plans buying ~80% of the per-block library
are not obviously an artifact of a weak search, which is what was assumed before measuring.

Left open, and the actual gap: the dev split certified L = 22.8-88.3 against U = 4174, a
47x-183x interval, because the exact synthesizer completed 0 of 3 required candidates inside
its 1800 s budget. The open problem is the WIDTH OF THE CERTIFICATE, not a missed cheap plan.

## Scope

One candidate, one package, one workload, dev split, one greedy cover. The spectral table is
per-candidate and committed for all six dev queries; the composition table is measured on
this instance only. Nothing here is claim-grade and nothing here changes any frozen contract.
