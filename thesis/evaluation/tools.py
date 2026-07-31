"""Initial concrete analysis tools.

Implemented here:
  - CompilerDiagnosticTool: compiles the sample with -Wall -Wextra
    -Wpedantic and parses gcc/clang diagnostics into Findings. This is
    both the cheapest static-analysis layer and the authoritative compile
    check; a non-zero compiler exit is blocking.
  - GccAnalyzerTool: a second, compile-only pass with GCC's -fanalyzer
    (path-sensitive symbolic execution), kept separate from the compiler
    tool on purpose — see the class docstring.
  - CppcheckTool: runs cppcheck and parses its structured XML output.

Both write the exact command they ran into the ToolResult, so the runs are
reproducible from the JSONL alone.
"""

from __future__ import annotations

import json
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

from thesis.evaluation.build_config import get_build_config
from thesis.evaluation.tool_config import tool_option
from thesis.evaluation.framework import (
    AssembledSample,
    EvaluationContext,
    Finding,
    ToolResult,
    binary_available,
    register_tool,
    run_command,
)

# Problem size the drivers require via -DDRIVER_PROBLEM_SIZE. The value is
# irrelevant to static analysis (it only sizes the benchmark data), but
# utilities.hpp #errors out when it is undefined, so every tool that parses a
# real translation unit must define it (mirrors the compile stage).
DRIVER_PROBLEM_SIZE_DEFINE = "DRIVER_PROBLEM_SIZE=(1<<8)"


def mpi_include_flags() -> list[str]:
    """`-I` flags for the MPI headers.

    The compile stage uses the mpicxx wrapper, which injects these
    automatically. clang-tidy and cppcheck parse with clang / their own
    front-end instead, so for MPI samples they need the MPI include dirs
    explicitly, otherwise <mpi.h> (pulled in by utilities.hpp) is not found.
    Uses OpenMPI's `--showme:incdirs` (the containers ship OpenMPI); returns
    empty if no MPI compiler wrapper is found or it is not OpenMPI, in which
    case the tool degrades to a partial parse rather than crashing. Tries
    mpicxx first (main toolchain image), then mpic++ (PARCOACH image).
    """
    wrapper = next(
        (w for w in ("mpicxx", "mpic++") if binary_available(w)), None
    )

    if wrapper is None:
        return []

    result = run_command([wrapper, "--showme:incdirs"], timeout=15.0)

    if result.returncode != 0 or not result.stdout.strip():
        return []

    flags: list[str] = []
    for include_dir in result.stdout.split():
        flags += ["-I", include_dir]

    return flags


def findings_in_model_file(findings: list[Finding], model_file: str) -> list[Finding]:
    """Keep only findings located in the model's generated-code.hpp.

    The analyzers parse the full translation unit (the benchmark's cpu.cc,
    which includes the assembled generated-code.hpp), so their raw output
    also carries diagnostics from the driver, benchmark and helper headers.
    Only the model's own file is attributable to the LLM; everything else is
    dropped (still recoverable from the persisted raw output).
    """
    return [f for f in findings if f.file == model_file]


# gcc/clang diagnostic line:
#   file:line:col: severity: message [-Wflag]
GCC_CLANG_DIAGNOSTIC = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<severity>error|warning|note):\s+(?P<message>.*?)\s*"
    r"(?:\[(?P<flag>-W[^\]]+)\])?$"
)


def parse_gcc_clang_diagnostics(stderr: str, tool_name: str) -> list[Finding]:
    findings: list[Finding] = []

    for raw_line in stderr.splitlines():
        match = GCC_CLANG_DIAGNOSTIC.match(raw_line.strip())

        if not match:
            continue

        severity = match.group("severity")
        flag = match.group("flag")

        findings.append(
            Finding(
                tool=tool_name,
                check_id=flag if flag else severity,
                severity=severity,
                message=match.group("message"),
                file=Path(match.group("file")).name,
                line=int(match.group("line")),
                column=int(match.group("col")),
                # An actual compile error is blocking; warnings are recorded
                # but do not gate the repair loop (see tooling design).
                blocking=severity == "error",
            )
        )

    return findings


class CompilerDiagnosticTool:
    """Compile with diagnostics on and parse warnings/errors.

    Compiles the full program (model driver + benchmark cpu.cc + the
    assembled generated-code.hpp) exactly as the correctness stage will,
    so a successful diagnostic compile means the sample is buildable.
    """

    name = "compiler"

    # hard capability (config can only narrow this; see tool_config.py)
    execution_models = ("serial", "omp", "mpi")

    def __init__(self, primary_compiler: str = "g++", build_timeout: float = 120.0):
        self.primary_compiler = primary_compiler
        self.build_timeout = build_timeout

    def is_available(self) -> bool:
        return binary_available(self.primary_compiler) and binary_available("mpicxx")

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        config = get_build_config(
            sample.execution_model,
            primary_compiler=self.primary_compiler,
            diagnostic=True,
        )

        model_driver = context.drivers_cpp_dir / config.model_driver_file
        benchmark_driver = sample.benchmark_dir / "cpu.cc"

        missing = [
            str(p)
            for p in (model_driver, benchmark_driver, sample.source_path)
            if not p.exists()
        ]

        if missing:
            return ToolResult(
                tool=self.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=f"missing inputs: {', '.join(missing)}",
            )

        with tempfile.TemporaryDirectory() as tmp:
            exec_path = str(Path(tmp) / "a.out")

            argv = config.base_command(
                sources=[str(model_driver), str(benchmark_driver)],
                output_path=exec_path,
                include_dirs=context.include_dirs(sample),
                extra_flags=[f'-D{DRIVER_PROBLEM_SIZE_DEFINE}'],
            )

            result = run_command(argv, timeout=self.build_timeout)

        findings = parse_gcc_clang_diagnostics(result.stderr, self.name)

        # Attribute by file: warnings originating in the upstream driver or
        # benchmark code are not the model's responsibility. Keep model-file
        # findings as-is; keep non-model findings only if they are errors
        # (an error anywhere means the sample does not build), and tag them.
        model_file = sample.source_path.name
        attributed: list[Finding] = []

        for finding in findings:
            in_model_file = finding.file == model_file

            if in_model_file:
                attributed.append(finding)
            elif finding.severity == "error":
                finding.check_id = f"{finding.check_id} (in driver/benchmark)"
                attributed.append(finding)
            # else: non-model warning, dropped (recorded only in raw_stderr)

        findings = attributed

        # Guarantee at least one blocking finding when the compile failed,
        # so downstream logic can treat "did not build" uniformly.
        if result.returncode != 0 and not any(f.blocking for f in findings):
            findings.append(
                Finding(
                    tool=self.name,
                    check_id="compile-failed",
                    severity="error",
                    message=(
                        "compilation failed"
                        + (" (timeout)" if result.timed_out else "")
                    ),
                    file=sample.source_path.name,
                    blocking=True,
                )
            )

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
        )


