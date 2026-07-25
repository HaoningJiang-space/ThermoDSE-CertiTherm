# V6 physical-trace gate — exact core vectors exist; the thermal input is incomplete

Status: **OPEN / transient replay blocked**  
Tier: NON-CLAIM diagnostic  
Revision: `3fa11d4`  
Host: `moe-server`, clean remote clone  
Commands:

```text
python research/triangle/order_trace_probe.py <out> <workload> <arch>
python research/triangle/energy_ledger.py <out> <workload> <arch>
```

## Question

Can the real ThermoDSE schedule be lowered into a floorplan-aligned, energy-conserving
spatial power trace that is meaningful to replay through HotSpot transient?

The answer at this revision is **no**. The per-order core vectors are obtainable and show
large spatial redistribution, but ThermoDSE's current thermal input omits or misplaces too
much external energy to serve as the physical oracle.

## What now works

`CertiTherm/thermodse_trace.py` lowers every per-order core component into the exact generated
floorplan names:

```text
mtxu -> mtxu_N       vecu -> vecu_N       ubuf -> ubuf_N
l0a + l0b -> ibuf_N  l0c + l1c -> obuf_N
```

It uses cycle-derived duration at the configured 1.8 GHz clock, includes compute energy, and
keeps NoC/NoP/DRAM as explicit unplaced residuals. It refuses missing/extra core blocks,
zero-duration orders, or a source-energy mismatch. Targeted remote tests pass: **22/22**.

Across two real workloads and three registered candidates, the represented core portion has
non-trivial spatial total-variation after scalar total-power amplitude is normalized away:

| workload | candidate | orders | physical latency (ms) | exactly placed core energy | time-weighted spatial TV | max spatial TV | distinct hottest blocks |
|---|---:|---:|---:|---:|---:|---:|---:|
| ResNet-50 | arch_a | 68 | 0.334497 | 41.12% | 0.4260 | 0.7464 | 16 |
| ResNet-50 | arch_b | 68 | 0.218311 | 46.13% | 0.4401 | 0.7289 | 19 |
| ResNet-50 | arch_c | 68 | 0.337058 | 44.14% | 0.4338 | 0.6893 | 17 |
| Transformer | arch_a | 124 | 0.586663 | 50.96% | 0.2660 | 0.9024 | 22 |
| Transformer | arch_b | 112 | 0.403236 | 55.71% | 0.3363 | 0.8440 | 24 |
| Transformer | arch_c | 129 | 0.524019 | 52.10% | 0.3916 | 0.8853 | 21 |

This closes one uncertainty: the scheduler does produce real spatial phase structure in the
exactly placed core portion. It does **not** establish any temperature or decision effect.

## What the original thermal path actually admits

`energy_ledger.py` calls ThermoDSE's original `gen_all_ptrace_3D` as the column-construction
oracle. It isolates each energy dictionary, verifies linear superposition, and then applies
the same floorplan-name admission that `CertiTherm/trace_runner.py` applies before HotSpot.
This distinguishes an emitted ptrace column from a column that actually enters the thermal
domain.

| workload | candidate | NoC admitted / source | NoP admitted / source | DRAM admitted / source | net source energy missing from HotSpot |
|---|---:|---:|---:|---:|---:|
| ResNet-50 | arch_a | 131.12% | n/a (zero source) | 0% | **43.99%** |
| ResNet-50 | arch_b | 128.98% | 0% | 0% | **45.16%** |
| ResNet-50 | arch_c | 133.41% | 0% | 0% | **49.99%** |
| Transformer | arch_a | 131.26% | n/a (zero source) | 0% | **24.97%** |
| Transformer | arch_b | 129.04% | 0% | 0% | **26.85%** |
| Transformer | arch_c | 133.37% | 0% | 0% | **36.11%** |

The mechanisms are source-visible, not inferred from aggregate mismatch:

1. NoC energy is copied uniformly to all four `io_*` blocks per core but divided by an edge
   count that is smaller than the number of receiving columns. This over-injects NoC energy
   by 28.98%–33.41%.
2. NoP energy is emitted only to `interposer`. `output_3D.flp` has no `interposer` unit, so
   name alignment drops 100% of it before HotSpot.
