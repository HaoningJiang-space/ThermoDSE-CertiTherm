# DR-DSC prototype: differentiable proposal for DSOS action selection

Status: **first prototype, smoke-tested only, not part of any frozen protocol
or claim path.** Do not cite results from this directory as evidence; do not
let it influence `method-freeze-v1`.

First execution: 2026-07-21 on moe-server, repo @ `89318c7`
(`round/gpu-dev-end-to-end`), python 3.12.13 / torch 2.6.0 / numpy 2.4.4 /
scipy 1.17.1. **37 passed** (16 CertiTherm baseline + 15 Stage A + 6 Stage B).
On the two known-answer toy fixtures the trained-and-rounded proposal reaches
the exact optimum with zero gap (`proxy_cost == exact_cost == 1.0`), and an
infeasible budget correctly fails closed instead of fabricating a certificate.

**That is a plumbing smoke test on 2-block, 2-action instances — nothing
more.** It says the loop runs, the adapter indexes correctly, and the exact
oracle re-verifies the output. It says nothing about behaviour at realistic
scale (~150–200 actions), about proposal quality on instances where greedy is
not already optimal, or about whether this is faster than the exact MILP it is
meant to accelerate. No claim beyond "it runs and agrees with the oracle on
toys" is supported.

NOTE: the environment above is NOT CertiTherm's frozen `requirements.lock`
(numpy 1.24.4 / scipy 1.10.1 / py3.8). It reuses an existing torch-bearing
conda env on moe-server via `--system-site-packages` because `/data` is at
100% capacity. Acceptable for a prototype smoke test; NOT acceptable for
anything claim-grade.

## Scope: what this is and is not

This is a candidate accelerant for `CertiTherm.synthesis`'s discrete
action-selection search (the "MILP is slow" problem), evaluated against two
rounds of external review during design. It is **not** the "jointly design new
continuous measurement channels / package parameters" idea also discussed —
that would reopen `docs/MEASUREMENT_LIBRARY.md`'s frozen registry and needs a
new freeze ID before any code is worth writing. This prototype only relaxes
the *discrete selection* `z_a ∈ {0,1}` over the **already-registered, frozen**
action library into a continuous gate `g_a ∈ [0,1]`, matching the narrower,
freeze-compatible half of that discussion.

## Why there is no PDHG / differentiable-margin-LP module here

An earlier design draft planned to differentiate the phase-I feasibility
margin LP itself (via batched PDHG) so gradients could reach continuous
measurement/package parameters. That's dropped from this v1 because it is
only needed for the continuous-redesign scope explicitly excluded above. The
inner adversarial witness search is convex and already solved exactly and
cheaply by `CertiTherm.synthesis._state_collision` (scipy/HiGHS), so the
witness is treated as a fixed constant and only the outer gate/coverage layer
carries gradients.

**Correction (peer review, 2026-07-21):** earlier drafts of this README, and
of the surrounding discussion, justified that with *Danskin's theorem*. That
was wrong. `_state_collision` solves a **zero-objective feasibility LP**
(`linprog(np.zeros(2*n), ...)`) and returns an *arbitrary* surviving
collision — it does not minimize the outer coverage objective, so there is no
inner argmin for an envelope theorem to apply to. What this actually is:
**constraint generation with stop-gradient witnesses.** The safety property is
unaffected (it comes from exact re-verification, not from the gradient's
provenance), and no code changed as a result of the correction — but the
theoretical label was unearned and is now dropped. Earning a real Danskin
gradient would require defining and solving an inner problem aligned with the
outer loss.

Architecture:

```
CertiTherm.synthesis._state_collision   (exact, scipy/HiGHS, CPU, unmodified)
        │  a surviving witness (fixed constant, no gradient through this)
        ▼
gate.py   hard separation → soft coverage / soft-min   (torch, GPU-batchable)
        │  gradient step on gate logits (the ONLY learnable quantity)
        ▼
rounding.py   cost-aware discretization
        │
        ▼
CertiTherm.synthesis._state_collision   (exact re-verification; new collision → back to top)
```

