# Run log: `archive-census-v1`

Companion to `docs/ARCHIVE_CENSUS_PREREGISTRATION.md`, which is frozen and must not be edited. This
file records every operational decision taken while executing it, in the order taken, **with the
verdict not yet read at the time each was made**. Anything here that changes what the certificate
computes is stated with its direction: whether it can raise or only lower the certified fraction.

## Timeline

**Freeze.** `658163a`, X = 20 %, Y = 30 %, before any archive design was run through the pipeline.

**Stage 1, captures.** 64 of 64 succeeded. 0 UNRESOLVED.

**Observation, not a decision.** The archive's reported peak and this pipeline's re-derived peak are
far apart: for `arxv056` the archive says 328.5 K and the re-derivation gives 320.4 K. The
preregistration already declared them different quantities and used the archive's only to define the
candidate set. The magnitude was not anticipated and is recorded here.

**Decision 1 — the FEM mesh was raised from `n = 64` to `n = 192`.** `n` is the `min_lateral_cells`
argument; `_axis_nodes` bisects past it, so the meshes actually built are **80, 160 and 320 cells per
lateral axis**. The mesh is sized by the 60 mm package box, so a small die gets proportionally fewer
cells: the archive's smallest die is 5.72 x 11.88 mm and got ~7.6 cells across, against ~33 for the
development architectures. Measured on that design, the model-form band moves
**0.6093 -> 0.6673 -> 0.6905 K** (contraction 2.5 per doubling, observed order ~1.32, Richardson
limit ~0.706 K).

*Direction:* **measured across the whole census, not asserted.** Peer review was right that FEM
refinement is not monotone in the signed quantity `max_{j,p} [T_FEM,j(p) - T_ref,j(p)]`, so "raising
the mesh can only lower X" does not follow from one design. Both operator sets exist for every
design, so it was measured at span 0.30 on the 62 designs that had both:

| | `n = 64` | `n = 192` |
| --- | --- | --- |
| model-form band | 0.1754 - 1.1227 K (median 0.6007) | 0.1793 - 1.2261 K (median 0.6444) |

The finer mesh gives a **larger** band -- the stricter direction -- on **61 of 62 designs (98 %)**,
by a median of +0.0461 K and at most +0.1705 K. The single exception, `arxv002`, moves the other way
by **0.0006 K**. So the direction holds empirically with one negligible counterexample, which is a
measurement and not the theorem the earlier wording implied.

*Protocol status:* the preregistration fixes the FEM **tolerances** and not the mesh, so this is not
a protocol change. The `n = 64` operators are retained on disk as the convergence evidence.

**Decision 2 — three designs fell back to the CPU HotSpot reference.** `arxv047`, `arxv052` and
`arxv054` were refused by the CUDA solver's own residual self-check
(`residual = 1.1526e-8` against `limit = 1.1422e-8`, 0.9 % over). **That check was not relaxed.**
The build was repeated on the CPU reference implementation, whose operators were measured
**bit-identical** to the GPU ones earlier the same day (`_merged_models` parity: exactly 0.0 K/W on
`grid128` and `grid256`).

*Direction:* **relative to the alternative actually available, it can only raise X or leave it
unchanged.** The alternative was not "a valid GPU operator" -- the GPU refused -- it was UNRESOLVED,
and UNRESOLVED designs stay in the fixed denominator. So omitting the fallback would have capped X at
95.3 %. Relative to a hypothetical valid GPU build the substitution could move a design either way.

*Superseded by Decision 5.* `arxv047` completed on the CPU. `arxv052` and `arxv054` did not -- they
hit the hard-coded 300 s per-solve timeout, which is a wall-clock guard against a hung process and
not a physical bound. Rather than raise it and wait an hour per design, the underlying refusal was
repaired; see below.

**Decision 5 -- the CUDA solver now restarts on the exact residual, and that repaired the refusal.**
The rejection was a known and documented failure mode of the solver's own stopping rule: PCG halts on
the *recurrence* residual, which drifts optimistic after hundreds of updates -- the source comment
says so and carries a 0.5x safety margin for it -- and the freshly computed `b - Gx` residual then
landed 0.9 % over tolerance. **The tolerance was not relaxed.** Instead the solver re-anchors the
recurrence on the exactly computed residual and continues from the current iterate, which is the
standard restart cure and costs one extra sparse product per pass.

*Result:* both designs solve in **32-33 s on the GPU**, against a CPU attempt that had not finished
after an hour.

*Parity, measured rather than argued:* rebuilding `arxv008` -- a design the pinned solver **accepted**
-- with the refined solver gives `max|dResponse| = 0.000e+00 K/W` and `max|dAmbient| = 0.000e+00 K`.
**Bit-identical.** The restart only fires where the pinned solver would have failed, so the two
designs built with it are not a different operator from the other 62.

*Direction:* it converts two UNRESOLVED designs into real verdicts, which may be CERTIFIED or
REFUSED. Not directional.

*Protocol status:* the preregistration fixes the reference model (`grid512-avg`), not the
implementation that computes it, and the parity above shows the implementation is the same map. The
pinned build is untouched; the refined solver lives in a parallel GPU build root whose receipt covers
it, so a new binary can never be paired with the pinned build's `GPU_SHA256SUMS`.

**Decision 3 — the class-total constraints are now honoured.** Peer review found that
`peak_over_polytope` and `one_sided_containment_bounds` received only the box, dropping the
`a_ub`/`b_ub` rows of the declared uncertainty set and therefore bounding a **larger** set.

*Direction:* dropping constraints is sound but loose, so honouring them can only raise X. **The
measured effect is zero.** The redundancy is a theorem for this construction --
`upper_i = min(q_i(1+s), Q_C) <= q_i(1+s)` gives `sum_C p_i <= (1+s) Q_C = b_C` for every point of the
box, independently of the global equality -- so the class caps cut nothing off. What is
instance-specific is that the slack is *exactly* zero: a singleton class has `upper = min(q(1+s), q)
= q` against a cap of `q(1+s)`, leaving slack `s*q > 0`. The general statement is `b_ub - a_ub @
upper >= 0`, which is what the test asserts; it measured 0 to machine precision on the instances
tried. The LP agrees with the greedy to 1.07e-9 K across every peak and band on the development
split.

**Decision 4 — three fail-closed gaps closed before the verdict ran.** The certifier did not read
the FEM ledger, so the preregistered 1e-6 tolerances on energy balance, impulse power and zero-solve
offset were never enforced; the frozen constants were imported without being checked against the
values the protocol names; and the comparison was `slack > 0` where the protocol says `<=`, i.e.
zero slack certifies.

*Direction:* the first two can only lower X (they can turn a design UNRESOLVED); the third can only
raise it, and by at most the designs sitting at exactly zero slack.

## What is NOT recorded here because it did not happen

No threshold was moved. No design was removed from the denominator. No uncertainty set, span,
reference model or workload was added or swapped after the freeze. The held-out splits were not read.
