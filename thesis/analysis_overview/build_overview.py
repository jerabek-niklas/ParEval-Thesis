"""Consolidated overview: flat CSV + markdown summary (design §10).

READ-ONLY join of all stage JSONLs on (sample_id, variant, iteration).
Iteration 0 is the shared initial generation and appears once PER VARIANT
as that variant's starting point (same underlying data, one row per
variant) — the `is_shared_initial` column marks those rows so nothing is
accidentally triple-counted.

Row grid per (sample, variant): iterations 0..last (last = highest
iteration on the sample's state trail). Missing records NEVER drop a row
(design §10): the row carries explicit NA markers, `data_complete=false`,
and `na_reason` distinguishing
    repair_unusable    the sample has no artifact at this iteration
                       (unassembled initial generation, refused/unusable
                       repair answer)
    backfill_missing:<stages>
                       artifact exists but stage records are absent —
                       run thesis/repair/run_backfill.py
    artifact_missing   iteration run itself is absent (loop interrupted)

Column semantics (raw tool-level counts, NOT the loop's stop semantics):
`blocking_count`/`low_confidence_count`/`non_blocking_count` sum the
per-tool counters over the static + dynamic records; a low-confidence
blocking finding is counted in BOTH blocking_count and
low_confidence_count. `<tool>_blocking` is the tool entry's num_blocking
(NA when the tool did not run on this sample). `mismatch_total` is the
MAX over the correctness grid points (grid points see different random
inputs; summing would double-count the same defect).
`repair_prompt_tokens`/`repair_completion_tokens` come from the repair
response record's provider usage (normalized across providers).

`cleaning_*` columns mirror the assembly record's cleaning block. They
belong in the results, not just in the logs: `cleaning_auto_closed` marks
samples whose braces the PIPELINE closed before evaluation, i.e. an
intervention on the measured object — a sample that only compiles because
of that repair must not silently count as a model success. The remaining
flags (`used_fence`, `dropped_leading_lines`, `relocated_includes`,
`signature_suspect`) describe how the answer was formatted and are an
instruction-following signal per model, since the system prompt asks for
bare code without Markdown. The "Cleaning interventions" section of
overview.md reports these shares per model and per iteration; read them
NEXT TO the correctness numbers, and state the auto_closed share wherever
pass rates are reported.

Outputs (refuses to overwrite without --force):
    <outputs.root>/analysis/<base_run>/overview.csv
    <outputs.root>/analysis/<base_run>/overview.md

Usage:
    python3 thesis/analysis_overview/build_overview.py \
        --config thesis/config/config.yaml --profile smoke [--model-id X] [--force]

Python 3.8 compatible.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.evaluation.finding_classes import CLASSES, classify_finding  # noqa: E402
from thesis.evaluation.tool_config import (  # noqa: E402
    STAGE_TOOLS,
    resolve_tool_settings,
)
from thesis.evaluation.run_enhanced_tests import derived_file_names  # noqa: E402
from thesis.repair import orchestrator  # noqa: E402
from thesis.repair.run_backfill import (  # noqa: E402
    ENHANCED_MARKER,
    load_jsonl_by_sample,
)

NA = "NA"

PIPELINE_TOOLS = tuple(STAGE_TOOLS["static_analysis"]) + tuple(
    STAGE_TOOLS["dynamic_analysis"]
)

ENHANCED_COUNTED = (
    "pass", "fail", "crash", "timeout", "build_failed", "runtime_error"
)
ENHANCED_GATED = ("baseline_incompatible", "numerically_unstable")

# Cleaning flags from assembly.jsonl (thesis/assembly/cleaning.py). These are
# INTERVENTIONS ON THE MEASURED OBJECT: the pipeline repairs model output
# before evaluating it, so the share of samples that needed which repair has
# to be reportable next to the correctness numbers. `auto_closed` is the
# strongest one (we closed braces the model left open); the others describe
# how the answer was formatted, which doubles as an instruction-following
# signal per model.
CLEANING_FLAGS = [
    "auto_closed",             # unbalanced braces closed by the pipeline
    "used_fence",              # answer came wrapped in a markdown fence
    "signature_suspect",       # signature line looked off after cleaning
    "braces_balanced",         # braces already balanced as delivered
]

# Counters from the same record; reported as "samples with count > 0".
CLEANING_COUNTS = [
    "dropped_leading_lines",
    "dropped_trailing_lines",
    "dropped_duplicated_prompt_lines",
    "relocated_includes",      # list in the record -> stored as its length
]

CLEANING_COLUMNS = (
    ["cleaning_%s" % flag for flag in CLEANING_FLAGS]
    + ["cleaning_%s" % name for name in CLEANING_COUNTS]
)

# Per-tool runtime columns (docs/timing-and-effort.md): <tool>_seconds is
# the tool's own duration_seconds; <tool>_timed_out marks runs whose error
# indicates a timeout — those durations are the TIMEOUT LIMIT, not a real
# analysis duration, and the runtime summary excludes them from median/p95
# so a 300 s cap cannot masquerade as measured cost.
TOOL_RUNTIME_COLUMNS = (
    ["%s_seconds" % tool for tool in PIPELINE_TOOLS]
    + ["%s_timed_out" % tool for tool in PIPELINE_TOOLS]
)

# Generation-side effort/timing view, filled for EVERY iteration (0 = the
# shared initial generation) from the joined generation record.
# generation_duration_seconds is only set for timing_mode "direct": batch
# records carry no latency by design (queue-dominated wall time).
GENERATION_COLUMNS = [
    "generation_timing_mode",
    "generation_duration_seconds",
    "generation_input_tokens",
    "generation_output_tokens",
    "generation_reasoning_tokens",
]

# Blocking findings per ERROR CLASS (finding_classes.py), derived from the
# recorded check_ids at join time (read-only; no schema change). Finding
# SUMS double-count by design — several tools reporting the same defect is
# the redundancy tier working; the summary therefore additionally reports
# the deduplicated "samples with >=1 blocking finding of class C" rate,
# which is the citable number.
CLASS_COLUMNS = ["class_%s_blocking" % name for name in CLASSES]

COLUMNS = [
    "sample_id", "model", "execution_model", "problem_type", "benchmark",
    "variant", "iteration", "is_shared_initial",
    "data_complete", "na_reason",
] + CLEANING_COLUMNS + [
    "build_ok", "correctness_verdict", "correctness_pass_gridpoints",
    "mismatch_total",
    "blocking_count", "low_confidence_count", "non_blocking_count",
] + ["%s_blocking" % tool for tool in PIPELINE_TOOLS] + CLASS_COLUMNS + TOOL_RUNTIME_COLUMNS + [
    "enhanced_pass", "enhanced_fail", "enhanced_crash", "enhanced_timeout",
    "enhanced_build_failed", "enhanced_runtime_error", "enhanced_gated",
    "status", "stop_reason",
    "repair_prompt_tokens", "repair_completion_tokens",
] + GENERATION_COLUMNS + [
    "duration_compile_seconds", "duration_analysis_seconds",
    "duration_tests_seconds",
    # stage sums; duration_analysis_seconds (static+dynamic combined) is
    # kept unchanged for compatibility, the split is new
    "static_seconds", "dynamic_seconds", "correctness_seconds",
    "enhanced_seconds",
]


def tool_timed_out(entry: Dict[str, Any]) -> bool:
    """Did this tool run end in a timeout (of the tool itself or its build)?

    Detected from the recorded error string ("<tool> timed out", "timeout",
    "build failed (timeout)", ...). Such entries still carry a duration —
    but it is the configured limit, not a measured analysis time.
    """
    error = entry.get("error")
    if not isinstance(error, str):
        return False
    lowered = error.lower()
    return "timed out" in lowered or "timeout" in lowered


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the consolidated overview.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model-id", default=None, help="Single model; default all enabled.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing overview outputs (default: abort).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Per-run data loading (cached)
# ---------------------------------------------------------------------------


class RunData:
    """All JSONLs of one (run_id, model) pair, loaded once."""

    def __init__(self, config: Dict[str, Any], run_id: str, model_id: str) -> None:
        intermediate = Path(config["outputs"]["intermediate_dir"]) / run_id / model_id
        raw = Path(config["outputs"]["raw_dir"]) / run_id / model_id

        enhanced_stage = (config.get("stages") or {}).get("enhanced_tests") or {}

        self.exists = (intermediate / "assembly.jsonl").exists()
        self.assembly = load_jsonl_by_sample(intermediate / "assembly.jsonl")
        self.static = load_jsonl_by_sample(
            intermediate / orchestrator.stage_output_file(config, "static_analysis")
        )
        self.correctness = load_jsonl_by_sample(
            intermediate / orchestrator.stage_output_file(config, "correctness_tests")
        )
        self.dynamic = load_jsonl_by_sample(
            intermediate / orchestrator.stage_output_file(config, "dynamic_analysis")
        )
        self.responses = load_jsonl_by_sample(raw / "generations.jsonl")

        # api_mode of the run that produced these responses, from the
        # generation summary. Needed to classify LEGACY v2 records: batch
        # mode already existed under schema v2 and stamped a near-zero
        # poll-side duration_seconds onto batch records WITHOUT any marker
        # in the record itself — the summary is the only per-run signal.
        # Summaries predating the batch feature carry no api_mode and were
        # all direct.
        self.generation_api_mode = "direct"
        summary_path = raw / "generation_summary.json"
        if summary_path.exists():
            try:
                with summary_path.open("r", encoding="utf-8") as handle:
                    self.generation_api_mode = (
                        json.load(handle).get("api_mode") or "direct"
                    )
            except (json.JSONDecodeError, OSError):
                pass

        self.enhanced: Dict[str, List[Dict[str, Any]]] = {}
        enhanced_name = enhanced_stage.get("output_file_name", "enhanced_tests.jsonl")
        enhanced_path = intermediate / enhanced_name
        if enhanced_path.exists():
            with enhanced_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    # tolerant like the runner's resume loader: a hard kill
                    # can truncate the trailing appended line; one bad line
                    # must not abort the whole overview build
                    try:
                        record = json.loads(line)
                        self.enhanced.setdefault(record["sample_id"], []).append(record)
                    except (ValueError, KeyError):
                        continue

        # timing semantics of THIS run's enhanced files, from the per-model
        # summary (versioned, never guessed from record shape):
        #   None (legacy, no marker)          duration_seconds = build+run
        #   "run_only_plus_build_groups"      duration_seconds = run only;
        #                                     compile times live per group in
        #                                     the build-groups file
        # The marker applies per (run, model) FILE. A resume ACROSS the
        # harness change (e.g. phase-2 backfill over a legacy run with
        # partial spec coverage) mixes semantics per record inside one
        # file; the runner records that as legacy_mixed_rows in the
        # summary, and the enhanced_seconds SUM stays correct either way
        # (legacy build+run + new run-only + new group compiles = the true
        # total) — only per-record duration splits must exclude such runs.
        self.enhanced_timing_semantics: Optional[str] = None
        self.enhanced_build_groups: Dict[str, List[Dict[str, Any]]] = {}

        try:
            groups_name, summary_name = derived_file_names(enhanced_name)
        except ValueError:
            # legacy configs could name the output arbitrarily (the old
            # runner accepted any name); such runs are legacy-semantics by
            # construction — read the records, never crash the join
            groups_name = summary_name = None

        summary_path = (intermediate / summary_name) if summary_name else None
        if summary_path is not None and summary_path.exists():
            try:
                with summary_path.open("r", encoding="utf-8") as handle:
                    enhanced_summary = json.load(handle)
                self.enhanced_timing_semantics = enhanced_summary.get("timing_semantics")
                groups_name = enhanced_summary.get("build_groups_file") or groups_name
            except (json.JSONDecodeError, OSError):
                pass

        groups_path = (intermediate / groups_name) if groups_name else None
        if groups_path is not None and groups_path.exists():
            with groups_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                        self.enhanced_build_groups.setdefault(
                            row["sample_id"], []
                        ).append(row)
                    except (ValueError, KeyError):
                        continue

            # A run interrupted before its summary write (or a --force
            # rerun over a stale marker-less legacy summary) leaves
            # new-format records WITHOUT the marker; the groups file only
            # ever exists for grouped (run-only) runs, so its presence is
            # the authoritative fallback signal — without it the whole
            # compile share would silently vanish from enhanced_seconds
            # (review finding 2026-08-08).
            if self.enhanced_timing_semantics is None:
                self.enhanced_timing_semantics = "run_only_plus_build_groups"


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------


def parse_sample_id(sample_id: str) -> "Tuple[str, str, str]":
    """(execution_model, benchmark_name, problem_type) — the convention
    from framework.iter_assembled_samples."""
    parts = sample_id.split("__")
    execution_model = parts[-2] if len(parts) >= 2 else "serial"
    name = parts[-3] if len(parts) >= 3 else "unknown"
    problem_type = parts[-4] if len(parts) >= 4 else "unknown"
    return execution_model, name, problem_type


def scoped_static_tools(config: Dict[str, Any], execution_model: str) -> List[str]:
    settings = resolve_tool_settings(config, "static_analysis")
    return [
        name for name, s in settings.items()
        if s.enabled and execution_model in s.execution_models
    ]


def usage_tokens(usage: Any) -> "Tuple[Optional[int], Optional[int]]":
    """(prompt, completion) normalized across provider usage shapes."""
    if not isinstance(usage, dict):
        return None, None

    prompt = None
    completion = None

    for key in ("prompt_tokens", "input_tokens", "prompt_token_count"):
        if isinstance(usage.get(key), int):
            prompt = usage[key]
            break

    for key in ("completion_tokens", "output_tokens", "candidates_token_count"):
        if isinstance(usage.get(key), int):
            completion = usage[key]
            break

    return prompt, completion


def apply_generation_columns(
    row: Dict[str, Any],
    response: Optional[Dict[str, Any]],
    run_api_mode: str = "direct",
) -> None:
    """Effort/timing view of the generation record behind this artifact.

    Tokens come from api_response.usage_normalized where present (v3
    records); older records are normalized on the fly from the raw usage —
    same function, so both paths agree.

    timing_mode classification, in order:
      1. status.timing_mode — authoritative on v3 records.
      2. generation_parameters.api_mode == "batch" — the marker v2 REPAIR
         batch records carry (set by the orchestrator's batch merge).
      3. `run_api_mode` from the run's generation summary — batch mode
         already existed under schema v2 and stamped a near-zero poll-side
         duration onto batch records with NO marker in the record itself;
         the summary's api_mode is the only signal for those files.
      4. "direct" — summaries predating the batch feature have no api_mode
         and all of those runs were synchronous.
    Latency is only taken from effectively-direct records; everything
    classified as batch contributes NO duration (its recorded value, where
    a legacy writer stamped one, is poll-side processing or queue time,
    never model latency — docs/timing-and-effort.md).
    """
    if not response:
        return

    api_response = response.get("api_response") or {}
    normalized = api_response.get("usage_normalized") or common.normalize_usage(
        api_response.get("usage")
    )

    if normalized:
        row["generation_input_tokens"] = normalized.get("input_tokens")
        row["generation_output_tokens"] = normalized.get("output_tokens")
        row["generation_reasoning_tokens"] = normalized.get("reasoning_tokens")

    status = response.get("status") or {}
    timing_mode = status.get("timing_mode")

    if timing_mode is None:
        record_mode = (response.get("generation_parameters") or {}).get("api_mode")
        if record_mode == "batch" or run_api_mode == "batch":
            timing_mode = "batch"
        else:
            timing_mode = "direct"

    row["generation_timing_mode"] = timing_mode

    if timing_mode == "direct":
        row["generation_duration_seconds"] = status.get("duration_seconds")


def apply_cleaning_columns(
    row: Dict[str, Any], assembly_entry: Optional[Dict[str, Any]]
) -> None:
    """Copy the assembly record's cleaning block into the row.

    Read-only join, like every other stage in this file. Missing entries stay
    None (rendered as NA) instead of defaulting to False — "we did not clean"
    and "we do not know" must not collapse into one value.
    """
    cleaning = (assembly_entry or {}).get("cleaning") or {}

    if not cleaning:
        return

    for flag in CLEANING_FLAGS:
        if cleaning.get(flag) is not None:
            row["cleaning_%s" % flag] = bool(cleaning[flag])

    for name in CLEANING_COUNTS:
        value = cleaning.get(name)
        if value is None:
            continue
        # relocated_includes is a list of the include lines that were moved
        row["cleaning_%s" % name] = len(value) if isinstance(value, list) else int(value)


def build_row(
    config: Dict[str, Any],
    model_id: str,
    variant: str,
    sample_id: str,
    iteration: int,
    run_data: Optional[RunData],
    state_record: Optional[Dict[str, Any]],
    marker_cache: Dict[str, bool],
) -> Dict[str, Any]:
    execution_model, name, problem_type = parse_sample_id(sample_id)

    row: Dict[str, Any] = {column: None for column in COLUMNS}
    row.update({
        "sample_id": sample_id,
        "model": model_id,
        "execution_model": execution_model,
        "problem_type": problem_type,
        "benchmark": name,
        "variant": variant,
        "iteration": iteration,
        "is_shared_initial": iteration == 0,
        "status": (state_record or {}).get("status"),
        "stop_reason": (state_record or {}).get("stop_reason"),
    })

    if run_data is None or not run_data.exists:
        row["data_complete"] = False
        row["na_reason"] = "artifact_missing"
        return row

    assembly_entry = run_data.assembly.get(sample_id)

    # Filled even for unusable samples: how the answer had to be cleaned is
    # known regardless of whether it survived assembly.
    apply_cleaning_columns(row, assembly_entry)

    if assembly_entry is None or not assembly_entry.get("assembled"):
        row["data_complete"] = False
        row["na_reason"] = "repair_unusable"
        return row

    missing_stages: List[str] = []

    # ---- static + dynamic findings -----------------------------------
    static_record = run_data.static.get(sample_id)
    dynamic_record = run_data.dynamic.get(sample_id)

    required_static = scoped_static_tools(config, execution_model)
    static_present = set(((static_record or {}).get("tools") or {}).keys())

    if static_record is None or not set(required_static).issubset(static_present):
        missing_stages.append("static")

    if dynamic_record is None:
        missing_stages.append("dynamic")

    blocking = low_confidence = non_blocking = 0
    stage_seconds = {"static": 0.0, "dynamic": 0.0}
    have_counts = False
    # blocking findings per error class, derived from the recorded
    # check_ids (finding_classes.py) — read-only, no schema change. Sums
    # double-count across tools by design (redundancy tier); the summary
    # reports the deduplicated sample rate next to them.
    class_counts: Counter = Counter()

    for stage_name, record in (("static", static_record), ("dynamic", dynamic_record)):
        if record is None:
            continue
        for tool_name, entry in (record.get("tools") or {}).items():
            column = "%s_blocking" % tool_name
            if entry.get("ran"):
                row[column] = int(entry.get("num_blocking", 0))
                have_counts = True
                blocking += int(entry.get("num_blocking", 0))
                low_confidence += int(entry.get("num_low_confidence", 0))
                non_blocking += int(entry.get("num_findings", 0)) - int(
                    entry.get("num_blocking", 0)
                )

                for finding in entry.get("findings") or []:
                    if finding.get("blocking"):
                        class_counts[
                            classify_finding(
                                tool_name,
                                finding.get("check_id") or "",
                                finding.get("message") or "",
                            )
                        ] += 1

                duration = float(entry.get("duration_seconds", 0.0))
                stage_seconds[stage_name] += duration
                row["%s_seconds" % tool_name] = round(duration, 3)
                row["%s_timed_out" % tool_name] = tool_timed_out(entry)

    if have_counts:
        row["blocking_count"] = blocking
        row["low_confidence_count"] = low_confidence
        row["non_blocking_count"] = non_blocking
        # combined static+dynamic (pre-existing column, meaning unchanged)
        row["duration_analysis_seconds"] = round(
            stage_seconds["static"] + stage_seconds["dynamic"], 3
        )
        # 0 is a statement ("no blocking finding of this class"), so every
        # class column is filled once any analysis ran; rows without any
        # analysis keep None -> NA
        for name in CLASSES:
            row["class_%s_blocking" % name] = int(class_counts.get(name, 0))

    if static_record is not None:
        row["static_seconds"] = round(stage_seconds["static"], 3)
    if dynamic_record is not None:
        row["dynamic_seconds"] = round(stage_seconds["dynamic"], 3)

    # ---- correctness -------------------------------------------------
    correctness_record = run_data.correctness.get(sample_id)

    if correctness_record is None:
        missing_stages.append("correctness")
    else:
        compile_info = correctness_record.get("compile") or {}
        row["build_ok"] = bool(compile_info.get("ok"))
        if compile_info.get("duration_seconds") is not None:
            row["duration_compile_seconds"] = compile_info["duration_seconds"]

        row["correctness_verdict"] = correctness_record.get("verdict")

        runs = correctness_record.get("runs") or []
        passed = sum(1 for r in runs if r.get("verdict") == "pass")
        row["correctness_pass_gridpoints"] = "%d/%d" % (passed, len(runs))

        totals = [r.get("mismatch_total") for r in runs if r.get("mismatch_total")]
        if totals:
            row["mismatch_total"] = max(totals)

        test_seconds = sum(float(r.get("duration_seconds", 0.0)) for r in runs)
        row["duration_tests_seconds"] = round(test_seconds, 3)
        row["correctness_seconds"] = round(
            float(compile_info.get("duration_seconds") or 0.0) + test_seconds, 3
        )

    # ---- enhanced ----------------------------------------------------
    benchmark_dir = (assembly_entry.get("drivers") or {}).get(
        "benchmark_dir", ""
    ).replace("\\", "/")

    # enhanced coverage follows the configured execution models (default
    # [serial] = historical behavior; the pilot adds omp/mpi, and missing
    # records there then count as backfill_missing like any other stage)
    enhanced_models = (
        ((config.get("stages") or {}).get("enhanced_tests") or {})
        .get("execution_models")
        or ["serial"]
    )

    enhanced_expected = False
    if execution_model in enhanced_models and benchmark_dir:
        if benchmark_dir not in marker_cache:
            cpu_cc = REPO_ROOT / benchmark_dir / "cpu.cc"
            marker_cache[benchmark_dir] = (
                cpu_cc.exists()
                and ENHANCED_MARKER in cpu_cc.read_text(encoding="utf-8")
            )
        enhanced_expected = marker_cache[benchmark_dir]

    enhanced_records = run_data.enhanced.get(sample_id) or []

    if enhanced_records:
        counts = Counter(r.get("status") for r in enhanced_records)
        row["enhanced_pass"] = counts.get("pass", 0)
        row["enhanced_fail"] = counts.get("fail", 0)
        row["enhanced_crash"] = counts.get("crash", 0)
        row["enhanced_timeout"] = counts.get("timeout", 0)
        row["enhanced_build_failed"] = counts.get("build_failed", 0)
        row["enhanced_runtime_error"] = counts.get("runtime_error", 0)
        row["enhanced_gated"] = sum(counts.get(s, 0) for s in ENHANCED_GATED)

        # both timing semantics (versioned via the run summary, see
        # RunData): legacy files carry build+run mixed in duration_seconds;
        # grouped runs carry run-only durations plus per-group compile
        # times in the build-groups file — never mixed across semantics
        record_seconds = sum(
            float(r.get("duration_seconds") or 0.0) for r in enhanced_records
        )
        if run_data.enhanced_timing_semantics == "run_only_plus_build_groups":
            compile_seconds = sum(
                float(g.get("compile_seconds") or 0.0)
                for g in run_data.enhanced_build_groups.get(sample_id) or []
            )
            row["enhanced_seconds"] = round(record_seconds + compile_seconds, 3)
        else:
            row["enhanced_seconds"] = round(record_seconds, 3)
    elif enhanced_expected:
        missing_stages.append("enhanced")

    # ---- repair tokens (iterations >= 1: the response that produced
    # this artifact) -----------------------------------------------------
    if iteration >= 1:
        response = run_data.responses.get(sample_id) or {}
        prompt_tokens, completion_tokens = usage_tokens(
            (response.get("api_response") or {}).get("usage")
        )
        row["repair_prompt_tokens"] = prompt_tokens
        row["repair_completion_tokens"] = completion_tokens

    # ---- generation effort + timing (ALL iterations; 0 = the shared
    # initial generation) ------------------------------------------------
    apply_generation_columns(
        row, run_data.responses.get(sample_id), run_data.generation_api_mode
    )

    # ---- completeness ------------------------------------------------
    if missing_stages:
        row["data_complete"] = False
        row["na_reason"] = "backfill_missing:" + ",".join(missing_stages)
    else:
        row["data_complete"] = True

    return row


def collect_model_rows(
    config: Dict[str, Any], base_run_id: str, model_id: str
) -> "List[Dict[str, Any]]":
    settings = orchestrator.repair_settings(config)
    marker_cache: Dict[str, bool] = {}
    run_cache: Dict[str, RunData] = {}

    def run_data_for(run_id: str) -> RunData:
        if run_id not in run_cache:
            run_cache[run_id] = RunData(config, run_id, model_id)
        return run_cache[run_id]

    rows: List[Dict[str, Any]] = []

    for variant in settings["variants"]:
        paths = orchestrator.LoopPaths(config, base_run_id, model_id, variant)

        if not paths.state_path.exists():
            continue  # loop never ran for this variant

        trail: Dict[str, Dict[int, Dict[str, Any]]] = {}
        with paths.state_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    record = json.loads(line)
                    trail.setdefault(record["sample_id"], {})[
                        int(record["iteration"])
                    ] = record

        base = run_data_for(base_run_id)
        sample_ids = sorted(set(base.assembly) | set(trail))

        for sample_id in sample_ids:
            iterations = trail.get(sample_id) or {0: None}
            last = max(iterations)

            for iteration in range(0, last + 1):
                run_id = paths.iter_run_id(iteration)
                rows.append(
                    build_row(
                        config=config,
                        model_id=model_id,
                        variant=variant,
                        sample_id=sample_id,
                        iteration=iteration,
                        run_data=run_data_for(run_id),
                        state_record=iterations.get(iteration),
                        marker_cache=marker_cache,
                    )
                )

    return rows


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def write_csv(rows: "List[Dict[str, Any]]", path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)

        for row in rows:
            serialized = []
            for column in COLUMNS:
                value = row.get(column)
                if value is None:
                    serialized.append(NA)
                elif isinstance(value, bool):
                    serialized.append("true" if value else "false")
                else:
                    serialized.append(value)
            writer.writerow(serialized)


# ---------------------------------------------------------------------------
# Markdown summary
# ---------------------------------------------------------------------------


def _rate(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return NA
    return "%.1f%% (%d/%d)" % (100.0 * numerator / denominator, numerator, denominator)


def _by_sample(rows: "List[Dict[str, Any]]") -> "Dict[Tuple[str, str], Dict[int, Dict[str, Any]]]":
    grouped: Dict[Tuple[str, str], Dict[int, Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["model"], row["sample_id"]), {})[row["iteration"]] = row
    return grouped


def _effective_row(row_map: "Dict[int, Dict[str, Any]]", iteration: int
                   ) -> "Optional[Dict[str, Any]]":
    """Carry-forward: the sample's newest ARTIFACT-BEARING row at or
    before `iteration`. A stopped sample keeps contributing its final
    artifact; a repair_unusable/artifact_missing row never displaces the
    last real artifact (the sample's state remains its previous code)."""
    eligible = [
        i for i, row in row_map.items()
        if i <= iteration
        and row.get("na_reason") not in ("repair_unusable", "artifact_missing")
    ]
    if not eligible:
        return None
    return row_map[max(eligible)]


def _enhanced_counts(row: Dict[str, Any]) -> "Tuple[int, int]":
    if row.get("enhanced_pass") is None:
        return 0, 0
    total = sum(
        int(row.get("enhanced_%s" % status) or 0) for status in ENHANCED_COUNTED
    )
    return int(row["enhanced_pass"]), total


def trajectory_table(rows: "List[Dict[str, Any]]", variant: str) -> List[str]:
    variant_rows = [r for r in rows if r["variant"] == variant]

    if not variant_rows:
        return ["(no data)"]

    grouped = _by_sample(variant_rows)
    max_iteration = max(r["iteration"] for r in variant_rows)

    lines = [
        "| iteration | n | ParEval pass | enhanced pass (specs) |",
        "| --- | --- | --- | --- |",
    ]

    for iteration in range(0, max_iteration + 1):
        pareval_n = pareval_pass = 0
        enhanced_pass = enhanced_total = 0

        for row_map in grouped.values():
            row = _effective_row(row_map, iteration)
            if row is None:
                continue

            if row.get("correctness_verdict") is not None:
                pareval_n += 1
                if row["correctness_verdict"] == "pass":
                    pareval_pass += 1

            e_pass, e_total = _enhanced_counts(row)
            enhanced_pass += e_pass
            enhanced_total += e_total

        lines.append(
            "| %d | %d | %s | %s |"
            % (
                iteration,
                len(grouped),
                _rate(pareval_pass, pareval_n),
                _rate(enhanced_pass, enhanced_total),
            )
        )

    return lines


def stop_reason_table(rows: "List[Dict[str, Any]]", variant: str) -> List[str]:
    finals: Counter = Counter()

    grouped = _by_sample([r for r in rows if r["variant"] == variant])
    for row_map in grouped.values():
        final = row_map[max(row_map)]
        finals[final.get("status") or NA] += 1

    lines = ["| final status | samples |", "| --- | --- |"]
    for status, count in sorted(finals.items()):
        lines.append("| %s | %d |" % (status, count))
    return lines


def enabled_pipeline_tools(config: Dict[str, Any]) -> "List[str]":
    """All configured+enabled tools of both analysis stages, in canonical
    order — the column set of the convergence table. NOT filtered to tools
    with findings: a zero column IS information ("asan_ubsan found
    nothing" is a result)."""
    enabled: List[str] = []
    for stage_name in ("static_analysis", "dynamic_analysis"):
        for name, settings in resolve_tool_settings(config, stage_name).items():
            if settings.enabled:
                enabled.append(name)
    return enabled


def findings_convergence_table(
    rows: "List[Dict[str, Any]]", variant: str, config: Dict[str, Any]
) -> List[str]:
    variant_rows = [r for r in rows if r["variant"] == variant]
    if not variant_rows:
        return ["(no data)"]

    max_iteration = max(r["iteration"] for r in variant_rows)
    tools = enabled_pipeline_tools(config)

    lines = [
        "Cell semantics: a NUMBER means the tool ran on at least one "
        "artifact at that iteration (0 = ran and found nothing — a "
        "result); n/a means the tool was not applicable on this "
        "iteration's execution-model mix (or its records are not merged "
        "yet, e.g. external containers).",
        "",
        "| iteration | artifacts | " + " | ".join(tools) + " |",
        "| --- | --- | " + " | ".join("---" for _ in tools) + " |",
    ]

    for iteration in range(0, max_iteration + 1):
        at_iteration = [
            r for r in variant_rows
            if r["iteration"] == iteration and r.get("blocking_count") is not None
        ]

        cells = []
        for tool in tools:
            values = [
                int(r["%s_blocking" % tool])
                for r in at_iteration
                if r.get("%s_blocking" % tool) is not None
            ]
            # per-row None = the tool's record entry is not-applicable or
            # absent; a tool with no value on ANY artifact could not run here
            cells.append(str(sum(values)) if values else "n/a")

        lines.append(
            "| %d | %d | %s |" % (iteration, len(at_iteration), " | ".join(cells))
        )

    return lines


def _class_cells(
    rows_subset: "List[Dict[str, Any]]",
) -> "Dict[str, Tuple[int, int]]":
    """(finding sum, samples with >=1) per class over a set of rows.

    The DOUBLE-COUNTING RULE, implemented: several tools may report the
    same defect (redundancy by design — llov and tsan flagging one race is
    the tier working, not an error), so the finding SUM overstates unique
    defects. The per-sample count deduplicates across tools (a row with
    class count > 0 counts once regardless of how many tools contributed)
    and is the citable number; the sums stay next to it.
    """
    cells: "Dict[str, Tuple[int, int]]" = {}

    for name in CLASSES:
        column = "class_%s_blocking" % name
        values = [int(r[column]) for r in rows_subset if r.get(column) is not None]
        cells[name] = (sum(values), sum(1 for v in values if v > 0))

    return cells


def _classes_in_use(rows: "List[Dict[str, Any]]") -> "List[str]":
    return [
        name for name in CLASSES
        if any((r.get("class_%s_blocking" % name) or 0) > 0 for r in rows)
    ]


def blocking_by_class_section(
    rows: "List[Dict[str, Any]]", variants: "List[str]"
) -> List[str]:
    """Blocking findings by ERROR CLASS — the level the thesis argues on
    ("model X mostly produces class Y"), above the per-tool view.

    Cell format everywhere: `<finding sum> (<samples with >=1>)`. The sum
    double-counts across redundant tools by design; the parenthesised
    sample count is deduplicated and is the reportable rate (see
    _class_cells).
    """
    classes = _classes_in_use(rows)

    if not classes:
        return ["No blocking findings recorded."]

    lines: List[str] = [
        "Cells are `findings (samples)`: finding sums double-count when "
        "several tools report the same defect (redundancy by design); the "
        "sample count deduplicates across tools and is the citable number. "
        "Classes: thesis/evaluation/finding_classes.py.",
    ]

    def table(header: str, buckets: "List[Tuple[str, List[Dict[str, Any]]]]") -> None:
        lines.append("")
        lines.append("| %s | n | %s |" % (header, " | ".join(classes)))
        lines.append("| --- | --- | %s |" % " | ".join("---" for _ in classes))
        for label, subset in buckets:
            cells = _class_cells(subset)
            lines.append(
                "| %s | %d | %s |"
                % (
                    label,
                    len(subset),
                    " | ".join(
                        "%d (%d)" % cells[name] for name in classes
                    ),
                )
            )

    # (a) class x iteration per variant — the per-class convergence curve
    for variant in variants:
        variant_rows = [
            r for r in rows
            if r["variant"] == variant and r.get("blocking_count") is not None
        ]
        if not variant_rows:
            continue
        lines.append("")
        lines.append("**%s — class x iteration (per-iteration artifacts):**" % variant)
        max_iteration = max(r["iteration"] for r in variant_rows)
        table("iteration", [
            (str(i), [r for r in variant_rows if r["iteration"] == i])
            for i in range(0, max_iteration + 1)
        ])

    # (b) class x model, FINAL state (carry-forward) — the per-model
    # error profile
    for variant in variants:
        grouped = _by_sample([r for r in rows if r["variant"] == variant])
        finals: "List[Dict[str, Any]]" = []
        for row_map in grouped.values():
            final = _effective_row(row_map, max(row_map))
            if final is not None and final.get("blocking_count") is not None:
                finals.append(final)
        if not finals:
            continue
        lines.append("")
        lines.append("**%s — class x model (final state, carry-forward):**" % variant)
        table("model", [
            (model, [r for r in finals if r["model"] == model])
            for model in sorted({r["model"] for r in finals})
        ])

    # (c) class x execution model at ITERATION 0 (shared rows deduplicated
    # across variants) — where do which errors originate?
    iteration0 = [
        r for r in _dedupe_measurement_rows(rows)
        if int(r["iteration"]) == 0 and r.get("blocking_count") is not None
    ]
    if iteration0:
        lines.append("")
        lines.append("**class x execution model at iteration 0 (initial generations):**")
        table("exec", [
            (execution_model,
             [r for r in iteration0 if r["execution_model"] == execution_model])
            for execution_model in ("serial", "omp", "mpi")
            if any(r["execution_model"] == execution_model for r in iteration0)
        ])

    return lines


def breakdown_table(rows: "List[Dict[str, Any]]", variant: str, key: str) -> List[str]:
    grouped = _by_sample([r for r in rows if r["variant"] == variant])

    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for row_map in grouped.values():
        last = row_map[max(row_map)]  # key fields are always present
        final = _effective_row(row_map, max(row_map)) or last
        buckets.setdefault(last.get(key) or NA, []).append(final)

    lines = [
        "| %s | n | ParEval pass | enhanced pass (specs) |" % key,
        "| --- | --- | --- | --- |",
    ]

    for bucket, finals in sorted(buckets.items()):
        pareval_n = sum(1 for r in finals if r.get("correctness_verdict") is not None)
        pareval_pass = sum(1 for r in finals if r.get("correctness_verdict") == "pass")
        enhanced_pass = sum(_enhanced_counts(r)[0] for r in finals)
        enhanced_total = sum(_enhanced_counts(r)[1] for r in finals)
        lines.append(
            "| %s | %d | %s | %s |"
            % (bucket, len(finals), _rate(pareval_pass, pareval_n),
               _rate(enhanced_pass, enhanced_total))
        )

    return lines


def clean_but_incorrect(rows: "List[Dict[str, Any]]") -> List[str]:
    grouped = _by_sample([r for r in rows if r["variant"] == "static_feedback"])

    if not grouped:
        return ["(static_feedback did not run)"]

    clean_finals = []
    for row_map in grouped.values():
        last = row_map[max(row_map)]
        if last.get("status") == "stopped_clean":
            clean_finals.append(_effective_row(row_map, max(row_map)) or last)

    if not clean_finals:
        return ["No static_feedback sample stopped clean."]

    with_verdict = [r for r in clean_finals if r.get("correctness_verdict") is not None]
    incorrect = [r for r in with_verdict if r["correctness_verdict"] != "pass"]

    with_enhanced = [r for r in clean_finals if r.get("enhanced_pass") is not None]
    enhanced_failing = [
        r for r in with_enhanced
        if sum(int(r.get("enhanced_%s" % s) or 0)
               for s in ("fail", "crash", "timeout", "runtime_error")) > 0
    ]

    lines = [
        "Samples stopping clean (no blocking static findings): %d" % len(clean_finals),
        "",
        "- ParEval-incorrect among them: %s"
        % _rate(len(incorrect), len(with_verdict)),
        "- enhanced-failing among them: %s"
        % _rate(len(enhanced_failing), len(with_enhanced)),
    ]

    missing = len(clean_finals) - len(with_verdict)
    if missing:
        lines.append(
            "- %d clean sample(s) without correctness data (backfill missing)"
            % missing
        )

    return lines


def _median_p95(values: "List[float]") -> "Tuple[Optional[float], Optional[float]]":
    """(median, p95). Median because the runtime distributions are skewed
    (means would be dominated by MUST deadlock timeouts and Valgrind
    outliers); p95 as the honest tail. p95 = nearest-rank, hand-rolled —
    no new dependencies."""
    if not values:
        return None, None

    ordered = sorted(values)
    p95_index = max(0, int(math.ceil(len(ordered) * 0.95)) - 1)

    return statistics.median(ordered), ordered[p95_index]


def _dedupe_measurement_rows(
    rows: "List[Dict[str, Any]]",
) -> "List[Dict[str, Any]]":
    """One row per actually-produced artifact.

    Iteration 0 is the SHARED initial generation: every variant's row
    points at the same records, so counting it per variant would multiply
    identical measurements by the number of variants. Iterations >= 1 are
    genuinely distinct per variant and stay.
    """
    seen: set = set()
    result: List[Dict[str, Any]] = []

    for row in rows:
        iteration = int(row["iteration"])
        if iteration == 0:
            key = (row["model"], row["sample_id"], 0)
        else:
            key = (row["model"], row["variant"], row["sample_id"], iteration)

        if key in seen:
            continue
        seen.add(key)
        result.append(row)

    return result


def runtime_cost_section(rows: "List[Dict[str, Any]]") -> List[str]:
    """Median/p95 analysis runtime per tool x execution model + timeout share.

    This is what lets detection performance be weighed against runtime
    cost (gcc_analyzer ~1.03x vs. Valgrind's 20-50x vs. MUST's deadlock
    timeouts). Timed-out runs are counted separately and EXCLUDED from
    median/p95 — their recorded duration is the configured limit, not a
    measured analysis time.
    """
    deduped = _dedupe_measurement_rows(rows)

    lines = [
        "Median and p95 of the per-sample tool runtime, split by execution "
        "model (medians because the distributions are skewed). n = runs "
        "with a recorded duration; timeouts are excluded from median/p95 "
        "and reported as their own share.",
        "",
        "| tool | exec | n | median s | p95 s | timeouts |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    printed = False

    for tool in PIPELINE_TOOLS:
        for execution_model in ("serial", "omp", "mpi"):
            subset = [
                r for r in deduped
                if r["execution_model"] == execution_model
                and r.get("%s_seconds" % tool) is not None
            ]
            if not subset:
                continue

            timeouts = [r for r in subset if r.get("%s_timed_out" % tool)]
            measured = [
                float(r["%s_seconds" % tool])
                for r in subset
                if not r.get("%s_timed_out" % tool)
            ]

            median, p95 = _median_p95(measured)
            printed = True
            lines.append(
                "| %s | %s | %d | %s | %s | %s |"
                % (
                    tool,
                    execution_model,
                    len(subset),
                    "%.2f" % median if median is not None else NA,
                    "%.2f" % p95 if p95 is not None else NA,
                    _rate(len(timeouts), len(subset)),
                )
            )

    if not printed:
        return ["No tool runtimes recorded."]

    return lines


def generation_effort_section(rows: "List[Dict[str, Any]]") -> List[str]:
    """Token-based effort per model x iteration, plus direct-only latency.

    Reasoning tokens are the PRIMARY effort metric: available in both API
    modes, comparable across providers, and free of infrastructure noise.
    Wall-clock latency is reported separately, from timing_mode == "direct"
    records ONLY, and even then it includes network and provider load — see
    docs/timing-and-effort.md for how it may be interpreted.
    """
    deduped = [
        r for r in _dedupe_measurement_rows(rows)
        if r.get("generation_input_tokens") is not None
        or r.get("generation_output_tokens") is not None
    ]

    if not deduped:
        return ["No generation usage data recorded."]

    def tokens(subset: "List[Dict[str, Any]]", column: str) -> "List[int]":
        return [int(r[column]) for r in subset if r.get(column) is not None]

    lines = [
        "Effort = tokens spent per generation (median over samples, plus "
        "the run total). reasoning median NA means the provider reports no "
        "reasoning-token field for this model.",
        "",
        "| model | iteration | n | input med | output med | reasoning med | "
        "reasoning sum |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    keys = sorted({(r["model"], int(r["iteration"])) for r in deduped})

    for model, iteration in keys:
        subset = [
            r for r in deduped
            if r["model"] == model and int(r["iteration"]) == iteration
        ]
        reasoning = tokens(subset, "generation_reasoning_tokens")

        def med(values: "List[int]") -> str:
            return "%d" % statistics.median(values) if values else NA

        lines.append(
            "| %s | %d | %d | %s | %s | %s | %s |"
            % (
                model,
                iteration,
                len(subset),
                med(tokens(subset, "generation_input_tokens")),
                med(tokens(subset, "generation_output_tokens")),
                med(reasoning),
                "%d" % sum(reasoning) if reasoning else NA,
            )
        )

    # ---- direct latency, strictly separated --------------------------
    lines.append("")
    lines.append(
        "Direct request latency (timing_mode == \"direct\" records ONLY — "
        "batch records carry no latency by design, their wall time is "
        "provider queue time). Latency additionally includes network and "
        "provider load; comparable numbers require one contiguous direct "
        "run."
    )
    lines.append("")
    lines.append("| model | n (direct) | median s | p95 s |")
    lines.append("| --- | --- | --- | --- |")

    for model in sorted({r["model"] for r in deduped}):
        latencies = [
            float(r["generation_duration_seconds"])
            for r in deduped
            if r["model"] == model
            and r.get("generation_timing_mode") == "direct"
            and r.get("generation_duration_seconds") is not None
        ]
        median, p95 = _median_p95(latencies)
        lines.append(
            "| %s | %d | %s | %s |"
            % (
                model,
                len(latencies),
                "%.2f" % median if median is not None else NA,
                "%.2f" % p95 if p95 is not None else NA,
            )
        )

    return lines


def enhanced_by_execution_model_section(rows: "List[Dict[str, Any]]") -> List[str]:
    """Enhanced verdicts split by execution model — the pilot's decision
    basis for parallel enhanced tests. The GATES behind these numbers are
    serial (documented simplification, docs/enhanced-tests-parallel.md):
    omp/mpi crash/timeout cells may contain driver-divergence cases and
    need manual sighting before being read as model errors; fail cells may
    contain parallel-rounding signatures (small relative deviations at
    many indices)."""
    deduped = [
        r for r in _dedupe_measurement_rows(rows)
        if r.get("enhanced_pass") is not None
    ]

    if not deduped:
        return ["No enhanced-test records."]

    lines = [
        "Spec-run verdicts per execution model (gates are SERIAL: sight "
        "omp/mpi crash/timeout manually for driver divergence, and expect "
        "rounding signatures in fail — see docs/enhanced-tests-parallel.md).",
        "",
        "| exec | samples | pass | fail | crash | timeout | build_failed | "
        "runtime_error | gated |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for execution_model in ("serial", "omp", "mpi"):
        subset = [r for r in deduped if r["execution_model"] == execution_model]
        if not subset:
            continue

        def total(column: str) -> int:
            return sum(int(r.get(column) or 0) for r in subset)

        lines.append(
            "| %s | %d | %d | %d | %d | %d | %d | %d | %d |"
            % (
                execution_model,
                len(subset),
                total("enhanced_pass"),
                total("enhanced_fail"),
                total("enhanced_crash"),
                total("enhanced_timeout"),
                total("enhanced_build_failed"),
                total("enhanced_runtime_error"),
                total("enhanced_gated"),
            )
        )

    return lines


def cleaning_section(rows: "List[Dict[str, Any]]") -> List[str]:
    """Share of samples per model and cleaning flag, split by iteration.

    Reported because auto-closing braces (and dropping stray lines) is an
    INTERVENTION ON THE MEASURED OBJECT: the pipeline repairs model output
    before evaluating it. The share belongs next to the correctness numbers.
    The iteration split additionally shows whether the answer FORMAT changes
    over the repair iterations (models that first answer in prose may switch
    to bare code once they get feedback, or the other way round).

    Counted per (sample_id, iteration) so the shared initial generation is
    not multiplied by the number of variants.
    """
    seen: Dict[Tuple[str, str, int], Dict[str, Any]] = {}

    for row in rows:
        # iteration 0 is the shared initial generation: identical across
        # variants, so one entry per (model, sample, iteration)
        key = (row["model"], row["sample_id"], int(row["iteration"]))
        if key not in seen:
            seen[key] = row

    with_data = [
        row for row in seen.values() if row.get("cleaning_used_fence") is not None
    ]

    if not with_data:
        return ["No assembly records with cleaning information."]

    lines = [
        "Answer-format repairs applied by the pipeline before evaluation "
        "(%d assembled sample(s) with cleaning data). auto_closed is an "
        "intervention on the measured object; the rest describe the answer "
        "format and double as an instruction-following signal."
        % len(with_data),
        "",
        "| model | samples | auto_closed | used_fence | signature_suspect | "
        "dropped_leading | relocated_includes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]

    def share(subset: "List[Dict[str, Any]]", column: str) -> str:
        hits = sum(1 for r in subset if r.get(column))
        return _rate(hits, len(subset))

    for model in sorted({row["model"] for row in with_data}):
        subset = [r for r in with_data if r["model"] == model]
        lines.append(
            "| %s | %d | %s | %s | %s | %s | %s |"
            % (
                model,
                len(subset),
                share(subset, "cleaning_auto_closed"),
                share(subset, "cleaning_used_fence"),
                share(subset, "cleaning_signature_suspect"),
                share(subset, "cleaning_dropped_leading_lines"),
                share(subset, "cleaning_relocated_includes"),
            )
        )

    iterations = sorted({int(r["iteration"]) for r in with_data})

    if len(iterations) > 1:
        lines.append("")
        lines.append("By iteration (does the answer format change under repair?):")
        lines.append("")
        lines.append(
            "| iteration | samples | auto_closed | used_fence | "
            "signature_suspect |"
        )
        lines.append("| --- | --- | --- | --- | --- |")

        for iteration in iterations:
            subset = [r for r in with_data if int(r["iteration"]) == iteration]
            lines.append(
                "| %d | %d | %s | %s | %s |"
                % (
                    iteration,
                    len(subset),
                    share(subset, "cleaning_auto_closed"),
                    share(subset, "cleaning_used_fence"),
                    share(subset, "cleaning_signature_suspect"),
                )
            )

    return lines


def completeness_section(rows: "List[Dict[str, Any]]") -> List[str]:
    incomplete = [r for r in rows if not r["data_complete"]]

    lines = [
        "Rows total: %d, incomplete: %d" % (len(rows), len(incomplete)),
    ]

    if incomplete:
        reasons: Counter = Counter()
        for row in incomplete:
            reason = row.get("na_reason") or "unknown"
            # bucket backfill reasons by their stage list
            reasons[reason] += 1

        lines.append("")
        lines.append("| na_reason | rows |")
        lines.append("| --- | --- |")
        for reason, count in sorted(reasons.items()):
            lines.append("| %s | %d |" % (reason, count))

    return lines


def render_markdown(
    rows: "List[Dict[str, Any]]",
    config: Dict[str, Any],
    base_run_id: str,
) -> str:
    variants = list(
        OrderedDict.fromkeys(r["variant"] for r in rows)
    )

    parts: List[str] = [
        "# Consolidated overview — run %s" % base_run_id,
        "",
        "Generated %s. Source: stage JSONLs joined on (sample_id, variant, "
        "iteration); see overview.csv for the flat table. Trajectories are "
        "CARRY-FORWARD: a stopped sample keeps contributing its final "
        "artifact to later iterations (the population stays constant). "
        "Enhanced rates count pass over all non-gated specs "
        "(gated = baseline_incompatible + numerically_unstable)."
        % common.utc_now_iso(),
        "",
        "## Pass-rate trajectories (ParEval vs. enhanced — overfitting view)",
    ]

    for variant in variants:
        parts.append("")
        parts.append("### %s" % variant)
        parts.extend(trajectory_table(rows, variant))

    parts.append("")
    parts.append("## Stop-reason distribution")
    for variant in variants:
        parts.append("")
        parts.append("### %s" % variant)
        parts.extend(stop_reason_table(rows, variant))

    parts.append("")
    parts.append("## Blocking findings per tool over iterations (convergence)")
    parts.append("")
    parts.append(
        "Counts are per produced artifact at that iteration (no carry-"
        "forward — this shows what the loop's artifacts still contain). "
        "ALL enabled tools are listed, not just those with findings."
    )
    for variant in variants:
        parts.append("")
        parts.append("### %s" % variant)
        parts.extend(findings_convergence_table(rows, variant, config))

    parts.append("")
    parts.append("## Blocking findings by error class")
    parts.append("")
    parts.extend(blocking_by_class_section(rows, variants))

    parts.append("")
    parts.append("## Breakdown by problem type and execution model (final state)")
    for variant in variants:
        parts.append("")
        parts.append("### %s" % variant)
        parts.extend(breakdown_table(rows, variant, "problem_type"))
        parts.append("")
        parts.extend(breakdown_table(rows, variant, "execution_model"))

    parts.append("")
    parts.append('## "Statically clean but incorrect" (static_feedback, design §9)')
    parts.append("")
    parts.extend(clean_but_incorrect(rows))

    parts.append("")
    parts.append("## Enhanced tests by execution model")
    parts.append("")
    parts.extend(enhanced_by_execution_model_section(rows))

    parts.append("")
    parts.append("## Runtime cost per tool")
    parts.append("")
    parts.extend(runtime_cost_section(rows))

    parts.append("")
    parts.append("## Generation effort and direct latency")
    parts.append("")
    parts.append(
        "Measurement semantics: thesis/docs/timing-and-effort.md (why batch "
        "wall time is not latency, why reasoning tokens are the primary "
        "effort metric)."
    )
    parts.append("")
    parts.extend(generation_effort_section(rows))

    parts.append("")
    parts.append("## Cleaning interventions")
    parts.append("")
    parts.extend(cleaning_section(rows))

    parts.append("")
    parts.append("## Data completeness")
    parts.append("")
    parts.extend(completeness_section(rows))

    stages = config.get("stages") or {}
    parts.append("")
    parts.append("## Effective config snapshot")
    parts.append("")
    parts.append("### stages.repair")
    parts.append("```json")
    parts.append(json.dumps(stages.get("repair") or {}, indent=2, sort_keys=True))
    parts.append("```")
    parts.append("")
    parts.append("### stages.enhanced_tests")
    parts.append("```json")
    parts.append(json.dumps(stages.get("enhanced_tests") or {}, indent=2, sort_keys=True))
    parts.append("```")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def analysis_dir(config: Dict[str, Any], base_run_id: str) -> Path:
    root = (config.get("outputs") or {}).get("root")
    if root:
        base = Path(root)
    else:
        base = Path(config["outputs"]["intermediate_dir"]).parent
    return base / "analysis" / base_run_id


def main() -> None:
    args = parse_args()

    config = load_config(Path(args.config).resolve())
    profile = common.get_profile(config, args.profile)
    base_run_id = profile["run_id"]

    models = [
        model for model in config.get("models", [])
        if model.get("enabled", False)
        and (args.model_id is None or model.get("id") == args.model_id)
    ]

    if not models:
        raise ValueError("No enabled models matched the selection.")

    out_dir = analysis_dir(config, base_run_id)
    csv_path = out_dir / "overview.csv"
    md_path = out_dir / "overview.md"

    if not args.force and (csv_path.exists() or md_path.exists()):
        raise SystemExit(
            "Overview outputs already exist under %s — use --force to "
            "overwrite." % out_dir
        )

    rows: List[Dict[str, Any]] = []
    for model_config in models:
        model_rows = collect_model_rows(config, base_run_id, model_config["id"])
        if not model_rows:
            print(
                "[%s] no repair state found for run %s — nothing to join "
                "for this model (run the loop first)."
                % (model_config["id"], base_run_id)
            )
        rows.extend(model_rows)

    if not rows:
        raise SystemExit(
            "No rows produced — no model has repair state for run %s."
            % base_run_id
        )

    write_csv(rows, csv_path)
    md_path.write_text(render_markdown(rows, config, base_run_id), encoding="utf-8")

    complete = sum(1 for r in rows if r["data_complete"])
    print("Overview: %d rows (%d complete, %d incomplete)"
          % (len(rows), complete, len(rows) - complete))
    print("  %s" % csv_path)
    print("  %s" % md_path)


if __name__ == "__main__":
    main()
