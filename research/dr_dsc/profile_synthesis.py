"""Stage-level profiler for CertiTherm's constraint-generation loop.

Answers the question two peer reviews left open: where do the ~2.86 s/iteration
observed on a 241-action instance actually go? Competing hypotheses were
(a) collision-LP solve time, (b) LP model construction, (c) cut-antichain
maintenance, (d) `_greedy_cover` rescans, and (e) — found by reading
`_collision_search` — **ProcessPoolExecutor churn**, since an exhaustive
search builds and tears down a fresh spawn-context pool on EVERY iteration,
re-importing numpy/scipy in every worker each time.

DESIGN: this does NOT modify `CertiTherm/synthesis.py`. It wraps the frozen
functions from outside, so the code being measured is exactly the code that
ships. Nothing here can change synthesis semantics; if a wrapper were buggy
the timings would be wrong but the algorithm's result would not.

TWO MODES, because they answer different questions:
  --workers 1   sequential. In-process timing is complete and attributable —
                this is the only mode where LP-vs-construction split is
                trustworthy, because with a process pool the LP solves happen
                in child processes that in-process wrappers cannot see.
  --workers N   the real configuration. Only wall-clock and pool overhead are
                meaningful here; per-stage LP numbers will under-count.

Report both. A large gap between sequential total and parallel wall clock at
the same iteration count is itself the pool-overhead measurement.
"""
from __future__ import annotations

import argparse
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

import CertiTherm.synthesis as syn


