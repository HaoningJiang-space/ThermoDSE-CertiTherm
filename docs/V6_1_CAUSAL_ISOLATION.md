# V6.1 source-subset isolation under a fixed additive power trace

Recomputed from the manifest's raw observations by `research/triangle/v61_validate.py`: the subset enumeration; every row's peak, argmax, runner-up and resolution-aware tie set, from the per-block temperature vectors; the classification, crossing coalitions and leave-one-out table; convergence; the energy ledger; cross-row provenance; and the gate, against the pinned registration `docs/registration/v61_grid64_counterexample.json` rather than the manifest's own copy of its verdicts. Any disagreement is a refusal. **Producer-attested, and not re-derivable here:** the temperatures themselves, the superposition residual, and the execution receipts — hashes without retained bytes cannot be re-verified.

## Provenance

- commit `56e77c28326f`, working tree CLEAN at start and end (`provenance_stable = True`)
- candidate `transformer` / `arch_b`, model `grid64-max`, requested step 0.5 us, ambient 318.15 K, limit 330.0 K, 233 floorplan blocks
- host `hpclab03`, Linux-5.15.0-71-generic-x86_64-with-glibc2.29, Python 3.8.10, NumPy 1.24.4, manifest schema 4, gate policy 2
- run `56e77c28-grid64-max-0.5us-1785061755`, wall 66.2 min
- registration `v61-grid64-max-transient-counterexample`, file unchanged since the run: `True`
- every input staged read-only, hashed as read, re-verified after each replay:
  - `config` `b5956b0d44880986…`
  - `floorplan` `97fd0c067b9d7b3a…`
  - `hotspot` `b0040b3ecb82897e…`
  - `materials` `d958a3263b196659…`
- superposition identity, subset == sum of singletons: worst `0.000e+00` W (producer-attested)

**This run is not an independent numerical confirmation of the registered numbers, and nothing here should be read as one.** The staged HotSpot binary is byte-identical to the one used by the earlier transient work (`docs/GPU_HOTSPOT_EVIDENCE.md:86`). With the same binary, inputs, code and platform, agreement to the last printed digit — including the `1.245e-07` K steady residual against a value quoted to six decimals — is what arithmetic requires. It evidences a reproducible build and an intact provenance chain; it evidences nothing about the physics and nothing about whether a solver ran.

### Execution receipts (producer-attested, not proof of execution)

Each row records that its directory and HotSpot workspace did not exist beforehand, its PID, a wall window inside the run's, this run's nonce, and **one record per HotSpot process** — role, argv, return code, wall window, and the output it wrote with that file's SHA-256 and byte size. Across 15 rows: **54 invocations** writing **54 output files** totalling 369.5 MB, plus 54 driver-written `.ptrace` inputs, all hashed.

Validated: the recorded role sequence is `mean-steady`, `fixed-initial`, then a doubling series of `periodic-N` whose last N equals the row's converged cycle count; every return code is 0; no two invocations claim the same output; every recorded output hash matches the workspace hash for that filename; and no invocation claims a `.ptrace` input as its own output. So an **inconsistent** producer is caught. A **dishonest** one is not: these fields are self-attested, the raw bytes are not archived in this repository, and nothing re-hashes them at render time. That is why this section is not called proof.

| subset | invocations | outputs | output MB | wall (s) | cycles |
| --- | ---: | ---: | ---: | ---: | ---: |
| `core` | 3 | 3 | 11.9 | 137.7 | 8 |
| `noc` | 3 | 3 | 11.9 | 130.7 | 8 |
| `nop` | 3 | 3 | 11.9 | 122.0 | 8 |
| `dram` | 4 | 4 | 33.1 | 348.5 | 16 |
| `core-noc` | 3 | 3 | 11.9 | 131.0 | 8 |
| `core-nop` | 3 | 3 | 11.9 | 137.4 | 8 |
| `core-dram` | 4 | 4 | 33.1 | 365.1 | 16 |
| `noc-nop` | 3 | 3 | 11.9 | 131.8 | 8 |
| `dram-noc` | 4 | 4 | 33.1 | 341.7 | 16 |
| `dram-nop` | 4 | 4 | 33.1 | 346.2 | 16 |
| `core-noc-nop` | 4 | 4 | 33.1 | 347.1 | 16 |
| `core-dram-noc` | 4 | 4 | 33.1 | 355.0 | 16 |
| `core-dram-nop` | 4 | 4 | 33.1 | 363.3 | 16 |
| `dram-noc-nop` | 4 | 4 | 33.1 | 343.2 | 16 |
| `full` | 4 | 4 | 33.1 | 353.8 | 16 |

## Source energy ledger

