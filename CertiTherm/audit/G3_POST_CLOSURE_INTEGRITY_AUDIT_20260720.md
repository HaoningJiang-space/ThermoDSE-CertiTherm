# G3 post-closure integrity audit — 2026-07-20

## Audit status

- Mode: claim, numeric, reproducibility, and gate-consistency audit
- Audited revision: `898df519f634d8f2a04c2773f01be27d7f20292e`
- Source: repository root at the audited commit (machine path intentionally omitted)
- Independent execution host: `moe-server` (`hpclab03`)
- Decision: **the committed G3 semantic matrix replays, but `G3 full gate: CLOSED` is not yet supported**
- Recommended public state: **`G3 semantic/breadth matrix: PASS; G3 full systems/independent-physics gate: OPEN`**

This audit does not assert that the previously reported dual-backend result was
fabricated. It finds that the result is not recoverable or independently
verifiable from the current repository and server state, and that the present
3D-ICE adapter does not yet implement a content-equivalent package model.

## Artifacts and code checked

- `CertiTherm/RESEARCH_CONTRACT.md`
- `CertiTherm/README.md`
- `CertiTherm/results/G3_FULL_REPORT.md`
- `CertiTherm/results/G3_REAL_2x2x2_CONSOLIDATED_REPORT.md`
- `CertiTherm/evidence/g3_2x2x2_real_bundle/`
- `CertiTherm/exact/g3_full_empirical.py`
- `CertiTherm/exact/build_g3_real_matrix.py`
- `CertiTherm/exact/replay_witness_independent.py`
- `CertiTherm/exact/three_d_ice_adapter.py`
- G2/G3/G4 software tests
- the six `/tmp/certitherm_g3_real_outputs/` files named in the consolidated report
- the ThermoDSE gitlink and the available HotSpot/3D-ICE executables on moe-server

## Verified positive results

### Clean committed-suite replay

A fresh moe-server clone at exactly `898df51` produced:

- full software suite with the required import path: **50 passed**;
- committed G3 suite semantic replay: **PASS**;
- `query_count = 4`;
- `point_certified_count = 4`;
- `placed_certified_count = 4`;
- `spatial_certified_count = 2`;
- `spatial_non_identifiable_count = 2`;
- `point_commitment_not_identifiable_count = 2`;
- `point_placed_disagreement_count = 0`;
- `unresolved_variant_count = 0`.

The fresh artifact and receipt SHA-256 values were:

- suite artifact: `6b03a2c0acce4788d3f1e109ba36b5b18cc10629db8342b8c86674c91d8ede32`;
- suite receipt: `c12a41e90ddd91efa335e46273c388aa5f5878ff484b1b4e66b3d1e4d9a3b04e`.

These differ from the hashes in the consolidated report because the report's
original external files are absent and its build path used a different command
and environment envelope. The reproduced artifact nevertheless confirms the
committed suite's qualitative matrix and metrics.

### HotSpot witness replay

After manually restoring the exact ThermoDSE gitlink revision and constructing
the missing minimal `tmp` directory, a best-effort HotSpot replay matched **4/4**
witness tuples. This is useful corroboration, but it is not claim-grade because
the required `tmp` template and materials provenance are not supplied by the
fresh clone.

## Claim-evidence matrix

| Claim | Current evidence | Audit status |
| --- | --- | --- |
| The committed 2-DNN × 2-architecture × 2-package suite has four query strata and eight candidate rows | Fresh clean-clone suite load and replay | **SUPPORTED** |
| Two spatial strata are `CERTIFIED` and two are `NON_IDENTIFIABLE` | Fresh suite artifact and embedded semantic replay | **SUPPORTED** |
| Point and placed commitments agree in all four strata | Fresh metric `point_placed_disagreement_count = 0` | **SUPPORTED** |
| Independent HotSpot replay matches four witness tuples | Best-effort moe-server rerun, but with an externally reconstructed template | **PARTIALLY SUPPORTED** |
| Independent 3D-ICE replay is reproducible and validates the same package physics | Original file absent; current binary does not launch; adapter drops package semantics | **UNSUPPORTED / UNRESOLVED** |
| G3 full gate is closed | Missing baseline/cost evidence, unrecoverable external artifacts, and unresolved independent physics | **OVERSTATED** |
| G4 may now consume a claim-grade physical G3 parent | Semantic parent exists, but full physical/reproducibility closure is incomplete | **PARTIALLY SUPPORTED** |

