# Measured cost of the thermal fidelity ladder

Answers the cheapest of the three go/no-go questions, and it needed no new
infrastructure: **is high-fidelity thermal analysis actually expensive enough that
choosing when to run it is worth anything?**

Until now every cost in `measurement_registry.tsv` was a hand-assigned `1/2/4/8`
(module-class actions are uniformly `1.0` across all 4159 rows), so the premise that cheap
analysis should be preferred over expensive analysis was unquantified — and so was the
"real report cost vs 1/2/4/8" ablation.

## Measurement

`research/triangle/fidelity_cost.py`, moe-server, clean clone at `ae323ea`, candidate
`arch_c` (`resnet50 c1`), **181 floorplan units**, 5 repetitions per model, HotSpot binary
built from the patched export. Inputs are materialised exactly as `experiments.py` does for
the operator build, so this is the cost of the analysis CertiTherm actually runs.

| model | solve median | solve range | operator build (181+1 solves) | ratio |
| --- | ---: | --- | ---: | ---: |
| `block` | **0.076 s** | 0.075–0.079 | 14 s | 1.00x |
| `grid64-avg` | 10.263 s | 10.224–10.326 | 1 868 s (31.1 min) | **135x** |
| `grid128-avg` | 32.613 s | 32.533–33.987 | 5 986 s (99.8 min) | **430x** |
| `grid256-avg` | 149.251 s | 149.124–149.589 | 27 168 s (**7.5 h**) | **1968x** |

Repetition spread is well under 1% (e.g. 149.124–149.589 s), so the shared host's competing
load did not contaminate these numbers.

## What it establishes

**The ladder spans ~2000x.** Building the finest registered operator for ONE candidate
costs 7.5 hours; the coarsest costs 14 seconds. Choosing when to climb the ladder is
therefore worth a great deal, and the multi-fidelity framing has real system value rather
than assumed value.

Concretely, for the family DSOS currently uses (`block` + `grid64-avg` + `grid128-avg`;
`grid256` is calibration-only):

| policy per candidate | operator cost | vs always-full |
| --- | ---: | ---: |
| always all three | 7 868 s (2.19 h) | 1.00x |
| `block` + `grid64-avg` only | 1 882 s (31.4 min) | **4.2x cheaper** |
| `block` only | 14 s | **562x cheaper** |

So the value of proving "the coarse model already determines the decision" is bounded above
by ~562x per candidate on this instance — not a rounding error. Over a top-K frontier the
absolute numbers scale with K: at K=20, always-`grid256` alone is ~150 machine-hours.

## What it does NOT establish

- Nothing about analyses further up the proposed ladder — placed transient power,
  fine RC/DSS transient, FEM/3D-ICE signoff — none of which are implemented here.
- Nothing about licence, queue, or engineer time in a real EDA flow; this is wall time of
  one open-source solver on one machine.
- Nothing about how *often* the coarse model suffices. A large ratio makes the question
  worth asking; it does not answer it. That is what the reachable-set and decision-margin
  work has to establish.
- One candidate, one package, one floorplan size (181 units). Grid solve cost is expected
  to scale with grid size rather than unit count, so the ratio should be stable across
  candidates, but that is an expectation, not a measurement.

## Consequence for the cost model

The frozen `1/2/4/8` action costs are not calibrated to anything measured. They are a
*relative* ordering within one report class, whereas the real spread across model fidelity
is three orders of magnitude. Any claim of the form "CertiTherm saves N% of measurement
cost" currently inherits the hand-assigned scale, and the "real report cost" ablation must
use measured numbers like these rather than the frozen constants.

Reproduce:

    python research/triangle/fidelity_cost.py artifacts/diag150b resnet50 1 5
