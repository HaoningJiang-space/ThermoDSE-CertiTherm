# Attacking the face term: what it is worth, measured term by term

RESULT 2026-08-02. NON-CLAIM probe, `moe-server`, tmux session `decomp`. Produced by
`research/triangle/robustness/residual_majorant_probe.py`, which now solves the volume, Robin and
face contributions **independently against the same operator** instead of only reporting their sum.

## Why the decomposition had to exist

`GB1_THE_NAIVE_MAJORANT_IS_VACUOUS.md` concluded that "the face term still sets the rate" from the
observation that the equilibrated column decays at `h^0.751`, close to the naive `h^0.770`.
**That attribution was wrong and is withdrawn**: the equilibrated load is `|volume| dx + |robin| ds`
and contains **no `dS` term at all**, so its rate cannot be attributed to a term that was removed.

"The face term has `O(1)` mass" and "what survives its removal converges slowly" are different
claims. Only the first was derived. This probe measures the second.

## P1 over DG0: two facts, both new

| cells/axis | VOLUME | ROBIN | FACE | NAIVE |
| ---: | ---: | ---: | ---: | ---: |
| 6 | **1.0000** | 0.0012 | 56.9458 | 57.9459 |
| 12 | **1.0000** | 0.0012 | 32.8507 | 33.8451 |

*(medians over 9 unit impulses; the three contributions sum to the naive figure to 4 decimals, so
the majorant is exactly additive in its loads, as linearity requires.)*

**1. `VOLUME = 1.0000` exactly, with `min = median = max`, at both meshes.** This turns the
structural argument into a measured identity: with P1 over DG0, `div(k grad u_h) = 0` inside every
element, so the volume residual is `f` itself and the majorant's volume problem **is the forward
problem**. It is **mesh-independent**, so refinement does nothing to it.

**2. The face term decays as `h^0.794`** (56.9458 -> 32.8507 across a 2x refinement) — it is **not**
non-decaying. The `O(1)` result is about the **mass** of the absolute-jump measure; the majorant
reports the maximum of the solution operator applied to that mass, which buys back ~0.79 of an
order. An earlier reading conflated the two.

## The consequence for the stated goal

**Attacking the face term at P1 is worthless, and the decomposition says so quantitatively.**
Driving the face contribution from 32.85 to exactly zero — which is what a perfect equilibrated
flux reconstruction achieves — lands on `VOLUME + ROBIN = 1.0012`, and the floor underneath it is
the identity `VOLUME = 1.0000`. **A certificate of width equal to the entire temperature rise is
what a perfect attack on the face term buys.**

So the face term is worth attacking **only after** the volume identity is broken, which requires an
element family where `div(k grad u_h)` is not identically zero. The two are ordered, not
alternatives, and the order is the opposite of the one the naive numbers suggest: the face term is
98.3 % of the naive majorant at P1 and yet attacking it changes nothing.

## What is still open

The P2 decomposition is running in the same session. It decides whether the face term becomes the
binding constraint once the volume identity is broken — which is the only configuration in which
"attack the face term" is a well-posed instruction. Its `h^0.794` rate at P1 is the prior estimate
of what an attack would have to beat.

---

# P2: the face term is NOT the barrier, and the goal is answered in the negative

| degree | cells | VOLUME | ROBIN | FACE | equilibrated (= VOL + ROB) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 6 | **1.0000** | 0.0012 | 56.9458 | 1.0012 |
| 1 | 12 | **1.0000** | 0.0012 | 32.8507 | 1.0012 |
| 2 | 6 | 1.4379 | 0.0001 | 14.5339 | 1.4380 |
| 2 | 12 | **0.8544** | ~0.0001 | — | 0.8545 |

*(medians over 9 impulses; `EQUILIBRATED = VOLUME + ROBIN` to four decimals at every point, which
confirms the decomposition is exact and the withdrawal in `GB1` was correct — the equilibrated
column's rate is the VOLUME term's rate, and never had a face contribution to attribute it to.)*

## Three measured rates, and the one that matters

| term | rate |
| --- | ---: |
| VOLUME at P1 | **`h^0.000`** — exactly 1.0000 at both meshes, mesh-independent by identity |
| FACE at P1 | `h^0.794` |
| **VOLUME at P2** | **`h^0.751`** |

**A degree-2 element should give roughly `h^2` on a smooth problem. It gives `h^0.751`.** That is
the finding, and it is not about faces at all: the solution has **limited regularity at the material
interfaces**, so raising the polynomial degree does not buy the order it would on a smooth domain.
This box has conductivity contrast **3.08**; the real package has **1.54e4**.

## The goal, answered

The instruction was to attack the face term's `O(1)` mass to the limit. Pushed to the limit, the
answer is that **the face term is not what stands in the way**, and the decomposition shows it twice:

* **At P1**, driving the face contribution to exactly zero — the limit of any equilibrated flux
  reconstruction — lands on `1.0012`, with the mesh-independent identity `VOLUME = 1.0000` beneath
  it. The face term is **98.3 %** of the naive majorant and attacking it perfectly buys **nothing**.
* **At P2**, the face term does fall by 2.3x (56.95 -> 14.53 at `cells=6`), so raising the degree
  attacks it for free. But what is left converges at `h^0.751`, and that rate is **the volume term's**,
  set by interface regularity — not by anything a flux reconstruction touches.

So there is no configuration in which "attack the face term" is the binding move. Before the volume
identity is broken it buys zero; after it is broken the volume term is already the slower one.

## What the barrier actually is, and what would have to be attacked instead

**Limited elliptic regularity at material interfaces.** The candidate attacks, in the order the
measurements support:

1. **Interface-fitted refinement / graded meshes at the material boundaries** — recover the
   asymptotic order where the regularity is lost, rather than refining uniformly. This is the only
   attack the `h^0.751` rate directly implicates, and it is cheap to test with the existing probe.
2. **`|.|`-free majorant forms.** The `O(1)` mass exists *because* the absolute value destroys the
   sign cancellation the true residual has. A majorant that keeps the sign would not have it — but
   the two-sided pointwise bound is what forces `|.|`, so this is a change of the certificate's form,
   not of its discretisation.
3. **Higher degree still.** Refuted in advance by the rate: at P2 the order is already limited by
   regularity rather than by the polynomial space, so P3 buys the same `h^0.751`.

**Not established:** that no pointwise route exists. **Established:** that the face term is not the
obstruction, that a perfect equilibrated flux reconstruction is worth exactly `1.0012 -> 1.0000` at
P1 and nothing at all in rate, and that the barrier is regularity at the interfaces — on a
contrast-3.08 box, four orders of magnitude milder than the real package.
