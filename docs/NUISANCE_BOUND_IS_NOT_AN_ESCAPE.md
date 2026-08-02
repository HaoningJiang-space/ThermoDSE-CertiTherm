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
