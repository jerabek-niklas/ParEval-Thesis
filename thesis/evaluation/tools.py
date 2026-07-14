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

import json
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


class InferTool:
    """Run Meta Infer over the full translation unit and parse report.json.

    Infer provides a detection method (interprocedural analysis via separation
    logic / bi-abduction: null dereference, resource/memory leaks,
    uninitialized values, ...) that is independent of the AST/dataflow checks
    in clang-tidy and cppcheck, so it strengthens the generic-C++ redundancy
    tier. It captures the same TU as the compile stage (`cpu.cc` including the
    assembled generated-code.hpp) with its own bundled clang, then findings are
    attributed back to the model file.
    """

    name = "infer"

    def __init__(self, primary_compiler: str = "g++", timeout: float = 300.0):
        # Infer uses its own bundled clang for capture regardless of the
        # primary compiler; the parameter is kept for a uniform constructor.
        self.timeout = timeout

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

            findings = findings_in_model_file(
                self._parse_report(report_path),
                sample.source_path.name,
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
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            error=error,
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


def register_default_tools(primary_compiler: str = "g++") -> None:
    register_tool(CompilerDiagnosticTool(primary_compiler=primary_compiler))
    register_tool(CppcheckTool())
    register_tool(ClangTidyTool(primary_compiler=primary_compiler))
    register_tool(InferTool(primary_compiler=primary_compiler))
    register_tool(ParcoachTool())
    register_tool(LLOVTool())
