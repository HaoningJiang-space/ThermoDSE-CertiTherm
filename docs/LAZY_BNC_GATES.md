# Persistent lazy branch-and-cut — kill-experiment gates (NON-CLAIM)

## What is being tested, and what is NOT being claimed

**Hypothesis.** Replacing the outer implicit-hitting-set loop (solve MILP -> verify ->
*discard the solver* -> add cut -> re-solve from scratch) with lazy separation inside ONE
persistent branch-and-bound tree reduces the number of expensive thermal-oracle calls, or
the time to reach the same bound.

**This is a hypothesis under test, not a chosen algorithm.** The measured cost model is

    T ~= (oracle calls) x (cells scanned) x ~91 ms / parallelism

with profiling attributing 99.4% of oracle time to the collision LP solve and ~0.6% to
assembly. Persistent search preserves the tree, LP basis, pseudocosts, incumbent and
solver-derived cuts — but if it does not reduce *oracle calls*, it cannot produce a
headline end-to-end speedup, and it may be SLOWER because it separates at more incumbents
than the outer loop has rounds.

`kernel-first` verification already cut a refuted round from ~681 LPs to ~48, which shifts
the remaining cost further onto the ROUND COUNT — the quantity persistent B&C does not
obviously improve. That is the reason for a kill experiment rather than a build-out.

## Withdrawn motivation — cross-elimination

An earlier shadow experiment (`research/triangle/cross_elim.py`, commit `d57d8be`) reported
that one witness cut invalidates ~5.90 of 7 other equal-cost covers. **That number must not
be cited as evidence that cuts are strong enough to make persistent branch-and-cut pay
off.**

Precisely: K=8 is a tiny, solver-selected, non-random sample from ONE exact-cost face. The
exact-assignment no-goods guarantee only that the covers are *distinct* — not that they are
adjacent or similar, which would be a property of the enumeration order, not of the
constraint. The statistic therefore estimates cross-elimination *within that sample* and
cannot support a global cut-strength claim.

The observed MaxHS plateau (`L=1256` unchanged over ~1000 added cuts on transformer
arch_b) is **not** a logical contradiction of the 5.9/7 figure — highly correlated cuts can
eliminate most of eight sampled covers while saying little about a much larger face. It is
strong *empirical* evidence that the sample was not representative of the evolving
surviving face: either that face is enormous, or these cuts eliminate neighbouring covers
laterally without lifting the lower bound.

The result itself is retained (negative and partial results are retained deliberately);
only the inference drawn from it is withdrawn. The remaining, still-valid motivation for
persistent search is the reuse of tree/basis/pseudocost/incumbent state — which must be
measured (Gate B), not assumed.

## Dependency receipt

Nothing in the pinned stack can do this: `scipy.optimize.milp` exposes no callback API at
all, and HiGHS/`highspy` exposes MIP-solution/interrupt/cut-pool callbacks but no
SCIP-style user *lazy-constraint enforcement*. The gate therefore needs a new dependency.

| item | value |
| --- | --- |
| package | `pyscipopt` 6.2.1 |
| wheel | `pyscipopt-6.2.1-cp38-cp38-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl` |
| sha256 | `6fa61eacb71c9dab8393cbbf245379b4a78b72721c9465fc3fb18f94d7c0a7d6` |
| bundled SCIP | 10.0 (no system install, no sudo, no compilation) |
| interpreter | CPython 3.8 (matches the pinned `make bootstrap` venv) |

Deliberately **NOT** added to `requirements.lock`: this is a diagnostic dependency for the
kill experiment, and adding it would change the fresh-clone contract and CI for a method
that has not passed its own gate. It lives in `requirements-bnc.txt` and is installed
explicitly. It moves into the main lock only if Gate C/D pass.

## Gate A — PySCIPOpt correctness (formulation + silent-failure regressions)

`research/triangle/tiny_lazy_bnc.py`. Three-way agreement on a tiny instance where `2^m`
enumeration is possible:

1. brute force over all `2^m` subsets — **ground truth**
2. the current outer IHS loop — today's algorithm
3. persistent lazy branch-and-cut in one SCIP tree — the proposal

(2) and (3) share the separation oracle, so their agreement proves only wiring; agreement
with (1) is the actual check.

Additional required checks:

- **Separation actually fired** (`separations > 0`, `cuts_added > 0`). Without this the
  agreement is vacuous — see the `conslock` failure below.
- **Independent cut re-derivation.** Every archived cut is recomputed from its stored
  world pair alone and must match *exactly*. A superset would be valid-but-weaker; a
  strict subset would be unsound.
- **`conslock` reversed must FAIL** (`--lock-mode reversed`). Getting the
  `addVarLocks(var, nlocksdown, nlocksup)` order backwards makes SCIP dual-fix every
  variable in presolve, fire the handler ZERO times, and return `status=optimal` with a
  wrong objective — observed in practice as `obj=3.0, x=[1,1,1], enfo calls=0` on a case
  whose true optimum is 2. For a covering row `sum x_i >= 1` the correct call is
  `addVarLocks(v, nlockspos, nlocksneg)`, applied to *every* action variable, because any
  variable may appear in a cut that does not exist yet.
