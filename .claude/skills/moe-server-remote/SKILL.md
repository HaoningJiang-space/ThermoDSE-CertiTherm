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

`moe-server` is already configured in `~/.ssh/config`. Use
`scripts/remote_exec.sh` in this skill rather than ad hoc
`ssh` one-liners — it encodes the connection options and patterns actually used in practice
(`ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=20
-o ServerAliveCountMax=3 moe-server '...'`). See `scripts/remote_exec.sh --help`.

## Setup pattern

Fresh clone into a unique, disk-hygienic directory, never reusing a stale one:

```bash
scripts/remote_exec.sh --new-clone dsos-check 'make bootstrap && make check'
```

By default this clones with `git clone --recurse-submodules` from `origin`
(GitHub) into `$CERTITHERM_REMOTE_BASE/certitherm-<label>.XXXXXX` — **not**
rsync. A credential-free clone from the `moe` bare mirror is also acceptable
when its branch SHA is explicitly checked against the pushed commit. Everything
— venv, HotSpot build, artifacts — stays
under the remote user's data root; the server's root disk is capacity-constrained.
The wrapper derives that user from `ssh -G moe-server`; set
`CERTITHERM_REMOTE_BASE` only when the server layout differs.

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
scripts/remote_exec.sh --background <remote-clone>/repo dev-run 'make reproduce-dev'
scripts/remote_exec.sh --status   <remote-clone>/repo dev-run
```

**HotSpot forks worker subprocesses under the tracked PID.** Killing only the parent PID
leaves orphaned HotSpot children burning CPU. Always kill children first:

```bash
scripts/remote_exec.sh --kill <remote-clone>/repo dev-run
```

(This finds children via `pgrep -P $pid`, kills them, then the parent, escalating to
`kill -KILL` if still alive after a couple seconds.)

Tuning: `CERTITHERM_LP_WORKERS` defaults to 1 because per-iteration process
creation was measured as a severe pessimization. Independent v3 queries use
one persistent pool controlled by `CERTITHERM_QUERY_WORKERS` (frozen at 3);
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

## What the host actually is (measured 2026-08-02)

`hpclab03`, **52 cores**, **125 GB RAM** (≈108 GB available), **2× NVIDIA A800 80 GB**.
Verify rather than assume before sizing a job:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=15 moe-server \
  'hostname; nproc; free -g | head -2; nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader; df -h /data | tail -1'
```

**The box is shared.** A measured FEM comparison in this repo was polluted exactly this way —
306 s vs 265 s with 9 other jobs contending for the 52 cores, which made the runtime comparison
uninterpretable. Before timing anything, check contention (`uptime`, `nvidia-smi`) and record it
in the ledger; a timing number without a contention record is not evidence.

## Disk hygiene — currently acute

**`/data` measured at 95 % full: 3.1 T used of 3.5 T, ~170 G free.** That is not headroom for a
large sweep. Check before every big job:

```bash
ssh moe-server 'df -h /data /'
```

Monitor the configured remote data root rather than a hard-coded user directory. Clean up stale
experiment directories **by exact name**, after their evidence has been archived/re-verified —
never a blind recursive deletion of the experiment root. `/data` is shared with other users;
do not reclaim space outside this project's own directories.

## Provenance a claim-grade run must carry

Adopted after `HEAD` moved more than a dozen times during one round's analysis, and a
cell-endpoint run was found not to have bound its starting SHA. **A run started from a moving
checkout is not attributable and cannot be repaired afterwards.**

Before starting: an isolated worktree at a pinned SHA, clean tree, submodules verified
(`git submodule status --recursive`). Every result artifact records: the starting SHA, the
input and config digests, the binary digest, the exit status — and, because the locked
dependency set is what makes the suite reproducible, **the interpreter actually used**. A local
system interpreter without the pinned `.venv` fails `test_precheck.py` on a missing `tabulate`
that `requirements.lock` pins at 0.9.0; a test summary that does not name its interpreter cannot
be compared against one that does.

## Getting results back

Results are **not** scp'd/rsync'd to the local machine — inspect them in place over SSH
(`ssh moe-server 'cd <repo> && cat artifacts/dev/*.tsv'`, or a short inline
`.venv/bin/python -c "..."` reading an NPZ) and let only textual summaries flow back into
the conversation. For anything that genuinely needs to leave the server, use
`make package-dev` / `make package-heldout` (tars `artifacts/<split>` excluding `work/`,
writes a `.sha256`) and publish it as a GitHub Release rather than copying it to the laptop
or committing raw NPZ/`.steady` files into git.