Note that the separation indicator is **hard**, not soft: the measurement
vectors and witnesses are frozen constants, never parameters, so nothing
needs a gradient with respect to them. The relaxation lives purely in the
gates, which makes the objective exactly the multilinear extension of the
underlying set-cover rather than a smoothed approximation of it.
`soft_separation` is retained for the future continuous-design extension.

`train.py` wires this into the same adversarial constraint-generation loop
`CertiTherm.synthesis.synthesize_ordered_query` already runs — it replaces
only the deterministic `_greedy_cover` pre-pass with a gradient-trained
proposal. The exact MILP closure in `synthesis.py` is untouched and remains
the only thing that can emit `OPTIMAL`/`UNSYNTHESIZABLE`. **Nothing in this
directory is allowed to report a certificate**; every entry point returns a
candidate selection that must be re-verified by `CertiTherm.synthesis` before
it means anything.

## Defects found in peer review, before this code was ever run

All fixed in the current files; recorded here because each one would have
produced a *misleading* result rather than an obvious failure.

1. **`soft_separation` scored non-separating actions at 0.731.** With
   `sqrt(x²+s²)` and no `-s`, an action with *zero* separation got
   sigmoid(1)≈0.731, and the function was flat across x∈[0,1e-6] — blind at
   the 1e-8 tolerance scale it was meant to discriminate at. Now
   zero-preserving, and superseded as the default by `hard_separation`.
2. **`cost_penalty` defaulted to 0**, making the objective monotonically
   increasing in every gate with nothing opposing it: every gate saturates to
   1 and rounding selects the *entire* library. That is a valid separating
   set, so the exact oracle confirms it and the run "succeeds" while being
   useless. Default is now 0.25 on max-normalized costs.
3. **The toy test asserted only `gap >= -1e-9`**, which the degenerate
   select-everything outcome satisfies trivially — it would have printed PASS
   at 2× the known optimum. Now pins the exact optimum and adds an asymmetric
   cost fixture that a cost-blind proposal cannot pass.
4. **The final round's selection was never checked.** The loop tests
   `selected` at the top of each iteration, so a certifying set produced by
   the last round's rounding exited by exhaustion and reported unverified — a
   false negative.
5. **`scipy` was missing from `requirements.txt`.** `oracle.py` imports
   `CertiTherm.synthesis`, which imports scipy at module scope; torch pulls in
   numpy but not scipy, so Stage B would have died at import time looking like
   a broken adapter.
6. **`research/` is untracked**, so a fresh clone of `origin` cannot contain
   it — the remote run needs an explicit source-sync step
   (`remote_exec.sh --sync`), and local edits do *not* propagate to an
   existing remote clone without re-syncing.
7. **The working branch is not `master`.** `origin/master` was 11 commits
   behind the active round branch with `CertiTherm/synthesis.py` differing by
   482 lines; cloning the default branch would have tested against a
   different `_state_collision` than this prototype was written against.
   `remote_exec.sh --new-clone` now takes `--branch`.

Also corrected: the Danskin framing (see above), `certified` →
`state_pair_verified` (it only ever meant one candidate and one state pair,
never the ordered query), and `soft_min`'s undocumented `log(B)/beta` drift
as the witness pool grows.

## Scale results (2026-07-22) — NEGATIVE, and retained

`benchmark.py` builds a realistically-shaped instance: a real 227-block
ThermoDSE floorplan, the action library from CertiTherm's own
`build_measurement_library` (**241 actions**: 10 module @1, 4 region @4,
227 post-route @8; the chiplet tier deduplicates away at cut 1x1 because it
equals total power), and CertiTherm's own power polytope. The thermal
operator is synthetic — see the module docstring.

| method | candidate cost | n | converged | budget | time |
|---|---|---|---|---|---|
| exact DSOS (8 workers) | not recorded | — | **no** (`UNRESOLVED`) | 250 iters | 716s |
| exact DSOS (sequential) | 302.0 | ≥38 | **no** (`UNRESOLVED`) | 5000 iters | 461s |
| plain greedy | 24.0 | 11 | **no** | 60 rounds | 3.1s |
| DR-DSC learned | 85.0 | 19 | **no** | 60 rounds | 132.7s |

