# DSOS Implementation Audit — 2026-07-21

## Outcome

The active code now contains an independent algorithm rather than a G4
attachment:

- query-level zero-error decision-confusability is the optimization object;
- a MILP synthesizes the minimum-cost batch observation set;
- continuous LP separation generates only necessary cross-decision cuts;
- exact results expose primal cost, MILP bound, LP-relaxation bound, and gap;
- unseparable same-power model flips return a witness;
- dual-price InfoCertGain, width, and fixed order use the same query oracle;
- fixed and width baselines stop at the first universal certificate.

The theorem is global only relative to the registered finite action library,
power polytopes, HotSpot model family, costs, margins, and tolerances. It is
not a global optimum over arbitrary sensors. This qualification must remain
next to every “theoretical limit” statement.

## Reproducibility checks completed

Fresh clone `12b8ef0` on moe-server:

- HotSpot submodule: `f18831e48cef5d62580585cca0d7fab6c71bc3cc`;
- ThermoDSE submodule: `51c150694457f4c6067703000ea50ff1eb9842c9`;
- pinned user-space Python bootstrap succeeds without sudo;
- HotSpot is built from an exported tree; both submodules stay clean;
- 54/54 repository tests pass;
- official HotSpot example smoke test passes;
- three DSOS/strategy tests pass after the residual-dual correction.

No local test or physical experiment was used.

Post-audit correction: HotSpot grid `max` mapping was rejected because a
maximum taken before impulse superposition is nonlinear. The registered grid
operators use block-average mapping, which preserves linearity. An
output-format-only patch raises emitted temperature precision from two to ten
decimal places; the resulting binary digest is the registered executable.
The first grid64 replay exposed a 0.00327 K numerical superposition residual.
Development therefore froze a 0.01 K two-sided per-model error band, inserted
it into every safe/unsafe LP, and replays all development powers. Held-out may
reject this bound but may not enlarge it.

## Scientific corrections

1. The active path is HotSpot-only. The uncalibrated
   `POWER_SCALE=16` 3D-ICE adapter and equivalence claim were deleted.
2. Ptrace alignment is by exact floorplan block name. Missing blocks or row
   mismatch abort; there is no positional truncation, padding, or relabeling.
3. The old fixed baseline was replaced with matched sequential early stop.
4. Old G1–G4 code is retained at tag `legacy-g1-g4-archived`; historical
   reports now carry explicit non-evidence banners.
5. Transformer exposed a pinned ThermoDSE API defect. The runtime shim restores
   only the one-byte default already used by base/Conv
   `total_filter_size`; it does not change formulas or the submodule.

## Open gates

- The development operator build and DSOS matrix must complete and be archived.
- Only after development is closed may `method-freeze-v1` held-out cases run.
- A held-out result is positive only under the predeclared criteria in
  `HELDOUT_PROTOCOL.md`; disagreement and negative baselines are retained.
- The current exact result is the **batch** zero-error limit. An adaptive
  theoretical limit needs a finite/quantized observation alphabet and an
  exact minimax Bellman tree. It should be a separate theorem/experiment, not
  silently conflated with DSOS.

## Recommended paper claim

“DSOS computes a globally minimum-cost non-adaptive observation contract for
a registered EDA measurement library, or returns a cross-decision
non-identifiability witness.”

Avoid “maximum information” or “the information-theoretic limit” without the
batch/library qualification.
