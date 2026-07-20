# CertiTherm

CertiTherm synthesizes the least-cost physical observation contract needed to
make an objective-ordered thermal chiplet-DSE decision identifiable.

The current method is **Decision-Sufficient Observation Synthesis (DSOS)**:
a minimum-cost hitting-set MILP and a continuous LP counterexample oracle
solve the zero-error decision-information problem. An `OPTIMAL` result carries
the selected channels, exact cost, MILP lower bound, LP-relaxation bound, and
zero gap. `UNSYNTHESIZABLE` carries a cross-decision witness that the complete
registered channel library cannot separate. Numerical uncertainty is always
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

`bootstrap` checks out the pinned ThermoDSE and official HotSpot gitlinks,
creates a pinned Python 3.8-compatible environment, and builds HotSpot from an
exported source tree. It never modifies either submodule.

Claim-grade runs are executed on moe-server:

```bash
make reproduce-dev
make heldout
```

Generated evidence is written outside Git under `artifacts/` as
TSV/CSV/NPZ/Markdown. No secret, machine-specific path, fitted power scale, or
3D-ICE conversion is part of the method.

## Registered thermal family

- HotSpot block;
- HotSpot grid 64×64, block-average mapping;
- HotSpot grid 128×128, block-average mapping.

Grid max mapping is excluded from the LP because max-before-superposition is
nonlinear. Grid 256×256 is calibration-only. Operators are built by zero-power and
one-watt impulses and bound to the binary/config/floorplan/material digests.
Cross-model disagreement at identical power is reported explicitly as
`MODEL_NON_IDENTIFIABLE`.

## Code map

- `CertiTherm/core.py` — validated power, thermal, action, and certificate data;
- `CertiTherm/synthesis.py` — exact cross-candidate DSOS;
- `CertiTherm/policies.py` — matched fixed, width, and dual-price baselines;
- `CertiTherm/hotspot.py` — official HotSpot operator construction;
- `CertiTherm/cli.py` — NPZ/TSV command line;
- `docs/INFORMATION_THEORETIC_METHOD.md` — objective and proof contract;
- `docs/HELDOUT_PROTOCOL.md` — frozen 4×3×3 evaluation.

## Evidence status

The pre-DSOS G1–G4 prototype is preserved at Git tag
`legacy-g1-g4-archived` and in the server-side evidence archive. Its 3D-ICE
`POWER_SCALE=16` replay and fixed-vs-adaptive G4 headline are withdrawn from
the active claim path. Historical reports under `CertiTherm/results/` and
`CertiTherm/audit/` are retained only as an audit trail; they are not current
results.

No held-out performance result is claimed until the frozen protocol completes
from a fresh clone and is archived unchanged.
