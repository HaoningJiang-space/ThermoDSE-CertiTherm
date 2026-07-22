# CertiTherm

CertiTherm synthesizes a physical observation contract that makes an
objective-ordered thermal chiplet-DSE decision identifiable. It proves the
least cost when exact closure is reached; otherwise it returns a replayable
certified contract, a valid lower bound, the remaining gap, and unresolved
counterexamples under one wall-clock budget.

The current method is **Decision-Sufficient Observation Synthesis (DSOS)**.
An ordered-decision decomposition reduces the global query exactly to
independent candidate-local minimum-cost hitting sets. Continuous LP oracles
search for zero-error decision collisions; a finite master accumulates the
resulting necessary cuts. The frozen Anytime-DSOS controller first obtains an
oracle-certified upper contract, then spends the remaining budget raising a
weak-duality lower bound. `OPTIMAL` additionally proves closure, while
`UNSYNTHESIZABLE` carries a cross-decision witness that the complete registered
channel library cannot separate. Numerical uncertainty is always
`UNRESOLVED`.

This is not ThermoDSE with another optimizer. ThermoDSE supplies workload and
architecture context; CertiTherm asks whether the information available at an
EDA stage is sufficient to justify the resulting architecture choice.

## Reproduce from a fresh clone

```bash
git clone --recurse-submodules git@github.com:HaoningJiang-space/ThermoDSE-CertiTherm.git
cd ThermoDSE-CertiTherm
make bootstrap
make check
```

`bootstrap` checks out the four pinned ThermoDSE, HotSpot, Rodinia, and SuperLU
gitlinks,
creates a pinned Python 3.8-compatible environment, and builds HotSpot from an
exported source tree. It never modifies a submodule.

Development and legacy-v1 commands are:

```bash
make reproduce-dev
make heldout
make package-dev package-heldout
```

The v3 claim-grade target is deliberately absent until every pre-open gate in
`docs/HELDOUT_PROTOCOL_V3.md` closes. This prevents a convenient command from
opening the split before the code, receipts, and report schema are frozen.

The optional custom FP64 CUDA backend builds all zero/impulse responses in one
batch while retaining CPU HotSpot as the independent truth backend:

```bash
make gpu-bootstrap
CUDA_VISIBLE_DEVICES=0 make gpu-check
CUDA_VISIBLE_DEVICES=0 make gpu-production-parity
CUDA_VISIBLE_DEVICES=0 make reproduce-dev-gpu
```

The GPU path is currently admitted only for steady `grid64-avg` and
`grid128-avg` models with fixed linear package physics. Leakage feedback,
natural-convection iteration, microchannels, unsupported mapping modes, and
non-convergence fail visibly; they are never silently approximated. See
`docs/GPU_HOTSPOT_ROUND.md` and `docs/GPU_HOTSPOT_TEST_PLAN.md` for the frozen
accuracy, launch, and evidence contract.
The claim-grade A800 result and artifact digests are recorded in
`docs/GPU_HOTSPOT_EVIDENCE.md`.

Generated evidence is written outside Git under `artifacts/` as
TSV/CSV/NPZ/Markdown. No secret, machine-specific path, fitted power scale, or
3D-ICE conversion is part of the method.

Each workload's candidates are ordered by its captured ThermoDSE
`latency × energy / die_yield` value before thermal feasibility is applied.
The registered observation library spans module, chiplet, placement-region,
and post-route per-block power reports with frozen non-unit EDA-stage costs;
the initial coarse observation reveals total power only.

## Registered thermal family

- HotSpot block;
- HotSpot grid 64×64, block-average mapping;
- HotSpot grid 128×128, block-average mapping.

Grid max mapping is excluded from the LP because max-before-superposition is
nonlinear. Grid 256×256 is calibration-only. Operators are built by zero-power and
one-watt impulses and bound to the binary/config/floorplan/material digests.
The exported build tightens HotSpot's grid steady-state convergence threshold
from `1e-6` to `1e-7` and records that patch; this changes numerical
convergence, not the thermal equations or stack.
The three models form one fail-closed upper envelope: a candidate is SAFE
only when every registered model is below the limit. Per-model placed
decisions are still archived so disagreement remains visible, but power
channels are never asked to identify an unobservable simulator label.

## Code map

- `CertiTherm/core.py` — validated power, thermal, action, and certificate data;
- `CertiTherm/synthesis.py` — exact and proof-carrying anytime DSOS core;
- `CertiTherm/policies.py` — matched fixed, width, and dual-price baselines;
- `CertiTherm/hotspot.py` — official HotSpot operator construction;
- `CertiTherm/cli.py` — NPZ/TSV command line;
- `docs/INFORMATION_THEORETIC_METHOD.md` — objective and proof contract;
- `docs/SPECTRAL_DECISION_ENVELOPE.md` — frequency/modal observability audit;
- `docs/MEASUREMENT_LIBRARY.md` — obtainable EDA channels and costs;
- `docs/THERMAL_ERROR_CONTRACT.md` — direct-replay error gate;
- `docs/HELDOUT_PROTOCOL_V3.md` — current frozen 4×3×3 evaluation.

## Evidence status

The pre-DSOS G1–G4 prototype is preserved at Git tag
`legacy-g1-g4-archived` and in the server-side evidence archive. Its 3D-ICE
`POWER_SCALE=16` replay and fixed-vs-adaptive G4 headline are withdrawn from
the active claim path. Historical reports under `CertiTherm/results/` and
`CertiTherm/audit/` are retained only as an audit trail; they are not current
results.

The v3 non-thermal precheck passed all 12 workload/architecture combinations
without invoking HotSpot; the primary architecture set remains unchanged.
No held-out thermal or policy result is claimed until the still-unopened v3
protocol completes from a fresh clone and is archived unchanged.
