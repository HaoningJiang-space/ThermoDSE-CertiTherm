# V6 direction decision — return CertiTherm to physical decision fidelity

Status: research direction decision, based on repository history through the V6 physical
trace gate.

## Verdict

The project did drift, but the original scientific question remains worth pursuing.

The useful core was always: **when may a chiplet DSE safely decide with a cheaper thermal
abstraction, and what is the minimum additional physical information needed when it may
not?** The drift was execution order. The history invested heavily in collision LPs,
MaxHS/deletion policies, exact bounds, GPU operators, kernels, and synthetic report
libraries before establishing that the workload trace, communication route, geometry, and
temperature decision all referred to the same physical system.

V6 found that this ordering was unsafe:

- the original HotSpot path drops or misplaces enough external energy to leave a 25%–50%
  net source mismatch across the six registered cases;
- NoP energy is addressed to a floorplan name that does not exist and DRAM heat is absent;
- the legacy route index aliases external columns with compute rows;
- some cross-chiplet physical edges are charged as NoC;
- correcting the route changes objective magnitudes by up to 13.13%;
- artificial action costs and an extrapolated production cost were not defensible.

Therefore the earlier solver results may remain engineering assets, but they are not the
paper's scientific evidence until their state sets, reports, and decisions are regenerated
from the corrected physical ledger.

## First-principles reset

For a chiplet system, placement, communication, package boundaries, and workload scheduling
are coupled. A byte crossing a die boundary has a different latency, energy, and heat
location from an on-die byte. One physical communication ledger must therefore drive all
three quantities. A scalar total-power match cannot repair a spatially wrong source.

For thermal analysis, temperature is the convolution of spatial-temporal power with the
package's thermal response. The relevant safety quantity is a local maximum with an
initial/boundary condition and an error bound, not average power or a cold one-cycle trace.
Spatial fidelity should precede temporal fidelity because a time-resolved replay of
misplaced heat is only a more expensive wrong answer.

These principles imply the refinement order:

1. source and unit conservation;
2. route and boundary semantics;
3. named geometry and spatial peak fidelity;
4. periodic temporal fidelity for unresolved margins;
5. an independent signoff model or abstention.

## What the present evidence says

The corrected path can produce energy-conserving, floorplan-aligned traces for two real
ThermoDSE workloads and three registered candidates. Under block and `grid64-avg`, temporal
uplift never changes feasibility, thermal order, or architecture selection; the largest
uplift is 0.144 K. Spatial model differences are larger in all six comparisons and create
a 33.01% decision-regret case.

A finer safety semantics produces one narrow counterexample: Transformer/`arch_b` is
329.904867 K under time-mean `grid64-max` but 330.19 K under periodic replay. At
`grid128-max`, the corresponding values are 329.918874 K and 330.20 K. The flip is
unchanged across 0.25/0.5/1.0 us steps and the two grids. Its meaning is not “transient
should be run everywhere.” Its HotSpot-bounded meaning is “transient can be a necessary
final refinement for candidates whose steady safety margin cannot dominate temporal and
model error.” An independent model must still validate the physical conclusion.

## Better paper

The stronger DAC/ICCAD paper is not a generic minimum sensor problem, a faster MaxHS paper,
or a transient HotSpot study. It is:

> **Decision-certified adaptive thermal fidelity for chiplet DSE:** a physical-ledger
> pipeline that cheaply accepts candidates only when a lower-fidelity result is
> decision-invariant, escalates spatial and temporal fidelity when the margin is
> insufficient, and returns an independently replayable witness or abstains otherwise.

The load-bearing result must be an end-to-end systems result on genuine top-K frontiers:
zero missed unsafe selections relative to independent signoff, materially fewer expensive
analyses, and bounded decision regret. Proof machinery supports this result; it is not the
headline.

The paper is not strong-accept ready with the present 2 x 3 matrix. It still needs:

- at least four materially different workloads and real top-K frontiers, not three chosen
  architectures;
- corrected route/objective regeneration for every candidate;
- `grid128-max` or finer convergence and an independent 3D-ICE/FEM-class replay of every
  escalated boundary case;
- characterized package/DRAM geometry, leakage policy, and explicit error budgets;
- measured cold/warm production-pipeline cost with counterbalanced execution;
- policy baselines: always coarse, always signoff, fixed two-stage, uncertainty/margin
  heuristic, and the proposed certificate/abstention policy;
- pre-registered metrics: missed infeasibility, selected-design regret, signoff count,
  wall time/core/GPU seconds, abstention rate, and certificate coverage;
- held-out evaluation after the method and thresholds are frozen.

### Prior-art boundary

The paper must be positioned more narrowly than “multi-fidelity thermal modeling.”
MFIT already presents fast multi-fidelity thermal models for 2.5D/3D multi-chiplet
architectures (`arXiv:2410.09188`). RapidChiplet already combines fast chiplet
interconnect, cost, and thermal-stability exploration (`arXiv:2311.06081`), while
ThermoDSE already jointly explores architecture, mapping, communication, area, yield, and
thermal constraints (`arXiv:2607.07096`). HotSpot is explicitly a compact
architecture-level RC model, and 3D-ICE is an established transient compact model for 3D
IC stacks.

Consequently, a fidelity ladder, another surrogate, or another chiplet DSE wrapper is not
enough novelty. CertiTherm has to contribute the **decision-level correctness contract**:
when a cheap result is sufficient, when escalation is mandatory, what replayable evidence
supports that decision, and what the system does when models disagree.

## Stop rules

Do not add another solver, kernel, synthetic feature family, or headline theorem before the
independent-model gate below is closed. Reject the transient headline if the boundary flip
fails 3D-ICE/FEM-class convergence. Reject the adaptive-fidelity headline if a simple
margin-triggered two-stage baseline achieves the same safety and cost on the top-K study.

## One goal

> **Build and freeze a corrected physical-ledger top-K benchmark over at least four
> workloads, then demonstrate that a decision-certified spatial-to-transient refinement
> policy matches independent 3D-ICE/FEM signoff with zero missed thermal infeasibility and
> zero selected-design regret while reducing measured expensive-signoff work by at least
> 5x against always-signoff; otherwise reject the CertiTherm adaptive-fidelity paper.**

This is one falsifiable goal. It makes physical correctness, decision value, and system
cost pass together, and it prevents further optimization of an unvalidated abstraction.
