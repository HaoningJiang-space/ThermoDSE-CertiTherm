"""Validate a schema-4 V6.1 manifest and derive everything a document needs from it.

Split out of the renderer so that formatting cannot quietly become validation. What is
independently RECOMPUTED here, with a refusal on any disagreement:

- the exact 2^n-1 subset enumeration, each row tagging to its own key;
- every row's peak, argmax, runner-up, top gap and resolution-aware tie set, from the per-block
  temperature VECTORS -- so no tie claim is trusted. A producer-reported tie list could name any
  block, because nothing tied it to a temperature;
- the quantisation-aware classification, crossing coalitions and leave-one-out table;
- convergence: residual against tolerance, tolerance against the output quantum, step against
  the requested step;
- the energy ledger against every row's retained energy;
- cross-row and row-vs-top-level provenance identity;
- the gate, against the pinned registration -- including the LOCATION predicate computed from
  the registered block's own temperature rather than from an argmax label;
- the per-invocation receipt sequence against each row's converged cycle count.

What remains producer-attested and is labelled so in the document: the temperatures themselves,
the superposition residual, and the execution receipts. Hashes without retained bytes cannot be
re-verified here.
"""
from __future__ import annotations

import hashlib
import json
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.triangle.v61_contract import (  # noqa: E402
    REGISTRATION,
    check_citation,
    classify,
    finite,
    get,
    load_registration,
    rel,
    require,
    subset_tag,
)

REQUIRED_SCHEMA = 5
REQUIRED_GATE_POLICY = 3

# Fields every row must agree on. `trace_sha256` is deliberately absent -- each subset has its
# own masked trace and the hashes must all DIFFER. `dirty`/`diff_sha256` are present: a row
# produced from a different tree state voids the set.
ROW_INVARIANT = ("commit", "dirty", "diff_sha256", "workload", "arch", "model", "max_step_us",
                 "ambient_k", "tolerance_k", "io_aspect_ratio", "hotspot_sha256",
                 "schema_version", "output_resolution_k", "input_hashes", "block_ids")
SHARED_WITH_TOP = ("commit", "dirty", "workload", "arch", "model", "max_step_us", "ambient_k",
                   "hotspot_sha256", "input_hashes")
HASH_CHARS = set("0123456789abcdef")


def _hash(value, where: str) -> str:
    require(isinstance(value, str) and len(value) == 64 and set(value) <= HASH_CHARS,
            f"{where} is not a sha256 ({value!r})")
    return value


def peak_view(values, block_ids, quantum: float, where: str) -> dict:
    """Recompute peak, argmax, runner-up, gap and tie set from a temperature vector.

    This is the whole point of storing vectors: the tie set is DERIVED, so a manifest cannot
    assert that the registered block is tied when its temperature says otherwise.
    """
    require(len(values) == len(block_ids),
            f"{where}: {len(values)} temperatures for {len(block_ids)} blocks")
    vals = [finite(v, f"{where}[{i}]") for i, v in enumerate(values)]
    peak = max(vals)
    winner = vals.index(peak)                     # first maximum in block order
    ties = tuple(block_ids[i] for i in sorted(range(len(vals)),
                                              key=lambda i: (-vals[i], i))
                 if peak - vals[i] <= quantum + 1e-9)
    rest = [v for i, v in enumerate(vals) if i != winner]
    second = max(rest) if rest else peak
    return {"peak_k": peak, "block": block_ids[winner], "second_k": second,
            "gap_k": peak - second, "ties": ties, "values": vals}


def validate_identity(m: dict) -> dict:
    gate = m.get("gate") or {}
    require(m.get("complete") is True and gate.get("passed") is True,
            f"complete={m.get('complete')} gate.passed={gate.get('passed')} "
            f"suppression={m.get('suppression_reason')}")
    run = get(m, "run", "manifest")
    require(get(run, "schema_version", "run") == REQUIRED_SCHEMA,
            f"manifest is schema {run.get('schema_version')}; this validator accepts only "
            f"schema {REQUIRED_SCHEMA}. Earlier manifests are historical artefacts, not "
            f"inputs: they record derived tie scalars instead of the temperature vectors "
            f"those claims have to be recomputed from.")
    require(get(gate, "gate_policy_version", "gate") == REQUIRED_GATE_POLICY,
            f"gate policy {gate.get('gate_policy_version')} != the accepted "
            f"{REQUIRED_GATE_POLICY}; the acceptance predicate is versioned separately from "
            f"the field schema and this manifest was admitted by a different one")
    require(not m["dirty"] and m.get("provenance_stable") is True,
            f"claim-grade rendering requires a clean tree that stayed clean: "
            f"dirty={len(m['dirty'])} provenance_stable={m.get('provenance_stable')}")
    end = get(m, "provenance_end", "manifest")
    require(end.get("commit") == m["commit"] and not end.get("dirty"),
            "the end-of-run provenance does not match the start")
    require(_hash(m["input_hashes"].get("hotspot"), "input_hashes.hotspot")
            == m["hotspot_sha256"],
            "the staged hotspot hash disagrees with the recorded binary hash")
    return {"gate": gate, "run": run}


