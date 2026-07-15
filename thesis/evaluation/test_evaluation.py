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

    # niter maps onto the drivers' argv contract: serial/mpi read argv[1]
    # (after the exec path) as the iteration count; the omp driver's argv[1]
    # is the thread count, so niter must NOT be appended there.
    argv, _ = serial.command("/tmp/a.out", {}, niter=1)
    check("serial appends niter", argv == ["/tmp/a.out", "1"])
    argv, _ = mpi.command("/tmp/a.out", {"num_procs": 2}, niter=1)
    check("mpi appends niter after exec", argv[-2:] == ["/tmp/a.out", "1"])
    argv, _ = omp.command("/tmp/a.out", {"num_threads": 4}, niter=1)
    check("omp ignores niter", argv == ["/tmp/a.out", "4"])


def test_correctness_verdicts() -> None:
    print("correctness: validation parsing and verdicts")
    from thesis.evaluation.run_correctness import parse_validation, run_verdict

    check("PASS parsed", parse_validation("Init\nValidation: PASS\nTime: 1.0\n") is True)
    check("FAIL parsed", parse_validation("Validation: FAIL\n") is False)
    check("missing marker -> None", parse_validation("Segmentation fault\n") is None)

    check("pass verdict", run_verdict(True, 0, False) == "pass")
    # drivers exit 0 after printing FAIL -> marker beats exit code
    check("fail verdict despite exit 0", run_verdict(False, 0, False) == "validation_failed")
    check("timeout beats marker", run_verdict(True, 0, True) == "timeout")
    check("crash after PASS is runtime_error", run_verdict(True, 139, False) == "runtime_error")
    check("missing marker is runtime_error", run_verdict(None, 0, False) == "runtime_error")


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


