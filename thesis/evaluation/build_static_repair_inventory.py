#!/usr/bin/env python3
"""pilot_001 static/repair inventory under the tool-state model (read-only).

The pilot_001 records are the authoritative source: nothing is re-run, no
verdict is recomputed for the pilot itself. What this script adds is the
CLASSIFICATION of the persisted entries under tool_state.v1 (the legacy
derivation in framework.legacy_analysis_state plus the record-level
subsumption), a re-derivation of the LLOV verdict classes from the retained
raw output with the fixed parser (reported NEXT TO the stored findings,
never replacing them), the per-tool finding-set regression of the wave's
rule changes, and the per-tool / repair comparability statement for a
prospective pilot_002.

Writes thesis/evaluation/static_repair_pilot001_inventory.json and prints
a markdown summary (used verbatim in the readiness report).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import framework, tools  # noqa: E402
from thesis.evaluation.framework import (  # noqa: E402
    STATE_COMPLETED, STATE_NOT_ANALYZED, STATE_NOT_APPLICABLE, STATE_PARTIAL,
    STATE_TIMEOUT, STATE_TOOL_ERROR,
)

PILOT = "pilot_001"
RESULTS = REPO_ROOT / "thesis" / "results" / "intermediate"
OUT = REPO_ROOT / "thesis" / "evaluation" / "static_repair_pilot001_inventory.json"
STATIC_TOOLS = ("compiler", "gcc_analyzer", "clang_tidy", "cppcheck", "infer", "parcoach", "llov")
STATE_ORDER = (STATE_COMPLETED, STATE_PARTIAL, STATE_NOT_ANALYZED, STATE_TOOL_ERROR,
               STATE_TIMEOUT, STATE_NOT_APPLICABLE)


def read_jsonl(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(l) for l in handle if l.strip()]


def run_dirs():
    base = RESULTS / PILOT
    iters = sorted(p for p in RESULTS.glob(PILOT + "__*__iter*") if p.is_dir())
    return base, iters


def iter_meta(path: Path):
    m = re.match(r".*__(?P<variant>[a-z_]+)__iter(?P<iteration>\d+)$", path.name)
    return (m.group("variant"), int(m.group("iteration"))) if m else (None, None)


# ---------------------------------------------------------------------------
# static inventory
# ---------------------------------------------------------------------------

def classify_records(records):
    """per tool: raw legacy state counts, effective (record-level) counts,
    verdict categories, subsumed count"""
    raw = defaultdict(Counter)
    eff = defaultdict(Counter)
    verdict = defaultdict(Counter)
    subsumed = Counter()
    gap_records = 0
    clean_all_completed = 0
    for rec in records:
        record_gap = False
        all_completed = True
        blocking_any = False
        for name in STATIC_TOOLS:
            entry = (rec.get("tools") or {}).get(name)
            if entry is None:
                raw[name]["missing_entry"] += 1
                eff[name]["missing_entry"] += 1
                continue
            state = framework.analysis_state_of(entry)
            raw[name][state] += 1
            estate, reason = framework.effective_tool_state(rec, name)
            eff[name][estate] += 1
            if framework.is_subsumed_rejection(estate, reason):
                subsumed[name] += 1
            blocking = int(entry.get("num_blocking", 0) or 0)
            verdict[name][framework.tool_verdict(estate, blocking)] += 1
            if blocking:
                blocking_any = True
            if framework.record_analysis_gap(rec, name) is not None:
                record_gap = True
            if estate not in (STATE_COMPLETED, STATE_NOT_APPLICABLE):
                all_completed = False
        if record_gap:
            gap_records += 1
        if all_completed and not blocking_any:
            clean_all_completed += 1
    return raw, eff, verdict, subsumed, gap_records, clean_all_completed


def llov_rederivation(records):
    """stored findings vs the fixed parser over the retained raw output"""
    out = Counter()
    class_old = Counter()
    class_new = Counter()
    changed_samples = []
    for rec in records:
        entry = (rec.get("tools") or {}).get("llov")
        if not entry or not entry.get("ran"):
            continue
        raw = (entry.get("raw_stdout") or "") + "\n" + (entry.get("raw_stderr") or "")
        old = entry.get("findings") or []
        new = tools.findings_in_model_file(tools.parse_llov_output(raw), "generated-code.hpp")
        regions = tools.parse_llov_regions(raw)
        old_race = sum(1 for f in old if f.get("check_id") == "llov-data-race")
        new_race = sum(1 for f in new if f.check_id == "llov-data-race")
        out["records"] += 1
        out["stored_findings"] += len(old)
        out["rederived_findings"] += len(new)
        out["stored_race_findings"] += old_race
        out["rederived_race_findings"] += new_race
        if entry.get("exit_code") not in (0, None) or entry.get("error"):
            c_old = c_new = "error"
        else:
            c_old = "race" if old_race else ("not_analyzed_only" if any(
                f.get("check_id") == "llov-region-not-analyzed" for f in old) else "no_finding")
            if regions["race"]:
                c_new = "race"
            elif regions["not_analyzed"] and regions["free"]:
                c_new = "free_and_not_analyzed"
            elif regions["not_analyzed"]:
                c_new = "not_analyzed_only"
            elif regions["free"]:
                c_new = "race_free_only"
            else:
                c_new = "no_region_verdict"
        class_old[c_old] += 1
        class_new[c_new] += 1
        if old_race != new_race:
            changed_samples.append({"sample_id": rec.get("sample_id"), "model_id": rec.get("model_id"),
                                    "stored_race": old_race, "rederived_race": new_race})
    return out, class_old, class_new, changed_samples


def finding_set_regression(records):
    """Per tool: how the wave's RULE changes would touch the stored finding
    set (identities and blocking flags). Nothing is rewritten."""
    reg = OrderedDict()
    # compiler: synthetic compile-failed only for completed builds now
    c = Counter()
    for rec in records:
        e = (rec.get("tools") or {}).get("compiler")
        if not e:
            continue
        if e.get("exit_code") == -1:
            c["exit_minus_one_records"] += 1
        raw = e.get("raw_stderr") or ""
        if "internal compiler error" in raw or "Killed signal" in raw:
            c["toolchain_marker_records"] += 1
        if any(f.get("check_id") == "compile-failed" for f in e.get("findings") or []):
            c["synthetic_compile_failed_findings"] += 1
    reg["compiler"] = OrderedDict([
        ("parser_changed", False),
        ("blocking_rule_changed_for", "toolchain failures only (exit -1 without timeout, ICE, cc1plus fatal)"),
        ("records_affected", c["exit_minus_one_records"] + c["toolchain_marker_records"]),
        ("detail", dict(c)),
        ("FINDING_SET_CHANGED_BY_TOOL", c["exit_minus_one_records"] + c["toolchain_marker_records"] > 0),
    ])
    # gcc_analyzer: parser unchanged, path events attached at run time only
    g = Counter()
    for rec in records:
        e = (rec.get("tools") or {}).get("gcc_analyzer")
        if not e or not e.get("ran") or e.get("error"):
            continue
        raw = e.get("raw_stderr") or ""
        if len(raw) >= 8000:
            g["raw_capped_records"] += 1
            continue
        reparsed = [f for f in tools.parse_gcc_clang_diagnostics(raw, "gcc_analyzer")
                    if f.check_id.startswith(tools.ANALYZER_FLAG_PREFIX)]
        reparsed = tools.findings_in_model_file(reparsed, "generated-code.hpp")
        old = sorted((f.get("check_id"), f.get("line")) for f in e.get("findings") or [])
        new = sorted((f.check_id, f.line) for f in reparsed)
        g["uncapped_records"] += 1
        g["identical_reparse" if old == new else "different_reparse"] += 1
    reg["gcc_analyzer"] = OrderedDict([
        ("parser_changed", False),
        ("blocking_rule_changed_for", "nothing (state PARTIAL/TOOL_ERROR added; path events attached)"),
        ("reparse_check_on_uncapped_raw", dict(g)),
        ("FINDING_SET_CHANGED_BY_TOOL", g["different_reparse"] > 0),
    ])
    # clang_tidy: clang-diagnostic-error no longer blocking
    t = Counter()
    for rec in records:
        e = (rec.get("tools") or {}).get("clang_tidy")
        for f in (e or {}).get("findings") or []:
            if str(f.get("check_id", "")).startswith("clang-diagnostic-error") and f.get("blocking"):
                t["blocking_flag_flipped"] += 1
                t["records"] += 0
        if e and any(str(f.get("check_id", "")).startswith("clang-diagnostic-error") and f.get("blocking")
                     for f in e.get("findings") or []):
            t["records_with_flip"] += 1
            comp = (rec.get("tools") or {}).get("compiler") or {}
            if comp.get("exit_code") not in (0, None):
                t["records_with_flip_and_compiler_failed"] += 1
    reg["clang_tidy"] = OrderedDict([
        ("parser_changed", False),
        ("blocking_rule_changed_for", "clang-diagnostic-error (front-end rejection): blocking -> non-blocking, state TOOL_ERROR / NOT_ANALYZED"),
        ("detail", dict(t)),
        ("FINDING_SET_CHANGED_BY_TOOL", t["blocking_flag_flipped"] > 0),
        ("identities_changed", False),
    ])
    # cppcheck: tool-side ids no longer blocking (except genuine #error)
    p = Counter()
    for rec in records:
        e = (rec.get("tools") or {}).get("cppcheck")
        for f in (e or {}).get("findings") or []:
            cid = f.get("check_id")
            if cid in tools.CPPCHECK_TOOL_SIDE_IDS and f.get("blocking"):
                msg = (f.get("message") or "").lstrip()
                if cid == "preprocessorErrorDirective" and msg.startswith(("#error", "#warning")):
                    p["genuine_error_directive_kept_blocking"] += 1
                else:
                    p["blocking_flag_flipped:" + str(cid)] += 1
    reg["cppcheck"] = OrderedDict([
        ("parser_changed", False),
        ("blocking_rule_changed_for", "syntaxError / internalError / preprocessorErrorDirective (lexer) etc.: blocking -> non-blocking, state PARTIAL / NOT_ANALYZED"),
        ("detail", dict(p)),
        ("FINDING_SET_CHANGED_BY_TOOL", any(k.startswith("blocking_flag_flipped") for k in p)),
        ("identities_changed", False),
    ])
    # infer: unchanged parser and level filter
    i = Counter()
    for rec in records:
        e = (rec.get("tools") or {}).get("infer")
        if not e:
            continue
        if "Aborting translation of method" in (e.get("raw_stderr") or ""):
            i["frontend_abort_records"] += 1
            if e.get("findings"):
                i["frontend_abort_records_with_findings"] += 1
    reg["infer"] = OrderedDict([
        ("parser_changed", False),
        ("level_filter_changed", False),
        ("blocking_rule_changed_for", "nothing (state NOT_ANALYZED / PARTIAL on frontend abort)"),
        ("detail", dict(i)),
        ("FINDING_SET_CHANGED_BY_TOOL", False),
    ])
    # parcoach: parser unchanged; preamble is a METHOD change for coverage
    q = Counter()
    for rec in records:
        e = (rec.get("tools") or {}).get("parcoach")
        if not e or not e.get("ran"):
            continue
        if (e.get("error") or "").startswith("clang -emit-llvm failed"):
            q["reduced_tu_compile_failures"] += 1
            comp = (rec.get("tools") or {}).get("compiler") or {}
            if comp.get("exit_code") == 0:
                q["reduced_tu_failures_on_compiler_built_samples"] += 1
        elif "timed out" in (e.get("error") or ""):
            q["timeouts"] += 1
        elif e.get("exit_code") == 0:
            q["completed"] += 1
    reg["parcoach"] = OrderedDict([
        ("parser_changed", False),
        ("blocking_rule_changed_for", "nothing"),
        ("method_changed", "reduced TU now carries the cpu.cc system-include preamble (coverage fix)"),
        ("detail", dict(q)),
        ("FINDING_SET_CHANGED_BY_TOOL", "COVERAGE_ONLY: %d reduced-TU failures on compiler-built samples would be analyzed "
                                       "(measured: identical findings on already-analyzable samples)"
                                       % q["reduced_tu_failures_on_compiler_built_samples"]),
    ])
    return reg


def static_inventory(base_dir, iter_dirs):
    inv = OrderedDict()
    base_records = []
    for path in sorted(base_dir.glob("*/static_analysis.jsonl")):
        base_records += read_jsonl(path)
    raw, eff, verdict, subsumed, gap_records, clean_all = classify_records(base_records)
    inv["base"] = OrderedDict([
        ("records", len(base_records)),
        ("models", len({r.get("model_id") for r in base_records})),
        ("schema_versions", sorted({r.get("schema_version") for r in base_records if r.get("schema_version")})),
        ("raw_legacy_state_per_tool", {t: OrderedDict((s, raw[t][s]) for s in STATE_ORDER + ("missing_entry",) if raw[t][s]) for t in STATIC_TOOLS}),
        ("effective_state_per_tool", {t: OrderedDict((s, eff[t][s]) for s in STATE_ORDER + ("missing_entry",) if eff[t][s]) for t in STATIC_TOOLS}),
        ("verdict_per_tool", {t: dict(verdict[t]) for t in STATIC_TOOLS}),
        ("not_analyzed_subsumed_by_compiler", dict(subsumed)),
        ("records_with_analysis_gap", gap_records),
        ("records_all_applicable_tools_completed_and_clean", clean_all),
    ])
    llov_counts, c_old, c_new, changed = llov_rederivation(base_records)
    inv["base"]["llov_rederivation"] = OrderedDict([
        ("scope", "stored findings vs fixed parser over retained raw output (LLOV raw output never hit the 8000-char cap)"),
        ("counts", dict(llov_counts)),
        ("class_stored", dict(c_old)),
        ("class_rederived", dict(c_new)),
        ("samples_with_changed_race_count", changed),
    ])
    inv["base"]["finding_set_regression"] = finding_set_regression(base_records)

    per_iter = OrderedDict()
    all_iter_records = []
    for path in iter_dirs:
        variant, iteration = iter_meta(path)
        records = []
        for f in sorted(path.glob("*/static_analysis.jsonl")):
            records += read_jsonl(f)
        all_iter_records += records
        raw_i, eff_i, _v, subsumed_i, gap_i, clean_i = classify_records(records)
        per_iter[path.name] = OrderedDict([
            ("variant", variant), ("iteration", iteration), ("records", len(records)),
            ("effective_state_per_tool", {t: OrderedDict((s, eff_i[t][s]) for s in STATE_ORDER + ("missing_entry",) if eff_i[t][s]) for t in STATIC_TOOLS}),
            ("records_with_analysis_gap", gap_i),
            ("records_all_completed_and_clean", clean_i),
        ])
    inv["iterations"] = per_iter
    inv["iterations_total_records"] = len(all_iter_records)
    inv["iterations_finding_set_regression"] = finding_set_regression(all_iter_records)
    return inv, base_records, all_iter_records


# ---------------------------------------------------------------------------
# repair inventory
# ---------------------------------------------------------------------------

def repair_inventory(base_dir, iter_dirs, base_records, iter_records):
    inv = OrderedDict()
    by_sample_static = {}
    for rec in base_records:
        by_sample_static[(PILOT, rec.get("sample_id"), rec.get("model_id"))] = rec
    for path in iter_dirs:
        for rec in read_jsonl_all(path):
            by_sample_static[(path.name, rec.get("sample_id"), rec.get("model_id"))] = rec

    loops = OrderedDict()
    status_counter = defaultdict(Counter)
    final_status = defaultdict(Counter)
    clean_with_gap = defaultdict(Counter)
    grace_keys = Counter()
    schema = Counter()
    for state_path in sorted(base_dir.glob("*/repair/*/state.jsonl")):
        model_id = state_path.parents[2].name
        variant = state_path.parent.name
        rows = read_jsonl(state_path)
        latest = {}
        for row in rows:
            schema[row.get("schema_version")] += 1
            status_counter[variant][row.get("status")] += 1
            if row.get("low_confidence_keys"):
                grace_keys[len(row["low_confidence_keys"][0])] += 1
            latest[row["sample_id"]] = row
        wave = {}
        wave_path = state_path.parent / "wave_state.json"
        if wave_path.exists():
            wave = json.loads(wave_path.read_text(encoding="utf-8"))
        loops[(model_id, variant)] = {"records": len(rows), "phase": wave.get("phase"),
                                     "iteration": wave.get("iteration"),
                                     "repair_condition_sha256": wave.get("repair_condition_sha256")}
        for sample_id, row in latest.items():
            status = row.get("status")
            final_status[variant][status] += 1
            # a clean/tests-pass stop whose deciding static record carries a
            # gap of a required tool (under the tool-state model)
            if status in ("stopped_clean", "stopped_tests_pass"):
                iteration = int(row.get("iteration") or 0)
                run_name = PILOT if iteration == 0 else "%s__%s__iter%d" % (PILOT, variant, iteration)
                rec = by_sample_static.get((run_name, sample_id, model_id))
                if rec is None:
                    clean_with_gap[variant]["static_record_missing"] += 1
                    continue
                gaps = [framework.record_analysis_gap(rec, t) for t in STATIC_TOOLS]
                gaps = [g for g in gaps if g]
                if variant == "test_feedback":
                    gaps = [g for g in gaps if g["tool"] == "compiler"]
                if gaps:
                    clean_with_gap[variant]["would_be_stopped_analysis_incomplete"] += 1
                    for g in gaps:
                        clean_with_gap[variant]["gap:" + g["tool"] + ":" + g["analysis_state"]] += 1
                else:
                    clean_with_gap[variant]["clean_with_complete_coverage"] += 1
    inv["loops"] = len(loops)
    inv["loop_phases"] = dict(Counter(v["phase"] for v in loops.values()))
    inv["loops_with_repair_condition_sha256"] = sum(1 for v in loops.values() if v["repair_condition_sha256"])
    inv["state_schema_versions"] = dict(schema)
    inv["status_records_per_variant"] = {v: dict(c) for v, c in status_counter.items()}
    inv["final_status_per_variant"] = {v: dict(c) for v, c in final_status.items()}
    inv["low_confidence_key_arity"] = dict(grace_keys)
    inv["clean_stops_reassessed_under_tool_state"] = {v: dict(c) for v, c in clean_with_gap.items()}

    generations = Counter()
    raw_root = RESULTS.parent / "raw"
    for path in iter_dirs:
        # repair responses are RAW generation records: raw/<iter_run>/<model>/
        for gen in sorted((raw_root / path.name).glob("*/generations.jsonl")):
            generations["files"] += 1
            for rec in read_jsonl(gen):
                generations["records"] += 1
                st = rec.get("status") or {}
                if st.get("success"):
                    generations["success"] += 1
                else:
                    generations["error:" + str(st.get("error_type"))] += 1
                if (rec.get("api_response") or {}).get("truncated") or rec.get("truncated"):
                    generations["truncated"] += 1
        for failed in (raw_root / path.name).glob("*/failed_responses.jsonl"):
            generations["failed_response_history_files"] += 1
    for ledger in base_dir.glob("*/repair/*/request_rounds.json"):
        generations["retry_ledgers"] += 1
    inv["iteration_generations"] = dict(generations)
    inv["provider_retry_evidence"] = ("no failure record survives in pilot_001 (the orchestrator dropped "
                                      "non-terminal failures on every load); orchestrator-level resubmissions "
                                      "are therefore not reconstructible - HISTORICAL_PROVENANCE_LIMITATION")
    return inv


def read_jsonl_all(run_dir: Path):
    out = []
    for f in sorted(run_dir.glob("*/static_analysis.jsonl")):
        out += read_jsonl(f)
    return out


# ---------------------------------------------------------------------------
# comparability
# ---------------------------------------------------------------------------

def comparability(static_inv, repair_inv):
    base = static_inv["base"]
    eff = base["effective_state_per_tool"]

    def rows(tool):
        return eff.get(tool, {})

    comp = OrderedDict()
    comp["compiler"] = OrderedDict([
        ("class", "DIRECTLY_COMPARABLE"),
        ("reason", "same g++ 13.3.0 toolchain image, unchanged diagnostic parser and build flags; the only rule change "
                   "(toolchain failures never become synthetic model compile errors) affects 0 pilot_001 records"),
        ("pilot_001_completed", rows("compiler").get(STATE_COMPLETED, 0)),
    ])
    comp["gcc_analyzer"] = OrderedDict([
        ("class", "COMPARABLE_WITH_LIMITATIONS"),
        ("reason", "identical tool, flags and parser; the wave adds the coverage STATE (PARTIAL for bail-out / "
                   "too-complex) and path events. pilot_001 'no finding' results split into COMPLETED and PARTIAL "
                   "only through the re-derived legacy classification (raw stderr capped at 8000 chars: PARTIAL is a "
                   "lower bound); a pilot_002 comparison must be scoped to COMPLETED+DEFECT_FOUND vs CLEAN populations"),
        ("pilot_001_states", dict(rows("gcc_analyzer"))),
    ])
    comp["clang_tidy"] = OrderedDict([
        ("class", "COMPARABLE_WITH_LIMITATIONS"),
        ("reason", "same LLVM 18.1.3, same check set; clang-diagnostic-error changed from blocking model defect to "
                   "TOOL_ERROR / NOT_ANALYZED (subsumed). In pilot_001 every such finding sits in a compiler-failed "
                   "record, so no stop decision changes; blocking counts differ by exactly those findings"),
        ("pilot_001_states", dict(rows("clang_tidy"))),
    ])
    comp["cppcheck"] = OrderedDict([
        ("class", "COMPARABLE_WITH_LIMITATIONS"),
        ("reason", "same Cppcheck 2.13.0 and options; lexer/parser failures (preprocessorErrorDirective 'No pair', "
                   "syntaxError) are no longer blocking model defects; genuine #error directives stay blocking; "
                   "1 pilot_001 base finding affected (compiler-failed record)"),
        ("pilot_001_states", dict(rows("cppcheck"))),
    ])
    comp["infer"] = OrderedDict([
        ("class", "METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE for omp; COMPARABLE_WITH_LIMITATIONS for serial/mpi"),
        ("reason", "same Infer 1.1.0 and level filter; but every pilot_001 OpenMP kernel was dropped by infer's clang-11 "
                   "frontend ('Aborting translation of method') and recorded as a clean COMPLETED run. Under the "
                   "tool-state model those 130 verdicts are NOT_ANALYZED; there is no OMP infer verdict to compare"),
        ("pilot_001_states", dict(rows("infer"))),
    ])
    comp["parcoach"] = OrderedDict([
        ("class", "METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE"),
        ("reason", "reduced TU now includes the cpu.cc system-include preamble (22 pilot_001 base entries were "
                   "compile failures on g++-buildable code); container identity for pilot_001 is TAG_ONLY "
                   "(parcoach-demo:2.4.1, no digest recorded); precision stays low-confidence (MBI 0.506, unchanged)"),
        ("pilot_001_states", dict(rows("parcoach"))),
    ])
    comp["llov"] = OrderedDict([
        ("class", "METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE"),
        ("reason", "parser fix ('Directive Not Analyzed', line:col locations) changes the stored verdict classes of "
                   "pilot_001 (re-derived next to the stored ones, never replacing them) and the reduced TU gained "
                   "the preamble; pilot_001 image identity TAG_ONLY (pareval-llov, clang 7.1.0 recorded)"),
        ("pilot_001_states", dict(rows("llov"))),
        ("llov_rederivation", base["llov_rederivation"]["class_rederived"]),
    ])
    repair = OrderedDict([
        ("class", "METHOD_CHANGED_NOT_DIRECTLY_COMPARABLE"),
        ("reason", "stop semantics changed: a required tool without a complete verdict now yields "
                   "stopped_analysis_incomplete instead of stopped_clean; grace_once identity widened to "
                   "(tool, check_id, file, line); orchestrator retry rounds bounded; repair condition pinned. "
                   "pilot_001 loops carry no repair_condition_sha256 (HISTORICAL_PROVENANCE_INSUFFICIENT for the "
                   "policy identity) and their clean stops are re-assessed above"),
        ("pilot_001_final_status", repair_inv["final_status_per_variant"]),
        ("clean_stops_reassessed_under_tool_state", repair_inv["clean_stops_reassessed_under_tool_state"]),
    ])
    return comp, repair


def markdown(static_inv, repair_inv, comp, repair_comp):
    lines = []
    base = static_inv["base"]
    lines.append("### pilot_001 static inventory (base run, %d records)" % base["records"])
    lines.append("")
    lines.append("| tool | " + " | ".join(STATE_ORDER) + " | missing |")
    lines.append("|---|" + "---|" * (len(STATE_ORDER) + 1))
    for t in STATIC_TOOLS:
        e = base["effective_state_per_tool"][t]
        lines.append("| %s | " % t + " | ".join(str(e.get(s, 0)) for s in STATE_ORDER) + " | %d |" % e.get("missing_entry", 0))
    lines.append("")
    lines.append("subsumed by the compiler's build failure (counted under NOT_ANALYZED): %s" % json.dumps(base["not_analyzed_subsumed_by_compiler"]))
    lines.append("records with an analysis gap of at least one required tool: %d; records with every applicable tool COMPLETED and clean: %d"
                 % (base["records_with_analysis_gap"], base["records_all_applicable_tools_completed_and_clean"]))
    lines.append("")
    lines.append("LLOV re-derivation (stored vs fixed parser): %s" % json.dumps(base["llov_rederivation"]["counts"]))
    lines.append("LLOV classes stored: %s" % json.dumps(base["llov_rederivation"]["class_stored"]))
    lines.append("LLOV classes re-derived: %s" % json.dumps(base["llov_rederivation"]["class_rederived"]))
    lines.append("")
    lines.append("### finding-set regression (base run)")
    lines.append("")
    lines.append("| tool | FINDING_SET_CHANGED_BY_TOOL | detail |")
    lines.append("|---|---|---|")
    for t, r in base["finding_set_regression"].items():
        lines.append("| %s | %s | %s |" % (t, r["FINDING_SET_CHANGED_BY_TOOL"], json.dumps(r.get("detail") or r.get("reparse_check_on_uncapped_raw") or {})))
    lines.append("")
    lines.append("### pilot_001 repair inventory")
    lines.append("")
    lines.append("loops: %d, phases: %s, state schemas: %s, grace key arity: %s" % (
        repair_inv["loops"], json.dumps(repair_inv["loop_phases"]), json.dumps(repair_inv["state_schema_versions"]),
        json.dumps(repair_inv["low_confidence_key_arity"])))
    lines.append("final status per variant: %s" % json.dumps(repair_inv["final_status_per_variant"]))
    lines.append("clean stops re-assessed under the tool-state model: %s" % json.dumps(repair_inv["clean_stops_reassessed_under_tool_state"]))
    lines.append("iteration generations: %s" % json.dumps(repair_inv["iteration_generations"]))
    lines.append("")
    lines.append("### per-tool comparability (pilot_001 vs prospective pilot_002)")
    lines.append("")
    lines.append("| tool | class |")
    lines.append("|---|---|")
    for t, c in comp.items():
        lines.append("| %s | %s |" % (t, c["class"]))
    lines.append("| repair loop | %s |" % repair_comp["class"])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    base_dir, iter_dirs = run_dirs()
    static_inv, base_records, iter_records = static_inventory(base_dir, iter_dirs)
    repair_inv = repair_inventory(base_dir, iter_dirs, base_records, iter_records)
    comp, repair_comp = comparability(static_inv, repair_inv)

    artifact = OrderedDict([
        ("schema_version", "static_repair_pilot001_inventory.v1"),
        ("pilot", PILOT),
        ("source_of_truth", "thesis/results/intermediate/pilot_001 (records read only; nothing re-run)"),
        ("tool_state_schema", framework.TOOL_STATE_SCHEMA_VERSION),
        ("static", static_inv),
        ("repair", repair_inv),
        ("comparability_per_tool", comp),
        ("comparability_repair", repair_comp),
        ("historical_provenance_limitations", [
            "no static_analysis_condition_sha256 / repair_condition_sha256 in any pilot_001 manifest or wave state (fields did not exist): RECONSTRUCTED from the pilot commit where possible, otherwise HISTORICAL_PROVENANCE_INSUFFICIENT",
            "no per-tool execution fingerprints, no sample_source_sha256, no per-tool timestamps in pilot_001 records",
            "external container identity TAG_ONLY (no image digest) for parcoach-demo:2.4.1 and pareval-llov",
            "gcc_analyzer raw_stderr capped at 8000 chars: PARTIAL re-derivation is a lower bound",
            "non-terminal provider failures were dropped on load: orchestrator-level retry counts are not reconstructible",
        ]),
    ])
    Path(args.out).write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(markdown(static_inv, repair_inv, comp, repair_comp))
    print("\nartifact written to", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
