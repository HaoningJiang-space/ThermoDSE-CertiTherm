# CertiTherm G3 Pilot Retraction

**Date:** 2026-07-20

**Status:** `LEGACY_INVALIDATED_FOR_CLAIMS`

**Gate verdict (updated 2026-07-20):** this document retracts the legacy
pilot only. The replacement content-bound real 2×2×2 suite has since passed
G3-A/B/C; the authoritative gate ledger is
`results/G3_REAL_2x2x2_CONSOLIDATED_REPORT.md`.

The former headline, `5/8 (62.5%) flip from uniform SAFE to spatial
NON_IDENTIFIABLE`, is withdrawn. The committed JSON is retained only for
forensic comparison with commit `b7b08ee`; it must not be cited, plotted, or
used in a paper table.

## Why the result is invalid

1. **The DNN axis was relabeled aggregate data.** The runner read the aggregate
   ptrace for all workloads and assigned it to whichever DNN name was active.
   It did not produce independent ResNet and Transformer power evidence.
2. **The package axis reused one operator.** Thermal matrices were cached only
   by architecture, loaded before changing `s_sink`, and therefore shared
   across the standard/enhanced labels.
3. **The baseline was not uniform or point-valued.** The alleged uniform path
   admitted arbitrary total-power-preserving redistribution with a `1.5x`
   component cap. The spatial path merely enlarged that nested set to `5x`.
4. **No architecture flip was evaluated.** The runner classified one
   candidate's thermal interval and never executed the imported
   `decide_architecture_query` over a shared candidate pool.
5. **The denominator was not eight independent physical cases.** Repeated
   values follow directly from the reused workload and package inputs.
6. **The written report was internally inconsistent.** Its table showed four
   3x3 transitions while the prose claimed three.

Consequently, the old table demonstrates only that loosening per-component
bounds can widen a candidate's temperature interval. It does not establish a
uniform-DSE error rate, DNN generality, package generality, cooling
ineffectiveness, or architecture-choice disagreement.

## Replacement protocol

`CertiTherm/exact/g3_full_empirical.py` is now a registered suite runner rather
than a mutable experiment generator. A valid suite must provide:

- distinct workload-specific placed-power and point-estimate files;
- distinct package-specific response matrices and thermal-config digests;
- the same architecture candidate pool in every workload/package stratum;
- a point estimate and a placed reference that both replay inside the spatial
  observation domain;
- complete point, placed-reference, and spatial
  `decide_architecture_query` artifacts with fresh replay receipts.

The runner reports `point_commitment_not_identifiable` and
`point_vs_placed_disagreement` counts. It deliberately does not call either an
error rate without an independently registered physical oracle.

## Remaining evidence before G3 can close

- real workload-specific SAIF/VCD plus post-placement instance power;
- two structurally distinct architecture families in one shared decision
  query, not two isolated candidate checks;
- two content-distinct package operators with frozen boundary conditions;
- original ThermoDSE point-estimate provenance;
- sampled-stress, component-box, and fixed-refinement baselines;
- independent thermal replay and runtime/RSS/certificate-size reporting.

No new experimental number is reported here.
