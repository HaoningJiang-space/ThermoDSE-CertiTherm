"""Analyse a counterbalanced deletion-order A/B run (step 3 of 6).

Reporting discipline, fixed deliberately so the write-up cannot drift:

  PRIMARY   deterministic counters -- oracle queries, POOL_REACHED, cover size, U.
            Verified bit-reproducible across repeats of a fixed configuration, so a
            difference between arms is attributable to the ordering. Reported per
            candidate with EVERY repetition shown, not just a summary.

  SECONDARY wall time, as PAIRED differences and log-ratios within a back-to-back
            pair, always alongside per-process CPU-seconds. Wall time on a shared
            host cannot distinguish "did more work" from "waited for CPU"; CPU
            seconds can.

  NOT CLAIMED at n=4: statistical significance, confidence intervals, a stable
            expected speedup, or generality. A paired sign test on four pairs has
            essentially no resolution, and a bootstrap interval would look more
            authoritative than four observations justify. This script therefore
            prints medians and full ranges and refuses to print a p-value or CI.

  COVER IDENTITY  equal U and equal cardinality do NOT imply the same cover. The
            symmetric difference and Jaccard similarity are reported, because two
            distinct equal-cost inclusion-minimal covers were already observed.

Also flags any counter that varies across repetitions of the SAME (candidate, order):
that is a finding needing explanation, not timing noise.

NON-CLAIM measurement.
Usage: python research/triangle/deletion_order_report.py <run_dir>
"""
from __future__ import annotations

import json
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

RUN = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if RUN is None or not (RUN / "logs").is_dir():
    print("usage: deletion_order_report.py <run_dir>  (needs <run_dir>/logs)")
    sys.exit(2)

KEY = re.compile(r"^r(\d+)_(.+)_c(\d+)_(cost|spectral)$")
GATE = re.compile(r"queries=(\d+)\s+probe_resolved=(\d+)\s+POOL_REACHED\(N\)=(\d+)\s+seq=(\d+)")


def parse_resource(path: Path):
    """user+sys CPU seconds and peak RSS from /usr/bin/time -v output."""
    if not path.exists():
        return None
    u = s = rss = None
    for line in path.read_text(errors="replace").splitlines():
        if "User time" in line:
            u = float(line.split(":")[-1])
        elif "System time" in line:
            s = float(line.split(":")[-1])
        elif "Maximum resident set size" in line:
            rss = float(line.split(":")[-1])
    if u is None or s is None:
        return None
    return {"cpu_s": u + s, "rss_kb": rss}


def parse_log(path: Path):
    txt = path.read_text(errors="replace")
    out = {}
    m = GATE.search(txt)
    if m:
        out.update(queries=int(m.group(1)), probe=int(m.group(2)),
                   pool=int(m.group(3)), seq=int(m.group(4)))
    m = re.search(r"verified feasible cover: (\d+) actions, U = (\d+)", txt)
    if m:
        out.update(cover_n=int(m.group(1)), U=float(m.group(2)))
    out["truncated"] = "budget-truncated" in txt
    m = re.search(r"--- result \(([^,]+),\s*(\d+) oracle calls\)", txt)
    if m:
        out["kind"] = m.group(1).strip()
        out["oracle_calls"] = int(m.group(2))
    return out


