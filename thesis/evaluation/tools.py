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
    STATE_COMPLETED,
    STATE_NOT_ANALYZED,
    STATE_NOT_APPLICABLE,
    STATE_PARTIAL,
    STATE_TIMEOUT,
    STATE_TOOL_ERROR,
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
                analysis_state=STATE_TOOL_ERROR,
                analysis_gap_reason="missing inputs (infrastructure, not a model defect)",
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

        # Tool-state wave: a build TIMEOUT is not a proven model defect (the
        # compiler never produced a verdict), so it is an analysis gap, not a
        # synthetic compile error. A NON-ZERO exit with the build finished IS
        # the model's own compile failure - the authoritative build verdict -
        # and stays a COMPLETED analysis with a blocking finding.
        if result.timed_out:
            return ToolResult(
                tool=self.name,
                ran=True,
                exit_code=result.returncode,
                duration_seconds=result.duration_seconds,
                findings=[],
                raw_stdout=result.stdout,
                raw_stderr=result.stderr,
                error="compile timed out",
                analysis_state=STATE_TIMEOUT,
                analysis_gap_reason=(
                    "compile exceeded %.0f s; no build verdict" % self.build_timeout
                ),
            )

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

        # Tool-state wave (measured in the audit): a missing compiler binary,
        # an internal compiler error, a `cc1plus: fatal error` (out of
        # memory, killed) or a non-zero exit WITHOUT any error diagnostic is
        # the TOOLCHAIN failing, not the model. Those never get the synthetic
        # compile-failed finding (which would be rendered to the repair LLM
        # as the model's compile error) - they are TOOL_ERROR analysis gaps.
        toolchain_failure = compiler_toolchain_failure(result)
        if toolchain_failure is None and result.returncode != 0 \
                and not COMPILER_ERROR_MARKER_RE.search(result.stderr or ""):
            toolchain_failure = (
                "compiler exited with %d without any error diagnostic "
                "(no build verdict)" % result.returncode
            )

        if toolchain_failure is not None:
            return ToolResult(
                tool=self.name,
                ran=True,
                exit_code=result.returncode,
                duration_seconds=result.duration_seconds,
                findings=[f for f in findings if not f.blocking],
                raw_stdout=result.stdout,
                raw_stderr=result.stderr,
                error=toolchain_failure,
                analysis_state=STATE_TOOL_ERROR,
                analysis_gap_reason=toolchain_failure,
                analysis_details={"build_ok": False, "toolchain_failure": True},
            )

        # Guarantee at least one blocking finding when the compile failed,
        # so downstream logic can treat "did not build" uniformly.
        if result.returncode != 0 and not any(f.blocking for f in findings):
            findings.append(
                Finding(
                    tool=self.name,
                    check_id="compile-failed",
                    severity="error",
                    message="compilation failed",
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
            # the build ran to a verdict either way: success, or the model's
            # own compile error (a COMPLETED analysis with a blocking finding)
            analysis_state=STATE_COMPLETED,
            analysis_details={"build_ok": result.returncode == 0},
        )


# An error diagnostic that proves the compiler judged the code: a located
# `error:` line, or the linker rejecting the program (a missing model
# function is `undefined reference` -> a model defect, not a toolchain one).
COMPILER_ERROR_MARKER_RE = re.compile(
    r"(?m)(?:^|\s)error:|undefined reference|ld returned \d+ exit status"
)

# Toolchain-side failure signatures (measured / documented gcc forms). Lines
# located at a model or driver file (`file:line:col: fatal error:` e.g. a
# missing include) are NOT in this set: those are the model's build errors.
# NOT in this set: `collect2: error: ld returned 1 exit status` - a link
# failure (undefined reference to a function the model declared but never
# defined) is the model's own build failure (measured by the reviewer).
COMPILER_TOOLCHAIN_FAILURE_RE = re.compile(
    r"(?m)^(?:cc1plus|cc1|g\+\+|gcc|mpicxx|mpic\+\+|clang\+\+|clang)"
    r": (?:fatal error|error): (?!.*\bno such file\b.*\.(?:cc|cpp|hpp|h)\b)"
    r"|internal compiler error|Killed signal terminated program"
    r"|out of memory allocating|Segmentation fault signal terminated"
)


def compiler_toolchain_failure(result: "CommandResult") -> "str | None":
    """Human reason when the compile PROCESS failed on the toolchain side,
    None when the compiler produced a build verdict (exit 0, or exit != 0
    with the model's own error diagnostics)."""
    stderr = result.stderr or ""
    if result.returncode == -1 and not result.timed_out:
        first = next((l for l in stderr.splitlines() if l.strip()), "process failed")
        return "compiler binary unavailable or not startable: %s" % first[:160]
    match = COMPILER_TOOLCHAIN_FAILURE_RE.search(stderr)
    if match:
        line_start = stderr.rfind("\n", 0, match.start()) + 1
        line_end = stderr.find("\n", match.start())
        line = stderr[line_start:(line_end if line_end >= 0 else None)].strip()
        return "toolchain failure (not a model defect): %s" % line[:200]
    return None


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

# ---------------------------------------------------------------------------
# GCC -fanalyzer EVENT PATH (tool-state wave)
#
# -fanalyzer explains each defect with a path-sensitive trace rendered as
# inline events:
#
#   file.hpp:12:6: warning: dereference of NULL [CWE-476] [-Wanalyzer-null-dereference]
#      12 |   *p = 42;
#         |   ~~~^~~~
#     'void f(int)': events 1-3
#       |
#       |   10 |   int *p = nullptr;
#       |      |        ^~~~~~~
#       |      |        |
#       |      |        (1) p is NULL
#       |   11 |   if (N > 3)
#       |      |      (2) following true branch...
#       |......
#       |   12 |   *p = 42;
#       |      |      (3) dereference of NULL p
#
# The generic diagnostic parser keeps only the headline; the trace used to
# live exclusively in raw_stderr and never reached the repair prompt. The
# parser below attaches the events to the ONE root finding (never separate
# findings, never counted): where the state originated, the branch condition,
# where the defect occurs. Cross-function/cross-file blocks are tracked so
# driver/system events stay context and the root attribution is unchanged.
# ---------------------------------------------------------------------------

ANALYZER_EVENT_RE = re.compile(r"\((?P<n>\d+)\)\s+(?P<text>.+?)\s*$")
ANALYZER_SOURCE_LINE_RE = re.compile(r"^\s*\|\s*(?P<line>\d+)\s*\|")
ANALYZER_FUNCTION_RE = re.compile(r"^\s*'(?P<function>.+)':\s+events?\s+\d+")
ANALYZER_LOCATION_RE = re.compile(
    r"^\s*\|?\s*(?P<file>[^\s:|]+\.(?:hpp|cc|cpp|h|c)):(?P<line>\d+):\d+:\s*$"
)

# Deterministic cap on the events attached to one finding: the first ones
# (origin) and the last ones (defect) are the informative ends of a path.
ANALYZER_PATH_MAX_EVENTS = 12
ANALYZER_PATH_HEAD = 5
ANALYZER_PATH_TAIL = 7


def parse_gcc_analyzer_paths(stderr: str) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Event paths of every -Wanalyzer-* headline, keyed by (file name, line).

    Each event: {"n": int, "text": str, "line": int|None, "file": str|None,
    "function": str|None}. `file` is the basename the block was last
    positioned in (None while inside the headline file).
    """
    paths: dict[tuple[str, int], list[dict[str, Any]]] = {}
    current_key: tuple[str, int] | None = None
    current_file: str | None = None
    current_function: str | None = None
    current_line: int | None = None

    for raw_line in stderr.splitlines():
        match = GCC_CLANG_DIAGNOSTIC.match(raw_line.strip())
        if match and match.group("severity") in ("warning", "error"):
            flag = match.group("flag") or ""
            if flag.startswith(ANALYZER_FLAG_PREFIX):
                current_key = (Path(match.group("file")).name, int(match.group("line")))
                paths.setdefault(current_key, [])
                current_file = None
                current_function = None
                current_line = int(match.group("line"))
            else:
                current_key = None
            continue

        if current_key is None:
            continue

        function_match = ANALYZER_FUNCTION_RE.match(raw_line)
        if function_match:
            current_function = function_match.group("function")
            continue

        location_match = ANALYZER_LOCATION_RE.match(raw_line)
        if location_match:
            current_file = Path(location_match.group("file")).name
            current_line = int(location_match.group("line"))
            continue

        source_match = ANALYZER_SOURCE_LINE_RE.match(raw_line)
        if source_match:
            current_line = int(source_match.group("line"))

        event_match = ANALYZER_EVENT_RE.search(raw_line)
        if event_match and "|" in raw_line:
            paths[current_key].append({
                "n": int(event_match.group("n")),
                "text": event_match.group("text"),
                "line": current_line,
                "file": current_file,
                "function": current_function,
            })

    return paths


def cap_analyzer_path(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic cap: first ANALYZER_PATH_HEAD + last ANALYZER_PATH_TAIL
    events with one elision marker in between."""
    if len(events) <= ANALYZER_PATH_MAX_EVENTS:
        return list(events)

    omitted = len(events) - ANALYZER_PATH_HEAD - ANALYZER_PATH_TAIL
    return (
        events[:ANALYZER_PATH_HEAD]
        + [{"n": None, "text": "... %d event(s) omitted ..." % omitted,
            "line": None, "file": None, "function": None}]
        + events[-ANALYZER_PATH_TAIL:]
    )


def attach_gcc_analyzer_paths(findings: list[Finding], stderr: str) -> None:
    """Attach the parsed event path to each analyzer defect finding
    (Finding.path). Findings stay one-per-headline; nothing is added."""
    if not findings:
        return

    paths = parse_gcc_analyzer_paths(stderr)

    for finding in findings:
        if finding.check_id in ANALYZER_NON_DEFECT_WARNINGS or finding.line is None:
            continue
        events = paths.get((finding.file or "", finding.line))
        if events:
            finding.path = cap_analyzer_path(events)


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


def reduced_tu_preamble(sample: AssembledSample) -> list[str]:
    """System-include preamble shared by every reduced translation unit
    (gcc_analyzer, parcoach, llov): cpu.cc's `<...>` includes plus <vector>."""
    includes = driver_system_includes(sample.benchmark_dir / "cpu.cc")
    if "#include <vector>" not in includes:
        includes.append("#include <vector>")
    return includes


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
                analysis_state=STATE_TOOL_ERROR,
                analysis_gap_reason="missing model source (infrastructure)",
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

        # Tool-state wave: coverage loss must be judged BEFORE the model-file
        # filter. Measured in the audit: `analysis bailed out early` is
        # attributed to a libstdc++ header (or to `cc1plus:` with no
        # location at all) and a planted defect in the model file is then
        # silently missed - the record must not look clean.
        too_complex_total = sum(
            1 for f in findings if f.check_id in ANALYZER_NON_DEFECT_WARNINGS
        )
        bailed_out = bool(ANALYZER_BAILOUT_RE.search(result.stderr or ""))

        findings = findings_in_model_file(findings, sample.source_path.name)

        # Tool-state wave: attach the analyzer's path EVENTS to each defect
        # finding (one logical defect stays ONE finding; events are context,
        # never separate findings, never counted) so the repair feedback can
        # show where the state originated, the branch condition and where the
        # defect occurs.
        attach_gcc_analyzer_paths(findings, result.stderr)

        # Fail-safe: a TU that does not compile (or an analyzer that times
        # out) produced no analysis, and must never look like a clean sample.
        # GCC exits 0 when it only emits warnings, so the exit code is a
        # reliable signal here.
        too_complex = sum(
            1 for f in findings if f.check_id in ANALYZER_NON_DEFECT_WARNINGS
        )
        error = None
        if result.timed_out:
            error = "gcc_analyzer timed out"
            state, gap = STATE_TIMEOUT, (
                "gcc -fanalyzer exceeded %.0f s; no analysis verdict" % self.timeout
            )
        elif result.returncode != 0:
            error = f"gcc -fanalyzer exited with {result.returncode}"
            # the reduced TU did not compile: no symbolic execution happened.
            # The build verdict itself belongs to the `compiler` tool - here
            # it is an analysis gap, not a second model defect.
            state, gap = STATE_TOOL_ERROR, (
                "translation unit did not compile under g++ -fanalyzer "
                "(the compiler tool carries the build verdict)"
            )
        elif bailed_out or too_complex_total:
            # -Wanalyzer-too-complex: the analyzer gave up on at least one
            # path (or on the whole exploration: "bailed out early"). Paths
            # analyzed before that point WERE analyzed (defect findings on
            # them are real), so this is PARTIAL - never a defect, never a
            # complete clean proof.
            if bailed_out:
                gap = (
                    "gcc -fanalyzer bailed out early (analysis budget "
                    "exhausted for the whole exploration); remaining paths "
                    "of the model code carry no verdict"
                )
            else:
                gap = (
                    "-Wanalyzer-too-complex on %d program point(s) (%d in the "
                    "model file): unanalyzed successors carry no verdict"
                    % (too_complex_total, too_complex)
                )
            state = STATE_PARTIAL
        else:
            state, gap = STATE_COMPLETED, None

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            error=error,
            analysis_state=state,
            analysis_gap_reason=gap,
            analysis_details={
                "too_complex_count": too_complex,
                "too_complex_total": too_complex_total,
                "bailed_out_early": bailed_out,
                "tu_rejected": state == STATE_TOOL_ERROR,
            },
        )