CORRECTION (integrity audit, 2026-07-22): earlier revisions of this table put
`11 (candidate)` on BOTH exact-DSOS rows. That number came from the
60-iteration verification run and was wrong for the others — the sweep records
`candidate_cost=302.0` at 5000 iterations, and with a maximum per-action cost
of 8 an 11-action cover cannot exceed 88, so 302 needs at least 38 actions.
Measured candidate sizes are 11 (60 iters, cost 31.0), 17 (250, 58.0) and 19
(1000, 74.0); the 5000-iteration count was not separately recorded and is only
bounded below. The 716s parallel run predates the reporting fix, so its
candidate was never captured at all.

**SUPERSEDED CLAIMS — do not reuse.** Earlier revisions of this table reported
`n=0` for the exact path and attributed the 716s to "the MILP, measured".
Both were wrong:

- `n=0` was a **reporting bug**, not an empty selection. On budget exhaustion
  `synthesize_minimum_observation` returned `master.selected`, which on that
  path is still the empty-cut master from initialisation, discarding an
  11-action working cover (cost 31.0). Fixed; the run now reports it under
  `candidate_action_ids`. Every earlier report quoting `n_selected=0` as
  "the algorithm selected nothing" must be regenerated.
- The exact MILP **never ran**. `_solve_master` is only called when separation
  finds no collision, which never happened. So neither "MILP is too slow" nor
  the "~8 hours at the 10000-iteration default" extrapolation is supported by
  that experiment. The defensible statement is narrow: *under the 8-worker
  fresh-spawn implementation, 250 iterations took 716s and stayed UNRESOLVED
  within the iteration budget.*

## Anytime certified lower bound (2026-07-22)

`_anytime_lower_bound` computes a **certified** global lower bound from the
cuts discovered so far, by weak duality (`L(y) = 1'y + sum_a min(0, c_a -
(C'y)_a)`, `y >= 0`) using the solver's dual prices only as a guess — so
solver error can loosen the bound but never invalidate it. Validated on 1000
random instances spanning seven orders of magnitude of cost: zero violations
of `LB <= integer optimum`, zero monotonicity violations.

| iterations | candidate cover cost | **certified lower bound** | wall |
|---|---|---|---|
| 60 | 31.0 | **16.0** | 4s |
| 250 | 58.0 | **21.0** | 18s |
| 1000 | 74.0 | **31.33** | 78s |
| 5000 | 302.0 | **169.17** | 456s |

**The candidate cover is demonstrably not an upper bound, and this table
proves it.** The bound at 1000 iterations (31.33) already EXCEEDS the
candidate cover reported at 60 iterations (31.0). Since the bound is globally
valid, that 31.0 cover cannot have been a feasible plan — it was cheap only
because it hit the few cuts discovered by then. Never subtract these two
columns and call the result an optimality gap.

**Diagnostic reading (this is the useful part).** The bound is not stalling —
it climbs 16 → 21 → 31 → 169 and is still rising between 1000 and 5000
iterations. (An earlier revision called that rise "roughly linear"; the
integrity audit rejected it, correctly — four checkpoints give interval slopes
of ~0.026, 0.014 and 0.034 bound units per iteration, which does not support a
linear characterisation.) So cut generation is
producing genuinely informative cuts; the loop is not spinning. What the
numbers say instead is that **this instance's true optimum is large**: at
least 169.17 against a full-library cost of 1842 (10 module@1 + 4 region@4 +
227 post-route@8). Non-closure here is not a solver failure, a greedy
failure, or an integrality-gap artifact — the answer itself is expensive and
the accumulated cuts have not yet come close to proving it.

That is consistent with the instance's physics: with a sharply local thermal
kernel over 227 blocks, almost any single block can drive the peak, so
certifying the decision genuinely requires pinning many blocks individually.
Whether a real HotSpot operator induces the same structure is exactly what the
running `--split dev` matrix can answer, and this synthetic instance cannot.

