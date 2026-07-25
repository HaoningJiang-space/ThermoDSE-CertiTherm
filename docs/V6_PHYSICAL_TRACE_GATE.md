# V6 physical-trace gate — one route ledger now drives energy, latency, and heat

Status: **PHYSICAL TRACE CLOSED / broad transient claim rejected; one HotSpot-converged grid-max boundary counterexample**
Tier: NON-CLAIM diagnostic  
Revision: through `6191d84` plus the registered grid-max convergence runs
Host: `moe-server`, clean remote clone  
Commands:

```text
python research/triangle/order_trace_probe.py <out> <workload> <arch>
python research/triangle/energy_ledger.py <out> <workload> <arch>
python research/triangle/route_classification_audit.py <route-event.json> [...]
python research/triangle/complete_trace_probe.py <out> <workload> <arch>
python research/triangle/transient_trace_probe.py <trace.npz> <floorplan> <sim> <out> [model] [step-us]
```

## Question

Can the real ThermoDSE schedule be lowered into a floorplan-aligned, energy-conserving
spatial power trace that is meaningful to replay through HotSpot transient?

The original ThermoDSE thermal path still answers **no**: it omits or misplaces too much
external energy. The new physical-ledger path answers **yes for trace construction** on all
six registered workload/candidate cases.

The first decision result is deliberately narrower than the original transient motivation.
Under both block and `grid64-avg`, periodic time structure changes no feasibility decision,
thermal ordering, or selected architecture in the registered 2-workload x 3-candidate
matrix. Spatial model choice is larger than temporal uplift in every one of those cases.
One boundary case, Transformer/`arch_b` under grid-max, does cross 330 K from
time-mean steady to periodic replay. The flip survives time-step refinement and
`grid64-max` to `grid128-max` refinement. It is a HotSpot-model counterexample, not an
external signoff result.

## Current closure update

The first route lowering failed closed because events with positive reported NoC energy had
only physical NoP edges. The mismatch was systematic:

| workload | candidate | mismatched events | reported NoC energy on all-NoP paths / total NoC |
|---|---:|---:|---:|
| ResNet-50 | arch_a | 0 | 0% |
| ResNet-50 | arch_b | 104 | 0.8706% |
| ResNet-50 | arch_c | 125 | 2.0636% |
| Transformer | arch_a | 0 | 0% |
| Transformer | arch_b | 188 | 0.7351% |
| Transformer | arch_c | 550 | 4.0696% |

Every mismatch was an adjacent cross-chiplet `core_to_core` edge labeled NoC; there were
zero opposite-direction mismatches. Merely redistributing the old aggregate counters was
therefore invalid. An attempted independent XY-union lowering also failed its hop receipt:
on `arch_c/ResNet-50` it produced 1.5821x the old internal-hop total. Its resulting
+0.522 mJ “correction” was rejected because it mixed boundary reclassification with a
changed multicast topology.

`CertiTherm/physical_nop.py` is now the replacement single fact source. It preserves the
pinned public cost interface but uses an unaliased `(nx + 2)` stride, deterministic
X-then-Y paths, one charge per rooted multicast-tree edge, and explicit chiplet-boundary
classification. The same edge ledger drives contention latency, channel energy, and heat
placement. The pinned submodule remains unchanged; this replacement is explicitly installed
only for the physical path.

The augmented floorplan preserves all original blocks and adds four named DRAM dies.
Upstream supplies their area and external location but no aspect ratio, so square dies are
an explicit sensitivity assumption. Uncovered side-strip area is zero-power filler and all
geometry is checked for overlap.

For every event, route energy is recomputed from volume, physical edge, and the evaluator's
per-hop cost. It must equal the physical monitor's NoC/NoP/DRAM energy for every order:

| workload | candidate | phases | blocks | latency (ms) | source (mJ) | routed (mJ) | physical/monitor hops |
|---|---:|---:|---:|---:|---:|---:|---:|
| ResNet-50 | arch_a | 68 | 243 | 0.334497 | 9.439827 | 5.949307 | 1.000000000 |
| ResNet-50 | arch_b | 68 | 233 | 0.221210 | 9.908419 | 5.657804 | 1.000000000 |
| ResNet-50 | arch_c | 68 | 187 | 0.337107 | 9.744279 | 5.673949 | 1.000000000 |
| Transformer | arch_a | 124 | 243 | 0.586984 | 23.632178 | 12.153209 | 1.000000000 |
| Transformer | arch_b | 112 | 233 | 0.405057 | 23.163035 | 10.415653 | 1.000000000 |
| Transformer | arch_c | 129 | 187 | 0.524478 | 24.156554 | 11.824104 | 1.000000000 |

All six traces conserve integrated energy and retain exact block identity. Targeted remote
tests pass 32/32 for route, floorplan, core lowering, and phase-trace contracts.

### First periodic transient receipt

Variable phases are averaged into a uniform HotSpot time grid while conserving every
block's energy. Both a common 318.15 K one-cycle start and a repeated trace initialized
from mean-power steady state are reported. Pinned HotSpot serializes `.ttrace` to
**0.01 K**; an earlier 1e-4 K convergence label was rejected as finer than the observable
output.

For `arch_c/ResNet-50` under the block model:

| max step | actual step | samples/cycle | periodic peak | hottest block | fixed-initial peak |
|---:|---:|---:|---:|---|---:|
| 1.0 us | 0.997359 us | 338 | 325.43 K | `dram_x5_y3` | 319.50 K |
| 0.5 us | 0.499418 us | 675 | 325.43 K | `dram_x5_y3` | 319.50 K |
| 0.25 us | 0.249894 us | 1349 | 325.43 K | `dram_x5_y3` | 319.50 K |

Eight cycles made the final two observed block-temperature cycles indistinguishable at
0.01 K. The 5.93 K cold-versus-periodic gap proves initialization is material. It does not
yet validate grid discretization or establish a decision flip.

### Registered 2 x 3 decision matrix

All six block and all six `grid64-avg` cases were replayed for up to eight cycles from the
same mean-steady initialization. Every case converged at the observable 0.01 K precision.

| workload | candidate | block mean / periodic (K) | grid64-avg mean / periodic (K) |
|---|---:|---:|---:|
| ResNet-50 | arch_a | 325.861 / 325.92 | 324.878 / 324.92 |
| ResNet-50 | arch_b | 327.615 / 327.70 | 326.987 / 327.01 |
| ResNet-50 | arch_c | 325.338 / 325.43 | 324.578 / 324.61 |
| Transformer | arch_a | 327.158 / 327.22 | 326.342 / 326.44 |
| Transformer | arch_b | 330.796 / 330.94 | 329.459 / 329.51 |
| Transformer | arch_c | 327.853 / 327.87 | 326.913 / 326.94 |

Within either model, there is no mean-to-periodic feasibility flip, thermal-ranking flip,
or selection regret. The maximum temporal uplift is 0.144 K. By contrast, the smallest
absolute block-versus-grid periodic difference is 0.69 K. Model fidelity therefore
dominates temporal detail on this small registered matrix.

The model choice itself changes the Transformer decision at 330 K: block declares
`arch_b` infeasible and selects `arch_c`, while `grid64-avg` declares `arch_b` feasible
and selects it. Using the corrected physical-time EDYP objective, the block choice has
2.54252 absolute regret, or 33.01%, relative to the grid choice. This is evidence that
spatial/model refinement matters; it is not evidence that averaging is a safe signoff
operator.

### Grid-max boundary case

`grid64-max` is used here because a safety decision cannot be justified from cell averages.
For Transformer/`arch_b`, its time-mean steady peak is 329.904867 K at `mtxu_16`, while
the 0.5 us periodic replay reaches 330.19 K at the same location. Thus the same registered
HotSpot model contains a mean-to-periodic feasibility flip at the declared 330 K boundary.
Time-step convergence is exact at HotSpot's output precision:

| model | max step | actual step | cycles | mean steady | periodic | boundary residual |
|---|---:|---:|---:|---:|---:|---:|
| grid64-max | 1.0 us | 0.997677 us | 16 | 329.904867 K | 330.19 K | 0.01 K |
| grid64-max | 0.5 us | 0.499453 us | 16 | 329.904867 K | 330.19 K | 0.01 K |
| grid64-max | 0.25 us | 0.249881 us | 16 | 329.904867 K | 330.19 K | 0.01 K |

