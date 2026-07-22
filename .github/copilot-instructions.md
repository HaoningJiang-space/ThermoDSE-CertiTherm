# Copilot Instructions for this Repository

This repository contains two connected codebases:

1. **`ThermoDSE/`**: thermal-aware chiplet DNN accelerator design-space exploration (DSE) and optimization.
2. **`CertiTherm/`**: decision-identifiability and proof/replay tooling built around thermal-response evidence and architecture queries.

## Build, test, and lint commands

### CertiTherm tests

Run from the repository root:

```bash
python -m pytest -q CertiTherm/tests/test_g3_evidence.py
python -m pytest -q CertiTherm/tests/test_g2_soundness.py
python -m pytest -q
```

### ThermoDSE executable workflows

Run from inside `ThermoDSE/tools` or `ThermoDSE/rl_opt` as shown (many scripts rely on `sys.path.append('../')` and relative paths):

```bash
cd ThermoDSE/tools
python scbo_search.py -hp /PATH/TO/HotSpot -maxA 300 -maxT 348 -sp ../tmp
python scbo_two_search.py -hp /PATH/TO/HotSpot -maxA 300 -maxT 348 -sp ../tmp

cd ../rl_opt
python rl_ppo.py -b1 1 -hp /PATH/TO/HotSpot -maxA 300 -maxT 348 -sp ../tmp_0
python sa_opt.py -b2 1 -hp /PATH/TO/HotSpot -maxA 300 -maxT 348 -sp ../tmp_1
python sa_opt.py -b3 1 -hp /PATH/TO/HotSpot -maxA 300 -maxT 348 -sp ../tmp_2
```

HotSpot smoke test:

```bash
cd ThermoDSE/test
bash run.sh
```

Reproduction summary helper:

```bash
cd ThermoDSE
python compare_results.py
```

### Linting

No repository-wide lint command is currently defined in tracked config files.

## High-level architecture

### ThermoDSE runtime pipeline

1. `tools/scbo_search.py` (or baseline scripts in `rl_opt/`) converts sampled search vectors to a fixed `sys_info` hardware tuple via `param_regulator`.
2. All optimizers instantiate `core/chiplet_eva.py::chiplet_evaluator` with `sys_info`, `hotspot_path`, and `sim_path`.
3. `chiplet_evaluator.generate_hardware()` builds accelerator/core memory structures, floorplans, and simulation artifacts.
4. `chiplet_evaluator.evaluate()` orchestrates:
   - workload import from `nns/`,
   - layer partitioning (`core/partengine.py`),
   - task DAG creation (`core/taskdag.py`),
   - scheduling/mapping (`core/schedule.py`),
   - NoP/NoC/DRAM cost modeling (`core/nop.py`),
   - thermal execution via HotSpot through generated ptrace/floorplan/config files.
5. Optimizers consume latency/energy/yield/temperature and apply thermal + area constraints.

### CertiTherm exact decision path

1. `exact/run_g2_query.py` loads a registered query bundle (`query.json` + `.npy`/`.json` artifacts), validates schema/content binding, and requires a clean Git worktree for claim-grade execution.
2. `exact/decision_query.py` applies architecture-selection semantics over ordered candidates (objective + tie-break rank), and emits `CERTIFIED`, `NON_IDENTIFIABLE`, or `UNRESOLVED`.
3. `exact/decide.py` is the compatibility wrapper around `exact/linear_oracle.py` LP bounds solving.
4. `exact/evidence.py` creates replay artifacts with digests; replay validates proofs/witnesses and input integrity.
5. `tests/test_g2_soundness.py`, `tests/test_g3_evidence.py`, and related tests enforce fail-closed behavior and adversarial replay checks.

## Key conventions in this repository

1. **Shared architecture tuple contract**: DSE scripts and evaluators use the same 10-field `sys_info` order:  
   `[chipletX, chipletY, chipletCx, chipletCy, chiplet_intvl, mtxu_h, mtxu_w, ubuf_size, nop_bw, dram_bw_design]`.
2. **Fail-closed status model for evidence logic**: unresolved inputs/simulation/proof states must stay explicit (`UNRESOLVED`), not converted to feasible/infeasible.
3. **Content-bound evidence artifacts**: CertiTherm claim-grade flows hash inputs/outputs and replay artifacts; keep provenance and SHA-256 digests intact.
4. **Execution directory matters**: many ThermoDSE scripts are not import-safe and depend on relative paths (`../tmp`, `../../HotSpot`); execute from their intended subdirectories.
5. **Parallel simulation requires isolated temp dirs**: use distinct `-sp` simulation paths (`tmp_0`, `tmp_1`, …) per worker/process to avoid file collisions.
