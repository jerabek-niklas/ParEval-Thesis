"""Static-analysis stage runner.

Runs every configured tool over every assembled sample and writes one
record per sample to static_analysis.jsonl, plus a per-model summary.

Usage:
    python thesis/evaluation/run_static_analysis.py \
        --config thesis/config/config.yaml --profile smoke
    python thesis/evaluation/run_static_analysis.py \
        --config thesis/config/config.yaml --profile smoke --model-id claude_fable_5
    # restrict to specific tools (otherwise uses stages.static_analysis.tools):
    python thesis/evaluation/run_static_analysis.py ... --tools compiler cppcheck

The runner is tool-agnostic: it asks the registry for each configured tool.
ENVIRONMENT GATE (2026-08-08): if ALL requested tools are unavailable the
run ABORTS before writing any record — that is with near certainty an
environment error (wrong host/container), and the old skip-with-a-warning
behavior once produced a complete host run of empty records. INDIVIDUAL
unavailable tools remain a warning (legitimate under the parcoach/llov
container split) and are persisted per invocation in the summary artifact
(static_analysis_summary.json), so the gap is documented in the artifacts,
not just in the terminal.

TOOL-STATE WAVE (cross-container merge safety, static_analysis.v3):
  * every record pins `sample_source_sha256` (the candidate bytes analysed);
    a later invocation on the same sample_id with different bytes is REFUSED
    (thesis/evaluation/static_provenance.check_merge) - tool entries of two
    candidate versions are never mixed;
  * every tool entry carries `tool_execution_fingerprint_sha256` +
    `tool_execution_condition` (implementation hash, settings, options,
    build config, TU strategy, measured tool identity, source hash). The same
    tool under a DIFFERENT condition is refused unless
    --replace-tool-entries <tool> is given explicitly; the same tool under
    the SAME condition is idempotent (kept, not re-run) - a persisted
    TIMEOUT / TOOL_ERROR is terminal for automatic resume and only re-runs
    with --rerun-gaps. Different tools from their own containers merge
    freely: fingerprints are per tool;
  * the summary is derived from the MERGED records, never from the current
    invocation alone: per expected tool - applicable / completed / partial /
    not-analyzed / errored / timed-out / missing sample counts, findings,
    blocking, low-confidence - plus an append-only invocation history
    (tools requested / run / skipped per invocation). Container order does
    not change the canonical summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.evaluation import framework  # noqa: E402
from thesis.evaluation import static_provenance as provenance  # noqa: E402
from thesis.evaluation.framework import (  # noqa: E402
    ANALYSIS_GAP_STATES,
    STATE_COMPLETED,
    STATE_NOT_ANALYZED,
    STATE_NOT_APPLICABLE,
    STATE_PARTIAL,
    STATE_TIMEOUT,
    STATE_TOOL_ERROR,
    TOOL_STATE_SCHEMA_VERSION,
    analysis_state_of,
    entry_is_clean,
)
from thesis.evaluation.tool_config import (  # noqa: E402
    ToolSettings,
    mark_low_confidence,
    resolve_tool_settings,
)
from thesis.evaluation.tools import register_default_tools  # noqa: E402

# v3: v2 plus the tool-state wave fields - per record `sample_source_sha256`,
# per tool entry `analysis_state` / `analysis_complete` /
# `analysis_gap_reason` / `tool_verdict` / `analysis_details` /
# `tool_execution_fingerprint_sha256` / `tool_execution_condition`. All
# additive; v2 records stay readable (framework.analysis_state_of derives the
# legacy state), so consumers use the accessors, never the raw fields.
STATIC_ANALYSIS_SCHEMA_VERSION = "static_analysis.v3"
# v3 (Static/Repair.1): the invocation history renames `legacy_records_pinned`
# to `pre_existing_records_pinned` (its meaning changed: a pre-existing record
# WITHOUT tool results is now the only unpinned record a normal invocation may
# initialize) and adds `legacy_records_fully_replaced` / `replace_legacy_record`.
# An explicit bump - the field's semantics must never change silently.
STATIC_SUMMARY_SCHEMA_VERSION = "static_analysis_summary.v3"

# Container toolchain manifest (written at image build time). Phase-2
# backfill compares its container against the phase-1 record
# (repair-loop-design.md §6), so the first phase-1 invocation drops a copy
# next to the run's artifacts.
TOOLCHAIN_VERSIONS_FILE = Path("/opt/toolchain-versions.txt")


def record_toolchain_versions(intermediate_dir: Path, run_id: str) -> None:
    target = intermediate_dir / run_id / "toolchain-versions.txt"

    if TOOLCHAIN_VERSIONS_FILE.exists() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            TOOLCHAIN_VERSIONS_FILE.read_text(encoding="utf-8"), encoding="utf-8"
        )
        print(f"Toolchain versions recorded: {target}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run static analysis on assembled samples.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model-id", default=None, help="Single model; default all enabled.")
    parser.add_argument(
        "--tools",
        nargs="*",
        default=None,
        help="Override the tool list from config.",
    )
    parser.add_argument("--primary-compiler", default="g++", choices=["g++", "clang++"])
    parser.add_argument(
        "--run-id",
        default=None,
        help="Override the profile run_id (repair-loop iteration artifacts "
        "use the convention <run>__<variant>__iter<N>).",
    )
    parser.add_argument(
        "--replace-tool-entries",
        nargs="*",
        default=None,
        metavar="TOOL",
        help="EXPLICITLY replace existing entries of these tools even if they "
        "were recorded under a different execution condition (otherwise a "
        "condition mismatch is refused). Recorded in the invocation history.",
    )
    parser.add_argument(
        "--replace-legacy-record",
        action="store_true",
        help="EXPLICITLY recompute whole legacy records (static_analysis.v2 "
        "without sample_source_sha256 but WITH tool entries): every "
        "historical tool entry is retired (archived in the record under "
        "`superseded_legacy_tools`) before the requested tools run, so no "
        "unverified result survives under the newly pinned source hash. "
        "Without it such a record is refused (fail-closed); the safe "
        "alternative is a fresh run_id. REQUIRES an explicit --run-id: the "
        "profile default must never carry this into a historical run.",
    )
    parser.add_argument(
        "--rerun-gaps",
        action="store_true",
        help="Re-run tools whose existing entry is an analysis gap (TIMEOUT / "
        "TOOL_ERROR / NOT_ANALYZED / PARTIAL) under the same condition. "
        "Without it a persisted gap is terminal for resume (no repeated "
        "60 s PARCOACH timeouts on every resume).",
    )
    return parser.parse_args()


def resolve_enabled_tools(
    config: dict[str, Any], override: list[str] | None, stage_name: str
) -> "dict[str, ToolSettings]":
    """Enabled tools from the per-tool config schema.

    The --tools CLI override FILTERS the enabled set (container split), it
    cannot enable a config-disabled tool — that is a config decision.
    """
    settings = resolve_tool_settings(config, stage_name)
    enabled = {name: s for name, s in settings.items() if s.enabled}

    if override:
        for name in override:
            if name in settings and name not in enabled:
                print(
                    f"Tool '{name}' requested via --tools but disabled in the "
                    f"config; enable it under stages.{stage_name}.tools first."
                )
        enabled = {name: s for name, s in enabled.items() if name in override}

    return enabled


def not_applicable_entry(tool_name: str, execution_model: str) -> dict[str, Any]:
    """Record entry for a tool whose configured scope excludes this sample."""
    return framework.ToolResult(
        tool=tool_name,
        ran=False,
        exit_code=None,
        duration_seconds=0.0,
        error=f"not applicable: '{execution_model}' outside configured execution_models",
        analysis_state=STATE_NOT_APPLICABLE,
    ).to_dict()


def load_existing_records(output_path: Path) -> dict[str, dict[str, Any]]:
    """Load prior static_analysis.jsonl records keyed by sample_id.

    Re-runs merge per tool instead of discarding the file: the pipeline runs
    different tool subsets in different containers (main toolchain image vs.
    the PARCOACH image), and each invocation must not destroy the results of
    the other.
    """
    records: dict[str, dict[str, Any]] = {}

    if not output_path.exists():
        return records

    with output_path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                entry = json.loads(line)
                records[entry["sample_id"]] = entry

    return records


def record_has_blocking(record: dict[str, Any]) -> bool:
    return any(
        tool_data.get("num_blocking", 0) > 0
        for tool_data in record.get("tools", {}).values()
    )


def record_low_confidence_count(record: dict[str, Any]) -> int:
    return sum(
        tool_data.get("num_low_confidence", 0)
        for tool_data in record.get("tools", {}).values()
    )


def record_analysis_gaps(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Tools of a record that ran without a complete, trustworthy verdict."""
    gaps = []
    for tool_name in (record.get("tools") or {}):
        # record-level state: a front-end rejection of a TU the compiler
        # also rejected is subsumed (no gap of its own), see framework
        gap = framework.record_analysis_gap(record, tool_name)
        if gap is not None:
            gaps.append(gap)
    return gaps