Reproduced exactly by all 15 rows: each row's retained energy equals the sum of its components' entries here, to 1e-15 J.

| source | energy (mJ) | share |
| --- | ---: | ---: |
| `core` | 12.747382 | 55.033% |
| `dram` | 5.550965 | 23.965% |
| `noc` | 3.619128 | 15.625% |
| `nop` | 1.245560 | 5.377% |
| **total** | **23.163035** | 100% |

## All 15 non-empty source subsets

| subset | time-mean steady (K) | periodic (K) | uplift (K) | steady argmax | periodic argmax | tied | cycles | status |
| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | --- |
| `nop` | 320.326022 | 320.42 | +0.09 | `blockX_1` | `blockX_1` | 1 | 8 | below |
| `noc` | 320.854258 | 320.99 | +0.14 | `ubuf_0` | `ubuf_0` | 4 | 8 | below |
| `noc-nop` | 321.676057 | 321.79 | +0.11 | `blockX_1` | `blockX_1` | 1 | 8 | below |
| `dram` | 322.857876 | 322.95 | +0.09 | `dram_x0_y4` | `dram_x0_y0` | 4 | 16 | below |
| `dram-nop` | 323.233830 | 323.33 | +0.10 | `dram_x0_y0` | `dram_x0_y0` | 2 | 16 | below |
| `dram-noc` | 323.965729 | 324.08 | +0.11 | `dram_x0_y0` | `dram_x0_y0` | 1 | 16 | below |
| `dram-noc-nop` | 324.341685 | 324.47 | +0.13 | `dram_x0_y0` | `dram_x0_y0` | 1 | 16 | below |
| `core` | 326.268802 | 326.54 | +0.27 | `mtxu_16` | `mtxu_16` | 2 | 8 | below |
| `core-nop` | 326.768648 | 326.95 | +0.18 | `ubuf_13` | `ubuf_13` | 4 | 8 | below |
| `core-noc` | 327.799962 | 328.12 | +0.32 | `mtxu_16` | `mtxu_16` | 2 | 8 | below |
| `core-dram` | 327.975129 | 328.20 | +0.22 | `mtxu_16` | `mtxu_16` | 2 | 16 | below |
| `core-noc-nop` | 328.198340 | 328.51 | +0.31 | `mtxu_16` | `mtxu_16` | 2 | 16 | below |
| `core-dram-nop` | 328.412897 | 328.61 | +0.20 | `ubuf_13` | `mtxu_16` | 2 | 16 | below |
| `core-dram-noc` | 329.506452 | 329.78 | +0.27 | `mtxu_16` | `mtxu_16` | 2 | 16 | below |
| **full** | 329.904867 | 330.19 | +0.29 | `mtxu_16` | `mtxu_16` | 2 | 16 | **CROSSING** |

HotSpot reports transient temperature to 0.01 K, so with a 330.0 K limit a row is `crossing` iff `periodic >= 330.01` K, `below` iff `periodic <= 329.99` K, and `indeterminate` otherwise — exactly 330.0 K is **not** a crossing. Indeterminate rows: none. Every row converged to within its 0.01 K tolerance, which equals the output quantum: convergence is at the observability floor, not below it. The `tied` column is the number of blocks within one quantum of that row's peak — see the appendix.

## Gate

Recomputed against `docs/registration/v61_grid64_counterexample.json` (`v61-grid64-max-transient-counterexample`, gate policy 2), whose registered tuple the manifest must match exactly:

- decision — steady < 330.0 K **and** the full row classifies as `crossing` under the same quantisation rule as every other row: **True**
- periodic value within one 0.01 K quantum of the registered 330.19 K: **True**
- location — the registered `mtxu_16` sits at 330.19 K against a peak of 330.19 K, i.e. within one quantum of the maximum: **True**
- steady delta from the registered value: `1.245e-07` K (reported, **not** gated — no repeatability-derived tolerance exists)

**The location check is a compatibility test, not spatial reproduction.** It asserts only that the registered block cannot be distinguished from the maximum at HotSpot's output resolution. Gate policy 1 required exact argmax equality, which depended on how an exact tie was broken: 11 of 15 rows here have a tied argmax, and refactoring the argmax from a flat maximum over (sample, block) to a per-block maximum flipped one row's reported label with every temperature unchanged. Exact equality still holds this run (`argmax_equals = True`) but is reported, not gated. The predicate is computed from the registered block's own temperature, not from a producer-reported tie list — such a list could name any block, since nothing in it is tied to a temperature.

**The gate binds names and temperatures, NOT the registered instance** (`binds_instance_hashes = False`, `canonical_trace_sha256 = None`). It does not verify that the registry, power trace or routing are unchanged, so a changed registry under the same workload/architecture names would still pass. Closing that needs a canonical trace hash preregistered from a run that is itself claim-grade. Open gap.

