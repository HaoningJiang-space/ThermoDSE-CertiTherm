# CertiTherm: Spatial Power Identifiability for Chiplet DSE

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
2. **Certifiable method**: Use DNN mapping + PE activity envelope + power
   conservation to construct a fine-grained power uncertainty set, then
   compute peak temperature upper/lower bounds. Output one of three
   labels per design: `definitely_safe / definitely_infeasible / undecidable`.
3. **Decision-directed information acquisition**: For undecidable
   candidates, request finer subarray / placement / post-route power
   on demand. Not all designs pay the cost of detailed physical flow.

## Hard kill gates (pre-registered)

- [ ] Use real SAIF/VCD + post-placement instance power (no random
      Gaussian hotspots).
- [ ] At least 2 DNN families, 2 non-isomorphic architecture families,
      2 package regimes.
- [ ] Fine-grained power must cause reproducible false-feasible,
      design-choice flip, or engineering-meaningful objective regret.
      Temperature-error-only is not sufficient.
- [ ] All `definitely_safe` certificates must have zero false positives.
- [ ] Decision-directed refinement must reduce expensive physical
      power queries vs. fixed uniform refinement.
- [ ] Bounds verified by independent thermal backend (3D-ICE) or small
      LP/FEM oracle.

## 6-step execution plan (per goal)

| Step | Action | Status |
|---|---|---|
| 1 | Set up audit harness (use existing ThermoDSE evaluator as oracle) | TODO |
| 2 | Build uniform-power baseline (1 µW per instance) | TODO |
| 3 | Synthesize spatial power map (block-level variation) | TODO |
| 4 | Run decision-flip audit (uniform vs spatial winner comparison) | TODO |
| 5 | CertiTherm core: identifiability classifier + certificate logic | TODO |
| 6 | Acquisition: active refinement on undecidable candidates | TODO |

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

- `/home/ynwang/jhn/DSE/ThermoDSE/REPRODUCTION_RESULTS.md` — reproduction context
- `/home/ynwang/jhn/DSE/Chiplet_DSE_Projects_Research_20260717/` — earlier research notes
- `/home/ynwang/jhn/DSE/DSE_FirstPrinciples_Followup_20260717/` — first-principles verdicts