# TU-level give-up of the analyzer; appears as
#   `<header>:L:C: warning: analysis bailed out early (...) [-Wanalyzer-too-complex]`
# or location-less `cc1plus: warning: analysis bailed out early (...)`
# (the latter is not matched by the file:line diagnostic regex at all).
ANALYZER_BAILOUT_RE = re.compile(r"analysis bailed out early")


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
                analysis_state=STATE_TOOL_ERROR,
                analysis_gap_reason="missing benchmark driver (infrastructure)",
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
        parsed, xml_state = self._parse_xml(result.stderr)
        findings = findings_in_model_file(parsed, sample.source_path.name)

        # Tool-side diagnostics (cppcheck could not parse/preprocess the
        # code) are an ANALYSIS GAP, not a model defect: the authoritative
        # compiler is the build gate. They stay in the record, non-blocking.
        tool_side = 0
        for finding in findings:
            if finding.check_id not in CPPCHECK_TOOL_SIDE_IDS:
                continue
            # a genuine `#error` / `#warning` directive in the model code is
            # the model's own build failure, not cppcheck's inability
            # (measured: message text starts with the directive itself,
            # whereas lexer failures read "No pair for character ...")
            if finding.check_id == "preprocessorErrorDirective" and (
                    finding.message or "").lstrip().startswith(("#error", "#warning")):
                continue
            finding.blocking = False
            finding.severity = "info"
            tool_side += 1

        error = None
        if result.timed_out:
            error = "cppcheck timed out"
            state, gap = STATE_TIMEOUT, (
                "cppcheck exceeded %.0f s; no verdict" % self.timeout
            )
        elif result.returncode != 0:
            # measured: CLI/path errors exit 1 with the message on STDOUT and
            # an empty stderr (no XML at all)
            error = f"cppcheck exited with {result.returncode}"
            first = next(
                (l for l in (result.stdout or "").splitlines() if l.strip()), "no output"
            )
            state, gap = STATE_TOOL_ERROR, "cppcheck process failed: %s" % first[:160]
        elif xml_state != "ok":
            # "no XML" is never clean: nothing proves the analysis ran
            error = "cppcheck produced %s XML result block" % (
                "no" if xml_state == "missing" else "a malformed"
            )
            state, gap = STATE_TOOL_ERROR, error
        elif tool_side:
            state, gap = STATE_PARTIAL, (
                "%d cppcheck tool-side diagnostic(s) (syntax/preprocessor/"
                "internal): parts of the code were not analyzed" % tool_side
            )
        else:
            state, gap = STATE_COMPLETED, None

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            error=error,
            analysis_state=state,
            analysis_gap_reason=gap,
            analysis_details={"xml": xml_state, "tool_side_diagnostics": tool_side,
                "tu_rejected": tool_side > 0,
            },
        )

    def _parse_xml(self, stderr: str) -> "tuple[list[Finding], str]":
        """(findings, xml_state) with xml_state in ok | missing | malformed."""
        findings: list[Finding] = []

        start = stderr.find("<results")

        if start == -1:
            return findings, "missing"

        try:
            root = ET.fromstring(stderr[start:])
        except ET.ParseError:
            return findings, "malformed"

        errors_node = root.find("errors")

        if errors_node is None:
            return findings, "ok"

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

        return findings, "ok"


