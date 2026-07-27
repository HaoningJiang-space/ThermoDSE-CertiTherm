# V7 — the periodic uplift is die-local; the crossing claim is withdrawn

Generated from committed data by `research/triangle/v7_locality_report.py`. No number here is hand-transcribed: each is read from `artifacts_receipts/v61_cg5_schema5/v61_manifest.json` or from the material block of `docs/registration/v7_gate_stack_mapping.json`, or derived from those by the formula printed beside it. The workload period is not a separate input — it is `step_s * samples_per_cycle`.

## What is withdrawn

The claim that the `grid64-max` transformer/arch_b 330 K crossing is model-robust — that transient analysis flips this feasibility decision in a way that survives model choice.

**It is withdrawn because model-robust support could not be established, not because an independent model disproved it.** No 3D-ICE or FEM run was performed and no gate output exists. The independent-model gate was preregistered and then closed without a verdict, because 3D-ICE cannot represent this package: `ThreeDicePassiveLayerSpec` carries no footprint and the chip dimensions are global, so a 21.7 x 17.95 mm die, a 50 mm spreader and a 60 mm sink cannot coexist. Truncating them to the chip footprint adds 44.921 mK/W of series copper — about 2.57 K at 57.18 W against a 0.095133 K margin — and enlarging the global footprint instead would extend the silicon die itself as fictitious material.

The >= 0.69 K intra-HotSpot spatial spread recorded in `docs/V6_PHYSICAL_TRACE_GATE.md` establishes that the classification is **fragile**, not that transient boundary flips do not exist. Nothing here is a convergence result.

## What replaces it: the uplift is local, and that is measurable

The V6.1 factorial is already a locality experiment. Going from the `core`-only subset to the full four-source set adds **45.0% of the dissipated energy**, and:

| quantity | core only | full | change |
| --- | ---: | ---: | ---: |
| steady rise above ambient | 8.119 K | 11.755 K | **+3.636 K** |
| periodic uplift | 0.2712 K | 0.2851 K | +0.0139 K |

The uplift change is only 1.4 output quanta at the 0.01 K reporting resolution, so the defensible form is an upper bound rather than a percentage: **the uplift moves by at most 0.024 K** while the steady rise moves 3.636 K — a sensitivity ratio of **>= 152x**.

Across all 15 subsets, `corr(energy, steady rise) = +0.991` and `corr(energy, uplift) = +0.828`. Restricting to the 8 subsets that contain `core`, where energy still varies 1.8x, the split is sharper: `corr(energy, steady rise) = +0.989` against `corr(energy, uplift) = +0.164` — no trend.

## Why: the thermal wave never reaches the package

At a period of 0.4050567 ms (2469 Hz, omega = 15512 rad/s), with silicon `alpha = k/c = 130.0/1630300 = 7.974e-05` m^2/s, the penetration depth is

    delta = sqrt(2 alpha / omega) = 101.4 um

against a 150 um die: `delta / t_die = 0.68`. In the TIM it is 11.4 um against a 20 um layer. The periodic component is therefore confined to the die and the first few tens of microns above it, which is why lateral and remote sources — DRAM dies at the chip corners, distributed NoC and NoP — contribute steady heat but almost no local ripple.

## The criterion this yields

> Transient refinement is decision-relevant exactly when the steady margin is smaller than the **local** ripple. The ripple is set by die properties and workload frequency and is estimable without any package model; the absolute level, which is what a threshold crossing depends on, is precisely the package-dependent part.

That is why the two halves of this instance have opposite epistemic status. The uplift is a robust physical feature: it survives removing 45% of the dissipated power, and its scale follows from a diffusion length. The crossing is not certifiable at 0.1 K, because it depends on an absolute level that no two thermal models agree on to that precision — within HotSpot alone, changing only the spatial mapping moves it by >= 0.69 K.

## Scope

- One candidate (transformer/arch_b), one workload period, one HotSpot model, and `grid64-max` is **out of the certified family** (`block`, `grid64-avg`, `grid128-avg`) — so none of this is certificate evidence.
- `delta` is a one-dimensional semi-infinite estimate. It supplies the *scale* and the explanation; it is not a predicted uplift. The sensitivity ratio is the measurement.
- The energy/uplift decoupling is measured across the subsets of a single instance. It is consistent with the twelve `block` and `grid64-avg` uplifts already recorded (0.017–0.144 K), but those cases have no committed per-case traces, so no cross-workload predictor is claimed.
- No independent thermal model has validated any number here.

Source manifest commit `fd9d93bb3e13`.
