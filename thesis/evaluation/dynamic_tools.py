"""Dynamic (runtime) analysis tools: sanitizer-instrumented executions.

Same Tool protocol, findings model and attribution philosophy as the static
tools (thesis/evaluation/tools.py, thesis/docs/static-analysis-filtering.md):
the whole benchmark program is instrumented and executed, the sanitizers
report over the full program, and only reports whose stack/location reaches
the model's generated-code.hpp are kept as findings. Everything else stays
in the raw output for auditing.

Implemented tools:
  - AsanUbsanTool ("asan_ubsan"): AddressSanitizer + LeakSanitizer + UBSan in
    one instrumented binary (all execution models). Memory errors, leaks and
    undefined behaviour that actually occur during the driver's validation
    and timing runs.
  - TsanTool ("tsan"): ThreadSanitizer for OpenMP samples, compiled with
    clang++ against LLVM's libomp and run with libarcher (OMPT tool) so that
    OpenMP synchronization is modelled — the gcc/libgomp+TSan combination
    reports false races inside the OpenMP runtime itself.

Each tool compiles its own instrumented binary (sanitizers change codegen,
-O1 -g for usable stack traces) and runs it over the same launch grid as the
correctness stage with niter=1. Findings are deduplicated per sample across
launch parameters by (check_id, line): the same race reported at 2, 4 and 8
threads is one finding.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from thesis.evaluation.build_config import get_build_config, get_launch_config
from thesis.evaluation.framework import (
    AssembledSample,
    EvaluationContext,
    Finding,
    ToolResult,
    binary_available,
    register_tool,
    run_command,
)
from thesis.evaluation.tools import DRIVER_PROBLEM_SIZE_DEFINE, mpi_include_flags

# Sanitizer builds: -O1 keeps traces readable and the run fast enough while
# still exercising optimized code paths; frame pointers for symbolization.
# Appended after the BuildConfig base flags, so -O1 overrides the base -O3.
SANITIZER_BASE_FLAGS = ("-O1", "-g", "-fno-omit-frame-pointer")

# Iterations of the drivers' timing loops (validation unaffected, see
# run_correctness.py). 1 keeps sanitizer runs short; the kernel still
# executes under instrumentation during validation + one timing pass.
SANITIZER_NITER = 1

OUTPUT_CAP_PER_RUN = 4000

# ---------------------------------------------------------------------------
# Report parsing
# ---------------------------------------------------------------------------

# ==PID==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x... / or
# ==PID==ERROR: LeakSanitizer: detected memory leaks
# The kind may contain spaces ("detected memory leaks", "attempting
# double-free") but ends before location qualifiers ("on address ...",
# "at pc ...") or end of line.
ASAN_HEADER = re.compile(
    r"ERROR: (?P<san>AddressSanitizer|LeakSanitizer): "
    r"(?P<kind>[-\w]+(?: [-\w]+)*?)(?=\s+(?:on|at)\s|\s*$)"
)

# WARNING: ThreadSanitizer: data race (pid=123)
TSAN_HEADER = re.compile(r"WARNING: ThreadSanitizer: (?P<kind>[\w ]+?) \(")

# file:line:col: runtime error: <message>   (UBSan, standalone line)
UBSAN_LINE = re.compile(
    r"^(?P<file>[^:\s][^:]*):(?P<line>\d+):(?P<col>\d+): runtime error: (?P<msg>.+)$"
)

SUMMARY_LINE = re.compile(r"^\s*SUMMARY: ")

# TSan report metadata sections that follow the racing-access stacks. Frames
# below these lines (heap-allocation stack, mutex-creation stack, thread-
# creation stack) routinely pass through the model's parallel region even for
# libomp-runtime-internal false positives — e.g. "Atomic read vs mutex init"
# inside libomp.so, whose thread/allocation stacks reach the model's
# `#pragma omp parallel`. Attribution therefore considers ONLY the access
# stacks above the first metadata section.
TSAN_METADATA_SECTION = re.compile(
    r"^\s*(Location is|Mutex M\d|Thread T\d+ [('])"
)


def slugify(kind: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", kind.strip().lower()).strip("-")


def model_frame_line(block: list[str], model_file: str) -> int | None:
    """First generated-code.hpp:<line> mentioned in a report block."""
    frame = re.compile(re.escape(model_file) + r":(\d+)")

    for line in block:
        match = frame.search(line)
        if match:
            return int(match.group(1))

    return None


def parse_sanitizer_output(stderr: str, model_file: str, tool_name: str) -> list[Finding]:
    """Parse ASan/LSan/TSan blocks and UBSan lines from run stderr.

    Attribution: a block becomes a finding only if its stack frames (or, for
    UBSan, the location itself) reach the model file. Reports rooted in the
    driver, benchmark or libraries are dropped (still visible in raw output).
    """
    findings: list[Finding] = []
    lines = stderr.splitlines()

    current_header: tuple[str, str] | None = None  # (check_id, message)
    current_block: list[str] = []

    def close_block() -> None:
        nonlocal current_header, current_block

        if current_header is not None:
            check_id, message = current_header

            attribution_lines = current_block
            if check_id.startswith("tsan-"):
                for index, block_line in enumerate(current_block):
                    if TSAN_METADATA_SECTION.match(block_line):
                        attribution_lines = current_block[:index]
                        break

            line_no = model_frame_line(attribution_lines, model_file)

            if line_no is not None:
                findings.append(
                    Finding(
                        tool=tool_name,
                        check_id=check_id,
                        severity="error",
                        message=message,
                        file=model_file,
                        line=line_no,
                        blocking=True,
                    )
                )

        current_header = None
        current_block = []

    for raw_line in lines:
        asan = ASAN_HEADER.search(raw_line)
        tsan = TSAN_HEADER.search(raw_line)

        if asan or tsan:
            close_block()

            if asan:
                prefix = "asan" if asan.group("san") == "AddressSanitizer" else "lsan"
                kind = slugify(asan.group("kind"))
            else:
                prefix = "tsan"
                kind = slugify(tsan.group("kind"))

            current_header = (f"{prefix}-{kind}", raw_line.strip().lstrip("=0123456789").strip())
            current_block = []
            continue

        if current_header is not None:
            current_block.append(raw_line)

            if SUMMARY_LINE.match(raw_line):
                close_block()
            continue

        ubsan = UBSAN_LINE.match(raw_line.strip())

        if ubsan and Path(ubsan.group("file")).name == model_file:
            findings.append(
                Finding(
                    tool=tool_name,
                    check_id="ubsan-runtime-error",
                    severity="error",
                    message=ubsan.group("msg"),
                    file=model_file,
                    line=int(ubsan.group("line")),
                    column=int(ubsan.group("col")),
                    blocking=True,
                )
            )

    close_block()

    return findings


def dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, int | None]] = set()
    unique: list[Finding] = []

    for finding in findings:
        key = (finding.check_id, finding.line)
        if key not in seen:
            seen.add(key)
            unique.append(finding)

    return unique


# ---------------------------------------------------------------------------
# Shared runner for instrumented executions
# ---------------------------------------------------------------------------


class _SanitizerToolBase:
    """Compile with instrumentation, run over the launch grid, parse stderr."""

    name: str = ""
    execution_models: tuple[str, ...] = ("serial", "omp", "mpi")

    def __init__(self, build_timeout: float = 180.0, run_timeout: float = 120.0):
        self.build_timeout = build_timeout
        self.run_timeout = run_timeout

    # --- hooks implemented by subclasses ---------------------------------

    def compiler_for(self, sample: AssembledSample, context: EvaluationContext) -> str:
        raise NotImplementedError

    def sanitize_flags(self) -> list[str]:
        raise NotImplementedError

    def run_env(self) -> dict[str, str]:
        return {}

    # ----------------------------------------------------------------------

    def is_available(self) -> bool:
        return True

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        if sample.execution_model not in self.execution_models:
            return ToolResult(
                tool=self.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=(
                    f"not applicable to execution model '{sample.execution_model}'"
                ),
            )

        config = get_build_config(sample.execution_model, self.compiler_for(sample, context))

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

        duration = 0.0
        raw_segments: list[str] = []
        findings: list[Finding] = []
        error: str | None = None

        with tempfile.TemporaryDirectory() as tmp:
            exec_path = str(Path(tmp) / "sanitized.out")

            argv = config.base_command(
                sources=[str(model_driver), str(benchmark_driver)],
                output_path=exec_path,
                include_dirs=context.include_dirs(sample),
                extra_flags=[
                    f"-D{DRIVER_PROBLEM_SIZE_DEFINE}",
                    *SANITIZER_BASE_FLAGS,
                    *self.sanitize_flags(),
                ],
            )

            build = run_command(argv, timeout=self.build_timeout)
            duration += build.duration_seconds

            if build.returncode != 0 or build.timed_out:
                # A failed instrumented build means no analysis happened —
                # must not be mistaken for a clean sample.
                return ToolResult(
                    tool=self.name,
                    ran=True,
                    exit_code=build.returncode,
                    duration_seconds=duration,
                    error="instrumented build failed"
                    + (" (timeout)" if build.timed_out else ""),
                    raw_stderr=build.stderr[:OUTPUT_CAP_PER_RUN],
                )

            launch = get_launch_config(sample.execution_model)
            last_exit = 0

            for params in launch.params:
                run_argv, launch_env = launch.command(
                    exec_path, params, niter=SANITIZER_NITER
                )

                env = {**launch_env, **self.run_env()}

                result = run_command(
                    run_argv, timeout=self.run_timeout, cwd=tmp, extra_env=env
                )
                duration += result.duration_seconds
                last_exit = result.returncode

                # Sanitizers report to stderr; MPI interleaves rank output.
                findings += parse_sanitizer_output(
                    result.stderr, sample.source_path.name, self.name
                )

                raw_segments.append(
                    f"--- run {params or '{}'} exit={result.returncode}"
                    f"{' TIMEOUT' if result.timed_out else ''} ---\n"
                    + result.stderr[:OUTPUT_CAP_PER_RUN]
                )

                if result.timed_out:
                    # Under TSan/ASan slowdown a timeout is ambiguous
                    # (deadlock vs. slow run); flag it, keep other runs.
                    error = f"run timed out at params {params}"

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=last_exit,
            duration_seconds=duration,
            findings=dedupe(findings),
            raw_stderr="\n".join(raw_segments),
            error=error,
        )


class AsanUbsanTool(_SanitizerToolBase):
    """AddressSanitizer + LeakSanitizer + UBSan, all execution models."""

    name = "asan_ubsan"
    execution_models = ("serial", "omp", "mpi")

    def compiler_for(self, sample: AssembledSample, context: EvaluationContext) -> str:
        return context.primary_compiler

    def sanitize_flags(self) -> list[str]:
        return ["-fsanitize=address,undefined"]

    def run_env(self) -> dict[str, str]:
        return {
            "ASAN_OPTIONS": "detect_leaks=1",
            "UBSAN_OPTIONS": "print_stacktrace=0",
        }

    def is_available(self) -> bool:
        return binary_available("g++")


class TsanTool(_SanitizerToolBase):
    """ThreadSanitizer for OpenMP samples (clang++ + libomp + libarcher)."""

    name = "tsan"
    execution_models = ("omp",)

    # Cached preflight result: None = not yet run, str = failure reason.
    _preflight_error: str | None | bool = None

    PREFLIGHT_HINT = (
        "TSan binaries crash at startup when the kernel's ASLR entropy is too "
        "high (vm.mmap_rnd_bits > 28; Docker Desktop's WSL2 VM defaults to 32). "
        "Fix once per VM boot: docker run --privileged --rm ubuntu:24.04 "
        "sysctl -w vm.mmap_rnd_bits=28"
    )

    def preflight(self) -> str | None:
        """Compile and run a trivial TSan binary once; failure means every
        TSan run would crash before reporting anything, which must surface
        as a tool error rather than as clean samples."""
        if TsanTool._preflight_error is not None:
            return TsanTool._preflight_error or None

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "pf.cc"
            binary = Path(tmp) / "pf.out"
            src.write_text("int main() { return 0; }\n", encoding="utf-8")

            build = run_command(
                ["clang++", "-fsanitize=thread", str(src), "-o", str(binary)],
                timeout=60.0,
            )

            if build.returncode != 0:
                TsanTool._preflight_error = (
                    "TSan preflight build failed (libclang-rt missing?): "
                    + build.stderr.strip()[:200]
                )
                return TsanTool._preflight_error

            probe = run_command([str(binary)], timeout=30.0)

            if probe.returncode != 0:
                TsanTool._preflight_error = (
                    f"TSan preflight binary exited {probe.returncode}. "
                    + self.PREFLIGHT_HINT
                )
                return TsanTool._preflight_error

        TsanTool._preflight_error = False  # success sentinel
        return None

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        if sample.execution_model in self.execution_models:
            failure = self.preflight()

            if failure:
                return ToolResult(
                    tool=self.name,
                    ran=False,
                    exit_code=None,
                    duration_seconds=0.0,
                    error=failure,
                )

        return super().run(sample, context)

    def compiler_for(self, sample: AssembledSample, context: EvaluationContext) -> str:
        # Always clang++: TSan must run against LLVM's libomp (with the
        # archer OMPT tool) — gcc links libgomp, whose internals TSan
        # falsely reports as racing.
        return "clang++"

    def sanitize_flags(self) -> list[str]:
        return ["-fsanitize=thread"]

    @staticmethod
    def archer_lib() -> Path | None:
        """LLVM-version-agnostic lookup of the archer OMPT tool library."""
        candidates = sorted(Path("/usr/lib").glob("llvm-*/lib/libarcher.so"))
        return candidates[-1] if candidates else None

    def run_env(self) -> dict[str, str]:
        env = {"TSAN_OPTIONS": "halt_on_error=0"}

        archer = self.archer_lib()
        if archer is not None:
            env["OMP_TOOL_LIBRARIES"] = str(archer)

        return env

    def is_available(self) -> bool:
        return binary_available("clang++")


# ---------------------------------------------------------------------------
# Valgrind Memcheck (dynamic binary instrumentation)
# ---------------------------------------------------------------------------

# Helgrind and DRD are implemented as regular pipeline tools (subclasses of
# MemcheckTool below) but DISABLED BY DEFAULT via config: the DataRaceBench
# validation measured Helgrind at recall 0.93 with FP-RATE 0.89 (it flags
# nearly every race-free OpenMP kernel — stock futex-based runtimes are not
# understood; Valgrind's manual requires an OpenMP runtime built with
# --disable-linux-futex) and DRD at recall 0.20. Enabling them is a config
# decision (stages.dynamic_analysis.tools); their findings then carry
# low_confidence via the default low_precision_warning: true. OpenMP race
# redundancy in the default set is TSan/Archer (dynamic) + LLOV (static).


def slug_kind(kind: str) -> str:
    """Valgrind error kind -> check id slug (InvalidRead -> invalid-read)."""
    kebab = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", kind.replace("_", "-"))
    return re.sub(r"-+", "-", kebab).lower().strip("-")


def parse_valgrind_xml(xml_text: str, model_file: str, tool_name: str) -> list[Finding]:
    """Parse valgrind --xml=yes output; keep errors whose stack reaches the
    model file. Location = the innermost model-file frame."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    findings: list[Finding] = []

    for error in root.iter("error"):
        kind = error.findtext("kind", default="unknown")

        # "Possibly lost" is a systematic artifact on OpenMP samples: the
        # libgomp thread pool is still alive at exit and its allocation stack
        # runs through the first parallel region entered — a model-file frame
        # — so it fired on 100% of OMP samples (uniform "320 bytes possibly
        # lost"). Genuine leaks stay covered by Leak_DefinitelyLost here and
        # by LeakSanitizer in the asan_ubsan tool.
        if kind == "Leak_PossiblyLost":
            continue

        message = (
            error.findtext("xwhat/text")
            or error.findtext("what")
            or kind
        )

        line_no: int | None = None
        for frame in error.iter("frame"):
            if frame.findtext("file") == model_file:
                line_text = frame.findtext("line")
                line_no = int(line_text) if line_text else None
                break

        if line_no is None:
            continue

        findings.append(
            Finding(
                tool=tool_name,
                check_id=f"memcheck-{slug_kind(kind)}",
                severity="error",
                message=message,
                file=model_file,
                line=line_no,
                blocking=True,
            )
        )

    return findings