# cppcheck ids that report cppcheck's OWN inability to process the code
# (its parser/preprocessor is not the authoritative compiler). They are
# analysis gaps, never model defects; see CppcheckTool.run.
CPPCHECK_TOOL_SIDE_IDS = {
    "syntaxError",
    "internalError",
    "internalAstError",
    "cppcheckError",
    "preprocessorErrorDirective",
    "unknownMacro",
    "missingInclude",
    "missingIncludeSystem",
}


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
                analysis_state=STATE_TOOL_ERROR,
                analysis_gap_reason="missing benchmark driver (infrastructure)",
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
            fixes_present = fixes_path.exists()

        # A clang-diagnostic-error among the findings means clang-tidy's OWN
        # front-end could not parse the TU. Tool-state wave: that is an
        # ANALYSIS GAP (TOOL_ERROR), not a model defect - the authoritative
        # build verdict belongs to the `compiler` tool (g++). Before this
        # wave the diagnostic was marked blocking so the sample could not be
        # counted clean; the state now carries that guarantee, and the
        # diagnostic stays in the record as a non-blocking error-severity
        # finding that is never sent to the repair LLM as a defect.
        parse_errors = [
            f for f in findings if f.check_id.startswith("clang-diagnostic-error")
        ]
        for finding in parse_errors:
            finding.blocking = False

        # The rejection signal must come from the RAW output: clang may
        # locate every error in baseline.hpp / cpu.cc (measured in pilot_001
        # iteration records), and the model-file attribution above drops
        # those findings - the TU is rejected all the same.
        frontend_rejected = bool(parse_errors) or (
            "Found compiler error" in (result.stderr or "")
        )

        error = None
        if result.timed_out:
            error = "clang_tidy timed out"
            state, gap = STATE_TIMEOUT, (
                "clang-tidy exceeded %.0f s; no verdict" % self.timeout
            )
        elif frontend_rejected:
            error = "clang front-end could not parse the translation unit"
            state, gap = STATE_TOOL_ERROR, (
                "clang-diagnostic-error: %s" % parse_errors[0].message[:160]
                if parse_errors
                else "clang-diagnostic-error located outside the model file "
                     "(driver/benchmark headers); see raw output"
            )
        elif result.returncode != 0:
            # Measured on LLVM 18 (tool-state wave audit): check findings
            # never change the exit code - clean and warning-only runs exit
            # 0. A non-zero exit without a clang-diagnostic-error is the
            # tool itself failing (unwritable fixes file, bad configuration,
            # missing binary, crash) and its findings, if any, are lost.
            error = f"clang-tidy exited with {result.returncode}"
            last = next(
                (l for l in reversed((result.stderr or "").splitlines()) if l.strip()),
                "no stderr",
            )
            state, gap = STATE_TOOL_ERROR, "clang-tidy process failed: %s" % last[:160]
        elif not fixes_present and "warning" not in (result.stderr or ""):
            # exit 0, no fixes file AND no diagnostic summary at all: nothing
            # proves the checks ran on this TU (a run on the benchmark drivers
            # always reports suppressed system-header warnings)
            error = "clang-tidy exited 0 without --export-fixes output or diagnostics"
            state, gap = STATE_TOOL_ERROR, (
                "no fixes file and no diagnostic summary: nothing proves the "
                "checks ran"
            )
        else:
            state, gap = STATE_COMPLETED, None

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            error=error,
            analysis_state=state,
            analysis_gap_reason=gap,
            analysis_details={
                "frontend_parse_errors": len(parse_errors),
                "fixes_present": fixes_present,
                "tu_rejected": frontend_rejected,
            },
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