3. DRAM energy is never emitted; the generator lines are commented out. HotSpot admits 0%.

The missing and over-injected energy must be reported separately. Their scalar difference
cannot be treated as cancellation because they occupy different physical locations and
therefore have different Green responses.

The per-order isolated contributions reproduce the original four-decimal ptrace within the
derived serialization bound of `(orders + 1) * 0.5e-4 W` for all six cases. The earlier
fixed `1e-3 W` threshold falsely rejected `arch_a`; it has been replaced by this bound.

## A second blocker: route indices are not spatial evidence

ThermoDSE allocates:

```text
link_hops = [0] * y * (x + 2) * 4
```

because the route grid contains `x` compute columns plus two external DRAM columns. But
`Nop.get_link_idx` computes:

```text
(y_index * x + x_index) * 4 + direction
```

using stride `x`, not `x + 2`. Thus `(row, x)` and `(row + 1, 0)` collide, as do the next
external column and `(row + 1, 1)`. Some allocated entries are unreachable. `link_hops`
therefore cannot be decoded into a floorplan power map.

The safe adapter must capture the higher-level communication events
`(source, destinations, volume, order)` before this indexing, independently route them, and
check that reconstructed NoC/NoP/DRAM energy equals the monitor dictionaries. It must not
copy the corrupted link array.

### Event capture result

`research/triangle/route_event_probe.py` now captures
`move_between_core`, `read_from_DRAM`, and `write_to_DRAM` before the aliased index. It
measures the original implementation's NoC/NoP/DRAM counter delta for each event and
reconciles their sums against every monitor order.

| workload | candidate | captured events | orders | worst per-order relative error |
|---|---:|---:|---:|---:|
| ResNet-50 | arch_a | 4,423 | 68 | 3.89e-16 |
| ResNet-50 | arch_b | 4,452 | 68 | 1.36e-15 |
| ResNet-50 | arch_c | 2,887 | 68 | 4.45e-16 |
| Transformer | arch_a | 12,501 | 124 | 2.19e-15 |
| Transformer | arch_b | 10,307 | 112 | 8.61e-16 |
| Transformer | arch_c | 9,515 | 129 | 1.67e-15 |

All three channels pass per-order reconciliation on all six cases. This closes **event-data
availability**: unaliased source/destination coordinates, volume, stage, order, DRAM
locations, and exact channel energy survive without changing the pinned submodule. It does
not close physical placement. The events still need an independently checked router and
named DRAM/IO geometry before they become a thermal power vector.

## Gate consequence

Do **not** run or cite transient HotSpot on the current ptrace. A replay could be numerically
precise while omitting a quarter to half of the heat source and assigning the remaining
communication heat incorrectly.

The next implementation gate is:

1. capture per-order core-to-core and core-to-DRAM communication events without modifying
   the pinned ThermoDSE submodule;
2. add explicit, geometry-checked DRAM/IO-die blocks to the thermal floorplan;
3. lower NoC/NoP link and DRAM access energy to named blocks;
4. prove, per source and per order, that source energy equals HotSpot-admitted energy within
   a derived serialization/numerical bound;
5. only then perform fixed-initial and periodic-initial transient replay.

## Dissent ledger

| severity | falsifiable objection | required closing evidence | status |
|---|---|---|---|
| Critical | The current HotSpot input is not an energy-conserving representation of the real ThermoDSE execution. | Per-source/per-order source energy equals HotSpot-admitted energy; no omitted or over-injected channel beyond derived tolerance. | **OPEN** |
| Critical | Communication heat cannot be located from `link_hops` because its coordinate index aliases rows and external columns. | Independent event capture and route reconstruction with parity against aggregate NoC/NoP energy on all registered candidates. | **OPEN — event capture parity passed 6/6; route-to-floorplan lowering remains** |
| Critical | No physical DRAM blocks exist in the active floorplan even though DRAM contributes 5.55–6.92 mJ for Transformer and 3.74–4.03 mJ for ResNet-50. | Explicit DRAM/IO geometry, area/placement receipt, and 100% DRAM energy admission. | **OPEN** |
| Major | Spatial power migration may still have negligible temperature or decision effect at sub-millisecond periods. | Converged fixed-initial and periodic-initial transient replay after all Critical trace objections close. | **OPEN** |
