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


def register_default_tools(primary_compiler: str = "g++") -> None:
    register_tool(CompilerDiagnosticTool(primary_compiler=primary_compiler))
    register_tool(CppcheckTool())
