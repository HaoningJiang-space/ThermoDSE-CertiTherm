# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

`ThermoDSE-CertiTherm` binds two git submodules under one research project:

- `ThermoDSE/` — thermal-aware chiplet DNN accelerator DSE (search/optimization). Treated
  as a **frozen, pinned dependency** here — it supplies architecture candidates and
  latency/energy/yield numbers, but is not itself modified by CertiTherm work.
- `HotSpot/` — official HotSpot thermal simulator source, built locally from an exported
  tree with two numerical patches (see `patches/`), never modified in place.

`CertiTherm/` is the actual research code in this repo: **Decision-Sufficient Observation
Synthesis (DSOS)**. It asks whether the physical observations obtainable at an EDA design
stage are sufficient to certify a thermal-feasibility-driven chiplet architecture decision,
as opposed to ThermoDSE's job of finding a good architecture in the first place.

This repo is one of several sibling repos in a larger untracked workspace;
see the parent workspace's `CLAUDE.md` for cross-repo rules
(remote-execution mandate, provenance rules, "never git add across repo boundaries"). Those
rules apply here too — this file only adds detail specific to `ThermoDSE-CertiTherm`.

## Setup and commands

Fresh clone bootstrap (also what CI in `.github/workflows/fresh-clone.yml` runs):

```bash
git clone --recurse-submodules git@github.com:HaoningJiang-space/ThermoDSE-CertiTherm.git
cd ThermoDSE-CertiTherm
make bootstrap   # pins a .venv, installs requirements.lock, builds HotSpot from patched export
make check       # test + hotspot-smoke + git diff --check + submodule cleanliness
```

`make bootstrap` creates `.venv` with the explicit `python3.8` interpreter and
`requirements.lock` (numpy/scipy/pytest/tabulate/matplotlib pinned for Python
3.8), exports `HotSpot/` HEAD into
`.build/hotspot`, applies `patches/hotspot-output-precision.patch` and
`patches/hotspot-grid-convergence.patch`, builds the `hotspot` binary, and records its
SHA-256. It never modifies either submodule in place.

Tests (from repo root; `CertiTherm/tests/conftest.py` puts `CertiTherm/exact`,
`CertiTherm/audit`, `CertiTherm/robust_dse` on `sys.path` so no manual `PYTHONPATH` is
needed):

```bash
make test                                                   # == python -m pytest -q CertiTherm/tests
.venv/bin/python -m pytest -q CertiTherm/tests
.venv/bin/python -m pytest -q CertiTherm/tests/test_synthesis.py::test_name_here
```

`make hotspot-smoke` runs the official HotSpot `example1` case through the freshly built
binary as a non-Python sanity check. `pytest.ini` sets `testpaths = CertiTherm/tests`.

Claim-grade experiment drivers (large, run on `moe-server`, not locally — see below):

```bash
make reproduce-dev    # python -m CertiTherm.experiments --split dev --output artifacts/dev
make heldout          # python -m CertiTherm.experiments --split heldout --output artifacts/heldout --frozen
make package-dev package-heldout   # tar + sha256 the artifacts/ bundles for release
```

The pre-open v3 rehearsal is intentionally separate from claim-grade held-out
execution:

```bash
CUDA_VISIBLE_DEVICES=0 make v3-dev-rehearsal
```

It runs the v3 controller on the development registry and refuses to reuse an
existing output directory. There is no `heldout-v3` target until the rehearsal
and artifact audit close the remaining gates in `docs/HELDOUT_PROTOCOL_V3.md`.

### Remote execution

Per the parent workspace's execution authority, HotSpot builds, `make bootstrap`,
`make check`, `make reproduce-dev`, and `make heldout` are claim-grade / native-build work
and must run on `moe-server` from a clean worktree at a committed revision, not locally.
Locally you may edit files, read/inspect, and run lightweight static checks.

## Architecture

