"""Reporting contracts for the consolidated overview (pilot_002 pre-run
wave, block E).

Everything a report must distinguish, as pure functions over the overview
rows and the run artifacts - no live-config reads, no LLM calls:

  * effective_config      the run MANIFEST is the source of truth over the
                          live config.yaml; without a manifest the report
                          says LEGACY_FALLBACK_LIVE_CONFIG explicitly
  * accepted semantic disclosures (dense_la/00 BL-01) rendered from
                          semantic_decisions_pilot002.json: per-benchmark
                          block + marker on every aggregate section that
                          includes the benchmark; no auto-exclusion; no
                          causal claim
  * static analysis coverage: CLEAN / DEFECT_FOUND / PARTIAL /
                          NOT_ANALYZED / TOOL_ERROR / TIMEOUT / NOT_APPLICABLE
                          per tool, LLOV classes and PARCOACH low-confidence
                          findings visible
  * repair final statuses separated into model outcomes and
                          infrastructure states (not model failures)
  * cross-pilot comparability consumed from cross_pilot_comparability.json
                          (no global "pilot_001 improved by X%")
  * timing semantics block from the timing contract
  * report provenance block + content-addressed report_condition_sha256

Python 3.8 compatible.
"""
from __future__ import annotations

import copy
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import condition_hashing as ch  # noqa: E402

REPORT_CONTRACT_VERSION = "report_contract.v1"
SEMANTIC_DECISIONS_PATH = REPO_ROOT / "thesis" / "evaluation" / "semantic_decisions_pilot002.json"
CROSS_PILOT_PATH = REPO_ROOT / "thesis" / "evaluation" / "cross_pilot_comparability.json"

CONFIG_SOURCE_MANIFEST = "MANIFEST"
CONFIG_SOURCE_LEGACY = "LEGACY_FALLBACK_LIVE_CONFIG"
UNKNOWN = "UNKNOWN"

# repair final statuses: model outcomes vs infrastructure states
REPAIR_MODEL_OUTCOME_STATUSES = ("stopped_clean", "stopped_tests_pass", "stopped_budget",
                                 "repair_unusable", "stopped_baseline_incompatible")
REPAIR_INFRASTRUCTURE_STATUSES = ("stopped_analysis_incomplete", "stopped_api_exhausted")

STATIC_GAP_STATES = ("PARTIAL", "NOT_ANALYZED", "TOOL_ERROR", "TIMEOUT")
STATIC_VERDICT_ORDER = ("CLEAN", "DEFECT_FOUND", "PARTIAL", "NOT_ANALYZED", "TOOL_ERROR",
                        "TIMEOUT", "NOT_APPLICABLE", "NO_RECORD")

# Sections that are contract/provenance blocks rather than result aggregates.
# Everything else - INCLUDING the static-coverage and repair-status tables,
# which do aggregate over the disclosure-bearing benchmark - is marked.
NON_AGGREGATE_SECTION_PREFIXES = ("## Accepted semantic disclosures",
                                  "## Report provenance", "## Effective config snapshot",
                                  "## Cross-pilot comparability", "## Timing semantics")


def load_json(path: Path) -> "Optional[Dict[str, Any]]":
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# manifest over live config
# ---------------------------------------------------------------------------

def effective_config(config: Dict[str, Any], manifest: "Optional[Dict[str, Any]]"
                     ) -> "Tuple[Dict[str, Any], str]":
    """The configuration the run ACTUALLY ran under: the manifest's frozen
    resolved_config wins for `stages` and `models`; the live config only
    contributes paths (`outputs`) and anything the manifest lacks."""
    live = copy.deepcopy(config)
    frozen = (manifest or {}).get("resolved_config") if manifest else None
    if not frozen:
        return live, CONFIG_SOURCE_LEGACY
    merged = copy.deepcopy(live)
    for key, value in frozen.items():
        if key == "outputs":
            continue
        merged[key] = copy.deepcopy(value)
    return merged, CONFIG_SOURCE_MANIFEST


def effective_models(config: Dict[str, Any], model_filter: "Optional[str]" = None
                     ) -> "List[Dict[str, Any]]":
    return [m for m in config.get("models", [])
            if m.get("enabled", False) and (model_filter is None or m.get("id") == model_filter)]


