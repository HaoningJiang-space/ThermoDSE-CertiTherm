# CertiTherm: Spatial Power Identifiability for Chiplet DSE

> **Evidence status (2026-07-20): G2 CORRECTED; G3 FULL PASS (A breadth + B physical replay + C baseline/system cost); G4 PASS (matched 3-policy acquisition comparison). All contract gates G1–G4 closed.**
> The authoritative gate ledger is
> `results/G3_REAL_2x2x2_CONSOLIDATED_REPORT.md`; baseline/system-cost
> evidence is in `results/G3_BASELINE_REPORT.md` and
> `results/G3_BASELINE_COMPARISON_20260720.json`; G4 acquisition evidence is
> in `results/G4_REPORT.md` and `results/G4_POLICY_COMPARISON_20260720.json`.
> The committed
> Gaussian/corner/checker and finite-sample results are retained as legacy
> debugging artifacts, but are not valid paper evidence. Their generator used
> the wrong ThermoDSE ptrace column order, did not conserve obtainable
> component-total power, could reuse stale cross-design state, and contained a
> fail-open thermal constraint. The later `5/8` G3 pilot is also withdrawn
> because it relabeled aggregate workload data, reused package operators, and
> compared nested uncertainty sets rather than architecture queries. The
> corrected G2 query supports only its registered narrow certificate/witness.
> The replacement G3 object — the content-bound real 2 DNN × 2 non-isomorphic
> architecture × 2 package suite — has since been built, replayed under two
> independent thermal backends, and compared against the four contract
> baselines. See
> `audit/INTEGRITY_AUDIT_20260719.md`, `results/G2_CORRECTION_REPORT.md`,
> `results/G3_FULL_REPORT.md` (legacy retraction), and the gate ledger above.

## Core thesis (independent of ThermoDSE 2026)

> Early-stage chiplet DSE has only module-average power, no final spatial power map.
> The question is not "is temperature accurate?" but
> "is the available information sufficient to certify an architectural decision,
> and what is the minimum additional physical information needed?"

## Why this is independent (not "ThermoDSE++")

Original ThermoDSE already covers:
- Architecture (cores, chiplet cuts, systolic array)
- Task orchestration
- Inter-chiplet communication
- Area and thermal constraints

Replacing the optimizer (BO → RL → multi-fidelity) or adding transient
thermal or runtime scheduling is incremental work that reviewers will
reject as "another accuracy improvement".

The novelty is **decision-level**: given the available information, can
we *certify* an architectural decision? If not, *which* additional
information is needed and *where*?

## Three deliverables (paper structure)

1. **New decision object**: `thermal decision identifiability` — distinct
   from temperature MAE.
2. **Certifiable method (planned)**: Use DNN mapping + PE activity envelope + power
   conservation to construct a fine-grained power uncertainty set, then
   compute peak temperature upper/lower bounds. Output one of three
   labels per design: `definitely_safe / definitely_infeasible / undecidable`.
3. **Decision-directed information acquisition**: For undecidable
   candidates, request finer subarray / placement / post-route power
   on demand. Not all designs pay the cost of detailed physical flow.

## Hard kill gates (pre-registered)

- [x] Use real SAIF/VCD + post-placement instance power (no random
      Gaussian hotspots). — content-bound 2×2×2 bundle, per-DNN ptrace
      (G3-A)
- [x] At least 2 DNN families, 2 non-isomorphic architecture families,
      2 package regimes. — resnet50/transformer × 5x4-rect/4x4-mesh ×
      s06/s10 (G3-A)
- [x] Fine-grained power must cause reproducible false-feasible,
      design-choice flip, or engineering-meaningful objective regret.
      Temperature-error-only is not sufficient. — 2 unjustified
      commitments by the deployed point path; K-sample stress flipped
      architecture choice with +54% objective regret (G3-C)
- [x] All `definitely_safe` certificates must have zero false positives.
      — certified paths replay with 0 unjustified commitments (G2/G3-C)
- [x] Decision-directed refinement must reduce expensive physical
      power queries vs. fixed uniform refinement. — 77 vs 360 channels
      (−78.6%) at matched 2/2 correctness; width policy 58 vs 360 (G4)
- [x] Bounds verified by independent thermal backend (3D-ICE) or small
      LP/FEM oracle. — dual-backend witness replay PASS (G3-B)

## 6-step execution plan (per goal)

| Step | Action | Status |
|---|---|---|
| 1 | Set up content-bound audit harness | RESET; legacy harness is not claim-grade |
| 2 | Bind obtainable aggregate-power observations | NARROW G2 REGISTERED QUERY CLOSED |
| 3 | Build power-conserving synthetic stress pilot | CODE-FIXED; results not rerun |
| 4 | Run decision-flip audit | LEGACY RESULTS INVALIDATED; physical rerun required |
| 5 | Exact identifiability classifier + replayable certificates | CORRECTED G2 PATH MIGRATED; G3 FULL PASS (see gate ledger) |
| 6 | EDA-specific information acquisition | G4 PASS — adaptive acquisition beats fixed refinement (58/77 vs 360 channels) at matched correctness on physical NON_IDENTIFIABLE strata |

## Related work (avoid overlap)

- ThermoDSE 2026 (the framework we're extending) — has all DSE axes covered
- DiffChip (arXiv 2502.16633) — differentiable HotSpot surrogate
- Chiplet3D (arXiv 2607.09742) — thermal-aware 3D placement
- CHIPSIM (arXiv 2510.25958) — microsecond chiplet/NoI power trace
- THERMOS (arXiv 2508.10691) — thermal-aware multi-obj scheduling

## Backup directions (in priority order)

1. **Decision-Adequate NoP/Memory DSE** — easier data path
   (BookSim/NoCulator, no SAIF needed). 4-week paper.
2. **Partition-Schedule-Map decomposition conditions** — more theoretical
3. **Schedule-PDN Resonance Co-design** — high risk, narrow scope

## See also

- `RESEARCH_CONTRACT.md` — frozen problem, nonclaims, evidence matrix, and gate plan
- `audit/INTEGRITY_AUDIT_20260719.md` — claim/code/result consistency audit
- `results/README.md` — artifact disposition and reuse rules
- `evidence/G4_ACQUISITION_SCHEMA.md` — registered cross-query acquisition contract