### `CertiTherm/` — the active DSOS pipeline

Everything is `@dataclass(frozen=True)` with `__post_init__` validation (`CertiTherm/core.py`
defines `PowerPolytope`, `ThermalFamily`, `MeasurementAction`, `CandidateSpace`,
`WorldPair`/`QueryWorldPair`, `ObservationPlan`/`QueryObservationPlan`). Pipeline:

```
CertiTherm/hotspot.py    build_family()     → ThermalFamily (registered HotSpot operators, sha256-bound)
CertiTherm/measurements.py                  → obtainable module/chiplet/region/post-route action library
CertiTherm/synthesis.py  synthesize_ordered_query() → ObservationPlan (MILP hitting-set + LP separation oracle)
CertiTherm/policies.py                      → matched fixed / width / dual-price baselines, same oracle
CertiTherm/spectral.py                      → interpretability-only spectral/mode analysis (never the certificate)
CertiTherm/experiments.py                   → end-to-end ThermoDSE→HotSpot→DSOS driver, resumable NPZ evidence
CertiTherm/cli.py                           → `build-family` / `synthesize` subcommands over NPZ/TSV
CertiTherm/adaptive.py                      → exact minimax Bellman recurrence, finite-alphabet calibration only
CertiTherm/trace_runner.py                  → name-aligned ThermoDSE ptrace → HotSpot wrapper (no positional truncation)
```

Read `docs/INFORMATION_THEORETIC_METHOD.md` before touching `synthesis.py` — it states the
three theorems (confusability graph = hitting set, ordered-decision decomposition,
constraint-generation exactness) that the implementation must stay faithful to, and the
exact vocabulary (`OPTIMAL`, `UNSYNTHESIZABLE`, `UNRESOLVED`) that status fields must use.

**Fail-closed status contract** (applies throughout `CertiTherm/`): a query result is one of
`CERTIFIED`/`OPTIMAL` (proof), `NON_IDENTIFIABLE`/`UNSYNTHESIZABLE` (witness/counterexample),
or `UNRESOLVED` (solver failure, timeout, missing compactness, invalid input) — **never** a
fabricated feasible/infeasible verdict. `CertiTherm/experiments.py` enforces a
`QUERY_METHOD_TIMEOUT_S = 1800` per-method budget; a timeout is archived, not silently
dropped or converted into a certificate.

**Thermal model family is HotSpot-only and linear**: `block`, `grid64-avg`, `grid128-avg`
(block-average mapping, chosen because it is linear in grid-cell temperature; HotSpot's
`max` grid mapping is nonlinear and is deliberately excluded from the LP). `grid256` is
calibration-only. `THERMAL_LIMIT_K = 330.0` in `experiments.py` is the frozen DSOS limit —
do not confuse it with the unrelated `348 K` / `300 mm²` defaults baked into ThermoDSE's own
`tools/`/`rl_opt/` CLI flags, which are a different, unsupported convention from the
upstream submodule.

A frozen `0.01 K` two-sided model-error band (`docs/THERMAL_ERROR_CONTRACT.md`) is folded
into every SAFE/REJECT LP, one-sidedly (error only ever makes certification harder, never
easier). Getting the sign of that inequality wrong was an actual regression caught before
the method freeze — see the contract doc before editing anything in the SAFE/REJECT LP
construction in `synthesis.py`.

### `exact/`, `results/`, `audit/`, `theory/`, `robust_dse/` — archived pre-DSOS work

These directories are the **pre-DSOS G1–G4 prototype** (`decide.py`, `decision_query.py`,
`linear_oracle.py`, `run_g2_query.py`, the `robust_dse` sampled-stress baseline, etc.). Per
`CertiTherm/README.md` and the tag `legacy-g1-g4-archived`, they do not support current
HotSpot-family or information-theoretic claims and should be treated as read-only audit
trail, not as a base to extend. `CertiTherm/tests/conftest.py` still adds `exact/`, `audit/`,
`robust_dse/` to `sys.path` because a handful of tests (`test_decisive_oracle.py`,
`test_g2_soundness.py`, `test_g3_baselines.py`, `test_robust_target.py`,
`test_spatial_power_injection.py`) still exercise that legacy code as regression coverage —
this is intentional, not dead configuration to clean up. Machine-specific import paths
from the prototype have been removed; regression imports resolve from the repository.

