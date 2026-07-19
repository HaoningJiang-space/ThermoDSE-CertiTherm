#!/usr/bin/env bash
set -euo pipefail

remote_name="${1:-origin}"
repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

branch=$(git branch --show-current)
head_commit=$(git rev-parse HEAD)

if [[ -z "$branch" || "$branch" == "master" || "$branch" == "main" ]]; then
  echo "prepush-guard: publish research from a named non-default branch" >&2
  exit 65
fi
if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  echo "prepush-guard: worktree must be clean" >&2
  exit 66
fi
if ! git remote get-url "$remote_name" >/dev/null 2>&1; then
  echo "prepush-guard: requested remote does not exist" >&2
  exit 67
fi

remote_urls=$(
  {
    git remote get-url --all "$remote_name"
    git remote get-url --push --all "$remote_name"
  } | sort -u
)
if grep -Eq '^[a-zA-Z][a-zA-Z0-9+.-]*://[^/@[:space:]]+@' <<<"$remote_urls"; then
  echo "prepush-guard: credential-bearing remote URL is forbidden" >&2
  exit 68
fi

secret_pattern='(ghp_[[:alnum:]]{20,}|github_pat_[[:alnum:]_]{20,})'
if git grep -I -q -E "$secret_pattern" HEAD --; then
  echo "prepush-guard: token-like material exists in the current tree" >&2
  exit 69
fi
while IFS= read -r commit; do
  if git grep -I -q -E "$secret_pattern" "$commit" --; then
    echo "prepush-guard: token-like material exists in reachable Git history" >&2
    exit 70
  fi
done < <(git rev-list --all)

echo "prepush-guard-ok"
echo "branch=$branch"
echo "head=$head_commit"
echo "remote=$remote_name"
