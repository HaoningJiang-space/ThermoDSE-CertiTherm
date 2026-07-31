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

### Certified thermal-robustness radii, and what they cost in yield

The current headline result. Thermal-aware chiplet DSE minimises EDYP = latency x energy / yield
subject to a peak-temperature constraint, and that constraint is a pass/fail test on the NOMINAL
power map — nothing in the objective charges for spending the thermal margin. Two computable radii
say how much power-model error the decision survives:

- **`tau*`** — uniform total-power under-prediction, closed form, no solver;
- **`S*`** — redistribution at a fixed total, `min_j Delta_j / H_j`: a nominal reject slack divided
  by a redistribution sensitivity, so it is not a re-parameterisation of the peak.

On the transformer workload the EDYP-optimal architecture tolerates a **9.0%** total-power
under-prediction where the design it outranks tolerates **63.6%**. Declaring a 10% power-model
accuracy — inside what an architecture-stage model is normally credited with — makes the selected
design not robustly feasible: the robust choice becomes a different architecture at **+32.1% EDYP**,
**4.00 K** less worst-case peak temperature, and a **higher yield** (0.953 against 0.927). On
resnet50 there is no disagreement up to 30%; the effect is workload-dependent.

Yield and temperature are coupled through die area — the registered model
`Y(A) = (1 + A D0/alpha)^(-alpha)` falls with area while power density and peak temperature fall as
area grows — and EDYP multiplies them. See `docs/THERMAL_ROBUSTNESS_RADII.md`, including what the
result does NOT say: the radii rank identically to the nominal peak on all 18 dev instances, so
"DSE selects on the wrong statistic" is not supported by this registry.

### Blind-direction certificates

The strongest current result comes from a structural family of cuts rather
than from accumulating generic ones. Every registered action is a 0/1
indicator over a group of blocks, so two blocks whose coefficient COLUMNS
agree in every multi-block action are indistinguishable along
`delta = t (e_b - e_c)`: no module, chiplet or regional report can see that
power move, while it does move the peak temperature. Such a collision is
separable only by a single-block action on b or on c.

Two consequences make this different in kind from cut accumulation. Hitting
all such cuts inside one cell of the common refinement is a VERTEX COVER,
whose minimum weight is computed exactly rather than approached
logarithmically; and cells partition the blocks, so their minima ADD.

Measured across the full 18-instance dev registry, certified lower bounds run
**864 to 1320** against a previously reported 22.8–88.3 on the headline
instance.

**Read that as conditional on the uncertainty set, not as a physical
requirement.** Under per-block activity-bounded redistribution the reject
floor is unreachable and the same certified requirement is **zero**. Both
numbers are correct for their own set, and the pair is the result: the
observation requirement is a property of the design AND the power-model
uncertainty assumed, which is why the radii above come first.
`docs/BLIND_DIRECTION_BOUND.md` has the numbers, the search bug that changed
them by 95%, and the negative results — the cover is necessary but NOT
sufficient, and a fix that would have removed 98% of the remaining obstacles
was rejected as fail-open.

**Read the Scope section of that document before quoting any number.** The
registered uncertainty set admits every nonnegative redistribution preserving
the workload total; `measurements.activity_bounded_power_space` narrows it to
a defensible activity range, and how the bound behaves under that narrowing is
what decides whether the result is a property of the design or of the
abstraction.

## Reproduce from a fresh clone

```bash
git clone --recurse-submodules git@github.com:HaoningJiang-space/ThermoDSE-CertiTherm.git
cd ThermoDSE-CertiTherm
make bootstrap
make check
```

`bootstrap` checks out the four pinned ThermoDSE, HotSpot, Rodinia, and SuperLU
gitlinks, creates the locked Python 3.8 environment, and builds HotSpot from an
exported source tree. It invokes `python3.8` by default even when an interactive
shell has activated another Python (for example, Conda); override
`BOOTSTRAP_PYTHON` only with another Python 3.8 executable. It never modifies a
submodule.

Development and legacy-v1 commands are:

```bash
make reproduce-dev
make heldout
make package-dev package-heldout
```

The non-claim v3 development rehearsal has one reproducible entry point:

```bash
CUDA_VISIBLE_DEVICES=0 make v3-dev-rehearsal
```

It builds and checks the GPU backend, then runs `method-freeze-v3.1` on the
existing development registry under the frozen 1800-second query budget. It writes
`split=dev_v3`, `registry_split=dev`, and a fixed full result schema, so it
cannot be confused with either v1 evidence or the unopened v3 held-out split.
The command refuses an existing output directory. The v3 **held-out** target
remains deliberately absent until every pre-open gate in
`docs/HELDOUT_PROTOCOL_V3.md` closes.

The optional custom FP64 CUDA backend builds all zero/impulse responses in one
batch while retaining CPU HotSpot as the independent truth backend:

```bash
make gpu-bootstrap
CUDA_VISIBLE_DEVICES=0 make gpu-check
CUDA_VISIBLE_DEVICES=0 make gpu-production-parity
CUDA_VISIBLE_DEVICES=0 make reproduce-dev-gpu
```

The separate CUDA collision proposer is retained as a reproducible negative
result and is not used by v3.1; see `docs/GPU_COLLISION_NEGATIVE_RESULT.md`.

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

Independent workload/package queries use one persistent spawn pool (three
workers for frozen v3). Query-internal algorithms and timers remain serial;
this avoids the previously measured cost of constructing a process pool in
every separation iteration. The worker count and scheduling mode are bound
into each run receipt.
Every HiGHS LP/MILP call also receives the remaining wall-clock budget as its
native `time_limit`. The Python alarm remains a fail-closed fallback, but a
long C++ presolve can no longer run past the method deadline merely because it
has not returned control to Python.

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
Every cached ThermoDSE capture and HotSpot operator carries a TSV sidecar that
also binds its builder-source bundle, registry inputs, submodule revision, and
artifact/calibration SHA-256. Missing or mismatched sidecars force a rebuild;
filename-only cache reuse is forbidden.
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
- `CertiTherm/blind_direction_cuts.py` — structural two-action cuts, forced
  vertices, and the additive vertex-cover lower bound;
- `CertiTherm/measurements.py` — obtainable action library and the registered
  and activity-bounded uncertainty sets;
- `CertiTherm/query_evidence.py` — witness replay and every coordinated result
  table;
- `CertiTherm/cache_receipts.py` — the false-cache-hit guard;
- `CertiTherm/policies.py` — matched fixed, width, and dual-price baselines;
- `CertiTherm/hotspot.py` — official HotSpot operator construction;
- `CertiTherm/cli.py` — NPZ/TSV command line;
- `docs/INFORMATION_THEORETIC_METHOD.md` — objective and proof contract;
- `docs/SPECTRAL_DECISION_ENVELOPE.md` — frequency/modal observability audit;
- `docs/MEASUREMENT_LIBRARY.md` — obtainable EDA channels and costs;
- `docs/THERMAL_ERROR_CONTRACT.md` — direct-replay error gate;
- `docs/HELDOUT_PROTOCOL_V3.md` — current frozen 4×3×3 evaluation;
- `docs/BLIND_DIRECTION_BOUND.md` — the blind-direction bound, its trajectory,
  and its negative results;
- `docs/THERMAL_ROBUSTNESS_RADII.md` — `tau*`, `S*`, the yield coupling, and
  the selection change they produce.

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

The blind-direction bounds are DEVELOPMENT-split results. They are certified
in the sense that every counted pair carries a witness repaired to exact
rational polytope feasibility and re-proved with zero slack, and the cover
search runs to proven optimality or refuses. They are not held-out, they use
one thermal family from one linear HotSpot configuration, and the power maps
come from a ThermoDSE evaluator with documented defects recorded in the parent
workspace's CLAUDE.md. The certified upper bound they are compared against is
a greedy cover over discovered cuts — a feasible plan found by one search, not
a proven optimum.