def stage_timeouts(config: Dict[str, Any]) -> "OrderedDict[str, Any]":
    stages = config.get("stages") or {}
    return OrderedDict([
        ("correctness_run_timeout_seconds", (stages.get("correctness_tests") or {}).get("run_timeout_seconds")),
        ("enhanced_run_timeout_seconds", (stages.get("enhanced_tests") or {}).get("run_timeout_seconds")),
        ("generation_timeout_seconds", (config.get("generation_defaults") or {}).get("timeout_seconds")),
    ])


# ---------------------------------------------------------------------------
# accepted semantic disclosures
# ---------------------------------------------------------------------------

def decisions_artifact_state(decisions: "Optional[Dict[str, Any]]" = None) -> str:
    """PRESENT / MISSING / UNREADABLE / MALFORMED - a report must never state
    "no disclosure is registered" when it simply could not read the artifact."""
    if decisions is not None:
        return "PRESENT" if isinstance(decisions.get("decisions"), list) else "MALFORMED"
    path = Path(SEMANTIC_DECISIONS_PATH)
    if not path.is_file():
        return "MISSING"
    loaded = load_json(path)
    if loaded is None:
        return "UNREADABLE"
    if not isinstance(loaded.get("decisions"), list):
        return "MALFORMED"
    return "PRESENT"


def disclosure_decisions(decisions: "Optional[Dict[str, Any]]" = None) -> "List[Dict[str, Any]]":
    """Every decision whose status is an ACCEPTED DISCLOSURE, with its
    reporting requirement (the artifact is the source of the wording)."""
    if decisions is None:
        decisions = load_json(SEMANTIC_DECISIONS_PATH) or {}
    result = []
    for entry in decisions.get("decisions") or []:
        status = str(entry.get("status") or "")
        if not status.startswith("ACCEPTED_DISCLOSURE"):
            continue
        result.append(OrderedDict([
            ("benchmark", entry.get("benchmark")),
            ("decision_ids", list(entry.get("decision_ids") or [])),
            ("status", status),
            ("prompt_changed", entry.get("prompt_changed")),
            ("oracle_changed", entry.get("oracle_changed")),
            ("reporting_requirement", entry.get("reporting_requirement") or {}),
        ]))
    return result


def benchmark_key(row: Dict[str, Any]) -> str:
    return "%s/%s" % (row.get("problem_type"), row.get("benchmark"))


def disclosures_in_rows(rows: "List[Dict[str, Any]]",
                        disclosures: "List[Dict[str, Any]]") -> "List[Dict[str, Any]]":
    present = {benchmark_key(r) for r in rows}
    return [d for d in disclosures if d["benchmark"] in present]


def disclosure_marker(rows: "List[Dict[str, Any]]",
                      disclosures: "List[Dict[str, Any]]",
                      artifact_state: "Optional[str]" = None) -> "Optional[str]":
    state = artifact_state or decisions_artifact_state()
    if state != "PRESENT":
        # unreadable artifact: an UNMARKED aggregate must not read as "no
        # disclosure applies"
        return ("_Disclosure status UNKNOWN: the semantic decision artifact is %s, so it "
                "is unverified whether this aggregate contains disclosure-bearing "
                "benchmarks._" % state)
    hits = disclosures_in_rows(rows, disclosures)
    if not hits:
        return None
    names = ", ".join("%s (%s)" % (d["benchmark"], "/".join(d["decision_ids"])) for d in hits)
    return ("_Includes accepted-disclosure benchmark(s): %s - the benchmark is NOT "
            "excluded; see 'Accepted semantic disclosures'._" % names)


