# The 330 K limit removed from the premise: report the interval of limits where the rules disagree

RESULT 2026-08-05. NON-CLAIM, pure post-processing of peaks already on disk; no solver.
`research/triangle/robustness/limit_parametric_disagreement.py`. **No external review** — Codex
quota-locked to 2026-08-08.

## The attack, and why it was the most fragile premise in the round

`CertiTherm/frozen_limits.py` fixes `THERMAL_LIMIT_K = 330.0` and **gives no source**. ThermoDSE's own
`348 K` is documented as unsupported. Every verdict this round is relative to that number, and moving
it to 335 K makes nothing fail — the paper would evaporate.

## The dependence is removable, and the algebra says so in one line

For a design with nominal peak `T_nom` and certified peak `T_cert` over the declared envelope:

    the incumbent's rule ACCEPTS   <=>  T_nom  <= L
    the envelope rule REFUTES      <=>  T_cert >  L - margin - linearisation
    both, i.e. they disagree       <=>  T_nom  <= L  <  T_cert + margin + linearisation

The disagreement set is an **interval of limits**, and its width

    W = (T_cert - T_nom) + margin + linearisation

**contains no `L` at all.** It is the envelope's uplift over the point evaluation plus the decision
margin — a property of the design and the declared envelope, and of nothing else.

So the claim stops being *"at 330 K the incumbent accepts a design we refute"* and becomes

> **For every design measured there is a band of thermal limits, `W` wide, on which the incumbent's
> nominal-peak rule accepts a design the envelope certificate refutes.**

No limit to defend, and the population is every case with a pair of peaks rather than the handful
near 330 K.

## Result over 229 cases

| | K |
| --- | ---: |
| width, min | 0.0845 |
| width, **median** | **1.3165** |
| width, max | 2.4745 |
| cases with a non-empty interval | **229 / 229** |
| cases whose interval contains 330 K | 13 |

**Every case measured has a non-empty disagreement band.** `330 K` lies inside 13 of them, so this
round's specific findings at 330 K are a **sample of a general phenomenon**, not an artefact of the
limit.

## What the reader has to be told, and it is in the driver's own output

```
read 229 distinct cases; 242 came through the legacy name table and 8 files yielded nothing.
EXCLUDED 1 case whose certificate does not respond to the envelope: arxv034
```

* **242 legacy reads** — most of the population still comes through the pre-contract name table
  (`case_record.py`); 122 archive radius files predate the declaration. The counter is reporting that
  the migration is partial rather than hiding it.
* **8 files yielded nothing**, six of which are operator manifests that legitimately have no cases.
* **1 exclusion**, named: `arxv034`'s envelope is a singleton (`ADVERSARIAL_SELF_REVIEW.md` E1), so
  its certificate does not respond to the envelope and it is not a data point. Excluded and
  **counted** — an earlier version refused the whole *population* over this one case, which is a
  different fail-closed behaviour and the wrong one.

## What this does NOT do

* **It does not establish that 330 K is wrong or right.** It makes the finding independent of the
  answer. A reader with a limit in `[T_nom, T_cert + 0.06)` for some design reads the disagreement
  off the table; a reader outside every band reads that the two rules agree for them.
* **It does not remove the limit from the certificates themselves.** `CERTIFIED`/`REFUTED` verdicts
  elsewhere in this round are still stated at 330 K and still need the provenance, or the
  model-relative phrasing (`A_VERDICT_IS_RELATIVE_TO_A_DECLARED_MODEL.md`).
* **`W` inherits the envelope.** It is `(T_cert − T_nom)` plus a constant, so a different declared
  envelope gives a different width — the span sweep
  (`THE_ENVELOPE_WIDTH_IS_NOT_WHERE_THE_DISAGREEMENT_COMES_FROM.md`) reports how it moves.