# ---------------------------------------------------------------------------
# summary derived from the MERGED records
# ---------------------------------------------------------------------------

def load_summary(summary_path: Path) -> dict[str, Any]:
    if not summary_path.exists():
        return {}
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def summarize_records(
    model_id: str,
    records: "dict[str, dict[str, Any]]",
    expected_tools: "dict[str, ToolSettings]",
    invocations: "list[dict[str, Any]]",
) -> dict[str, Any]:
    """The canonical per-model summary: a pure function of the merged records
    and the EXPECTED (config-enabled) tool set - identical regardless of the
    order in which the containers ran.
    """
    per_tool: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

    for name, settings in expected_tools.items():
        applicable = [
            r for r in records.values()
            if settings.applies_to(r.get("execution_model", ""))
        ]
        states: Counter = Counter()
        findings = blocking = low_confidence = 0
        missing = subsumed = 0
        for record in applicable:
            entry = (record.get("tools") or {}).get(name)
            if entry is None:
                missing += 1
                continue
            state, reason = framework.effective_tool_state(record, name)
            states[state] += 1
            if framework.is_subsumed_rejection(state, reason):
                subsumed += 1
            findings += int(entry.get("num_findings", 0) or 0)
            blocking += int(entry.get("num_blocking", 0) or 0)
            low_confidence += int(entry.get("num_low_confidence", 0) or 0)

        completed = states.get(STATE_COMPLETED, 0)
        per_tool[name] = OrderedDict([
            ("execution_models", list(settings.execution_models)),
            ("applicable_samples", len(applicable)),
            ("samples_with_entry", len(applicable) - missing),
            ("samples_missing_entry", missing),
            ("completed", completed),
            ("partial", states.get(STATE_PARTIAL, 0)),
            ("not_analyzed", states.get(STATE_NOT_ANALYZED, 0)),
            # of which: rejected TUs the compiler ALSO rejected (the model
            # defect is carried by `compiler`; no gap of the tool's own)
            ("not_analyzed_subsumed_by_compiler", subsumed),
            ("tool_error", states.get(STATE_TOOL_ERROR, 0)),
            ("timeout", states.get(STATE_TIMEOUT, 0)),
            ("incomplete", len(applicable) - completed),
            ("clean_completed", sum(
                1 for r in applicable
                if (r.get("tools") or {}).get(name) is not None
                and entry_is_clean((r.get("tools") or {})[name]))),
            ("findings", findings),
            ("blocking", blocking),
            ("low_confidence", low_confidence),
        ])

    tools_with_applicable = [n for n, t in per_tool.items() if t["applicable_samples"] > 0]
    tools_completed_all = [
        n for n, t in per_tool.items()
        if t["applicable_samples"] > 0 and t["completed"] == t["applicable_samples"]
    ]
    tools_with_gaps = [
        n for n, t in per_tool.items()
        if (t["partial"] + t["not_analyzed"] + t["tool_error"] + t["timeout"]) > 0
    ]
    tools_with_missing = [n for n, t in per_tool.items() if t["samples_missing_entry"] > 0]

    # LLOV: explicit race / clean / not-analyzed / error / timeout counts so a
    # high "no finding" rate can never read as a high race-free rate
    llov_classes: Counter = Counter()
    if "llov" in expected_tools:
        for record in records.values():
            if not expected_tools["llov"].applies_to(record.get("execution_model", "")):
                continue
            entry = (record.get("tools") or {}).get("llov")
            if entry is None:
                llov_classes["missing_entry"] += 1
                continue
            state, _reason = framework.effective_tool_state(record, "llov")
            if state == STATE_TIMEOUT:
                llov_classes["timeout"] += 1
            elif state == STATE_TOOL_ERROR:
                llov_classes["tool_error"] += 1
            elif int(entry.get("num_blocking", 0) or 0) > 0:
                llov_classes["race_detected"] += 1
            elif state == STATE_COMPLETED:
                llov_classes["race_free_completed"] += 1
            elif state == STATE_PARTIAL:
                llov_classes["partial_not_analyzed"] += 1
            else:
                llov_classes["region_not_analyzed"] += 1

    samples_with_gap = sum(1 for r in records.values() if record_analysis_gaps(r))

    return OrderedDict([
        ("schema_version", STATIC_SUMMARY_SCHEMA_VERSION),
        ("tool_state_schema", TOOL_STATE_SCHEMA_VERSION),
        ("model_id", model_id),
        ("samples", len(records)),
        ("samples_with_blocking", sum(1 for r in records.values() if record_has_blocking(r))),
        ("samples_with_analysis_gap", samples_with_gap),
        ("expected_tools", list(expected_tools)),
        ("tools_with_applicable_samples", tools_with_applicable),
        ("tools_completed_on_all_applicable", tools_completed_all),
        ("tools_with_analysis_gaps", tools_with_gaps),
        ("tools_with_missing_entries", tools_with_missing),
        ("per_tool", per_tool),
        # backwards-compatible views of the v1 fields, now derived from the
        # merged records (never from one invocation)
        ("findings_per_tool", OrderedDict((n, t["findings"]) for n, t in per_tool.items())),
        ("blocking_per_tool", OrderedDict((n, t["blocking"]) for n, t in per_tool.items())),
        ("low_confidence_per_tool", OrderedDict((n, t["low_confidence"]) for n, t in per_tool.items())),
        ("llov_classes", OrderedDict(sorted(llov_classes.items()))),
        ("invocations", invocations),
        ("summary_semantics", "derived from the merged static_analysis.jsonl "
                              "records against the config-enabled tool set; "
                              "invocation order does not change it (timestamps "
                              "and the invocation history aside)"),
        ("created_at_utc", common.utc_now_iso()),
    ])