def disclosure_section(rows: "List[Dict[str, Any]]",
                       disclosures: "List[Dict[str, Any]]",
                       artifact_state: "Optional[str]" = None) -> "List[str]":
    lines: "List[str]" = []
    state = artifact_state or decisions_artifact_state()
    if state != "PRESENT":
        lines.append("**SEMANTIC_DISCLOSURE_RENDERING = UNKNOWN** - the semantic decision "
                     "artifact (%s) is %s, so this report cannot state whether accepted "
                     "disclosures exist. Every aggregate below is therefore UNVERIFIED "
                     "with respect to disclosure-bearing benchmarks; do not read the "
                     "absence of markers as their absence."
                     % (ch.repo_relative(SEMANTIC_DECISIONS_PATH), state))
        return lines
    if not disclosures:
        lines.append("No accepted-disclosure decision is registered in the semantic "
                     "decision artifact (artifact read successfully, 0 accepted "
                     "disclosures).")
        return lines
    present = disclosures_in_rows(rows, disclosures)
    absent = [d for d in disclosures if d not in present]
    lines.append("Rendered automatically from semantic_decisions_pilot002.json. An accepted "
                 "disclosure is a METHODOLOGICAL LIMITATION attached to a benchmark's "
                 "results: the benchmark runs, verdicts are unchanged, no sample is "
                 "excluded, and every aggregate that contains it is marked.")
    for d in present:
        req = d["reporting_requirement"] or {}
        ids = "/".join(d["decision_ids"])
        base_rows = [r for r in rows if benchmark_key(r) == d["benchmark"] and r.get("iteration") == 0]
        # unique samples, not rows: one sample appears once per repair variant
        per_exec = Counter(dict((r["sample_id"], r.get("execution_model")) for r in base_rows).values())
        lines.append("")
        lines.append("### %s - decision %s" % (d["benchmark"], ids))
        lines.append("")
        lines.append("- Status: %s (accepted disclosure; prompt changed: %s; oracle changed: %s)."
                     % (d["status"], _yesno(d["prompt_changed"]), _yesno(d["oracle_changed"])))
        lines.append("- Methodological limitation: results for this benchmark may be sensitive "
                     "to the accepted LU tolerance/rounding convention (%s)."
                     % (req.get("short_hint") or "see decision artifact"))
        if req.get("affected_results"):
            lines.append("- Affected results:")
            for item in req["affected_results"]:
                lines.append("  - %s" % item)
        if req.get("not_affected"):
            lines.append("- Not affected:")
            for item in req["not_affected"]:
                lines.append("  - %s" % item)
        if req.get("enhanced_reporting_note"):
            lines.append("- Enhanced reporting note: %s" % req["enhanced_reporting_note"])
        lines.append("- Samples of this benchmark in this run (base population): %d%s."
                     % (len({r["sample_id"] for r in base_rows}),
                        (" (" + ", ".join("%s %d" % (k, v) for k, v in sorted(per_exec.items())) + ")")
                        if per_exec else ""))
        lines.append("- This disclosure states a limitation only. It does not claim that any "
                     "observed result of this benchmark was caused by the convention, and it "
                     "does not remove the benchmark from any aggregate.")
    for d in absent:
        lines.append("")
        lines.append("- %s (%s): registered disclosure, benchmark not in this run's rows."
                     % (d["benchmark"], "/".join(d["decision_ids"])))
    return lines


def _yesno(value: Any) -> str:
    if value is None:
        return UNKNOWN
    return "yes" if value else "no"


def mark_aggregate_sections(parts: "List[str]", marker: "Optional[str]") -> "List[str]":
    """Insert the disclosure marker under every '## ' aggregate header."""
    if not marker:
        return parts
    out: "List[str]" = []
    for part in parts:
        out.append(part)
        if part.startswith("## ") and not part.startswith(NON_AGGREGATE_SECTION_PREFIXES):
            out.append("")
            out.append(marker)
    return out


# ---------------------------------------------------------------------------
# static analysis coverage
# ---------------------------------------------------------------------------

def static_verdict(row: Dict[str, Any], tool: str) -> str:
    state = row.get("%s_analysis_state" % tool)
    if state is None:
        return "NO_RECORD"
    if state == "COMPLETED":
        blocking = row.get("%s_blocking" % tool)
        return "DEFECT_FOUND" if isinstance(blocking, (int, float)) and blocking > 0 else "CLEAN"
    return str(state)


