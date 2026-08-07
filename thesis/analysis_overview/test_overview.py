"""Tests for the consolidated overview (pattern: test_orchestrator.py).

Run:  python thesis/analysis_overview/test_overview.py
"""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.generation import common  # noqa: E402
from thesis.analysis_overview.build_overview import (  # noqa: E402
    COLUMNS,
    NA,
    collect_model_rows,
    render_markdown,
    write_csv,
)

FAILURES = []


def check(label, condition):
    status = "ok" if condition else "FAIL"
    print("  [%s] %s" % (status, label))
    if not condition:
        FAILURES.append(label)


MODEL = "m1"
BASE = "base_run"
S_SERIAL = "m1__dense_la__00_dense_la_lu_decomp__serial__sample_0"
S_OMP = "m1__stencil__50_stencil_jacobi__omp__sample_0"

# real parameterizable benchmark (marker check reads the repo driver)
REAL_BENCHMARK = "drivers/cpp/benchmarks/dense_la/00_dense_la_lu_decomp"


def fixture_config(tmp):
    return {
        "outputs": {
            "raw_dir": (Path(tmp) / "raw").as_posix(),
            "intermediate_dir": (Path(tmp) / "intermediate").as_posix(),
        },
        "stages": {
            "static_analysis": {
                "tools": {
                    "compiler": {"enabled": True},
                    "clang_tidy": {"enabled": True},
                    # off here so the fixture's static records stay a minimal
                    # two-tool set; gcc_analyzer is enabled in the real config
                    "gcc_analyzer": {"enabled": False},
                    "cppcheck": {"enabled": False},
                    "infer": {"enabled": False},
                    "parcoach": {"enabled": False},
                    "llov": {"enabled": False},
                }
            },
            "dynamic_analysis": {
                "tools": {
                    "asan_ubsan": {"enabled": True},
                    # enabled but never present in any record: the
                    # convergence table must show it as n/a, not hide it
                    "tsan": {"enabled": True},
                    "memcheck": {"enabled": False},
                    "must": {"enabled": False},
                }
            },
            "correctness_tests": {},
            "enhanced_tests": {},
            "repair": {
                "max_iterations": 3,
                "variants": ["static_feedback", "test_feedback"],
            },
        },
    }


def jsonl(config, run_id, file_name, records, raw=False):
    root = Path(config["outputs"]["raw_dir" if raw else "intermediate_dir"])
    path = root / run_id / MODEL / file_name
    if path.exists():
        path.unlink()
    for record in records:
        common.append_jsonl(path, record)


def tool_entry(ran=True, findings=0, blocking=0, low_confidence=0, seconds=0.5,
               error=None, finding_entries=None):
    return {
        "ran": ran, "num_findings": findings, "num_blocking": blocking,
        "num_low_confidence": low_confidence, "duration_seconds": seconds,
        "findings": finding_entries or [], "error": error,
    }


