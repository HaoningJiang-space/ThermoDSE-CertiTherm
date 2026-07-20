# G3-C Frozen Baseline Comparison Report

Date: 2026-07-20  
Source commit: `46f327f1` (clean-tree registered run, replay `PASS`)  
Claim-grade artifact: `/tmp/certitherm_g3_real_outputs/g3_baseline_comparison.json`  
Artifact SHA-256: `49ee2f4237931fc790825075d70b86faf3d1c0b60f028b0739f5faab86215fa3`  
In-repo summary: `CertiTherm/results/G3_BASELINE_COMPARISON_20260720.json`

## Scope

Contract requirement (RESEARCH_CONTRACT, "Method is operationally useful"):
comparison against **uniform**, **sampled-stress**, **interval-box**, and
**fixed-refinement** baselines on the registered real 2×2×2 suite, with query
cost, runtime, RSS, certificate size, and regret.

All four baselines ran under the registered G3 loader on **identical
candidates, objectives, thermal limit (330 K), and thermal operator**. The
recomputed deployed ThermoDSE point path reproduces the registered
`point_estimate` variant outcome in 4/4 strata
(`fairness_point_path_matches_registered_variant = true`).

Physical reference: `placed_reference` certified outcome
(`arch_5x4_rect_struct` in all 4 strata; placed peaks 322.0–324.6 K ≤ 330 K).

## Headline table (4 strata)

| Method | Commits | Certified | Unjustified commits | Wrong arch | False-safe / false-infeasible | Regret (obj) | Physical queries | Wall time |
|---|---|---|---|---|---|---|---|---|
| `uniform_aggregate_point` (deployed ThermoDSE) | 4/4 | 0 | **2** | 0 | 0 / 0 | 0 | 0 | <0.01 s |
| `k_sample_synthetic_stress` (K=64, frozen seeds) | 4/4 | 0 | **2** | **2** | 0 / 0 | **22.50** (11.25 per attention workload) | 0 (512 synthetic samples) | 0.12 s |
| `interval_box_aggregate` (certified conservative) | 2/4 | 2/4 | 0 | 0 | 0 / 0 | 0 | 0 | 5.76 s |
| `fixed_uniform_refinement` (non-adaptive full sensing) | 2/2 applicable | 2/2 | 0 | 0 | 0 / 0 | 0 | **360 channels** (180/stratum) | 2.79 s |
| **Registered spatial path (proposed)** | 2/4 certified | 2/4 | 0 | 0 | 0 / 0 | 0 | 0 | 60.2 s (12 variants: 200.3 s incl. point/placed) |

## Per-stratum findings

### CNN strata (2) — spatial oracle CERTIFIED

All methods select `arch_5x4_rect_struct`, matching the placed reference.
Interval-box widths (6.62–6.79 K) are only slightly wider than the coupled
spatial bounds (6.16–6.27 K); K=64 sampling finds zero violations
(max sampled peaks 326.4–326.9 K vs the 330 K limit).

### Attention strata (2) — spatial oracle NON_IDENTIFIABLE

- **`uniform_aggregate_point` commits blindly.** It selects the physically
  correct `arch_5x4_rect_struct` in both strata but cannot know the decision
  is non-identifiable: 2 unjustified commitments. On this suite the deployed
  point path is *lucky, not certified*.
- **`k_sample_synthetic_stress` flips the architecture choice.** Sampling
  hits the admissible-but-unrealized hot corner of `arch_5x4` (6/64 and
  5/64 violations; max sampled peaks 330.59 K / 330.40 K) while missing the
  milder `arch_4x4` corners (0 violations; max 329.79 K / 328.94 K). The
  stress test therefore rejects the physically better design and selects
  `arch_4x4_mesh_fullcut` in both strata — objective regret
  32.08 − 20.83 = **11.25 EDYP per workload (+54 %)**. Finite sampling
  alone is neither a bound nor a safe decision rule.
- **`interval_box_aggregate` stays honest but loses resolution.** With group
  coupling replaced by one aggregate sum row it reports NON_IDENTIFIABLE in
  both attention strata (widths 8.6–9.8 K vs spatial 8.2–9.1 K). It never
  over-commits (0 unjustified) but its certified coverage is 2/4 with
  strictly wider intervals — the conservative option, not a decision tool.
- **`fixed_uniform_refinement` prices brute-force sensing.** Certifying the
  two non-identifiable strata by uniform refinement to full placement costs
  180 sensor channels per stratum (100 undetermined blocks on `arch_5x4` +
  80 on `arch_4x4`), 360 total, to reach the placed outcome. This is the
  frozen acquisition-cost column that G4 witness-directed acquisition must
  beat at matched correctness.

## Systems cost

- Baseline runner: wall 33.0 s total (all 4 baselines × 4 strata), peak RSS
  170,240 KB; per-baseline wall times in the summary JSON.
- Suite variants (12): total wall 200.3 s, peak RSS 555,896 KB, certificate
  sizes 12,759–21,696 B (`G3_SYSTEM_COST_SUMMARY_20260720.json`).
- Baseline result record sizes: recorded per row as
  `certificate_size_bytes` in the summary JSON.

## Replay

- Registered runner executed from fresh clean clone `/tmp/certitherm_g3c_clone`
  at commit `46f327f1`; receipt `PASS` (recomputes every baseline from the
  content-bound bundle and compares all deterministic fields).
- Suite artifact replay embedded in the baseline runner: `PASS`.

## Claim boundary

Baseline rows are frozen comparison procedures, not certificates (except
`interval_box_aggregate`, which is certified but conservative). A finite
sample maximum is never a bound. This report closes the G3-C evidence
requirement; it does not by itself establish G4 acquisition benefit — the
fixed-refinement column is the cost reference G4 must undercut.