def validate_rows(m: dict) -> dict:
    rows = get(m, "rows", "manifest")
    limit = finite(get(m, "thermal_limit_k", "manifest"), "thermal_limit_k")
    ambient = finite(get(m, "ambient_k", "manifest"), "ambient_k")
    comp = get(m, "component_energy_j", "manifest")
    comps = sorted(comp)
    for c in comps:
        require(finite(comp[c], f"component_energy_j[{c}]") > 0,
                f"component `{c}` has non-positive energy")

    want = {subset_tag(c, comps) for k in range(1, len(comps) + 1)
            for c in combinations(comps, k)}
    require(len(want) == 2 ** len(comps) - 1,
            f"component names collide under tagging: {len(want)} tags for {len(comps)} names")
    require(set(rows) == want,
            f"row set != the {len(want)} non-empty subsets; missing "
            f"{sorted(want - set(rows))}, extra {sorted(set(rows) - want)}")

    full_tag = subset_tag(comps, comps)
    ref = rows[full_tag]
    quantum = finite(get(ref, "output_resolution_k", "full row"), "output_resolution_k")
    require(quantum > 0, "output resolution must be positive")
    block_ids = get(ref, "block_ids", "full row")
    require(isinstance(block_ids, list) and block_ids
            and len(set(block_ids)) == len(block_ids),
            "the block registry is empty or has duplicate names")

    view = {}
    for tag in sorted(rows):
        r, w = rows[tag], f"row `{tag}`"
        require(r.get("complete") is True, f"{w}: row is not complete")
        require(subset_tag(get(r, "components", w), comps) == tag,
                f"{w}: components {r['components']} do not tag to its own key")
        for f in ROW_INVARIANT:
            require(get(r, f, w) == ref[f],
                    f"{w}: {f} differs from the full row")

        periodic = peak_view(get(r, "periodic_block_peaks_k", w), block_ids, quantum,
                             f"{w}.periodic")
        steady = peak_view(get(r, "mean_steady_block_k", w), block_ids, quantum,
                           f"{w}.mean_steady")
        # The stored scalars must agree with the observation they summarise.
        for name, got_key, derived in (("periodic peak", "periodic_peak_k", periodic["peak_k"]),
                                       ("steady peak", "mean_steady_peak_k", steady["peak_k"])):
            require(abs(finite(get(r, got_key, w), f"{w}.{got_key}") - derived) < 1e-9,
                    f"{w}: stored {name} disagrees with its own temperature vector "
                    f"({r[got_key]!r} vs {derived!r})")
        require(get(r, "periodic_hottest_block", w) == periodic["block"],
                f"{w}: stored periodic argmax disagrees with its temperature vector")
        require(get(r, "mean_steady_hottest_block", w) == steady["block"],
                f"{w}: stored steady argmax disagrees with its temperature vector")
        require(steady["peak_k"] > ambient,
                f"{w}: steady peak {steady['peak_k']} is not above ambient {ambient}")

        tol = finite(get(r, "tolerance_k", w), f"{w}.tolerance_k")
        require(tol >= quantum,
                f"{w}: tolerance {tol} K is finer than the {quantum} K output resolution")
        residual = max(finite(get(r, "boundary_residual_k", w), f"{w}.boundary_residual_k"),
                       finite(get(r, "peak_residual_k", w), f"{w}.peak_residual_k"))
        require(residual <= tol + 1e-9,
                f"{w}: periodic residual {residual} K exceeds its {tol} K tolerance")
        cycles = get(r, "cycles", w)
        require(isinstance(cycles, int) and cycles >= 2, f"{w}: {cycles!r} cycles is unconverged")
        step = finite(get(r, "step_s", w), f"{w}.step_s")
        require(0 < step <= r["max_step_us"] * 1e-6 + 1e-15,
                f"{w}: step {step} s is not in (0, the requested {r['max_step_us']} us]")
        spc = get(r, "samples_per_cycle", w)
        require(isinstance(spc, int) and spc > 0, f"{w}: samples_per_cycle {spc!r} is invalid")
        require(abs(sum(comp[c] for c in r["components"])
                    - finite(get(r, "retained_source_energy_j", w), f"{w}.retained")) <= 1e-15,
                f"{w}: retained energy != the sum of its components in the ledger")
        _hash(get(r, "trace_sha256", w), f"{w}.trace_sha256")

        view[tag] = {"row": r, "periodic": periodic, "steady": steady,
                     "status": classify(periodic["peak_k"], limit, quantum),
                     "margin_to_limit_k": limit - periodic["peak_k"],
                     "uplift_k": periodic["peak_k"] - steady["peak_k"],
                     "uplift_ratio_pct": 100 * (periodic["peak_k"] - steady["peak_k"])
                                         / (steady["peak_k"] - ambient)}

    require(len({rows[t]["trace_sha256"] for t in rows}) == len(rows),
            "two rows record the same trace hash, so one masked trace served two subsets")
    require(abs(sum(comp.values()) - finite(get(m, "full_source_energy_j", "manifest"),
                                           "full_source_energy_j")) <= 1e-15,
            "component energies do not sum to the full source energy")
    for f in SHARED_WITH_TOP:
        require(ref[f] == get(m, f, "manifest"), f"top-level {f} disagrees with the rows")

    crossing = {frozenset(rows[t]["components"]) for t in rows if view[t]["status"] == "crossing"}
    minimal = sorted(("+".join(sorted(c)) for c in crossing
                      if not any(o < c for o in crossing)), key=len)
    full = view[full_tag]
    loo = {}
    for drop in comps:
        t = subset_tag([c for c in comps if c != drop], comps)
        loo[drop] = dict(view[t], tag=t,
                         removal_delta_k=full["periodic"]["peak_k"] - view[t]["periodic"]["peak_k"])
    indeterminate = sorted(t for t in rows if view[t]["status"] == "indeterminate")
    return {"rows": rows, "view": view, "comps": comps, "quantum": quantum, "limit": limit,
            "ambient": ambient, "comp": comp, "block_ids": block_ids, "full_tag": full_tag,
            "full": full, "minimal": minimal, "loo": loo, "indeterminate": indeterminate,
            "excess_k": full["periodic"]["peak_k"] - limit,
            "uniqueness_claimable": len(minimal) == 1 and not indeterminate}