def build_world(tmp):
    config = fixture_config(tmp)
    intermediate = Path(config["outputs"]["intermediate_dir"])

    # ---- state trails ------------------------------------------------
    sf_state = intermediate / BASE / MODEL / "repair" / "static_feedback" / "state.jsonl"
    for sample_id, iteration, status in [
        (S_SERIAL, 0, "active"), (S_SERIAL, 1, "stopped_clean"),
        (S_OMP, 0, "active"), (S_OMP, 1, "repair_unusable"),
    ]:
        common.append_jsonl(sf_state, {
            "sample_id": sample_id, "iteration": iteration, "status": status,
            "stop_reason": "reason-%s-%d" % (status, iteration),
        })

    tf_state = intermediate / BASE / MODEL / "repair" / "test_feedback" / "state.jsonl"
    for sample_id in (S_SERIAL, S_OMP):
        common.append_jsonl(tf_state, {
            "sample_id": sample_id, "iteration": 0,
            "status": "stopped_tests_pass", "stop_reason": "tests pass",
        })

    # ---- base run (iteration 0, shared) ------------------------------
    jsonl(config, BASE, "assembly.jsonl", [
        {"sample_id": S_SERIAL, "assembled": True,
         "drivers": {"benchmark_dir": REAL_BENCHMARK},
         # the interesting case: braces had to be closed by the pipeline
         "cleaning": {"used_fence": True, "auto_closed": True,
                      "braces_balanced": False, "signature_suspect": False,
                      "dropped_leading_lines": 2, "dropped_trailing_lines": 0,
                      "dropped_duplicated_prompt_lines": 0,
                      "relocated_includes": ["#include <vector>"]}},
        {"sample_id": S_OMP, "assembled": True,
         "drivers": {"benchmark_dir": "drivers/cpp/benchmarks/stencil/50_stencil_jacobi"},
         "cleaning": {"used_fence": False, "auto_closed": False,
                      "braces_balanced": True, "signature_suspect": False,
                      "dropped_leading_lines": 0, "dropped_trailing_lines": 0,
                      "dropped_duplicated_prompt_lines": 0,
                      "relocated_includes": []}},
    ])
    jsonl(config, BASE, "static_analysis.jsonl", [
        {"sample_id": S_SERIAL, "tools": {
            "compiler": tool_entry(findings=1, blocking=1, finding_entries=[
                {"check_id": "error", "blocking": True,
                 "message": "no matching function"}]),
            "clang_tidy": tool_entry(findings=1, blocking=0, seconds=1.0,
                                     finding_entries=[
                {"check_id": "misc-const-correctness", "blocking": False,
                 "message": "style"}]),
        }},
        {"sample_id": S_OMP, "tools": {
            "compiler": tool_entry(),
            "clang_tidy": tool_entry(),
        }},
    ])
    jsonl(config, BASE, "correctness.jsonl", [
        {"sample_id": S_SERIAL, "verdict": "validation_failed",
         "compile": {"ok": True, "duration_seconds": 1.5},
         "runs": [{"verdict": "validation_failed", "mismatch_total": 42,
                   "duration_seconds": 2.0}]},
        {"sample_id": S_OMP, "verdict": "validation_failed",
         "compile": {"ok": True, "duration_seconds": 1.0},
         "runs": [{"verdict": "validation_failed", "duration_seconds": 1.0}]},
    ])
    jsonl(config, BASE, "dynamic_analysis.jsonl", [
        {"sample_id": S_SERIAL, "tools": {"asan_ubsan": tool_entry(seconds=3.0)}},
        # S_OMP dynamic record deliberately MISSING -> backfill_missing
    ])
    jsonl(config, BASE, "enhanced_tests.jsonl",
          [{"sample_id": S_SERIAL, "status": "pass", "duration_seconds": 0.2}
           for _ in range(3)]
          + [{"sample_id": S_SERIAL, "status": "fail", "duration_seconds": 0.2},
             {"sample_id": S_SERIAL, "status": "baseline_incompatible",
              "duration_seconds": 0.2}])

    # ---- base generations (raw): one direct, one batch record ---------
    jsonl(config, BASE, "generations.jsonl", [
        # v3 direct record WITH usage_normalized (preferred path)
        {"sample_id": S_SERIAL,
         "status": {"success": True, "timing_mode": "direct",
                    "duration_seconds": 4.2},
         "api_response": {
             "usage": {"input_tokens": 200, "output_tokens": 80,
                       "output_tokens_details": {"thinking_tokens": 128}},
             "usage_normalized": {"input_tokens": 200, "output_tokens": 80,
                                  "reasoning_tokens": 128}}},
        # batch record: NO latency by design, raw usage only (tests the
        # on-the-fly normalization fallback)
        {"sample_id": S_OMP,
         "status": {"success": True, "timing_mode": "batch",
                    "duration_seconds": None,
                    "batch_submitted_at_utc": "2026-08-01T00:00:00Z",
                    "batch_completed_at_utc": "2026-08-01T04:00:00Z"},
         "api_response": {
             "usage": {"input_tokens": 300, "output_tokens": 60,
                       "output_tokens_details": {"reasoning_tokens": 44}}}},
    ], raw=True)

    # ---- static_feedback iteration 1 ---------------------------------
    iter1 = "%s__static_feedback__iter1" % BASE
    jsonl(config, iter1, "generations.jsonl", [
        {"sample_id": S_SERIAL,
         "status": {"success": True, "timing_mode": "direct",
                    "duration_seconds": 2.0},
         "api_response": {"usage": {"prompt_tokens": 100,
                                    "completion_tokens": 50}}},
        {"sample_id": S_OMP, "status": {"success": False,
                                        "error_type": "ModelRefusal"}},
    ], raw=True)
    jsonl(config, iter1, "assembly.jsonl", [
        # after one round of feedback the answer arrives clean and unfenced
        {"sample_id": S_SERIAL, "assembled": True,
         "drivers": {"benchmark_dir": REAL_BENCHMARK},
         "cleaning": {"used_fence": False, "auto_closed": False,
                      "braces_balanced": True, "signature_suspect": False,
                      "dropped_leading_lines": 0, "dropped_trailing_lines": 0,
                      "dropped_duplicated_prompt_lines": 0,
                      "relocated_includes": []}},
        {"sample_id": S_OMP, "assembled": False,
         "skip_reason": "generation not successful (error_type=ModelRefusal)"},
    ])
    jsonl(config, iter1, "static_analysis.jsonl", [
        {"sample_id": S_SERIAL, "tools": {
            "compiler": tool_entry(), "clang_tidy": tool_entry(),
        }},
    ])
    jsonl(config, iter1, "correctness.jsonl", [
        {"sample_id": S_SERIAL, "verdict": "pass",
         "compile": {"ok": True, "duration_seconds": 1.0},
         "runs": [{"verdict": "pass", "duration_seconds": 1.0}]},
    ])
    jsonl(config, iter1, "dynamic_analysis.jsonl", [
        # a TIMED-OUT run: its 120 s are the configured limit, not a
        # measured duration — the runtime summary must exclude it
        {"sample_id": S_SERIAL, "tools": {"asan_ubsan": tool_entry(
            seconds=120.0, error="asan_ubsan timed out")}},
    ])
    # iter1 enhanced files use the NEW timing semantics (grouped builds):
    # duration_seconds = run only, compile times per group, summary marker.
    # The BASE run above deliberately has NO summary -> legacy semantics.
    jsonl(config, iter1, "enhanced_tests.jsonl",
          [{"sample_id": S_SERIAL, "status": "pass", "duration_seconds": 0.1}
           for _ in range(4)])
    jsonl(config, iter1, "enhanced_build_groups.jsonl", [
        {"sample_id": S_SERIAL, "execution_model": "serial", "size": 2,
         "spec_count": 2, "compile_seconds": 2.0, "build_status": "success",
         "build_stderr": ""},
        {"sample_id": S_SERIAL, "execution_model": "serial", "size": 7,
         "spec_count": 2, "compile_seconds": 1.5, "build_status": "success",
         "build_stderr": ""},
    ])
    common.write_json(
        Path(config["outputs"]["intermediate_dir"]) / iter1 / MODEL
        / "enhanced_tests_summary.json",
        {"timing_semantics": "run_only_plus_build_groups",
         "build_groups_file": "enhanced_build_groups.jsonl"},
    )

    return config