class MemcheckTool:
    """Valgrind Memcheck: memory errors via dynamic binary instrumentation.

    The compile-independent second method for the memory-error class next to
    ASan (compile-time instrumentation). Plain -O1 -g build, executed under
    valgrind with XML output. Scope: serial and omp (one reduced grid point —
    valgrind serializes threads, so thread count does not matter for memory
    errors). MPI is excluded: per-rank valgrind wrapping under mpirun adds
    complexity while ASan already covers MPI memory errors dynamically.
    """

    name = "memcheck"
    execution_models = ("serial", "omp")

    # Valgrind slows execution 20-50x; one grid point per model suffices.
    LAUNCH_PARAMS = {"serial": [{}], "omp": [{"num_threads": 2}]}

    # subclasses select the valgrind tool; the XML parser is shared and
    # memcheck-prefixed, run() rewrites the prefix for non-memcheck tools
    VALGRIND_TOOL = "memcheck"

    def __init__(self, build_timeout: float = 180.0, run_timeout: float = 300.0):
        self.build_timeout = build_timeout
        self.run_timeout = run_timeout

    def is_available(self) -> bool:
        return binary_available("valgrind")

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        if sample.execution_model not in self.execution_models:
            return ToolResult(
                tool=self.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=(
                    f"not applicable to execution model '{sample.execution_model}'"
                ),
            )

        config = get_build_config(sample.execution_model, context.primary_compiler)

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

        duration = 0.0
        findings: list[Finding] = []
        raw_segments: list[str] = []
        error: str | None = None

        with tempfile.TemporaryDirectory() as tmp:
            exec_path = str(Path(tmp) / "plain.out")

            argv = config.base_command(
                sources=[str(model_driver), str(benchmark_driver)],
                output_path=exec_path,
                include_dirs=context.include_dirs(sample),
                extra_flags=[f"-D{DRIVER_PROBLEM_SIZE_DEFINE}", *SANITIZER_BASE_FLAGS],
            )

            build = run_command(argv, timeout=self.build_timeout)
            duration += build.duration_seconds

            if build.returncode != 0 or build.timed_out:
                return ToolResult(
                    tool=self.name,
                    ran=True,
                    exit_code=build.returncode,
                    duration_seconds=duration,
                    error="build failed" + (" (timeout)" if build.timed_out else ""),
                    raw_stderr=build.stderr[:OUTPUT_CAP_PER_RUN],
                )

            launch = get_launch_config(
                sample.execution_model,
                overrides={sample.execution_model: self.LAUNCH_PARAMS[sample.execution_model]},
            )

            last_exit = 0

            for index, params in enumerate(launch.params):
                xml_path = Path(tmp) / f"memcheck_{index}.xml"

                binary_argv, launch_env = launch.command(
                    exec_path, params, niter=SANITIZER_NITER
                )

                run_argv = [
                    "valgrind",
                    "--tool=" + self.VALGRIND_TOOL,
                    "--xml=yes",
                    f"--xml-file={xml_path}",
                    *binary_argv,
                ]

                result = run_command(
                    run_argv, timeout=self.run_timeout, cwd=tmp, extra_env=launch_env
                )
                duration += result.duration_seconds
                last_exit = result.returncode

                xml_text = ""
                if xml_path.exists():
                    xml_text = xml_path.read_text(encoding="utf-8", errors="replace")

                parsed = parse_valgrind_xml(
                    xml_text, sample.source_path.name, self.name
                )

                # single parser source: check_ids come back "memcheck-<kind>";
                # helgrind/drd rewrite the prefix to their own name
                if self.VALGRIND_TOOL != "memcheck":
                    for finding in parsed:
                        finding.check_id = self.name + finding.check_id[len("memcheck"):]

                findings += parsed

                raw_segments.append(
                    f"--- run {params or '{}'} exit={result.returncode}"
                    f"{' TIMEOUT' if result.timed_out else ''} ---\n"
                    + result.stderr[:OUTPUT_CAP_PER_RUN]
                )

                if result.timed_out:
                    error = f"run timed out at params {params}"

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=last_exit,
            duration_seconds=duration,
            findings=dedupe(findings),
            raw_stderr="\n".join(raw_segments),
            error=error,
        )


