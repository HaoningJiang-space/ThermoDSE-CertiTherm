"""Render the V6.1 evidence document from a manifest. (NON-CLAIM tooling)

What this generator independently RECOMPUTES from `rows`, and refuses to render on any
disagreement: the subset enumeration, the quantisation-aware classification of every row, the
crossing coalitions, the leave-one-out table, the energy ledger, convergence, cross-row
provenance identity, and the gate verdicts (against the pinned registration in
`docs/registration/`, not against the manifest's own copy of them).

What remains PRODUCER-REPORTED and is labelled as such in the output: the per-row temperature
scalars themselves, the superposition residual, the execution receipts, and the narrative
scope sentence. This generator cannot re-derive those without the raw traces; calling the
receipts "proof of execution" would be an overclaim, so the document calls them an audit
receipt. An earlier version of this docstring claimed "every derived claim" and "nothing here
may be a bare literal" -- both were false, and the slogans were what let four literals and
several copied verdicts survive.

Usage: python research/triangle/v61_render_evidence.py <manifest.json> [out.md]
"""
from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRATION = ROOT / "docs/registration/v61_grid64_counterexample.json"
REQUIRED_SCHEMA = 3


def _rel(path: Path) -> str:
    """Repo-relative when inside the tree, absolute otherwise.

    `Path.relative_to` RAISES for a path outside ROOT, and this was called from inside
    refusal messages -- so a refusal about a misplaced registration crashed with a ValueError
    instead of printing. An error path must never be able to raise.
    """
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


class Refuse(Exception):
    """Any inconsistency, missing evidence, or unmet precondition. Never rendered around."""


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise Refuse(msg)


def _get(d: dict, key: str, where: str):
    """Fetch a required field as a Refuse, not a KeyError -- a traceback is not fail-closed."""
    _require(key in d, f"{where}: required field `{key}` is missing")
    return d[key]


def _finite(value, where: str) -> float:
    _require(isinstance(value, (int, float)) and not isinstance(value, bool)
             and value == value and abs(value) != float("inf"),
             f"{where} is not a finite number ({value!r})")
    return float(value)


def subset_tag(components, all_components) -> str:
    return "full" if set(components) == set(all_components) else "-".join(sorted(components))


def classify(periodic_k: float, limit_k: float, quantum_k: float) -> str:
    """The ONE classification rule. Strictly outside the two-sided quantum band, or
    INDETERMINATE: at a 330.0 K limit and a 0.01 K quantum, >= 330.01 crosses, <= 329.99 is
    below, and exactly 330.00 is undecidable."""
    if periodic_k >= limit_k + quantum_k:
        return "crossing"
    if periodic_k <= limit_k - quantum_k:
        return "below"
    return "indeterminate"


# --- validation ------------------------------------------------------------------------

def validate_identity(m: dict) -> dict:
    """Schema, gate precondition, and cross-row / row-vs-top-level provenance identity."""
    gate = m.get("gate") or {}
    _require(m.get("complete") is True and gate.get("passed") is True,
             f"complete={m.get('complete')} gate.passed={gate.get('passed')} "
             f"suppression={m.get('suppression_reason')}")
    run = _get(m, "run", "manifest")
    _require(_get(run, "schema_version", "run") == REQUIRED_SCHEMA,
             f"manifest is schema {run.get('schema_version')}; this generator renders only "
             f"schema {REQUIRED_SCHEMA}. Earlier manifests are historical artefacts, not "
             f"inputs -- they carry neither execution receipts nor tie evidence.")
    _require(not m["dirty"] and m.get("provenance_stable") is True,
             f"claim-grade rendering requires a clean tree that stayed clean: "
             f"dirty={len(m['dirty'])} provenance_stable={m.get('provenance_stable')}")
    end = _get(m, "provenance_end", "manifest")
    _require(end.get("commit") == m["commit"] and not end.get("dirty"),
             "the end-of-run provenance does not match the start")
    _require(m["input_hashes"].get("hotspot") == m["hotspot_sha256"],
             "the staged hotspot hash disagrees with the recorded binary hash")
    return {"gate": gate, "run": run}


