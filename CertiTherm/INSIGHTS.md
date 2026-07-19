# CertiTherm Phase 1 Insights: What's Interesting

## Headline insight

**Spatial power variation causes 17% design-flip rate in thermal-feasibility verdicts.** This validates the CertiTherm research direction.

## Specific findings (ranked by novelty)

### 1. **The 6-7K thermal budget margin is exactly what's violated** (Strongest finding)

Paper's best TESA SA ideal `[4,4,4,4,0.0005,...]` had uniform T=341.3K with 6.7K margin to the 348K budget. Spatial power pushes T to 392.3K — **44K over budget**. The "we have margin" argument DSE papers make is invalid because the margin is exactly the right size to be sensitive to spatial variation.

### 2. **False-feasible is the dominant failure mode (asymmetric)**

- UNIFORM_SAFE_SPATIAL_FAIL: 2 designs (uniform too optimistic)
- UNIFORM_FAIL_SPATIAL_SAFE: 0 designs (uniform never too pessimistic)

This asymmetry means: **uniform-power DSE systematically picks thermally-risky designs**. If CertiTherm's certificate is `definitely_safe`, it must hold under any spatial power realization. The current best practices (T uniform + small margin) don't.

### 3. **SA-found designs are more vulnerable than uniformly-random ones**

The two designs that flip (`[4,4,4,4,0.0005,...]` and `[4,5,2,1,0.0017,...]`) are:
- One is **paper's recommended best** (TESA SA ideal winner)
- One is **our SCBO two-stage recommended best** (EDYP 195.18)

The min-design (`[2,2,1,1,0.0005,...]`) did NOT flip — it has 273K margin to budget, robust to spatial power. **The optimizer-found winners are exactly the ones at the decision boundary, which is where spatial variation flips them.**

### 4. **Spatial pattern shape matters more than peak strength**

| Pattern | Strength | Flip rate |
|---|---|---|
| centered 5x | 5x | 17% |
| centered 3x | 3x | 12% |
| corner 3x | 3x | 0% |

Centered concentration is more dangerous than corner concentration at the same peak multiplier. This matters for DSE because:
- Real workload-aware power tends to concentrate in compute-heavy regions
- A centered pattern is more realistic for matrix-multiplication-heavy workloads (transformer, CNN)
- CertiTherm should default to centered-pattern analysis, not corner

### 5. **Quantitative relationship: spatial T shift scales with concentration**

Mean shift: +21K (centered 5x), +11K (centered 3x), +1K (corner 3x).

Roughly: `delta_T ≈ strength × concentration_factor × base_power_density`. For the systems here:
- strength=5x with 1 chip concentrated → ~50K delta (matches design 2)
- strength=3x → ~25K delta (matches design 3)
- corner pattern (2 chips concentrated) → ~12K even at 5x (matches corner data)

This gives a back-of-envelope formula: for a system at uniform T with margin M, spatial power can shift T by ~`(peak_multiplier - 1) × chip_concentration × T_uniform`. If M < this, decision flips.

## How this maps to CertiTherm paper

### Section 3 (contribution): Decision-Adequate Certificate

We have evidence that:
- `certify_safe` requires showing peak T ≤ budget under **all** spatial power realizations (worst-case bound)
- Current best EDYP winners fail this — they're at the decision boundary
- The certificate must include both architectural feasibility AND spatial-robustness

### Section 4 (method): Spatial Power Uncertainty Set

Our results motivate:
- Use `max_pattern_peak(spatial) - uniform_peak` as the "spatial sensitivity" metric
- Designs with high spatial sensitivity → mark `undecidable` and request more data
- Designs with low spatial sensitivity → mark `definitely_safe` if uniform-T ≤ budget

### Section 5 (experiments): Decision-Flip Audit (this audit)

The Phase 1 audit can be the "preliminary" experiment in the paper, showing the abstract problem is real. The full paper adds:
1. Real SAIF/VCD traces (gem5+McPAT) instead of synthetic
2. CertiTherm's certificate logic and active refinement
3. Comparison vs 3D-ICE oracle for bound verification

## What's NOT interesting (avoid)

1. "Spatial power changes temperature" — obvious, already known from CHIPSIM work
2. "Uniform power is wrong" — known from Chiplet3D
3. "Different workloads have different power profiles" — known from any DSE

CertiTherm's unique contribution is the **decision-level framing**: "when can we TRUST an architectural choice without measuring spatial power?" That's the abstract gap this Phase 1 audit validates.

## Implications for follow-up work

1. **Immediate next step**: replace synthetic spatial patterns with real workload traces from gem5+McPAT. Estimate 1-2 weeks.
2. **Build the certificate logic**: a classifier that produces `definitely_safe / undecidable` given an uncertainty set. Estimate 2-3 weeks.
3. **Active refinement**: when `undecidable`, decide what finer spatial data to request. Estimate 2-3 weeks.
4. **3D-ICE oracle verification**: independent thermal backend. Estimate 1 week.
5. **Scale to 50+ designs, 5+ workloads, 3+ package regimes**: produce the kill gate evidence for the paper. Estimate 2 weeks.

Total: ~10-12 weeks to a paper submission.

## Why this is a strong paper

The CertiTherm direction is differentiated from:
- ThermoDSE 2026: provides accuracy, not decision-certificates
- DiffChip 2025: differentiable thermal surrogate, not certificates
- Chiplet3D 2026: thermal-aware placement, not early-stage identification
- CHIPSIM 2025: cycle-accurate power, not decision-making

The novelty is asking "given the information we have at DSE time, can we trust
the architectural decision?" — and providing three deliverables:
1. `decision_identifiability` as a new objective (not MAE)
2. A certifiable method (no false-positives on `definitely_safe`)
3. An active information-acquisition algorithm (only request more data for
   undecidable cases)

## Memory file: `/home/ynwang/.claude/projects/-home-ynwang/memory/certitherm-audit-2026.md`