### Research governance — read before changing method or claims

- `README.md` is the current top-level statement of the method and code map.
- `docs/INFORMATION_THEORETIC_METHOD.md` — DSOS objective, theorems, proof contract.
- `docs/MEASUREMENT_LIBRARY.md` — the frozen obtainable-action registry and cost model.
- `docs/THERMAL_ERROR_CONTRACT.md` — the 0.01 K HotSpot linearization error band.
- `docs/SPECTRAL_DECISION_ENVELOPE.md` — spectral/mode interpretability tooling (not a certificate).
- `docs/HELDOUT_PROTOCOL.md` — the frozen `method-freeze-v1` dev/held-out split, workloads,
  architectures, and pass criteria; **do not** run or reinterpret held-out cases outside this
  protocol, and any post-freeze tuning requires a new freeze ID and a new split.
- `CertiTherm/RESEARCH_CONTRACT.md` and `CertiTherm/INSIGHTS.md` are **archived** (superseded
  2026-07-21 by the docs above) — useful for history of what was tried and killed (e.g. the
  3D-ICE `POWER_SCALE=16` equivalence claim, the K-sample "worst-case" baseline), not as
  current guidance.
- `docs/IMPLEMENTATION_AUDIT_20260721.md` records the most recent reproducibility audit
  (fresh clone, submodule pins, 54/54 tests) and the corrections it made — read it to see
  what was already fixed rather than re-discovering the same issues.

Generated evidence (`artifacts/`, `.build/`, `.venv/`) is gitignored and lives outside the
tracked tree; only compact TSV/CSV/NPZ/Markdown manifests under `experiments/` and
`CertiTherm/results*` are meant to be committed.

## Conventions

- Commit subjects are short imperative statements describing the exact semantic change
  (e.g. "Decompose ordered DSOS into exact local optima", "Archive timed-out query methods
  fail closed") — no generic "update"/"fix stuff" messages, and no bundling unrelated changes.
- `git-push-haoning` (`.codex/skills/git-push-haoning/`) is the canonical publish workflow:
  work on `round/<gate>-<topic>` branches off `master`, never commit directly to `master`,
  run `scripts/prepush_guard.sh origin` before pushing, and keep the `moe` remote
  credential-free and separate from public GitHub publication on `origin`.
- Units: HotSpot temperatures are Kelvin (`_k` suffix in field names), power is watts
  (`_w`), matching the sibling `ChipletThermalEnvelope` project's SI-suffix convention.
- `origin` is a **public** GitHub repo. The initial commit had live tokens in
  `.claude/settings.json` (a GitHub PAT and an Anthropic/proxy token). Both were confirmed
  revoked at the source, then the entire history was rewritten with `git-filter-repo` and
  force-pushed once (`0ff5f96` in the current log is itself the post-rewrite hash) — the
  project's only force-push to date, done only after archiving and re-verifying the
  pre-rewrite state. `origin`'s push URL now uses a dedicated deploy key (`github-certitherm`
  host alias). Never re-add `.claude/settings.json` (or any credential-bearing file) to the
  index. If a token-shaped string shows up in chat, refuse to store or embed it and tell the
  user to verify revocation at the provider — this has already happened at least twice with
  the same leaked PAT being pasted again well after it was supposedly dead.
  See `.claude/skills/certitherm-git-haoning/SKILL.md` for the runnable incident playbook and
  `.claude/skills/moe-server-remote/SKILL.md` for the remote-execution workflow.