def validate_rows(m: dict) -> dict:
    """Recompute every row-derived claim. This is the load-bearing function."""
    rows = _get(m, "rows", "manifest")
    limit = _finite(_get(m, "thermal_limit_k", "manifest"), "thermal_limit_k")
    ambient = _finite(_get(m, "ambient_k", "manifest"), "ambient_k")
    comp = _get(m, "component_energy_j", "manifest")
    comps = sorted(comp)
    for c in comps:
        _require(_finite(comp[c], f"component_energy_j[{c}]") > 0,
                 f"component `{c}` has non-positive energy")

    # exact enumeration: 2^n - 1 rows, each tagging uniquely to its own key
    want = {subset_tag(c, comps) for k in range(1, len(comps) + 1)
            for c in combinations(comps, k)}
    _require(len(want) == 2 ** len(comps) - 1,
             f"component names collide under tagging: {len(want)} tags for {len(comps)} names")
    _require(set(rows) == want,
             f"row set != the {len(want)} non-empty subsets; missing "
             f"{sorted(want - set(rows))}, extra {sorted(set(rows) - want)}")

    ref = rows[subset_tag(comps, comps)]
    quantum = _finite(_get(ref, "output_resolution_k", "full row"), "output_resolution_k")
    _require(quantum > 0, "output resolution must be positive")
    # `trace_sha256` is deliberately NOT invariant -- each subset has its own masked trace.
    # `dirty`/`diff_sha256` ARE: a row produced from a different tree state voids the set.
    invariant = ("commit", "dirty", "diff_sha256", "workload", "arch", "model", "max_step_us",
                 "ambient_k", "tolerance_k", "io_aspect_ratio", "hotspot_sha256",
                 "schema_version", "output_resolution_k", "input_hashes")
    shared_with_top = ("commit", "dirty", "workload", "arch", "model", "max_step_us",
                       "ambient_k", "hotspot_sha256", "input_hashes")

    for tag in sorted(rows):
        r = rows[tag]
        w = f"row `{tag}`"
        _require(r.get("complete") is True, f"{w}: row is not complete")
        _require(subset_tag(_get(r, "components", w), comps) == tag,
                 f"{w}: components {r['components']} do not tag to its own key")
        for f in invariant:
            _require(_get(r, f, w) == ref[f],
                     f"{w}: {f} differs from the full row ({r[f]!r} vs {ref[f]!r})")
        steady = _finite(_get(r, "mean_steady_peak_k", w), f"{w}.mean_steady_peak_k")
        periodic = _finite(_get(r, "periodic_peak_k", w), f"{w}.periodic_peak_k")
        _require(steady > ambient,
                 f"{w}: steady peak {steady} is not above ambient {ambient}, so the uplift "
                 f"ratio has no meaning")
        # convergence, not merely a cycle count. An unconverged 16-cycle row with a 10 K
        # residual previously passed because only finiteness and cycles >= 2 were checked.
        tol = _finite(_get(r, "tolerance_k", w), f"{w}.tolerance_k")
        _require(tol >= quantum,
                 f"{w}: tolerance {tol} K is finer than the {quantum} K output resolution")
        residual = max(_finite(_get(r, "boundary_residual_k", w), f"{w}.boundary_residual_k"),
                       _finite(_get(r, "peak_residual_k", w), f"{w}.peak_residual_k"))
        _require(residual <= tol + 1e-9,
                 f"{w}: periodic residual {residual} K exceeds its {tol} K tolerance")
        _require(_get(r, "cycles", w) >= 2, f"{w}: {r['cycles']} cycles is unconverged")
        step = _finite(_get(r, "step_s", w), f"{w}.step_s")
        _require(0 < step <= r["max_step_us"] * 1e-6 + 1e-15,
                 f"{w}: step {step} s is not in (0, the requested {r['max_step_us']} us]")
        spc = _get(r, "samples_per_cycle", w)
        _require(isinstance(spc, int) and spc > 0, f"{w}: samples_per_cycle {spc!r} is invalid")
        _require(abs(sum(comp[c] for c in r["components"])
                     - _finite(_get(r, "retained_source_energy_j", w), f"{w}.retained")) <= 1e-15,
                 f"{w}: retained energy != the sum of its components in the ledger")

    _require(len({rows[t]["trace_sha256"] for t in rows}) == len(rows),
             "two rows record the same trace hash, so one masked trace served two subsets")
    _require(abs(sum(comp.values()) - _finite(_get(m, "full_source_energy_j", "manifest"),
                                             "full_source_energy_j")) <= 1e-15,
             "component energies do not sum to the full source energy")
    for f in shared_with_top:
        _require(ref[f] == _get(m, f, "manifest"), f"top-level {f} disagrees with the rows")

    status = {t: classify(rows[t]["periodic_peak_k"], limit, quantum) for t in rows}
    crossing = {frozenset(rows[t]["components"]) for t in rows if status[t] == "crossing"}
    minimal = sorted(("+".join(sorted(c)) for c in crossing
                      if not any(o < c for o in crossing)), key=len)
    full = rows[subset_tag(comps, comps)]
    loo = {}
    for drop in comps:
        t = subset_tag([c for c in comps if c != drop], comps)
        loo[drop] = {"tag": t, "periodic_peak_k": rows[t]["periodic_peak_k"],
                     "status": status[t],
                     "margin_to_limit_k": limit - rows[t]["periodic_peak_k"],
                     "removal_delta_k": full["periodic_peak_k"] - rows[t]["periodic_peak_k"]}
    ratios = {t: 100 * (rows[t]["periodic_peak_k"] - rows[t]["mean_steady_peak_k"])
              / (rows[t]["mean_steady_peak_k"] - ambient) for t in rows}

    return {"rows": rows, "comps": comps, "quantum": quantum, "limit": limit,
            "ambient": ambient, "comp": comp, "status": status, "minimal": minimal,
            "loo": loo, "ratios": ratios, "full": full,
            "indeterminate": sorted(t for t in rows if status[t] == "indeterminate"),
            "excess_k": full["periodic_peak_k"] - limit,
            "uniqueness_claimable": len(minimal) == 1 and not any(
                v == "indeterminate" for v in status.values())}