def test_sanitizer_parsing() -> None:
    print("dynamic: sanitizer report parsing, attribution and dedup")
    from thesis.evaluation.dynamic_tools import dedupe, parse_sanitizer_output

    model = "generated-code.hpp"

    asan = (
        "==22==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x502c at pc 0x5d54\n"
        "READ of size 4 at 0x502c thread T0\n"
        "    #0 0x5d54 in luFactorize /x/generated-code.hpp:4\n"
        "    #1 0x5d55 in compute /x/cpu.cc:42\n"
        "SUMMARY: AddressSanitizer: heap-buffer-overflow /x/generated-code.hpp:4 in luFactorize\n"
    )
    findings = parse_sanitizer_output(asan, model, "asan_ubsan")
    check("asan block parsed", len(findings) == 1)
    check("asan check id", findings[0].check_id == "asan-heap-buffer-overflow")
    check("asan model line", findings[0].line == 4 and findings[0].blocking)

    non_model = (
        "==22==ERROR: AddressSanitizer: heap-use-after-free on address 0x50 at pc 0x1\n"
        "    #0 0x1 in correctLuFactorize /x/baseline.hpp:9\n"
        "    #1 0x2 in validate /x/cpu.cc:60\n"
        "SUMMARY: AddressSanitizer: heap-use-after-free /x/baseline.hpp:9\n"
    )
    check("non-model asan dropped", parse_sanitizer_output(non_model, model, "t") == [])

    tsan = (
        "WARNING: ThreadSanitizer: data race (pid=77)\n"
        "  Write of size 8 at 0x7b by thread T2:\n"
        "    #0 luFactorize(...) /x/generated-code.hpp:3 (out+0x12)\n"
        "  Previous write of size 8 at 0x7b by thread T1:\n"
        "    #0 luFactorize(...) /x/generated-code.hpp:3 (out+0x12)\n"
        "SUMMARY: ThreadSanitizer: data race /x/generated-code.hpp:3\n"
    )
    findings = parse_sanitizer_output(tsan, model, "tsan")
    check("tsan race parsed", len(findings) == 1)
    check("tsan check id", findings[0].check_id == "tsan-data-race")
    check("tsan model line", findings[0].line == 3)

    ubsan = (
        "/x/generated-code.hpp:7:15: runtime error: signed integer overflow: 2147483647 + 1\n"
        "/x/cpu.cc:12:3: runtime error: load of null pointer of type 'int'\n"
    )
    findings = parse_sanitizer_output(ubsan, model, "asan_ubsan")
    check("ubsan model line kept, driver line dropped", len(findings) == 1)
    check("ubsan location", findings[0].line == 7 and findings[0].column == 15)

    lsan = (
        "==9==ERROR: LeakSanitizer: detected memory leaks\n"
        "\n"
        "Direct leak of 400 byte(s) in 1 object(s) allocated from:\n"
        "    #0 0x1 in operator new[](unsigned long)\n"
        "    #1 0x2 in luFactorize /x/generated-code.hpp:2\n"
        "SUMMARY: AddressSanitizer: 400 byte(s) leaked in 1 allocation(s).\n"
    )
    findings = parse_sanitizer_output(lsan, model, "asan_ubsan")
    check("lsan leak parsed", len(findings) == 1)
    check("lsan check id", findings[0].check_id == "lsan-detected-memory-leaks")

    duplicated = parse_sanitizer_output(tsan, model, "tsan") + parse_sanitizer_output(
        tsan, model, "tsan"
    )
    check("dedupe by (check_id, line)", len(dedupe(duplicated)) == 1)

    # libomp-internal FP pattern: racing accesses only in the runtime, but
    # the thread-creation/allocation stacks pass through the model's parallel
    # region. Attribution must use access stacks only -> dropped.
    libomp_fp = (
        "WARNING: ThreadSanitizer: data race (pid=746)\n"
        "  Atomic read of size 1 at 0x72 by main thread:\n"
        "    #0 pthread_mutex_lock <null> (sanitized.out+0x63)\n"
        "    #1 <null> <null> (libomp.so.5+0xbdf44)\n"
        "  Previous write of size 1 at 0x72 by thread T1:\n"
        "    #0 pthread_mutex_init <null> (sanitized.out+0x62)\n"
        "    #1 <null> <null> (libomp.so.5+0xba6c1)\n"
        "  Location is heap block of size 1568 at 0x72 allocated by main thread:\n"
        "    #0 malloc <null> (sanitized.out+0x5f)\n"
        "    #1 luFactorize /x/generated-code.hpp:15\n"
        "  Thread T1 (tid=751, running) created by main thread at:\n"
        "    #0 pthread_create <null> (sanitized.out+0x60)\n"
        "    #1 luFactorize /x/generated-code.hpp:11\n"
        "SUMMARY: ThreadSanitizer: data race\n"
    )
    check(
        "libomp-internal race with model alloc stack dropped",
        parse_sanitizer_output(libomp_fp, model, "tsan") == [],
    )


def test_valgrind_parsing() -> None:
    print("dynamic: valgrind memcheck XML parsing and attribution")
    from thesis.evaluation.dynamic_tools import parse_valgrind_xml, slug_kind

    check("kind slug camel", slug_kind("InvalidRead") == "invalid-read")
    check("kind slug leak", slug_kind("Leak_DefinitelyLost") == "leak-definitely-lost")

    xml = (
        "<valgrindoutput><protocolversion>4</protocolversion>"
        "<error><unique>0x0</unique><tid>1</tid><kind>InvalidRead</kind>"
        "<what>Invalid read of size 4</what>"
        "<stack>"
        "<frame><ip>0x1</ip><fn>luFactorize</fn><file>generated-code.hpp</file><line>3</line></frame>"
        "<frame><ip>0x2</ip><fn>compute</fn><file>cpu.cc</file><line>42</line></frame>"
        "</stack></error>"
        "<error><unique>0x1</unique><tid>1</tid><kind>InvalidWrite</kind>"
        "<what>Invalid write of size 8</what>"
        "<stack>"
        "<frame><ip>0x3</ip><fn>correctLu</fn><file>baseline.hpp</file><line>9</line></frame>"
        "</stack></error>"
        "</valgrindoutput>"
    )

    findings = parse_valgrind_xml(xml, "generated-code.hpp", "memcheck")
    check("model error kept, baseline error dropped", len(findings) == 1)
    check("memcheck check id", findings[0].check_id == "memcheck-invalid-read")
    check("innermost model frame line", findings[0].line == 3)
    check("memcheck blocking", findings[0].blocking)

    check("malformed xml -> empty", parse_valgrind_xml("<oops", "m.hpp", "memcheck") == [])

    # libgomp thread-pool artifact: possibly-lost with a model frame must be
    # dropped (fired on 100% of OMP samples otherwise)
    possibly = (
        "<valgrindoutput><error><kind>Leak_PossiblyLost</kind>"
        "<xwhat><text>320 bytes in 1 blocks are possibly lost</text></xwhat>"
        "<stack><frame><file>generated-code.hpp</file><line>14</line></frame></stack>"
        "</error></valgrindoutput>"
    )
    check(
        "possibly-lost artifact dropped",
        parse_valgrind_xml(possibly, "generated-code.hpp", "memcheck") == [],
    )