def main():
    runs = defaultdict(dict)                       # (wl,cand) -> (rep,order) -> record
    for log in sorted((RUN / "logs").glob("*.log")):
        m = KEY.match(log.stem)
        if not m:
            continue
        rep, wl, cand, order = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        rec = parse_log(log)
        res = parse_resource(log.with_suffix(".resource"))
        if res:
            rec.update(res)
        man = log.with_suffix(".manifest.json")
        if man.exists():
            j = json.loads(man.read_text())
            rec["cover_ids"] = frozenset(j.get("cover_action_ids", []))
            rec["completed"] = bool(j.get("completed_sweep"))
            rec["kernel_s"] = j.get("kernel_build_s")
            rec["initial_s"] = j.get("initial_verify_s")
        runs[(wl, cand)][(rep, order)] = rec

    if not runs:
        print("no parsable arms found"); sys.exit(2)

    print(f"run: {RUN}")
    truncated = [(k, rk) for k, v in runs.items() for rk, r in v.items()
                 if r.get("truncated") or r.get("completed") is False]
    if truncated:
        print(f"\nFAIL: {len(truncated)} arm(s) budget-truncated -> not inclusion-minimal; "
              f"the comparison is invalid: {truncated[:4]}")
        sys.exit(1)

    for (wl, cand), arms in sorted(runs.items()):
        print(f"\n=== {wl} c{cand} ===")
        reps = sorted({r for r, _ in arms})

        # --- PRIMARY: deterministic counters, every repetition shown ------------
        print("  PRIMARY (deterministic counters)")
        print(f"    {'rep':>3} {'order':>9} {'queries':>8} {'pool':>6} {'cover':>6} {'U':>7}")
        for rep in reps:
            for order in ("cost", "spectral"):
                r = arms.get((rep, order))
                if not r:
                    continue
                print(f"    {rep:>3} {order:>9} {r.get('queries','?'):>8} "
                      f"{r.get('pool','?'):>6} {r.get('cover_n','?'):>6} "
                      f"{r.get('U','?'):>7}")

        # counter stability within a fixed (candidate, order)
        for order in ("cost", "spectral"):
            for field in ("queries", "pool", "cover_n", "U"):
                vals = [arms[(rep, order)].get(field) for rep in reps
                        if (rep, order) in arms and arms[(rep, order)].get(field) is not None]
                if len(vals) > 1 and len(set(vals)) > 1:
                    print(f"    NOTE: {order}.{field} VARIES across repetitions "
                          f"{sorted(set(vals))} -- this is a finding to explain, not noise")

        # --- paired counter deltas ---------------------------------------------
        dq, dp = [], []
        for rep in reps:
            c, s = arms.get((rep, "cost")), arms.get((rep, "spectral"))
            if c and s and "queries" in c and "queries" in s:
                dq.append(s["queries"] - c["queries"])
                dp.append(s["pool"] - c["pool"])
        if dq:
            print(f"    paired delta queries (spectral-cost): {dq}  median={st.median(dq):+.0f}")
            print(f"    paired delta pool    (spectral-cost): {dp}  median={st.median(dp):+.0f}")

        # --- cover identity ----------------------------------------------------
        for rep in reps:
            c, s = arms.get((rep, "cost")), arms.get((rep, "spectral"))
            if not (c and s and c.get("cover_ids") and s.get("cover_ids")):
                continue
            A, B = c["cover_ids"], s["cover_ids"]
            inter, union = len(A & B), len(A | B)
            print(f"    rep{rep} cover identity: |A|={len(A)} |B|={len(B)} "
                  f"symmetric_diff={len(A ^ B)} jaccard={inter/union:.4f} "
                  f"same_set={A == B}"
                  + ("" if A == B else f"  (equal U={c.get('U')} yet DIFFERENT covers)"))

        # --- SECONDARY: paired wall time and CPU seconds -----------------------
        print("  SECONDARY (paired, shared host -- not a significance claim)")
        ratios = []
        for rep in reps:
            c, s = arms.get((rep, "cost")), arms.get((rep, "spectral"))
            if not (c and s and c.get("cpu_s") and s.get("cpu_s")):
                continue
            ratio = c["cpu_s"] / s["cpu_s"] if s["cpu_s"] else float("nan")
            ratios.append(ratio)
            print(f"    rep{rep} cpu_s cost={c['cpu_s']:.1f} spectral={s['cpu_s']:.1f} "
                  f"ratio={ratio:.3f}")
        if ratios:
            print(f"    cpu-second ratio (cost/spectral): median={st.median(ratios):.3f} "
                  f"range=[{min(ratios):.3f}, {max(ratios):.3f}]  n={len(ratios)}")
            print("    NOT a confidence interval; n is too small for an inferential claim.")

    print("\nReporting contract: counters are primary; wall/CPU time is paired secondary. "
          "No p-values, no confidence intervals, no generality claim at this n.")


if __name__ == "__main__":
    main()
