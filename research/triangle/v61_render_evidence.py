"""Format the V6.1 evidence document from a VALIDATED view. (NON-CLAIM tooling)

Formatting only. Every number, classification and verdict comes from
`research/triangle/v61_validate.py`, which recomputes them from the manifest's raw observations
and refuses on any disagreement -- so this module cannot quietly become the place where a claim
is decided. It was, twice: once when it printed `summary.row_status` verbatim, and again when it
printed the manifest's own gate verdicts.

Usage: python research/triangle/v61_render_evidence.py <manifest.json> [out.md]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.triangle.v61_contract import REGISTRATION, Refuse, rel  # noqa: E402
from research.triangle.v61_validate import build_with_mechanism  # noqa: E402


def render(m: dict, v: dict, g: dict, ex: dict, manifest_path: Path) -> str:
    rows, q, limit = v["rows"], v["quantum"], v["limit"]
    comp, comps, view = v["comp"], v["comps"], v["view"]
    total = m["full_source_energy_j"]
    run, reg, excess = v["run"], g["reg"], v["excess_k"]
    full = v["full"]
    n = len(rows)
    L: list[str] = []
    A = L.append

    A("# V6.1 source-subset isolation under a fixed additive power trace")
    A("")
    A(f"Recomputed from the manifest's raw observations by `research/triangle/v61_validate.py`: "
      f"the subset enumeration; every row's peak, argmax, runner-up and resolution-aware tie "
      f"set, from the per-block temperature vectors; the classification, crossing coalitions and "
      f"leave-one-out table; convergence; the energy ledger; cross-row provenance; and the gate, "
      f"against the pinned registration `{rel(REGISTRATION)}` rather than the manifest's own "
      f"copy of its verdicts. Any disagreement is a refusal. **Producer-attested, and not "
      f"re-derived here:** the temperatures themselves, the superposition residual, and the "
      f"execution receipts. The raw HotSpot outputs they hash ARE retained, outside this "
      f"repository, so an independent consumer can reparse them — this generator does not.")
    A("")
    A("## Provenance")
    A("")
    A(f"- commit `{m['commit'][:12]}`, working tree CLEAN at start and end "
      f"(`provenance_stable = {m['provenance_stable']}`)")
    A(f"- candidate `{m['workload']}` / `{m['arch']}`, model `{m['model']}`, requested step "
      f"{m['max_step_us']} us, ambient {v['ambient']} K, limit {limit} K, "
      f"{len(v['block_ids'])} floorplan blocks")
    A(f"- host `{run.get('host','?')}`, {run.get('platform','?')}, "
      f"Python {run.get('python','?')}, NumPy {run.get('numpy','?')}, manifest schema "
      f"{run['schema_version']}, gate policy {g['policy_version']}")
    A(f"- run `{run['run_id']}`, wall {(run['ended_unix']-run['started_unix'])/60:.1f} min")
    A(f"- registration `{g['pinned']['registration_id']}`, file unchanged since the run: "
      f"`{g['registration_intact']}`")
    A("- every input staged read-only, hashed as read, re-verified after each replay:")
    for k, h in sorted(m["input_hashes"].items()):
        A(f"  - `{k}` `{h[:16]}…`")
    A(f"- superposition identity, subset == sum of singletons: worst "
      f"`{m['superposition_worst_w']:.3e}` W (producer-attested)")
    A("")
    earlier = g["pinned"]["earlier_hotspot_binary_sha256"]
    same = m["hotspot_sha256"] == earlier["sha256"]
    A(f"**This run is not an independent numerical confirmation of the registered numbers, and "
      f"nothing here should be read as one.** The staged HotSpot binary is "
      f"{'byte-identical to' if same else 'DIFFERENT from'} the one used by the earlier "
      f"transient work (`{earlier['document']}:{earlier['line']}`). With the same binary, "
      f"inputs, code and platform, agreement to the last printed digit — including the "
      f"`{g['steady_delta_k']:.3e}` K steady residual against a value quoted to six decimals — "
      f"is what arithmetic requires. It evidences a reproducible build and an intact provenance "
      f"chain; it evidences nothing about the physics and nothing about whether a solver ran.")
    A("")
    A("### Execution receipts (producer-attested, not proof of execution)")
    A("")
    inv = sum(r["hotspot_invocations"] for r in ex["receipts"].values())
    outs = sum(r["hotspot_outputs"] for r in ex["receipts"].values())
    ins = sum(r["driver_inputs"] for r in ex["receipts"].values())
    mb = sum(r["output_bytes"] for r in ex["receipts"].values()) / 1e6
    A(f"Each row records that its directory and HotSpot workspace did not exist beforehand, its "
      f"PID, a wall window inside the run's, this run's nonce, and **one record per HotSpot "
      f"process** — role, argv, return code, wall window, and the output it wrote with that "
      f"file's SHA-256 and byte size. Across {n} rows: **{inv} invocations** writing "
      f"**{outs} output files** totalling {mb:.1f} MB, plus {ins} driver-written `.ptrace` "
      f"inputs, all hashed.")
    A("")
    A(f"Validated: the recorded role sequence is `mean-steady`, `fixed-initial`, then a doubling "
      f"series of `periodic-N` whose last N equals the row's converged cycle count; every return "
      f"code is 0; no two invocations claim the same output; every recorded output hash matches "
      f"the workspace hash for that filename; and no invocation claims a `.ptrace` input as its "
      f"own output. So an **inconsistent** producer is caught. A **dishonest** one is not: these "
      f"fields are self-attested, the raw bytes are not archived in this repository, and nothing "
      f"re-hashes them at render time. That is why this section is not called proof.")
    A("")
    A("| subset | invocations | outputs | output MB | wall (s) | cycles |")
    A("| --- | ---: | ---: | ---: | ---: | ---: |")
    for t in sorted(rows, key=lambda t: ex["receipts"][t]["started_unix"]):
        r = ex["receipts"][t]
        A(f"| `{t}` | {r['hotspot_invocations']} | {r['hotspot_outputs']} | "
          f"{r['output_bytes']/1e6:.1f} | {r['wall_s']:.1f} | {rows[t]['cycles']} |")
    A("")
    A("## Source energy ledger")
    A("")
    A(f"Reproduced exactly by all {n} rows: each row's retained energy equals the sum of its "
      f"components' entries here, to 1e-15 J.")
    A("")
    A("| source | energy (mJ) | share |")
    A("| --- | ---: | ---: |")
    for k in sorted(comp, key=lambda x: -comp[x]):
        A(f"| `{k}` | {comp[k]*1e3:.6f} | {100*comp[k]/total:.3f}% |")
    A(f"| **total** | **{total*1e3:.6f}** | 100% |")
    A("")
    A(f"## All {n} non-empty source subsets")
    A("")
    A("| subset | time-mean steady (K) | periodic (K) | uplift (K) | steady argmax | "
      "periodic argmax | tied | cycles | status |")
    A("| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | --- |")
    for t in sorted(rows, key=lambda t: view[t]["periodic"]["peak_k"]):
        d = view[t]
        A(f"| {'**full**' if t == v['full_tag'] else '`'+t+'`'} | "
          f"{d['steady']['peak_k']:.6f} | {d['periodic']['peak_k']:.2f} | "
          f"{d['uplift_k']:+.2f} | `{d['steady']['block']}` | `{d['periodic']['block']}` | "
          f"{len(d['periodic']['ties'])} | {rows[t]['cycles']} | "
          f"{'**CROSSING**' if d['status'] == 'crossing' else d['status']} |")
    A("")
    A(f"HotSpot reports transient temperature to {q} K, so with a {limit} K limit a row is "
      f"`crossing` iff `periodic >= {limit+q}` K, `below` iff `periodic <= {limit-q}` K, and "
      f"`indeterminate` otherwise — exactly {limit} K is **not** a crossing. Indeterminate "
      f"rows: {', '.join('`'+t+'`' for t in v['indeterminate']) or 'none'}. Every row converged "
      f"to within its {rows[v['full_tag']]['tolerance_k']} K tolerance, which equals the output "
      f"quantum: convergence is at the observability floor, not below it. The `tied` column is "
      f"the number of blocks within one quantum of that row's peak — see the appendix.")
    A("")
    A("## Gate")
    A("")
    A(f"Recomputed against `{rel(REGISTRATION)}` (`{g['pinned']['registration_id']}`, gate "
      f"policy {g['policy_version']}), whose registered tuple the manifest must match exactly:")
    A("")
    A(f"- decision — steady < {limit} K **and** the full row classifies as `crossing` under the "
      f"same quantisation rule as every other row: **{g['decision_ok']}**")
    A(f"- periodic value within one {q} K quantum of the registered "
      f"{reg['periodic_peak_k']} K: **{g['value_ok']}**")
    A(f"- location — the registered `{reg['hottest']}` sits at "
      f"{g['registered_block_k']:.2f} K against a peak of {full['periodic']['peak_k']:.2f} K, "
      f"i.e. within one quantum of the maximum: **{g['location_compatible']}**")
    A(f"- steady delta from the registered value: `{g['steady_delta_k']:.3e}` K (reported, "
      f"**not** gated — no repeatability-derived tolerance exists)")
    A("")
    A(f"**The location check is a compatibility test, not spatial reproduction.** It asserts "
      f"only that the registered block cannot be distinguished from the maximum at HotSpot's "
      f"output resolution. Gate policy 1 required exact argmax equality, which depended on how "
      f"an exact tie was broken: {len(ex['tied_rows'])} of {n} rows here have a tied argmax, and "
      f"refactoring the argmax from a flat maximum over (sample, block) to a per-block maximum "
      f"flipped one row's reported label with every temperature unchanged. Exact equality still "
      f"holds this run (`argmax_equals = {g['argmax_equals']}`) but is reported, not gated. The "
      f"predicate is computed from the registered block's own temperature, not from a "
      f"producer-reported tie list — such a list could name any block, since nothing in it is "
      f"tied to a temperature.")
    A("")
    canon = g["pinned"]["canonical_instance"]
    A(f"**The gate binds the physical instance** (`binds_instance_hashes = "
      f"{reg['binds_instance_hashes']}`, `canonical_trace_sha256 = "
      f"{reg['canonical_trace_sha256'][:16]}…`). Enforced against the canonical instance: the "
      f"staged input hashes, the HotSpot binary, the {canon['block_count']}-block floorplan "
      f"registry hash, all {len(canon['trace_sha256_by_subset'])} per-subset power-trace hashes, "
      f"and the source energy decomposition. Until gate policy 3 the gate bound names and "
      f"temperatures only, so a changed registry, trace or routing under the same "
      f"workload/architecture names would have passed.")
    A("")
    A(f"**What that does and does not establish.** These hashes were *canonicalised from* the "
      f"schema-4 claim-grade run (`{canon['canonicalised_from']['manifest']}`, commit "
      f"`{canon['canonicalised_from']['commit'][:12]}`), **not preregistered ahead of the "
      f"fact** — the originally registered run in `{g['pinned']['grid64_source']['document']}` "
      f"predates this pipeline and no hash of its inputs survives. So the binding guarantees "
      f"that this run replayed the same physical instance as the run the evidence rests on. It "
      f"does **not** establish that either run replayed the instance behind the original "
      f"registered numbers. That link cannot be recovered and is closed only for runs from here "
      f"on.")
    A("")
    A("## Result")
    A("")
    if v["uniqueness_claimable"]:
        A(f"The {n} rows exhaust every non-empty subset of "
          f"{{{', '.join('`'+c+'`' for c in comps)}}} with no indeterminate row, and exactly one "
          f"of them crosses: **`{v['minimal'][0]}`** is the unique minimal crossing coalition in "
          f"this factorial. That is a statement about this trace, this candidate and this "
          f"discretisation — not about candidates, traces or discretisations in general.")
    else:
        A(f"Minimal crossing coalitions: "
          f"{', '.join('`'+c+'`' for c in v['minimal']) or 'none'}. Uniqueness is **not** "
          f"claimable: {len(v['minimal'])} minimal coalition(s) and "
          f"{len(v['indeterminate'])} indeterminate row(s).")
    A("")
    A("### Leave-one-out is an arithmetic consequence, not a second finding")
    A("")
    d = {k: x["removal_delta_k"] for k, x in v["loo"].items()}
    lo_k = min(d, key=lambda k: d[k])
    arithmetic = (all(x["status"] == "below" for x in v["loo"].values())
                  and min(d.values()) >= excess + q)
    A(f"The full set crosses by only **{excess:+.2f} K** ({full['periodic']['peak_k']:.2f} K "
      f"against a {limit} K limit). "
      + (f"Every removal costs at least a full {q} K quantum more than that excess (smallest: "
         f"{d[lo_k]:+.2f} K for `{lo_k}`), so once the exhaustive factorial shows the full set "
         f"is the only crossing subset, all {len(d)} leave-one-out verdicts follow with no "
         f"further information. This is **Boolean threshold necessity within a fixed "
         f"factorial**, not a measure of physical causal importance."
         if arithmetic else
         f"Not every removal clears the excess by a full {q} K quantum (smallest: "
         f"{d[lo_k]:+.2f} K for `{lo_k}`), so the verdicts are not purely arithmetic — read the "
         f"table row by row."))
    A("")
    A("| removed source | periodic (K) | removal delta (K) | delta / excess | "
      "margin to limit (K) | status |")
    A("| --- | ---: | ---: | ---: | ---: | --- |")
    for k in sorted(v["loo"], key=lambda k: -d[k]):
        x = v["loo"][k]
        A(f"| `{k}` | {x['periodic']['peak_k']:.2f} | {x['removal_delta_k']:+.2f} | "
          f"{x['removal_delta_k']/excess:.1f}x | {x['margin_to_limit_k']:+.2f} | "
          f"{'below → necessary in the grand coalition' if x['status'] == 'below' else x['status']} |")
    A("")
    A(f"The informative row is the smallest. `{lo_k}` carries {100*comp[lo_k]/total:.3f}% of the "
      f"dissipated energy yet its removal drops the periodic peak by {d[lo_k]:.2f} K — "
      f"{d[lo_k]/excess:.1f}x the excess and {d[lo_k]/q:.0f}x the {q} K quantum. Energy share "
      f"does not predict which source decides the threshold; the deltas do, and they are what a "
      f"paper table should carry rather than the necessity label.")
    A("")
    A("## Appendix — why the reported hottest block is tied, and by two different mechanisms")
    A("")
    tied = ex["tied_rows"]
    exact = sorted(t for t in view if view[t]["steady"]["gap_k"] == 0.0)
    A(f"**The statistic to use here is the steady one, not the periodic one.** {len(tied)} of {n} "
      f"rows have more than one block within one {q} K quantum of the *periodic* peak, but a "
      f"top-two gap of zero in a value serialised to {q} K is what quantisation *produces* — it "
      f"cannot show the underlying temperatures are equal. The mean-steady block output carries "
      f"ten decimals (this repository patches `%.2f` to `%.10f` for the block dump, though not "
      f"for the per-cell dump), and there **{len(exact)} of {n}** rows have a top-two gap of "
      f"exactly `0.000e+00` — the same double, bit for bit. An earlier version of this appendix "
      f"cited the periodic count for a claim only the steady values support.")
    A("")
    tm = ex.get("tie_mechanism") or {}
    if tm:
        c = tm["mechanism_counts"]
        g_ = tm["grid"]
        A(f"`research/triangle/v61_tie_mechanism.py` reconstructs HotSpot's `g2bmap` rectangle for "
          f"all {len(v['block_ids'])} blocks from the floorplan this run was produced from "
          f"(hash-verified against the manifest) and the {g_['rows']}x{g_['cols']} grid "
          f"({g_['cell_w_m']*1e6:.1f} x {g_['cell_h_m']*1e6:.1f} um cells over "
          f"{g_['chip_w_m']*1e3:.2f} x {g_['chip_h_m']*1e3:.2f} mm). Under `GRID_MAX` a block's "
          f"temperature is `max` over that rectangle — a value **copied** from one cell — and the "
          f"rectangle is rounded outward, so it covers every cell the block touches. Two blocks "
          f"therefore share cells when their common boundary falls *inside* a cell; a "
          f"grid-aligned boundary produces none.")
        A("")
        A("| subset | top two blocks | steady gap (K) | shared cells | mechanism |")
        A("| --- | --- | ---: | ---: | --- |")
        for tag in sorted(tm["rows"], key=lambda t: tm["rows"][t]["steady_gap_k"]):
            r = tm["rows"][tag]
            A(f"| `{tag}` | `{r['top_two'][0]}` / `{r['top_two'][1]}` | "
              f"{r['steady_gap_k']:.3e} | {r['shared_cells']} | {r['mechanism']} |")
        A("")
        A(f"**Mechanism 1 — a shared boundary cell ({c['shared_cell']} rows).** Every "
          f"bit-identical pair has overlapping rectangles, so the same cell value is available to "
          f"both. In the crossing row `{reg['hottest']}` and its partner share "
          f"{tm['rows'][v['full_tag']]['shared_cells']} cells.")
        A("")
        A(f"**Mechanism 2 — floorplan symmetry ({c['symmetric']} rows).** Here the near-degenerate "
          f"blocks are corner DRAM dies whose rectangles are **disjoint**, so no cell can be "
          f"shared: they agree to about 1e-7 K but are never bit-identical. `dram-nop` is the "
          f"clean demonstration — adding NoP separates the top pair from the bottom pair by "
          f"0.03 K while the left-right pair stays degenerate at 6e-7 K, so the surviving "
          f"degeneracy is exactly the surviving symmetry. The appendix previously offered only "
          f"mechanism 1, which is refuted for these rows.")
        A("")
        A(f"Overlap is **necessary but not sufficient**: {c['overlap_untied']} row "
          f"({'`' + [t for t, r in tm['rows'].items() if r['mechanism'] == 'overlap_untied'][0] + '`' if c['overlap_untied'] else 'none'}) "
          f"has overlapping rectangles and is not tied, because each block's own hottest cell "
          f"lies outside the shared region. That asymmetry is what makes the classification "
          f"informative rather than a restatement of adjacency.")
        A("")
        A(f"**Still unproven:** {tm['unproven']}")
    else:
        A(f"No tie diagnostic accompanies this manifest, so the mechanism is UNTESTED here.")
    A("")
    if ex["moves"]:
        A(f"{len(ex['moves'])} subsets report a different argmax label for the two semantics:")
        A("")
        A("| subset | steady argmax | periodic argmax | steady gap (K) | periodic gap (K) | "
          "periodic tie set | relocation? |")
        A("| --- | --- | --- | ---: | ---: | ---: | --- |")
        for mv in ex["moves"]:
            A(f"| `{mv['tag']}` | `{mv['steady']}` | `{mv['periodic']}` | "
              f"{mv['steady_gap_k']:.3e} | {mv['periodic_gap_k']:.3e} | "
              f"{mv['periodic_ties']} | "
              f"{'yes' if mv['resolved'] else 'NO — a tie broken differently'} |")
        A("")
        unresolved = [mv["tag"] for mv in ex["moves"] if not mv["resolved"]]
        A(f"A label change counts as a relocation only if BOTH endpoints are resolvable: the old "
          f"block outside the new tie set, the new block outside the old one, and both gaps "
          f"above one quantum. "
          + (f"{len(unresolved)} of {len(ex['moves'])} fail that test "
             f"({', '.join('`'+t+'`' for t in unresolved)}), so they are not evidence that a "
             f"peak moved." if unresolved else
             f"All {len(ex['moves'])} pass it, which still makes them observations about the "
             f"argmax rather than a demonstrated mechanism."))
    else:
        A("No subset reports a different argmax label for the two semantics.")
    A("")
    A(f"**What this licenses, and what it does not.** The temperature field and its hottest grid "
      f"cell are model results. What the mapping makes unresolvable is the attribution of that "
      f"peak to one named floorplan *block*: at this grid the peak is localised to a "
      f"{g_['cell_w_m']*1e6:.0f} x {g_['cell_h_m']*1e6:.0f} um cell, and several blocks can own "
      f"that cell. It does **not** follow that there is no physical hotspot, nor that the "
      f"equality would survive a finer grid or a different mapping mode." if tm else "")
    A("")
    A("## Scope")
    A("")
    b = ex["bundle"]
    A(f"Evidence grade: **instance-bound, provenance-controlled, single-capture HotSpot evidence "
      f"with producer-attested execution receipts and retained raw outputs.** The staged hashes "
      f"establish integrity within this execution and the canonical hashes bind the physical "
      f"instance forward from the schema-4 run. The raw HotSpot outputs are retained as one "
      f"bundle of {b['members']} files, {b['bytes']/1e6:.1f} MB gzipped from "
      f"{b['uncompressed_bytes']/1e6:.1f} MB, `sha256 {b['sha256'][:16]}…`, deliberately "
      f"**outside** this repository (`{b['path']}` on the run host) — a hash identifies bytes, "
      f"it does not guarantee they still exist on a shared volume. No independent thermal model "
      f"has validated any number, which bounds this to HotSpot-conditional decision "
      f"preservation rather than physical accuracy.")
    A("")
    lo = min(view, key=lambda t: view[t]["uplift_ratio_pct"])
    hi = max(view, key=lambda t: view[t]["uplift_ratio_pct"])
    A(f"Bounded to: this fixed trace; this fixed routing and timing; an additive deposition "
      f"intervention with no temperature-dependent power feedback; the HotSpot model, candidate "
      f"and discretisation; and the **fixed decomposition of {total*1e3:.3f} mJ into "
      f"{', '.join('`'+c+'`' for c in comps)}** — a different assignment of the same total would "
      f"change every row, and that assignment is an artefact of the routed-trace lowering, not a "
      f"measurement. NOT established: that any source alone suffices; that periodic uplift is "
      f"baseline-independent (as a fraction of the steady rise above ambient it spans "
      f"{view[lo]['uplift_ratio_pct']:.2f}% for `{lo}` to {view[hi]['uplift_ratio_pct']:.2f}% "
      f"for `{hi}`, and the {q} K quantum is already "
      f"{100*q/(view[hi]['steady']['peak_k']-v['ambient']):.2f}% of `{hi}`'s rise, so any "
      f"source-identity effect is `{m['summary']['source_identity_effect_on_uplift']}`); "
      f"generalisation to other candidates, models or discretisations; or agreement with any "
      f"independent thermal model.")
    A("")
    g128 = g["pinned"]["grid128_row"]
    A(f"`grid128-max` has not been run as a factorial. Its registered argmax "
      f"(`{g128['steady_block']}` steady / `{g128['periodic_block']}` periodic, "
      f"`{g128['document']}:{g128['line']}`) differs from this run's `{reg['hottest']}`, but "
      f"given how few argmax labels here are resolvable that difference cannot be read as a "
      f"spatial finding. A grid128 factorial would need its own preregistration and is only "
      f"required if the paper claims resolution robustness or a spatial mechanism.")
    A("")
    A(f"Manifest: `{rel(manifest_path)}`")
    return "\n".join(L) + "\n"


def main() -> None:
    manifest_path = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    m = json.loads(manifest_path.read_text())
    try:
        v, gate, ex = build_with_mechanism(m, manifest_path)
        text = render(m, v, gate, ex, manifest_path)
    except Refuse as exc:
        print(f"REFUSING to render: {exc}")
        sys.exit(2)
    if out:
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} ({text.count(chr(10))} lines)")
    else:
        print(text)


if __name__ == "__main__":
    main()
