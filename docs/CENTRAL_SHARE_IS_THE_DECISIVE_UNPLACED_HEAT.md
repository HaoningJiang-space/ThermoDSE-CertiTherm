# The favourable placement puts heat where the ptrace says there is none

RESULT 2026-08-03. NON-CLAIM, computed from committed operators and the audit ledger. **No frozen
thermal input was changed.** Sharpens the open Tier-2 item in
`NUISANCE_BOUND_IS_NOT_AN_ESCAPE.md` from "the central share has no home" into a quantified
statement about why that item decides the headline.

## The two source facts, and they point opposite ways

`NUISANCE_BOUND_IS_NOT_AN_ESCAPE.md` established from the generator that
`eblk0..3 == dram_e0..e3 == interposer_e0..e3` — `gen_floorplan.py:325,327` calls `gen_cover_flp`
with identical arguments for both files. Placing the missing heat on those four frame blocks and
weighting by area, **5 of 6 development rows survive** and the `arch_b -> arch_c` headline is
strengthened.

But the same generator, read one line further, says where the power actually goes:

    gen_cover_flp(...):
      name_e0 .. name_e3   the four frame strips
      name                 coreWidth x coreHeight at offset (eblk_w, eblk_h)   <- the sys area itself

and `THERMODSE_ENDPOINT_AUDIT.md:138` records what the ptrace does with them:

> `interposer` carries `sum(nop)/latency`; **`interposer_e0..e3` are zero.**

**So the frame — where the favourable result places the heat — is exactly where the trace puts
none of it, and the central block, which carries all of the NoP power, maps to the sys area.**

`NUISANCE_BOUND` states this limitation itself at line 115: *"The central `dram`/`interposer` blocks
are NOT placed by this. Only the four edge blocks are established."* This document quantifies what
that omission is worth.

## How much of the missing energy has an established destination

From the audit's ledger, which closes to zero residual:

| source | energy (pJ) | share of the missing | destination |
| --- | ---: | ---: | --- |
| DRAM | 3.7405e9 | 78.82 % | `dram` + four edge strips; the split is **not** established (the placing code is commented out) |
| **NoP** | **1.0052e9** | **21.18 %** | **the central `interposer` block, established** |

So **at least 21.18 % of the missing energy has a destination the generator fixes, and that
destination is the sys area.**

## What that share alone does, bounded

The greedy uplift is linear in the added power (`h_Q(r_j) = dP * max_i R_ji`), so the NoP share
scales exactly from the all-blocks column already measured:

| case | slack (K) | `eblk` support, **all** `dP` | **NoP share only, core support** | |
| --- | ---: | ---: | ---: | --- |
| resnet50/`arch_b` | 6.608 | 3.02 ✓ | **15.14** | ✗ |
| resnet50/`arch_c` | 8.839 | 1.57 ✓ | **7.36** | ✓ |
| **transformer/`arch_b`** | 2.989 | 5.08 ✗ | **27.57** | ✗ |
| **transformer/`arch_c`** | 6.299 | 4.17 ✓ | **15.52** | ✗ |

**Three of four are vacuous on the NoP share alone — including `transformer/arch_c`, which is the
destination the `+32.1 %` headline recommends.**

## What this does and does not establish

**It does not show the headline is wrong.** The greedy bound places all of the share on the single
worst-coupled block, and the central block covers the **whole sys area** — a source spread over that
area is far milder than a point load on its hottest member. The true figure is somewhere between the
uniform spread and this bound, and nothing here locates it.

**It shows the question cannot be dodged.** The central block has **no column in any operator**,
because it has no entry in `output_3D.flp`. Its row `R_{j,central}` does not exist, so its effect is
not merely unmeasured — it is **uncomputable without the Tier-2 placement**. And the bound above is
loose enough to allow either answer while being tight enough that "assume it is small" is not
available: on the headline's own destination it exceeds the slack by 2.5x.

**And it removes the option of resting on the favourable reading.** The `eblk`-only result is
correct about the frame's geometry and silent about the frame's power, which the trace sets to zero.
Quoting "5 of 6 survive" without the central share attached quotes a placement the generator
contradicts.

## The Tier-2 action this names, precisely

Place the central `dram` and `interposer` blocks in `output_3D.flp` at `coreWidth x coreHeight`,
offset `(eblk_w, eblk_h)`, per `gen_cover_flp`, and rebuild the operators so `R_{j,central}` exists.
Then the NoP share is a matrix-vector product rather than a bound, and the DRAM split — the
remaining 78.82 %, whose own placing code is commented out — becomes the only open term.

Until then, every statement about whether the missing heat is survivable is a statement about the
frame only, and must say so.