# ---------------------------------------------------------------------------
# per-model run
# ---------------------------------------------------------------------------

def run_model(
    context: framework.EvaluationContext,
    intermediate_dir: Path,
    run_id: str,
    model_id: str,
    tool_settings: "dict[str, ToolSettings]",
    tools_skipped: "list[dict[str, str]] | None" = None,
    expected_tools: "dict[str, ToolSettings] | None" = None,
    replace_tool_entries: "list[str] | None" = None,
    rerun_gaps: bool = False,
    replace_legacy_record: bool = False,
    invocation_label: str | None = None,
) -> dict[str, Any]:
    output_path = intermediate_dir / run_id / model_id / "static_analysis.jsonl"
    summary_path = output_path.parent / "static_analysis_summary.json"

    records = load_existing_records(output_path)
    expected = expected_tools if expected_tools is not None else tool_settings
    replace = set(replace_tool_entries or ())

    # main()'s environment gate already dropped unavailable tools (abort
    # when ALL are unavailable); this per-model check is a belt only
    available_tools = []
    for name in tool_settings:
        tool = framework.get_tool(name)
        if tool.is_available():
            available_tools.append(tool)
        else:
            print(f"[{model_id}] tool '{name}' unavailable in this environment, skipping.")

    ran_counter: Counter = Counter()
    kept_counter: Counter = Counter()
    samples_seen = 0
    legacy_pins = 0
    # sample_id -> historical tool entries dropped by --replace-legacy-record
    legacy_replaced: "dict[str, list[str]]" = {}

    # Fail-closed: verify ALL merges BEFORE writing anything, so a refused
    # sample never leaves a half-updated file behind.
    samples = list(framework.iter_assembled_samples(
        context.repo_root, intermediate_dir, run_id, model_id
    ))
    source_hashes: dict[str, str | None] = {}
    for sample in samples:
        source_hashes[sample.sample_id] = provenance.sample_source_sha256(sample.source_path)
        provenance.check_merge(records.get(sample.sample_id), sample.sample_id,
                               source_hashes[sample.sample_id],
                               replace_legacy_record=replace_legacy_record)

    for sample in samples:
        samples_seen += 1

        record = records.get(sample.sample_id)
        pre_existing = record is not None

        if record is None:
            record = {
                "schema_version": STATIC_ANALYSIS_SCHEMA_VERSION,
                "run_id": run_id,
                "model_id": model_id,
                "sample_id": sample.sample_id,
                "execution_model": sample.execution_model,
                "tools": {},
            }
            records[sample.sample_id] = record

        if record.get("sample_source_sha256") is None and source_hashes[sample.sample_id]:
            # Only two shapes reach this point (check_merge refuses the rest,
            # including a source whose bytes cannot be read): a record without
            # any tool result, or a legacy record whose FULL recomputation was
            # explicitly requested. Retiring entries without pinning would
            # leave a mangled record, so both happen together or not at all.
            historical = provenance.unpinned_legacy_entries(record)
            if historical:
                # ARCHIVE, never delete: the historical entries lose their
                # status as results (no consumer reads anything but
                # record["tools"]) but the evidence itself is preserved
                # verbatim inside the same record.
                record["superseded_legacy_tools"] = record["tools"]
                record["tools"] = {}
                legacy_replaced[sample.sample_id] = historical
                # the RECORD itself must say what it is: a v3 record born
                # from an unpinned v2 one, not a natively provenanced record
                record["legacy_entries_dropped"] = historical
                record["provenance_note"] = (
                    "recomputed from an unpinned static_analysis.v2 record "
                    "(--replace-legacy-record): every historical tool entry "
                    "was retired before re-analysis because it could not be "
                    "tied to any candidate source bytes. The retired entries "
                    "are preserved verbatim under `superseded_legacy_tools` "
                    "and are NOT results: no consumer reads them."
                )
            record["sample_source_sha256"] = source_hashes[sample.sample_id]
            if pre_existing:
                legacy_pins += 1

        record["created_at_utc"] = common.utc_now_iso()
        record["schema_version"] = STATIC_ANALYSIS_SCHEMA_VERSION
        record["tool_state_schema"] = TOOL_STATE_SCHEMA_VERSION

        for tool in available_tools:
            settings = tool_settings[tool.name]

            # configured scope (config ∩ hard capability) gates the run;
            # the record still gets an explicit not-applicable entry so
            # downstream consumers see the decision
            if not settings.applies_to(sample.execution_model):
                record["tools"][tool.name] = not_applicable_entry(
                    tool.name, sample.execution_model
                )
                continue

            condition = provenance.tool_execution_condition(
                tool, settings, sample.execution_model, context.primary_compiler,
                source_hashes[sample.sample_id],
            )
            fingerprint = provenance.tool_execution_fingerprint_sha256(condition)

            existing = record["tools"].get(tool.name)
            decision = provenance.check_tool_entry_merge(
                existing, tool.name, sample.sample_id, fingerprint,
                replace_allowed=tool.name in replace,
            )

            if decision == "keep":
                if rerun_gaps and analysis_state_of(existing) in ANALYSIS_GAP_STATES:
                    decision = "run"
                else:
                    kept_counter[tool.name] += 1
                    continue

            result = tool.run(sample, context)

            num_low_confidence = mark_low_confidence(result.findings, settings)

            entry = result.to_dict()
            entry["num_low_confidence"] = num_low_confidence
            entry["tool_execution_fingerprint_sha256"] = fingerprint
            entry["tool_execution_condition"] = condition
            record["tools"][tool.name] = entry
            ran_counter[tool.name] += 1

        # Recompute over ALL tools in the record (merged across invocations).
        record["has_blocking_findings"] = record_has_blocking(record)
        record["low_confidence_count"] = record_low_confidence_count(record)
        record["analysis_gaps"] = record_analysis_gaps(record)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for entry in records.values():
            file.write(json.dumps(entry) + "\n")

    if legacy_replaced:
        dropped_tools: Counter = Counter()
        for dropped in legacy_replaced.values():
            dropped_tools.update(dropped)
        examples = sorted(legacy_replaced)[:5]
        print(
            f"[{model_id}] --replace-legacy-record: dropped ALL historical "
            f"tool entries of {len(legacy_replaced)} unpinned legacy "
            f"record(s) ({sum(dropped_tools.values())} tool entries) before "
            "re-analysis - they could not be tied to any candidate source "
            "bytes. Per tool: "
            + ", ".join("%s %d" % item for item in sorted(dropped_tools.items()))
            + "; first samples: " + ", ".join(examples)
            + (" ..." if len(legacy_replaced) > len(examples) else "")
        )
    elif legacy_pins:
        print(
            f"[{model_id}] {legacy_pins} pre-existing record(s) without tool "
            "results were pinned to the current sample_source_sha256 "
            "(nothing historical was legitimized by that)."
        )

    previous = load_summary(summary_path)
    invocations = list(previous.get("invocations") or [])
    invocations.append(OrderedDict([
        ("label", invocation_label),
        ("created_at_utc", common.utc_now_iso()),
        ("tools_requested", list(tool_settings)),
        ("tools_run", [t.name for t in available_tools]),
        ("tools_skipped", tools_skipped or []),
        ("entries_run", OrderedDict(sorted(ran_counter.items()))),
        ("entries_kept_idempotent", OrderedDict(sorted(kept_counter.items()))),
        ("replace_tool_entries", sorted(replace)),
        ("rerun_gaps", bool(rerun_gaps)),
        # renamed in static_analysis_summary.v3 (see the schema comment):
        # pre-existing records that had NO tool result and were initialized
        ("pre_existing_records_pinned", legacy_pins),
        ("legacy_records_fully_replaced", OrderedDict([
            ("records", len(legacy_replaced)),
            ("tool_entries", sum(len(d) for d in legacy_replaced.values())),
            ("tools", OrderedDict(sorted(
                Counter(t for d in legacy_replaced.values() for t in d).items()))),
            ("first_sample_ids", sorted(legacy_replaced)[:5]),
        ])),
        ("replace_legacy_record", bool(replace_legacy_record)),
        ("primary_compiler", context.primary_compiler),
    ]))

    summary = summarize_records(model_id, records, expected, invocations)
    # legacy v1 views kept for consumers that read them: the LAST invocation
    # only (never the coverage statement - that is per_tool)
    summary["tools_run"] = [t.name for t in available_tools]
    summary["tools_skipped"] = tools_skipped or []
    common.write_json(summary_path, summary)

    print(
        f"[{model_id}] samples: {samples_seen}, "
        f"with blocking findings: {summary['samples_with_blocking']}, "
        f"with analysis gaps: {summary['samples_with_analysis_gap']}"
    )
    for name in summary["tools_run"]:
        t = summary["per_tool"].get(name)
        if t is None:
            continue
        print(
            f"    {name}: {t['findings']} findings ({t['blocking']} blocking); "
            f"completed {t['completed']}/{t['applicable_samples']}, "
            f"gaps partial={t['partial']} not_analyzed={t['not_analyzed']} "
            f"error={t['tool_error']} timeout={t['timeout']}; "
            f"run now {ran_counter[name]}, kept {kept_counter[name]}"
        )
    print(f"[{model_id}] output: {output_path}")

    return summary