def validate_gate(m: dict, v: dict) -> dict:
    """Recompute the gate from the full row and the PINNED registration.

    The location predicate is computed from the registered block's OWN temperature. Exact argmax
    equality made the gate depend on how an exact tie was broken -- and most rows here are exact
    ties -- while membership in a producer-reported tie list would only have exchanged
    tie-break fragility for list-integrity fragility.
    """
    pinned = load_registration()
    reg = pinned["registered_tuple"]
    gate = m["gate"]
    require(get(gate, "registered_tuple", "gate") == reg,
            f"the manifest's registered tuple differs from the pinned registration in "
            f"{rel(REGISTRATION)}; one of them has drifted")
    require(gate.get("registration_id") == pinned["registration_id"],
            "the manifest names a different registration id")
    live = hashlib.sha256(REGISTRATION.read_bytes()).hexdigest()
    registration_intact = gate.get("registration_sha256") == live
    for f in ("workload", "arch", "model", "max_step_us", "ambient_k"):
        require(m[f] == reg[f],
                f"this run's {f}={m[f]!r} is not the registered {reg[f]!r}; the gate does not "
                f"apply and no registered comparison may be printed")
    require(v["limit"] == reg["thermal_limit_k"], "the run's limit is not the registered one")
    check_citation(pinned["grid64_source"],
                   [reg["hottest"], reg["periodic_peak_k"], reg["mean_steady_peak_k"]])
    check_citation(pinned["grid128_row"], [pinned["grid128_row"]["steady_block"],
                                           pinned["grid128_row"]["periodic_block"]])
    check_citation(pinned["earlier_hotspot_binary_sha256"],
                   [pinned["earlier_hotspot_binary_sha256"]["sha256"]])

    # INSTANCE BINDING. Until gate policy 3 the gate bound names and temperatures only, so a
    # changed registry, trace or routing under the same workload/architecture names would have
    # passed. The canonical hashes were canonicalised from the schema-4 claim-grade run, not
    # preregistered ahead of it -- so they pin that FUTURE runs replay the same physical instance
    # as the run the document rests on, not that that run replayed the original.
    require(reg["binds_instance_hashes"] is True,
            "gate policy 3 requires the registration to bind instance hashes")
    canon = get(pinned, "canonical_instance", "registration")
    require(m["input_hashes"] == get(canon, "input_hashes", "canonical_instance"),
            "the staged inputs are not the canonical instance's")
    require(m["hotspot_sha256"] == canon["hotspot_sha256"],
            "the HotSpot binary is not the canonical instance's")
    registry = hashlib.sha256("\n".join(v["block_ids"]).encode()).hexdigest()
    require(registry == get(canon, "block_registry_sha256", "canonical_instance"),
            f"the floorplan block registry hashes to {registry[:16]}..., not the canonical "
            f"{canon['block_registry_sha256'][:16]}...; the geometry or its naming changed")
    canon_traces = get(canon, "trace_sha256_by_subset", "canonical_instance")
    require(set(canon_traces) == set(v["rows"]),
            "the canonical instance pins a different subset set")
    for tag in sorted(v["rows"]):
        require(v["rows"][tag]["trace_sha256"] == canon_traces[tag],
                f"row `{tag}` replayed a different power trace than the canonical instance")
    require(v["comp"] == get(canon, "component_energy_j", "canonical_instance"),
            "the source energy decomposition is not the canonical instance's")
    require(reg["canonical_trace_sha256"] == canon_traces[v["full_tag"]],
            "the registered canonical trace hash disagrees with the canonical instance")

    full, q = v["full"], v["quantum"]
    require(reg["hottest"] in v["block_ids"],
            f"the registered block {reg['hottest']!r} is not in this run's block registry")
    registered_k = full["periodic"]["values"][v["block_ids"].index(reg["hottest"])]
    peak = full["periodic"]["peak_k"]
    decision_ok = full["steady"]["peak_k"] < v["limit"] and full["status"] == "crossing"
    value_ok = abs(peak - reg["periodic_peak_k"]) <= q + 1e-9
    location_compatible = 0.0 <= peak - registered_k <= q + 1e-9
    argmax_equals = full["periodic"]["block"] == reg["hottest"]
    steady_delta = abs(full["steady"]["peak_k"] - reg["mean_steady_peak_k"])
    require(gate.get("location_compatible_at_resolution") is location_compatible,
            "the stored location verdict disagrees with recomputation")
    require(abs(finite(get(gate, "steady_delta_k", "gate"), "steady_delta_k") - steady_delta)
            < 1e-12, "the stored steady delta disagrees with recomputation")
    # `gate.passed is True` is a precondition, so every recomputed verdict must hold.
    require(decision_ok and value_ok and location_compatible,
            f"the manifest reports gate.passed but recomputation gives decision_ok="
            f"{decision_ok} value_ok={value_ok} location_compatible={location_compatible}")
    return {"pinned": pinned, "reg": reg, "decision_ok": decision_ok, "value_ok": value_ok,
            "location_compatible": location_compatible, "argmax_equals": argmax_equals,
            "registered_block_k": registered_k, "steady_delta_k": steady_delta,
            "registration_intact": registration_intact,
            "registered_is_resolvable": full["periodic"]["gap_k"] > q,
            "policy_version": gate["gate_policy_version"]}