def row_of(rows, sample_id, variant, iteration):
    for row in rows:
        if (row["sample_id"] == sample_id and row["variant"] == variant
                and row["iteration"] == iteration):
            return row
    raise AssertionError(
        "row not found: %s/%s/%d" % (sample_id, variant, iteration)
    )


# ---------------------------------------------------------------------------


def test_rows():
    print("row grid, key columns, NA logic")

    with tempfile.TemporaryDirectory() as tmp:
        config = build_world(tmp)
        rows = collect_model_rows(config, BASE, MODEL)

        check("6 rows: 4 static_feedback + 2 test_feedback", len(rows) == 6)

        serial0 = row_of(rows, S_SERIAL, "static_feedback", 0)
        check("iteration 0 marked shared", serial0["is_shared_initial"] is True)
        check("parse: execution model", serial0["execution_model"] == "serial")
        check("parse: problem type", serial0["problem_type"] == "dense_la")
        check("parse: benchmark", serial0["benchmark"] == "00_dense_la_lu_decomp")
        check("blocking_count 1", serial0["blocking_count"] == 1)
        check("non_blocking_count 1", serial0["non_blocking_count"] == 1)
        check("compiler_blocking 1", serial0["compiler_blocking"] == 1)
        check("verdict carried", serial0["correctness_verdict"] == "validation_failed")
        check("grid points 0/1", serial0["correctness_pass_gridpoints"] == "0/1")
        check("mismatch_total 42", serial0["mismatch_total"] == 42)
        check("enhanced pass/fail/gated 3/1/1",
              serial0["enhanced_pass"] == 3 and serial0["enhanced_fail"] == 1
              and serial0["enhanced_gated"] == 1)
        check("status from trail", serial0["status"] == "active")
        check("durations summed",
              serial0["duration_compile_seconds"] == 1.5
              and serial0["duration_tests_seconds"] == 2.0
              and serial0["duration_analysis_seconds"] == 4.5)
        check("row complete", serial0["data_complete"] is True)
        check("no repair tokens at iteration 0",
              serial0["repair_prompt_tokens"] is None)

        # ---- timing/effort columns (Teil 3) --------------------------
        check("per-tool seconds",
              serial0["compiler_seconds"] == 0.5
              and serial0["clang_tidy_seconds"] == 1.0
              and serial0["asan_ubsan_seconds"] == 3.0)
        check("no timeout flags on clean runs",
              serial0["asan_ubsan_timed_out"] is False)
        check("stage sums split",
              serial0["static_seconds"] == 1.5
              and serial0["dynamic_seconds"] == 3.0
              and serial0["correctness_seconds"] == 3.5
              and serial0["enhanced_seconds"] == 1.0)
        check("generation effort joined at iteration 0",
              serial0["generation_input_tokens"] == 200
              and serial0["generation_reasoning_tokens"] == 128)
        check("direct record carries latency",
              serial0["generation_timing_mode"] == "direct"
              and serial0["generation_duration_seconds"] == 4.2)

        # ---- error classes (Fehlerklassen-Ebene) ---------------------
        check("compile error classified as build",
              serial0["class_build_blocking"] == 1)
        check("non-blocking finding carries no class count",
              serial0["class_other_blocking"] == 0)
        check("0 is a statement, not NA (analysis ran)",
              serial0["class_race_blocking"] == 0)

        serial1 = row_of(rows, S_SERIAL, "static_feedback", 1)
        check("iter1 not shared", serial1["is_shared_initial"] is False)
        check("iter1 verdict pass", serial1["correctness_verdict"] == "pass")
        check("iter1 enhanced 4 pass", serial1["enhanced_pass"] == 4)
        check("iter1 tokens from response usage",
              serial1["repair_prompt_tokens"] == 100
              and serial1["repair_completion_tokens"] == 50)
        check("iter1 status stopped_clean", serial1["status"] == "stopped_clean")
        check("iter1 complete", serial1["data_complete"] is True)
        check("timed-out tool flagged, duration kept",
              serial1["asan_ubsan_timed_out"] is True
              and serial1["asan_ubsan_seconds"] == 120.0)

        omp0 = row_of(rows, S_OMP, "static_feedback", 0)
        check("batch record: NO latency, tokens normalized on the fly",
              omp0["generation_timing_mode"] == "batch"
              and omp0["generation_duration_seconds"] is None
              and omp0["generation_reasoning_tokens"] == 44)
        check("omp iter0 incomplete: dynamic backfill missing",
              omp0["data_complete"] is False
              and omp0["na_reason"] == "backfill_missing:dynamic")
        check("omp iter0 still carries what exists",
              omp0["correctness_verdict"] == "validation_failed")
        check("omp: enhanced not expected -> no enhanced NA reason",
              "enhanced" not in (omp0["na_reason"] or ""))

        omp1 = row_of(rows, S_OMP, "static_feedback", 1)
        check("unusable row kept with NA markers (never dropped)",
              omp1["data_complete"] is False
              and omp1["na_reason"] == "repair_unusable")
        check("unusable row: analytic columns empty",
              omp1["build_ok"] is None and omp1["blocking_count"] is None)
        check("unusable row: class columns stay NA (nothing analyzed)",
              omp1["class_build_blocking"] is None)
        check("unusable row keeps the state", omp1["status"] == "repair_unusable")

        tf0 = row_of(rows, S_SERIAL, "test_feedback", 0)
        check("test_feedback sees the same shared initial data",
              tf0["is_shared_initial"] is True and tf0["enhanced_pass"] == 3)
        check("variant-specific status on shared row",
              tf0["status"] == "stopped_tests_pass")


