# CertiTherm Research Contract for DAC / ICCAD / DATE

Status: preregistered direction and evidence plan; no paper claim is authorized.

## Optimized idea card

| Field | Contract |
| --- | --- |
| Task | Verify whether an early chiplet-DSE architecture decision is invariant over every placed fine-power map consistent with obtainable hardware observations |
| Gap | Existing thermal-aware DSE commonly evaluates one estimated or aggregate-derived power map but does not prove that the selected architecture survives observation-equivalent spatial realizations |
| Root challenge | Aggregate power observations define an equivalence class of fine maps, while thermal feasibility and architecture order depend on spatial placement |
| Core insight | Optimize and verify the decision over the observation equivalence class, not the temperature error of one guessed map |
| Mechanism | Typed observation IR, compact admissible power set, frozen thermal operator, exact lower/upper peak certificates, reachable-outcome theorem, and replayable decision-changing witness tuples |
| Contribution type | New EDA decision-verification setting plus a proof-carrying method; physical empirical finding is conditional on G2 |
| Target audience | DAC/ICCAD/DATE DSE, physical-design, thermal-signoff, and heterogeneous-integration communities |
| Main risk | The physical observation sets may be too tight or too loose to yield useful certification coverage on real designs |

## Frozen query semantics

For each architecture candidate, bind:

1. fine-cell identities and placement;
2. obtainable observation row identities, matrix, values, and provenance;
3. finite nonnegative component bounds and registered inequalities;
4. one content-bound thermal operator and ambient vector;
5. nonthermal objective and deterministic tie rank;
6. thermal limit with equality classified feasible.

Return exactly one of:

- `CERTIFIED`: every admissible cross-candidate fine map selects one outcome;
- `NON_IDENTIFIABLE`: two complete observation-equivalent tuples replay to
  different outcomes;
- `UNRESOLVED`: invalid input, empty observation, missing compactness, resource
  exhaustion, solver failure, or proof-replay failure prevents a conclusion.

The exact small-instance path is the semantic oracle. A scalable floating-point
or mixed-integer path may be added only with independent replay and fail-closed
status handling.

## Claims and nonclaims

### Candidate claims

1. **Problem/semantics:** thermal-aware chiplet DSE decisions can be
   non-identifiable under the information actually obtainable at a design
   stage.
2. **Method:** CertiTherm returns proof-carrying certification or a sharp
   observation-equivalent decision-flipping witness pair.
3. **System evidence:** on registered physical cases, the method reduces false
   decision confidence while exposing proof/query cost.

### Frozen nonclaims

- A finite synthetic sample maximum is not a worst-case bound.
- G1 synthetic fixtures do not prove placed-power or DNN-general behavior.
- Generic active learning, VOI, DDID, or CEGAR is not claimed as new.
- Least-information/minimum-query optimality is not claimed before a formal
  registered acquisition family and proof.
- Scalable runtime, zero false positives, or backend-independent physics is not
  claimed before the corresponding gate passes.

## Claim–evidence matrix

| Claim | Required evidence | Metrics | Gate |
| --- | --- | --- | --- |
| Typed semantics are correct | exact rational fixtures, primal/dual replay, forged-object rejection, independent LP parity | false certifications, replay fraction, parity fraction | G1 |
| Real decisions can be non-identifiable | placed-power cases with one observation and two valid fine maps selecting different architectures | witness count, observation equality, decision flip, regret | G2 |
| Real decisions can be certified | universal bound certificate replayed against physical oracle cases | false-safe count, false-infeasible count, coverage | G2 |
| Method generalizes across DNN/design/package | at least 2 DNN families × 2 non-isomorphic architecture families × 2 package regimes | per-stratum coverage and failure taxonomy | G3 |
| Method is operationally useful | comparison to uniform, sampled-stress, interval-box, and fixed-refinement baselines | query cost, runtime, RSS, certificate size, regret | G3 |
| Acquisition is EDA-specific and useful | fixed measurement family and adaptive policy on physical undecidable cases | expensive-query reduction at matched error/coverage | G4 |

## Experiment design

### Workload and design matrix

- DNN families: one convolution-dominant and one attention/sequence-dominant
  family at minimum; exact network identities remain TBD until evidence is
  available.
- Architecture families: at least two non-isomorphic chiplet/core-cut or
  mapping organizations, not nearby parameter points from one family.
- Package regimes: at least two material/cooling/interposer regimes with frozen
  stack and boundary-condition provenance.
- Power evidence: real activity plus placed instance power; every aggregation
  row must be derived and replayable.

### Baselines

| Baseline | Purpose | Fairness requirement |
| --- | --- | --- |
| Original ThermoDSE aggregate/uniform path | deployed/default comparison | identical architecture set, objectives, thermal limit, and backend |
| Corrected K-sample synthetic stress | test whether finite sampling alone suffices | power-conserving observations, fixed seeds/K, never called a bound |
| Component box/interval bound | simple conservative baseline | same component limits and operator |
| Fixed uniform refinement | acquisition-cost baseline | same available measurement family |
| Exact small oracle | semantic ground truth | only registered bounded instances |
| Scalable CertiTherm solver | proposed operational path | independent certificate/witness replay |
| Placed-power thermal oracle | physical outcome reference | content-bound inputs and backend configuration |

Closest published method baselines remain `needs-literature-search`; do not
invent or select them from memory.

### Primary metrics

- certification coverage and unresolved fraction;
- false-safe and false-infeasible decisions against the registered oracle;
- architecture-choice disagreement and nonthermal objective regret;
- interval width and distance to decision boundary;
- expensive physical-query count;
- solver wall time, peak RSS, certificate size, and replay time;
- per-DNN, per-architecture-family, and per-package failure taxonomy.

### Mechanism ablations

1. remove placement identity while keeping aggregate totals;
2. replace coupled observation constraints with independent boxes;
3. remove thermal-row coupling or use only one peak surrogate;
4. replace exact replay with solver self-report;
5. vary observation granularity and component bounds;
6. compare fixed, uncertainty-width, and decision-witness-directed refinement;
7. vary thermal backend/model form and boundary conditions.

## Gate and stop conditions

| Gate | Pass condition | Stop / pivot condition |
| --- | --- | --- |
| G1 semantic oracle | zero false certifications/accepted forgeries on registered exact fixtures; complete replay and LP parity | any unresolved proof accepted as a claim |
| G2 physical witness/certificate | at least one replayable certificate and one decision-changing witness from content-bound placed-power cases | no decision relevance under realistic observations, or evidence provenance cannot be built |
| G3 breadth and systems cost | registered 2×2×2 breadth, fair baselines, bounded overhead, explicit failures | result exists only for one synthetic pattern or one nearby design family |
| G4 acquisition | fewer expensive queries than fixed refinement at matched correctness/coverage | benefit derives only from generic policy tuning without an EDA-specific observation mechanism |

Passing G1 authorizes only G2. Passing a synthetic stress test never authorizes a
paper claim.

## Execution order

1. Preserve legacy outputs but exclude them from claims.
2. Migrate the exact typed G1 oracle with source-commit provenance.
3. Build a content-bound run-manifest schema and replay command.
4. Generate real placed-power observations for one narrow G2 pair.
5. Run exact/scalable classification and independent thermal replay.
6. Audit the first positive and negative physical cases before expanding the
   benchmark matrix.
7. Refresh current related work before freezing novelty wording.

No experimental result is generated by this contract. All quantitative table
cells remain TBD until a clean registered run produces them.
