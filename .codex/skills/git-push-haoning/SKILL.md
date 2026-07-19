---
name: git-push-haoning
description: Safely clone, branch, commit, audit, and publish work for HaoningJiang-space/ThermoDSE-CertiTherm, including multi-worktree research rounds, moe-server validation, Git recovery, and evidence-preserving integration from ChipletThermalEnvelope. Use when Codex works in ThermoDSE-CertiTherm, pushes to HaoningJiang-space, prepares a CertiTherm research commit, manages several Git rounds, or checks that credentials and scientific artifacts are safe to publish.
---

# Publish Haoning CertiTherm Work

## Bind the project

- Treat `https://github.com/HaoningJiang-space/ThermoDSE-CertiTherm.git` as the canonical publication repository.
- Locate the active clone with `git rev-parse --show-toplevel`; keep documentation and manifests repository-relative.
- Read `CLAUDE.md`, `CertiTherm/README.md`, `CertiTherm/INSIGHTS.md`, `CertiTherm/audit/SUMMARY.md`, Git status, remotes, and recent history before changing research content.
- Keep ThermoDSE source as a sibling repository or an explicitly pinned dependency. Do not add the unrelated ThermoDSE history as a merge remote.

## Keep credentials outside Git

- Never put a PAT, access token, password, or credential-bearing URL in this skill, a prompt-generated command, Git config, a committed file, a manifest, or shell history.
- Treat any token pasted into chat as compromised. Tell the user to revoke it and use a newly created credential through their own secure credential manager.
- Prefer an already-loaded SSH key. Check its identity with `ssh -T git@github.com`; repository ownership and the authenticated account are separate facts.
- Otherwise require the user to authenticate through GitHub CLI browser/device flow or an operating-system credential helper in their own secure terminal. Do not echo or interpolate a token.
- Keep fetch and push URLs credential-free. A permitted push URL is `git@github.com:HaoningJiang-space/ThermoDSE-CertiTherm.git` when the loaded key has write access.
- Keep `origin` for GitHub publication and an optional credential-free `moe` remote for isolated execution/recovery. A push to `moe` does not count as public GitHub publication.

## Use round branches and worktrees

1. Fetch and inspect `origin/master` without rewriting local work.
2. Never develop directly on `master`. Create `round/<gate>-<topic>` from a recorded base commit.
3. Use a separate worktree for an independent implementation, integrity audit, or correction round.
4. Preserve concurrent user changes. Stop if an overlapping dirty change cannot be isolated.
5. Make small commits that each bind one contract, implementation, experiment, or audit result.
6. Push the named round branch before remote execution so the tested commit is recoverable.

## Validate remotely

- Run builds, tests, HotSpot/3D-ICE jobs, and claim-bearing experiments only on `moe-server` when the project task inherits the remote-execution requirement.
- Require the remote checkout to be clean and at the exact local commit before a claim-bearing run.
- Store raw run output outside the Git worktree. Commit only compact, content-bound manifests after replay and integrity checks.
- Record commit, config digest, input digests, command, environment, exit status, wall time, peak RSS, and output digest.

## Protect the scientific story

- Treat the current Gaussian/corner/checker Phase 1 and sample-maximum Phase 2 results as preliminary synthetic stress evidence.
- Do not call a maximum over `K` sampled patterns a worst-case bound, robust certificate, or zero-false-positive guarantee. Call it a sampled stress maximum unless coverage is proved.
- Preserve the earlier G0/G1 insight: the defensible core is typed hardware-observation semantics plus exact, replayable decision-identifiability certificates and decision-changing witness tuples.
- Transfer prior artifacts by source commit and manifest digest. Do not silently copy claims or mix the frozen 6-variable/40-inequality G1 contract with an 8/48 independent implementation.
- Keep generic DDID/VOI/CEGAR and minimum-information acquisition as prior-art-constrained nonclaims until an EDA-specific theorem and physical evidence exist.
- Do not elevate synthetic fixtures into a DAC/ICCAD/DATE claim. Require real placed-power evidence, at least two DNN families, two non-isomorphic architecture families, two package regimes, and independent thermal replay.

## Commit and push

1. Run `scripts/prepush_guard.sh origin` from this skill.
2. Review `git diff --check`, staged diff, and the exact file list.
3. Commit with a message that distinguishes `contract`, `feat`, `test`, `evidence`, `audit`, or `docs`.
4. Push explicitly with `git push --set-upstream origin HEAD` only after the guard passes and the authenticated identity has write permission.
5. Verify with `git ls-remote --heads origin refs/heads/<branch>` and compare the returned commit to local `HEAD`.
6. Never force-push unless the user explicitly authorizes the exact branch rewrite.

## Recover safely

- Prefer a new correction commit or branch over history rewriting.
- Use `git reflog`, remote refs, and clean worktrees to recover lost commits.
- Never use `git reset --hard`, broad recursive deletion, or checkout-based discard without explicit authorization.
- If push authentication fails, keep the local commit and report the exact branch and commit. Do not weaken credential isolation to make the push succeed.