def test_csv():
    print("CSV serialization")

    with tempfile.TemporaryDirectory() as tmp:
        config = build_world(tmp)
        rows = collect_model_rows(config, BASE, MODEL)

        csv_path = Path(tmp) / "overview.csv"
        write_csv(rows, csv_path)

        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = list(csv.reader(handle))

        check("header equals column contract", reader[0] == COLUMNS)
        check("6 data rows", len(reader) == 7)

        by_key = {
            (r[COLUMNS.index("sample_id")], r[COLUMNS.index("variant")],
             r[COLUMNS.index("iteration")]): r
            for r in reader[1:]
        }
        omp1 = by_key[(S_OMP, "static_feedback", "1")]
        check("NA marker in CSV", omp1[COLUMNS.index("build_ok")] == NA)
        check("data_complete false serialized",
              omp1[COLUMNS.index("data_complete")] == "false")
        check("booleans serialized lowercase",
              by_key[(S_SERIAL, "static_feedback", "0")][
                  COLUMNS.index("is_shared_initial")] == "true")


def test_markdown():
    print("markdown summary numbers")

    with tempfile.TemporaryDirectory() as tmp:
        config = build_world(tmp)
        rows = collect_model_rows(config, BASE, MODEL)
        markdown = render_markdown(rows, config, BASE)

        # trajectory static_feedback:
        #   iter0: ParEval 0/2 fail, enhanced 3 of 4 counted specs
        #   iter1: serial->iter1 (pass, enhanced 4/4), omp carries its
        #          ITER-0 artifact (unusable never displaces it) -> ParEval
        #          1/2; enhanced only serial contributes -> 4/4
        check("trajectory iter0 ParEval", "| 0 | 2 | 0.0% (0/2) | 75.0% (3/4) |" in markdown)
        check("trajectory iter1 carry-forward",
              "| 1 | 2 | 50.0% (1/2) | 100.0% (4/4) |" in markdown)

        check("stop distribution counts clean",
              "| stopped_clean | 1 |" in markdown)
        check("stop distribution counts unusable",
              "| repair_unusable | 1 |" in markdown)

        # convergence: ALL enabled tools appear as columns (config-driven,
        # not "tools with findings"); tsan is enabled but present in no
        # record -> n/a everywhere, asan_ubsan ran with 0 findings -> 0
        check("convergence lists all enabled tools incl. finding-free ones",
              "| iteration | artifacts | compiler | clang_tidy | asan_ubsan | tsan |"
              in markdown)
        check("enabled-but-never-ran tool shows n/a, ran-and-clean shows 0",
              "| 0 | 2 | 1 | 0 | 0 | n/a |" in markdown)

        # error classes: the compile error surfaces as class `build`,
        # cells are "findings (samples)"
        check("class section present",
              "## Blocking findings by error class" in markdown)
        check("class x iteration table rendered",
              "**static_feedback — class x iteration" in markdown)
        check("build class counted with sample dedup",
              "| 0 | 2 | 1 (1) |" in markdown)
        check("class x model final-state table rendered",
              "**static_feedback — class x model" in markdown)
        check("class x execution model at iteration 0 rendered",
              "**class x execution model at iteration 0" in markdown)

        check("clean-but-incorrect uses the final artifact",
              "ParEval-incorrect among them: 0.0% (0/1)" in markdown)

        # cleaning: 2 distinct samples at iteration 0 (shared across
        # variants -> counted once), 1 of them auto_closed and fenced
        check("cleaning section present", "## Cleaning interventions" in markdown)
        check("cleaning share per model",
              "| %s | 3 | 33.3%% (1/3) | 33.3%% (1/3) |" % MODEL in markdown)
        check("cleaning split by iteration",
              "By iteration (does the answer format change under repair?)" in markdown)

        # runtime cost: asan serial = iter0 (3.0 s) + iter1 (120 s TIMED OUT,
        # excluded from median/p95) -> n=2, median 3.00, timeouts 1/2;
        # iteration-0 rows are deduped across the two variants
        check("runtime section present", "## Runtime cost per tool" in markdown)
        check("timeouts excluded from median and counted",
              "| asan_ubsan | serial | 2 | 3.00 | 3.00 | 50.0% (1/2) |" in markdown)
        check("compiler runtime aggregated",
              "| compiler | serial | 2 | 0.50 | 0.50 | 0.0% (0/2) |" in markdown)

        # effort: iter0 deduped -> serial (200/80/128) + omp (300/60/44):
        # medians 250/70/86, reasoning sum 172; iter1 -> serial only, no
        # reasoning field -> NA
        check("effort section present",
              "## Generation effort and direct latency" in markdown)
        check("effort medians per model x iteration",
              "| %s | 0 | 2 | 250 | 70 | 86 | 172 |" % MODEL in markdown)
        check("missing reasoning field renders NA",
              "| %s | 1 | 1 | 100 | 50 | NA | NA |" % MODEL in markdown)

        # latency: DIRECT records only (4.2 iter0 serial + 2.0 iter1);
        # the batch record must not contribute
        check("latency only from direct records",
              "| %s | 2 | 3.10 | 4.20 |" % MODEL in markdown)

        check("completeness counts incomplete rows",
              "Rows total: 6, incomplete: 3" in markdown)
        check("completeness splits reasons",
              "| backfill_missing:dynamic | 2 |" in markdown
              and "| repair_unusable | 1 |" in markdown)

        check("config snapshot included",
              "### stages.repair" in markdown and '"max_iterations": 3' in markdown)