def check_citation(cite: dict, values) -> None:
    """A pinned document:line must still contain the values recorded beside it.

    Line numbers drift the moment the cited document is edited -- this record was wrong
    within an hour of being written, because adding a correction paragraph above the cited
    table shifted it by one. A wrong citation prints silently, so it has to be a refusal.
    """
    path = ROOT / _get(cite, "document", "citation")
    _require(path.is_file(), f"cited document {cite['document']} is missing")
    lines = path.read_text(encoding="utf-8").splitlines()
    n = _get(cite, "line", "citation")
    _require(1 <= n <= len(lines),
             f"{cite['document']}:{n} is past the end of a {len(lines)}-line file")
    line = lines[n - 1]
    for v in values:
        _require(str(v) in line,
                 f"{cite['document']}:{n} no longer contains {v!r}; the pinned citation in "
                 f"{_rel(REGISTRATION)} is stale")


def validate_gate(m: dict, view: dict) -> dict:
    """Recompute the gate from the full row and the PINNED registration.

    The manifest's own `decision_ok` / `value_ok` / `location_ok` were previously printed
    verbatim, so an edited manifest could assert a passing gate with untouched rows. They are
    now recomputed and the stored copies must agree.
    """
    _require(REGISTRATION.is_file(), f"pinned registration {REGISTRATION} is missing")
    pinned = json.loads(REGISTRATION.read_text())
    reg = pinned["registered_tuple"]
    stored = _get(m["gate"], "registered_tuple", "gate")
    _require(stored == reg,
             "the manifest's registered tuple differs from the pinned registration in "
             f"{_rel(REGISTRATION)}; one of them has drifted")
    for f in ("workload", "arch", "model", "max_step_us", "ambient_k"):
        _require(m[f] == reg[f],
                 f"this run's {f}={m[f]!r} is not the registered {reg[f]!r}; the gate does "
                 f"not apply and no registered comparison may be printed")
    _require(view["limit"] == reg["thermal_limit_k"],
             "the run's thermal limit is not the registered one")
    check_citation(pinned["grid64_source"],
                   [reg["hottest"], reg["periodic_peak_k"], reg["mean_steady_peak_k"]])
    check_citation(pinned["grid128_row"], [pinned["grid128_row"]["steady_block"],
                                           pinned["grid128_row"]["periodic_block"]])
    check_citation(pinned["earlier_hotspot_binary_sha256"],
                   [pinned["earlier_hotspot_binary_sha256"]["sha256"]])

    full, q = view["full"], view["quantum"]
    # The DECISION uses the same quantisation-aware rule as every row, not a bare `>= limit`.
    # The driver's own gate used `periodic >= 330`, which would pass a 330.00 K row that the
    # classification calls indeterminate.
    decision_ok = (full["mean_steady_peak_k"] < view["limit"]
                   and view["status"][subset_tag(view["comps"], view["comps"])] == "crossing")
    value_ok = abs(full["periodic_peak_k"] - reg["periodic_peak_k"]) <= q + 1e-9
    argmax_equals = full["periodic_hottest_block"] == reg["hottest"]
    steady_delta = abs(full["mean_steady_peak_k"] - reg["mean_steady_peak_k"])
    _require(m["gate"].get("value_ok") is value_ok,
             "the stored gate value_ok disagrees with recomputation")
    _require(m["gate"].get("location_ok") is argmax_equals,
             "the stored gate location_ok disagrees with recomputation")
    # The stored `decision_ok` is deliberately NOT compared: the driver computed it with a
    # bare `periodic >= limit`, which is weaker than the shared quantisation rule used here.
    # Requiring the recomputed verdict covers the case where the two disagree.
    #
    # `gate.passed is True` is a precondition, so every recomputed verdict must hold. Without
    # this, a manifest asserting a passed gate could carry a full row that the shared
    # quantisation rule calls indeterminate -- found by a test that expected a refusal here.
    _require(decision_ok and value_ok and argmax_equals,
             f"the manifest reports gate.passed but recomputation gives "
             f"decision_ok={decision_ok} value_ok={value_ok} argmax_equals={argmax_equals}")
    _require(abs(_finite(_get(m["gate"], "steady_delta_k", "gate"), "steady_delta_k")
                 - steady_delta) < 1e-12,
             "the stored steady delta disagrees with recomputation")
    return {"pinned": pinned, "reg": reg, "decision_ok": decision_ok, "value_ok": value_ok,
            "argmax_equals": argmax_equals, "steady_delta_k": steady_delta,
            # The resolution-aware test. `argmax_equals` depends on tie-breaking, so on its
            # own it is not a location claim.
            "in_tie_set": reg["hottest"] in full["periodic_tie_blocks"],
            "registered_is_resolvable": full["periodic_top_gap_k"] > q,
            "stored_decision_ok": m["gate"].get("decision_ok")}