All three runs identify `mtxu_16`. Spatial-grid refinement gives:

| model | actual step | cycles | mean steady | periodic | boundary residual |
|---|---:|---:|---:|---:|---:|
| grid64-max | 0.499453 us | 16 | 329.904867 K (`mtxu_16`) | 330.19 K (`mtxu_16`) | 0.01 K |
| grid128-max | 0.499453 us | 16 | 329.918874 K (`ubuf_13`) | 330.20 K (`ubuf_16`) | 0.01 K |

The grid-refined periodic peaks differ by 0.01 K and both cross 330 K. Local hotspot
identity changes, so `grid64-max` is not a claim about exact hotspot ownership, but the
feasibility flip is invariant. This closes the registered HotSpot time/grid convergence
gate positively.

The comparison is threshold-sensitive: the observed uplift is only 0.285 K and HotSpot
serializes transient output to 0.01 K. It proves neither silicon temperature nor general
prevalence. It does show the correct possible role for transient analysis: a late,
margin-triggered refinement after source, route, geometry, and spatial-max semantics have
already been validated.

For the non-boundary `arch_c`/ResNet-50 case, `grid64-max` is stable at 325.30 K. Varying
the uncharacterized DRAM aspect ratio over 0.5, 1, and 2 changes its periodic peak only
from 325.27 K to 325.30 K (0.04 K span). This closes that limited geometry sensitivity;
it does not calibrate DRAM/package geometry to a manufactured system.

### Route correction changes objective magnitudes, not this small ranking

Replacing the aliased legacy route accounting with the physical ledger changes physical-time
EDYP by 6.57%–13.13% on ResNet-50 and 2.09%–6.59% on Transformer. The registered order
remains `arch_b`, `arch_c`, `arch_a` for both workloads. Deterministic event and hop
receipts, rather than shared-host wall time, are the leading evidence.

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

Do not cite the original ptrace, the rejected mixed-topology correction, or a universal
“transient matters” claim. The evidence supports a different fidelity order:

1. validate workload energy, route semantics, and named physical placement;
2. refine spatial peak fidelity and reject unsafe average-only decisions;
3. use cheap steady analysis when its certified margin dominates model/error bounds;
4. invoke periodic transient only for unresolved near-boundary candidates;
5. abstain or escalate to an independent signoff model when the registered models disagree.

Before a paper claim, repeat this policy on a true top-K frontier, measure its production
cost, and validate all escalated decisions with an independent 3D-ICE/FEM-class model.
The current two-workload, three-candidate HotSpot study is a mechanism and falsification
study, not enough breadth or external validity for DAC/ICCAD.

## Dissent ledger

| severity | falsifiable objection | required closing evidence | status |
|---|---|---|---|
| Critical | The original HotSpot input is not an energy-conserving representation of the execution. | Per-source/per-order source energy equals HotSpot-admitted energy. | **CLOSED for physical path, 6/6; original path invalid** |
| Critical | Latency, energy, and heat use inconsistent aliased or invented routes. | One unaliased ledger drives contention, energy, and placement; independent parity. | **CLOSED, 6/6 at hop ratio 1.0** |
| Critical | No physical DRAM blocks exist despite material DRAM energy. | Explicit geometry, area/placement receipt, and 100% energy admission. | **CLOSED under square-die assumption; sensitivity OPEN** |
| Major | A cold one-cycle replay stands in for repeated operation. | Fixed-initial and periodic replay with observable convergence tolerance. | **CLOSED, all 12 block/grid-avg cases; cold-start bias is material** |
| Major | Block discretization may hide or mis-rank grid-local peaks. | Grid transient convergence and cross-candidate comparison. | **CLOSED negatively for grid-avg as signoff; one grid-max flip survives grid/time refinement** |
| Major | Correcting the route ledger may change the DSE objective ranking. | Regenerate and compare old/new candidate objectives. | **CLOSED on registered 2 x 3: magnitude changes, order does not** |
| Major | A HotSpot-only boundary flip may be numerical or model-specific. | Time-step and grid convergence plus independent 3D-ICE/FEM replay. | **HotSpot convergence CLOSED; external validation OPEN** |