## Findings by severity

### P0 — External evidence is not retained

The consolidated report declares six files under
`/tmp/certitherm_g3_real_outputs/` as the single source of truth. All six are
missing from both the current local machine and moe-server. Their listed hashes
therefore cannot be checked, and a fresh clone cannot inspect the exact witness
temperatures, commands, environment, or backend results used to close the gate.

Required repair:

1. publish a content-addressed G3 evidence archive or GitHub release;
2. retain the suite artifact, receipt, per-query index, case matrix, HotSpot
   replay, and dual-backend replay;
3. bind the archive to the repository commit, command, host-independent input
   paths, simulator source revision, binary hash, and shared-library hashes;
4. make a fresh-clone verifier download and validate the archive by SHA-256.

### P0 — The 3D-ICE adapter is not package-equivalent

`three_d_ice_adapter.py` currently:

- requires `--materials` but never reads it;
- searches for `ambient ...`, while the registered HotSpot files use
  `-ambient 318.15`, so it silently falls back to `300.0 K`;
- ignores the standard/enhanced package differences in `-r_convec`, `-s_sink`,
  and `-t_spreader`;
- hardcodes one silicon layer and a top-sink coefficient;
- permits an unbound `THREE_D_ICE_HTC` environment override;
- silently assigns zero power to floorplan blocks absent from the ptrace;
- checks only the selected outcome, without a registered temperature/error
  relation between HotSpot and 3D-ICE.

Consequently, `all_match = true` can show that a different hardcoded 3D-ICE
model reaches the same coarse decision; it does not establish that the same two
package regimes were independently simulated.

Required repair:

1. define and test a HotSpot-to-3D-ICE stack translation contract;
2. parse and bind every package parameter used by the experiment;
3. require exact block-name equality instead of intersection/zero fill;
4. remove environment-only physics knobs or record them in the artifact;
5. register a numerical or decision-margin error contract;
6. add adapter unit tests and at least one canonical cross-backend calibration.

### P0 — Fresh-clone simulator dependencies are incomplete

`ThermoDSE` is stored as gitlink `51c150694457f4c6067703000ea50ff1eb9842c9`,
but `.gitmodules` is missing. A fresh clone therefore has an empty `ThermoDSE/`
directory and `replay_witness_independent.py` fails at `from core...`.

After manually restoring that exact revision, replay still fails because
`ThermoDSE/tmp` is untracked and absent. The available moe-server 3D-ICE
executables also fail to start because `libopenblas.so.0` is unavailable. The
audited binary hash is
`24945a4c855db44d1f5a647ed38f5a47ed6b68b0a638efaf96cd93a6c30b59f0`.

Required repair:

1. add a valid `.gitmodules` entry or replace the gitlink with a documented
   dependency bootstrap script;
2. commit a minimal immutable simulation template instead of copying a mutable
   `ThermoDSE/tmp` tree;
3. pin the 3D-ICE revision and provide a reproducible build/container with all
   runtime libraries;
4. fail before execution if any dependency hash differs.

### P0 — Independent replay has fail-open success states

Both replay paths compute `all_match = true` when the case list is empty.
`replay_witness_independent.py` also writes an `UNRESOLVED` backend record and
returns exit code zero when a required backend is missing. Thus a wrapper that
checks only process success or `all_match` can accept vacuous evidence.

Required repair:

- require the registered expected witness count (currently four);
- require at least two distinct outcomes for every non-identifiable query;
- require every declared backend to be present and resolved;
- return nonzero on empty, partial, or unresolved replay;
- make the gate consume one explicit aggregate `PASS/UNRESOLVED/INVALID` field.

### P1 — “Full gate closed” conflicts with the frozen contract

The G3 contract requires fair baselines and bounded system cost. The current
consolidated report contains no matched results for uniform, finite-sample,
interval-box, or fixed-refinement baselines, and no runtime, peak RSS,
certificate-size, or replay-cost table. Moreover, the generated suite artifact
itself states that it “does not by itself close G3 [or] prove
independent-backend correctness.”