# ---------------------------------------------------------------------------


def test_enhanced_timing_semantics():
    print("enhanced timing: legacy vs run_only_plus_build_groups per run")

    with tempfile.TemporaryDirectory() as tmp:
        config = build_world(tmp)
        rows = collect_model_rows(config, BASE, MODEL)

        serial0 = row_of(rows, S_SERIAL, "static_feedback", 0)
        check("legacy run (no summary marker): sum of durations as before",
              serial0["enhanced_seconds"] == 1.0)

        serial1 = row_of(rows, S_SERIAL, "static_feedback", 1)
        check("grouped run: run durations + group compile times",
              serial1["enhanced_seconds"] == 3.9)  # 4x0.1 + 2.0 + 1.5

        # interrupted-run resilience: the summary write is the LAST step of
        # a run — kill the summary (died before write) and truncate the
        # trailing groups line (hard kill mid-append). The groups file's
        # presence must still classify the run as run-only, and the
        # truncated line must not abort the build.
        iter1_dir = (Path(config["outputs"]["intermediate_dir"])
                     / ("%s__static_feedback__iter1" % BASE) / MODEL)
        (iter1_dir / "enhanced_tests_summary.json").unlink()
        with (iter1_dir / "enhanced_build_groups.jsonl").open(
                "a", encoding="utf-8") as handle:
            handle.write('{"sample_id": "x", "compile_secon')

        rows = collect_model_rows(config, BASE, MODEL)
        serial1 = row_of(rows, S_SERIAL, "static_feedback", 1)
        check("no summary: groups file presence classifies as run-only",
              serial1["enhanced_seconds"] == 3.9)

        # legacy config with a non-.jsonl output name: the runner rejects
        # such names now, but the READ-ONLY join must degrade to
        # legacy-semantics records instead of crashing on old data
        config["stages"]["enhanced_tests"]["output_file_name"] = "weird_name"
        try:
            rows = collect_model_rows(config, BASE, MODEL)
            check("non-.jsonl legacy config: overview degrades, no crash",
                  len(rows) == 6)
        except ValueError:
            check("non-.jsonl legacy config: overview degrades, no crash", False)


