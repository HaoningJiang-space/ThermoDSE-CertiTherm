#!/usr/bin/env bash
# Wrapper for running ThermoDSE-CertiTherm commands on moe-server.
# Formalizes the ad hoc ssh patterns this project has actually used (there is no
# dedicated wrapper script for this repo yet, unlike the sibling ChipletThermalEnvelope
# project's .codex/skills/chiplet-thermal-envelope-remote/scripts/remote_exec.sh).
set -euo pipefail

SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=20 -o ServerAliveCountMax=3)
REMOTE_USER="${CERTITHERM_REMOTE_USER:-$(ssh -G moe-server | awk '$1 == "user" { print $2; exit }')}"
if [[ -z "$REMOTE_USER" ]]; then
  echo "cannot resolve remote user from ssh alias moe-server" >&2
  exit 64
fi
REMOTE_BASE="${CERTITHERM_REMOTE_BASE:-/data/${REMOTE_USER}/experiments}"
# Public HTTPS, deliberately: read-only, needs no credential on the server, and
# cannot leak one. Do NOT use `git@github-certitherm:...` here -- that is a
# LOCAL ~/.ssh/config alias which does not resolve on moe-server
# ("Could not resolve hostname github-certitherm").
REPO_URL="https://github.com/HaoningJiang-space/ThermoDSE-CertiTherm.git"

usage() {
  cat <<'EOF'
Usage:
  remote_exec.sh --preflight
      Local check: worktree clean, branch is round/* (warns otherwise), prints local HEAD.

  remote_exec.sh --new-clone <label> [--branch <ref>] <cmd...>
      Fresh `git clone --recurse-submodules` into a new
      $CERTITHERM_REMOTE_BASE/certitherm-<label>.XXXXXX directory on moe-server,
      then run <cmd...> with cwd = repo root.
      ALWAYS pass --branch with the branch you are actually working on. The
      default clone checks out the remote HEAD (master), which can be many
      commits behind your round branch -- running against it silently tests
      DIFFERENT code than the one you edited.

  remote_exec.sh --sync <path> <relative-dir>
      Copy a local directory (typically UNTRACKED, e.g. research/dr_dsc) into an
      existing remote clone via tar-over-ssh, then print sha256 of every file on
      both sides so you can confirm they match. A fresh clone only contains
      COMMITTED files -- untracked work must be synced explicitly or the remote
      run fails with confusing "file not found" errors. Re-run this after every
      local edit; editing locally does NOT update the remote clone.

  remote_exec.sh --run <path> <cmd...>
      Run <cmd...> in an existing remote clone at <path> (cwd = repo root).

  remote_exec.sh --background <path> <label> <cmd...>
      Same as --run but detached with nohup + a PID file at <path>/artifacts/<label>.pid,
      so a multi-hour run survives the SSH session closing. Poll with --status.

  remote_exec.sh --status <path> <label>
      Report the backgrounded job's process tree and tail its log.

  remote_exec.sh --kill <path> <label>
      Kill a backgrounded job's PID *and its children* (HotSpot workers fork under the
      tracked parent PID; killing only the parent leaves them running).
EOF
}

cmd=${1:-}
case "$cmd" in
  --preflight)
    if [ -n "$(git status --porcelain)" ]; then
      echo "worktree not clean" >&2
      exit 1
    fi
    branch=$(git rev-parse --abbrev-ref HEAD)
    case "$branch" in
      round/*) ;;
      master|main)
        echo "WARNING: on $branch — confirm this is a routine fix, not claim-grade work" >&2 ;;
      *)
        echo "WARNING: unrecognized branch $branch" >&2 ;;
    esac
    echo "branch: $branch"
    echo "local HEAD: $(git rev-parse HEAD)"
    ;;
  --new-clone)
    label=$2; shift 2
    branch=""
    if [ "${1:-}" = "--branch" ]; then branch=$2; shift 2; fi
    branch_opt=""
    [ -n "$branch" ] && branch_opt="--branch '$branch'"
    # shellcheck disable=SC2029
    ssh "${SSH_OPTS[@]}" moe-server "
      set -euo pipefail
      run_dir=\$(mktemp -d '${REMOTE_BASE}/certitherm-${label}.XXXXXX')
      git clone --recurse-submodules $branch_opt '${REPO_URL}' \"\$run_dir/repo\"
      cd \"\$run_dir/repo\"
      echo \"remote clone: \$run_dir/repo\"
      echo \"remote branch: \$(git rev-parse --abbrev-ref HEAD)\"
      echo \"remote HEAD: \$(git rev-parse HEAD)\"
      $*
    "
    ;;
  --sync)
    path=$2; subdir=$3
    if [ ! -d "$subdir" ]; then
      echo "local directory not found: $subdir (run from the repo root)" >&2
      exit 1
    fi
    tar -cf - --exclude='__pycache__' --exclude='*.pyc' "$subdir" \
      | ssh "${SSH_OPTS[@]}" moe-server "cd '$path' && tar -xf -"
    echo "=== local sha256 ==="
    find "$subdir" -type f ! -name '*.pyc' ! -path '*__pycache__*' -exec sha256sum {} + | sort -k2
    echo "=== remote sha256 ==="
    ssh "${SSH_OPTS[@]}" moe-server \
      "cd '$path' && find '$subdir' -type f ! -name '*.pyc' ! -path '*__pycache__*' -exec sha256sum {} + | sort -k2"
    echo "(compare the two blocks above -- they must match exactly)"
    ;;
  --run)
    path=$2; shift 2
    ssh "${SSH_OPTS[@]}" moe-server "cd '$path' && $*"
    ;;
  --background)
    path=$2; label=$3; shift 3
    ssh "${SSH_OPTS[@]}" moe-server "
      cd '$path'
      mkdir -p artifacts
      nohup $* > 'artifacts/${label}.log' 2>&1 < /dev/null &
      echo \$! > 'artifacts/${label}.pid'
      echo \"backgrounded as PID \$(cat 'artifacts/${label}.pid')\"
    "
    ;;
  --status)
    path=$2; label=$3
    ssh "${SSH_OPTS[@]}" moe-server "
      cd '$path'
      pid=\$(cat 'artifacts/${label}.pid' 2>/dev/null || echo '')
      if [ -n \"\$pid\" ]; then
        ps -o pid,etime,stat,%cpu,%mem,cmd -p \"\$pid\" 2>/dev/null || echo 'PID not running (finished or never started)'
        pgrep -P \"\$pid\" | xargs -r ps -o pid,etime,stat,%cpu,%mem,cmd -p 2>/dev/null || true
      else
        echo 'no PID file found'
      fi
      echo '--- tail log ---'
      tail -n 40 'artifacts/${label}.log' 2>/dev/null || true
    "
    ;;
  --kill)
    path=$2; label=$3
    ssh "${SSH_OPTS[@]}" moe-server "
      cd '$path'
      pid=\$(cat 'artifacts/${label}.pid' 2>/dev/null || echo '')
      if [ -n \"\$pid\" ]; then
        children=\$(pgrep -P \"\$pid\" || true)
        [ -n \"\$children\" ] && kill \$children || true
        kill \"\$pid\" 2>/dev/null || true
        sleep 2
        kill -0 \"\$pid\" 2>/dev/null && kill -KILL \"\$pid\" || true
        echo \"killed PID \$pid and children: \$children\"
      else
        echo 'no PID file found'
      fi
    "
    ;;
  *)
    usage
    exit 1
    ;;
esac