def static_coverage_section(rows: "List[Dict[str, Any]]", tools: "List[str]",
                            summaries: "Optional[Dict[str, Dict[str, Any]]]" = None) -> "List[str]":
    """Per-tool verdict/state table over the base population (iteration 0
    rows) plus LLOV classes and PARCOACH low-confidence counts."""
    base_rows = [r for r in rows if r.get("iteration") == 0 and r.get("variant")]
    seen = set()
    unique_rows = []
    for r in base_rows:
        key = (r.get("model"), r.get("sample_id"))
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(r)
    lines = ["Tool states follow tool_state.v1: COMPLETED splits into CLEAN / DEFECT_FOUND "
             "(a verdict); PARTIAL, NOT_ANALYZED, TOOL_ERROR and TIMEOUT are COVERAGE "
             "LIMITATIONS (the invocation completed, the sample has no trustworthy verdict "
             "from that tool); NOT_APPLICABLE is scoping. Legacy pilot_001 records are "
             "re-derived by framework.effective_tool_state.", "",
             "| tool | " + " | ".join(STATIC_VERDICT_ORDER) + " | gap rows |",
             "|---|" + "---|" * (len(STATIC_VERDICT_ORDER) + 1)]
    any_gap_rows = 0
    for tool in tools:
        counts = Counter(static_verdict(r, tool) for r in unique_rows)
        gaps = sum(counts[s] for s in STATIC_GAP_STATES)
        lines.append("| %s | %s | %d |" % (tool, " | ".join(str(counts[s]) for s in STATIC_VERDICT_ORDER), gaps))
    for r in unique_rows:
        if any(static_verdict(r, t) in STATIC_GAP_STATES for t in tools):
            any_gap_rows += 1
    lines.append("")
    lines.append("Base samples with at least one coverage limitation: %d of %d "
                 "(reported as coverage, never as a clean verdict)." % (any_gap_rows, len(unique_rows)))
    # low_confidence_count is a PER-ROW total over all static+dynamic tools
    # (build_overview), not a PARCOACH counter: report it as what it is
    low_conf = sum(int(r.get("low_confidence_count") or 0) for r in unique_rows
                   if isinstance(r.get("low_confidence_count"), (int, float)))
    parcoach_rows = sum(1 for r in unique_rows
                        if static_verdict(r, "parcoach") == "DEFECT_FOUND") if "parcoach" in tools else 0
    lines.append("Low-confidence findings over all analysis tools (visible, counted inside "
                 "the blocking counts by the redundancy rule; PARCOACH's low-precision "
                 "warnings are the dominant source but this total is NOT attributed to a "
                 "single tool): %d over the base population%s."
                 % (low_conf,
                    "; samples with a PARCOACH defect verdict: %d" % parcoach_rows
                    if "parcoach" in tools else ""))
    if summaries:
        for model_id, summary in sorted(summaries.items()):
            classes = (summary or {}).get("llov_classes")
            if classes:
                lines.append("")
                lines.append("LLOV classes (%s): %s" % (
                    model_id, ", ".join("%s=%s" % (k, v) for k, v in sorted(classes.items()))))
    return lines


# ---------------------------------------------------------------------------
# repair final statuses
# ---------------------------------------------------------------------------

def repair_status_class(status: "Optional[str]") -> str:
    if status in REPAIR_INFRASTRUCTURE_STATUSES:
        return "INFRASTRUCTURE_STATE (not a model failure)"
    if status in REPAIR_MODEL_OUTCOME_STATUSES:
        return "MODEL_OUTCOME"
    return "OTHER"