**Findings that survive, in order of importance.**

1. **The default parallelism is a 32x pessimization.** Sequential separation
   runs at 0.064 s/iteration against 2.07 s/iteration for the 8-worker
   default: over 96% of parallel wall time is not useful LP work. Each
   exhaustive search builds a fresh spawn-context `ProcessPoolExecutor` to
   dispatch twelve LPs of ~5-6 ms each; the ~2 s/iteration overhead is an
   unseparated mixture of spawn, per-worker numpy/scipy import, problem
   pickling, IPC, HiGHS init and teardown, and should not be attributed to any
   one of them. At twelve LPs per round, even zero-overhead 8-way parallelism
   could only save ~53 ms/round, so sequential is the right default at this
   scale.

2. **Non-convergence is real and is NOT a parallelism artifact.** Removing the
   32x penalty and running 5000 sequential iterations (461s) still returns
   `UNRESOLVED`. The cut antichain grows to 5840 with ~2 new cuts per
   iteration and little domination pruning, and exactly 2 collisions are found
   per iteration throughout. LP cost per solve grows only mildly with the
   selected set (5.1 ms at 25 iterations to 6.4 ms at 5000), so the
   non-closure is combinatorial rather than a per-solve cost problem.

3. **Stage attribution shifts with scale, so small-run profiles mislead.** At
   25 iterations LP solve is 96.7% and antichain+greedy 0.6%; at 5000
   iterations LP is 82.6% while `greedy_cover` reaches 11.8% (0.3 ms to
   10.9 ms per call) and antichain insertion 2.5%, both growing superlinearly
   as every round rescans thousands of cuts. An earlier claim here that
   antichain and greedy "are not the bottleneck" was drawn from the 25-round
   profile and is only true at that scale.

4. **A structural observation worth exploiting.** Exactly 2 of the 12
   reject cells produce collisions on every one of 5000 iterations, so roughly
   83% of LP time re-proves the same cells infeasible. Caching is only sound
   under a monotonicity guard: `selected` is recomputed from scratch each
   round and can shrink, so a cell may only be skipped when the new selection
   is a superset of the one under which it was last proved infeasible.

2. **The learned ordering does not beat plain greedy — it is markedly
   worse.** At a matched 60-round budget, 85.0 vs 24.0 (+254%). Both are
   unconverged, so this is not a comparison of final optima and should not be
   quoted as one; but there is no reading of it in which the learned signal
   is helping. The honest conclusion for the DR-DSC direction is negative.

3. **A likely contributing asymmetry, stated against my own result.** Plain
   greedy recomputes coverage *gain* after every pick (adaptive), whereas
   `greedy_cover_rounding` walks a *static* learned gate/cost order and only
   skips actions covering nothing new. A fairer variant would fold the
   learned score into an adaptive gain. That might narrow the gap — it does
   not explain away a 3.5x deficit, and it is not a reason to keep tuning
   before the convergence problem in (1) is solved.

**A prior kernel artifact, recorded so it is not repeated.** The first
operator used `0.9/(1+d/4mm)`, giving a max/min response ratio of only 5.4x:
every block heated every thermal point, so certifying the peak required
pinning nearly all 227 blocks. Switching to `exp(-d/1.2mm)` (ratio ~2.5e6,
matching real HotSpot locality) did NOT fix convergence, which is how we know
non-convergence is structural rather than a kernel artifact.

**Not yet established:** a converging realistic instance. The 30-block
floorplan was *trivially* certified (the empty selection already admits no
witness — no thermal tension at a 345 K limit), so it cannot discriminate
between orderings either. Finding a size/limit regime where the exact path
actually closes is the prerequisite for any further comparison, and is the
next thing to do rather than more tuning of the proposal layer.

## Defect found by the first run itself

Fixing `cost_penalty` was necessary but NOT sufficient. On the first real
execution the symmetric fixture still returned `selected=(0,1)`,
`proxy_cost=2.0` against an exact optimum of `1.0`.