# ---------------------------------------------------------------------------
# GCC -fanalyzer (path-sensitive symbolic execution)
# ---------------------------------------------------------------------------

# The analyzer reports exclusively under -Wanalyzer-* flags. Everything else
# this pass emits is an ordinary compiler diagnostic that the `compiler` tool
# already owns, so only this prefix is kept (see the class docstring).
ANALYZER_FLAG_PREFIX = "-Wanalyzer"

# -Wanalyzer-* warnings that report the ANALYZER's own limits instead of a
# defect in the code: the symbolic execution ran out of budget and gave up on
# that path. They are recorded (an honest "could not analyze here", same idea
# as LLOV's region-not-analyzed verdict) but never blocking — there is no
# defect to repair.
ANALYZER_NON_DEFECT_WARNINGS = (
    "-Wanalyzer-too-complex",
    "-Wanalyzer-symbol-too-complex",
)

# `#include <system_header>` at the start of a file (the driver's preamble).
SYSTEM_INCLUDE_RE = re.compile(r"^\s*#include\s*<[^>]+>\s*$")


def driver_system_includes(benchmark_driver: Path) -> list[str]:
    """The `#include <...>` preamble of a benchmark's cpu.cc.

    A reduced translation unit must reproduce it: cpu.cc includes
    <algorithm>, <cmath>, <numeric>, <random>, <vector> BEFORE
    generated-code.hpp, so model code may legitimately call std::sort or
    std::transform without including the header itself. Without the
    preamble such a sample would fail to compile in the reduced TU and be
    recorded as a tool error although it builds fine in the pipeline
    (measured: 7 of 60 benchmarks affected).

    Only `<...>` includes are taken — the quoted ones (utilities.hpp,
    baseline.hpp, generated-code.hpp) are handled explicitly.
    """
    try:
        text = benchmark_driver.read_text(encoding="utf-8")
    except OSError:
        return []

    return [
        line.strip()
        for line in text.splitlines()
        if SYSTEM_INCLUDE_RE.match(line)
    ]


class GccAnalyzerTool:
    """Compile-only pass with GCC's `-fanalyzer` and parse its diagnostics.

    Why this is a separate tool and not extra flags on `compiler`:

    1. The `compiler` tool is simultaneously the build gate — its exit code
       decides whether a sample compiles at all, and the correctness stage
       depends on that verdict. Adding a much more expensive analysis to that
       invocation would couple the build decision to an analysis that can time
       out on its own.
    2. `-Wall -Wextra -Wpedantic` diagnostics and `-fanalyzer` are two
       different DETECTION METHODS: syntactic/local checks in the front end vs.
       interprocedural, path-sensitive symbolic execution of the CFG. Counting
       them as one tool would hide which method found what — exactly the split
       already made between `clang_sa` and `clang_tidy_ast` in the tool
       validation.

    Method independence: this is GCC's own symbolic execution engine, sharing
    no code with Clang's Static Analyzer, cppcheck's dataflow, or Infer's
    bi-abduction, so it is a genuinely fifth generic method in the redundancy
    tier.

    REDUCED TRANSLATION UNIT (measured, not a preference): unlike the other
    static tools this one does NOT analyze the benchmark's cpu.cc. The
    analyzer explores paths under a fixed exploration budget, and on the full
    driver TU that budget is spent inside `validate()` and the std::vector
    machinery BEFORE the model function is reached — GCC then stops silently
    ("analysis bailed out early (1061 'after-snode' enodes; 3184 enodes)",
    visible only with -Wanalyzer-too-complex). Measured on a planted null
    dereference in dense_la/00: not reported for serial and omp, reported for
    mpi — i.e. the full TU makes detection depend on unrelated driver
    complexity. It also would not reproduce the configuration the tool
    validation measured, where each Juliet kernel is its own small TU.
    Analyzing `<vector>` + utilities.hpp + generated-code.hpp instead spends
    the whole budget on the model code: the planted bug is found under all
    three execution models, and the pass gets faster (~1.3 s vs ~2.7 s).
    Same pattern (and same reason class) as ParcoachTool and LLOVTool.

    Always invoked through GCC (`g++`, or `mpicxx` for MPI, which wraps the
    system GCC here) regardless of `--primary-compiler`: `-fanalyzer` is a
    GCC-only feature and being a GCC-native method is the point of this tool.
    A toolchain where the wrapper is not GCC makes the compile fail, which is
    recorded as a tool error — never as a clean sample.

    Only diagnostics carrying a `-Wanalyzer-*` flag are turned into findings;
    plain warnings from this pass are dropped because the `compiler` tool
    reports them already (they would otherwise be counted twice).
    """

    name = "gcc_analyzer"

    # hard capability (config can only narrow this; see tool_config.py)
    execution_models = ("serial", "omp", "mpi")

    def __init__(self, timeout: float = 300.0):
        # Deliberately more generous than CompilerDiagnosticTool's 120 s: the
        # analyzer explores paths symbolically and is the expensive pass.
        # Configurable via stages.static_analysis.tools.gcc_analyzer.timeout_seconds.
        self.timeout = timeout

    def is_available(self) -> bool:
        return binary_available("g++") and binary_available("mpicxx")

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        # primary_compiler is intentionally ignored (see class docstring):
        # g++ for serial/omp, mpicxx for mpi.
        config = get_build_config(sample.execution_model, primary_compiler="g++")

        if not sample.source_path.exists():
            return ToolResult(
                tool=self.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=f"missing model source: {sample.source_path}",
            )

        # Mirror cpu.cc's system-include preamble so model code may rely on it
        # exactly as it does in the real build (see driver_system_includes).
        includes = driver_system_includes(sample.benchmark_dir / "cpu.cc")

        if "#include <vector>" not in includes:
            includes.append("#include <vector>")

        with tempfile.TemporaryDirectory() as tmp:
            reduced_tu = Path(tmp) / "reduced.cc"
            reduced_tu.write_text(
                "\n".join(includes)
                + '\n#include "utilities.hpp"\n'
                + '#include "generated-code.hpp"\n',
                encoding="utf-8",
            )

            # Compile-only with the execution model's own flags and defines
            # from the BuildConfig (so OpenMP pragmas and MPI symbols are seen
            # exactly as in the real build); no binary is produced or needed.
            argv = config.base_command(
                sources=[str(reduced_tu)],
                output_path=str(Path(tmp) / "analyzer.o"),
                include_dirs=context.include_dirs(sample),
                extra_flags=[
                    "-fanalyzer",
                    # make the analyzer's own give-up points visible instead of
                    # letting an unanalyzed sample look clean (recorded as
                    # non-blocking info findings, see below)
                    "-Wanalyzer-too-complex",
                    "-c",
                    f"-D{DRIVER_PROBLEM_SIZE_DEFINE}",
                ],
            )

            result = run_command(argv, timeout=self.timeout)

        findings = [
            f
            for f in parse_gcc_clang_diagnostics(result.stderr, self.name)
            if f.check_id.startswith(ANALYZER_FLAG_PREFIX)
        ]

        for finding in findings:
            if finding.check_id in ANALYZER_NON_DEFECT_WARNINGS:
                finding.severity = "info"
                finding.blocking = False
                continue

            # -Wanalyzer-* findings are syntactically warnings but describe
            # genuine defects (null deref, double free, use-after-free,
            # out-of-bounds). Validation on Juliet: precision 0.937 overall
            # and 1.0 on the C++ kernels — high enough to gate on, and they
            # only reach the repair feedback if they do.
            finding.blocking = True

        findings = findings_in_model_file(findings, sample.source_path.name)

        # Fail-safe: a TU that does not compile (or an analyzer that times
        # out) produced no analysis, and must never look like a clean sample.
        # GCC exits 0 when it only emits warnings, so the exit code is a
        # reliable signal here.
        error = None
        if result.timed_out:
            error = "gcc_analyzer timed out"
        elif result.returncode != 0:
            error = f"gcc -fanalyzer exited with {result.returncode}"

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            error=error,
        )


