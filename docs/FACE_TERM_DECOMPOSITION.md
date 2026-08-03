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