The cause is structural, not a tuning error. With two interchangeable
unit-cost actions the relaxation is perfectly symmetric, so both gates
converge to the *same* value: coverage `C = 2g − g²`, loss `= g² − 1.5g`,
minimized at **g = 0.75** — and the observed training history converged to
`0.9375 = 2(0.75) − 0.75²`, confirming the analysis exactly. Thresholding at
0.5 then takes both. This is the classic fractional-symmetric-optimum failure
of relaxed set cover, and no amount of cost weighting removes it.

The fix is in the *rounding rule*, not the objective:
`rounding.greedy_cover_rounding` adds actions in descending learned
`gate/cost` order and STOPS at full hard coverage. That keeps what the
relaxation actually learned (the preference order) while restoring the
minimality thresholding destroys. Both fixtures then hit the exact optimum.

Worth noting honestly: on instances this small, that stopping rule is doing
most of the work, and the learned gates only supply an ordering that
cost-effectiveness greedy would likely have found anyway. Whether the learned
order beats plain greedy is exactly what a non-toy instance would have to
show, and has not been tested.

## What's deliberately NOT proven yet

- No equivalence theorem for the soft-coverage relaxation (the
  `ρ(S) > 0 ⟺ decision-identifying`-style margin result the reviews asked
  for).
- No explicit approximation/smoothing-gap bound.
- No safe-fixing / exact-branch-and-cut acceleration hookup (the
  lowest-risk, highest-value item from both reviews — worth doing next,
  independently of this differentiable path, straight off the LP-relaxation
  duals `CertiTherm.synthesis._solve_master` already computes).
- No hyperparameter calibration (`temperature`, `smoothing`, `beta`,
  `lr`, `steps_per_round`). These would need a frozen calibration protocol
  (à la `docs/THERMAL_ERROR_CONTRACT.md`) before this could sit anywhere near
  a claim path, even as "just a warm start."

## Files

- `gate.py` — sigmoid gates, multilinear soft coverage `C_g(ω) = 1 - ∏(1-g_a h_a(ω))`,
  conservative soft-min over a witness pool, a dual-sensitivity action-scoring
  heuristic, and a Euclidean budget projection. Pure tensor ops; no CertiTherm
  dependency; the only module worth unit-testing without a GPU.
- `oracle.py` — thin adapter around `CertiTherm.synthesis._state_collision`
  (a private function — this is a real dependency-fragility risk, flagged
  deliberately rather than hidden: a refactor of `synthesis.py` can silently
  break this file).
- `train.py` — the outer adversarial loop described above.
- `rounding.py` — cost-aware gate discretization, pure numpy.
- `tests/test_gate_coverage.py` — self-contained, torch-only, hand-verifiable
  sanity checks (no CertiTherm/scipy needed).
- `tests/test_end_to_end_toy.py` — wires the full loop against the same tiny
  fixture as `CertiTherm/tests/test_synthesis.py::test_exact_plan_reaches_unit_cost_global_limit`,
  and checks the rounded result is exact-re-verified and reports
  `proxy_cost` vs `synthesize_ordered_query`'s exact cost. **This has never
  been run.**

## Running this (moe-server only — package installs happen there, not locally)

This intentionally does not touch `requirements.lock` (that file is
`CertiTherm`'s frozen, pinned environment). Install into a separate venv:

```bash
scripts/remote_exec.sh --new-clone dr-dsc-check '
  python3 -m venv .venv-dr-dsc &&
  .venv-dr-dsc/bin/pip install -r research/dr_dsc/requirements.txt &&
  .venv-dr-dsc/bin/python -m pytest -q research/dr_dsc/tests
'
```

(run the above from `.claude/skills/moe-server-remote/`, i.e.
`.claude/skills/moe-server-remote/scripts/remote_exec.sh --new-clone ...`).
Report back `proxy_cost`, `exact_cost`, and the gap on the toy fixture before
trusting anything else here.