- **`consenfops` implemented.** Pseudo solutions carry no LP; omitting the handler lets
  SCIP accept a solution separation never examined — the same silent class of bug.
- **No pseudo-separation on fractional solutions.** `C(z)` is defined only once a
  measurement set `S` is fixed, and `S = {i : x_i = 1}` does not exist for a fractional
  `x`. Rounding a fractional LP solution to a set and calling the oracle on it would
  produce a globally *valid* cut that is not necessarily *violated* by the current LP
  solution — valid is not the same as violated. Fractional nodes are left to branching.
- **presolve on/off agreement.**
- **Vocabulary.** SCIP reporting `dualbound == primalbound` is `solver_asserted`
  optimality. Only agreement with brute force (Gate A) or an independently checked bound
  (production) may be reported as verified.

## The two lower bounds are different quantities (peer review, adopted)

An earlier draft of this plan stated that SCIP's dual bound would serve as `L` and be
"independently re-checked by exact-rational weak duality over the archived cuts". **That is
not possible, and the invariant was wrong.** Exact weak duality over the cut rows certifies
only the LP-relaxation bound

    max sum_k y_k   s.t.  y >= 0,  sum_{k : i in C_k} y_k <= c_i

which proves `L_LP <= C*` but generally cannot reproduce SCIP's *integer* branch-and-bound
bound. They are two different numbers; one cannot verify the other.

Frozen convention:

| field | meaning |
| --- | --- |
| `certified_lower_bound` | exact-Fraction Lagrangian over archived cuts, lattice-lifted. Publishable as `L`. Valid for ANY `y >= 0`, so a badly captured dual can only weaken it. |
| `solver_asserted_dual` | SCIP's B&B dual bound. Recorded for comparison. **Never** published as `L` without a separately archived and independently validated B&B proof. |

Status vocabulary (extends the repository contract, no new synonyms):
`OPTIMAL` = verified feasible `U` and independently certified `L = U`;
`CERTIFIED` = finite independently certified `[L, U]`;
`UNSYNTHESIZABLE` = independently verified empty-separator witness;
`UNRESOLVED` = no publishable conclusion.

`U` starts at `+inf` and becomes finite only after an exhaustively verified cover exists —
the full registry is an upper bound only *after* exhaustive verification.

## Known defects in the production path this gate must not inherit

- **`_cut_from_pair(pair, actions, cover)` takes the cover** and excludes already-selected
  actions, so the cut is not a canonical function of the witness and a verifier cannot
  re-derive it from the world pair alone. The gate uses a canonical
  `C(z) = {i : |d_i'z| > tau_i}` over the *whole* registry, then separately asserts
  `C(z) ∩ supp(x) = {}`. Production must be reconciled to that form.
- **Legacy warm-start cuts (`strong_antichain_*.npz`) store incidence vectors, not world
  pairs**, so they cannot be independently re-derived. They must be regenerated with
  witnesses, backfilled, or excluded from certificate-bearing runs. An incidence vector is
  not a physical proof.
- **Floating-point witnesses need a frozen convention.** A stored `z` with
  `|d_i'z|` near `tau_i` can flip cut membership across platforms. Ambiguous separators
  must be omitted from `C(z)`; an ambiguous witness must yield `UNRESOLVED`
  (`certificate.separator_set` already implements this guard band).
- **Do not evict dominated cuts from a live SCIP model.** Keep every accepted physical cut
  as a constraint; maintain the antichain only for lookup and reporting.

## Callback contract (soundness depends on it, not on `needscons=False`)

`needscons=False` is only the mechanism that activates the handler without explicit
constraint objects; it is not a soundness property. Required:

1. every added cut is globally valid and added **globally**;
2. `conslock` down-locks **every** action variable (any may appear in a future cut);
3. every integral solution reaching enforcement/feasibility is checked — never only
   "improving" ones; a false `FEASIBLE` for an unexamined point can corrupt fathoming;
4. `consenfops` implemented (pseudo solutions carry no LP);
5. fractional nodes are branched, never separated by rounding `x` to a set;
6. an infeasible assignment must either violate an already-active cut or yield a NEW
   global cut — otherwise `UNRESOLVED`, never a silent re-discovery loop (this is the
   implementation-level progress premise the finite-termination proof needs);
7. separation results are cached by assignment (SCIP presents the same point through
   several callbacks);
8. callback exceptions set an abort flag, interrupt the solve, and force `UNRESOLVED`.

Separation should be staged for cost — cached cuts, then kernel cells, stop at first
collision, full scan only when nothing was found and the candidate could be certified —
but the tiny gate deliberately runs exhaustive separation so correctness is easy to check.

## Gate B — isolate the master-side benefit (Amdahl ceiling)

Replay the SAME historical cut ledger, **calling no thermal oracle**, to answer:

> how much master time does keeping the search tree actually save?

If the master is only a few percent of end-to-end time, then even a 100x master speedup
cannot be the headline — an Amdahl ceiling, and the cheapest way to kill the hypothesis.

Comparing "repeated SciPy MILP" directly against "persistent SCIP" would confound TWO
variables (solver identity and restart-vs-persistence). Three arms, not two:

| arm | isolates |
| --- | --- |
| B-1 repeated SciPy/HiGHS master (today) | baseline |
| B-2 repeated SCIP master, no callbacks | SCIP vs HiGHS on the same restart pattern |
| B-3 persistent SCIP with lazy separation | persistence vs restart, net of solver identity |

Report per arm: master time excluding callbacks; callback wall time; distinct integral
assignments checked; duplicate callback checks; LP/pseudo/heuristic callback counts; cells
and collision LPs per assignment; time to first verified incumbent; final dual bound.

Secondary: how many integral assignments the persistent tree presents versus the number of
rounds the outer loop takes. More assignments than rounds is a direct warning that
separation cost will go UP, which is the main way this hypothesis dies.

**The baseline must be the tuned one, not the historical run.** The outer loop currently
uses 16 of 52 cores and `kernel_sweep.sh` has never been executed; the persistent-worker
and first-collision levers are also unmeasured. Freezing a tuned outer-loop baseline is
lower-risk than replacing the proof engine, and it changes the number that B&C must beat.
That sweep is a prerequisite of Gate C, not an alternative to it.

## Gate C — controlled A/B on real arch_c

Both methods with the same kernel, same strong oracle, same initial cuts, same budget,
same thread count. Report: oracle callbacks; total collision LPs; discovered cuts;
lower-bound trajectory; certified `U`; time-to-same-`L`; time-to-same-`U`.

**Go criterion:** persistent B&C reduces oracle LP count by >= 50%, OR achieves >= 2x
time-to-same-bound. At 1.1–1.3x it is an engineering backend, not a paper contribution.

## Gate D — hardest case, transformer arch_b

Only after C passes. Only if BOTH reduce oracle work does the global margin warm start get
added and the combination measured.

## Gate A — RESULT: PASS (moe-server, fresh clone, `d69d53b`)

Fresh `git clone --recurse-submodules` + `make bootstrap` +
`pip install -r requirements-bnc.txt`, run at a committed revision.

| run | verdict |
| --- | --- |
| A1 correct locks, presolve on | **PASS** — three-way agreement, separation fired, ledger verified, `L <= C*` |
| A2 correct locks, presolve off | **PASS** — identical numbers to A1 |
| A3 reversed locks | **failed the gate, as required** |

A1/A2: brute force `C* = 3` via `S=(0,1,2)`; outer IHS `C* = 3` in 4 rounds / 3 MILP
solves; lazy B&C `C* = 3`, `enfolp=1 check=10 separations=4 cached=7 cuts_added=3`;
independent cut re-derivation PASS; `solver_asserted_dual = 3.0`;
`certified_lower_bound = 3` (lattice-lifted 3).

### A3 is the load-bearing result

With reversed locks SCIP returned `status=optimal` and `obj=8` — the true optimum is 3 —
having fired the enforcement callback **zero** times and added **zero** cuts. No error, no
warning. And:

    solver_asserted_dual = 8.0     <-- EXCEEDS the true C* = 3
    certified_lower_bound = 3      <-- correct, did not follow

**Had SCIP's dual bound been published as `L`, this run would have emitted a false
certificate.** The independent exact-Fraction Lagrangian over the archived cuts was
unaffected because it does not depend on the solver's search being correct. This is
empirical confirmation of the "two different lower bounds" rule above, not merely a
theoretical argument for it.

### Defect found by the gate itself

The first A1 run failed on `separator inside the selected set`. A selected action's LP
constraint is `|d_i'z| <= tau_i`, but the returned point satisfies it only to solver
tolerance and sat a few ulps outside, so a strict comparison classified it as a separator
of the collision it forbids. Fixed with the guard band described above (`d69d53b`). This
also explains why the production `_cut_from_pair` receives the cover — that parameter is
not gratuitous, it hides this numerical problem.

### NOT covered — stated explicitly

- **`consenfops` was never invoked** (`enfops=0` under both presolve settings). The
  pseudo-solution path is implemented but **untested**; this instance always has an LP.
  It must not be reported as verified. Gate C needs a case that exercises it, or an
  explicit argument that the path is unreachable in the production configuration.
- Restart, cutoff, and multi-node paths are not exercised: A1 solves in a single node.
- Heuristic-supplied solutions are only observed indirectly via `check=10`; callback
  counts are not yet asserted per callback type.

### Early signal, not a conclusion

Persistent B&C performed **4 separations** against the outer loop's **4 rounds** — no
reduction in oracle calls on this instance. A 5-action instance cannot support any
extrapolation, and the hypothesis is about degenerate equal-cost faces which do not arise
here. Recorded because it is the first data point and points the same way as the Gate B/C
concern, not because it decides anything.

## Status

| gate | state |
| --- | --- |
| A | **PASS** (`d69d53b`), with `consenfops` coverage explicitly outstanding |
| B | not started |
| C | not started |
| D | not started |

A failed gate is archived verbatim as a negative result. "Significant speedup" is not an
acceptable summary of an unmet target, and a timed-out baseline is reported as
`> budget / T_new`, never as an infinite speedup.
