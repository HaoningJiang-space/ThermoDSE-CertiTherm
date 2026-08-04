# Item 2: the archive's EDYP is a multi-network product, and it is bracketed rather than identified

RESULT 2026-08-05. NON-CLAIM, measured on `arxv001` through the pinned submodule.
**No external review** — Codex quota-locked to 2026-08-08.

## The question

`docs/THIRTEEN_REASSURING_NUMBERS.md` lists EDYP among the load-bearing quantities with no
independent check: the archive's stored EDYP and this project's recomputed `E·D/Y` differ by a
**non-constant** factor of `0.0172-0.0204`, so they are not the same quantity and mixing them
compares a number against a different number with the same name.

## What was measured, on one design

`chiplet_eva.py:234` prints `self.energy * self.latency / self.die_yield`, where both terms are
**totals accumulated across the networks the evaluator was given**. So the quantity scales roughly as
`n²` in the number of networks, and the comparison depends entirely on which suite was used.

| networks evaluated | `ΣE` (mJ) | `ΣD` (ms) | `ΣE·ΣD/Y` |
| --- | ---: | ---: | ---: |
| 1 — `resnet50` alone | 10.6115 | 1.3930 | **14.98** |
| 2 — the frozen dev split | 29.2132 | 3.4050 | **100.79** |
| **13 — all of `workloads.tsv`** | 145.5600 | 25.7373 | **3 795.88** |
| | | **archive's stored value** | **834.14** |

**The archive's number sits between the 2-network and 13-network sums, and matches neither.** It is
more than the dev split and less than the whole table.

## What this establishes, and what it deliberately does not

**Established.** The archive's EDYP is a **product of totals over a multi-network suite**, not a
per-network quantity. Our per-workload `E·D/Y` is therefore a **different quantity**, which is why
the ratio was never constant, and the paper's practice of recomputing both sides from its own runs
and saying "our EDYP" is correct and stays.

**Not established: which suite.** `834.14` is bracketed by `(2, 13)` networks. Identifying the exact
subset by searching for the combination that reproduces `834.14` would be **fitting, not measuring** —
this project has a standing rule against a number obtained by trying alternatives until one matches,
and a fitted suite would then be quoted as a fact. The subset is recoverable only from ThermoDSE's own
search configuration, which is not in the pinned archive files.

**So the oracle for EDYP is partial and is reported as partial.** What it rules out is the thing that
mattered: EDYP is not comparable across network counts, so no table may place the archive's column
beside ours. What it leaves open is which networks the archive used, and that is a question for the
upstream tool's configuration, not for a measurement here.

## The registry-split filter, which is what hid this for a round

Four of the networks did not run at first because `capture_frozen_inputs` filtered the workload table
by the frozen registry split, which holds **2 of 13**. The filter is correct for claim-grade work — it
is what makes the dev/held-out separation real — and it is exactly wrong for reproducing an upstream
number computed over a different set. `workload_row` now lifts it the same way `arch_row` lifts the
architecture filter, and refuses a row whose id disagrees with the one the outputs are named from.