# ---------------------------------------------------------------------------
# MUST (dynamic MPI correctness checking)
# ---------------------------------------------------------------------------

# MUST error-id token in a report row, e.g. MUST_ERROR_DEADLOCK,
# MUST_WARNING_...; severity and kind are derived from it.
MUST_ID_TOKEN = re.compile(r"MUST_(?P<sev>ERROR|WARNING|INFO)_(?P<kind>[A-Z0-9_]+)")

HTML_TAG = re.compile(r"<[^>]+>")


def parse_must_html(html: str, model_file: str, tool_name: str) -> list[Finding]:
    """Parse MUST_Output.html; keep entries whose call references reach the
    model file (references look like `luFactorize@/path/generated-code.hpp:12`).

    An entry spans MULTIPLE table rows: the main row carries the
    MUST_ERROR_*/MUST_WARNING_* token, the following (hidden) detail row
    carries the message and the call references. Parsing therefore segments
    the flattened document text from token to token instead of per row.
    """
    frame = re.compile(re.escape(model_file) + r":(\d+)")

    text = HTML_TAG.sub(" ", html)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    tokens = list(MUST_ID_TOKEN.finditer(text))
    findings: list[Finding] = []

    for index, token in enumerate(tokens):
        segment_end = tokens[index + 1].start() if index + 1 < len(tokens) else len(text)
        segment = text[token.end():segment_end]

        location = frame.search(segment)

        if not location:
            continue

        severity = "error" if token.group("sev") == "ERROR" else (
            "warning" if token.group("sev") == "WARNING" else "info"
        )

        # message = segment text without the reference tail
        message = re.split(r"References of a representative process", segment)[0].strip()

        findings.append(
            Finding(
                tool=tool_name,
                check_id=f"must-{slug_kind(token.group('kind').title())}",
                severity=severity,
                message=message[:400],
                file=model_file,
                line=int(location.group(1)),
                blocking=severity == "error",
            )
        )

    return findings


