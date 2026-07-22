---
name: certitherm-git-haoning
description: Runnable git branch/worktree/push/recovery command sequences for ThermoDSE-CertiTherm (HaoningJiang-space), plus real incident playbooks (credential leak + history rewrite, false master-status claim, symlinked submodule). Extends the policy in .codex/skills/git-push-haoning without duplicating it — read that file for the "why", this one for the "exact commands".
---

# Git workflow for ThermoDSE-CertiTherm

This skill supplies the literal command sequences actually used in this repo's history,
plus playbooks for incidents that already happened once and are likely to happen again.
The underlying policy (round branches, never force-push without authorization, credential
hygiene, `moe` vs `origin`) is documented in `.codex/skills/git-push-haoning/SKILL.md` and
its `scripts/prepush_guard.sh` guard — read that first; don't restate it here, use it.

## Round branch + worktree, exact sequence

Sibling directory naming, next to the main clone (not nested inside it):
`<repo-root>_<gate>_<shortdesc>`, e.g. `ThermoDSE-CertiTherm_g3_repair`. Branch name
`round/<gate>-<topic>`. Always check-before-create so a repeat invocation doesn't clobber
an existing worktree:

```bash
git worktree list --porcelain
test -e ../ThermoDSE-CertiTherm_<gate>_<short> || \
  git worktree add -b round/<gate>-<topic> ../ThermoDSE-CertiTherm_<gate>_<short> origin/master
```

When building on top of an audited round rather than master, base it on that round's
specific commit, not `origin/master`:

```bash
git worktree add -b round/<gate>-<topic> <path> <audited-round-commit-sha>
```

Commit/push loop (routine, single-purpose commits — this project's actual practice pushes
small fixes straight to `origin master` far more often than the "never commit to master"
policy literally states; treat `round/*` as mandatory for larger audited pieces of work,
and ask the user if a given change is routine-fix-sized or round-worthy when unsure):

```bash
git diff --check
git add <files>
git commit -m "<Imperative, single semantic change>"
git push -u origin <branch>       # or: git push origin master  for a routine fix
```

Guard + verify before any push, run per remote you're pushing to:

```bash
bash .codex/skills/git-push-haoning/scripts/prepush_guard.sh origin
git push --set-upstream origin HEAD
test "$(git rev-parse HEAD)" = "$(git ls-remote --heads origin refs/heads/<branch> | awk '{print $1}')"
```

## `moe` remote — what it's actually for

`moe` is a credential-free SSH bare-repo staging target, not a
test-execution target. Resolve the remote user from the SSH alias instead of
embedding a personal path:

```bash
remote_user=$(ssh -G moe-server | awk '$1 == "user" { print $2; exit }')
remote_repo="/data/$remote_user/git/ThermoDSE-CertiTherm.git"
ssh -o BatchMode=yes -o ConnectTimeout=10 moe-server "git init --bare '$remote_repo'"
git remote add moe "moe-server:$remote_repo"
git push moe <branch>
```

Push `moe` first as a low-friction checkpoint whenever GitHub write access is uncertain or
in flux; push `origin` once it's resolved. Remote test/experiment execution always uses a
**separate** working clone on moe-server (see
`.claude/skills/moe-server-remote/`). A credential-free clone from the bare mirror is
acceptable only after its branch SHA is checked against the intended pushed SHA; never
execute inside the bare repository itself.

## Submodule discipline

Before trusting a submodule state (especially before a claim-grade run):

```bash
git submodule status --recursive | awk '$1 ~ /^[-+U]/ { bad=1 } END { exit bad }'
git submodule foreach --recursive 'test -z "$(git status --porcelain)"'
```
(`-` uninitialized, `+` checked-out SHA differs from pinned, `U` merge conflict — all
failures.) Adding a new submodule pins to the exact commit, never a branch/tag that can move:

```bash
git submodule add <url> <dir>
git -C <dir> checkout <full-40-char-sha>   # detached HEAD here is correct, not a mistake
git submodule status
```

**Watch for a submodule that's actually a raw symlink pointing outside the repo** — this
repo's `HotSpot` was once committed as a `120000` symlink blob into another user's absolute
home-directory path, which silently breaks on any other machine/clone. Fix: `git rm` the
symlink, then `git submodule add` the real upstream URL and pin it properly.

## Incident playbook: leaked credential

If a token/secret is pasted in chat, found in a diff, or found already committed:

1. Refuse to write it into any file, skill, commit, or config — no exceptions, regardless of
   whether it looks like a repeat of something already flagged before.
2. Tell the user to revoke it at the provider (GitHub token settings / Anthropic console)
   immediately. A history rewrite is not a substitute for revocation — it only removes
   discoverability, the credential itself must be killed at the source.
3. Only after revocation is confirmed, if the secret is already committed, a full rewrite is
   the real precedent set by this project (executed exactly once so far):
   ```bash
   python3 -m venv /tmp/certitherm-filter-repo-venv
   /tmp/certitherm-filter-repo-venv/bin/pip install git-filter-repo
   /tmp/certitherm-filter-repo-venv/bin/git-filter-repo --force --sensitive-data-removal \
     --invert-paths --path <leaked-file> [--path <other-paths-to-strip>]
   ```
   Before running this: archive the pre-rewrite state (tar + sha256) somewhere durable (this
   project put it on moe-server) and re-run the full test suite against the pre-rewrite
   commit as a clean baseline. After running this: `git push --force origin master` is the
   **only** acceptable force-push, and only with explicit user authorization for this exact
   branch; delete any now-stale branches based on the old history
   (`git push origin --delete <branch>` then `git branch -D <branch>` locally); every
   existing clone (including any on moe-server) must be discarded and re-cloned fresh.
4. Set up a scoped, non-personal credential for future pushes rather than reusing whatever
   leaked — this project's actual fix was a dedicated deploy key:
   ```bash
   ssh-keygen -t ed25519 -N '' -C 'ThermoDSE-CertiTherm deploy key' -f ~/.ssh/id_ed25519_certitherm_deploy
   # add to ~/.ssh/config: Host github-certitherm / HostName github.com / User git /
   #   IdentityFile ~/.ssh/id_ed25519_certitherm_deploy / IdentitiesOnly yes
   git remote set-url --push origin git@github-certitherm:HaoningJiang-space/ThermoDSE-CertiTherm.git
   ```
   then have the user add the public key as a GitHub Deploy Key with write access via the
   web UI (not something to automate — it's a one-time manual step on their account).

`git reflog` is fine to use for *provenance/audit* during this kind of incident (e.g.
confirming when/how a prior push happened) — it does not itself record credentials, so
reading it is safe even mid-incident.

## Incident playbook: don't trust a bare "done ✓" claim on master

Before treating any commit pushed straight to `master` as an integration base, diff it
against the actively audited round branch from their common ancestor and re-run the
relevant checks — don't take a commit message's stated status at face value:

```bash
git merge-base master round/<gate>-<topic>
git diff <merge-base> master
git diff <merge-base> round/<gate>-<topic>
```

Real precedent: a commit on `master` claimed "G1–G4 都已完成并 push ✓" while a parallel
audited round was in flight from the same ancestor; diffing and re-checking found it was
actually broken (truncated data, a missing report, a real bug). The audited round branch
was kept as the integration base instead of the suspect master commit.
