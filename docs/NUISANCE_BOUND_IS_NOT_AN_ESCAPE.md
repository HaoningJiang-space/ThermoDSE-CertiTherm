# Bounding the missing heat does not rescue the certificate — measured

RESULT 2026-08-02. NON-CLAIM probe, `moe-server`, existing operators and captures, nothing changed.
Tests round-4 peer review's Rank-2 mechanism **before** any Tier-2 work is spent on it.

## What was tested

Rank 2 proposes writing `p = p_map(x) + q` with `q` in a nuisance set `Q` covering the DRAM, NoP and
NoC-correction heat the trace omits, and relaxing each thermal row by the support function
`h_Q(r_j) = sup_{q in Q} r_j q`. **Its stated attraction is that it does not require placing the
missing sources** — only bounding them — so it would sidestep the Tier-2 trace change entirely.

Its stated danger, from the same review: a weak `Q` makes every row vacuous. That is now measured
rather than feared.

`Q` = `{q >= 0, supp(q) in S, sum q = dP}` with `dP = 0.9996 x sum(p_map)` from the audit closure,
so `h_Q(r_j) = dP * max_{i in S} R_ji` — a greedy fill, exact and free. A row survives iff
`h_Q(r_j) < slack_j`.

## Result: only one support keeps rows alive, and it is the one nobody has established

| case | slack (K) | `dP` (W) | all blocks | filler (47) | **`eblk` (4)** | `io` (80) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| resnet50/`arch_a` | 8.808 | 14.21 | 100.25 ✗ | 8.97 ✗ | **1.74 ✓** | 47.87 ✗ |
| resnet50/`arch_b` | 6.608 | 23.14 | 71.47 ✗ | 17.20 ✗ | **3.02 ✓** | 43.56 ✗ |
| resnet50/`arch_c` | 8.839 | 13.68 | 34.75 ✗ | 8.43 ✓ | **1.57 ✓** | 20.29 ✗ |
| transformer/`arch_a` | 6.460 | 28.79 | 203.15 ✗ | 18.17 ✗ | **3.52 ✓** | 97.00 ✗ |
| **transformer/`arch_b`** | **2.989** | 41.49 | 130.15 ✗ | 16.18 ✗ | **5.08 ✗** | 74.97 ✗ |
| transformer/`arch_c` | 6.299 | 28.85 | 73.26 ✗ | 17.72 ✗ | **4.17 ✓** | 42.74 ✗ |

**Two findings, and both are negative for the escape route.**

1. **The mechanism survives only by confining the missing heat to the four `eblk` blocks** — and
   `docs/THERMODSE_ENDPOINT_AUDIT.md` §4 states in terms that the filler reading of `eblk*` is
   *"plausible but does not establish it"*, and withdraws an earlier "reserved DRAM positions"
   hypothesis. So **Rank 2 rests on exactly the geometric claim that Tier-2 work would have to
   establish.** It does not sidestep the trace problem; it renames it.
2. **`transformer/arch_b` is vacuous under every support tested**, including `eblk`-only
   (5.08 K against 2.989 K of slack). That is the design the entire `arch_b -> arch_c` headline is
   about. **The headline decision cannot be certified under any nuisance bound measured here.**

## What this settles

* **"Bound, don't place" is not a cheaper alternative.** Every support loose enough to be defensible
  without new evidence is vacuous; the only non-vacuous support is an unestablished physical claim.
* The Tier-2 authorisation should therefore **not** be spent building robust rows over a guessed `Q`.
  It should be spent on the evidence that would make a support defensible — i.e. establishing where
  DRAM and NoP heat physically goes — which is the same work either way.
* `io`-only being vacuous everywhere is worth noting separately: NoP and PHY heat placed on IO blocks
  would swamp every row, so the lumped `interposer` column is not merely a loss of spatial
  information — **any plausible placement of it is decision-changing.**

## Scope

Six dev points, `standard` package, `grid512`, block-average rows, nominal map, one `dP` taken from
one architecture's audit closure and scaled by total power. The supports are name-family guesses, not
measured source locations — which is the point: **no measured source location exists, and that is the
blocking gap.**

---

# ESTABLISHED FROM SOURCE: `eblk0..3` IS where DRAM and NoP go, and it changes the verdict

`docs/THERMODSE_ENDPOINT_AUDIT.md` §4 called the filler reading of `eblk*` *"plausible but does not
establish it"* and withdrew an earlier "reserved DRAM positions" hypothesis. **It is now established,
by one grep of the generator rather than by geometry comparison.**

`ThermoDSE/core/gen_floorplan.py:325,327` (and again at `:434,436`):

```python
gen_cover_flp('interposer', sys_width, sys_height, eblk_w, eblk_h, output_file)   # interposer.flp
gen_cover_flp('dram',       sys_width, sys_height, eblk_w, eblk_h, output_file)   # dram.flp
```

**Identical arguments.** And `gen_cover_flp` (`:202-209`) emits `name_e0..e3` with the same four
formulas `gen_sys_floorplan` (`:280-283`) uses for `eblk0..3`. So

> `dram_e0..e3` == `eblk0..3` == `interposer_e0..e3` — **the same four physical frame positions**,
> by construction, not by inference from byte-identical geometry.

The central `dram` and `interposer` blocks likewise map to the sys area itself, which is why neither
can simply be appended to `output_3D.flp`: they would overlap the compute blocks in a planar model.

## What this does to the numbers

The support restriction is no longer a guess, so the adversarial reading over `eblk` is replaced by
the physically motivated one — a uniform source over the four frame blocks, weighted by their areas
from the capture's own floorplan text:

| case | slack | adversarial over `eblk` | **by area over `eblk`** | verdict |
| --- | ---: | ---: | ---: | --- |
| resnet50/`arch_a` | 8.808 | 1.737 | **1.417** | OK |
| resnet50/`arch_b` | 6.608 | 3.017 | **2.398** | OK |
| resnet50/`arch_c` | 8.839 | 1.570 | **1.315** | OK |
| transformer/`arch_a` | 6.460 | 3.520 | **2.871** | OK |
| **transformer/`arch_b`** | **2.989** | 5.075 | **4.243** | **VACUOUS** |
| transformer/`arch_c` | 6.299 | 4.173 | **2.908** | OK, **3.39 K left** |

**Two corrections to earlier documents follow.**

1. **`docs/MISSING_ENERGY_SENSITIVITY.md` was pessimistic and its placement is superseded.** It
   spread the missing heat *proportionally to the existing map*, i.e. onto the hot compute blocks,
   and concluded `transformer/arch_c` falls to `+0.750 K`. The generator says the heat belongs on the
   **cool frame**, where the same watts leave **3.39 K**. Proportional placement is not the physical
   case; it is now the pessimistic bracket, and it should be read as one.
2. **The `arch_b -> arch_c` headline SURVIVES and is strengthened.** `arch_b` is refused with more
   margin than before, and `arch_c` still certifies. The earlier reading — that the missing energy
   makes the decision unresolvable — held only under the superseded placement.

## What is still open, and it is smaller than it was

* `transformer/arch_b` is vacuous under every support including the established one. That is the
  design being *refused*, so it does not threaten the headline — but it does mean **no positive
  statement about `arch_b` is available**, only a refusal.
* The central `dram`/`interposer` blocks are NOT placed by this. Only the four edge blocks are
  established; the central share has no home in `output_3D.flp` and remains the open Tier-2 question.
* The NoC over-count (+33.41 %) and its uniform spreading are untouched by any of this.
