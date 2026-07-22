# CertiTherm Phase 1 Audit Summary

> **LEGACY_INVALIDATED_FOR_CLAIMS (2026-07-19).** The numbers below are
> preserved as historical pilot output. The generating injector used an
> incorrect ptrace schema and did not conserve component-total power; failed
> rows and cross-run inconsistencies also invalidate the reported rates and
> temperature deltas. Do not cite this file as evidence. See
> `INTEGRITY_AUDIT_20260719.md`.

## Experimental Setup

- **Goal**: Test if uniform-power vs spatial-power changes architectural decisions
- **Test designs**: 8-12 representative sys_info designs (mix of paper-discovered,
  our SCBO-discovered, and diverse exploration)
- **Spatial modes tested**: centered (5x peak at center), corner (2x at corners), checker (alternating)
- **Strengths tested**: 5x peak (centered), 5x peak (corner), 3x peak (centered, more realistic)

## Key Results

### Decision-Flip Rate

| Mode | Strength | Tested | Safe_Both | Infeas_Both | UNIFORM_SAFE_SPATIAL_FAIL | UNIFORM_FAIL_SPATIAL_SAFE | Flipped |
|---|---|---|---|---|---|---|---|
| centered | 5x | 12 | 3 | 4 | 2 | 0 | **2/12 = 17%** |
| centered | 3x | 8 | 3 | 3 | 1 | 0 | **1/8 = 12%** |
| corner | 5x | 8 | 3 | 3 | 1 | 0 | **1/8 = 12%** |

### Peak Temperature Delta (spatial - uniform)

| Mode | Strength | Mean | Max | Min | Std |
|---|---|---|---|---|---|
| centered | 5x | +21.5 K | +51.0 K | +0.5 K | 13.1 K |
| centered | 3x | +10.7 K | +25.5 K | +0.3 K | 7.4 K |
| corner | 5x | +7.8 K | +21.6 K | -5.5 K | 9.5 K |

## Critical Insight: CertiTherm Kill Gate PASSED

The decision-flip audit shows that **spatial power variation causes feasibility
flips** — specifically:

1. **2/12 designs (17%)** are classified as FEASIBLE under uniform power but
   INFEASIBLE under spatial power (centered mode, strength=5x).
2. The **designs that flip are the SAME designs that paper / our SCBO recommends
   as winners** — `[4, 4, 4, 4, 0.0005, ...]` and `[4, 5, 2, 1, 0.0017, ...]`.
3. **Peak temperature shifts by up to +51 K** under spatial power — exceeding
   the 7 K margin between paper's reported 341.3 K and the 348 K thermal budget.

This is the exact scenario CertiTherm's kill gate was designed to detect:
**fine-grained power DOES cause reproducible false-feasible outcomes** that
can flip architectural decisions.

## Examples of Decision Flips

### Design 2: `[4, 4, 4, 4, 0.0005, 112, 128, 4194304, 64, 128]`
- Uniform peak T: 341.3 K → FEASIBLE
- Spatial peak T: 392.3 K (+51 K!) → INFEASIBLE
- This is **paper's best TESA SA ideal design** — would be wrongly certified!

### Design 4: `[4, 5, 2, 1, 0.0017, 128, 128, 1048576, 112, 224]`
- Uniform peak T: 332.25 K → FEASIBLE
- Spatial peak T: 353.5 K (+21.25 K) → INFEASIBLE
- This is **our SCBO two-stage best** (EDYP 195.18) — also wrongly certified!

## Implications for CertiTherm Paper

1. **The abstract is validated**: thermal decision identifiability is a real
   problem, not invented.
2. **The 17% flip rate is sufficient evidence**: even at conservative
   spatial patterns (3x peak), 12% of designs flip.
3. **The false-feasible category is dominant**: uniform power systematically
   UNDER-estimates peak temperature, especially for designs with concentrated
   compute regions. This is the bias CertiTherm can fix.
4. **The paper can claim a concrete safety property**: certi-safe designs
   would have ZERO false-feasible rate under any spatial power in the
   uncertainty set.

## Next Steps for CertiTherm Paper

1. **Build the certificate logic**: given spatial-power uncertainty set,
   produce `definitely_safe / definitely_infeasible / undecidable` per design.
2. **Active refinement**: for undecidable candidates, request more spatial
   data; report query complexity reduction.
3. **Validate on real workloads**: use gem5+McPAT to get real workload-aware
   power traces (instead of synthetic Gaussian patterns).
4. **Compare against 3D-ICE oracle**: independent thermal backend to verify
   certificate correctness.

## Caveats / Limitations

- **Synthetic spatial patterns**: We used Gaussian/corner/checker shapes, not
  real SAIF/VCD traces. Real workload traces may show different flip rates.
- **Single workload assumption**: The decision-flip test used the standard
  7-workload average. Per-workload flips may differ.
- **Block model only**: We used HotSpot block model (not detailed_3D). Real
  vertical coupling could change the picture.

## Files in this audit

- `spatial_power_injection.py` — retained ptrace modifier and regression fixture
- legacy decision-flip drivers and their workstation-local CSV outputs — preserved
  at Git tag `legacy-g1-g4-archived`, removed from the active branch because
  they had no callers and embedded non-portable machine paths
