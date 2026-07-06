"""Tests for the evaluation framework and the initial tools.

Run:
    python thesis/evaluation/test_evaluation.py

The compile/run tests require g++ and the repo's drivers; they are skipped
with a printed notice if g++ is unavailable.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import framework
from thesis.evaluation.build_config import (
    get_build_config,
    get_launch_config,
    resolve_compiler,
)
from thesis.evaluation.tools import (
    CppcheckTool,
    parse_gcc_clang_diagnostics,
    register_default_tools,
)


def check(name: str, condition: bool) -> None:
    print(f"  [{'ok' if condition else 'FAIL'}] {name}")
    if not condition:
        raise AssertionError(name)


def test_build_config() -> None:
    print("build config: compiler and flag selection")
    serial = get_build_config("serial", "g++")
    check("serial uses g++", serial.compiler == "g++")
    check("serial no openmp", not serial.needs_openmp)
    check("serial macro", serial.macro == "USE_SERIAL")

    omp = get_build_config("omp", "g++")
    check("omp has -fopenmp", "-fopenmp" in omp.cxxflags)

    mpi = get_build_config("mpi", "g++")
    check("mpi uses mpicxx regardless of primary", mpi.compiler == "mpicxx")

    clang_omp = get_build_config("omp", "clang++")
    check("primary compiler respected", clang_omp.compiler == "clang++")

    diag = get_build_config("serial", "g++", diagnostic=True)
    check("diagnostic flags present", "-Wall" in diag.cxxflags)


def test_resolve_compiler() -> None:
    print("compiler resolution")
    check("mpi -> mpicxx", resolve_compiler("mpi", "g++")[0] == "mpicxx")
    check("omp needs openmp", resolve_compiler("omp", "g++")[1] is True)
    check("serial no openmp", resolve_compiler("serial", "g++")[1] is False)


def test_launch_config() -> None:
    print("launch config: run commands")
    serial = get_launch_config("serial")
    argv, env = serial.command("/tmp/a.out", {})
    check("serial direct exec", argv == ["/tmp/a.out"])

    omp = get_launch_config("omp")
    argv, env = omp.command("/tmp/a.out", {"num_threads": 4})
    check("omp sets OMP_NUM_THREADS", env.get("OMP_NUM_THREADS") == "4")
    check("omp passes thread arg", "4" in argv)

    mpi = get_launch_config("mpi")
    argv, env = mpi.command("/tmp/a.out", {"num_procs": 4})
    check("mpi uses mpirun -np", argv[:3] == ["mpirun", "-np", "4"])


def test_gcc_parser() -> None:
    print("gcc/clang diagnostic parser")
    stderr = (
        "generated-code.hpp:5:10: warning: unused variable 'x' [-Wunused-variable]\n"
        "generated-code.hpp:8:3: error: 'foo' was not declared in this scope\n"
    )
    findings = parse_gcc_clang_diagnostics(stderr, "compiler")
    check("two findings", len(findings) == 2)
    check("warning not blocking", not findings[0].blocking)
    check("flag captured", findings[0].check_id == "-Wunused-variable")
    check("error blocking", findings[1].blocking)
    check("line parsed", findings[1].line == 8)


def test_cppcheck_parser() -> None:
    print("cppcheck XML parser")
    xml = (
        '<results version="2"><cppcheck version="2.13.0"/><errors>'
        '<error id="uninitvar" severity="error" msg="Uninitialized variable: y">'
        '<location file="generated-code.hpp" line="12" column="5"/></error>'
        '<error id="unusedVariable" severity="style" msg="Unused: z">'
        '<location file="generated-code.hpp" line="3" column="9"/></error>'
        "</errors></results>"
    )
    findings = CppcheckTool()._parse_xml(xml)
    check("two findings", len(findings) == 2)
    check("error blocking", findings[0].blocking and findings[0].line == 12)
    check("style not blocking", not findings[1].blocking)


def test_registry() -> None:
    print("tool registry")
    register_default_tools("g++")
    check("compiler registered", "compiler" in framework.registered_tools())
    check("cppcheck registered", "cppcheck" in framework.registered_tools())
    check("clang_tidy registered", "clang_tidy" in framework.registered_tools())
    check("infer registered", "infer" in framework.registered_tools())
    check("parcoach registered", "parcoach" in framework.registered_tools())
    check("llov registered", "llov" in framework.registered_tools())


def test_finding_serialization() -> None:
    print("finding/result serialization")
    f = framework.Finding(
        tool="compiler", check_id="-Wfoo", severity="warning", message="m", blocking=False
    )
    result = framework.ToolResult(
        tool="compiler", ran=True, exit_code=0, duration_seconds=1.0, findings=[f]
    )
    d = result.to_dict()
    check("num_findings reported", d["num_findings"] == 1)
    check("num_blocking reported", d["num_blocking"] == 0)
    check("round-trips through json", json.loads(json.dumps(d))["tool"] == "compiler")


def test_clang_tidy_helpers() -> None:
    print("clang-tidy helpers: offset->line and blocking classification")
    from thesis.evaluation.tools import offset_to_line_col, is_blocking_check

    text = "line1\nline2\nline3\n"
    check("offset 0 -> (1,1)", offset_to_line_col(text, 0) == (1, 1))
    check("offset 6 -> (2,1)", offset_to_line_col(text, 6) == (2, 1))
    check("offset 8 -> (2,3)", offset_to_line_col(text, 8) == (2, 3))

    check("bugprone blocking", is_blocking_check("bugprone-use-after-move"))
    check("clang-analyzer blocking", is_blocking_check("clang-analyzer-cplusplus.NewDeleteLeaks"))
    check("concurrency blocking", is_blocking_check("concurrency-mt-unsafe"))
    check("mpi blocking", is_blocking_check("mpi-type-mismatch"))
    check("openmp blocking", is_blocking_check("openmp-use-default-none"))
    check("performance not blocking", not is_blocking_check("performance-for-range-copy"))


def test_clang_tidy_yaml_parse() -> None:
    print("clang-tidy export-fixes YAML parsing")
    import tempfile
    from thesis.evaluation.tools import ClangTidyTool
    from thesis.evaluation.framework import AssembledSample

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "generated-code.hpp"
        src.write_text("void f() {\n  int x = 0;\n  (void)x;\n}\n")

        fixes = Path(tmp) / "fixes.yaml"
        fixes.write_text(
            "---\n"
            f"MainSourceFile: '{src}'\n"
            "Diagnostics:\n"
            "  - DiagnosticName: bugprone-use-after-move\n"
            "    DiagnosticMessage:\n"
            "      Message: 'used after move'\n"
            f"      FilePath: '{src}'\n"
            "      FileOffset: 13\n"
            "    Level: Warning\n"
            "  - DiagnosticName: performance-for-range-copy\n"
            "    DiagnosticMessage:\n"
            "      Message: 'expensive copy'\n"
            f"      FilePath: '{src}'\n"
            "      FileOffset: 13\n"
            "    Level: Warning\n"
            # Diagnostic in the benchmark driver, not the model file: since
            # clang-tidy now analyzes the full TU (cpu.cc) such diagnostics
            # appear and MUST be filtered out.
            "  - DiagnosticName: bugprone-integer-division\n"
            "    DiagnosticMessage:\n"
            "      Message: 'in the driver'\n"
            "      FilePath: '/elsewhere/cpu.cc'\n"
            "      FileOffset: 3\n"
            "    Level: Warning\n"
        )

        sample = AssembledSample(
            sample_id="x", model_id="m", run_id="r", execution_model="serial",
            problem_type="p", name="n", source_path=src,
            benchmark_dir=Path(tmp), model_driver_file="", assembly_entry={},
        )

        findings = ClangTidyTool()._parse_fixes(fixes, sample)
        check("non-model finding filtered out", len(findings) == 2)
        check("all findings in model file", all(f.file == src.name for f in findings))
        check("bugprone is blocking", findings[0].blocking)
        check("performance not blocking", not findings[1].blocking)
        check("line computed from offset", findings[0].line == 2)


def test_cppcheck_filtering() -> None:
    print("cppcheck: findings filtered to the model file")
    from thesis.evaluation.tools import findings_in_model_file

    # cppcheck over the full TU reports across cpu.cc, the helper headers and
    # the model file; only the model-file finding must survive.
    xml = (
        '<results version="2"><cppcheck version="2.13.0"/><errors>'
        '<error id="uninitvar" severity="error" msg="in model">'
        '<location file="/x/generated-code.hpp" line="12" column="5"/></error>'
        '<error id="nullPointer" severity="error" msg="in benchmark">'
        '<location file="/x/cpu.cc" line="20" column="1"/></error>'
        '<error id="unreadVariable" severity="warning" msg="in helper">'
        '<location file="/x/utilities.hpp" line="5" column="1"/></error>'
        "</errors></results>"
    )

    parsed = CppcheckTool()._parse_xml(xml)
    check("three parsed before filtering", len(parsed) == 3)

    kept = findings_in_model_file(parsed, "generated-code.hpp")
    check("only the model-file finding kept", len(kept) == 1)
    check("kept finding is the model one", kept[0].message == "in model")


def test_infer_parse_and_filter() -> None:
    print("infer: report.json parsing and model-file filtering")
    from thesis.evaluation.tools import InferTool, findings_in_model_file

    # Mirrors the real Infer report.json schema; includes a finding in the
    # benchmark driver that must be filtered out.
    report = [
        {"bug_type": "NULL_DEREFERENCE", "qualifier": "pointer `q` could be null",
         "severity": "ERROR", "line": 6, "column": 11, "file": "/x/generated-code.hpp"},
        {"bug_type": "DEAD_STORE", "qualifier": "value never read",
         "severity": "WARNING", "line": 3, "column": 2, "file": "/x/generated-code.hpp"},
        {"bug_type": "RESOURCE_LEAK", "qualifier": "leak in the benchmark harness",
         "severity": "ERROR", "line": 9, "column": 1, "file": "/x/cpu.cc"},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        parsed = InferTool()._parse_report(report_path)

    check("three parsed before filtering", len(parsed) == 3)
    check("bug_type -> check_id", parsed[0].check_id == "NULL_DEREFERENCE")
    check("ERROR is blocking", parsed[0].blocking)
    check("WARNING not blocking", not parsed[1].blocking)
    check("file basename extracted", parsed[0].file == "generated-code.hpp")

    kept = findings_in_model_file(parsed, "generated-code.hpp")
    check("benchmark-file finding filtered out", len(kept) == 2)
    check("no non-model file remains", all(f.file == "generated-code.hpp" for f in kept))


def test_stub_rewriter() -> None:
    print("parcoach: LLVM IR stub rewriter")
    from thesis.evaluation.tools import stub_external_declares

    ll = (
        "declare noundef ptr @_Znwm(i64 noundef) #3\n"
        "declare void @_ZdlPv(ptr noundef) #4\n"
        "declare void @_ZSt17__throw_bad_allocv() #5\n"
        "declare i32 @MPI_Bcast(ptr noundef, i32 noundef, ptr, i32, ptr) #2\n"
        "declare double @llvm.fmuladd.f64(double, double, double) #6\n"
        "define void @kernel() {\n  ret void\n}\n"
    )

    result = stub_external_declares(ll)

    check("operator new stubbed to define", "define ptr @_Znwm" in result)
    check("operator new returns undef", "ret ptr undef" in result)
    check("operator delete stubbed", "define void @_ZdlPv" in result)
    check("throw helper stubbed", "define void @_ZSt17__throw_bad_allocv" in result)
    check("MPI declare untouched", "declare i32 @MPI_Bcast" in result)
    check("MPI not stubbed", "define i32 @MPI_Bcast" not in result)
    check("intrinsic declare untouched", "declare double @llvm.fmuladd.f64" in result)
    check("existing define untouched", "define void @kernel() {" in result)


def test_parcoach_parse_and_filter() -> None:
    print("parcoach: output parsing and model-file filtering")
    from thesis.evaluation.tools import parse_parcoach_output, findings_in_model_file

    output = (
        "Warning: no main function in module\n"
        "PARCOACH: /x/generated-code.hpp: warning: MPI_Bcast line 8 possibly "
        "not called by all processes because of conditional(s) line(s)  7 "
        "(/x/generated-code.hpp) (Call Ordering Error)\n"
        "PARCOACH: /x/utilities.hpp: warning: MPI_Barrier line 115 possibly "
        "not called by all processes because of conditional(s) line(s)  3 "
        "(/x/utilities.hpp) (Call Ordering Error)\n"
        "PARCOACH: remark: No issues found.\n"
    )

    parsed = parse_parcoach_output(output)
    check("two warnings parsed (remark ignored)", len(parsed) == 2)
    check("collective in message", parsed[0].message.startswith("MPI_Bcast"))
    check("line parsed", parsed[0].line == 8)
    check("file basename", parsed[0].file == "generated-code.hpp")
    check("blocking", parsed[0].blocking)

    kept = findings_in_model_file(parsed, "generated-code.hpp")
    check("non-model finding filtered", len(kept) == 1)
    check("model finding kept", kept[0].file == "generated-code.hpp")


def test_llov_parse_and_filter() -> None:
    print("llov: verdict-block parsing and model-file filtering")
    from thesis.evaluation.tools import parse_llov_output, findings_in_model_file

    output = (
        "Changing attributes for .omp_outlined._debug__ \n"
        "Data Race detected.\n"
        "Source : /x/generated-code.hpp:13\n"
        "Sink : /x/generated-code.hpp:13\n"
        "Region is Data Race Free.\n"
        "File : /x/generated-code.hpp:20\n"
        "Region Not Analyzed by the verifier. Loop -> <unnamed loop>\n"
        "File : /x/generated-code.hpp:27\n"
        "Data Race detected.\n"
        "Source : /x/cpu.cc:40\n"
    )

    parsed = parse_llov_output(output)
    check("three findings (race-free block yields none)", len(parsed) == 3)

    race = parsed[0]
    check("race check id", race.check_id == "llov-data-race")
    check("race blocking", race.blocking)
    check("race location from Source line", race.file == "generated-code.hpp" and race.line == 13)

    not_analyzed = parsed[1]
    check("not-analyzed check id", not_analyzed.check_id == "llov-region-not-analyzed")
    check("not-analyzed non-blocking info", not not_analyzed.blocking and not_analyzed.severity == "info")
    check("not-analyzed location", not_analyzed.line == 27)

    kept = findings_in_model_file(parsed, "generated-code.hpp")
    check("cpu.cc race filtered out", len(kept) == 2)


def main() -> None:
    tests = [
        test_build_config,
        test_resolve_compiler,
        test_launch_config,
        test_gcc_parser,
        test_cppcheck_parser,
        test_cppcheck_filtering,
        test_clang_tidy_helpers,
        test_clang_tidy_yaml_parse,
        test_infer_parse_and_filter,
        test_stub_rewriter,
        test_parcoach_parse_and_filter,
        test_llov_parse_and_filter,
        test_registry,
        test_finding_serialization,
    ]

    for test in tests:
        test()
        print()

    print(f"All {len(tests)} evaluation-framework tests passed.")


if __name__ == "__main__":
    main()