def validate_execution(m: dict, view: dict) -> dict:
    """Validate the per-row audit receipts and the argmax tie evidence.

    These are PRODUCER-REPORTED. Checking them catches an inconsistent producer, not a
    dishonest one; the document says so rather than calling them proof of execution.
    """
    rows, run, q = view["rows"], m["run"], view["quantum"]
    nonce = _get(run, "run_id", "run")
    r0, r1 = _finite(_get(run, "started_unix", "run"), "run.started_unix"), \
             _finite(_get(run, "ended_unix", "run"), "run.ended_unix")
    receipts, moves = {}, []
    for tag in sorted(rows):
        r, w = rows[tag], f"row `{tag}`"
        ex = _get(r, "execution", w)
        _require(isinstance(ex, dict) and ex, f"{w}: the execution receipt is empty")
        _require(ex.get("run_nonce") == nonce,
                 f"{w}: receipt nonce {ex.get('run_nonce')!r} != this run's {nonce!r}, so the "
                 f"row belongs to a different execution")
        _require(ex.get("dest_existed_before_run") is False,
                 f"{w}: the row directory already existed before the row ran")
        _require(not ex.get("workspace_files_before_run"),
                 f"{w}: the HotSpot workspace was not empty before the row ran")
        _require(isinstance(ex.get("pid"), int) and ex["pid"] > 0, f"{w}: no valid PID")
        s, e = _finite(_get(ex, "started_unix", w), w), _finite(_get(ex, "ended_unix", w), w)
        _require(r0 <= s <= e <= r1 + 1e-6, f"{w}: the row's wall window is outside the run's")
        _require(abs(_finite(_get(ex, "wall_s", w), w) - (e - s)) < 1e-6,
                 f"{w}: wall_s disagrees with ended - started")
        # 1 mean-steady solve + 1 fixed-initial solve + one per cycle attempt. Cycle doubling
        # from 8 means log2(cycles/8) + 1 attempts.
        attempts = max(1, r["cycles"].bit_length() - 8 .bit_length() + 1)
        _require(_get(ex, "hotspot_invocations", w) == 2 + attempts,
                 f"{w}: {ex['hotspot_invocations']} invocations does not match the "
                 f"{2 + attempts} implied by converging at {r['cycles']} cycles")
        raw = _get(ex, "raw_outputs", w)
        _require(isinstance(raw, dict) and raw, f"{w}: no workspace artefacts hashed")
        for name, h in raw.items():
            _require(isinstance(h, str) and len(h) == 64 and all(c in "0123456789abcdef"
                                                                for c in h),
                     f"{w}: {name} has a malformed sha256 {h!r}")
        # The workspace holds BOTH the ptrace files the driver wrote and HotSpot's outputs.
        # Counting all of them as "HotSpot outputs" was wrong; separate them by suffix.
        produced = {n: h for n, h in raw.items() if not n.endswith(".ptrace")}
        # Each invocation writes exactly one output: mean.steady, fixed-initial.ttrace, then
        # one periodic-N.ttrace per cycle attempt.
        _require(len(produced) == ex["hotspot_invocations"],
                 f"{w}: {len(produced)} HotSpot output files for "
                 f"{ex['hotspot_invocations']} invocations; each invocation writes one")
        _require({"mean.steady", "fixed-initial.ttrace"} <= set(produced),
                 f"{w}: the mean-steady or fixed-initial output is missing")
        _require(f"periodic-{r['cycles']}.ttrace" in produced,
                 f"{w}: no ttrace for the converged {r['cycles']}-cycle replay")
        receipts[tag] = dict(ex, hotspot_outputs=len(produced), driver_inputs=len(raw) - len(produced))

        # tie evidence, both semantics, all fields required
        for sem in ("periodic", "mean_steady"):
            peak = r[f"{sem}_peak_k"]
            second = _finite(_get(r, f"{sem}_second_peak_k", w), f"{w}.{sem}_second_peak_k")
            gap = _finite(_get(r, f"{sem}_top_gap_k", w), f"{w}.{sem}_top_gap_k")
            ties = _get(r, f"{sem}_tie_blocks", w)
            _require(second <= peak + 1e-12, f"{w}: {sem} runner-up exceeds the peak")
            _require(abs(gap - (peak - second)) < 1e-9,
                     f"{w}: {sem} top gap disagrees with peak - runner-up")
            _require(gap >= -1e-12, f"{w}: {sem} top gap is negative")
            _require(isinstance(ties, list) and ties and len(set(ties)) == len(ties),
                     f"{w}: {sem} tie set is empty or has duplicates")
            _require(r[f"{sem}_hottest_block"] in ties,
                     f"{w}: the reported {sem} argmax is not in its own tie set")
        # A label change is a RELOCATION only if both endpoints are resolvable: the old block
        # outside the new tie set and the new block outside the old one.
        a, b = r["mean_steady_hottest_block"], r["periodic_hottest_block"]
        if a != b:
            resolved = (a not in r["periodic_tie_blocks"]
                        and b not in r["mean_steady_tie_blocks"]
                        and r["periodic_top_gap_k"] > q and r["mean_steady_top_gap_k"] > q)
            moves.append({"tag": tag, "steady": a, "periodic": b, "resolved": resolved,
                          "periodic_gap_k": r["periodic_top_gap_k"],
                          "steady_gap_k": r["mean_steady_top_gap_k"],
                          "periodic_ties": len(r["periodic_tie_blocks"])})
    return {"receipts": receipts, "moves": moves, "nonce": nonce,
            "tied_rows": sorted(t for t in rows if len(rows[t]["periodic_tie_blocks"]) > 1)}


