"""Initial concrete analysis tools.

Implemented here:
  - CompilerDiagnosticTool: compiles the sample with -Wall -Wextra
    -Wpedantic and parses gcc/clang diagnostics into Findings. This is
    both the cheapest static-analysis layer and the authoritative compile
    check; a non-zero compiler exit is blocking.
  - CppcheckTool: runs cppcheck and parses its structured XML output.

Both write the exact command they ran into the ToolResult, so the runs are
reproducible from the JSONL alone.
"""

from __future__ import annotations

import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from thesis.evaluation.build_config import get_build_config
from thesis.evaluation.framework import (
    AssembledSample,
    EvaluationContext,
    Finding,
    ToolResult,
    binary_available,
    register_tool,
    run_command,
)

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
            problem_size = '(1<<8)'

            argv = config.base_command(
                sources=[str(model_driver), str(benchmark_driver)],
                output_path=exec_path,
                include_dirs=context.include_dirs(sample),
                extra_flags=[f'-DDRIVER_PROBLEM_SIZE={problem_size}'],
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
    """Run cppcheck and parse its XML (version 2) output."""

    name = "cppcheck"

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout

    def is_available(self) -> bool:
        return binary_available("cppcheck")

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        include_flags: list[str] = []

        for include_dir in context.include_dirs(sample):
            include_flags += ["-I", include_dir]

        config = get_build_config(sample.execution_model, context.primary_compiler)

        argv = [
            "cppcheck",
            "--enable=warning,portability",
            "--inconclusive",
            "--language=c++",
            "--std=c++17",
            f"-D{config.macro}",
            "--xml",
            "--xml-version=2",
            *include_flags,
            str(sample.source_path),
        ]

        result = run_command(argv, timeout=self.timeout)

        # cppcheck writes results as XML to stderr.
        findings = self._parse_xml(result.stderr)

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
        "mpi-*",
        "openmp-*",
        "performance-*",
        "cppcoreguidelines-narrowing-conversions",
        "misc-*",
        # noisy/irrelevant misc checks for short benchmark kernels
        "-misc-include-cleaner",
        "-misc-use-anonymous-namespace",
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


def is_blocking_check(check_id: str) -> bool:
    return any(check_id.startswith(group) for group in CLANG_TIDY_BLOCKING_GROUPS)


class ClangTidyTool:
    """Run clang-tidy with the curated check set and parse -export-fixes YAML.

    The Clang Static Analyzer runs via the clang-analyzer-* checks, so this
    one tool covers both clang-tidy and the static analyzer. Findings are
    attributed to the model source file; diagnostics in driver/benchmark
    code are dropped (still recoverable from raw output).
    """

    name = "clang_tidy"

    def __init__(self, primary_compiler: str = "g++", timeout: float = 180.0):
        # primary_compiler only affects the -std/flags passed after `--`;
        # clang-tidy always uses its own clang front-end for parsing.
        self.timeout = timeout

    def is_available(self) -> bool:
        return binary_available("clang-tidy")

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        config = get_build_config(sample.execution_model, context.primary_compiler)

        compile_flags = ["-std=c++17", f"-D{config.macro}"]

        if config.needs_openmp:
            compile_flags.append("-fopenmp")

        # The assembled generated-code.hpp is never compiled standalone: the
        # benchmark's cpu.cc includes utilities.hpp (which defines NO_INLINE
        # and pulls in the std headers) immediately before it. Reproduce that
        # context with a forced include so clang-tidy parses the same TU the
        # compiler sees; without it every sample fails to parse.
        utilities_header = context.drivers_cpp_dir / "utilities.hpp"
        if utilities_header.exists():
            compile_flags += ["-include", str(utilities_header)]

        for include_dir in context.include_dirs(sample):
            compile_flags += ["-I", include_dir]

        with tempfile.TemporaryDirectory() as tmp:
            fixes_path = Path(tmp) / "fixes.yaml"

            argv = [
                "clang-tidy",
                f"--checks={CLANG_TIDY_CHECKS}",
                f"--export-fixes={fixes_path}",
                # only surface diagnostics from the model's own file
                f"--header-filter=^$",
                str(sample.source_path),
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


def register_default_tools(primary_compiler: str = "g++") -> None:
    register_tool(CompilerDiagnosticTool(primary_compiler=primary_compiler))
    register_tool(CppcheckTool())
    register_tool(ClangTidyTool(primary_compiler=primary_compiler))