# infer's clang frontend gives up on a method it cannot translate (measured
# for every OpenMP kernel: "Aborting translation of method 'luFactorize' in
# file '.../cpu.cc'") - the run still exits 0 with a report.json
INFER_ABORT_RE = re.compile(r"Aborting translation of method '([^']+)'")

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
                analysis_state=STATE_TOOL_ERROR,
                analysis_gap_reason="missing benchmark driver (infrastructure)",
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
                # bufferoverrun_max_level: 0 switches it off entirely instead
                # of paying for findings that would all be discarded.
                *(["--bufferoverrun"] if self.bufferoverrun_max_level > 0 else []),
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
            # evaluated INSIDE the temp dir (it is gone at return time)
            report_present = report_path.exists() and not result.timed_out
            report_parse_ok = True
            if report_present:
                try:
                    parsed_report = json.loads(report_path.read_text(encoding="utf-8"))
                    report_parse_ok = isinstance(parsed_report, list)
                except (OSError, ValueError):
                    report_parse_ok = False
            aborted_methods = INFER_ABORT_RE.findall(result.stderr or "")
            nothing_analyzed = (
                "Nothing to compile" in (result.stderr or "")
                or "There was nothing to analyze" in (result.stderr or "")
            )

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
                state, gap = STATE_TIMEOUT, (
                    "infer exceeded %.0f s; no verdict" % self.timeout
                )
            elif result.returncode != 0:
                error = f"infer exited with {result.returncode}"
                state, gap = STATE_TOOL_ERROR, (
                    "infer capture/analysis failed (its bundled clang did not "
                    "accept the TU, or the analysis crashed); the compiler tool "
                    "carries the build verdict"
                )
            elif not report_present:
                error = "infer produced no report.json"
                state, gap = STATE_TOOL_ERROR, "no report.json: nothing proves the analysis ran"
            elif not report_parse_ok:
                error = "infer report.json is not a parseable issue list"
                state, gap = STATE_TOOL_ERROR, "unparseable report.json: no verdict"
            elif nothing_analyzed:
                error = "infer captured nothing"
                state, gap = STATE_TOOL_ERROR, (
                    "infer reported 'nothing to analyze' (no translation unit was "
                    "captured): an empty report is not a clean verdict"
                )
            elif aborted_methods:
                # Measured: infer's clang-11 frontend cannot translate OpenMP
                # captured statements and DROPS the whole method (every OMP
                # kernel of pilot_001) while exiting 0 with a report. Findings
                # elsewhere are real; the absence of findings in the aborted
                # method(s) is no verdict.
                names = sorted(set(aborted_methods))
                state = STATE_PARTIAL if findings else STATE_NOT_ANALYZED
                gap = (
                    "infer's clang-11 frontend aborted translation of %d method(s) "
                    "(%s): those bodies were not analyzed (OpenMP captured "
                    "statements unsupported); no verdict for them"
                    % (len(names), ", ".join(names[:4]))
                )
            else:
                state, gap = STATE_COMPLETED, None

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout + self._dropped_note(dropped),
            raw_stderr=result.stderr,
            error=error,
            analysis_state=state,
            analysis_gap_reason=gap,
            analysis_details={
                "report_present": report_present,
                "report_parse_ok": report_parse_ok,
                "aborted_methods": sorted(set(aborted_methods)),
                "bufferoverrun_dropped": len(dropped),
                "tu_rejected": state == STATE_TOOL_ERROR and not result.timed_out
                and result.returncode != 0,
            },
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

    def __init__(self, timeout: float = 60.0):
        # 60 s (lowered from 180, 2026-08-08). Measured on smoke_003:
        # PARCOACH is BIMODAL — successful runs finish at p95 0.03 s,
        # while ~45% of samples are GENUINE hangs (model-correlated, the
        # analysis never terminates on them). A higher timeout rescues no
        # run and costs 120 s per hang; the timeout also covers the
        # clang -emit-llvm step, so do not go below 60 s. Configurable via
        # stages.static_analysis.tools.parcoach.timeout_seconds.
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
                analysis_state=STATE_NOT_APPLICABLE,
            )

        clang = self._clang()

        include_flags: list[str] = []
        for include_dir in context.include_dirs(sample):
            include_flags += ["-I", include_dir]

        include_flags += mpi_include_flags()

        with tempfile.TemporaryDirectory() as tmp:
            reduced_tu = Path(tmp) / "reduced.cc"
            # Tool-state wave: mirror cpu.cc's system-include preamble exactly
            # like GccAnalyzerTool. Measured on pilot_001: without it the
            # reduced TU failed on code the authoritative g++ builds (missing
            # std::sort / std::array / std::min from <algorithm>/<array>) and
            # the tool recorded a TOOL_ERROR that used to pass as clean. The
            # preamble changes nothing for samples that already compiled
            # (identical findings and output, measured on 6 pilot samples).
            reduced_tu.write_text(
                "\n".join(reduced_tu_preamble(sample))
                + '\n#include "utilities.hpp"\n'
                + '#include "generated-code.hpp"\n',
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
                # The REDUCED TU (not the model's real build) failed to
                # compile with the container's clang: an analysis gap of the
                # harness, never a model defect - the authoritative build
                # verdict belongs to the `compiler` tool.
                first_error = next(
                    (l.strip() for l in compile_result.stderr.splitlines()
                     if "error:" in l), "")
                return ToolResult(
                    tool=self.name,
                    ran=True,
                    exit_code=compile_result.returncode,
                    duration_seconds=compile_result.duration_seconds,
                    raw_stdout=compile_result.stdout,
                    raw_stderr=compile_result.stderr,
                    error="clang -emit-llvm failed for the reduced TU",
                    analysis_state=(
                        STATE_TIMEOUT if compile_result.timed_out else STATE_TOOL_ERROR
                    ),
                    analysis_gap_reason=(
                        "reduced-TU compile timed out" if compile_result.timed_out
                        else "reduced TU did not compile in the PARCOACH container: "
                        + first_error[:200]
                    ),
                    analysis_details={"phase": "emit-llvm"},
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
            state, gap = STATE_TIMEOUT, (
                "parcoach exceeded %.0f s (measured bimodal: genuine hangs; a "
                "longer timeout rescues nothing); no verdict" % self.timeout
            )
        elif result.returncode != 0:
            # PARCOACH crashing must never look like a clean sample.
            error = f"parcoach exited with {result.returncode}"
            state, gap = STATE_TOOL_ERROR, "parcoach crashed / exited non-zero"
        else:
            state, gap = STATE_COMPLETED, None

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            error=error,
            analysis_state=state,
            analysis_gap_reason=gap,
            analysis_details={"phase": "parcoach"},
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
# Locations come as `path:line` or (pilot_001 output, LLOV on clang 7)
# `path:line:col`; the old regex required the 2-field form and silently
# dropped every 3-field verdict (file became "generated-code.hpp:16" and
# failed the model-file filter) - 2 pilot samples lost their only data-race
# verdict. Tool-state wave: both forms are accepted.
LLOV_LOCATION_RE = re.compile(
    r"^\s*(?:Source|Sink|File)\s*:\s*(?P<file>.+?):(?P<line>\d+)(?::(?P<col>\d+))?\s*$"
)

# LLOV's "could not analyze" verdict has two wordings (both measured in
# pilot_001 raw output): "Region Not Analyzed by the verifier." and
# "Directive Not Analyzed by the verifier."; only the first was parsed before
# the tool-state wave, so 28 pilot records whose ONLY output was the second
# form were stored as 0 findings (= looked race free).
LLOV_NOT_ANALYZED_PREFIXES = ("Region Not Analyzed", "Directive Not Analyzed")


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
        elif line.startswith(LLOV_NOT_ANALYZED_PREFIXES):
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


def parse_llov_regions(output: str) -> dict[str, int]:
    """Per-region verdict counts of one LLOV run (race / free / not_analyzed).

    The counts are what the analysis STATE is derived from; the findings
    (parse_llov_output) only carry race and not-analyzed blocks, so a
    "Region is Data Race Free." block would otherwise be indistinguishable
    from "no region seen at all".
    """
    counts = {"race": 0, "free": 0, "not_analyzed": 0}

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("Data Race detected"):
            counts["race"] += 1
        elif line.startswith(LLOV_NOT_ANALYZED_PREFIXES):
            counts["not_analyzed"] += 1
        elif line.startswith("Region is Data Race Free"):
            counts["free"] += 1

    return counts


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
                analysis_state=STATE_NOT_APPLICABLE,
            )

        include_flags: list[str] = []
        for include_dir in context.include_dirs(sample):
            include_flags += ["-I", include_dir]

        with tempfile.TemporaryDirectory() as tmp:
            reduced_tu = Path(tmp) / "reduced.cc"
            # Tool-state wave: mirror cpu.cc's system-include preamble exactly
            # like GccAnalyzerTool. Measured on pilot_001: without it the
            # reduced TU failed on code the authoritative g++ builds (missing
            # std::sort / std::array / std::min from <algorithm>/<array>) and
            # the tool recorded a TOOL_ERROR that used to pass as clean. The
            # preamble changes nothing for samples that already compiled
            # (identical findings and output, measured on 6 pilot samples).
            reduced_tu.write_text(
                "\n".join(reduced_tu_preamble(sample))
                + '\n#include "utilities.hpp"\n'
                + '#include "generated-code.hpp"\n',
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

        output = result.stdout + "\n" + result.stderr
        findings = findings_in_model_file(
            parse_llov_output(output), sample.source_path.name
        )
        regions = parse_llov_regions(output)

        # Tool-state wave. LLOV's verdicts are per OpenMP REGION:
        #   "Region is Data Race Free."             analysed, clean
        #   "Data Race detected."                   analysed, defect
        #   "Region Not Analyzed by the verifier."  NO verdict for that region
        # "Region Not Analyzed" is therefore NEVER race-free; a run whose
        # regions were all unanalysed (or that emitted no region verdict at
        # all) carries no trustworthy verdict.
        error = None
        if result.timed_out:
            error = "llov timed out"
            state, gap = STATE_TIMEOUT, (
                "LLOV plugin compile exceeded %.0f s; no verdict" % self.timeout
            )
        elif result.returncode != 0:
            # A failed plugin compile means no analysis happened — must not
            # be mistaken for a race-free sample.
            error = f"llov clang exited with {result.returncode}"
            state, gap = STATE_TOOL_ERROR, (
                "LLOV clang 7 could not compile the reduced TU (exit %d); the "
                "compiler tool carries the build verdict" % result.returncode
            )
        elif regions["race"] > 0:
            state = STATE_PARTIAL if regions["not_analyzed"] else STATE_COMPLETED
            gap = (
                "%d region(s) not analyzed besides the detected race(s)"
                % regions["not_analyzed"] if regions["not_analyzed"] else None
            )
        elif regions["not_analyzed"] > 0 and regions["free"] > 0:
            state, gap = STATE_PARTIAL, (
                "%d of %d OpenMP region(s) not analyzed by LLOV (no race verdict "
                "for them)" % (regions["not_analyzed"],
                               regions["not_analyzed"] + regions["free"])
            )
        elif regions["not_analyzed"] > 0:
            state, gap = STATE_NOT_ANALYZED, (
                "all %d OpenMP region(s) reported Region Not Analyzed - no race "
                "verdict exists" % regions["not_analyzed"]
            )
        elif regions["free"] > 0:
            state, gap = STATE_COMPLETED, None
        else:
            state, gap = STATE_NOT_ANALYZED, (
                "LLOV emitted no region verdict at all (no analysable OpenMP "
                "region seen by the plugin) - not evidence of race freedom"
            )

        if state in (STATE_TIMEOUT, STATE_TOOL_ERROR):
            # measured: a run can print region verdicts and then crash
            # (isl_ctx abort, exit 254); verdicts of a failed run are not
            # trusted - no findings from a run without a clean exit
            findings = []

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=result.returncode,
            duration_seconds=result.duration_seconds,
            findings=findings,
            raw_stdout=result.stdout,
            raw_stderr=result.stderr,
            error=error,
            analysis_state=state,
            analysis_gap_reason=gap,
            analysis_details={"regions": regions},
        )


# ---------------------------------------------------------------------------
# Tool identity / implementation condition (tool-state wave)
# ---------------------------------------------------------------------------

# Per tool: the module-level callables whose SOURCE defines the tool's
# behaviour besides its class (parsers, TU construction, filters). Hashed
# content-addressed so a change to one tool's implementation is visible in
# THAT tool's execution fingerprint without a git HEAD.
_IMPLEMENTATION_DEPS: dict[str, tuple[str, ...]] = {
    "compiler": ("CompilerDiagnosticTool", "parse_gcc_clang_diagnostics"),
    "gcc_analyzer": ("GccAnalyzerTool", "parse_gcc_clang_diagnostics",
                     "driver_system_includes", "parse_gcc_analyzer_paths",
                     "cap_analyzer_path", "attach_gcc_analyzer_paths",
                     "findings_in_model_file"),
    "clang_tidy": ("ClangTidyTool", "is_blocking_check", "offset_to_line_col",
                   "mpi_include_flags"),
    "cppcheck": ("CppcheckTool", "findings_in_model_file", "mpi_include_flags"),
    "infer": ("InferTool", "bufferoverrun_level", "findings_in_model_file",
              "mpi_include_flags"),
    "parcoach": ("ParcoachTool", "parse_parcoach_output", "stub_external_declares",
                 "findings_in_model_file", "mpi_include_flags"),
    "llov": ("LLOVTool", "parse_llov_output", "parse_llov_regions",
             "findings_in_model_file"),
}

# Constant tables that change a tool's classification (hashed alongside).
_IMPLEMENTATION_TABLES: dict[str, tuple[str, ...]] = {
    "gcc_analyzer": ("ANALYZER_NON_DEFECT_WARNINGS", "ANALYZER_PATH_MAX_EVENTS"),
    "clang_tidy": ("CLANG_TIDY_CHECKS", "CLANG_TIDY_BLOCKING_GROUPS",
                   "CLANG_TIDY_BLOCKING_EXCEPTIONS", "CLANG_TIDY_LEVEL"),
    "cppcheck": ("CPPCHECK_SEVERITY", "CPPCHECK_BLOCKING_SEVERITIES",
                 "CPPCHECK_TOOL_SIDE_IDS"),
    "infer": ("INFER_SEVERITY", "INFER_LEVELED_BUG_PREFIXES", "INFER_UNRANKED_LEVEL"),
    "parcoach": ("PARCOACH_WARNING_RE", "LLVM_DECLARE_ATTR_TOKENS"),
    "llov": ("LLOV_ANALYSIS_FLAGS", "LLOV_LOCATION_RE"),
    "compiler": ("DRIVER_PROBLEM_SIZE_DEFINE",),
}

_TOOL_VERSION_COMMANDS: dict[str, list[str]] = {
    "compiler": ["g++", "--version"],
    "gcc_analyzer": ["g++", "--version"],
    "clang_tidy": ["clang-tidy", "--version"],
    "cppcheck": ["cppcheck", "--version"],
    "infer": ["infer", "--version"],
    "parcoach": ["parcoach", "--version"],
}

_IDENTITY_CACHE: dict[str, str | None] = {}


def tool_implementation_sha256(tool_name: str) -> str:
    """Content hash of the tool implementation: its class, the helper
    callables and constant tables it depends on (from THIS module)."""
    import hashlib
    import inspect

    module = globals()
    parts: list[str] = []
    for symbol in _IMPLEMENTATION_DEPS.get(tool_name, ()):
        obj = module.get(symbol)
        parts.append("%s\n%s" % (symbol, inspect.getsource(obj) if obj is not None else "<missing>"))
    for symbol in _IMPLEMENTATION_TABLES.get(tool_name, ()):
        parts.append("%s=%s" % (symbol, _canonical_table(module.get(symbol))))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _canonical_table(value: Any) -> str:
    """Process-independent text form of a constant table: sets are sorted
    (str hash randomization made their repr vary between processes), dicts
    are sorted by key, regexes contribute their pattern and flags."""
    if hasattr(value, "pattern"):
        return "re(%r, %d)" % (value.pattern, int(value.flags))
    if isinstance(value, (set, frozenset)):
        return "{%s}" % ", ".join(sorted(repr(v) for v in value))
    if isinstance(value, dict):
        return "{%s}" % ", ".join(
            "%r: %s" % (k, _canonical_table(v))
            for k, v in sorted(value.items(), key=lambda kv: repr(kv[0])))
    if isinstance(value, (list, tuple)):
        return "[%s]" % ", ".join(_canonical_table(v) for v in value)
    return repr(value)


def tool_runtime_identity(tool_name: str) -> str | None:
    """`<tool> --version` first non-empty line, measured once per process;
    None when the binary is absent (never invented). LLOV is identified by
    its own clang++ under LLOV_HOME."""
    if tool_name in _IDENTITY_CACHE:
        return _IDENTITY_CACHE[tool_name]

    identity: str | None = None
    argv = _TOOL_VERSION_COMMANDS.get(tool_name)

    if tool_name == "llov":
        try:
            tool = LLOVTool()
            argv = [str(tool._clang), "--version"] if tool._clang.exists() else None
        except Exception:  # noqa: BLE001
            argv = None

    if argv and (binary_available(argv[0]) or Path(argv[0]).exists()):
        result = run_command(argv, timeout=20.0)
        text = (result.stdout or "") + "\n" + (result.stderr or "")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if lines:
            identity = lines[0][:200]
            if tool_name == "clang_tidy" and len(lines) > 1 and "version" in lines[1].lower():
                identity = lines[1][:200]

    _IDENTITY_CACHE[tool_name] = identity
    return identity


def tool_option_snapshot(tool: Any) -> dict[str, Any]:
    """The effective constructor options of a registered tool object (the
    values register_default_tools resolved from the config)."""
    snapshot: dict[str, Any] = {}
    for attribute in ("timeout", "build_timeout", "bufferoverrun_max_level",
                      "primary_compiler", "llov_home"):
        if hasattr(tool, attribute):
            value = getattr(tool, attribute)
            snapshot[attribute] = str(value) if isinstance(value, Path) else value
    return snapshot


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
    register_tool(
        ParcoachTool(
            timeout=float(
                tool_option(config, "static_analysis", "parcoach",
                            "timeout_seconds", 60.0)
            )
        )
    )
    register_tool(LLOVTool())