def validate_execution(m: dict, v: dict) -> dict:
    rows, run, q = v["rows"], m["run"], v["quantum"]
    nonce = get(run, "run_id", "run")
    r0 = finite(get(run, "started_unix", "run"), "run.started_unix")
    r1 = finite(get(run, "ended_unix", "run"), "run.ended_unix")
    receipts, moves = {}, []
    for tag in sorted(rows):
        r, w = rows[tag], f"row `{tag}`"
        ex = get(r, "execution", w)
        require(isinstance(ex, dict) and ex, f"{w}: the execution receipt is empty")
        require(ex.get("run_nonce") == nonce,
                f"{w}: receipt nonce {ex.get('run_nonce')!r} != this run's {nonce!r}, so the "
                f"row belongs to a different execution")
        require(ex.get("dest_existed_before_run") is False,
                f"{w}: the row directory already existed before the row ran")
        require(not ex.get("workspace_files_before_run"),
                f"{w}: the HotSpot workspace was not empty before the row ran")
        require(isinstance(ex.get("pid"), int) and ex["pid"] > 0, f"{w}: no valid PID")
        s, e = finite(get(ex, "started_unix", w), w), finite(get(ex, "ended_unix", w), w)
        require(r0 <= s <= e <= r1 + 1e-6, f"{w}: the row's wall window is outside the run's")
        require(abs(finite(get(ex, "wall_s", w), w) - (e - s)) < 1e-6,
                f"{w}: wall_s disagrees with ended - started")

        # Validate the RECORDED invocation sequence. Inferring the count from the cycle count
        # hard-coded replay_periodic's doubling schedule into the consumer, so a valid receipt
        # from a different initial_cycles would have looked invalid.
        inv = get(ex, "invocations", w)
        require(isinstance(inv, list) and len(inv) >= 3,
                f"{w}: {len(inv) if isinstance(inv, list) else inv!r} invocations recorded; a "
                f"replay needs at least mean-steady, fixed-initial and one periodic attempt")
        roles = [get(rec, "role", f"{w} invocation {i}") for i, rec in enumerate(inv)]
        require(roles[0] == "mean-steady" and roles[1] == "fixed-initial",
                f"{w}: the first two invocations are {roles[:2]}, not the mean-steady and "
                f"fixed-initial solves")
        periodic_roles = roles[2:]
        cycles_seq = []
        for role in periodic_roles:
            require(role.startswith("periodic-"), f"{w}: unexpected invocation role {role!r}")
            n = role.split("-", 1)[1]
            require(n.isdigit(), f"{w}: invocation role {role!r} has no cycle count")
            cycles_seq.append(int(n))
        for a, b in zip(cycles_seq, cycles_seq[1:]):
            require(b == 2 * a,
                    f"{w}: periodic attempts {cycles_seq} are not a doubling sequence")
        require(cycles_seq[-1] == r["cycles"],
                f"{w}: the last periodic attempt is {cycles_seq[-1]} cycles but the row "
                f"converged at {r['cycles']}")
        workspace = get(ex, "workspace_files", w)
        require(isinstance(workspace, dict) and workspace, f"{w}: no workspace files hashed")
        for name, h in workspace.items():
            _hash(h, f"{w}.workspace_files[{name}]")
        seen = set()
        for i, rec in enumerate(inv):
            where = f"{w} invocation {i} ({roles[i]})"
            require(get(rec, "returncode", where) == 0,
                    f"{where}: return code {rec['returncode']!r}; a completed manifest cannot "
                    f"contain a failed invocation")
            out = get(rec, "output", where)
            require(out not in seen, f"{where}: {out!r} was already written by another "
                                     f"invocation")
            seen.add(out)
            require(out in workspace,
                    f"{where}: its output {out!r} is not among the hashed workspace files")
            require(_hash(get(rec, "output_sha256", where), f"{where}.output_sha256")
                    == workspace[out],
                    f"{where}: the recorded output hash disagrees with the workspace hash")
            size = get(rec, "output_bytes", where)
            require(isinstance(size, int) and size > 0, f"{where}: output size {size!r}")
            i0 = finite(get(rec, "started_unix", where), where)
            i1 = finite(get(rec, "ended_unix", where), where)
            require(s <= i0 <= i1 <= e + 1e-6,
                    f"{where}: its wall window is outside the row's")
            require(len(get(rec, "argv", where)) >= 3, f"{where}: argv is implausibly short")
        require(f"periodic-{r['cycles']}.ttrace" in seen,
                f"{w}: no ttrace recorded for the converged {r['cycles']}-cycle replay")
        inputs = {n for n in workspace if n.endswith(".ptrace")}
        require(seen.isdisjoint(inputs),
                f"{w}: an invocation claims a .ptrace input as its own output")
        receipts[tag] = dict(ex, hotspot_invocations=len(inv), hotspot_outputs=len(seen),
                             driver_inputs=len(inputs),
                             output_bytes=sum(rec["output_bytes"] for rec in inv))

        # A label change is a RELOCATION only if both endpoints are resolvable.
        pv, sv = v["view"][tag]["periodic"], v["view"][tag]["steady"]
        if pv["block"] != sv["block"]:
            moves.append({"tag": tag, "steady": sv["block"], "periodic": pv["block"],
                          "periodic_gap_k": pv["gap_k"], "steady_gap_k": sv["gap_k"],
                          "periodic_ties": len(pv["ties"]),
                          "resolved": (sv["block"] not in pv["ties"]
                                       and pv["block"] not in sv["ties"]
                                       and pv["gap_k"] > q and sv["gap_k"] > q)})
    # The raw HotSpot outputs, retained as ONE bundle outside the repository. Hashes without
    # bytes cannot be reparsed by anyone, which was the second-largest gap after instance
    # binding. This does not defeat a dishonest producer; it makes independent reparsing
    # possible at all.
    bundle = get(m, "raw_output_bundle", "manifest")
    _hash(get(bundle, "sha256", "raw_output_bundle"), "raw_output_bundle.sha256")
    require(isinstance(bundle.get("bytes"), int) and bundle["bytes"] > 0,
            f"the raw output bundle has no plausible size ({bundle.get('bytes')!r})")
    members = get(bundle, "members", "raw_output_bundle")
    expected = sum(receipts[t]["hotspot_outputs"] for t in rows)
    require(members == expected,
            f"the bundle holds {members} members but the receipts record {expected} HotSpot "
            f"outputs; something was written or dropped outside the recorded invocations")
    require(bundle.get("in_repository") is False,
            "the bundle must be recorded as living outside the repository")

    fresh = all(receipts[t].get("run_nonce") == nonce for t in rows)
    require(m["summary"].get("all_rows_fresh") is fresh,
            f"summary.all_rows_fresh={m['summary'].get('all_rows_fresh')} but the receipts give "
            f"{fresh}")
    require(fresh, "at least one row does not belong to this run")
    return {"receipts": receipts, "moves": moves, "nonce": nonce, "bundle": bundle,
            "tied_rows": sorted(t for t in rows if len(v["view"][t]["periodic"]["ties"]) > 1)}