def repair_status_section(rows: "List[Dict[str, Any]]") -> "List[str]":
    final: Dict[Tuple[Any, Any, Any], Dict[str, Any]] = {}
    for r in rows:
        key = (r.get("model"), r.get("variant"), r.get("sample_id"))
        if key not in final or (r.get("iteration") or 0) >= (final[key].get("iteration") or 0):
            final[key] = r
    lines = ["Final status per (model, variant, sample). stopped_analysis_incomplete and "
             "stopped_api_exhausted are INFRASTRUCTURE states: the loop stopped because "
             "analysis coverage or transport rounds ran out, which says nothing about the "
             "model; they are never counted as clean, as tests-pass or as a model failure.",
             "", "| variant | final status | class | samples |", "|---|---|---|---|"]
    counts: Counter = Counter()
    for (_model, variant, _sample), r in final.items():
        counts[(variant, r.get("status"))] += 1
    for (variant, status), n in sorted(counts.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        lines.append("| %s | %s | %s | %d |" % (variant, status, repair_status_class(status), n))
    return lines


# ---------------------------------------------------------------------------
# cross-pilot comparability (consumed, never re-derived)
# ---------------------------------------------------------------------------

def cross_pilot_section(artifact: "Optional[Dict[str, Any]]") -> "List[str]":
    if not artifact:
        return ["cross_pilot_comparability.json not found - cross-pilot comparability UNKNOWN; "
                "no cross-pilot statement is made."]
    reeval = artifact.get("cross_pilot_reevaluation") or {}
    lines = [
        "Consumed from cross_pilot_comparability.json (fingerprint %s..., state commit %s). "
        "Comparability is per cell (benchmark x execution model x stage), never global: "
        "no 'pilot_001 improved by X%%' statement is derivable from this artifact."
        % (str(artifact.get("cross_pilot_fingerprint_sha256") or UNKNOWN)[:12],
           str(artifact.get("state_commit") or UNKNOWN)[:12]),
        "",
        "- Classification: %s" % artifact.get("classification", UNKNOWN),
        "- Reuse status: %s (a reuse decision is NOT made by this report)" % artifact.get("reuse_status", UNKNOWN),
    ]
    subset = (artifact.get("candidate_subset") or {}).get("benchmarks")
    if subset:
        lines.append("- Candidate subset benchmarks: %s" % ", ".join(str(b) for b in subset))
    matrix = reeval.get("correctness_cell_matrix") or {}
    direct = matrix.get("directly_comparable_benchmarks")
    if direct is not None:
        lines.append("- Correctness: directly comparable benchmarks: %s"
                     % (", ".join(str(b) for b in direct) if direct else "none"))
    for item in matrix.get("mandatory_disclosures_for_the_directly_comparable_cells") or []:
        lines.append("  - mandatory disclosure: %s" % item)
    per_benchmark = matrix.get("per_benchmark") or []
    if per_benchmark:
        classes = Counter(str(p.get("class")) for p in per_benchmark)
        lines.append("- Correctness cell classes: %s"
                     % ", ".join("%s=%d" % (k, v) for k, v in sorted(classes.items())))
    enhanced = reeval.get("enhanced") or {}
    if enhanced.get("overlap_totals"):
        lines.append("- Enhanced overlap totals: %s" % json.dumps(enhanced["overlap_totals"], sort_keys=True))
    areas = reeval.get("areas") or {}
    static_repair = areas.get("F_static_repair") or {}
    per_tool = _class_map(static_repair.get("per_tool"), "tool")
    if per_tool:
        lines.append("- Static/repair per tool: %s"
                     % ", ".join("%s=%s" % (name, klass) for name, klass in per_tool))
    repair = static_repair.get("repair")
    if isinstance(repair, dict):
        lines.append("- Repair comparability: %s" % (repair.get("class") or UNKNOWN))
    for caveat in artifact.get("statistical_caveats") or []:
        lines.append("- Statistical caveat: %s" % _flatten(caveat))
    return lines


def _class_map(value: Any, name_key: str) -> "List[Tuple[str, str]]":
    """Accept both artifact shapes: {name: {class: ...}} and [{<name_key>: ...,
    class: ...}]. Anything else yields nothing rather than raising - a report
    must never crash on an artifact shape it does not know."""
    result: "List[Tuple[str, str]]" = []
    if isinstance(value, dict):
        for name, entry in sorted(value.items()):
            klass = entry.get("class") if isinstance(entry, dict) else entry
            result.append((str(name), str(klass)))
    elif isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                result.append((str(entry.get(name_key)), str(entry.get("class"))))
    return result


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join("%s: %s" % (k, v) for k, v in sorted(value.items()))
    if isinstance(value, list):
        return "; ".join(_flatten(v) for v in value)
    return str(value)


# ---------------------------------------------------------------------------
# timing semantics block
# ---------------------------------------------------------------------------

def generation_timing_classes(config: Dict[str, Any], run_id: str,
                              model_ids: "List[str]") -> "OrderedDict[str, str]":
    from thesis.evaluation.check_timing_semantics import Checker, check_generation

    raw = Path(config["outputs"]["raw_dir"]) / run_id
    result: "OrderedDict[str, str]" = OrderedDict()
    for model_id in model_ids:
        checker = Checker({})
        result[model_id] = check_generation(checker, raw / model_id / "generations.jsonl")["class"]
    return result


def timing_section(effective: Dict[str, Any], config_source: str,
                   gen_classes: "Dict[str, str]") -> "List[str]":
    from thesis.evaluation import timing_semantics as ts

    timeouts = stage_timeouts(effective)
    contract = ts.timing_contract()
    statements = contract["global_statements"]
    all_direct = bool(gen_classes) and all(c == ts.DIRECT_LATENCY_AVAILABLE for c in gen_classes.values())
    lines = [
        "Timing contract %s (sha %s...). Limits come from the %s."
        % (contract["contract_version"], ts.timing_contract_sha256(contract)[:12],
           "run manifest" if config_source == CONFIG_SOURCE_MANIFEST
           else "LIVE config (LEGACY FALLBACK: no run manifest)"),
        "",
        "- Configured correctness run timeout: %s s; enhanced run timeout: %s s; "
        "generation client timeout: %s s; build limit: %s s (code default)."
        % (timeouts["correctness_run_timeout_seconds"], timeouts["enhanced_run_timeout_seconds"],
           timeouts["generation_timeout_seconds"], contract["constants"]["build_timeout_default_seconds"]),
        "- Timeouts store the OBSERVED elapsed plus a flag, never the limit.",
        "- Direct generation duration_seconds = end-to-end client latency including client/SDK "
        "retries and adapter overhead; batch records carry duration_seconds = null and only a "
        "job-level queue span (never latency).",
        "- Run seconds are NOT comparable across execution models (mpi includes the mpirun "
        "launcher and MPI init, omp the OpenMP runtime init, serial the process startup): "
        "RUN_SECONDS_CROSS_EXECUTION_MODEL_COMPARABLE = %s."
        % str(statements["RUN_SECONDS_CROSS_EXECUTION_MODEL_COMPARABLE"]).lower(),
        "- Static tool durations are analysis cost, not model speed.",
        "- Generation timing class per model: %s."
        % (", ".join("%s=%s" % (m, c) for m, c in gen_classes.items()) or "n/a"),
        "- CROSS_MODEL_LATENCY_RANKING = %s." % ("AVAILABLE (all models direct)" if all_direct
                                                else "NOT_AVAILABLE (mixed direct/batch or insufficient)"),
        "- Absolute runtime comparison with another pilot: NOT_COMPARABLE unless both runs' "
        "pinned runtime conditions (host/container/compiler/grid/niter) match.",
    ]
    return lines


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

def report_condition() -> "OrderedDict[str, Any]":
    """The reporting METHOD: LF-normalized implementation hashes + the
    timing contract + the semantic decision artifact. No timestamps, no
    hostnames, no absolute paths."""
    from thesis.evaluation import timing_semantics as ts

    here = Path(__file__).resolve().parent
    return OrderedDict([
        ("report_contract_version", REPORT_CONTRACT_VERSION),
        ("implementation", [
            ch.file_condition_entry(here / "build_overview.py"),
            ch.file_condition_entry(here / "report_contracts.py"),
            ch.file_condition_entry(REPO_ROOT / "thesis" / "evaluation" / "check_timing_semantics.py"),
        ]),
        ("timing_contract_sha256", ts.timing_contract_sha256()),
        ("semantic_decisions_sha256_lf_normalized", ch.lf_normalized_sha256(SEMANTIC_DECISIONS_PATH)),
    ])


def report_condition_sha256() -> str:
    return ch.canonical_sha256(report_condition())


def provenance_block(config: Dict[str, Any], base_run_id: str,
                     manifest: "Optional[Dict[str, Any]]", config_source: str,
                     model_ids: "List[str]") -> "OrderedDict[str, Any]":
    from thesis.evaluation.run_manifest import manifest_path

    m = manifest or {}
    path = manifest_path(config, base_run_id)
    cross = load_json(CROSS_PILOT_PATH) or {}
    decisions = load_json(SEMANTIC_DECISIONS_PATH) or {}
    enhanced_specs = m.get("enhanced_specs") or {}
    enhanced_policy = m.get("enhanced_policy") or {}
    enhanced_exec = m.get("enhanced_execution") or {}
    block = OrderedDict([
        ("schema_version", "report_provenance.v1"),
        ("run_id", base_run_id),
        ("config_source", config_source),
        ("manifest_architecture", m.get("manifest_architecture") or
         ("LEGACY_SHARED_MANIFEST" if manifest else "NONE")),
        ("manifest_sha256", ch.raw_sha256(path) or UNKNOWN),
        ("manifest_created_at_utc", m.get("created_at_utc") or UNKNOWN),
        ("manifest_git_commit", m.get("git_commit") or UNKNOWN),
        ("models", list(model_ids)),
        ("generation_condition_sha256", _gen_condition(config, m) or UNKNOWN),
        ("assembly_condition_sha256", m.get("assembly_condition_sha256") or UNKNOWN),
        ("assembly_model_sets", m.get("assembly_model_sets") or UNKNOWN),
        # what the RUN froze (manifest-sourced)
        ("frozen_correctness_stage_sha256", _frozen_correctness_stage_sha(m) or UNKNOWN),
        # what the CURRENT repository computes - a comparison value, not run
        # provenance (the run recorded no evaluation condition of its own)
        ("evaluation_condition_sha256_recomputed_now", _eval_condition(config, m) or UNKNOWN),
        ("enhanced_specs_sha256", enhanced_specs.get("sha256") or UNKNOWN),
        ("enhanced_policy_sha256", enhanced_policy.get("policy_sha256")
         or enhanced_policy.get("sha256") or UNKNOWN),
        ("enhanced_execution_fingerprint_sha256",
         enhanced_exec.get("enhanced_execution_fingerprint_sha256") or UNKNOWN),
        ("model_execution_fingerprints", m.get("model_execution_fingerprints") or UNKNOWN),
        ("static_analysis_condition_sha256", m.get("static_analysis_condition_sha256") or UNKNOWN),
        ("repair_condition_sha256", m.get("repair_condition_sha256") or UNKNOWN),
        ("runtime_evidence_sha256", m.get("runtime_evidence_sha256") or UNKNOWN),
        ("contract_sha256", m.get("contract_sha256") or UNKNOWN),
        ("semantic_decisions_sha256_lf_normalized",
         ch.lf_normalized_sha256(SEMANTIC_DECISIONS_PATH) or UNKNOWN),
        ("semantic_decisions_statuses", OrderedDict([
            ("resolved", decisions.get("resolved_count")),
            ("accepted_disclosure", decisions.get("disclosure_count")),
            ("unresolved", decisions.get("unresolved_count"))]) if decisions else UNKNOWN),
        ("cross_pilot_artifact_sha256", cross.get("cross_pilot_fingerprint_sha256") or UNKNOWN),
        ("report_condition_sha256", report_condition_sha256()),
        ("report_condition", report_condition()),
    ])
    return block


def _gen_condition(config: Dict[str, Any], manifest: Dict[str, Any]) -> "Optional[str]":
    """Generation condition of the FROZEN config (the gate's field
    definition applied to the manifest's resolved_config)."""
    frozen = manifest.get("resolved_config") or {}
    gd = frozen.get("generation_defaults")
    models = frozen.get("models")
    if gd is None or models is None:
        return None
    from thesis.evaluation.check_cross_pilot_gate import canon_sha256

    model_view = {}
    for x in models:
        model_view[x["id"]] = {k: x.get(k) for k in sorted(x.keys())
                               if k not in ("price_per_mtok_in", "price_per_mtok_out")}
    return canon_sha256({"generation_defaults": gd, "models": model_view})


def _eval_condition(config: Dict[str, Any], manifest: Dict[str, Any]) -> "Optional[str]":
    """The cross-pilot gate's evaluation condition (build flags, launch
    configs, timeouts, niter) recomputed from the CURRENT repository state -
    NOT a value the manifest recorded. It is reported under an explicitly
    named key (`evaluation_condition_sha256_recomputed_now`) so it can never
    be read as run provenance; what the RUN froze is
    `frozen_correctness_stage_sha256`."""
    try:
        from thesis.evaluation.check_cross_pilot_gate import canon_sha256, evaluation_condition_projection

        return canon_sha256(evaluation_condition_projection())
    except Exception:  # noqa: BLE001 - UNKNOWN is the honest answer
        return None


def _frozen_correctness_stage_sha(manifest: Dict[str, Any]) -> "Optional[str]":
    stage = ((manifest.get("resolved_config") or {}).get("stages") or {}).get("correctness_tests")
    if stage is None:
        return None
    return ch.canonical_sha256(stage)


def render_provenance(block: Dict[str, Any]) -> "List[str]":
    lines = ["Every value below is read from the run manifest or from a content-addressed "
             "artifact of the CURRENT repository; UNKNOWN means the run predates the field "
             "(legacy) or the artifact is missing - it is never guessed. Keys ending in "
             "`_recomputed_now` are computed from the current repository state, NOT from "
             "the run's own record: they are comparison values, not run provenance.", ""]
    for key, value in block.items():
        if key == "report_condition":
            continue
        if isinstance(value, dict):
            value = json.dumps(value, sort_keys=True)
        elif isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append("- %s: %s" % (key, value))
    return lines