Recommendation: split the gate into:

- `G3-A semantic breadth`: PASS;
- `G3-B witness physical replay`: HotSpot partial, 3D-ICE unresolved;
- `G3-C baseline and systems cost`: OPEN;
- `G3 full`: OPEN until A+B+C pass.

### P1 — Repository status documents contradict each other

The consolidated report says `G3 full gate: CLOSED`, while `CertiTherm/README.md`,
`results/G3_FULL_REPORT.md`, `audit/G3_EVIDENCE_REPAIR_END_20260720.md`, and
`INSIGHTS.md` still say G3 is open. A paper or automation cannot determine the
authoritative state.

Required repair: nominate one gate ledger as authoritative and derive the README
and reports from it, or update all status documents in one audited commit.

### P1 — Numeric inconsistency in the consolidated report

The metric table reports `point_commitment_not_identifiable_count = 2`, but the
requirement checklist still says `=1`. The fresh replay confirms the correct
value is **2**.

### P1 — The empirical claim must respect zero point/placed disagreement

The strongest supported result is that the point commitment is not universally
identifiable over the registered spatial equivalence set. The experiment does
**not** show that the registered placed-power reference selects a different
architecture: `point_placed_disagreement_count = 0`.

Safe wording:

> Two of four registered query strata admit observation-equivalent spatial
> realizations with distinct architecture outcomes, even though the available
> placed reference agrees with the point estimate in all four strata.

Unsafe wording includes “the point estimate chose the wrong architecture in two
cases” or an empirical false-decision rate against placed ground truth.

### P2 — The documented default test command is not self-contained

On both local and moe-server fresh clones, `python3 -m pytest -q` fails during
collection because imports require an undocumented path setup. The suite passes
50/50 only with:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=CertiTherm/exact:CertiTherm/audit:CertiTherm/robust_dse \
python3 -m pytest -q
```

The repository also tracks 17 CPython 3.11 `.pyc` files. Python 3.12 creates
additional untracked bytecode, which makes the claim-grade clean-tree check
fail.

Required repair: remove tracked bytecode, ignore `__pycache__/` and `*.pyc`, and
add package/test configuration so the documented command works without manual
`PYTHONPATH`.

## Recommended execution order

1. Reopen only the **full** G3 gate; retain the semantic-matrix PASS.
2. Fix the numeric/status-document contradictions.
3. Make replay fail closed on missing cases, dependencies, and backends.
4. Repair dependency bootstrapping and publish the exact external evidence.
5. Replace the current 3D-ICE adapter with a content-equivalent stack mapping,
   then rerun all four witness tuples from a fresh clone/container.
6. Add the frozen G3 baseline and systems-cost table.
7. Only then run G4 on the two physical `NON_IDENTIFIABLE` strata and compare
   witness-directed acquisition against fixed and uncertainty-width refinement.

For a DAC/ICCAD/DATE paper, step 6 is not optional: without baseline/cost
evidence the result is a sound motivating counterexample suite, not yet a full
EDA method evaluation.

## Numeric consistency findings

- Correct current non-identifiable count: **2**, not 1.
- Correct current certified count: **2**.
- Correct current point/placed disagreement count: **0**.
- Fresh replay reproduces all suite metrics but not the report's original
  external-file hashes.

## Citation findings

- Citation metadata audit: not applicable to this code/evidence audit.
- Citation-context audit: not performed; no literature novelty claim is changed
  by this document.

## Next CCFA owner

- `ccf-integrity-auditor`: re-audit the repaired artifact and gate ledger.
- `ccf-experiment-designer`: freeze the missing baseline/system-cost matrix.
- `ccf-paper-writer`: update claim wording only after evidence status is aligned.

## No-invention status

No result was invented. Positive statements above come from the committed suite,
fresh local/moe-server tests, or the explicitly labeled best-effort HotSpot
rerun. The unavailable original `/tmp` artifacts and the failed 3D-ICE rerun are
reported as unavailable or unresolved rather than inferred as passing.
