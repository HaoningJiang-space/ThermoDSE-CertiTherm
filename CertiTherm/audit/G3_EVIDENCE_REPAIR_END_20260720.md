# G3 Evidence Repair End Packet — 2026-07-20

## Revision

- Branch: `round/g3-evidence-repair`
- Base: `b7b08eeb518589ac03d3a92f38fe2b72cbf96d86`
- Retraction commit: `a69f1e30296b5cbb9011a7905892769d088c460c`
- Implementation commit: `2565eaf60bd76ae01c7ee832b4d0b6fd4caaf1e8`

## Delivered change

The former mutable G3 demonstration was replaced by a registered suite runner.
It no longer captures or relabels aggregate DNN ptraces, edits a shared HotSpot
configuration, caches thermal operators by architecture alone, compares
hard-coded `1.5x`/`5x` domains, or infers an architecture flip from one
candidate's bound.

The new path requires a complete workload-family × package matrix. Every
stratum uses the same cross-candidate architecture query and binds three
matched variants:

1. an original-ThermoDSE singleton point estimate;
2. a singleton placed-power reference;
3. the registered spatial observation-equivalence class.

Workload power, point power, response matrices, package configs, placement,
architecture identity, and input files are content-bound. Reused workload or
package evidence fails closed. Every produced query artifact is embedded in a
suite envelope and freshly replayed before a receipt can pass.

The old `5/8` result is wrapped as `LEGACY_INVALIDATED_FOR_CLAIMS`; the report,
README, insight record, and artifact-disposition table now withdraw the error
rate and G3-complete language.

## Verification performed

- `git diff --check`: PASS before both commits.
- Manual/static review of changed paths: completed.
- Automated tests: **NOT RUN**, locally or remotely, following the owner's
  explicit instruction on 2026-07-20.
- Claim-grade G3 suite: NOT RUN; no physical suite exists in this repository.
- New numeric result: none.

The added `CertiTherm/tests/test_g3_evidence.py` cases are unexecuted test code,
not evidence. They cover singleton baselines, full cross-candidate execution,
workload relabel rejection, package alias rejection, incomplete Cartesian
matrices, and artifact tampering.

## Claim-to-evidence status

| Claim | Current evidence | Verification class | Status |
| --- | --- | --- | --- |
| Old 62.5% error-decision rate | Invalid generator and aliased inputs | forensic audit | WITHDRAWN |
| G3 software rejects the four known aliasing/comparison errors | implementation plus unexecuted adversarial tests | static only | UNVERIFIED |
| Two-DNN/two-architecture/two-package generality | no registered physical suite | none | OPEN |
| Point decisions disagree with placed references | no registered physical suite | none | TBD |
| Spatial decisions are certifiable/non-identifiable at useful coverage | no registered physical suite | none | TBD |

## Constructive dissent

1. **Critical — physical breadth remains absent.** Static input validation does
   not establish DNN or package generality. Required evidence: the registered
   physical suite and independent replay. Status: OPEN.
2. **High — implementation tests were not executed.** Syntax, fixture behavior,
   and replay closure remain unverified by execution. Required evidence:
   targeted and full tests from the exact pushed commit. Status: OPEN.
3. **High — the point baseline provenance is not yet instantiated.** A file can
   satisfy the schema without showing it came from the original ThermoDSE
   default path. Required evidence: generator command, source revision, and
   digest chain. Status: OPEN.
4. **High — placed-reference HotSpot is not an independent truth backend.** A
   point/placed disagreement may still be model-specific. Required evidence:
   3D-ICE or another registered independent replay with an error contract.
   Status: OPEN.
5. **Medium — exact-query scaling is unmeasured.** Required evidence: candidate
   count/domain-size runtime, RSS, artifact-size, and replay-time curves.
   Status: OPEN.

## Gate verdict and next owner

G3 remains **OPEN**. The correction round fixes the experimental interface and
claim boundary; it does not close an empirical gate.

Next owner: physical evidence production, followed by execution of the already
added tests and an integrity audit of the first registered suite. No G4
acquisition work is authorized by this round.