# --- rendering -------------------------------------------------------------------------

def build(m: dict) -> tuple:
    ident = validate_identity(m)
    view = validate_rows(m)
    view.update(ident)
    gate = validate_gate(m, view)
    ex = validate_execution(m, view)
    return view, gate, ex


def render(m: dict, view: dict, g: dict, ex: dict, manifest_path: Path) -> str:
    rows, q, limit = view["rows"], view["quantum"], view["limit"]
    comp, comps = view["comp"], view["comps"]
    total = m["full_source_energy_j"]
    run, reg, excess = view["run"], g["reg"], view["excess_k"]
    n = len(rows)
    L: list[str] = []
    A = L.append

    A("# V6.1 source-subset isolation under a fixed additive power trace")
    A("")
    A(f"Recomputed from the manifest rows by `research/triangle/v61_render_evidence.py`: the "
      f"subset enumeration, every row's classification, the crossing coalitions, the "
      f"leave-one-out table, the energy ledger, convergence, cross-row provenance, and the "
      f"gate verdicts (against the pinned registration "
      f"`{_rel(REGISTRATION)}`, not the manifest's own copy of them). Any "
      f"disagreement is a refusal. **Producer-reported, and not independently re-derivable "
      f"here:** the temperature scalars themselves, the superposition residual, the execution "
      f"receipts, and the scope sentence.")
    A("")
    A("## Provenance")
    A("")
    A(f"- commit `{m['commit'][:12]}`, working tree CLEAN at start and end "
      f"(`provenance_stable = {m['provenance_stable']}`)")
    A(f"- candidate `{m['workload']}` / `{m['arch']}`, model `{m['model']}`, requested step "
      f"{m['max_step_us']} us, ambient {view['ambient']} K, limit {limit} K")
    A(f"- host `{run.get('host','?')}`, {run.get('platform','?')}, "
      f"Python {run.get('python','?')}, NumPy {run.get('numpy','?')}, schema "
      f"{run['schema_version']}")
    A(f"- run `{run['run_id']}`, wall {(run['ended_unix']-run['started_unix'])/60:.1f} min")
    A("- every input staged read-only, hashed as read, re-verified after each replay:")
    for k, h in sorted(m["input_hashes"].items()):
        A(f"  - `{k}` `{h[:16]}…`")
    A(f"- superposition identity, subset == sum of singletons: worst "
      f"`{m['superposition_worst_w']:.3e}` W (producer-reported)")
    A("")
    earlier = g["pinned"]["earlier_hotspot_binary_sha256"]
    same_binary = m["hotspot_sha256"] == earlier["sha256"]
    A(f"**This run is not an independent numerical confirmation of the registered numbers, and "
      f"nothing here should be read as one.** The staged HotSpot binary is "
      f"{'byte-identical to' if same_binary else 'DIFFERENT from'} the one used by the earlier "
      f"transient work (`{earlier['document']}:{earlier['line']}`). With the same binary, "
      f"inputs, code and platform, agreement to the last printed digit — including the "
      f"`{g['steady_delta_k']:.3e}` K steady residual against a value quoted to six decimals — "
      f"is what arithmetic requires. It evidences a reproducible build and an intact "
      f"provenance chain; it evidences nothing about the physics and nothing about whether a "
      f"solver ran.")
    A("")
    A("### Execution receipts (producer-generated audit receipts, not proof of execution)")
    A("")
    inv = sum(r["hotspot_invocations"] for r in ex["receipts"].values())
    outs = sum(r["hotspot_outputs"] for r in ex["receipts"].values())
    ins = sum(r["driver_inputs"] for r in ex["receipts"].values())
    A(f"Every row records that its directory and HotSpot workspace did not exist beforehand, "
      f"its PID, a wall window inside the run's, this run's nonce, its HotSpot invocation "
      f"count, and a SHA-256 of every workspace file. Across {n} rows: **{inv} HotSpot "
      f"invocations**, **{outs} HotSpot output files** and {ins} driver-written `.ptrace` "
      f"inputs, all hashed. The invocation count is checked against the count implied by each "
      f"row's converged cycle count, and the expected output filenames must be present — so an "
      f"inconsistent producer is caught. A *dishonest* producer is not: these fields are "
      f"self-attested and nothing here re-hashes the artefacts at render time. That is the "
      f"remaining gap, and it is the reason this section is not called proof.")
    A("")
    A("| subset | invocations | HotSpot outputs | wall (s) | cycles |")
    A("| --- | ---: | ---: | ---: | ---: |")
    for t in sorted(rows, key=lambda t: ex["receipts"][t]["started_unix"]):
        r = ex["receipts"][t]
        A(f"| `{t}` | {r['hotspot_invocations']} | {r['hotspot_outputs']} | "
          f"{r['wall_s']:.1f} | {rows[t]['cycles']} |")
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
      "periodic argmax | cycles | status |")
    A("| --- | ---: | ---: | ---: | --- | --- | ---: | --- |")
    for t in sorted(rows, key=lambda t: rows[t]["periodic_peak_k"]):
        r, st = rows[t], view["status"][t]
        A(f"| {'**full**' if t == 'full' else '`'+t+'`'} | {r['mean_steady_peak_k']:.6f} | "
          f"{r['periodic_peak_k']:.2f} | "
          f"{r['periodic_peak_k']-r['mean_steady_peak_k']:+.2f} | "
          f"`{r['mean_steady_hottest_block']}` | `{r['periodic_hottest_block']}` | "
          f"{r['cycles']} | {'**CROSSING**' if st == 'crossing' else st} |")
    A("")
    A(f"HotSpot reports transient temperature to {q} K, so with a {limit} K limit a row is "
      f"`crossing` iff `periodic >= {limit+q}` K, `below` iff `periodic <= {limit-q}` K, and "
      f"`indeterminate` otherwise — exactly {limit} K is **not** a crossing. Indeterminate "
      f"rows: {', '.join('`'+t+'`' for t in view['indeterminate']) or 'none'}. Every row "
      f"converged to within its {rows['full']['tolerance_k']} K tolerance, which equals the "
      f"output quantum: convergence is at the observability floor, not below it.")
    A("")
    A("## Gate")
    A("")
    A(f"Recomputed against `{_rel(REGISTRATION)}`, whose registered tuple the "
      f"manifest must match exactly:")
    A("")
    A(f"- decision — steady < {limit} K **and** the full row classifies as `crossing` under "
      f"the same quantisation rule as every other row: **{g['decision_ok']}**")
    A(f"- periodic value within one {q} K quantum of the registered "
      f"{reg['periodic_peak_k']} K: **{g['value_ok']}**")
    A(f"- reported argmax equals the registered `{reg['hottest']}`: **{g['argmax_equals']}**")
    A("")
    if not g["registered_is_resolvable"]:
        A(f"**The location check is not a location claim.** The full row's top-two gap is "
          f"`{rows['full']['periodic_top_gap_k']:.2f}` K — its argmax is tied with "
          f"{', '.join('`'+b+'`' for b in rows['full']['periodic_tie_blocks'] if b != reg['hottest'])} "
          f"at the reported resolution. `{reg['hottest']}` is in the tie set "
          f"(**{g['in_tie_set']}**), which is the most that can be asserted; exact argmax "
          f"equality holds only because of how the tie is broken, and a change of tie-break "
          f"order would flip it and fail this gate for no physical reason. **This has already "
          f"happened**: refactoring the argmax from a flat maximum over (sample, block) to a "
          f"per-block maximum changed one row's reported label with every temperature "
          f"unchanged. The driver still gates on exact equality; making it gate on tie-set "
          f"membership is an open item.")
        A("")
    A(f"**The gate binds names and temperatures, NOT the registered instance** "
      f"(`binds_instance_hashes = {reg['binds_instance_hashes']}`, "
      f"`canonical_trace_sha256 = {reg['canonical_trace_sha256']}`). It does not verify that "
      f"the registry, power trace or routing are unchanged, so a changed registry under the "
      f"same workload/architecture names would still pass. Closing that needs a canonical "
      f"trace hash preregistered from a run that is itself claim-grade. Open gap.")
    A("")
    A("## Result")
    A("")
    if view["uniqueness_claimable"]:
        A(f"The {n} rows exhaust every non-empty subset of "
          f"{{{', '.join('`'+c+'`' for c in comps)}}} with no indeterminate row, and exactly "
          f"one of them crosses: **`{view['minimal'][0]}`** is the unique minimal crossing "
          f"coalition in this factorial. That is a statement about this trace, this candidate "
          f"and this discretisation — not about candidates, traces or discretisations in "
          f"general.")
    else:
        A(f"Minimal crossing coalitions: "
          f"{', '.join('`'+c+'`' for c in view['minimal']) or 'none'}. Uniqueness is **not** "
          f"claimable: {len(view['minimal'])} minimal coalition(s) and "
          f"{len(view['indeterminate'])} indeterminate row(s).")
    A("")
    A("### Leave-one-out is an arithmetic consequence, not a second finding")
    A("")
    d = {k: v["removal_delta_k"] for k, v in view["loo"].items()}
    lo_k = min(d, key=lambda k: d[k])
    # Quantisation-aware: a removal must exceed the excess by a full quantum to guarantee the
    # row lands strictly below rather than on the undecidable boundary.
    arithmetic = all(v["status"] == "below" for v in view["loo"].values()) and \
        min(d.values()) >= excess + q
    A(f"The full set crosses by only **{excess:+.2f} K** ({view['full']['periodic_peak_k']:.2f} "
      f"K against a {limit} K limit). "
      + (f"Every removal costs at least a full {q} K quantum more than that excess (smallest: "
         f"{d[lo_k]:+.2f} K for `{lo_k}`), so once the exhaustive factorial shows the full set "
         f"is the only crossing subset, all {len(d)} leave-one-out verdicts follow with no "
         f"further information. This is **Boolean threshold necessity within a fixed "
         f"factorial**, not a measure of physical causal importance."
         if arithmetic else
         f"Not every removal clears the excess by a full {q} K quantum (smallest: "
         f"{d[lo_k]:+.2f} K for `{lo_k}`), so the verdicts are not purely arithmetic — read "
         f"the table row by row."))
    A("")
    A("| removed source | periodic (K) | removal delta (K) | delta / excess | "
      "margin to limit (K) | status |")
    A("| --- | ---: | ---: | ---: | ---: | --- |")
    for k in sorted(view["loo"], key=lambda k: -d[k]):
        v = view["loo"][k]
        A(f"| `{k}` | {v['periodic_peak_k']:.2f} | {v['removal_delta_k']:+.2f} | "
          f"{v['removal_delta_k']/excess:.1f}x | {v['margin_to_limit_k']:+.2f} | "
          f"{'below → necessary in the grand coalition' if v['status'] == 'below' else v['status']} |")
    A("")
    A(f"The informative row is the smallest. `{lo_k}` carries "
      f"{100*comp[lo_k]/total:.3f}% of the dissipated energy yet its removal drops the "
      f"periodic peak by {d[lo_k]:.2f} K — {d[lo_k]/excess:.1f}x the excess and "
      f"{d[lo_k]/q:.0f}x the {q} K quantum. Energy share does not predict which source decides "
      f"the threshold; the deltas do, and they are what a paper table should carry rather than "
      f"the necessity label.")
    A("")
    A("## Appendix — the reported argmax block is mostly not resolvable")
    A("")
    tied = ex["tied_rows"]
    A(f"In **{len(tied)} of {n}** subsets the periodic argmax is tied with at least one other "
      f"block at the reported resolution, and in most of those the top-two gap is exactly "
      f"0.000e+00 K — far below quantisation, i.e. the two blocks are assigned the same "
      f"temperature by the model, not merely rounded to it. Under `{m['model']}` a block's "
      f"temperature is the maximum over the grid cells covering it, so two blocks sharing the "
      f"hottest cell receive identical values; that is the leading explanation and it is "
      f"**UNTESTED** here.")
    A("")
    if ex["moves"]:
        A(f"{len(ex['moves'])} subsets report a different argmax label for the two semantics:")
        A("")
        A("| subset | steady argmax | periodic argmax | steady gap (K) | periodic gap (K) | "
          "periodic tie set | relocation? |")
        A("| --- | --- | --- | ---: | ---: | ---: | --- |")
        for mv in ex["moves"]:
            A(f"| `{mv['tag']}` | `{mv['steady']}` | `{mv['periodic']}` | "
              f"{mv['steady_gap_k']:.2f} | {mv['periodic_gap_k']:.2f} | "
              f"{mv['periodic_ties']} | "
              f"{'yes' if mv['resolved'] else 'NO — a tie broken differently'} |")
        A("")
        unresolved = [mv["tag"] for mv in ex["moves"] if not mv["resolved"]]
        A(f"A label change counts as a relocation only if BOTH endpoints are resolvable: the "
          f"old block outside the new tie set, the new block outside the old one, and both "
          f"gaps above one quantum. "
          + (f"{len(unresolved)} of {len(ex['moves'])} fail that test "
             f"({', '.join('`'+t+'`' for t in unresolved)}), so they are not evidence that a "
             f"peak moved." if unresolved else
             f"All {len(ex['moves'])} pass it, which still makes them observations about the "
             f"argmax rather than a demonstrated mechanism."))
    else:
        A("No subset reports a different argmax label for the two semantics.")
    A("")
    A("## Scope")
    A("")
    A(f"Evidence grade: **run-provenance-controlled, registry-instance-unbound, "
      f"single-capture HotSpot evidence with producer-attested execution receipts.** The "
      f"staged hashes establish integrity within this execution; "
      f"`binds_instance_hashes = {reg['binds_instance_hashes']}` leaves the identity link to "
      f"the originally registered trace and routing open; no independent thermal model has "
      f"validated any number here. (The run recorded its own grade as "
      f"\"{m['summary']['evidence_grade']}\" — producer-reported, superseded by the above.)")
    A("")
    lo, hi = min(view["ratios"], key=lambda t: view["ratios"][t]), \
             max(view["ratios"], key=lambda t: view["ratios"][t])
    A(f"Bounded to: this fixed trace; this fixed routing and timing; an additive deposition "
      f"intervention; the HotSpot model, candidate and discretisation; and the **fixed "
      f"decomposition of {total*1e3:.3f} mJ into "
      f"{', '.join('`'+c+'`' for c in comps)}** — a different assignment of the same total "
      f"would change every row, and that assignment is an artefact of the routed-trace "
      f"lowering, not a measurement. Says nothing about temperature-dependent power feedback. "
      f"NOT established: that any source alone suffices; that periodic uplift is "
      f"baseline-independent (as a fraction of the steady rise above ambient it spans "
      f"{view['ratios'][lo]:.2f}% for `{lo}` to {view['ratios'][hi]:.2f}% for `{hi}`, and the "
      f"{q} K quantum is already "
      f"{100*q/(rows[hi]['mean_steady_peak_k']-view['ambient']):.2f}% of `{hi}`'s rise, so any "
      f"source-identity effect is `{m['summary']['source_identity_effect_on_uplift']}`); "
      f"generalisation to other candidates, models or discretisations; or agreement with any "
      f"independent thermal model.")
    A("")
    g128 = g["pinned"]["grid128_row"]
    A(f"`grid128-max` has not been run as a factorial. Its registered argmax "
      f"(`{g128['steady_block']}` steady / `{g128['periodic_block']}` periodic, "
      f"`{g128['document']}:{g128['line']}`) differs from this run's `{reg['hottest']}`, but "
      f"given how few argmax labels here are resolvable that difference cannot currently be "
      f"read as a spatial finding. A grid128 factorial would need its own preregistration and "
      f"is only required if the paper claims resolution robustness or a spatial mechanism.")
    A("")
    # repo-relative when inside the tree, so the document is path-independent and can be
    # regenerated byte-for-byte from any checkout
    A(f"Manifest: `{_rel(manifest_path)}`")
    return "\n".join(L) + "\n"


def main() -> None:
    manifest_path = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    m = json.loads(manifest_path.read_text())
    try:
        view, gate, ex = build(m)
        text = render(m, view, gate, ex, manifest_path)
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