## Result

The 15 rows exhaust every non-empty subset of {`core`, `dram`, `noc`, `nop`} with no indeterminate row, and exactly one of them crosses: **`core+dram+noc+nop`** is the unique minimal crossing coalition in this factorial. That is a statement about this trace, this candidate and this discretisation — not about candidates, traces or discretisations in general.

### Leave-one-out is an arithmetic consequence, not a second finding

The full set crosses by only **+0.19 K** (330.19 K against a 330.0 K limit). Every removal costs at least a full 0.01 K quantum more than that excess (smallest: +0.41 K for `nop`), so once the exhaustive factorial shows the full set is the only crossing subset, all 4 leave-one-out verdicts follow with no further information. This is **Boolean threshold necessity within a fixed factorial**, not a measure of physical causal importance.

| removed source | periodic (K) | removal delta (K) | delta / excess | margin to limit (K) | status |
| --- | ---: | ---: | ---: | ---: | --- |
| `core` | 324.47 | +5.72 | 30.1x | +5.53 | below → necessary in the grand coalition |
| `dram` | 328.51 | +1.68 | 8.8x | +1.49 | below → necessary in the grand coalition |
| `noc` | 328.61 | +1.58 | 8.3x | +1.39 | below → necessary in the grand coalition |
| `nop` | 329.78 | +0.41 | 2.2x | +0.22 | below → necessary in the grand coalition |

The informative row is the smallest. `nop` carries 5.377% of the dissipated energy yet its removal drops the periodic peak by 0.41 K — 2.2x the excess and 41x the 0.01 K quantum. Energy share does not predict which source decides the threshold; the deltas do, and they are what a paper table should carry rather than the necessity label.

## Appendix — the reported argmax block is mostly not resolvable

In **11 of 15** subsets the periodic argmax is tied with at least one other block within one 0.01 K quantum, and in 11 of them the top-two gap is exactly `0.000e+00` K — far below quantisation, so the model assigns both blocks the same temperature rather than rounding them together. Under `grid64-max` a block's temperature is the maximum over the grid cells covering it, so two blocks sharing the hottest cell receive identical values; that is the leading explanation and it is **UNTESTED** here. Every tie set in this document was reconstructed from the per-block temperature vectors, not read from the manifest.

2 subsets report a different argmax label for the two semantics:

| subset | steady argmax | periodic argmax | steady gap (K) | periodic gap (K) | periodic tie set | relocation? |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `core-dram-nop` | `ubuf_13` | `mtxu_16` | 0.00 | 0.00 | 2 | NO — a tie broken differently |
| `dram` | `dram_x0_y4` | `dram_x0_y0` | 0.00 | 0.00 | 4 | NO — a tie broken differently |

A label change counts as a relocation only if BOTH endpoints are resolvable: the old block outside the new tie set, the new block outside the old one, and both gaps above one quantum. 2 of 2 fail that test (`core-dram-nop`, `dram`), so they are not evidence that a peak moved.

## Scope

Evidence grade: **run-provenance-controlled, registry-instance-unbound, single-capture HotSpot evidence with producer-attested execution receipts.** The staged hashes establish integrity within this execution; `binds_instance_hashes = False` leaves the identity link to the originally registered trace and routing open; the raw HotSpot outputs are not archived here, so no consumer can reparse them; and no independent thermal model has validated any number.

Bounded to: this fixed trace; this fixed routing and timing; an additive deposition intervention with no temperature-dependent power feedback; the HotSpot model, candidate and discretisation; and the **fixed decomposition of 23.163 mJ into `core`, `dram`, `noc`, `nop`** — a different assignment of the same total would change every row, and that assignment is an artefact of the routed-trace lowering, not a measurement. NOT established: that any source alone suffices; that periodic uplift is baseline-independent (as a fraction of the steady rise above ambient it spans 1.89% for `dram-nop` to 5.02% for `noc`, and the 0.01 K quantum is already 0.37% of `noc`'s rise, so any source-identity effect is `UNTESTED`); generalisation to other candidates, models or discretisations; or agreement with any independent thermal model.

`grid128-max` has not been run as a factorial. Its registered argmax (`ubuf_13` steady / `ubuf_16` periodic, `docs/V6_PHYSICAL_TRACE_GATE.md:149`) differs from this run's `mtxu_16`, but given how few argmax labels here are resolvable that difference cannot be read as a spatial finding. A grid128 factorial would need its own preregistration and is only required if the paper claims resolution robustness or a spatial mechanism.

Manifest: `artifacts_receipts/v61_cg4_schema4/v61_manifest.json`
