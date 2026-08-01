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

**Decision 1 — the FEM mesh was raised from `n = 64` to `n = 192`.** The mesh is sized by the 60 mm
package box, so a small die gets proportionally fewer cells: the archive's smallest die is
5.72 x 11.88 mm and got ~7.6 cells across, against ~33 for the development architectures. Measured on
that design, the model-form band moves **0.6093 -> 0.6673 -> 0.6905 K** for 80 -> 160 -> 320 cells per
axis (contraction 2.5 per doubling, observed order ~1.32, Richardson limit ~0.706 K).

*Direction:* a coarse mesh **understates** the band, which makes certification **easier**. Raising it
can therefore only lower X. It could not have been a rescue.

*Protocol status:* the preregistration fixes the FEM **tolerances** and not the mesh, so this is not
a protocol change. The `n = 64` operators are retained on disk as the convergence evidence.

**Decision 2 — three designs fell back to the CPU HotSpot reference.** `arxv047`, `arxv052` and
`arxv054` were refused by the CUDA solver's own residual self-check
(`residual = 1.1526e-8` against `limit = 1.1422e-8`, 0.9 % over). **That check was not relaxed.**
The build was repeated on the CPU reference implementation, whose operators were measured
**bit-identical** to the GPU ones earlier the same day (`_merged_models` parity: exactly 0.0 K/W on
`grid128` and `grid256`).

*Direction:* neither. A CPU-built operator can move a design either way, so this is not a
directional rescue. Had the fallback been omitted, those three would have been UNRESOLVED and would
have stayed in the denominator, lowering X by up to 4.7 points.

**Decision 3 — the class-total constraints are now honoured.** Peer review found that
`peak_over_polytope` and `one_sided_containment_bounds` received only the box, dropping the
`a_ub`/`b_ub` rows of the declared uncertainty set and therefore bounding a **larger** set.

*Direction:* dropping constraints is sound but loose, so honouring them can only raise X. **The
measured effect is zero**: `upper = min(placed * (1 + span), content_upper_bounds)` already implies
each class cap, `b_ub - a_ub @ upper` is zero to machine precision, and the LP agrees with the greedy
to 1.07e-9 K across every peak and band on the development split. Pinned by a test.

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