def test_tool_config() -> None:
    print("tool_config: schema validation, scoping, low_confidence marking")
    from thesis.evaluation import dynamic_tools, tools
    from thesis.evaluation.framework import Finding
    from thesis.evaluation.tool_config import (
        HARD_CAPABILITIES,
        ToolSettings,
        mark_low_confidence,
        resolve_tool_settings,
        validate_repair_config,
        validate_stage_tools,
    )

    # hard-capability table stays in sync with the tool classes
    class_caps = {
        "compiler": tools.CompilerDiagnosticTool.execution_models,
        "clang_tidy": tools.ClangTidyTool.execution_models,
        "cppcheck": tools.CppcheckTool.execution_models,
        "infer": tools.InferTool.execution_models,
        "parcoach": tools.ParcoachTool.execution_models,
        "llov": tools.LLOVTool.execution_models,
        "asan_ubsan": dynamic_tools.AsanUbsanTool.execution_models,
        "tsan": dynamic_tools.TsanTool.execution_models,
        "memcheck": dynamic_tools.MemcheckTool.execution_models,
        "must": dynamic_tools.MustTool.execution_models,
        "helgrind": dynamic_tools.HelgrindTool.execution_models,
        "drd": dynamic_tools.DrdTool.execution_models,
    }
    for name, caps in class_caps.items():
        check(f"capabilities in sync: {name}", tuple(caps) == HARD_CAPABILITIES[name])

    # defaults preserve current behavior; helgrind/drd disabled
    settings = resolve_tool_settings({}, "dynamic_analysis")
    check("must enabled by default", settings["must"].enabled)
    check("helgrind disabled by default", not settings["helgrind"].enabled)
    check("drd disabled by default", not settings["drd"].enabled)
    check("helgrind low-precision default", settings["helgrind"].low_precision_warning)

    # config can narrow, never extend (warning + intersection)
    cfg = {"stages": {"dynamic_analysis": {"tools": {
        "asan_ubsan": {"execution_models": ["serial"]},
        "tsan": {"execution_models": ["serial", "omp"]},  # serial impossible
    }}}}
    resolved = resolve_tool_settings(cfg, "dynamic_analysis")
    check("narrowing respected", resolved["asan_ubsan"].execution_models == ("serial",))
    check("extension clipped to capability", resolved["tsan"].execution_models == ("omp",))

    # unknown tool / unknown model are hard errors
    try:
        validate_stage_tools(
            {"stages": {"static_analysis": {"tools": {"nope": {}}}}}, "static_analysis"
        )
        check("unknown tool rejected", False)
    except ValueError:
        check("unknown tool rejected", True)

    try:
        validate_stage_tools(
            {"stages": {"static_analysis": {"tools": {"infer": {"execution_models": ["gpu"]}}}}},
            "static_analysis",
        )
        check("unknown execution model rejected", False)
    except ValueError:
        check("unknown execution model rejected", True)

    try:
        validate_repair_config({"stages": {"repair": {"low_confidence_stop_mode": "sometimes"}}})
        check("bad stop mode rejected", False)
    except ValueError:
        check("bad stop mode rejected", True)

    # low_confidence marking: tool-wide and family-based
    findings = [
        Finding(tool="x", check_id="clang-analyzer-optin.mpi.MPI-Checker",
                severity="warning", message="m"),
        Finding(tool="x", check_id="bugprone-narrowing-conversions",
                severity="warning", message="m"),
    ]
    check("low_confidence default False", not findings[0].low_confidence)

    family = ToolSettings("clang_tidy", True, ("mpi",), False, ("clang-analyzer-optin.mpi",))
    marked = mark_low_confidence(findings, family)
    check("family marking hits only the family", marked == 1
          and findings[0].low_confidence and not findings[1].low_confidence)

    toolwide = ToolSettings("parcoach", True, ("mpi",), True, ())
    marked = mark_low_confidence(findings, toolwide)
    check("tool-wide marking hits all", marked == 2 and findings[1].low_confidence)


