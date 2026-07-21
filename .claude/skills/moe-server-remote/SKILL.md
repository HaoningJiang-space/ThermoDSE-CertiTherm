---
name: moe-server-remote
description: Run ThermoDSE-CertiTherm builds, tests, and claim-grade experiments on moe-server — the only host authorized for native/C++/CUDA compilation, HotSpot runs, and GPU work. Use whenever a task in this repo needs anything beyond editing files or lightweight static checks.
---

# Run ThermoDSE-CertiTherm on moe-server

## Absolute rule

Never compile C++/CUDA locally, and never run tests, HotSpot/3D-ICE simulations, or
experiments locally — not even "quickly to check." Locally: edit files, `git` inspect,
lightweight static checks only. This was violated once in practice (a local G4 run got
started by mistake); the fix was to kill it immediately and discard its output as
non-evidence, not to keep it as a shortcut. If the user explicitly says skip remote
execution for a specific low-stakes change ("不用在远端测试，你push上去就行"), that's
allowed, but the resulting commit/report must say so explicitly (e.g. "tests not executed,
evidence-excluded") — never present unexecuted work as passing.

## Connection

`moe-server` is already configured in `~/.ssh/config` (`HostName 10.16.52.172`,
`User ziheng`, `Port 10548`). Use `scripts/remote_exec.sh` in this skill rather than ad hoc
`ssh` one-liners — it encodes the connection options and patterns actually used in practice
(`ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=20
-o ServerAliveCountMax=3 moe-server '...'`). See `scripts/remote_exec.sh --help`.

## Setup pattern

Fresh clone into a unique, disk-hygienic directory, never reusing a stale one:

```bash
scripts/remote_exec.sh --new-clone dsos-check 'make bootstrap && make check'
```

This clones with `git clone --recurse-submodules` from `origin` (GitHub) into
`/data/ziheng/experiments/certitherm-<label>.XXXXXX` — **not** rsync, and **not** via the
`moe` git remote (that remote is a push-only staging target, see the git skill; nothing is
ever pulled from it for test runs). Everything — venv, HotSpot build, artifacts — stays
under `/data/ziheng/...` (i.e. `/data/$USER`); the server's root disk is capacity-constrained.

Commands always run with cwd = repo root (`cd "$run_dir/repo" && ...`). Running pytest from
outside the repo root fails with `ModuleNotFoundError: No module named 'CertiTherm'` — this
has been hit twice in practice.

No `sudo`/`apt-get`/`conda`/`mamba` on this host for this project — `make bootstrap` is a
pure user-space `virtualenv` + `requirements.lock` install. If you need to check whether a
build tool exists, use `command -v <tool>` (read-only probing), don't try to install one.

## Long-running jobs (`make reproduce-dev`, `make heldout`)

These run for hours. Background them with a PID file so they survive the SSH session
closing, then poll sparsely — do not hold the SSH connection open and do not poll every few
seconds:

```bash
scripts/remote_exec.sh --background /data/ziheng/experiments/certitherm-dsos-final.XXXXXX/repo dev-run 'make reproduce-dev'
scripts/remote_exec.sh --status   /data/ziheng/experiments/certitherm-dsos-final.XXXXXX/repo dev-run
```

**HotSpot forks worker subprocesses under the tracked PID.** Killing only the parent PID
leaves orphaned HotSpot children burning CPU. Always kill children first:

```bash
scripts/remote_exec.sh --kill /data/ziheng/experiments/certitherm-dsos-final.XXXXXX/repo dev-run
```

(This finds children via `pgrep -P $pid`, kills them, then the parent, escalating to
`kill -KILL` if still alive after a couple seconds.)

Tuning: `CERTITHERM_LP_WORKERS` (Makefile default 8) controls separation-LP parallelism;
GPU runs additionally want `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1` (let
CUDA/the outer job scheduler own parallelism, not BLAS) plus `CERTITHERM_GPU_HOTSPOT=1`,
`CUDA_NVCC=/usr/local/cuda-12.8/bin/nvcc`, `CUDA_ARCH=sm_80`. moe-server has 52 CPU cores
(`nproc`); a good split for HotSpot operator building has been "3 independent operators ×
16 HotSpot workers = 48 total," preserving deterministic output order — don't just crank
worker counts blindly.

A per-query `QUERY_METHOD_TIMEOUT_S = 1800` timeout is expected and must be archived as
`UNRESOLVED` (`FAILURES.tsv`), never silently dropped or treated as crashing the whole batch
(fixed once in commit `c887ed8` after a timeout took an entire multi-hour `dev` run's
evidence with it — the partial pre-fix output was preserved under a
`artifacts/dev.failed-before-<fix-commit>` label rather than deleted, which is the right
pattern if you ever hit an analogous failure: keep partial evidence, label it, don't erase it).

## Disk hygiene

Check headroom before a big job: `ssh moe-server 'df -h /data /'`. Monitor growth:
`ssh moe-server 'du -x -d 2 /data/ziheng | sort -n | tail -20'`. Clean up stale experiment
directories **by exact name**, after their evidence has been archived/re-verified — never a
blind `rm -rf /data/ziheng/experiments/*`.

## Getting results back

Results are **not** scp'd/rsync'd to the local machine — inspect them in place over SSH
(`ssh moe-server 'cd <repo> && cat artifacts/dev/*.tsv'`, or a short inline
`.venv/bin/python -c "..."` reading an NPZ) and let only textual summaries flow back into
the conversation. For anything that genuinely needs to leave the server, use
`make package-dev` / `make package-heldout` (tars `artifacts/<split>` excluding `work/`,
writes a `.sha256`) and publish it as a GitHub Release rather than copying it to the laptop
or committing raw NPZ/`.steady` files into git.
