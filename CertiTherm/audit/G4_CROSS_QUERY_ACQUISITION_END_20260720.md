# G4 cross-query acquisition end packet — 2026-07-20

## Revision

- Branch: `round/g4-cross-query-acquisition`
- Parent G3 repair: `808d00a35e0d26f36008cb8ae1f0df24358bdd36`
- Legacy invalidation commit: `f2c4eef`
- Implementation commit: `ff36861`

## Delivered change

The truncated single-candidate G4 pilot from
`73a1afd67685bfc96873980f0837a3dfa08cdadb` is explicitly invalidated.  Its
JSON cannot be used as evidence that acquisition resolves a decision.

The replacement makes acquisition an information-refinement operation on the
same architecture-selection query used by G2/G3:

1. consume and replay one `spatial_equivalence` artifact from a G3 suite;
2. bind an explicit candidate/block linear measurement registry, physical
   source-file digests, obtainability record, and common cost model;
3. append rather than replace the target candidate's observation constraints;
4. retain all other candidates and re-solve the complete decision query;
5. require both decision-changing witness values to produce certified,
   distinct, matching architecture outcomes;
6. stop fail-closed if a potentially cheaper action is unresolved; and
7. emit an external, self-authenticating artifact with a fresh semantic replay.

Measurement names have no executable semantics.  This removes the legacy
interposer/name-parser failure and makes component ordering explicit through
block identities.  A synthetic registry is accepted only by the in-memory
software-test interface; the claim-grade CLI requires a
`physical_measurement_family` with hash-verified source files.

## Verification performed

- `git diff --check`: PASS before the implementation commit.
- Secret-pattern scan of changed repository paths: no credential found.
- Manual/static review of the registry, constraint append, cross-query,
  ordering, fail-closed, artifact, and replay paths: completed.
- Automated tests: **NOT RUN**, locally or remotely, following the owner's
  explicit instruction on 2026-07-20.
- Claim-grade G3/G4 experiment: NOT RUN.
- New numerical result: none.

The seven added test functions are authored but unexecuted.  They cover:
constraint preservation, two-direction cross-query confirmation, rejection of
one-direction-only evidence, name-parser independence, unknown-block
rejection, `NOT_APPLICABLE` handling, and artifact-tamper rejection.

## Claim-to-evidence status

| Statement | Current evidence | Status |
| --- | --- | --- |
| Legacy one-sensor/truncated-ptrace result closes G4 | invalid early return with no acquisition | WITHDRAWN |
| New implementation preserves decision-level semantics | code plus manual review and unexecuted tests | UNVERIFIED |
| One registered action confirms a physical witness pair | no physical G3 parent or measurement registry | TBD |
| Witness-directed acquisition reduces expensive queries | no fixed-refinement comparison | OPEN |
| G4 finds globally minimum information | explicitly outside the contract | NONCLAIM |
| G4 resolves every possible measurement value | witness-pair tests are insufficient | NONCLAIM |

## Constructive dissent

1. **Critical — G3 physical breadth is still absent.** G4 has no legitimate
   parent case until a registered G3 spatial query is both physical and
   `NON_IDENTIFIABLE`.
2. **High — the implementation has not executed.** Static review does not
   establish solver behavior, fixture validity, replay closure, or runtime.
3. **High — no physical measurement family is registered.** A defensible EDA
   mechanism must derive region/subarray/post-placement aggregates from real
   tool outputs and bind their source files and acquisition cost.
4. **High — witness-pair confirmation is not universal resolution.** A stronger
   policy theorem would need a partition of the feasible measurement range and
   certification over every cell/value, not just two endpoints selected by the
   current counterexample.
5. **High — operational usefulness is unmeasured.** G4 needs matched fixed and
   uncertainty-width refinement baselines at equal correctness/coverage.

## Next executable stage

After the owner authorizes execution:

1. execute the targeted G4 tests from the exact pushed commit;
2. produce and replay the registered physical 2×2×2 G3 suite;
3. select only its `NON_IDENTIFIABLE` spatial queries;
4. generate one physical measurement registry per query from content-bound EDA
   reports, with a frozen cost unit;
5. run G4 and its replay outside Git; and
6. compare expensive-query count, total declared cost, correctness/coverage,
   runtime, and failure taxonomy against fixed uniform and uncertainty-width
   refinement.

G4 remains **OPEN**.  The implementation now has a defensible interface and
claim boundary, not experimental evidence.
