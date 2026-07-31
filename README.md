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

### The chiplet-count decision is not identifiable from the objective

The current headline. Full statement, with scope and the two withdrawn predecessors, in
`docs/DECISION_SUFFICIENT_INSTRUMENTATION.md`.

**A refinement-monotone yield aggregate cannot price chiplet count.** If the yield term of a DSE
objective is an area-weighted arithmetic mean `sum_i (a_i/A) Y(a_i + c)` of a strictly decreasing
per-die yield, then splitting any die replaces one value by two strictly larger ones carrying the
same total weight, so the aggregate rises under *every* refinement at *every* parameter value. Such a
term can only ever argue for cutting further. This is a property of the aggregation, not of one tool,
and it is the thing to check in any thermal-aware chiplet DSE reporting a scalar yield. It is
executed against the implementation in `CertiTherm/tests/test_yield_composition.py`, together with
the contrast that makes it informative: the all-dies-good product falls under the same refinement,
and a bonded aggregate falls geometrically in the count.

Measured on **30 freshly generated points** — 6 tile grids x cuts `1/2/4` x 2 workloads, 15
architectures surviving; 3 were refused by the frozen 0.01 K linearisation-error contract, which is
the fail-closed path working. Die geometry is recorded in every capture so all compositions are
exact, with a fatal self-check that the recomputed mean reproduces the evaluator's own number.

In **10 of 10** decision groups the reported yield rises monotonically with the die count — up to
**+18.6 percentage points** — while the all-dies-good product is flat or falling, at most **+0.4**.
Carried into the objective the two order the cut *oppositely*: the product prefers the monolithic die
in 10 of 10 groups, the evaluator's mean prefers a cut design in 8 of 10. **10 of 10 groups change
their preferred chiplet count with the composition rule.**

The decision also sits on a **phase boundary in a real manufacturing parameter**. The `n=2` versus
`n=4` choice ties at a bonding yield in **0.9764 – 0.9997**, and the 0.99 an organic-substrate cost
model registers falls *inside* that range — so at a realistic bonding yield some grids go one way and
some the other, and a one-percent change in the assumption moves them.

**The thermal robustness radii do not depend on any of that.** `tau*` (uniform total-power
under-prediction) and the relocation radius come from the power map and the linear HotSpot operator
alone — no yield model, no cost model, no latency. The radius rises monotonically with the die count
in **10 of 10** groups and selects the finest cut unanimously, under no manufacturing assumption.
It agrees with the evaluator's own choice in 8 of 10; the claim is not that the objective is always
wrong, but that its answer is not determined by the physics while the radius's is.

### What observation the decision actually needs, and under which uncertainty set

Three uncertainty sets are in play and **containment transfers asymmetrically**. From a SUBSET of the
true set, existence and lower bounds travel up: a REJECT map exists, a coarse-blind pair exists, the
cost is at least `c`. From a SUPERSET, universal safety and upper bounds travel down: no REJECT map
exists, no measurement is needed. Getting that backwards withdrew two earlier headlines from this
project — a certified bound of 1440 quoted at "5 % relocation" that was computed on the superset, and
a "no measurement needed" read off the inscribed subset. Both are recorded rather than deleted.

Under bulk relocation `|p - q|_1 <= 2 b Q`, the first tier needs only reachability, which has a
**closed form** — no solver, no approximation, no transfer argument:

| candidate | workload | `beta*_safe` (feasibility) | `beta*_reject` (identifiability) |
| --- | --- | --- | --- |
| arch_a / arch_b / arch_c | resnet50 | 4.090 / 2.117 / 3.994 % | 4.133 / 2.144 / 4.035 % |
| arch_a / arch_b / arch_c | transformer | 1.519 / **0.493** / 1.477 % | 1.540 / 0.548 / 1.497 % |

Two radii, not one, because **SAFE is not the complement of REJECT**: the registered rows leave a
`2 x margin` band in which a map is neither. Below `beta*_safe` every admissible map is robustly
SAFE; below `beta*_reject` no SAFE/REJECT pair exists to tell apart, so the minimum-cost observation
is zero. Quoting the second while meaning the first was a real error here, caught in review.
Under independent per-block deviation the bracket is two-sided: nothing needed below
`0.196 – 3.376 %`, and post-route per-block extraction provably required at `5 %` (`10 %` for one
instance), with the interval between reported `UNRESOLVED` rather than as a coarse-sufficient window
— that middle tier is defined but was never established on this registry.

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
- `docs/DECISION_SUFFICIENT_INSTRUMENTATION.md` — the current statement: the
  refinement-monotonicity proposition, the composition phase boundary, the
  containment-transfer rule, and what is established per uncertainty model;
- `docs/THERMAL_ROBUSTNESS_RADII.md` — `tau*`, `S*`, the yield coupling, and
  the corrections that renamed the two radii apart;
- `docs/BLIND_DIRECTION_BOUND.md` — the blind-direction bound, its trajectory,
  and the two withdrawals of its headline.

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

Everything above is a DEVELOPMENT-split result, on the registry plus freshly
generated development points. The frozen held-out split was not opened;
opening it to enlarge a sample is what the protocol exists to prevent. A
design-space statement here is a finite-sample statement about the points
generated, not about the parameterised space.

Certified means each counted pair carries a witness repaired to exact rational
polytope feasibility and re-proved with zero slack, and the cover search runs
to proven optimality or refuses. It does not mean held-out. One thermal family
from one linear HotSpot configuration; power maps from a ThermoDSE evaluator
with documented defects (`e_tot` subtracts compute energy, NoP energy is
smeared over the interposer, HotSpot leakage feedback is disabled), which
affect the energy-delay factor under every yield composition equally and are
not corrected here.

Two headline numbers were withdrawn this round and both withdrawals are kept
in the tree rather than deleted: a certified bound quoted under an uncertainty
set it was not computed on, and a safety conclusion carried from a subset to
the set containing it. The containment-transfer table above exists because of
them, and three independent implementations of the relocation radius — a box
greedy, a lifted LP, an inverted transfer greedy — are now required by test to
agree in the order their containments force.

The upper bound the blind-direction work compares against is a greedy cover
over discovered cuts — a feasible plan found by one search, not a proven
optimum.
