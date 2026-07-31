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
                    "tsan": {"enabled": False},
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


def tool_entry(ran=True, findings=0, blocking=0, low_confidence=0, seconds=0.5):
    return {
        "ran": ran, "num_findings": findings, "num_blocking": blocking,
        "num_low_confidence": low_confidence, "duration_seconds": seconds,
        "findings": [],
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
            "compiler": tool_entry(findings=1, blocking=1),
            "clang_tidy": tool_entry(findings=1, blocking=0, seconds=1.0),
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
          [{"sample_id": S_SERIAL, "status": "pass"} for _ in range(3)]
          + [{"sample_id": S_SERIAL, "status": "fail"},
             {"sample_id": S_SERIAL, "status": "baseline_incompatible"}])

    # ---- static_feedback iteration 1 ---------------------------------
    iter1 = "%s__static_feedback__iter1" % BASE
    jsonl(config, iter1, "generations.jsonl", [
        {"sample_id": S_SERIAL, "status": {"success": True},
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
        {"sample_id": S_SERIAL, "tools": {"asan_ubsan": tool_entry()}},
    ])
    jsonl(config, iter1, "enhanced_tests.jsonl",
          [{"sample_id": S_SERIAL, "status": "pass"} for _ in range(4)])

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

        serial1 = row_of(rows, S_SERIAL, "static_feedback", 1)
        check("iter1 not shared", serial1["is_shared_initial"] is False)
        check("iter1 verdict pass", serial1["correctness_verdict"] == "pass")
        check("iter1 enhanced 4 pass", serial1["enhanced_pass"] == 4)
        check("iter1 tokens from response usage",
              serial1["repair_prompt_tokens"] == 100
              and serial1["repair_completion_tokens"] == 50)
        check("iter1 status stopped_clean", serial1["status"] == "stopped_clean")
        check("iter1 complete", serial1["data_complete"] is True)

        omp0 = row_of(rows, S_OMP, "static_feedback", 0)
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

        # convergence: compiler blocking 2 at iteration 0 (1 serial + 0 omp
        # = 1)... serial has 1, omp 0 -> 1; iteration 1: 0
        check("convergence table lists compiler", "compiler" in markdown)

        check("clean-but-incorrect uses the final artifact",
              "ParEval-incorrect among them: 0.0% (0/1)" in markdown)

        # cleaning: 2 distinct samples at iteration 0 (shared across
        # variants -> counted once), 1 of them auto_closed and fenced
        check("cleaning section present", "## Cleaning interventions" in markdown)
        check("cleaning share per model",
              "| %s | 3 | 33.3%% (1/3) | 33.3%% (1/3) |" % MODEL in markdown)
        check("cleaning split by iteration",
              "By iteration (does the answer format change under repair?)" in markdown)

        check("completeness counts incomplete rows",
              "Rows total: 6, incomplete: 3" in markdown)
        check("completeness splits reasons",
              "| backfill_missing:dynamic | 2 |" in markdown
              and "| repair_unusable | 1 |" in markdown)

        check("config snapshot included",
              "### stages.repair" in markdown and '"max_iterations": 3' in markdown)


# ---------------------------------------------------------------------------


def main():
    tests = [test_rows, test_csv, test_markdown]

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
