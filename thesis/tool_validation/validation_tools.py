"""Validation-tool wrappers: pipeline-configured tools on standalone kernels.

DESIGN DECISION (Adapter vs. Direktaufruf)
------------------------------------------
The pipeline Tool classes in thesis/evaluation/tools.py and dynamic_tools.py
are hard-coupled to the ParEval scaffold in exactly one place: their run()
methods construct the translation unit from the benchmark driver
(cpu.cc + model driver + generated-code.hpp) and attribute findings to
generated-code.hpp. The suite kernels here are standalone C/C++ programs
with their own main(), so faking them into that scaffold would be
semantically wrong (double mains, missing baseline symbols).

Everything else in the pipeline modules is scaffold-independent and is
REUSED VERBATIM so that this measurement validates the tools exactly as the
pipeline configures them:
  - flags / check sets:  CLANG_TIDY_CHECKS, DIAGNOSTIC_FLAGS,
    LLOV_ANALYSIS_FLAGS, SANITIZER_BASE_FLAGS, cppcheck argument set
  - output parsers:      parse_gcc_clang_diagnostics, CppcheckTool._parse_xml,
    ClangTidyTool._parse_fixes, InferTool._parse_report, parse_llov_output,
    parse_parcoach_output, parse_sanitizer_output, parse_must_html
  - fail-safe semantics: a tool failure (non-zero exit, missing report,
    timeout) is an error, never a silently clean kernel
  - attribution:         findings_in_model_file against the kernel file name

So: thin direct invocations, no changes to any pipeline file.

Python 3.8 compatible (LLOV container).
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation.build_config import DIAGNOSTIC_FLAGS  # noqa: E402
from thesis.evaluation.framework import (  # noqa: E402
    AssembledSample,
    Finding,
    binary_available,
    run_command,
)
from thesis.evaluation.tools import (  # noqa: E402
    CLANG_TIDY_CHECKS,
    ClangTidyTool,
    CppcheckTool,
    InferTool,
    LLOVTool,
    LLOV_ANALYSIS_FLAGS,
    findings_in_model_file,
    mpi_include_flags,
    parse_gcc_clang_diagnostics,
    parse_llov_output,
    parse_parcoach_output,
)
from thesis.evaluation.dynamic_tools import (  # noqa: E402
    SANITIZER_BASE_FLAGS,
    AsanUbsanTool,
    MustTool,
    TsanTool,
    dedupe,
    parse_must_html,
    parse_sanitizer_output,
    parse_valgrind_xml,
)
from thesis.tool_validation.suite_kernels import ValidationKernel  # noqa: E402

RAW_CAP = 4000


@dataclass
class ValidationRun:
    tool: str
    ran: bool
    findings: List[Finding] = field(default_factory=list)
    error: Optional[str] = None
    runtime_seconds: float = 0.0
    raw: str = ""

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "ran": self.ran,
            "findings": [f.to_dict() for f in self.findings],
            "error": self.error,
            "runtime_seconds": round(self.runtime_seconds, 3),
            "raw": self.raw[:RAW_CAP],
        }


def parser_sample(kernel: ValidationKernel) -> AssembledSample:
    """Minimal AssembledSample so pipeline parsers attribute findings to the
    kernel file (they only use source_path / execution_model)."""
    return AssembledSample(
        sample_id=kernel.kernel_id,
        model_id="validation",
        run_id="validation",
        execution_model=kernel.execution_model,
        problem_type=kernel.suite,
        name=kernel.kernel_id,
        source_path=kernel.path,
        benchmark_dir=Path("."),
        model_driver_file="",
        assembly_entry={},
    )


def base_flags(kernel: ValidationKernel) -> List[str]:
    flags: List[str] = []

    for directory in kernel.include_dirs:
        flags += ["-I", directory]

    for define in kernel.extra_defines:
        flags.append("-D" + define)

    if kernel.execution_model == "mpi":
        flags += mpi_include_flags()

    return flags


def std_flag(kernel: ValidationKernel) -> str:
    # mirror the pipeline standard for C++; C kernels use the suites' dialect
    return "-std=c++17" if kernel.language == "cpp" else "-std=c11"


def host_compiler(kernel: ValidationKernel) -> str:
    return "g++" if kernel.language == "cpp" else "gcc"


class CompilerValidation:
    """gcc/clang diagnostics, pipeline flags (-Wall -Wextra -Wpedantic -O3)."""

    name = "compiler"
    suites = ("juliet",)

    # Extra flags appended by VARIANT subclasses only. Empty here, so the
    # argv of the pipeline-configured `compiler` measurement is byte-identical
    # to before this hook existed (empty splat) — the variant comparison is
    # worthless if the baseline moves.
    extra_flags: "Tuple[str, ...]" = ()

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout

    def is_available(self) -> bool:
        return binary_available("gcc")

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        with tempfile.TemporaryDirectory() as tmp:
            argv = [
                host_compiler(kernel),
                std_flag(kernel),
                "-O3",  # array-bounds/uninitialized warnings need optimization
                *DIAGNOSTIC_FLAGS,
                *self.extra_flags,
                *base_flags(kernel),
                "-c",
                str(kernel.path),
                "-o",
                str(Path(tmp) / "k.o"),
            ]
            result = run_command(argv, timeout=self.timeout)

        findings = findings_in_model_file(
            parse_gcc_clang_diagnostics(result.stderr, self.name), kernel.path.name
        )

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=findings,
            runtime_seconds=result.duration_seconds,
            raw=result.stderr,
            # a non-compiling BAD kernel still produced diagnostics = signal;
            # the runner's preflight already skipped truly broken kernels
            error="timeout" if result.timed_out else None,
        )


class ClangTidyValidation:
    """clang-tidy with the pipeline check set (incl. Clang SA + MPI-Checker)."""

    name = "clang_tidy"
    suites = ("juliet", "mbi")

    def __init__(self, timeout: float = 180.0):
        self.timeout = timeout
        self._pipeline = ClangTidyTool()

    def is_available(self) -> bool:
        return self._pipeline.is_available()

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        with tempfile.TemporaryDirectory() as tmp:
            fixes = Path(tmp) / "fixes.yaml"

            argv = [
                "clang-tidy",
                "--checks=" + CLANG_TIDY_CHECKS,
                "--export-fixes=" + str(fixes),
                str(kernel.path),
                "--",
                std_flag(kernel),
                *base_flags(kernel),
            ]

            result = run_command(argv, timeout=self.timeout)
            findings = self._pipeline._parse_fixes(fixes, parser_sample(kernel))

        for finding in findings:
            if finding.check_id.startswith("clang-diagnostic-error"):
                finding.blocking = True

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=findings,
            runtime_seconds=result.duration_seconds,
            raw=result.stdout + "\n" + result.stderr,
            error="timeout" if result.timed_out else None,
        )


class CppcheckValidation:
    """cppcheck with the pipeline argument set."""

    name = "cppcheck"
    suites = ("juliet",)

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout
        self._pipeline = CppcheckTool()

    def is_available(self) -> bool:
        return self._pipeline.is_available()

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        argv = [
            "cppcheck",
            "--enable=warning,portability",
            "--inconclusive",
            "--language=" + ("c++" if kernel.language == "cpp" else "c"),
            "--std=" + ("c++17" if kernel.language == "cpp" else "c11"),
            *["-D" + d for d in kernel.extra_defines],
            *[flag for d in kernel.include_dirs for flag in ("-I", d)],
            "--xml",
            "--xml-version=2",
            str(kernel.path),
        ]

        result = run_command(argv, timeout=self.timeout)

        findings = findings_in_model_file(
            self._pipeline._parse_xml(result.stderr), kernel.path.name
        )

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=findings,
            runtime_seconds=result.duration_seconds,
            raw=result.stderr,
            error="timeout" if result.timed_out else None,
        )


class InferValidation:
    """Meta Infer, pipeline invocation (incl. --headers) on the kernel."""

    name = "infer"
    suites = ("juliet",)

    # Extra `infer run` flags for VARIANT subclasses only — empty here, so the
    # pipeline-configured `infer` baseline is unchanged (see CompilerValidation).
    extra_infer_flags: "Tuple[str, ...]" = ()

    def __init__(self, timeout: float = 300.0):
        self.timeout = timeout
        self._pipeline = InferTool()

    def is_available(self) -> bool:
        return self._pipeline.is_available()

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "infer-out"

            argv = [
                "infer",
                "run",
                "--headers",
                *self.extra_infer_flags,
                "-o",
                str(out_dir),
                "--keep-going",
                "--",
                "clang++" if kernel.language == "cpp" else "clang",
                std_flag(kernel),
                *base_flags(kernel),
                "-c",
                str(kernel.path),
                "-o",
                str(Path(tmp) / "k.o"),
            ]

            result = run_command(argv, timeout=self.timeout)

            report = out_dir / "report.json"
            findings = findings_in_model_file(
                self._pipeline._parse_report(report), kernel.path.name
            )

            error = None
            if result.timed_out:
                error = "timeout"
            elif result.returncode != 0:
                error = "infer exited with %d" % result.returncode
            elif not report.exists():
                error = "infer produced no report.json"

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=findings,
            runtime_seconds=result.duration_seconds,
            raw=result.stdout + "\n" + result.stderr,
            error=error,
        )


class LlovValidation:
    """LLOV plugin compile on the kernel (pipeline flags, own clang)."""

    name = "llov"
    suites = ("drb",)

    def __init__(self, timeout: float = 180.0):
        self.timeout = timeout
        self._pipeline = LLOVTool()

    def is_available(self) -> bool:
        return self._pipeline.is_available()

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        # DRB kernels are C: use LLOV's bundled clang (sibling of clang++)
        clang = str(self._pipeline._clang)
        if kernel.language == "c":
            clang = clang[: -len("++")] if clang.endswith("++") else clang

        with tempfile.TemporaryDirectory() as tmp:
            argv = [
                clang,
                "-Xclang", "-load", "-Xclang", str(self._pipeline._plugin),
                "-fopenmp",
                std_flag(kernel),
                *LLOV_ANALYSIS_FLAGS,
                *base_flags(kernel),
                "-c",
                str(kernel.path),
                "-o",
                str(Path(tmp) / "k.o"),
            ]

            result = run_command(argv, timeout=self.timeout)

        findings = findings_in_model_file(
            parse_llov_output(result.stdout + "\n" + result.stderr),
            kernel.path.name,
        )

        error = None
        if result.timed_out:
            error = "timeout"
        elif result.returncode != 0:
            error = "llov clang exited with %d" % result.returncode

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=findings,
            runtime_seconds=result.duration_seconds,
            raw=result.stdout + "\n" + result.stderr,
            error=error,
        )


class ParcoachValidation:
    """PARCOACH on the kernel's LLVM IR (clang-15 -emit-llvm, no driver).

    MBI/DRB kernels are plain C: the C++-std workarounds from the pipeline
    (-fno-exceptions, external stubbing) are unnecessary — PARCOACH's own
    test suite is C. OpenMP kernels are compiled with -fopenmp.
    """

    name = "parcoach"
    suites = ("drb", "mbi")

    def __init__(self, timeout: float = 180.0):
        self.timeout = timeout

    def _clang(self) -> Optional[str]:
        import shutil

        found = shutil.which("clang")
        if found:
            return found

        fallback = Path("/usr/lib/llvm-15/bin/clang")
        return str(fallback) if fallback.exists() else None

    def is_available(self) -> bool:
        return binary_available("parcoach") and self._clang() is not None

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        clang = self._clang()

        with tempfile.TemporaryDirectory() as tmp:
            ll_path = Path(tmp) / "kernel.ll"

            argv = [
                clang,
                std_flag(kernel),
                "-g",
                "-S",
                "-emit-llvm",
                *(["-fopenmp"] if kernel.execution_model == "omp" else []),
                *base_flags(kernel),
                "-c",
                str(kernel.path),
                "-o",
                str(ll_path),
            ]

            compile_result = run_command(argv, timeout=self.timeout)

            if compile_result.returncode != 0 or not ll_path.exists():
                return ValidationRun(
                    tool=self.name,
                    ran=True,
                    error="clang -emit-llvm failed",
                    runtime_seconds=compile_result.duration_seconds,
                    raw=compile_result.stderr,
                )

            result = run_command(["parcoach", str(ll_path)], timeout=self.timeout)

        findings = findings_in_model_file(
            parse_parcoach_output(result.stdout + "\n" + result.stderr),
            kernel.path.name,
        )

        error = None
        if result.timed_out:
            error = "timeout"
        elif result.returncode != 0:
            error = "parcoach exited with %d" % result.returncode

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=findings,
            runtime_seconds=compile_result.duration_seconds + result.duration_seconds,
            raw=(result.stdout + "\n" + result.stderr),
            error=error,
        )


class TsanValidation:
    """TSan/Archer: compile+run the kernel (has its own main)."""

    name = "tsan"
    suites = ("drb",)

    THREAD_COUNTS = (4, 8)

    def __init__(self, build_timeout: float = 120.0, run_timeout: float = 60.0):
        self.build_timeout = build_timeout
        self.run_timeout = run_timeout
        self._pipeline = TsanTool()

    def is_available(self) -> bool:
        return self._pipeline.is_available()

    def _run_env(self, threads: int) -> "dict[str, str]":
        env = dict(self._pipeline.run_env())
        env["OMP_NUM_THREADS"] = str(threads)
        return env

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        preflight = self._pipeline.preflight()
        if preflight:
            return ValidationRun(tool=self.name, ran=False, error=preflight)

        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "k.out"

            argv = [
                "clang++" if kernel.language == "cpp" else "clang",
                std_flag(kernel),
                "-fopenmp",
                "-fsanitize=thread",
                *SANITIZER_BASE_FLAGS,
                *base_flags(kernel),
                str(kernel.path),
                "-o",
                str(binary),
                "-lm",
            ]

            build = run_command(argv, timeout=self.build_timeout)

            if build.returncode != 0:
                return ValidationRun(
                    tool=self.name,
                    ran=True,
                    error="instrumented build failed",
                    runtime_seconds=build.duration_seconds,
                    raw=build.stderr,
                )

            findings: List[Finding] = []
            raw_parts: List[str] = []
            runtime = build.duration_seconds
            error = None

            for threads in self.THREAD_COUNTS:
                env = self._run_env(threads)

                result = run_command(
                    [str(binary)], timeout=self.run_timeout, cwd=tmp, extra_env=env
                )
                runtime += result.duration_seconds

                findings += parse_sanitizer_output(
                    result.stderr, kernel.path.name, self.name
                )
                raw_parts.append(result.stderr[:1500])

                if result.timed_out:
                    error = "run timed out at %d threads" % threads

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=dedupe(findings),
            runtime_seconds=runtime,
            raw="\n".join(raw_parts),
            error=error,
        )


def juliet_sources(kernel: ValidationKernel) -> "list[str]":
    """Kernel file + Juliet's io.c (printLine etc. — needed once we LINK,
    unlike the compile-only static tools)."""
    sources = [str(kernel.path)]

    if kernel.include_dirs:
        io_c = Path(kernel.include_dirs[0]) / "io.c"
        if io_c.exists():
            sources.append(str(io_c))

    return sources


class AsanUbsanValidation:
    """ASan+LSan+UBSan on executed Juliet testcases.

    Builds the bad/good variant (OMITGOOD/OMITBAD) WITH main
    (-DINCLUDEMAIN) and io.c linked, runs it, parses sanitizer reports
    attributed to the kernel file. Pipeline-identical instrumentation
    (-fsanitize=address,undefined + SANITIZER_BASE_FLAGS) and env
    (detect_leaks=1 -> CWE401 via LSan).

    SEMANTICS NOTE (footnote in summary.md): a dynamic tool only reports a
    bug the test run actually TRIGGERS. Juliet bad-mains do trigger their
    defect, but recall numbers are still not directly comparable to static
    tools. Non-zero exit codes are EXPECTED on detection (ASan aborts).
    """

    name = "asan_ubsan"
    suites = ("juliet",)

    def __init__(self, build_timeout: float = 120.0, run_timeout: float = 15.0):
        self.build_timeout = build_timeout
        self.run_timeout = run_timeout
        self._pipeline = AsanUbsanTool()

    def is_available(self) -> bool:
        return binary_available("gcc")

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "k.out"

            build = run_command(
                [
                    host_compiler(kernel),
                    std_flag(kernel),
                    "-fsanitize=address,undefined",
                    *SANITIZER_BASE_FLAGS,
                    "-DINCLUDEMAIN",
                    *base_flags(kernel),
                    *juliet_sources(kernel),
                    "-o",
                    str(binary),
                    "-lm",
                ],
                timeout=self.build_timeout,
            )

            if build.returncode != 0:
                return ValidationRun(
                    tool=self.name,
                    ran=True,
                    error="instrumented build failed",
                    runtime_seconds=build.duration_seconds,
                    raw=build.stderr,
                )

            result = run_command(
                [str(binary)],
                timeout=self.run_timeout,
                cwd=tmp,
                extra_env=self._pipeline.run_env(),
            )

            findings = parse_sanitizer_output(
                result.stdout + "\n" + result.stderr, kernel.path.name, self.name
            )

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=dedupe(findings),
            runtime_seconds=build.duration_seconds + result.duration_seconds,
            raw=result.stderr[:1500],
            # non-zero exit = sanitizer abort on detection, NOT an error;
            # only a hang is (some Juliet mains read stdin -> timeout guard)
            error="timeout (kernel may expect stdin)" if result.timed_out else None,
        )


class MemcheckJulietValidation:
    """Valgrind Memcheck on executed Juliet testcases (plain -O1 -g build
    with main + io.c, run under valgrind XML). The DBI counterpart to ASan
    on the same executions; same dynamic-semantics footnote applies."""

    name = "memcheck"
    suites = ("juliet",)

    def __init__(self, build_timeout: float = 120.0, run_timeout: float = 60.0):
        self.build_timeout = build_timeout
        self.run_timeout = run_timeout

    def is_available(self) -> bool:
        return binary_available("valgrind") and binary_available("gcc")

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "k.out"

            build = run_command(
                [
                    host_compiler(kernel),
                    std_flag(kernel),
                    *SANITIZER_BASE_FLAGS,
                    "-DINCLUDEMAIN",
                    *base_flags(kernel),
                    *juliet_sources(kernel),
                    "-o",
                    str(binary),
                    "-lm",
                ],
                timeout=self.build_timeout,
            )

            if build.returncode != 0:
                return ValidationRun(
                    tool=self.name,
                    ran=True,
                    error="build failed",
                    runtime_seconds=build.duration_seconds,
                    raw=build.stderr,
                )

            xml_path = Path(tmp) / "vg.xml"

            result = run_command(
                [
                    "valgrind",
                    "--tool=memcheck",
                    "--xml=yes",
                    "--xml-file=" + str(xml_path),
                    str(binary),
                ],
                timeout=self.run_timeout,
                cwd=tmp,
            )

            xml_text = ""
            if xml_path.exists():
                xml_text = xml_path.read_text(encoding="utf-8", errors="replace")

            findings = parse_valgrind_xml(xml_text, kernel.path.name, self.name)

            error = None
            if result.timed_out:
                error = "timeout (kernel may expect stdin)"
            elif not xml_text:
                error = "valgrind produced no XML output"

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=dedupe(findings),
            runtime_seconds=build.duration_seconds + result.duration_seconds,
            raw=result.stderr[:1500],
            error=error,
        )


class _ValgrindRaceValidation:
    """Helgrind / DRD on DataRaceBench — EXCLUSION-JUSTIFICATION measurement.

    These two are deliberately NOT part of the evaluation pipeline: the ad-hoc
    feasibility test showed Helgrind reporting races on race-free OpenMP
    kernels (frames pointing into user code, so attribution cannot filter
    them) and DRD detecting nothing, consistent with Valgrind's documented
    requirement of a futex-free OpenMP runtime. Running them against DRB's
    204 labeled kernels turns that 2-kernel observation into a suite-scale,
    citable FP-rate/recall measurement for the methodology chapter.

    Reuses the pipeline's parse_valgrind_xml (single source of parsing
    logic); only the check_id prefix is rewritten from "memcheck-" to the
    tool name, since the pipeline parser is memcheck-specific there.
    """

    suites = ("drb",)

    name = ""        # set by subclass
    tool_flag = ""   # --tool=<...>

    THREADS = 2      # valgrind serializes threads; count barely matters

    def __init__(self, build_timeout: float = 120.0, run_timeout: float = 120.0):
        self.build_timeout = build_timeout
        self.run_timeout = run_timeout

    def is_available(self) -> bool:
        return binary_available("valgrind") and binary_available("gcc")

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "k.out"

            build = run_command(
                [
                    host_compiler(kernel),
                    std_flag(kernel),
                    "-fopenmp",
                    *SANITIZER_BASE_FLAGS,  # -O1 -g -fno-omit-frame-pointer
                    *base_flags(kernel),
                    str(kernel.path),
                    "-o",
                    str(binary),
                    "-lm",
                ],
                timeout=self.build_timeout,
            )

            if build.returncode != 0:
                return ValidationRun(
                    tool=self.name,
                    ran=True,
                    error="build failed",
                    runtime_seconds=build.duration_seconds,
                    raw=build.stderr,
                )

            xml_path = Path(tmp) / "vg.xml"

            result = run_command(
                [
                    "valgrind",
                    "--tool=" + self.tool_flag,
                    "--xml=yes",
                    "--xml-file=" + str(xml_path),
                    str(binary),
                ],
                timeout=self.run_timeout,
                cwd=tmp,
                extra_env={"OMP_NUM_THREADS": str(self.THREADS)},
            )

            xml_text = ""
            if xml_path.exists():
                xml_text = xml_path.read_text(encoding="utf-8", errors="replace")

            findings = parse_valgrind_xml(xml_text, kernel.path.name, self.name)

            # the pipeline parser prefixes check_ids with "memcheck-";
            # rewrite to this tool's name (e.g. helgrind-race)
            for finding in findings:
                if finding.check_id.startswith("memcheck-"):
                    finding.check_id = self.name + "-" + finding.check_id[len("memcheck-"):]

            error = None
            if result.timed_out:
                error = "timeout"
            elif not xml_text:
                error = "valgrind produced no XML output"

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=dedupe(findings),
            runtime_seconds=build.duration_seconds + result.duration_seconds,
            raw=result.stderr[:1500],
            error=error,
        )


class CompilerAnalyzerValidation(CompilerValidation):
    """COMPARISON MEASUREMENT ONLY (not a pipeline tool): the pipeline
    compiler invocation PLUS -fanalyzer, GCC's path-sensitive static
    analyzer.

    Quantifies what -fanalyzer adds over plain warning-based diagnostics on
    the same kernels — recall gain, precision, and the runtime surcharge.
    The open question it answers empirically is C++ viability: GCC documents
    the analyzer as targeting C, so the scorer reports the metrics split by
    kernel language (see score_validation.language_split).

    Everything else is identical to CompilerValidation (same flags, same
    gcc diagnostic parser — the -Wanalyzer-* warnings arrive in the normal
    diagnostic format — same fail-safe semantics: a timeout is an `error`,
    never a silent miss).
    """

    name = "compiler_fanalyzer"

    extra_flags = ("-fanalyzer",)

    def __init__(self, timeout: float = 300.0):
        # path-sensitive analysis is far more expensive than -Wall: generous
        # per-kernel budget (the base tool runs at 120s)
        super().__init__(timeout=timeout)


class InferBoValidation(InferValidation):
    """COMPARISON MEASUREMENT ONLY (not a pipeline tool): the pipeline Infer
    invocation PLUS --bufferoverrun (InferBO, the abstract-interpretation
    buffer-overrun/integer-overflow analysis, off by default).

    Default Infer (Pulse + biabduction) structurally cannot report buffer
    overruns or integer overflows, which is exactly where its Juliet recall
    is zero. This measurement quantifies whether enabling InferBO closes
    that gap at acceptable precision — including the confidence-level
    breakdown (BUFFER_OVERRUN_L1..L5), since InferBO encodes its certainty
    in the bug_type suffix.

    Same report parser, same fail-safe semantics as InferValidation.
    """

    name = "infer_bo"

    extra_infer_flags = ("--bufferoverrun",)

    def __init__(self, timeout: float = 300.0):
        super().__init__(timeout=timeout)


class HelgrindValidation(_ValgrindRaceValidation):
    name = "helgrind"
    tool_flag = "helgrind"


class DrdValidation(_ValgrindRaceValidation):
    name = "drd"
    tool_flag = "drd"


class TsanNoArcherValidation(TsanValidation):
    """COMPARISON MEASUREMENT ONLY (not a pipeline tool): TSan without the
    Archer OMPT plugin (OMP_TOOL_LIBRARIES stripped). Quantifies Archer's
    contribution suite-wide — FP suppression / OpenMP sync modelling inside
    the runtime — as the justification for shipping TSan+Archer (rather
    than plain TSan) in the pipeline.
    """

    name = "tsan_noarcher"

    def _run_env(self, threads: int) -> "dict[str, str]":
        env = super()._run_env(threads)
        env.pop("OMP_TOOL_LIBRARIES", None)
        env.pop("ARCHER_OPTIONS", None)
        return env


class MustValidation:
    """MUST: compile with mpicc, run under mustrun with the MBI rank count.

    Validation-specific --must:timeout of 30s (pipeline uses 60s): MBI
    kernels are tiny, and the full suite has ~1100 defective kernels, many
    deadlocking — 60s each would put the full run at ~16h+. MUST flags the
    deadlock AT the timeout, so halving it only bounds the wait, not the
    detection.
    """

    name = "must"
    suites = ("mbi",)

    MUST_TIMEOUT_SECONDS = 30

    def __init__(self, build_timeout: float = 120.0, run_timeout: float = 120.0):
        self.build_timeout = build_timeout
        self.run_timeout = run_timeout
        self._pipeline = MustTool()

    def is_available(self) -> bool:
        return self._pipeline.is_available()

    def run(self, kernel: ValidationKernel) -> ValidationRun:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "k.out"

            build = run_command(
                ["mpicc", "-O1", "-g", str(kernel.path), "-o", str(binary), "-lm"],
                timeout=self.build_timeout,
            )

            if build.returncode != 0:
                return ValidationRun(
                    tool=self.name,
                    ran=True,
                    error="build failed",
                    runtime_seconds=build.duration_seconds,
                    raw=build.stderr,
                )

            run_dir = Path(tmp) / "must"
            run_dir.mkdir()

            # /usr/bin/timeout wrapper: a Python-level timeout kills only
            # mustrun, while orphaned MPI ranks keep the output pipes open —
            # observed to block the pipe drain for HOURS on rare kernels.
            # The system timeout signals mustrun in its process group, mpirun
            # tears the ranks down, pipes close. -k hard-kills stragglers.
            result = run_command(
                [
                    "/usr/bin/timeout",
                    "--signal=TERM",
                    "-k",
                    "15",
                    str(int(self.run_timeout)),
                    self._pipeline._mustrun(),
                    "--must:timeout",
                    str(self.MUST_TIMEOUT_SECONDS),
                    "-np",
                    str(kernel.num_procs),
                    str(binary),
                ],
                timeout=self.run_timeout + 60,
                cwd=str(run_dir),
            )

            report = run_dir / "MUST_Output.html"

            findings: List[Finding] = []
            error = None

            if report.exists():
                findings = parse_must_html(
                    report.read_text(encoding="utf-8", errors="replace"),
                    kernel.path.name,
                    self.name,
                )
            else:
                error = "MUST produced no report"

            if result.timed_out:
                error = "mustrun timed out"

        return ValidationRun(
            tool=self.name,
            ran=True,
            findings=findings,
            runtime_seconds=build.duration_seconds + result.duration_seconds,
            raw=result.stdout + "\n" + result.stderr,
            error=error,
        )


VALIDATION_TOOLS = {
    tool.name: tool
    for tool in (
        CompilerValidation(),
        ClangTidyValidation(),
        CppcheckValidation(),
        InferValidation(),
        LlovValidation(),
        ParcoachValidation(),
        TsanValidation(),
        MustValidation(),
        # dynamic memory tools on executed Juliet testcases:
        AsanUbsanValidation(),
        MemcheckJulietValidation(),
        # justification measurements only, not pipeline tools:
        HelgrindValidation(),
        DrdValidation(),
        TsanNoArcherValidation(),
        # variant measurements (base tool + one extra analysis) — quantify
        # what the extra component contributes; same category as tsan_noarcher
        CompilerAnalyzerValidation(),
        InferBoValidation(),
    )
}
