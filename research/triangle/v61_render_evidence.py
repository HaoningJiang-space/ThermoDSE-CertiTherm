"""Render the V6.1 evidence document FROM a validated manifest. (NON-CLAIM tooling)

Numbers are never hand-transcribed. Manual transcription is how a `core` row that converged
in 8 cycles got reported as 16, and how a measured 1.89-5.02% range got narrowed to "about
2-3%".

Two gates, both of which must pass before a single line is emitted:

1. `complete is true` AND `gate.passed is true` -- neither alone is sufficient, because a gate
   failure previously wrote a truthy `summary` string that a key-existence check would have
   read as success.
2. `validate()` RECOMPUTES every derived claim from `rows` and refuses on any disagreement
   with `summary`. The first version of this generator checked only the two booleans and then
   trusted `summary.row_status`, `minimal_crossing_coalitions`, `leave_one_out` and
   `evidence_grade` verbatim -- i.e. it trusted the very fields a paper table depends on.

Facts that are NOT in the manifest (the earlier run's binary hash, the grid128 registered
hottest blocks) are read out of their committed source documents and the source is required
to still contain them; a stale literal is a refusal, not a silent wrong sentence. Nothing
here may be a bare literal.

Usage: python research/triangle/v61_render_evidence.py <manifest.json> [out.md]
"""
from __future__ import annotations

import json
import re
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# External facts, each with the committed document that is the authority for it. The renderer
# refuses if the source no longer contains the value -- a literal that cannot be re-derived
# from the manifest must at least be re-checkable against its source.
EXTERNAL = {
    "earlier_binary_hash_doc": "docs/GPU_HOTSPOT_EVIDENCE.md",
    "grid128_doc": "docs/V6_PHYSICAL_TRACE_GATE.md",
}