class MustTool:
    """MUST: dynamic MPI correctness checking (deadlocks, type matching,
    collective verification) via PnMPI interposition.

    The runtime counterpart to PARCOACH's static collective analysis. Plain
    -O1 -g build (mpicxx), executed under /opt/must/bin/mustrun with
    --must:timeout so that real deadlocks terminate deterministically and
    are reported instead of hanging the stage. MPI samples only.

    Verified against a planted rank-conditional MPI_Recv deadlock
    (MUST_ERROR_DEADLOCK, reference `main@file:line`) and a clean MPI
    program (0 errors, 0 warnings, exit 0).
    """

    name = "must"
    execution_models = ("mpi",)

    MUSTRUN = "/opt/must/bin/mustrun"

    # process-group timeout wrapper (coreutils); mandatory, see preflight()
    SYSTEM_TIMEOUT = "/usr/bin/timeout"

    # Deadlock classes can depend on the rank count; two grid points bound
    # the cost (each deadlocked run costs up to --must:timeout seconds).
    LAUNCH_PARAMS = [{"num_procs": 2}, {"num_procs": 4}]

    MUST_TIMEOUT_SECONDS = 60

    def __init__(self, build_timeout: float = 180.0, run_timeout: float = 300.0):
        self.build_timeout = build_timeout
        self.run_timeout = run_timeout

    def is_available(self) -> bool:
        return Path(self.MUSTRUN).exists() or binary_available("mustrun")

    def preflight(self) -> "str | None":
        """Environment preflight (consumed by run_dynamic_analysis's gate):
        the /usr/bin/timeout process-group wrapper is MANDATORY — without
        it a hung MUST run is killed only at the mustrun process, orphaned
        MPI ranks keep the output pipes open, and the pipe drain blocks
        for hours (observed in the tool validation). No silent fallback to
        the unwrapped path."""
        if not Path(self.SYSTEM_TIMEOUT).exists():
            return (
                f"{self.SYSTEM_TIMEOUT} (coreutils) not found — MUST needs "
                "the system-timeout process-group wrapper to tear down "
                "hung MPI ranks; install coreutils in the container"
            )
        return None

    def _mustrun(self) -> str:
        return self.MUSTRUN if Path(self.MUSTRUN).exists() else "mustrun"

    def run(self, sample: AssembledSample, context: EvaluationContext) -> ToolResult:
        if sample.execution_model not in self.execution_models:
            return ToolResult(
                tool=self.name,
                ran=False,
                exit_code=None,
                duration_seconds=0.0,
                error=(
                    f"not applicable to execution model '{sample.execution_model}'"
                ),
            )

        config = get_build_config(sample.execution_model, context.primary_compiler)

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

        duration = 0.0
        findings: list[Finding] = []
        raw_segments: list[str] = []
        error: str | None = None

        with tempfile.TemporaryDirectory() as tmp:
            exec_path = str(Path(tmp) / "plain.out")

            argv = config.base_command(
                sources=[str(model_driver), str(benchmark_driver)],
                output_path=exec_path,
                include_dirs=context.include_dirs(sample),
                extra_flags=[f"-D{DRIVER_PROBLEM_SIZE_DEFINE}", *SANITIZER_BASE_FLAGS],
            )

            build = run_command(argv, timeout=self.build_timeout)
            duration += build.duration_seconds

            if build.returncode != 0 or build.timed_out:
                return ToolResult(
                    tool=self.name,
                    ran=True,
                    exit_code=build.returncode,
                    duration_seconds=duration,
                    error="build failed" + (" (timeout)" if build.timed_out else ""),
                    raw_stderr=build.stderr[:OUTPUT_CAP_PER_RUN],
                )

            last_exit = 0

            for index, params in enumerate(self.LAUNCH_PARAMS):
                run_dir = Path(tmp) / f"must_{index}"
                run_dir.mkdir()

                run_argv = [
                    # /usr/bin/timeout wrapper (ported back from the
                    # validation variant, 2026-08-08): a Python-level
                    # timeout kills only mustrun, while orphaned MPI ranks
                    # keep the output pipes open — observed in the tool
                    # validation to block the pipe drain for HOURS. The
                    # system timeout signals mustrun in its process group,
                    # mpirun tears the ranks down, the pipes close;
                    # -k hard-kills stragglers.
                    self.SYSTEM_TIMEOUT,
                    "--signal=TERM",
                    "-k",
                    "15",
                    str(int(self.run_timeout)),
                    self._mustrun(),
                    "--must:timeout",
                    str(self.MUST_TIMEOUT_SECONDS),
                    "-np",
                    str(params["num_procs"]),
                    exec_path,
                    str(SANITIZER_NITER),
                ]

                # the Python-side timeout must sit ABOVE the system timeout
                # (validation pattern: run_timeout + 60) — otherwise the
                # ineffective kill-only-mustrun path fires first again
                result = run_command(
                    run_argv, timeout=self.run_timeout + 60, cwd=str(run_dir)
                )
                duration += result.duration_seconds
                last_exit = result.returncode

                # with the wrapper, a hang surfaces as the wrapper's exit
                # code (124 = TERM after the limit, 137 = KILLed by -k),
                # not as a Python-level timed_out; both keep the exact
                # record semantics of a timed-out run
                timed_out = result.timed_out or result.returncode in (124, 137)

                report = run_dir / "MUST_Output.html"

                if report.exists():
                    findings += parse_must_html(
                        report.read_text(encoding="utf-8", errors="replace"),
                        sample.source_path.name,
                        self.name,
                    )
                else:
                    # No report means MUST itself failed — must not be
                    # mistaken for a clean sample.
                    error = f"MUST produced no report at params {params}"

                raw_segments.append(
                    f"--- run {params} exit={result.returncode}"
                    f"{' TIMEOUT' if timed_out else ''} ---\n"
                    + (result.stdout + "\n" + result.stderr)[:OUTPUT_CAP_PER_RUN]
                )

                if timed_out:
                    error = f"run timed out at params {params}"

        return ToolResult(
            tool=self.name,
            ran=True,
            exit_code=last_exit,
            duration_seconds=duration,
            findings=dedupe(findings),
            raw_stderr="\n".join(raw_segments),
            error=error,
        )


class HelgrindTool(MemcheckTool):
    """Helgrind race detection — disabled by default (see module comment:
    DRB-measured FP rate 0.89 on race-free OpenMP kernels). Findings carry
    low_confidence via config when enabled."""

    name = "helgrind"
    VALGRIND_TOOL = "helgrind"
    # hard capability: race detection concerns OpenMP samples only
    execution_models = ("omp",)
    LAUNCH_PARAMS = {"omp": [{"num_threads": 2}]}


class DrdTool(MemcheckTool):
    """DRD race detection — disabled by default (DRB-measured recall 0.20)."""

    name = "drd"
    VALGRIND_TOOL = "drd"
    execution_models = ("omp",)
    LAUNCH_PARAMS = {"omp": [{"num_threads": 2}]}


def register_dynamic_tools() -> None:
    register_tool(AsanUbsanTool())
    register_tool(TsanTool())
    register_tool(MemcheckTool())
    register_tool(MustTool())
    # registered but config-disabled by default (tool_config._DEFAULTS)
    register_tool(HelgrindTool())
    register_tool(DrdTool())