def test_legacy_timing_classification():
    print("legacy v2 records: batch pseudo-durations never become latency")
    from thesis.analysis_overview.build_overview import apply_generation_columns

    def fresh_row():
        return {"generation_timing_mode": None,
                "generation_duration_seconds": None,
                "generation_input_tokens": None,
                "generation_output_tokens": None,
                "generation_reasoning_tokens": None}

    # legacy v2 INITIAL-generation batch record: no timing_mode, no marker
    # in the record — the old batch poll stamped ~0 s of poll-side
    # processing as duration_seconds. Only the run summary's api_mode
    # identifies it; its pseudo-duration must NOT become latency.
    legacy_batch = {
        "status": {"success": True, "duration_seconds": 0.004},
        "api_response": {"usage": {"input_tokens": 10, "output_tokens": 5}},
    }
    row = fresh_row()
    apply_generation_columns(row, legacy_batch, run_api_mode="batch")
    check("summary api_mode classifies legacy batch",
          row["generation_timing_mode"] == "batch")
    check("pseudo-duration excluded from latency",
          row["generation_duration_seconds"] is None)
    check("tokens still counted", row["generation_input_tokens"] == 10)

    # legacy v2 REPAIR batch record: carries generation_parameters.api_mode
    # (set by the orchestrator's batch merge) — wins even when the run
    # summary is absent/direct
    repair_batch = {
        "status": {"success": True, "duration_seconds": None},
        "generation_parameters": {"api_mode": "batch", "batch_id": "b-1"},
        "api_response": {"usage": {"input_tokens": 10, "output_tokens": 5}},
    }
    row = fresh_row()
    apply_generation_columns(row, repair_batch, run_api_mode="direct")
    check("record marker classifies repair batch",
          row["generation_timing_mode"] == "batch")

    # plain legacy v2 direct record: real latency, kept
    legacy_direct = {
        "status": {"success": True, "duration_seconds": 5.2},
        "api_response": {"usage": {"input_tokens": 10, "output_tokens": 5}},
    }
    row = fresh_row()
    apply_generation_columns(row, legacy_direct, run_api_mode="direct")
    check("legacy direct keeps its latency",
          row["generation_timing_mode"] == "direct"
          and row["generation_duration_seconds"] == 5.2)

    # v3 record: explicit timing_mode is authoritative over everything
    v3_direct = {
        "status": {"success": True, "timing_mode": "direct",
                   "duration_seconds": 3.0},
        "api_response": {"usage": {"input_tokens": 10, "output_tokens": 5}},
    }
    row = fresh_row()
    apply_generation_columns(row, v3_direct, run_api_mode="batch")
    check("explicit timing_mode beats the run api_mode",
          row["generation_timing_mode"] == "direct"
          and row["generation_duration_seconds"] == 3.0)


