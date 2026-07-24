# Literature Search: Decision-Complete Thermal DSE

Date: 2026-07-24

Search purpose: ground the proposal against chiplet DSE, information
discovery, abstraction refinement, and observation selection

Target venue/family: DAC / ICCAD / DATE; EDA, architecture, and optimization

Source-quality policy: primary and stable sources prioritized; policy-excluded
sources omitted

## Summary

- Closest conceptual work is split across four communities rather than one
  paper: thermal/chiplet DSE, decision-dependent information discovery,
  decision-robust feature acquisition, and CEGAR.
- None of the screened sources establishes the exact proposed combination:
  continuous placed-power worlds, architecture-decision equivalence, a
  hierarchy of EDA report abstractions, robust thermal replay, and
  proof-carrying minimum-cost refinement.
- Novelty remains **needs-search**, not proven. The generic refinement and
  information-purchase machinery is established; novelty must rest on the EDA
  property, formulation, physical evidence, and end-to-end capability.
- The strongest rescue from a generic “minimum observation” story is
  decision-complete EDA abstraction with a physically calibrated state family.

## Paper table

| # | Title | Year | Venue/source | Link | Type | Insight | Completeness | Numeric evidence | Overall | Relevance |
|---:|---|---:|---|---|---|---:|---:|---:|---|---|
| 1 | ThermoDSE | 2026 | arXiv preprint | [paper](https://arxiv.org/abs/2607.07096) | system/tool | 4 | 3 | 4 | A | Direct DSE front end; optimizes under thermal constraints but does not certify abstraction adequacy |
| 2 | Monad | 2023 | arXiv / chiplet accelerator paper | [paper](https://arxiv.org/abs/2302.11256) | pure method | 4 | 4 | 4 | A | Joint architecture/integration DSE; candidate-generation baseline |
| 3 | MOHaM | 2024 | IEEE Transactions on Computers | [paper](https://arxiv.org/abs/2210.14657) | pure method | 4 | 4 | 4 | A | Hardware–mapping co-optimization; shows why realizable states must include mapping couplings |
| 4 | Temperature-Aware Sizing of Multi-Chip Module Accelerators for Multi-DNN Workloads | 2023 | DATE | [paper](https://past.date-conference.com/proceedings-archive/2023/DATA/540.pdf) | pure method | 4 | 4 | 4 | A | Close thermal MCM design baseline using explicit power and HotSpot models |
| 5 | HotSpot: A Dynamic Compact Thermal Model at the Processor-Architecture Level | 2003 | Microelectronics Journal | [paper](https://doi.org/10.1016/S0026-2692(03)00206-4) | system/tool | 5 | 5 | 5 | A | Thermal-model foundation and scope boundary |
| 6 | Counterexample-Guided Abstraction Refinement | 2000 | CAV | [paper](https://doi.org/10.1007/10722167_15) | theory/proof | 5 | 5 | 4 | Risk | Establishes generic CEGAR; prevents claiming counterexample refinement itself as novel |
| 7 | Formal Property Verification by Abstraction Refinement | 2001 | DAC | [paper](https://www.cs.cmu.edu/~dongw/DAC01.pdf) | system/tool | 4 | 4 | 4 | Risk | Demonstrates abstraction refinement is already native to EDA verification |
| 8 | Exact and Approximate Schemes for Robust Optimization Problems with Decision-Dependent Information Discovery | 2024 | INFORMS Journal on Computing | [paper](https://arxiv.org/abs/2208.04115) | pure method | 5 | 5 | 4 | Risk | Closest generic robust co-optimization and decomposition framework |
| 9 | The Robust Selection Problem with Information Discovery | 2026 | Discrete Applied Mathematics | [paper](https://arxiv.org/abs/2501.02510) | theory/proof | 4 | 4 | 3 | Risk | Queries uncertain parameters before selection; close to joint design–analysis extension |
| 10 | Query-Competitive Algorithms for Cheapest Set Problems under Uncertainty | 2016 | Theoretical Computer Science | [paper](https://doi.org/10.1016/j.tcs.2015.11.025) | theory/proof | 4 | 4 | 3 | A | Formalizes minimum queries needed to identify a cheapest feasible set |
| 11 | Optimal Feature Selection for Decision Robustness in Bayesian Networks | 2017 | IJCAI | [paper](https://www.ijcai.org/proceedings/2017/215) | pure method | 4 | 4 | 4 | Risk | Direct precedent for selecting information to preserve a decision |
| 12 | Near-Optimal Sensor Placements in Gaussian Processes | 2008 | JMLR | [paper](https://jmlr.org/beta/papers/v9/krause08a.html) | method + theory | 5 | 5 | 5 | A | Mutual-information sensor placement and submodular approximation baseline |
| 13 | Robust Submodular Observation Selection | 2008 | JMLR | [paper](https://jmlr.org/beta/papers/v9/krause08b.html) | method + theory | 5 | 5 | 5 | A | Worst-case observation selection with non-unit costs |
| 14 | Adaptive Submodularity: Theory and Applications in Active Learning and Stochastic Optimization | 2011 | JAIR | [paper](https://arxiv.org/abs/1003.3967) | theory/proof | 5 | 5 | 4 | A | Important boundary for adaptive extensions and greedy guarantees |
| 15 | PhySense: Sensor Placement Optimization for Accurate Physics Sensing | 2025 | NeurIPS | [paper](https://proceedings.neurips.cc/paper_files/paper/2025/hash/332b4fbe322e11a71fa39d91c664d8fa-Abstract-Conference.html) | method + benchmark | 4 | 5 | 5 | A | Strong reconstruction-driven sensor placement; key contrast is field accuracy versus decision sufficiency |

Scores assess the paper as a relevant reference, not acceptance likelihood or
the viability of CertiTherm.

## Clusters

### Cluster 1: thermal and chiplet DSE

- Representative papers: ThermoDSE, Monad, MOHaM, DATE 2023 temperature-aware
  sizing.
- Already solved: multi-dimensional architecture/mapping/package exploration
  with performance, energy, cost, and thermal models.
- Remaining gap: whether the abstraction supplied to the optimizer preserves
  the final architecture decision over physically legal states.
- Differentiation: optimizer-independent decision-completeness witnesses and
  abstraction refinement.

### Cluster 2: decision-dependent information discovery

- Representative papers: exact/approximate DDID schemes, robust selection with
  information discovery, query-competitive cheapest-set algorithms.
- Already solved: generic formulations in which costly queries reveal
  uncertain parameters before a robust selection.
- Remaining gap: EDA report hierarchies, continuous thermal collision worlds,
  direct physical replay, and proof-carrying abstraction contracts.
- Differentiation: make decision-complete EDA abstraction the central property;
  use DDID as mathematical context, not as a renamed contribution.

### Cluster 3: decision-robust feature acquisition

- Representative paper: Optimal Feature Selection for Decision Robustness.
- Already solved: choose expensive features that maximize the probability of
  retaining a classifier decision.
- Remaining gap: prior-free fail-closed guarantees over continuous physical
  worlds and safety-constrained architecture selection.
- Differentiation: worst-case physical certification rather than expected
  same-decision probability.

### Cluster 4: sensor and observation selection

- Representative papers: GP sensor placement, robust submodular observation
  selection, adaptive submodularity, PhySense.
- Already solved: optimize reconstruction variance, mutual information, or
  learned field reconstruction quality.
- Remaining gap: full field recovery may be unnecessary for an EDA decision.
- Differentiation: measure decision sufficiency and architecture regret, not
  field MSE.

### Cluster 5: abstraction refinement

- Representative papers: CEGAR and DAC abstraction refinement.
- Already solved: use counterexamples to refine an abstract verification model.
- Remaining gap: cost-aware synthesis of physical EDA report abstractions for
  continuous multi-model thermal decisions.
- Differentiation: paired physical worlds, decision completeness, report cost,
  robust observation error, and DSE integration.

## Opportunity map

| Cluster | Status | Open gap | Possible direction | Evidence needed | Risk |
|---|---|---|---|---|---|
| Chiplet thermal DSE | deployment/system gap | abstraction correctness is untested | certify top-\(K\) DSE frontiers | real legal traces and decision flips | medium |
| DDID | covered generic mechanism | EDA-specific decision property and proof artifacts | decision-complete thermal abstraction | theorem differentiation and end-to-end system | high |
| Decision robustness | covered neighboring objective | prior-free physical safety | minimax robust decision completeness | noise and model-error theorem | medium |
| Sensor placement | crowded but open | reconstruction is stronger than decision need | decision-bearing spatial modes | compare field accuracy and decision cost | medium |
| CEGAR | covered generic loop | costly physical refinement library | proof-carrying EDA abstraction synthesis | physical witnesses and measured report costs | high |

## Citation and positioning cautions

- Do not claim that counterexample-guided refinement is new.
- Do not claim that purchasing information before optimization is new.
- Do not claim that decision-robust feature acquisition is new.
- Do not compare CertiTherm to PhySense only on runtime; their objectives differ.
- Do not imply that HotSpot agreement proves silicon truth.
- Novelty should be stated as the combination of a new EDA correctness
  property, continuous physical witness semantics, robust report refinement,
  and end-to-end chiplet-DSE evidence.