def main() -> None:
    args = parse_args()

    config = load_config(Path(args.config).resolve())
    profile = common.get_profile(config, args.profile)
    run_id = args.run_id or profile["run_id"]

    if args.replace_legacy_record and not args.run_id:
        # The `pilot` profile still carries the historical pilot_001 run id,
        # so an implicit run id could carry a full recomputation into frozen
        # evidence. Naming the run is part of the decision.
        print(
            "--replace-legacy-record requires an explicit --run-id (the "
            "profile default resolves to '%s'). Name the run whose records "
            "you intend to recompute; historical pilot evidence must not be "
            "recomputed at all - use a fresh run_id instead." % run_id
        )
        sys.exit(2)

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    drivers_cpp_dir = REPO_ROOT / "drivers" / "cpp"

    register_default_tools(primary_compiler=args.primary_compiler, config=config)

    enabled_settings = resolve_enabled_tools(config, args.tools, "static_analysis")
    # the config-enabled set is the coverage EXPECTATION of the summary,
    # independent of which subset this container runs
    expected_settings = resolve_enabled_tools(config, None, "static_analysis")

    # Only keep tools the registry actually knows; warn on the rest.
    known: dict[str, ToolSettings] = {}
    for name, settings in enabled_settings.items():
        try:
            framework.get_tool(name)
            known[name] = settings
        except KeyError:
            print(f"Tool '{name}' configured but not implemented yet, skipping.")

    # Environment availability gate (2026-08-08). The old behavior — skip
    # unavailable tools per model with a log line — once produced a full
    # host run with ZERO tools and written empty records. ALL requested
    # tools unavailable is with near certainty an environment error (wrong
    # host/container), never a legitimate state -> abort BEFORE records.
    # Individual unavailable tools stay a warning (legitimate: the
    # parcoach/llov container split requests subsets), but the drop is
    # persisted per invocation in the summary artifact.
    unavailable = [
        name for name in known
        if not framework.get_tool(name).is_available()
    ]

    if unavailable and len(unavailable) == len(known):
        print(
            "ENVIRONMENT GATE FAILED — aborting before any record is "
            "written: ALL requested static tools are unavailable in this "
            "environment (" + ", ".join(unavailable) + "). Wrong host or "
            "container? compiler/clang_tidy/cppcheck/infer/gcc_analyzer "
            "run in pareval-thesis, parcoach in parcoach-demo, llov in "
            "pareval-llov."
        )
        sys.exit(2)

    tools_skipped = []
    for name in unavailable:
        print(
            f"WARNING: tool '{name}' unavailable in this environment — "
            "skipped for this invocation (recorded in the summary's "
            "invocation history; coverage is judged from the merged records)."
        )
        tools_skipped.append({
            "tool": name,
            "reason": "binary unavailable (is_available() failed)",
        })
        del known[name]

    context = framework.EvaluationContext(
        repo_root=REPO_ROOT,
        drivers_cpp_dir=drivers_cpp_dir,
        primary_compiler=args.primary_compiler,
        config=config,
    )

    models = [
        model
        for model in config.get("models", [])
        if model.get("enabled", False)
        and (args.model_id is None or model.get("id") == args.model_id)
    ]

    if not models:
        raise ValueError("No enabled models matched the selection.")

    scopes = ", ".join(
        f"{name}[{'/'.join(s.execution_models)}]" for name, s in known.items()
    )
    print(f"Static analysis | run {run_id} | tools: {scopes}")
    print("=" * 40)

    record_toolchain_versions(intermediate_dir, run_id)

    # freeze the run configuration / record config drift (run_manifest.py)
    from thesis.evaluation.run_manifest import ensure_run_manifest, register_static_condition

    ensure_run_manifest(
        config, run_id, stage="static_analysis", profile=args.profile,
        primary_compiler=args.primary_compiler,
    )
    condition = provenance.static_analysis_condition(config, args.primary_compiler)
    register_static_condition(
        config, run_id, provenance.static_analysis_condition_sha256(condition), condition,
    )

    # Pre-run enforcement (contracted runs only). Each runtime DOMAIN this
    # invocation will actually produce findings in is stamped BEFORE the
    # first record: the main container for the host-side tools, the PARCOACH
    # container and the LLOV container for their own tools. A drift is
    # STAGE_RUNTIME_DRIFT - a provenance failure before analysis, never a
    # TOOL_ERROR and never a tool-state gap record.
    from thesis.evaluation import stage_runtime

    domain_stages = stage_runtime.static_stages_for_tools(list(known))
    # ONE CLI invocation, projected onto every runtime domain it stamps: the
    # PARCOACH and LLOV container invocations carry the SAME effective values
    # as the main one (they are the same command line). Registering them for
    # the main domain only would leave every contracted PARCOACH/LLOV run
    # without an effective invocation - post-run permanently UNRESOLVED.
    for domain_stage in domain_stages:
        values = {
            "primary_compiler": {
                "value": args.primary_compiler,
                "source": "CLI" if args.primary_compiler != "g++" else "DEFAULT"},
            "tools": {"value": sorted(known),
                      "source": "CLI" if args.tools else "CONFIG"},
            "replace_tool_entries": {"value": bool(args.replace_tool_entries),
                                     "source": "CLI" if args.replace_tool_entries else "DEFAULT"},
            "rerun_gaps": {"value": bool(args.rerun_gaps),
                           "source": "CLI" if args.rerun_gaps else "DEFAULT"},
            "replace_legacy_record": {"value": bool(args.replace_legacy_record),
                                      "source": "CLI" if args.replace_legacy_record else "DEFAULT"},
        }
        enforcement = stage_runtime.enforce_stage(
            config, run_id, domain_stage,
            effective_values=values,
            profile=args.profile,
            model_scope=[model["id"] for model in models] if args.model_id else None,
            writer="static_analysis")
        if enforcement.get("enforced"):
            print("Pre-run enforcement [%s]: stage runtime %s..."
                  % (domain_stage, str(enforcement.get("stage_runtime_sha256"))[:12]))
        else:
            print("Pre-run enforcement [%s]: NOT_APPLICABLE (%s)"
                  % (domain_stage, enforcement.get("reason")))

    for model_config in models:
        try:
            run_model(
                context=context,
                intermediate_dir=intermediate_dir,
                run_id=run_id,
                model_id=model_config["id"],
                tool_settings=known,
                tools_skipped=tools_skipped,
                expected_tools=expected_settings,
                replace_tool_entries=args.replace_tool_entries,
                rerun_gaps=args.rerun_gaps,
                replace_legacy_record=args.replace_legacy_record,
                invocation_label="run_static_analysis --tools %s" % (
                    " ".join(args.tools) if args.tools else "<config>"),
            )
        except provenance.StaticMergeConflict as conflict:
            print("MERGE REFUSED (fail-closed): %s" % conflict)
            sys.exit(3)


if __name__ == "__main__":
    main()