# cppcheck severities -> our normalized severities
CPPCHECK_SEVERITY = {
    "error": "error",
    "warning": "warning",
    "portability": "warning",
    "performance": "info",
    "style": "info",
    "information": "info",
}

# cppcheck ids that indicate a genuine bug rather than a style nit; these
# are the blocking subset (mirrors the curated static-analysis set).
CPPCHECK_BLOCKING_SEVERITIES = {"error"}


class CppcheckTool:
    """Run cppcheck over the full translation unit and parse its XML output.

    cppcheck analyzes the benchmark's cpu.cc (which includes utilities.hpp,
    baseline.hpp and the assembled generated-code.hpp) with the same defines
    and include paths as the compile stage, so it sees real types and context
    instead of an isolated fragment. Its raw output then contains diagnostics
    from the whole TU; only those located in the model file are kept.
    """

    name = "cppcheck"

    # hard capability (config can only narrow this; see tool_config.py)
    execution_models = ("serial", "omp", "mpi")

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout

    def is_available(self) -> bool:
        return binary_available("cppcheck")

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        config = get_build_config(sample.execution_model, context.primary_compiler)

        benchmark_driver = sample.benchmark_dir / "cpu.cc"

        if not benchmark_driver.exists():
            return ToolResult(
                tool=self.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=f"missing benchmark driver: {benchmark_driver}",
            )

        include_flags: list[str] = []

        for include_dir in context.include_dirs(sample):
            include_flags += ["-I", include_dir]

        if sample.execution_model == "mpi":
            include_flags += mpi_include_flags()

        argv = [
            "cppcheck",
            "--enable=warning,portability",
            "--inconclusive",
            "--language=c++",
            "--std=c++17",
            f"-D{config.macro}",
            f"-D{DRIVER_PROBLEM_SIZE_DEFINE}",
            "--xml",
            "--xml-version=2",
            *include_flags,
            str(benchmark_driver),
        ]

        result = run_command(argv, timeout=self.timeout)

        # cppcheck writes results as XML to stderr; keep only model-file findings.
        findings = findings_in_model_file(
            self._parse_xml(result.stderr), sample.source_path.name
        )

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
        )

    def _parse_xml(self, stderr: str) -> list[Finding]:
        findings: list[Finding] = []

        start = stderr.find("<results")

        if start == -1:
            return findings

        try:
            root = ET.fromstring(stderr[start:])
        except ET.ParseError:
            return findings

        errors_node = root.find("errors")

        if errors_node is None:
            return findings

        for error in errors_node.findall("error"):
            cppcheck_severity = error.get("severity", "information")
            severity = CPPCHECK_SEVERITY.get(cppcheck_severity, "info")

            file_name = None
            line = None
            column = None

            location = error.find("location")
            if location is not None:
                file_name = Path(location.get("file", "")).name or None
                line = int(location.get("line")) if location.get("line") else None
                column = int(location.get("column")) if location.get("column") else None

            findings.append(
                Finding(
                    tool=self.name,
                    check_id=error.get("id", "unknown"),
                    severity=severity,
                    message=error.get("msg", ""),
                    file=file_name,
                    line=line,
                    column=column,
                    blocking=cppcheck_severity in CPPCHECK_BLOCKING_SEVERITIES,
                )
            )

        return findings


