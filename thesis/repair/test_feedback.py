"""Tests for the repair feedback formatter (pattern: test_evaluation.py).

Run:  python thesis/repair/test_feedback.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.repair.feedback import (  # noqa: E402
    IterationRecord,
    build_repair_request,
    collect_findings,
    render_current_feedback,
    render_history_iteration,
    strategy_sources,
)

FAILURES = []


def check(label, condition):
    status = "ok" if condition else "FAIL"
    print("  [%s] %s" % (status, label))
    if not condition:
        FAILURES.append(label)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def finding(tool, check_id, message, line=3, blocking=True, low_confidence=False, file=None):
    return {
        "tool": tool,
        "check_id": check_id,
        "severity": "error" if blocking else "info",
        "message": message,
        "file": file if file is not None else "generated-code.hpp",
        "line": line,
        "column": 1,
        "blocking": blocking,
        "low_confidence": low_confidence,
    }


def base_config(**overrides):
    """Config with enabled/disabled tools and repair defaults."""
    config = {
        "stages": {
            "static_analysis": {
                "tools": {
                    "compiler": {"enabled": True},
                    "clang_tidy": {"enabled": True},
                    "cppcheck": {"enabled": False},  # disabled -> invisible
                },
            },
            "dynamic_analysis": {
                "tools": {
                    "tsan": {"enabled": True},
                    "helgrind": {"enabled": False},  # disabled -> invisible
                },
            },
            "repair": {
                "history_mode": "compressed",
                "feedback": {},
                "strategies": {
                    "static_feedback": {"sources": ["compiler_errors", "static_findings"]},
                    "test_feedback": {
                        "sources": ["compiler_errors", "correctness_verdicts", "dynamic_findings"]
                    },
                    "combined_feedback": {
                        "sources": [
                            "compiler_errors",
                            "static_findings",
                            "correctness_verdicts",
                            "dynamic_findings",
                        ]
                    },
                },
            },
        }
    }

    repair = config["stages"]["repair"]
    for key, value in overrides.items():
        repair[key] = value

    return config


STATIC_RECORD = {
    "tools": {
        "compiler": {
            "findings": [
                finding("compiler", "compile-error", "expected ';' before '}'", line=7),
                finding(
                    "compiler",
                    "-Wunused-variable",
                    "unused variable 'tmp'",
                    line=4,
                    blocking=False,
                ),
                finding(
                    "compiler",
                    "compile-error (in driver/benchmark)",
                    "no matching function for call to 'luFactorize'",
                    line=42,
                    file="cpu.cc",
                ),
            ]
        },
        "clang_tidy": {
            "findings": [
                finding("clang_tidy", "bugprone-narrowing-conversions", "narrowing conversion", line=9),
                finding(
                    "clang_tidy",
                    "clang-analyzer-optin.mpi.MPI-Checker",
                    "request has no matching wait",
                    line=11,
                    low_confidence=True,
                ),
                finding(
                    "clang_tidy",
                    "performance-for-range-copy",
                    "loop variable copied",
                    line=5,
                    blocking=False,
                ),
            ]
        },
        "cppcheck": {  # tool disabled in config -> must never render
            "findings": [finding("cppcheck", "nullPointer", "SHOULD NOT APPEAR", line=1)]
        },
    }
}

DYNAMIC_RECORD = {
    "tools": {
        "tsan": {"findings": [finding("tsan", "tsan-data-race", "data race on A", line=12)]},
        "helgrind": {  # disabled
            "findings": [finding("helgrind", "helgrind-race", "SHOULD NOT APPEAR", line=2)]
        },
    }
}

CORRECTNESS_FAIL = {
    "execution_model": "omp",
    "verdict": "validation_failed",
    "runs": [
        {"params": {"num_threads": 1}, "verdict": "pass"},
        {
            "params": {"num_threads": 4},
            "verdict": "validation_failed",
            # field contract of run_correctness.parse_mismatch_output:
            # shown entries + the MANDATORY total over all differing indices
            "mismatches": [
                {"index": 0, "expected": 1.5, "got": 2.0, "input": 4.0},
                {"index": 3, "expected": -1.5, "got": 0.0},
                {"index": 7, "expected": 2.5, "got": 0.5},
            ],
            "mismatch_total": 47,
        },
        {"params": {"num_threads": 8}, "verdict": "validation_failed"},
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_source_filter_per_strategy():
    print("source filter: strategies see only their sources")
    config = base_config()

    static_fb = render_current_feedback(
        config, strategy_sources(config, "static_feedback"),
        static_record=STATIC_RECORD, dynamic_record=DYNAMIC_RECORD,
        correctness_record=CORRECTNESS_FAIL,
    )
    check("static_feedback: no dynamic findings", "tsan-data-race" not in static_fb)
    check("static_feedback: no test verdicts", "ParEval tests" not in static_fb)
    check("static_feedback: static finding present", "bugprone-narrowing" in static_fb)

    test_fb = render_current_feedback(
        config, strategy_sources(config, "test_feedback"),
        static_record=STATIC_RECORD, dynamic_record=DYNAMIC_RECORD,
        correctness_record=CORRECTNESS_FAIL,
    )
    check("test_feedback: no static findings", "bugprone-narrowing" not in test_fb)
    check("test_feedback: dynamic finding present", "tsan-data-race" in test_fb)
    check("test_feedback: verdicts present", "ParEval tests" in test_fb)


def test_compiler_errors_in_all_strategies():
    print("compiler rule: compile errors are base feedback everywhere")
    config = base_config()

    for strategy in ("static_feedback", "test_feedback", "combined_feedback"):
        rendered = render_current_feedback(
            config, strategy_sources(config, strategy),
            static_record=STATIC_RECORD, dynamic_record=DYNAMIC_RECORD,
            correctness_record=CORRECTNESS_FAIL,
        )
        check("%s contains compile error" % strategy, "expected ';'" in rendered)


def test_driver_error_translation():
    print("driver-located compile error is translated")
    config = base_config()
    rendered = render_current_feedback(
        config, ["compiler_errors"], static_record=STATIC_RECORD
    )
    check("translation text used", "call site in the test driver" in rendered)
    check("raw driver file not mentioned", "cpu.cc" not in rendered)
    check("original message kept", "no matching function" in rendered)


def test_low_confidence_rendering():
    print("low_confidence: prefix, ordering, disabled tools")
    config = base_config(
        feedback={"low_confidence_prefix": "CUSTOM PREFIX:"}
    )
    rendered = render_current_feedback(
        config, ["compiler_errors", "static_findings", "dynamic_findings"],
        static_record=STATIC_RECORD, dynamic_record=DYNAMIC_RECORD,
    )
    check("custom prefix from config", "CUSTOM PREFIX:" in rendered)
    check(
        "low_confidence after normal blocking",
        rendered.find("bugprone-narrowing") < rendered.find("CUSTOM PREFIX:"),
    )
    check("disabled static tool absent", "SHOULD NOT APPEAR" not in rendered)
    check("MPI-Checker finding rendered", "no matching wait" in rendered)


def test_non_blocking_toggle():
    print("include_non_blocking: rendering-only switch")
    config_off = base_config()
    rendered_off = render_current_feedback(
        config_off, ["compiler_errors", "static_findings"], static_record=STATIC_RECORD
    )
    check("default: style finding absent", "performance-for-range-copy" not in rendered_off)
    check("default: compiler warning absent", "-Wunused-variable" not in rendered_off)

    config_on = base_config(feedback={"include_non_blocking": True})
    rendered_on = render_current_feedback(
        config_on, ["compiler_errors", "static_findings"], static_record=STATIC_RECORD
    )
    check("enabled: style finding present", "performance-for-range-copy" in rendered_on)
    check("enabled: compiler warning rides in as static", "-Wunused-variable" in rendered_on)
    check(
        "enabled: own section with header",
        "Non-blocking quality hints" in rendered_on
        and rendered_on.find("Non-blocking quality hints")
        < rendered_on.find("performance-for-range-copy"),
    )

    groups_off = collect_findings(
        config_off, ["compiler_errors", "static_findings"], STATIC_RECORD, None
    )
    groups_on = collect_findings(
        config_on, ["compiler_errors", "static_findings"], STATIC_RECORD, None
    )
    check(
        "blocking count identical regardless of flag",
        len(groups_off["compiler_errors"]) + len(groups_off["blocking"])
        == len(groups_on["compiler_errors"]) + len(groups_on["blocking"]),
    )


def test_history_modes():
    print("history: compressed vs full, no old mismatch numbers in either")
    long_message = "x" * 200
    record = IterationRecord(
        iteration=1,
        cleaned_code="void f() {}",
        static_record={
            "tools": {
                "clang_tidy": {
                    "findings": [finding("clang_tidy", "bugprone-x", long_message, line=6)]
                }
            }
        },
        correctness_record=CORRECTNESS_FAIL,
    )
    sources = ["compiler_errors", "static_findings", "correctness_verdicts"]

    compressed = render_history_iteration(base_config(), sources, record)
    check("compressed: message truncated to 80", ("x" * 80) in compressed and ("x" * 81) not in compressed)
    check("compressed: verdict sentence", "ParEval tests: FAIL (omp at 4/8 threads)" in compressed)
    check("compressed: no mismatch numbers", "expected" not in compressed)

    full = render_history_iteration(base_config(history_mode="full"), sources, record)
    check("full: message untruncated", ("x" * 200) in full)
    check("full: verdicts present", "4 threads" in full)
    check("full: no mismatch numbers either", "expected" not in full)

    style = finding("clang_tidy", "performance-noise", "hint", blocking=False)
    record.static_record["tools"]["clang_tidy"]["findings"].append(style)
    compressed2 = render_history_iteration(
        base_config(feedback={"include_non_blocking": True}), sources, record
    )
    check("compressed never includes non-blocking", "performance-noise" not in compressed2)


def test_mismatch_rendering_current():
    print("mismatch report: bounded with fields, verdict-only without")
    config = base_config()
    with_fields = render_current_feedback(
        config, ["correctness_verdicts"], correctness_record=CORRECTNESS_FAIL
    )
    check("k=3 indices rendered", with_fields.count("index ") == 3)
    check("expected/got present", "expected 1.5, got 2.0" in with_fields)
    check("input value rendered when present", "(input 4.0)" in with_fields)
    check(
        "total > shown renders the remainder",
        "... and 44 more differing indices (47 total)" in with_fields,
    )

    same_total = {
        "execution_model": "omp",
        "verdict": "validation_failed",
        "runs": [
            {
                "params": {"num_threads": 4},
                "verdict": "validation_failed",
                "mismatches": [
                    {"index": 0, "expected": 1.0, "got": 2.0},
                    {"index": 1, "expected": 3.0, "got": 4.0},
                ],
                "mismatch_total": 2,
            }
        ],
    }
    exact = render_current_feedback(config, ["correctness_verdicts"], correctness_record=same_total)
    check("total == shown renders no remainder line", "more differing" not in exact)

    scalar = {
        "execution_model": "serial",
        "verdict": "validation_failed",
        "runs": [
            {
                "params": {},
                "verdict": "validation_failed",
                "mismatches": [{"expected": 7, "got": 4}],
                "mismatch_total": 1,
            }
        ],
    }
    scalar_rendered = render_current_feedback(
        config, ["correctness_verdicts"], correctness_record=scalar
    )
    check("scalar entry without index", "    expected 7, got 4" in scalar_rendered)

    bare = {
        "execution_model": "omp",
        "verdict": "validation_failed",
        "runs": [{"params": {"num_threads": 4}, "verdict": "validation_failed"}],
    }
    without = render_current_feedback(config, ["correctness_verdicts"], correctness_record=bare)
    check("degrades to verdicts", "validation_failed" in without and "expected" not in without)


def test_template_overrides():
    print("templates: every block overridable from config")
    config = base_config(
        feedback={
            "templates": {
                "task_header": "### AUFGABE",
                "current_header": "### JETZT",
                "feedback_header": "### BEFUNDE",
                "instruction": "### ANWEISUNG mit Zeilenhinweis",
                "history_iteration_header": "### Versuch {n}",
            }
        }
    )
    request = build_repair_request(
        task_prompt="write lu",
        history=[IterationRecord(iteration=1, cleaned_code="void old() {}")],
        current_code="void f() {}",
        current_records={"static": STATIC_RECORD, "dynamic": None, "correctness": None},
        strategy="static_feedback",
        config=config,
    )
    for token in ("### AUFGABE", "### Versuch 1", "### JETZT", "### BEFUNDE", "### ANWEISUNG"):
        check("override %s" % token, token in request)
    check(
        "block order task<history<current<feedback<instruction",
        request.find("### AUFGABE")
        < request.find("### Versuch 1")
        < request.find("### JETZT")
        < request.find("### BEFUNDE")
        < request.find("### ANWEISUNG"),
    )


def main():
    tests = [
        test_source_filter_per_strategy,
        test_compiler_errors_in_all_strategies,
        test_driver_error_translation,
        test_low_confidence_rendering,
        test_non_blocking_toggle,
        test_history_modes,
        test_mismatch_rendering_current,
        test_template_overrides,
    ]

    for test in tests:
        test()
        print()

    if FAILURES:
        print("%d FAILURES: %s" % (len(FAILURES), FAILURES))
        sys.exit(1)

    print("All %d repair-feedback tests passed." % len(tests))


if __name__ == "__main__":
    main()
