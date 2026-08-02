# PeakCert: the consolidated plan, and the one correction that changes its first step

PLAN 2026-08-02. Consolidates `PEAKCERT_OPERATOR_PREREGISTRATION.md`, `GB1_THE_NAIVE_MAJORANT_IS_VACUOUS.md`,
`MECHANISM_REVIEW.md`, `NUISANCE_BOUND_IS_NOT_AN_ESCAPE.md` and `GATE1_THE_RATIO_IS_REMOVABLE.md`
into one ordered plan. **Reviewed by Claude only** — Codex quota is exhausted until 2026-08-08, so
this has had no external adversarial pass and must be read as a single opinion, not a cross-check.

## The direction is already adopted; what is open is its foundation

An external analysis proposed switching the main line to **PeakCert / a proof-carrying pointwise
thermal operator**. That is not a change of direction — `PEAKCERT_OPERATOR_PREREGISTRATION.md` v2
already registers exactly it, and was already adversarially reviewed once (which caught a
mathematical error in its own conservatism bound, thresholds unsupported by 400x, an invalid kill
routing, and a one-sided treatment of a two-sided problem).

**What is open is that its foundation has already been measured and failed.**

## The measured failure, and why refinement cannot rescue it

`GB1` ran the registered symmetric residual majorant — the primary and only open route to a two-sided
pointwise envelope:

| cells/axis | dofs | vacuity factor (median) |
| ---: | ---: | ---: |
| 6 | 5 341 | **57.95** |
| 12 | 18 421 | **33.85** |
| 18 | 39 349 | **24.82** |

A bound reading "within +-25x the entire temperature rise" certifies nothing. And the decay is
`h^0.770` (0.776 then 0.765, consistently), with a structural explanation:

> each interior flux jump is `O(h)`, each face has area `O(h^2)`, and there are `O(h^-3)` faces, so
> **the total mass of the absolute-jump measure is `O(1)` and does not vanish under refinement.**

This was measured on a synthetic box of contrast **3.08**; the real package is **1.54e4**.

## The correction that changes step 1

The failure mechanism names its own fix. The majorant is vacuous because `|r|` makes every interior
flux jump **add** where the true solution cancels them in sign. The standard remedy is an
**equilibrated flux reconstruction** (Braess–Schoberl, Ern–Vohralik): build an `H(div)`-conforming
flux by local patch problems so the interior jumps are **identically zero**, leaving a volume-only
majorant.

**And the volume-only term is already known to be benign here.** `steady_heat_fem` uses P1 Lagrange
with DG0 coefficients, so `grad u_h` and `k` are both constant per tetrahedron and
`div(k grad u_h) = 0` exactly inside every element — the volume residual reduces to `f` itself, which
is exactly the argument that predicted a vacuity factor near **1** before the face term dominated.

> **So the prediction that failed was not wrong about the volume term; it was wrong to ignore the
> face term. Equilibrated flux removes the face term, and the original prediction becomes testable.**

**Step 1 is therefore NOT to re-run the naive majorant.** Re-running it would reproduce a known
negative result — the failure this repository's own rules name explicitly ("a number you compute that
matches one already committed is a signal you are re-running someone's experiment").

## Ordered plan

| gate | what | status |
| --- | --- | --- |
| **G0** | freeze a SHA in an isolated worktree, run the existing gates remotely, **persist source, inputs, environment, binaries and exit status as artifacts** | **owed** — this session ran the adjoint gates but left no artifact; commit messages are not evidence |
| **G1A'** | **equilibrated flux reconstruction**, then re-measure the envelope. Preregistered thresholds unchanged: median `<= 0.5 K`, P95 `<= 1 K`, zero false-SAFE, `>= 80 %` of near-limit instances decidable | **the only step that can falsify the main line** |
| **G1B** | legal mapping semantics and a conserving trace | partially advanced, see below |
| **G2** | decision separator: guard band rejects, PeakCert accepts, independent signoff safe, objective better | blocked on G1A' and G1B |
| **G3** | lazy adjoint rows | **demote to optional backend** — measured ceiling is 3.5–6.4 %, one factorisation costs 439–939 triangular solves |

## What G1B already has, from this session

* **`eblk0..3` == `dram_e0..e3` == `interposer_e0..e3`, established from the generator**, not inferred:
  `gen_floorplan.py:325,327` calls `gen_cover_flp` with **identical arguments** for `interposer.flp`
  and `dram.flp`, and its `_e0..e3` formulas are the ones `gen_sys_floorplan:280-283` uses for
  `eblk0..3`. The endpoint audit had called this "plausible but not established".
* With the missing heat placed there and weighted by area, **5 of 6 dev points survive** and the
  `arch_b -> arch_c` headline is **strengthened**, not broken. `MISSING_ENERGY_SENSITIVITY.md`'s
  proportional placement is superseded and demoted to the pessimistic bracket.
* **Still open:** the central `dram`/`interposer` share has no home in `output_3D.flp`; the NoC
  over-count (+33.41 %) and its uniform spreading are untouched.

## What must not be repeated

* Do not re-run the naive majorant to "confirm" 21–64x.
* Do not spend the Tier-2 authorisation on robust rows over a guessed nuisance set: measured vacuous
  under every support except the one now established, and vacuous even there on `transformer/arch_b`.
* Do not claim a speed contribution from lazy rows.
* Do not quote `1.061 K` or `106x` as repository-wide; the combined three-package range is
  `0.251 – 1.4332 K`, i.e. `25 – 143x`.