def test_class_dedup_and_cells():
    print("error classes: cross-tool sample dedup (redundancy rule)")
    from thesis.analysis_overview.build_overview import _class_cells
    from thesis.evaluation.finding_classes import classify_finding

    # llov and tsan report the SAME race on one sample: two findings land
    # in the row's race counter...
    row = {"class_%s_blocking" % name: 0 for name in
           ("memory", "uninitialized", "null_deref", "arithmetic", "race",
            "deadlock", "mpi_usage", "api_misuse", "build", "other")}
    for tool, check_id in (("llov", "llov-data-race"), ("tsan", "tsan-data-race")):
        cls = classify_finding(tool, check_id)
        row["class_%s_blocking" % cls] += 1

    cells = _class_cells([row])
    check("llov+tsan same race -> findings 2", cells["race"][0] == 2)
    check("llov+tsan same race -> samples 1 (deduplicated)",
          cells["race"][1] == 1)

    # a second sample without the race: sample rate 1 of 2, sums unchanged
    clean = dict(row)
    clean["class_race_blocking"] = 0
    cells = _class_cells([row, clean])
    check("sample rate counts rows with >=1", cells["race"] == (2, 1))

    # rows with None (nothing analyzed) are excluded from both numbers
    cells = _class_cells([row, {"class_race_blocking": None}])
    check("NA rows excluded", cells["race"] == (2, 1))


def main():
    tests = [test_rows, test_csv, test_markdown,
             test_enhanced_timing_semantics,
             test_legacy_timing_classification, test_class_dedup_and_cells]

    for test in tests:
        test()
        print()

    if FAILURES:
        print("FAILED (%d):" % len(FAILURES))
        for label in FAILURES:
            print("  - " + label)
        sys.exit(1)

    print("All %d overview test groups passed." % len(tests))


if __name__ == "__main__":
    main()
