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
        )

        sample = AssembledSample(
            sample_id="x", model_id="m", run_id="r", execution_model="serial",
            problem_type="p", name="n", source_path=src,
            benchmark_dir=Path(tmp), model_driver_file="", assembly_entry={},
        )

        findings = ClangTidyTool()._parse_fixes(fixes, sample)
        check("two findings parsed", len(findings) == 2)
        check("bugprone is blocking", findings[0].blocking)
        check("performance not blocking", not findings[1].blocking)
        check("line computed from offset", findings[0].line == 2)


def main() -> None:
    tests = [
        test_build_config,
        test_resolve_compiler,
        test_launch_config,
        test_gcc_parser,
        test_cppcheck_parser,
        test_clang_tidy_helpers,
        test_clang_tidy_yaml_parse,
        test_registry,
        test_finding_serialization,
    ]

    for test in tests:
        test()
        print()

    print(f"All {len(tests)} evaluation-framework tests passed.")


if __name__ == "__main__":
    main()