def validate_tie_mechanism(m: dict, v: dict, path: Path) -> dict:
    """Cross-check the geometric tie diagnostic against the manifest it claims to describe.

    The receipt is produced by `v61_tie_mechanism.py`, which reconstructs HotSpot's g2bmap in
    Python. A reimplementation cannot be its own oracle, so everything the manifest can settle is
    settled here: the floorplan identity, the run identity, and every per-row bit-identity and
    steady gap, recomputed from the temperature vectors. What is left to the receipt is the
    geometry.
    """
    if not path.is_file():
        return {}
    r = json.loads(path.read_text(encoding="utf-8"))
    require(get(r, "floorplan_sha256", "tie receipt") == m["input_hashes"]["floorplan"],
            "the tie diagnostic describes a different floorplan than this manifest")
    require(get(r, "run_id", "tie receipt") == m["run"]["run_id"],
            "the tie diagnostic describes a different run than this manifest")
    require(set(get(r, "rows", "tie receipt")) == set(v["rows"]),
            "the tie diagnostic covers a different row set")
    counts = get(r, "mechanism_counts", "tie receipt")
    require(sum(counts.values()) == len(v["rows"]),
            f"the tie diagnostic classifies {sum(counts.values())} rows, not {len(v['rows'])}")
    for tag, row in sorted(r["rows"].items()):
        w = f"tie receipt row `{tag}`"
        steady = m["rows"][tag]["mean_steady_block_k"]
        order = sorted(range(len(steady)), key=lambda i: (-steady[i], i))
        top = [v["block_ids"][order[0]], v["block_ids"][order[1]]]
        require(get(row, "top_two", w) == top,
                f"{w}: names {row['top_two']}, but the vectors give {top}")
        identical = steady[order[0]] == steady[order[1]]
        require(get(row, "bit_identical", w) is identical,
                f"{w}: claims bit_identical={row['bit_identical']}, vectors give {identical}")
        require(abs(get(row, "steady_gap_k", w)
                    - (steady[order[0]] - steady[order[1]])) < 1e-15,
                f"{w}: the recorded steady gap disagrees with the vectors")
        shared = get(row, "shared_cells", w)
        if identical:
            require(shared > 0,
                    f"{w}: bit-identical from disjoint cell rectangles is impossible under a "
                    f"`max` mapping that copies a cell value")
        if row.get("mechanism") == "symmetric":
            require(shared == 0 and not identical,
                    f"{w}: a symmetry explanation requires disjoint rectangles and a nonzero gap")
    return r


def build(m: dict) -> tuple:
    ident = validate_identity(m)
    v = validate_rows(m)
    v.update(ident)
    return v, validate_gate(m, v), validate_execution(m, v)


def build_with_mechanism(m: dict, manifest_path: Path) -> tuple:
    """`build`, plus the tie diagnostic if a receipt sits beside the manifest."""
    v, g, ex = build(m)
    ex["tie_mechanism"] = validate_tie_mechanism(
        m, v, Path(manifest_path).parent / "tie_mechanism.json")
    return v, g, ex