# Curated clang-tidy check set for parallel C++ correctness/quality.
# bugprone/concurrency/clang-analyzer/mpi/openmp are the blocking groups;
# performance is enabled but logged-only (a quality signal, not a gate).
CLANG_TIDY_BLOCKING_GROUPS = (
    "bugprone-",
    "concurrency-",
    "clang-analyzer-",
    "mpi-",
    "openmp-",
)

CLANG_TIDY_CHECKS = ",".join(
    [
        "-*",  # start from nothing, enable explicitly
        "bugprone-*",
        "concurrency-*",
        "clang-analyzer-*",
        # The Clang SA MPI checker is opt-in. On this clang-tidy (LLVM 18) the
        # clang-analyzer-* glob already runs opt-in checkers, but we name it
        # explicitly so the MPI static-analysis method is deliberate and
        # greppable, and stays enabled regardless of how a given clang-tidy
        # version treats the glob. This is the path-sensitive MPI method,
        # distinct from the AST-based mpi-* checks below and from PARCOACH's
        # dataflow analysis.
        "clang-analyzer-optin.mpi.MPI-Checker",
        "mpi-*",
        "openmp-*",
        "performance-*",
        "cppcoreguidelines-narrowing-conversions",
        "misc-*",
        # Excluded checks: systematic false positives that fire on (nearly)
        # every sample and would poison the repair loop. Documented in full in
        # thesis/docs/static-analysis-filtering.md.
        "-misc-include-cleaner",  # IWYU-style noise on short kernels
        "-misc-use-anonymous-namespace",  # irrelevant for header-embedded code
        # The assembled model code is, by scaffold design, always a function
        # definition inside a .hpp that cpu.cc includes -> fires 100% of the time.
        "-misc-definitions-in-headers",
        # OpenMPI macros (MPI_COMM_WORLD, MPI_DOUBLE, ...) expand to C-style
        # void* casts inside <mpi.h>; the diagnostic is attributed to the
        # model's line although the cast lives in the MPI header -> fires on
        # essentially all MPI samples.
        "-bugprone-casting-through-void",
    ]
)

# clang-tidy Level -> normalized severity
CLANG_TIDY_LEVEL = {
    "Error": "error",
    "Warning": "warning",
    "Remark": "info",
    "Note": "note",
}