def test_must_parsing() -> None:
    print("dynamic: MUST HTML parsing and attribution")
    from thesis.evaluation.dynamic_tools import parse_must_html

    # mirrors the real MUST_Output.html structure (captured from the
    # planted-deadlock feasibility run): the token sits in the main row, the
    # message + call references in a SEPARATE hidden detail row
    html = (
        "<table>"
        "<tr onclick=\"showdetail(this,'detail0');\"><td>0-1</td>"
        "<td><b>MUST_ERROR_DEADLOCK</b></td>"
        "<td>The application issued a set of MPI calls that can cause a deadlock!</td></tr>"
        "<tr id=\"detail0\"><td>The application issued a set of MPI calls that can "
        "cause a deadlock! References 1-2 list the involved calls."
        "&nbsp;References of a representative process: reference 1 rank 0: "
        "MPI_Recv (1st occurrence) called from: "
        "#0 luFactorize@/x/generated-code.hpp:14 "
        "reference 2 rank 1: MPI_Finalize (1st occurrence) called from: "
        "#0 main@/x/mpi-driver.cc:103&nbsp;</td></tr>"
        # error whose references never reach the model file -> dropped
        "<tr><td>1</td><td><b>MUST_ERROR_TYPEMATCH_MISMATCH</b></td>"
        "<td>datatypes do not match!</td></tr>"
        "<tr id=\"detail1\"><td>A send and a receive operation use datatypes that "
        "do not match! reference 1 rank 0: MPI_Bcast called from: "
        "#0 validate@/x/cpu.cc:66</td></tr>"
        # warning severity
        "<tr><td>2</td><td><b>MUST_WARNING_SELF_COMM</b></td>"
        "<td>Rank sends to itself</td></tr>"
        "<tr id=\"detail2\"><td>Rank sends to itself: "
        "#0 luFactorize@/x/generated-code.hpp:20</td></tr>"
        "</table>"
    )

    findings = parse_must_html(html, "generated-code.hpp", "must")
    check("model rows kept, driver row dropped", len(findings) == 2)
    check("deadlock check id", findings[0].check_id == "must-deadlock")
    check("deadlock line from model ref", findings[0].line == 14)
    check("deadlock blocking", findings[0].blocking)
    check("reference tail stripped from message", "reference 1" not in findings[0].message)
    check("warning severity mapped", findings[1].severity == "warning" and not findings[1].blocking)

    check("clean html -> empty", parse_must_html("<table><tr><td>x</td></tr></table>", "m.hpp", "must") == [])


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
    check("openmp group blocking", is_blocking_check("openmp-exception-escape"))
    # hygiene recommendation that fires on correct code -> exception
    check("use-default-none not blocking", not is_blocking_check("openmp-use-default-none"))
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
        test_correctness_verdicts,
        test_gcc_parser,
        test_cppcheck_parser,
        test_cppcheck_filtering,
        test_clang_tidy_helpers,
        test_clang_tidy_yaml_parse,
        test_infer_parse_and_filter,
        test_sanitizer_parsing,
        test_valgrind_parsing,
        test_must_parsing,
        test_tool_config,
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
