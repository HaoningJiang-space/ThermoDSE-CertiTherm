# Thirteen reassuring numbers in one round, and what separated the caught from the survivors

METHOD 2026-08-05. Written from this session's own record. Every entry below is a defect I introduced
or inherited, and **not one of them crashed**. Each produced a plausible number that a reader would
have accepted.

## The inventory

| # | the reassuring number | what was actually wrong | caught by |
| --- | --- | --- | --- |
| 1 | uplifts computed from `Q = 0.9997` | one architecture's audit closure applied to six; the true span is `0.3328-0.9997` and the value used was the **largest** | measuring it per case, on a hunch |
| 2 | "`interval` is geometry-invariant" | true on `arch_a` (which has `cut_x=cut_y=1`), false on `arch_b` and `arch_c` | measuring a second base |
| 3 | the uniform-spread "bound" | **not** an upper bound: below the routed placement on 4 of 6 points | building the routed operator |
| 4 | "the endpoint split moves the peak by **exactly 0.0 K**" | the parameter was accepted and never threaded to the placement | an exact `0.0` across five values is not a plausible insensitivity |
| 5 | mapping lower bound `345.32 K` | above an **attained** `327.55 K`; per-group column sums inflate by group size | reporting the **gap**, which came out negative |
| 6 | FEM cell operator | midpoint power assignment made a unit impulse dissipate **3.9 W** | the energy-balance gate |
| 7 | FEM cell operator, take two | unsnapped cell areas left `3.2e-06 W` | the same gate |
| 8 | `e_total = 4.99 K`, "fold it in" | two independent maxima; the tight form is `1.82 K` | deriving the one-maximum bound |
| 9 | `arxv034`: "radius 2.0, tolerates ±200 %" | the envelope is a **singleton**; it tolerates nothing | a supremum constant across a 2000-fold widening |
| 10 | "46 cases" in the population | the harvester guessed field names; one more fallback gave **230** | adding a fallback by accident |
| 11 | validation failures silently dropped | `except ValueError: return None` deleted the evidence the validation exists to surface | reading the handler |
| 12 | "`v61_render_evidence` is orphaned" | blanking string constants to exclude docstring prose also blanked the **subprocess path strings** | the deletion broke 5 tests |
| 13 | "all 6 candidates are depended on" | the oracle was dominated by `test_private_api_census`, which fails whenever **any** file is removed | a uniform answer is a suspicious answer |

## What separates the two halves

Look at the last column. The defects caught **fast** each had an **independent computation whose
failure mode differs from the thing it checks**:

* an **energy-balance gate** (6, 7) — it does not know what the operator is for, only that watts in
  must equal watts out;
* a **stored result to re-run against** (every refactor this round) — bit-identity is a check nothing
  can talk its way past;
* a **reported gap** (5) — a negative gap is arithmetically impossible, so the bound announced its own
  invalidity;
* a **test suite** (12) — it broke *collection*, which is louder than an assertion.

The defects that survived longest — 1, 2, 3, 9, 10 — had **no paired oracle at all**. They were
single computations, and a single computation cannot notice that it is wrong. Peer review would not
have caught them either: each was internally consistent and its output was in the plausible range.

> **A quantity is trustworthy in proportion to the independent check attached to it — not to the care
> in its derivation, and not to the review it passed.**

That is not a platitude here; it is the measured content of thirteen cases in one session.

## The corollary that decides what to do next

If the rule is right, then **the next wrong number in this project is in whichever load-bearing
quantity currently has no independent check.** That set is enumerable, and enumerating it is cheaper
than any of the thirteen repairs above.

| load-bearing quantity | independent check | status |
| --- | --- | --- |
| `sup_p` over the envelope | LP oracle vs greedy, agreeing to `1.07e-9 K` | **has one** |
| the cell operator | FEM reference, `Δ certified ≤ 0.071 K` | **has one** |
| the FEM operator | analytical identity `mean(T_top) = T_amb + r_convec·P`, ratio 1.000 | **has one** |
| the mapping optimum | exact per-cell assignment lower bound | **has one** |
| the routed lowering's energy | source/route reconciliation receipts, `< 1e-9` | **has one** |
| refactors | bit-identity against a stored run | **has one** |
| the routed lowering's placement, **core term** | `placement_oracle.py`: per-core energy from `monitor.core_dict` against the trace's per-block sums, worst relative **5.88e-16** on 16 cores | **has one, 2026-08-05** |
| the routed lowering's placement, **NoC/NoP/DRAM** | — | **none.** The route decides these, so the monitor has no per-block statement to compare against |
| **EDYP** | — | **none.** The archive's own EDYP is a different quantity (ratio 0.0172-0.0204, non-constant) and is deliberately not mixed in |
| the 330 K limit | removed from the premise: `THE_LIMIT_IS_NOT_A_PREMISE.md`, 229/229 cases have a non-empty disagreement band, median 1.3165 K, independent of `L` | **no longer needed, 2026-08-05** |
| the activity envelope | `test_envelope_never_collapses_silently.py`: 11 cases pinning that >1 block per class never collapses and 1 per class always does, at every span, from either bound | **has one, 2026-08-05** |

**Four quantities carried the paper with no oracle when this was written. Three now have one, and
the fourth's dependence was removed rather than checked:**

* the **core** placement reconciles to `5.88e-16` per core — the first check on *where* the heat
  lands rather than how much of it there is;
* the envelope's collapse is a pinned invariant instead of a one-off discovery;
* the limit is no longer a premise, so it needs no provenance for that finding to stand.

**What remains unchecked is named and is not small:** the NoC, NoP and DRAM **distribution**. The
route decides it, the monitor has no per-block statement about it, and its total is all that
reconciles. An oracle for it needs a second routing derivation, not a second reading of the same
one — and `physical_nop.py` already exists precisely because ThermoDSE's own route ledger was found
defective, so the second derivation cannot simply be that ledger.

## So the next work is not another result

It is to build the missing oracles, cheapest first:

1. **The placement.** An independent check exists and is cheap: ThermoDSE's own monitor counters give
   per-component energy, and the routed lowering already reconciles the *total*. Reconciling the
   **per-block** distribution against a second derivation — the legacy ptrace's own column semantics,
   which `THERMODSE_ENDPOINT_AUDIT.md` decomposed to zero residual — would pair it.
2. **EDYP.** Identify what the archive's stored EDYP actually aggregates. It is one ThermoDSE run over
   the full workload suite, and until it is identified the paper must say "our EDYP" every time.
3. **The envelope.** The class-total cap has now produced a singleton once (#9). A property test over
   the *population* of placed vectors — does the box ever collapse, and on which designs — turns a
   one-off discovery into a checked invariant.
4. **The limit.** Either a citation, or the limit-parametric restatement already built
   (`limit_parametric_disagreement.py`), which removes the dependence entirely.

Item 4 is done and unreported; item 3 is a test; items 1 and 2 are each one run. **None of them is a
new experiment — all four are oracles for numbers already published.**