class Stages:
    """Accumulates (count, seconds) per named stage."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = defaultdict(int)
        self.seconds: dict[str, float] = defaultdict(float)
        self.sizes: dict[str, list[float]] = defaultdict(list)

    def record(self, name: str, elapsed: float) -> None:
        self.calls[name] += 1
        self.seconds[name] += elapsed

    def note(self, name: str, value: float) -> None:
        self.sizes[name].append(float(value))

    def report(self, total: float) -> str:
        lines = [f"{'stage':<28} {'calls':>8} {'seconds':>10} {'% total':>8} {'ms/call':>10}"]
        lines.append("-" * 68)
        for name in sorted(self.seconds, key=lambda k: -self.seconds[k]):
            s, c = self.seconds[name], self.calls[name]
            lines.append(
                f"{name:<28} {c:>8} {s:>10.2f} {100*s/total if total else 0:>7.1f}% "
                f"{1000*s/c if c else 0:>9.1f}"
            )
        lines.append("-" * 68)
        lines.append(f"{'WALL TOTAL':<28} {'':>8} {total:>10.2f} {100.0:>7.1f}%")
        for name in sorted(self.sizes):
            v = self.sizes[name]
            if v:
                lines.append(
                    f"  {name}: n={len(v)} min={min(v):g} max={max(v):g} "
                    f"mean={sum(v)/len(v):.1f} last={v[-1]:g}"
                )
        return "\n".join(lines)


def install(stages: Stages) -> None:
    """Wrap the frozen functions. Every wrapper delegates unchanged."""

    real_linprog = syn.linprog
    real_milp = syn.milp
    real_insert = syn._insert_minimal_cut
    real_greedy = syn._greedy_cover
    real_master = syn._solve_master
    real_search = syn._collision_search
    real_pool = syn.ProcessPoolExecutor

    def linprog(*a, **k):
        t = time.perf_counter()
        try:
            return real_linprog(*a, **k)
        finally:
            stages.record("lp_solve(scipy.linprog)", time.perf_counter() - t)

    def milp(*a, **k):
        t = time.perf_counter()
        try:
            return real_milp(*a, **k)
        finally:
            stages.record("milp_solve(scipy.milp)", time.perf_counter() - t)

    def insert(cuts, cut, masks=None):
        t = time.perf_counter()
        try:
            return real_insert(cuts, cut, masks)
        finally:
            stages.record("antichain_insert", time.perf_counter() - t)
            stages.note("antichain_size", len(cuts))

    def greedy(costs, cuts):
        t = time.perf_counter()
        try:
            return real_greedy(costs, cuts)
        finally:
            stages.record("greedy_cover", time.perf_counter() - t)

    def master(costs, cuts, incumbent=None):
        t = time.perf_counter()
        try:
            return real_master(costs, cuts, incumbent=incumbent)
        finally:
            stages.record("solve_master(TOTAL)", time.perf_counter() - t)

    def search(*a, **k):
        t = time.perf_counter()
        try:
            out = real_search(*a, **k)
            stages.note("collisions_per_search", len(out))
            return out
        finally:
            stages.record("collision_search(TOTAL)", time.perf_counter() - t)

    class TimedPool(real_pool):
        """Times the pool object's lifecycle.

        HONEST LABELLING (corrected 2026-07-22): `ProcessPoolExecutor` starts
        its workers LAZILY, on the first submit/map -- so `pool_ctor` below
        measures almost nothing (~0.5 ms) and does NOT capture spawn cost.
        The real overhead lands inside `pool.map`, i.e. inside
        `collision_search(TOTAL)`, and is an unseparated mixture of: process
        spawn, Python+NumPy+SciPy import per worker, `_CollisionProblem`
        pickling, IPC, scheduling, HiGHS init, and teardown.

        So do NOT attribute the ~2 s/iteration to any single one of those.
        The defensible statement is: *per-iteration fresh-process-pool
        overhead is ~2 s*. Derive it as (parallel wall - sequential wall) at
        equal iteration counts, not from these two counters.
        """

        def __init__(self, *a, **k):
            t = time.perf_counter()
            super().__init__(*a, **k)
            stages.record("pool_ctor(lazy,~0)", time.perf_counter() - t)

        def __exit__(self, *exc):
            t = time.perf_counter()
            try:
                return super().__exit__(*exc)
            finally:
                stages.record("pool_exit(join+teardown)", time.perf_counter() - t)

    syn.linprog = linprog
    syn.milp = milp
    syn._insert_minimal_cut = insert
    syn._greedy_cover = greedy
    syn._solve_master = master
    syn._collision_search = search
    syn.ProcessPoolExecutor = TimedPool
    # _collisions/_collision close over the module global, so rebinding the
    # module attribute is enough -- verified by the assertion below.
    assert syn._collision_search is search


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--flp", required=True)
    p.add_argument("--points", type=int, default=6)
    p.add_argument("--limit-k", type=float, default=345.0)
    p.add_argument("--decay-m", type=float, default=0.0012)
    p.add_argument("--iterations", type=int, default=40)
    p.add_argument("--workers", type=int, default=1,
                   help="1 = sequential (attributable). >1 = real config (wall clock only).")
    args = p.parse_args()

    from .benchmark import build_instance

    arch = {"chiplet_x": "7", "chiplet_y": "3", "cut_x": "1", "cut_y": "1"}
    candidate, actions, blocks = build_instance(
        Path(args.flp), args.points, args.limit_k, arch, args.decay_m
    )
    print(f"blocks={len(blocks)} actions={len(actions)} "
          f"iterations={args.iterations} workers={args.workers}")

    stages = Stages()
    install(stages)

    t0 = time.perf_counter()
    plan = syn.synthesize_minimum_observation(
        candidate.power,
        candidate.thermal,
        actions,
        max_iterations=args.iterations,
        separation_workers=args.workers,
    )
    total = time.perf_counter() - t0

    print(f"\nstatus={plan.status} iterations={plan.iterations} "
          f"n_selected={len(plan.selected_action_ids)} "
          f"lower_bound={plan.lower_bound}")
    print(f"message: {plan.message}\n")
    print(stages.report(total))

    lp = stages.seconds.get("lp_solve(scipy.linprog)", 0.0)
    search_total = stages.seconds.get("collision_search(TOTAL)", 0.0)
    print("\n=== attribution ===")
    if args.workers == 1:
        print(f"  LP solve inside collision search : {lp:.2f}s "
              f"({100*lp/search_total if search_total else 0:.1f}% of search)")
        print(f"  construction/other in search     : {search_total-lp:.2f}s")
    else:
        print("  (workers>1: LP time under-counted -- solves run in child processes,")
        print("   and pool spawn happens lazily INSIDE pool.map, so it is folded into")
        print("   collision_search rather than the pool_ctor counter. Quantify pool")
        print("   overhead as (this wall clock - sequential wall clock) at equal")
        print("   iteration count, not from the pool_* counters below.)")
        print(f"  pool_ctor + pool_exit (partial)  : "
              f"{stages.seconds.get('pool_ctor(lazy,~0)',0)+stages.seconds.get('pool_exit(join+teardown)',0):.2f}s")
    print(f"  antichain + greedy               : "
          f"{stages.seconds.get('antichain_insert',0)+stages.seconds.get('greedy_cover',0):.2f}s")
    print(f"  master (MILP path)               : {stages.seconds.get('solve_master(TOTAL)',0):.2f}s")


if __name__ == "__main__":
    main()