def offset_to_line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a byte offset into (line, column), both 1-based.

    clang-tidy's -export-fixes reports byte offsets, not line/col. The
    assembled source is small, so a direct scan is fine.
    """
    if offset < 0 or offset > len(text):
        return (0, 0)

    preceding = text[:offset]
    line = preceding.count("\n") + 1
    last_newline = preceding.rfind("\n")
    column = offset - last_newline  # 1-based: char after the newline is col 1

    return (line, column)


# Checks inside blocking groups that are hygiene recommendations rather than
# defect indicators: they fire on demonstrably correct code (verified via the
# clean-kernel check in verify_detection.py) and would gate the repair loop
# for every sample. Recorded as findings, but never blocking.
CLANG_TIDY_BLOCKING_EXCEPTIONS = {
    # fires on every `#pragma omp parallel ...` without a default clause,
    # including race-free kernels; a style recommendation, not a bug signal
    "openmp-use-default-none",
}


def is_blocking_check(check_id: str) -> bool:
    if check_id in CLANG_TIDY_BLOCKING_EXCEPTIONS:
        return False

    return any(check_id.startswith(group) for group in CLANG_TIDY_BLOCKING_GROUPS)


class ClangTidyTool:
    """Run clang-tidy with the curated check set and parse -export-fixes YAML.

    The Clang Static Analyzer runs via the clang-analyzer-* checks, so this
    one tool covers both clang-tidy and the static analyzer. Findings are
    attributed to the model source file; diagnostics in driver/benchmark
    code are dropped (still recoverable from raw output).
    """

    name = "clang_tidy"

    # hard capability (config can only narrow this; see tool_config.py)
    execution_models = ("serial", "omp", "mpi")

    def __init__(self, primary_compiler: str = "g++", timeout: float = 180.0):
        # primary_compiler only affects the -std/flags passed after `--`;
        # clang-tidy always uses its own clang front-end for parsing.
        self.timeout = timeout

    def is_available(self) -> bool:
        return binary_available("clang-tidy")

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        config = get_build_config(sample.execution_model, context.primary_compiler)

        benchmark_driver = sample.benchmark_dir / "cpu.cc"

        if not benchmark_driver.exists():
            return ToolResult(
                tool=self.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=f"missing benchmark driver: {benchmark_driver}",
            )

        # clang-tidy parses with clang directly, so reproduce the compiler's
        # translation unit: analyze the benchmark's cpu.cc (which includes
        # utilities.hpp, baseline.hpp and the assembled generated-code.hpp)
        # with the same defines and include paths the compile stage uses. The
        # assembled generated-code.hpp resolves via the -I on its source dir,
        # exactly as in the real build. Findings are attributed back to the
        # model file afterwards.
        compile_flags = [
            "-std=c++17",
            f"-D{config.macro}",
            f"-D{DRIVER_PROBLEM_SIZE_DEFINE}",
        ]

        if config.needs_openmp:
            compile_flags.append("-fopenmp")

        if sample.execution_model == "mpi":
            compile_flags += mpi_include_flags()

        for include_dir in context.include_dirs(sample):
            compile_flags += ["-I", include_dir]

        with tempfile.TemporaryDirectory() as tmp:
            fixes_path = Path(tmp) / "fixes.yaml"

            argv = [
                "clang-tidy",
                f"--checks={CLANG_TIDY_CHECKS}",
                f"--export-fixes={fixes_path}",
                # cpu.cc is the main file, so its diagnostics are exported
                # regardless; this limits exported *header* diagnostics to the
                # model file (driver/benchmark headers stay out). _parse_fixes
                # then attributes strictly to generated-code.hpp.
                "--header-filter=generated-code\\.hpp$",
                str(benchmark_driver),
                "--",
                *compile_flags,
            ]

            result = run_command(argv, timeout=self.timeout)

            findings = self._parse_fixes(fixes_path, sample)

        # A clang-diagnostic-error among the findings means clang-tidy could
        # not parse the TU; treat it as blocking so the sample is never
        # silently counted as clean. (Normal findings also yield exit 1, so
        # exit code alone is not a reliable signal.)
        for finding in findings:
            if finding.check_id.startswith("clang-diagnostic-error"):
                finding.blocking = True

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
        )

    def _parse_fixes(self, fixes_path: Path, sample: AssembledSample) -> list[Finding]:
        if not fixes_path.exists():
            return []

        content = fixes_path.read_text(encoding="utf-8")

        if not content.strip():
            return []

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            return []

        if not data or "Diagnostics" not in data:
            return []

        model_file = sample.source_path.name
        # cache file contents for offset->line, keyed by path
        file_cache: dict[str, str] = {}
        findings: list[Finding] = []

        for diagnostic in data["Diagnostics"]:
            check_id = diagnostic.get("DiagnosticName", "unknown")
            level = diagnostic.get("Level", "Warning")
            severity = CLANG_TIDY_LEVEL.get(level, "warning")

            message_block = diagnostic.get("DiagnosticMessage", {})
            message = message_block.get("Message", "")
            file_path = message_block.get("FilePath", "")
            file_offset = message_block.get("FileOffset", 0)

            file_name = Path(file_path).name if file_path else None

            # attribute to model source only
            if file_name != model_file:
                continue

            if file_path not in file_cache:
                try:
                    file_cache[file_path] = Path(file_path).read_text(encoding="utf-8")
                except OSError:
                    file_cache[file_path] = ""

            line, column = offset_to_line_col(file_cache[file_path], file_offset)

            findings.append(
                Finding(
                    tool=self.name,
                    check_id=check_id,
                    severity=severity,
                    message=message,
                    file=file_name,
                    line=line if line else None,
                    column=column if column else None,
                    blocking=is_blocking_check(check_id),
                )
            )

        return findings


# Infer severity -> normalized severity. Infer marks genuine C/C++ defects
# (null-deref, resource/memory leak, uninitialized value, ...) as ERROR; those
# are the blocking subset, consistent with how the other tools gate.
INFER_SEVERITY = {
    "ERROR": "error",
    "WARNING": "warning",
    "INFO": "info",
    "ADVICE": "info",
    "LIKE": "info",
}

# InferBO (`--bufferoverrun`) encodes its confidence in the bug type's suffix:
# BUFFER_OVERRUN_L1 .. _L5 and INTEGER_OVERFLOW_L1 .. _L5, where L1 is a
# definite issue and the level rises with the amount of guessing involved.
# The _U<n> / _S<n> variants stand for unknown resp. symbolic operand values.
INFER_LEVELED_BUG_PREFIXES = ("BUFFER_OVERRUN_", "INTEGER_OVERFLOW_")

# Level assigned to the non-L suffixes (U = unknown, S = symbolic operands).
# The validation measured L-levels only, and these two denote values the
# analysis could not pin down at all, so they are ranked with the least
# reliable level instead of trusting the digit in their name.
INFER_UNRANKED_LEVEL = 5


def bufferoverrun_level(bug_type: str) -> int | None:
    """Confidence level of an InferBO bug type, or None if it carries none.

    None means "not a leveled InferBO type" — every other Infer bug type
    (NULL_DEREFERENCE, MEMORY_LEAK, ...) passes the level filter untouched.
    """
    for prefix in INFER_LEVELED_BUG_PREFIXES:
        if not bug_type.startswith(prefix):
            continue

        suffix = bug_type[len(prefix):]

        if len(suffix) == 2 and suffix[0] == "L" and suffix[1].isdigit():
            return int(suffix[1])

        return INFER_UNRANKED_LEVEL

    return None


class InferTool:
    """Run Meta Infer over the full translation unit and parse report.json.

    Infer provides a detection method (interprocedural analysis via separation
    logic / bi-abduction: null dereference, resource/memory leaks,
    uninitialized values, ...) that is independent of the AST/dataflow checks
    in clang-tidy and cppcheck, so it strengthens the generic-C++ redundancy
    tier. It captures the same TU as the compile stage (`cpu.cc` including the
    assembled generated-code.hpp) with its own bundled clang, then findings are
    attributed back to the model file.

    The invocation additionally enables InferBO (`--bufferoverrun`, buffer
    overruns and integer overflows via abstract interpretation over intervals)
    on top of the default checkers. It is the same engine and the same capture,
    so it costs one run, not two — measured 1.09x on the validation suite.

    Findings are filtered by InferBO's own confidence level (see
    `bufferoverrun_level`): the tool-validation level table is unambiguous —
    L1 produced 36 true positives and 0 false positives, L3 produced 0 true
    positives and 58 false positives. Everything above `bufferoverrun_max_level`
    is therefore DISCARDED rather than kept as non-blocking: those levels are
    measured noise, and non-blocking findings still reach the repair feedback.
    Level and threshold are recorded per finding / in the raw output, so the
    discarded ones remain reconstructable.
    """

    name = "infer"

    # hard capability (config can only narrow this; see tool_config.py)
    execution_models = ("serial", "omp", "mpi")

    def __init__(
        self,
        primary_compiler: str = "g++",
        timeout: float = 300.0,
        bufferoverrun_max_level: int = 2,
    ):
        # Infer uses its own bundled clang for capture regardless of the
        # primary compiler; the parameter is kept for a uniform constructor.
        self.timeout = timeout
        # Configurable via
        # stages.static_analysis.tools.infer.bufferoverrun_max_level.
        self.bufferoverrun_max_level = bufferoverrun_max_level

    def is_available(self) -> bool:
        return binary_available("infer")

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        config = get_build_config(sample.execution_model, context.primary_compiler)

        benchmark_driver = sample.benchmark_dir / "cpu.cc"

        if not benchmark_driver.exists():
            return ToolResult(
                tool=self.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=f"missing benchmark driver: {benchmark_driver}",
            )

        compile_flags = [
            "-std=c++17",
            f"-D{config.macro}",
            f"-D{DRIVER_PROBLEM_SIZE_DEFINE}",
        ]

        if config.needs_openmp:
            compile_flags.append("-fopenmp")

        if sample.execution_model == "mpi":
            compile_flags += mpi_include_flags()

        for include_dir in context.include_dirs(sample):
            compile_flags += ["-I", include_dir]

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "infer-out"

            # `infer run` = capture (its clang parses the TU) + analyze.
            # Compile-only (`-c`); no binary is produced or needed.
            #
            # --headers is REQUIRED: the model code lives in generated-code.hpp,
            # an included header. Without it Infer analyzes only the .cc it
            # captures (cpu.cc) and silently skips all header code, so it could
            # never report a finding in the model file. Diagnostics in the other
            # headers (utilities.hpp, baseline.hpp, system) are attributed away
            # by findings_in_model_file below.
            argv = [
                "infer",
                "run",
                "--headers",
                # InferBO on top of the default checkers: same capture, same
                # analysis run. Validation: recall 0.095 -> 0.151 with
                # precision 0.805 -> 0.867 after the level filter below.
                "--bufferoverrun",
                "-o",
                str(out_dir),
                "--keep-going",
                "--",
                "clang++",
                "-c",
                str(benchmark_driver),
                *compile_flags,
            ]

            result = run_command(argv, timeout=self.timeout)

            report_path = out_dir / "report.json"

            findings, dropped = self._filter_bufferoverrun_levels(
                findings_in_model_file(
                    self._parse_report(report_path),
                    sample.source_path.name,
                )
            )

            # Fail-safe: a failed capture/analysis (non-zero exit, timeout,
            # or missing report) must never be mistaken for a clean sample.
            # infer exits 0 on successful runs even when it finds issues.
            error = None
            if result.timed_out:
                error = "infer timed out"
            elif result.returncode != 0:
                error = f"infer exited with {result.returncode}"
            elif not report_path.exists():
                error = "infer produced no report.json"

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout + self._dropped_note(dropped),
            raw_stderr=result.stderr,
            error=error,
        )

    def _filter_bufferoverrun_levels(
        self, findings: list[Finding]
    ) -> tuple[list[Finding], list[Finding]]:
        """Split InferBO findings at `bufferoverrun_max_level`.

        Returns (kept, dropped). Non-InferBO bug types are never touched.
        Kept findings are annotated with their level in the message so the
        confidence is visible in the record and in the repair feedback.
        """
        kept: list[Finding] = []
        dropped: list[Finding] = []

        for finding in findings:
            level = bufferoverrun_level(finding.check_id)

            if level is None:
                kept.append(finding)
                continue

            if level > self.bufferoverrun_max_level:
                dropped.append(finding)
                continue

            finding.message = (
                f"{finding.message} [InferBO confidence level L{level}]".strip()
            )
            kept.append(finding)

        return kept, dropped

    def _dropped_note(self, dropped: list[Finding]) -> str:
        """Append the level-filtered findings to the persisted raw output.

        `infer run`'s console output does not enumerate suppressed issues, so
        without this line the discarded low-confidence findings would not be
        reconstructable from the record. Kept deterministic and short.
        """
        if not dropped:
            return ""

        return "\n[level filter] dropped above L%d: %s\n" % (
            self.bufferoverrun_max_level,
            "; ".join(
                "%s at %s:%s" % (f.check_id, f.file, f.line) for f in dropped
            ),
        )

    def _parse_report(self, report_path: Path) -> list[Finding]:
        if not report_path.exists():
            return []

        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        if not isinstance(data, list):
            return []

        findings: list[Finding] = []

        for item in data:
            infer_severity = item.get("severity", "WARNING")

            findings.append(
                Finding(
                    tool=self.name,
                    check_id=item.get("bug_type", "unknown"),
                    severity=INFER_SEVERITY.get(infer_severity, "warning"),
                    message=item.get("qualifier", ""),
                    file=Path(item.get("file", "")).name or None,
                    line=item.get("line") or None,
                    column=item.get("column") or None,
                    blocking=infer_severity == "ERROR",
                )
            )

        return findings


# ---------------------------------------------------------------------------
# PARCOACH (MPI collective verification on LLVM IR)
# ---------------------------------------------------------------------------

# Attribute tokens that may precede the return type in an LLVM `declare`.
LLVM_DECLARE_ATTR_TOKENS = {
    "dso_local", "noundef", "signext", "zeroext", "inreg", "nonnull",
    "dereferenceable", "align", "nocapture", "readonly", "writeonly",
    "noalias", "returned", "immarg", "nofree", "captures", "range",
}

LLVM_DECLARE_RE = re.compile(r"^declare\s+(.*?)\s*@([\w.$-]+)\((.*)$")


def stub_external_declares(ll_text: str) -> str:
    """Rewrite LLVM textual IR: give trivial bodies to external declarations.

    PARCOACH 2.4.1 hard-crashes (std::out_of_range in its ExtInfo external-
    function model) on declarations it does not know — reliably triggered by
    the C++ allocation/throw symbols (operator new/delete, __throw_*) that any
    std::vector kernel emits. Turning those declares into definitions with
    trivial bodies removes the ExtInfo lookup entirely.

    Kept as declarations (must NOT be stubbed):
      - MPI_* / PMPI_*: the subject of the analysis (PARCOACH models these),
      - llvm.* intrinsics: cannot be given bodies.

    Safety: stub bodies contain no MPI calls, so they cannot add or mask
    collective-ordering errors; only alias precision may degrade.
    """
    out: list[str] = []

    for line in ll_text.splitlines(keepends=True):
        match = LLVM_DECLARE_RE.match(line.rstrip())

        if not match:
            out.append(line)
            continue

        ret_part, name, rest = match.groups()

        if name.startswith(("llvm.", "MPI_", "PMPI_")):
            out.append(line)
            continue

        tokens = [
            t for t in ret_part.split()
            if t.split("(")[0] not in LLVM_DECLARE_ATTR_TOKENS
        ]
        return_type = " ".join(tokens) if tokens else "void"

        # find the matching close of the parameter list
        depth = 1
        end = 0
        for end, char in enumerate(rest):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break

        params = rest[:end]
        body = "  ret void" if return_type == "void" else f"  ret {return_type} undef"
        out.append(f"define {return_type} @{name}({params}) {{\n{body}\n}}\n")

    return "".join(out)


# PARCOACH warning line, e.g.:
#   PARCOACH: /path/generated-code.hpp: warning: MPI_Bcast line 8 possibly
#   not called by all processes because of conditional(s) line(s)  7
#   (/path/generated-code.hpp) (Call Ordering Error)
PARCOACH_WARNING_RE = re.compile(
    r"PARCOACH:\s+(?P<file>[^:]+):\s+warning:\s+"
    r"(?P<collective>\w+)\s+line\s+(?P<line>\d+)\s+(?P<message>.*)"
)


def parse_parcoach_output(output: str) -> list[Finding]:
    findings: list[Finding] = []

    for raw_line in output.splitlines():
        match = PARCOACH_WARNING_RE.search(raw_line)

        if not match:
            continue

        message = f"{match.group('collective')} {match.group('message')}".strip()

        findings.append(
            Finding(
                tool="parcoach",
                check_id="parcoach-collective-ordering",
                severity="warning",
                message=message,
                file=Path(match.group("file")).name,
                line=int(match.group("line")),
                column=None,
                # A collective possibly not reached by all ranks is a genuine
                # MPI correctness defect class (deadlock risk) — gate on it.
                blocking=True,
            )
        )

    return findings


class ParcoachTool:
    """Run PARCOACH's static MPI collective verification on the model kernel.

    Runs in the dedicated PARCOACH container (LLVM 15), not in the main
    toolchain image — invoke run_static_analysis.py inside
    registry.gitlab.inria.fr/parcoach/parcoach-demo:2.4.1 with
    `--tools parcoach`.

    Pipeline per sample (MPI samples only):
      1. Build a REDUCED translation unit: <vector> + utilities.hpp +
         generated-code.hpp — without the benchmark driver. The driver's
         C++ machinery crashes/hangs PARCOACH and is irrelevant to the
         collectives in the model function.
      2. Compile with the container's clang-15 using -fno-exceptions
         -fno-rtti (removes exception landingpads that segfault PARCOACH's
         Andersen AA) and -DOMPI_SKIP_MPICXX (drops OpenMPI C++ bindings it
         cannot model).
      3. stub_external_declares(): trivial bodies for non-MPI externals
         (works around PARCOACH's fatal ExtInfo lookup).
      4. parcoach <stubbed.ll>, parse warnings, attribute to the model file.
    """

    name = "parcoach"

    # hard capability (config can only narrow this; see tool_config.py)
    execution_models = ("mpi",)

    def __init__(self, timeout: float = 180.0):
        self.timeout = timeout

    def _clang(self) -> str | None:
        import shutil

        found = shutil.which("clang")
        if found:
            return found

        fallback = Path("/usr/lib/llvm-15/bin/clang")
        return str(fallback) if fallback.exists() else None

    def is_available(self) -> bool:
        return binary_available("parcoach") and self._clang() is not None

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        if sample.execution_model != "mpi":
            return ToolResult(
                tool=self.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=(
                    "not applicable: parcoach verifies MPI collectives "
                    f"(execution model is '{sample.execution_model}')"
                ),
            )

        clang = self._clang()

        include_flags: list[str] = []
        for include_dir in context.include_dirs(sample):
            include_flags += ["-I", include_dir]

        include_flags += mpi_include_flags()

        with tempfile.TemporaryDirectory() as tmp:
            reduced_tu = Path(tmp) / "reduced.cc"
            reduced_tu.write_text(
                '#include <vector>\n'
                '#include "utilities.hpp"\n'
                '#include "generated-code.hpp"\n',
                encoding="utf-8",
            )

            ll_path = Path(tmp) / "kernel.ll"

            compile_argv = [
                clang,
                "-std=c++17",
                "-fno-exceptions",
                "-fno-rtti",
                "-DOMPI_SKIP_MPICXX",
                "-DUSE_MPI",
                f"-D{DRIVER_PROBLEM_SIZE_DEFINE}",
                "-g",
                "-S",
                "-emit-llvm",
                "-c",
                str(reduced_tu),
                *include_flags,
                "-o",
                str(ll_path),
            ]

            compile_result = run_command(compile_argv, timeout=self.timeout)

            if compile_result.returncode != 0 or not ll_path.exists():
                return ToolResult(
                    tool=self.name,
                    ran=True,
                    exit_code=compile_result.returncode,
                    duration_seconds=compile_result.duration_seconds,
                    raw_stdout=compile_result.stdout,
                    raw_stderr=compile_result.stderr,
                    error="clang -emit-llvm failed for the reduced TU",
                )

            stubbed_path = Path(tmp) / "kernel.stubbed.ll"
            stubbed_path.write_text(
                stub_external_declares(ll_path.read_text(encoding="utf-8")),
                encoding="utf-8",
            )

            result = run_command(
                ["parcoach", str(stubbed_path)], timeout=self.timeout
            )

        findings = findings_in_model_file(
            parse_parcoach_output(result.stdout + "\n" + result.stderr),
            sample.source_path.name,
        )

        error = None
        if result.timed_out:
            error = "parcoach timed out"
        elif result.returncode != 0:
            # PARCOACH crashing must never look like a clean sample.
            error = f"parcoach exited with {result.returncode}"

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            error=error,
        )


# ---------------------------------------------------------------------------
# LLOV (static OpenMP data-race detection, polyhedral analysis)
# ---------------------------------------------------------------------------

# Canonical LLOV invocation flags, taken from the benchmark configuration
# shipped inside the LLOV artifact image (OmpSCR llov.cf.mk, OSCR_CPP_REPORT).
# Without them the pass either reports a race for everything (-O0 optnone
# blocks Polly) or analyzes nothing (-O1/-O2 pre-transform the region).
LLOV_ANALYSIS_FLAGS = (
    "-Xclang", "-disable-O0-optnone",
    "-mllvm", "-polly-process-unprofitable",
    "-mllvm", "-polly-invariant-load-hoisting",
    "-mllvm", "-polly-ignore-parameter-bounds",
    "-mllvm", "-polly-dependences-on-demand",
    "-g",
)

# LLOV verdict lines followed by location lines, e.g.:
#   Data Race detected.
#   Source : /path/file.hpp:13
#   Sink : /path/file.hpp:13
# or
#   Region Not Analyzed by the verifier. Loop -> <unnamed loop>
#   File : /path/file.hpp:13
# ("Region is Data Race Free." blocks produce no finding.)
LLOV_LOCATION_RE = re.compile(
    r"^\s*(?:Source|Sink|File)\s*:\s*(?P<file>.+?):(?P<line>\d+)\s*$"
)


def parse_llov_output(output: str) -> list[Finding]:
    """Parse LLOV's verdict blocks into findings.

    Emits one finding per 'Data Race detected.' block (blocking) and one
    info finding per 'Region Not Analyzed' block — the latter keeps LLOV's
    honest "could not analyze" verdict visible per sample instead of
    conflating it with "race free".
    """
    findings: list[Finding] = []
    pending: Finding | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            findings.append(pending)
            pending = None

    for raw_line in output.splitlines():
        line = raw_line.strip()

        if line.startswith("Data Race detected"):
            flush()
            pending = Finding(
                tool="llov",
                check_id="llov-data-race",
                severity="warning",
                message="Data race detected (LLOV polyhedral analysis)",
                blocking=True,
            )
        elif line.startswith("Region Not Analyzed"):
            flush()
            pending = Finding(
                tool="llov",
                check_id="llov-region-not-analyzed",
                severity="info",
                message="OpenMP region not analyzable by LLOV (no race verdict)",
                blocking=False,
            )
        elif line.startswith("Region is Data Race Free"):
            flush()
        else:
            match = LLOV_LOCATION_RE.match(line)
            if match and pending is not None and pending.file is None:
                pending.file = Path(match.group("file")).name
                pending.line = int(match.group("line"))

    flush()
    return findings


class LLOVTool:
    """Run LLOV's static OpenMP data-race verification on the model kernel.

    Runs in the dedicated LLOV container (LLOV artifact image + Python 3.8,
    see docker/Dockerfile.llov), not in the main toolchain image — invoke
    run_static_analysis.py inside `pareval-llov` with `--tools llov`.

    LLOV is a compile-time LLVM pass: the analysis happens during a plugin
    compile of a REDUCED translation unit (<vector> + utilities.hpp +
    generated-code.hpp, no benchmark driver) with LLOV's own clang 7.1 and
    the canonical Polly flags from its benchmark configuration. OpenMP
    samples only; verdicts: race (blocking) / not-analyzed (info) / race
    free (no finding).
    """

    name = "llov"

    # hard capability (config can only narrow this; see tool_config.py)
    execution_models = ("omp",)

    def __init__(self, llov_home: str = "/home/llvm/Work/LLOV", timeout: float = 180.0):
        import os

        self.llov_home = Path(os.environ.get("LLOV_HOME", llov_home))
        self.timeout = timeout

    @property
    def _clang(self) -> Path:
        return self.llov_home / "bin" / "clang++"

    @property
    def _plugin(self) -> Path:
        return self.llov_home / "lib" / "OpenMPVerify.so"

    def is_available(self) -> bool:
        return self._clang.exists() and self._plugin.exists()

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        if sample.execution_model != "omp":
            return ToolResult(
                tool=self.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=(
                    "not applicable: llov verifies OpenMP data races "
                    f"(execution model is '{sample.execution_model}')"
                ),
            )

        include_flags: list[str] = []
        for include_dir in context.include_dirs(sample):
            include_flags += ["-I", include_dir]

        with tempfile.TemporaryDirectory() as tmp:
            reduced_tu = Path(tmp) / "reduced.cc"
            reduced_tu.write_text(
                '#include <vector>\n'
                '#include "utilities.hpp"\n'
                '#include "generated-code.hpp"\n',
                encoding="utf-8",
            )

            argv = [
                str(self._clang),
                "-Xclang", "-load", "-Xclang", str(self._plugin),
                "-fopenmp",
                "-std=c++17",
                *LLOV_ANALYSIS_FLAGS,
                "-DUSE_OMP",
                f"-D{DRIVER_PROBLEM_SIZE_DEFINE}",
                *include_flags,
                "-c",
                str(reduced_tu),
                "-o",
                str(Path(tmp) / "out.o"),
            ]

            result = run_command(argv, timeout=self.timeout)

        findings = findings_in_model_file(
            parse_llov_output(result.stdout + "\n" + result.stderr),
            sample.source_path.name,
        )

        error = None
        if result.timed_out:
            error = "llov timed out"
        elif result.returncode != 0:
            # A failed plugin compile means no analysis happened — must not
            # be mistaken for a race-free sample.
            error = f"llov clang exited with {result.returncode}"

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            error=error,
        )


def register_default_tools(
    primary_compiler: str = "g++", config: dict[str, Any] | None = None
) -> None:
    """Register the static tools; `config` supplies the per-tool options.

    Without a config every tool keeps its constructor default, so callers
    that only need the tools themselves (verify_detection.py) stay unchanged.
    """
    register_tool(CompilerDiagnosticTool(primary_compiler=primary_compiler))
    register_tool(
        GccAnalyzerTool(
            timeout=float(
                tool_option(config, "static_analysis", "gcc_analyzer",
                            "timeout_seconds", 300.0)
            )
        )
    )
    register_tool(CppcheckTool())
    register_tool(ClangTidyTool(primary_compiler=primary_compiler))
    register_tool(
        InferTool(
            primary_compiler=primary_compiler,
            bufferoverrun_max_level=int(
                tool_option(config, "static_analysis", "infer",
                            "bufferoverrun_max_level", 2)
            ),
        )
    )
    register_tool(ParcoachTool())
    register_tool(LLOVTool())