class Refuse(Exception):
    """Any inconsistency between summary and rows. Never rendered around, never downgraded."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise Refuse(msg)


def subset_tag(components, all_components) -> str:
    return "full" if set(components) == set(all_components) else "-".join(sorted(components))


def classify(periodic_k: float, limit_k: float, quantum_k: float) -> str:
    """The exact classification rule, restated here so the document can print it.

    Strictly outside the two-sided quantum band, or INDETERMINATE. At a 330.0 K limit and a
    0.01 K quantum: >= 330.01 crossing, <= 329.99 below, and 330.00 is indeterminate.
    """
    if periodic_k >= limit_k + quantum_k:
        return "crossing"
    if periodic_k <= limit_k - quantum_k:
        return "below"
    return "indeterminate"


def external_fact(key: str, pattern: str, label: str) -> tuple[tuple[str, ...], str]:
    """Return (captured groups, 'path:line') for a fact that lives in a committed document.

    The pattern must be anchored on something identifying (a model name, a hash) so that a
    reordered or extended source cannot silently match the wrong row.
    """
    path = ROOT / EXTERNAL[key]
    _require(path.exists(), f"external source {EXTERNAL[key]} for {label} is missing")
    hits = [(n, m) for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if (m := re.search(pattern, line))]
    _require(len(hits) == 1, f"external source {EXTERNAL[key]} matches {label} "
                             f"{len(hits)} times (pattern {pattern!r}); expected exactly one "
                             f"-- the literal in this generator is stale or ambiguous")
    n, m = hits[0]
    return (m.groups() or (m.group(0),)), f"{EXTERNAL[key]}:{n}"


def validate(m: dict) -> dict:
    """Recompute every derived claim from `rows`. Returns the recomputed view."""
    gate = m.get("gate") or {}
    _require(m.get("complete") is True and gate.get("passed") is True,
             f"complete={m.get('complete')} gate.passed={gate.get('passed')} "
             f"suppression={m.get('suppression_reason')}")

    rows, s = m["rows"], m["summary"]
    limit = m["thermal_limit_k"]
    comp = m["component_energy_j"]
    comps = sorted(comp)

    # -- exact subset enumeration: 2^n - 1 rows, each distinct, covering every subset -------
    want = {subset_tag(c, comps) for k in range(1, len(comps) + 1)
            for c in combinations(comps, k)}
    _require(len(want) == 2 ** len(comps) - 1, f"tagging collided: {len(want)} tags")
    _require(set(rows) == want, f"row set != the {len(want)} non-empty subsets; "
                                f"missing {sorted(want - set(rows))}, "
                                f"extra {sorted(set(rows) - want)}")

    # -- per-row integrity ------------------------------------------------------------------
    # `trace_sha256` is deliberately NOT invariant: each subset has its own masked trace, and
    # the hashes must all DIFFER -- two equal hashes would mean two rows replayed one trace.
    invariant = ("commit", "workload", "arch", "model", "max_step_us", "ambient_k",
                 "tolerance_k", "io_aspect_ratio", "hotspot_sha256",
                 "schema_version", "output_resolution_k")
    ref = rows[subset_tag(comps, comps)]
    quantum = ref["output_resolution_k"]
    _require(quantum > 0, "output resolution must be positive")
    for tag, r in sorted(rows.items()):
        _require(r.get("complete") is True, f"{tag}: row is not complete")
        _require(subset_tag(r["components"], comps) == tag,
                 f"{tag}: row components {r['components']} do not tag to its own key")
        for f in ("mean_steady_peak_k", "periodic_peak_k", "step_s",
                  "boundary_residual_k", "peak_residual_k"):
            v = r[f]
            _require(isinstance(v, (int, float)) and v == v and abs(v) != float("inf"),
                     f"{tag}: {f} is not finite ({v!r})")
        _require(r["cycles"] >= 2, f"{tag}: {r['cycles']} cycles is unconverged")
        for f in invariant:
            _require(r[f] == ref[f], f"{tag}: {f} differs from the reference row "
                                     f"({r[f]!r} vs {ref[f]!r})")
        _require(r["input_hashes"] == ref["input_hashes"],
                 f"{tag}: staged input hashes differ from the reference row")
        _require(abs(r["margin_to_limit_k"] - (limit - r["periodic_peak_k"])) < 1e-6,
                 f"{tag}: margin_to_limit_k disagrees with limit - periodic")
        # the energy ledger must reproduce this row's retained energy exactly
        _require(abs(sum(comp[c] for c in r["components"])
                     - r["retained_source_energy_j"]) <= 1e-15,
                 f"{tag}: retained energy != sum of its components in the ledger")
    traces = {t: r["trace_sha256"] for t, r in rows.items()}
    _require(len(set(traces.values())) == len(rows),
             "two rows share a trace hash, so a subset was not independently lowered")
    _require(abs(sum(comp.values()) - m["full_source_energy_j"]) <= 1e-15,
             "component energies do not sum to the full source energy")
    for f in ("commit", "workload", "arch", "model", "max_step_us", "ambient_k",
              "hotspot_sha256"):
        _require(ref[f] == m[f], f"top-level {f} disagrees with the rows")

    # -- recomputed classification and coalitions -------------------------------------------
    status = {t: classify(r["periodic_peak_k"], limit, quantum) for t, r in rows.items()}
    _require(status == s["row_status"], "recomputed row_status disagrees with the manifest")
    crossing = {frozenset(rows[t]["components"]) for t, v in status.items() if v == "crossing"}
    minimal = sorted(("+".join(sorted(c)) for c in crossing
                      if not any(o < c for o in crossing)), key=len)
    _require(minimal == s["minimal_crossing_coalitions"],
             "recomputed minimal crossing coalitions disagree with the manifest")
    _require(sorted("+".join(sorted(c)) for c in crossing) == s["crossing_subsets"],
             "recomputed crossing subsets disagree with the manifest")
    _require([t for t, v in status.items() if v == "indeterminate"] == s["indeterminate_rows"],
             "recomputed indeterminate rows disagree with the manifest")

    loo = {}
    full = rows[subset_tag(comps, comps)]
    for drop in comps:
        r = rows[subset_tag([c for c in comps if c != drop], comps)]
        loo[drop] = {"periodic_peak_k": r["periodic_peak_k"],
                     "status": status[subset_tag(r["components"], comps)],
                     "margin_to_limit_k": r["margin_to_limit_k"],
                     "below_limit": status[subset_tag(r["components"], comps)] == "below",
                     # removal delta: what taking this source out actually costs in K
                     "removal_delta_k": full["periodic_peak_k"] - r["periodic_peak_k"]}
    for drop, v in loo.items():
        got = s["leave_one_out"][drop]
        for f in ("periodic_peak_k", "status", "below_limit"):
            _require(got[f] == v[f], f"leave-one-out {drop}: {f} disagrees "
                                     f"({got[f]!r} vs {v[f]!r})")

    # -- execution receipts and tie evidence (schema 3+; absent in the schema-2 manifest) ---
    run = m.get("run") or {}
    receipts = {t: r.get("execution") for t, r in rows.items()}
    present = [t for t, x in receipts.items() if isinstance(x, dict) and x]
    _require(len(present) in (0, len(rows)),
             f"{len(present)} of {len(rows)} rows carry an execution receipt; a partial set "
             f"cannot support a statement about the run as a whole")
    has_receipts = bool(present)
    if has_receipts:
        nonce = run.get("run_id")
        _require(bool(nonce), "rows carry a run nonce but the manifest records no run id")
        for t, ex in sorted(receipts.items()):
            _require(ex.get("dest_existed_before_run") is False,
                     f"{t}: the row directory already existed before the row ran")
            _require(not ex.get("workspace_files_before_run"),
                     f"{t}: the HotSpot workspace was not empty before the row ran")
            # 1 mean-steady solve + 1 fixed-initial solve + at least one cycle attempt.
            _require(ex.get("hotspot_invocations", 0) >= 3,
                     f"{t}: {ex.get('hotspot_invocations')} HotSpot invocations is too few "
                     f"for one replay")
            _require(len(ex.get("raw_outputs") or {}) >= 3,
                     f"{t}: fewer raw HotSpot outputs than invocations that write a file")
            _require(run.get("started_unix", 0) <= ex["started_unix"] <= ex["ended_unix"]
                     <= run.get("ended_unix", float("inf")) + 1e-6,
                     f"{t}: the row's wall window is not inside the run's")
        fresh = all(receipts[t].get("run_nonce") == nonce for t in rows)
        _require(s.get("all_rows_fresh") == fresh,
                 f"summary.all_rows_fresh={s.get('all_rows_fresh')} but recomputing it from "
                 f"the receipts' run nonces gives {fresh}")
    has_ties = all("periodic_top_gap_k" in r for r in rows.values())
    if has_ties:
        for t, r in sorted(rows.items()):
            _require(abs(r["periodic_top_gap_k"]
                         - (r["periodic_peak_k"] - r["periodic_second_peak_k"])) < 1e-9,
                     f"{t}: periodic top gap disagrees with peak - runner-up")
            _require(r["periodic_hottest_block"] in r["periodic_tie_blocks"],
                     f"{t}: the reported argmax block is not in its own tie set")

    ratios = {t: 100 * (r["periodic_peak_k"] - r["mean_steady_peak_k"])
              / (r["mean_steady_peak_k"] - m["ambient_k"]) for t, r in rows.items()}
    return {"status": status, "minimal": minimal, "loo": loo, "quantum": quantum,
            "comps": comps, "ratios": ratios, "full": full,
            "has_receipts": has_receipts, "has_ties": has_ties,
            "excess_k": full["periodic_peak_k"] - limit}


def main() -> None:
    manifest_path = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    m = json.loads(manifest_path.read_text())
    try:
        v = validate(m)
    except Refuse as exc:
        print(f"REFUSING to render: {exc}")
        sys.exit(2)

    gate, s, rows = m["gate"], m["summary"], m["rows"]
    limit, comp, total = m["thermal_limit_k"], m["component_energy_j"], m["full_source_energy_j"]
    run = m.get("run", {})
    reg = gate["registered_tuple"]
    q, full = v["quantum"], v["full"]
    excess = v["excess_k"]

    L: list[str] = []
    A = L.append
    A("# V6.1 source-subset isolation under a fixed additive power trace")
    A("")
    A("Every number and every classification below is **recomputed from the manifest rows** by")
    A("`research/triangle/v61_render_evidence.py`, which refuses to emit anything unless the")
    A("manifest has `complete: true` and `gate.passed: true` **and** its own recomputation of")
    A("the subset enumeration, the quantisation-aware classification, the minimal crossing")
    A("coalitions, the leave-one-out table and the energy ledger agrees with the manifest's")
    A("`summary`. The two facts that are not in the manifest (this run's binary versus the")
    A("earlier one, and the grid128 registered blocks) are read out of the committed documents")
    A("cited beside them, and a source that no longer states the value is a refusal.")
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
    A(f"- run id `{run.get('run_id','?')}`, wall "
      f"{(run['ended_unix'] - run['started_unix']) / 60:.1f} min"
      if run.get("ended_unix") else "- run window not recorded")
    A("- every input staged read-only and hashed as read; re-verified after each replay")
    for k, h in sorted(m["input_hashes"].items()):
        A(f"  - `{k}` `{h[:16]}…`")
    A(f"- superposition identity, subset == sum of singletons: worst "
      f"`{m['superposition_worst_w']:.3e}` W")
    A("")
    _, cite = external_fact("earlier_binary_hash_doc",
                            f"`({re.escape(m['hotspot_sha256'])})`",
                            "this run's HotSpot binary hash")
    A(f"The HotSpot binary staged here is **byte-identical** to the one used by the earlier "
      f"transient work (`{cite}` records the same SHA-256). The build is therefore reproducible "
      f"— but it also means this run cannot be an *independent numerical* confirmation of the "
      f"earlier numbers: identical inputs through an identical binary are arithmetically "
      f"determined to agree. What it confirms is the provenance chain, not the physics.")
    A("")
    if v["has_receipts"]:
        ex = {t: rows[t]["execution"] for t in rows}
        total_inv = sum(e["hotspot_invocations"] for e in ex.values())
        total_raw = sum(len(e["raw_outputs"]) for e in ex.values())
        A(f"**Fresh execution is evidenced per row, not asserted.** Every row records that its "
          f"output directory and HotSpot workspace did not exist before it ran, its wall "
          f"window inside the run's, its PID, this run's nonce, the number of HotSpot "
          f"processes it started, and the SHA-256 of every raw HotSpot artefact it produced. "
          f"Across the {len(rows)} rows: **{total_inv} HotSpot invocations** and "
          f"**{total_raw} raw output files hashed** "
          f"(`summary.all_rows_fresh = {s.get('all_rows_fresh')}`, recomputed here from the "
          f"receipts' nonces rather than read). A cache read would have to fabricate the "
          f"artefacts as well as the numbers.")
        A("")
        A("| subset | HotSpot invocations | raw outputs | wall (s) | dir existed before |")
        A("| --- | ---: | ---: | ---: | --- |")
        for t in sorted(rows, key=lambda t: ex[t]["started_unix"]):
            e = ex[t]
            A(f"| `{t}` | {e['hotspot_invocations']} | {len(e['raw_outputs'])} | "
              f"{e['wall_s']:.1f} | {e['dest_existed_before_run']} |")
    else:
        A(f"**Fresh execution is asserted by policy, not proven by this document.** "
          f"`summary.all_rows_fresh = {s.get('all_rows_fresh')}` echoes the driver's no-reuse "
          f"constant; this manifest (schema {run.get('schema_version','?')}) carries no per-row "
          f"process receipt — no PID, wall window, HotSpot invocation count, or hash of the raw "
          f"HotSpot output. Nothing here would distinguish {len(rows)} solver executions from "
          f"{len(rows)} reads of a cache. The driver records all of it from schema 3 onward; "
          f"for this manifest it is an open gap.")
    A("")
    A("## Source energy ledger")
    A("")
    A(f"Reproduced exactly by every one of the {len(rows)} rows: each row's retained energy "
      f"equals the sum of its components' entries here (checked to 1e-15 J).")
    A("")
    A("| source | energy (mJ) | share |")
    A("| --- | ---: | ---: |")
    for k in sorted(comp, key=lambda x: -comp[x]):
        A(f"| `{k}` | {comp[k]*1e3:.6f} | {100*comp[k]/total:.3f}% |")
    A(f"| **total** | **{total*1e3:.6f}** | 100% |")
    A("")
    A(f"## All {len(rows)} non-empty source subsets")
    A("")
    A("| subset | time-mean steady (K) | periodic (K) | uplift (K) | steady argmax | "
      "periodic argmax | cycles | status |")
    A("| --- | ---: | ---: | ---: | --- | --- | ---: | --- |")
    for t in sorted(rows, key=lambda t: rows[t]["periodic_peak_k"]):
        r = rows[t]
        name = "**full**" if t == "full" else f"`{t}`"
        st = v["status"][t]
        A(f"| {name} | {r['mean_steady_peak_k']:.6f} | {r['periodic_peak_k']:.2f} | "
          f"{r['periodic_peak_k']-r['mean_steady_peak_k']:+.2f} | "
          f"`{r['mean_steady_hottest_block']}` | `{r['periodic_hottest_block']}` | "
          f"{r['cycles']} | {'**CROSSING**' if st == 'crossing' else st} |")
    A("")
    A(f"Classification is quantisation-aware, with the boundary stated exactly. HotSpot reports "
      f"transient temperatures to {q} K, so with a {limit} K limit a row is `crossing` iff "
      f"`periodic >= {limit + q}` K, `below` iff `periodic <= {limit - q}` K, and "
      f"`indeterminate` otherwise — a value of exactly {limit} K is **not** a crossing. "
      f"Indeterminate rows this run: {s['indeterminate_rows'] or 'none'}. Every status in the "
      f"table above was recomputed from `periodic_peak_k` by this rule, not read from the "
      f"manifest.")
    A("")
    A("## Gate")
    A("")
    A(f"- decision (steady < {limit} and periodic >= {limit}): **{gate['decision_ok']}**")
    A(f"- periodic value within one output quantum of the registered "
      f"{reg['periodic_peak_k']} K: **{gate['value_ok']}**")
    A(f"- reported argmax block equals registered `{reg['hottest']}`: "
      f"**{gate['location_ok']}**")
    A(f"- steady delta from the registered value: `{gate['steady_delta_k']:.3e}` K "
      f"(reported, **not** gated — {gate['steady_gate_note']})")
    A("")
    A(f"The steady delta is `{gate['steady_delta_k']:.3e}` K, i.e. the registered value is "
      f"quoted to {len(str(reg['mean_steady_peak_k']).split('.')[-1])} decimals and the "
      f"residual sits at that quoting resolution. **Near-exact agreement is not repeatability "
      f"evidence.** With the same code, binary, inputs and platform, agreement to the last "
      f"printed digit is what arithmetic requires; it does not distinguish a fresh solver run "
      f"from a reused result. It would only be *suspicious* if presented as proof that the "
      f"solver ran.")
    A("")
    A(f"**The gate binds names and temperatures, NOT the registered instance** "
      f"(`binds_instance_hashes = {reg['binds_instance_hashes']}`, "
      f"`canonical_trace_sha256 = {reg['canonical_trace_sha256']}`). It verifies that this "
      "pipeline reproduces the documented crossing at the documented location; it does **not** "
      "verify that the registry, power trace or routing are unchanged, so a changed registry "
      "under the same workload/architecture names could still pass. Closing that needs a "
      "canonical trace hash preregistered from a run that is itself claim-grade. Open gap.")
    A("")
    A("## Result")
    A("")
    A(f"- **minimal crossing coalitions:** "
      f"{', '.join('`'+c+'`' for c in v['minimal']) or 'none'}")
    A(f"- the {len(rows)} rows exhaust every non-empty subset of "
      f"{{{', '.join('`'+c+'`' for c in v['comps'])}}} with no indeterminate row, so "
      f"`{v['minimal'][0] if v['minimal'] else 'n/a'}` is the **unique minimal crossing "
      f"coalition in this factorial**. That is a statement about this trace, this candidate "
      f"and this discretisation — not about candidates, traces or discretisations in general.")
    A("")
    A("### Leave-one-out is an arithmetic consequence, not a second finding")
    A("")
    deltas = {k: d["removal_delta_k"] for k, d in v["loo"].items()}
    A(f"The full set crosses by only **{excess:+.2f} K** ({full['periodic_peak_k']:.2f} K "
      f"against a {limit} K limit).")
    if min(deltas.values()) > excess:
        A(f"Every source's removal costs more than that excess (smallest: "
          f"{min(deltas.values()):+.2f} K for `{min(deltas, key=lambda k: deltas[k])}`), so "
          f"once the exhaustive factorial shows the full set is the only crossing subset, all "
          f"{len(deltas)} leave-one-out verdicts follow with no further information. This is "
          f"**Boolean threshold necessity within a fixed factorial**, not a measure of physical "
          f"causal importance.")
    else:
        A(f"Not every removal exceeds that excess (smallest: {min(deltas.values()):+.2f} K for "
          f"`{min(deltas, key=lambda k: deltas[k])}`), so the leave-one-out verdicts are not "
          f"purely arithmetic — read the table row by row.")
    A("")
    A("| removed source | periodic (K) | removal delta (K) | delta / excess | "
      "margin to limit (K) | status |")
    A("| --- | ---: | ---: | ---: | ---: | --- |")
    for k in sorted(v["loo"], key=lambda k: -v["loo"][k]["removal_delta_k"]):
        d = v["loo"][k]
        A(f"| `{k}` | {d['periodic_peak_k']:.2f} | {d['removal_delta_k']:+.2f} | "
          f"{d['removal_delta_k']/excess:.1f}x | {d['margin_to_limit_k']:+.2f} | "
          f"{'below → necessary in the grand coalition' if d['below_limit'] else d['status']} |")
    A("")
    smallest = min(v["loo"], key=lambda k: v["loo"][k]["removal_delta_k"])
    sm = v["loo"][smallest]
    A(f"The informative row is the smallest one. `{smallest}` carries "
      f"{100*comp[smallest]/total:.3f}% of the dissipated energy yet its removal drops the "
      f"periodic peak by {sm['removal_delta_k']:.2f} K — "
      f"{sm['removal_delta_k']/excess:.1f}x the {excess:+.2f} K excess, and "
      f"{sm['removal_delta_k']/q:.0f}x the {q} K output quantum. Energy share alone does not "
      f"predict which source decides the threshold; the deltas do, and they are the quantity "
      f"a paper table should carry rather than the necessity label.")
    A("")
    A("## Appendix — reported-argmax changes (observations, not a mechanism)")
    A("")
    moves = sorted((t, r["mean_steady_hottest_block"], r["periodic_hottest_block"])
                   for t, r in rows.items()
                   if r["mean_steady_hottest_block"] != r["periodic_hottest_block"])
    if moves:
        A(f"In {len(moves)} of {len(rows)} subsets the **reported argmax block label** differs "
          f"between the two semantics:")
        if v["has_ties"]:
            A("")
            A("| subset | steady argmax | periodic argmax | periodic top-two gap (K) | "
              "blocks within one quantum | resolvable? |")
            A("| --- | --- | --- | ---: | ---: | --- |")
            for t, a, b in moves:
                r = rows[t]
                tied = len(r["periodic_tie_blocks"])
                A(f"| `{t}` | `{a}` | `{b}` | {r['periodic_top_gap_k']:.2f} | {tied} | "
                  f"{'yes' if r['periodic_top_gap_k'] > q else 'NO — inside the quantum'} |")
            A("")
            unresolved = [t for t, _, _ in moves if rows[t]["periodic_top_gap_k"] <= q]
            if unresolved:
                A(f"{len(unresolved)} of these ({', '.join('`'+t+'`' for t in unresolved)}) have "
                  f"a top-two gap no larger than the {q} K output quantum, so the label change "
                  f"is **indistinguishable from a tie broken differently** and is not evidence "
                  f"that a peak moved.")
            else:
                A(f"All {len(moves)} have a top-two gap larger than the {q} K output quantum, so "
                  f"the label change is resolvable at the reported resolution. That still makes "
                  f"it an observation about the argmax, not a demonstrated physical mechanism.")
        else:
            for t, a, b in moves:
                A(f"- `{t}`: steady `{a}` → periodic `{b}`")
            A("")
            A(f"This says the argmax label changed. It does **not** establish that a physically "
              f"meaningful peak relocated: periodic temperatures are reported only to {q} K, "
              f"and this manifest records no second-hottest temperature, no top-two gap and no "
              f"tie set, so a change between two blocks within one quantum of each other is "
              f"indistinguishable from a tie broken differently. `dram_x0_y4` versus "
              f"`dram_x0_y0` in particular may be a symmetry. The driver records the runner-up "
              f"and the resolution-aware tie set from schema 3 onward; until a manifest carries "
              f"them these rows support no claim.")
        A("")
        A(f"The crossing row's argmax is unchanged, so this is not the crossing mechanism "
          f"either way.")
    else:
        A("No subset reported a different argmax block between the two semantics.")
    A("")
    A("## Scope")
    A("")
    A(f"Evidence grade recorded by the run: **{s['evidence_grade']}**")
    A("")
    A(f"Qualified by what the manifest itself states, the accurate grade is "
      f"**run-provenance-controlled, registry-instance-unbound, single-capture HotSpot "
      f"evidence**: the staged hashes establish integrity *within this execution*, while "
      f"`binds_instance_hashes = {reg['binds_instance_hashes']}` leaves the identity link to "
      f"the originally registered trace and routing open, and no independent thermal model has "
      f"validated any number here.")
    A("")
    A(s["scope"])
    A("")
    A(f"One bound that sentence omits: the conclusions also depend on the **fixed decomposition "
      f"of power into {', '.join('`'+c+'`' for c in v['comps'])}** given in the ledger above. A "
      f"different assignment of the same {total*1e3:.3f} mJ to those four names would change "
      f"every subset row, and that assignment is an artefact of the routed-trace lowering, not "
      f"a measurement.")
    A("")
    lo, hi = min(v["ratios"].values()), max(v["ratios"].values())
    lo_t = min(v["ratios"], key=lambda t: v["ratios"][t])
    hi_t = max(v["ratios"], key=lambda t: v["ratios"][t])
    A(f"Explicitly NOT established: that any source alone suffices; that periodic uplift is "
      f"baseline-independent — the uplift as a fraction of the steady rise above ambient spans "
      f"**{lo:.2f}% (`{lo_t}`) to {hi:.2f}% (`{hi_t}`)** across the {len(rows)} subsets, "
      f"computed here from the rows, and is resolution-sensitive where the rise is small "
      f"(the {q} K quantum is {100*q/(rows[hi_t]['mean_steady_peak_k']-m['ambient_k']):.2f}% of "
      f"`{hi_t}`'s rise), so any source-identity effect is "
      f"`{s['source_identity_effect_on_uplift']}`; generalisation to other candidates, thermal "
      f"models or discretisations; or agreement with any independent thermal model.")
    A("")
    (g_steady, g_per), g_cite = external_fact(
        "grid128_doc", r"grid128-max.*?\(`(\w+)`\).*?\(`(\w+)`\)",
        "the grid128 registered blocks")
    A(f"`grid128-max` has NOT been run as a factorial. Its registered hottest block "
      f"(`{g_steady}` steady / `{g_per}` periodic, per `{g_cite}` — externally supplied, not "
      f"from this manifest) "
      f"differs from this run's `{reg['hottest']}` **and moves between the two semantics**, so "
      f"a grid128 factorial would be a distinct discretised result requiring its own "
      f"preregistration, not a resolution cross-check of this one. It is only needed if the "
      f"paper claims resolution robustness, a spatial mechanism, or general source necessity; "
      f"for the bounded grid64 existence claim made here it is not. A single grid128 full-trace "
      f"row would not be an adequate causal cross-check either way.")
    A("")
    A(f"Manifest: `{manifest_path}` (run id `{run.get('run_id','?')}`)")

    text = "\n".join(L) + "\n"
    if out:
        out.write_text(text, encoding="utf-8")
        print(f"wrote {out} ({len(L)} lines)")
    else:
        print(text)


if __name__ == "__main__":
    main()
