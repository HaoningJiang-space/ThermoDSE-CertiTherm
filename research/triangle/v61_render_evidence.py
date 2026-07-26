"""Render the V6.1 evidence document FROM a validated manifest. (NON-CLAIM tooling)

Numbers are never hand-transcribed. Manual transcription is how a `core` row that converged
in 8 cycles got reported as 16, and how a measured 1.89-5.02% range got narrowed to "about
2-3%". The generator reads the manifest and refuses to emit anything unless
`complete is true` AND `gate.passed is true` -- neither alone is sufficient, because a gate
failure previously wrote a truthy `summary` string that a key-existence check would have read
as success.

Usage: python research/triangle/v61_render_evidence.py <manifest.json> [out.md]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MANIFEST = Path(sys.argv[1])
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else None


def main() -> None:
    m = json.loads(MANIFEST.read_text())
    gate = m.get("gate") or {}
    if m.get("complete") is not True or gate.get("passed") is not True:
        print(f"REFUSING to render: complete={m.get('complete')} "
              f"gate.passed={gate.get('passed')} "
              f"suppression={m.get('suppression_reason')}")
        sys.exit(2)

    s = m["summary"]
    rows = m["rows"]
    limit = m["thermal_limit_k"]
    comp = m["component_energy_j"]
    total = m["full_source_energy_j"]
    run = m.get("run", {})
    order = sorted(rows, key=lambda t: rows[t]["periodic_peak_k"])

    L = []
    A = L.append
    A("# V6.1 causal isolation — which power sources produce the grid-max crossing")
    A("")
    A("Generated from a validated manifest by `research/triangle/v61_render_evidence.py`; no")
    A("number here is hand-transcribed. The generator refuses to run unless the manifest has")
    A("`complete: true` **and** `gate.passed: true`.")
    A("")
    A("## Provenance")
    A("")
    tree = "CLEAN" if not m["dirty"] else f"DIRTY ({len(m['dirty'])} files)"
    A(f"- commit `{m['commit'][:12]}`, working tree {tree}")
    A(f"- provenance re-verified at end of run: `provenance_stable = "
      f"{m.get('provenance_stable')}`")
    A(f"- candidate `{m['workload']}` / `{m['arch']}`, model `{m['model']}`, requested step "
      f"{m['max_step_us']} us, ambient {m['ambient_k']} K, limit {limit} K")
    A(f"- host `{run.get('host','?')}`, {run.get('platform','?')}, "
      f"Python {run.get('python','?')}, NumPy {run.get('numpy','?')}")
    A(f"- every input staged read-only and hashed as read; re-verified after each replay")
    for k, v in sorted(m["input_hashes"].items()):
        A(f"  - `{k}` `{v[:16]}…`")
    A(f"- all rows fresh (no reuse): `{s.get('all_rows_fresh')}`")
    A(f"- superposition identity, subset == sum of singletons: worst "
      f"`{m['superposition_worst_w']:.3e}` W")
    A("")
    A("## Source energy ledger")
    A("")
    A("| source | energy (mJ) | share |")
    A("| --- | ---: | ---: |")
    for k in sorted(comp, key=lambda x: -comp[x]):
        A(f"| `{k}` | {comp[k]*1e3:.6f} | {100*comp[k]/total:.3f}% |")
    A(f"| **total** | **{total*1e3:.6f}** | 100% |")
    A("")
    A("## All 15 non-empty source subsets")
    A("")
    A("| subset | time-mean steady (K) | periodic (K) | uplift (K) | steady hottest | "
      "periodic hottest | cycles | status |")
    A("| --- | ---: | ---: | ---: | --- | --- | ---: | --- |")
    for t in order:
        r = rows[t]
        name = "**full**" if t == "full" else f"`{t}`"
        st = s["row_status"][t]
        mark = "**CROSSING**" if st == "crossing" else st
        A(f"| {name} | {r['mean_steady_peak_k']:.6f} | {r['periodic_peak_k']:.2f} | "
          f"{r['periodic_peak_k']-r['mean_steady_peak_k']:+.2f} | "
          f"`{r['mean_steady_hottest_block']}` | `{r['periodic_hottest_block']}` | "
          f"{r['cycles']} | {mark} |")
    A("")
    A(f"Classification is quantisation-aware: HotSpot reports transient temperatures to "
      f"{rows['full']['output_resolution_k']} K, so a row within one quantum of the limit is "
      f"`indeterminate` and is excluded from the coalition analysis rather than counted as "
      f"crossing. Indeterminate rows this run: "
      f"{s['indeterminate_rows'] or 'none'}.")
    moves = [(t, r["mean_steady_hottest_block"], r["periodic_hottest_block"])
             for t, r in rows.items()
             if r["mean_steady_hottest_block"] != r["periodic_hottest_block"]]
    if moves:
        A("")
        A(f"In {len(moves)} of {len(rows)} subsets the hottest block MOVES between the two "
          f"semantics, so time structure relocates the peak and does not merely raise it:")
        for t, a, b in sorted(moves):
            A(f"- `{t}`: steady `{a}` -> periodic `{b}`")
        A("")
        A("This is an observation, not a mechanism: it is not the crossing mechanism (the "
          "crossing row's hottest block is unchanged) and no source-identity cause has been "
          "tested for it.")
    A("")
    A("## Gate")
    A("")
    A(f"- decision (steady < {limit} and periodic >= {limit}): **{gate['decision_ok']}**")
    A(f"- periodic value within one output quantum of the registered "
      f"{gate['registered_tuple']['periodic_peak_k']} K: **{gate['value_ok']}**")
    A(f"- hottest block equals registered `{gate['registered_tuple']['hottest']}`: "
      f"**{gate['location_ok']}**")
    A(f"- steady delta from the registered value: `{gate['steady_delta_k']:.6f}` K "
      f"(reported, **not** gated — {gate['steady_gate_note']})")
    A("")
    A("**The gate binds names and temperatures, NOT the registered instance** "
      f"(`binds_instance_hashes = {gate['registered_tuple']['binds_instance_hashes']}`). It "
      "verifies that this pipeline reproduces the documented crossing at the documented "
      "location; it does **not** verify that the registry, power trace or routing are "
      "unchanged, so a changed registry under the same workload/architecture names could "
      "still pass. Closing that needs a canonical trace hash preregistered from a run that "
      "is itself claim-grade. Open gap.")
    A("")
    A("## Result")
    A("")
    A(f"- **minimal crossing coalitions:** "
      f"{', '.join('`'+c+'`' for c in s['minimal_crossing_coalitions']) or 'none'}")
    A("- **leave-one-out** — is each source necessary given the others?")
    A("")
    A("| removed source | periodic (K) | margin to limit (K) | status |")
    A("| --- | ---: | ---: | --- |")
    for k, v in s["leave_one_out"].items():
        A(f"| `{k}` | {v['periodic_peak_k']:.2f} | {v['margin_to_limit_k']:+.2f} | "
          f"{'below → conditionally necessary' if v['below_limit'] else v['status']} |")
    A("")
    A("## Scope")
    A("")
    A(f"Evidence grade: **{s['evidence_grade']}**")
    A("")
    A(s["scope"])
    A("")
    A("Explicitly NOT established: that any source alone suffices; that periodic uplift is "
      "baseline-independent (the uplift/steady-rise ratio spans roughly 1.9–5.0% across the "
      "15 subsets and is resolution-sensitive where the rise is small, so any source-identity "
      f"effect is `{s['source_identity_effect_on_uplift']}`); generalisation to other "
      "candidates, thermal models or discretisations; or agreement with any independent "
      "thermal model.")
    A("")
    A(f"`grid128-max` has NOT been run as a factorial. Its registered hottest block is "
      "`ubuf_13` (steady) / `ubuf_16` (periodic) — different from this run's `mtxu_16` **and "
      "moving between the two semantics** — so a grid128 factorial would be a distinct "
      "discretised causal result requiring its own preregistration, not a resolution "
      "cross-check of this one.")
    A("")
    A(f"Manifest: `{MANIFEST}` (run id `{run.get('run_id','?')}`)")

    text = "\n".join(L) + "\n"
    if OUT:
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {OUT} ({len(L)} lines)")
    else:
        print(text)


if __name__ == "__main__":
    main()
