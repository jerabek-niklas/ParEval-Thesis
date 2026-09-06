"""Core framework for the evaluation stages (compilation, static analysis,
correctness tests).

Design:
  - Every analysis tool implements the Tool protocol: given an assembled
    sample, it returns a list of Finding plus raw output for auditing.
  - A registry maps tool names (as used in config under
    stages.static_analysis.tools) to Tool instances, so adding a tool is a
    one-line registration and a config edit.
  - iter_assembled_samples() yields the assembled sources produced by the
    assembly stage, joined with the per-sample metadata, so every stage
    consumes the exact same files (no re-cleaning, no divergence).

This module performs no analysis itself; it provides the plumbing that the
compilation and static-analysis runners build on.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterator, Protocol


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

SEVERITY_ORDER = {"error": 3, "warning": 2, "note": 1, "info": 0}


def severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.get(severity, 0)


# ---------------------------------------------------------------------------
# Findings and results
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single normalized finding from any tool.

    Normalizing every tool to this shape is what makes cross-tool analysis
    (redundancy, per-model finding rates) and uniform repair feedback
    possible.
    """

    tool: str
    check_id: str  # e.g. "bugprone-use-after-move", "-Wunused-variable"
    severity: str  # error | warning | note | info
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    blocking: bool = False
    # Set post-run from config (tool_config.mark_low_confidence) for tools/
    # finding families with measured low precision (~0.5 on the validation
    # suites). The repair loop renders these as verify-first hints; their
    # stop semantics are configured via stages.repair.low_confidence_stop_mode.
    low_confidence: bool = False
    # Tool-state wave: optional analyzer EVENT PATH (gcc -fanalyzer) attached
    # to this one finding - context for the repair feedback, never a finding
    # of its own and never counted. Empty for every other tool.
    path: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Tool analysis STATE (Static/Repair tool-state wave)
#
# A tool entry existing in a record never meant "analysis completed", and
# "no findings" never meant "clean": a tool can time out, crash, fail to
# capture, produce no report, give up on a region (LLOV "Region Not
# Analyzed", GCC -Wanalyzer-too-complex) or refuse the translation unit. The
# state makes that explicit and machine-readable, ADDITIVELY next to the
# existing fields. Three verdict categories follow from it:
#
#   DEFECT_FOUND            blocking finding(s) from a COMPLETED or PARTIAL run
#   CLEAN                   COMPLETED and no blocking finding
#   NO_TRUSTWORTHY_VERDICT  PARTIAL without defect, NOT_ANALYZED, TOOL_ERROR,
#                           TIMEOUT - an ANALYSIS GAP: not a model defect, and
#                           never "clean"
#   NOT_APPLICABLE          the tool's scope excludes this sample
#
# The state itself is NOT a finding: a gap is persisted in the record, the
# summary and the repair state, but it is never rendered to the repair LLM as
# a defect to fix.
# ---------------------------------------------------------------------------

TOOL_STATE_SCHEMA_VERSION = "tool_state.v1"

STATE_NOT_APPLICABLE = "NOT_APPLICABLE"
STATE_COMPLETED = "COMPLETED"
STATE_PARTIAL = "PARTIAL"
STATE_NOT_ANALYZED = "NOT_ANALYZED"
STATE_TOOL_ERROR = "TOOL_ERROR"
STATE_TIMEOUT = "TIMEOUT"

ANALYSIS_STATES = (
    STATE_NOT_APPLICABLE,
    STATE_COMPLETED,
    STATE_PARTIAL,
    STATE_NOT_ANALYZED,
    STATE_TOOL_ERROR,
    STATE_TIMEOUT,
)

# states in which the tool ran but produced no complete, trustworthy verdict
ANALYSIS_GAP_STATES = (
    STATE_PARTIAL,
    STATE_NOT_ANALYZED,
    STATE_TOOL_ERROR,
    STATE_TIMEOUT,
)

VERDICT_DEFECT_FOUND = "DEFECT_FOUND"
VERDICT_CLEAN = "CLEAN"
VERDICT_NO_TRUSTWORTHY = "NO_TRUSTWORTHY_VERDICT"
VERDICT_NOT_APPLICABLE = "NOT_APPLICABLE"


def tool_verdict(analysis_state: str, num_blocking: int) -> str:
    """The three-way verdict category of one tool entry."""
    if analysis_state == STATE_NOT_APPLICABLE:
        return VERDICT_NOT_APPLICABLE
    if num_blocking > 0 and analysis_state in (STATE_COMPLETED, STATE_PARTIAL):
        # a defect found by a partial analysis is still a defect
        return VERDICT_DEFECT_FOUND
    if analysis_state == STATE_COMPLETED:
        return VERDICT_CLEAN
    return VERDICT_NO_TRUSTWORTHY


def legacy_analysis_state(entry: dict[str, Any]) -> tuple[str, str | None]:
    """Derive (analysis_state, gap_reason) for a tool entry written BEFORE the
    tool-state schema (pilot_001, static_analysis.v2 without analysis_state).

    Conservative, read-only derivation from the persisted fields; used by
    every consumer through analysis_state_of() so historical records are
    never re-interpreted as clean. Heuristics mirror the tool rules of
    tools.py for the signals that were persisted at the time.
    """
    error = entry.get("error")
    error_text = str(error).lower() if error else ""

    if not entry.get("ran"):
        if error_text.startswith("not applicable"):
            return STATE_NOT_APPLICABLE, None
        return STATE_TOOL_ERROR, error or "tool did not run"

    if "timed out" in error_text or "timeout" in error_text:
        return STATE_TIMEOUT, error

    if error:
        return STATE_TOOL_ERROR, error

    tool = entry.get("tool")
    check_ids = [f.get("check_id") or "" for f in entry.get("findings") or []]

    raw = "%s\n%s" % (entry.get("raw_stdout") or "", entry.get("raw_stderr") or "")

    if tool == "llov":
        # The legacy parser dropped `path:line:col` locations and never
        # matched "Directive Not Analyzed"; the persisted raw output (never
        # capped for LLOV in pilot_001) is the trustworthy signal.
        race = any(c == "llov-data-race" for c in check_ids) or "Data Race detected" in raw
        not_analyzed = (
            any(c == "llov-region-not-analyzed" for c in check_ids)
            or "Region Not Analyzed" in raw
            or "Directive Not Analyzed" in raw
        )
        free = "Region is Data Race Free" in raw
        if race:
            if not_analyzed:
                return STATE_PARTIAL, "some OpenMP regions not analyzed (legacy record, re-derived from raw output)"
            return STATE_COMPLETED, None
        if not_analyzed:
            if free:
                return STATE_PARTIAL, "some OpenMP regions not analyzed (legacy record, re-derived from raw output)"
            return STATE_NOT_ANALYZED, "region(s)/directive(s) not analyzed by LLOV (legacy record, re-derived from raw output)"
        if free:
            return STATE_COMPLETED, None
        return STATE_NOT_ANALYZED, "LLOV emitted no region verdict at all (legacy record)"

    if tool == "gcc_analyzer":
        if "analysis bailed out early" in raw:
            return STATE_PARTIAL, "gcc -fanalyzer bailed out early (legacy record, re-derived from raw output; raw output is capped, so this is a lower bound)"
        if any(c.endswith("too-complex") for c in check_ids) or "-Wanalyzer-too-complex" in raw:
            return STATE_PARTIAL, "-Wanalyzer-too-complex: analyzer gave up on at least one path"
        return STATE_COMPLETED, None

    if tool == "clang_tidy":
        if any(c.startswith("clang-diagnostic-error") for c in check_ids):
            return STATE_TOOL_ERROR, "clang front-end could not parse the translation unit"
        return STATE_COMPLETED, None

    if tool == "cppcheck":
        raw = entry.get("raw_stderr")
        if isinstance(raw, str) and raw and "<results" not in raw:
            return STATE_TOOL_ERROR, "cppcheck produced no XML result block"
        return STATE_COMPLETED, None

    if tool == "infer" and "Aborting translation of method" in raw:
        # legacy record: the frontend dropped at least one method (every
        # OpenMP kernel in pilot_001); findings, if any, remain valid
        if any(f.get("blocking") for f in entry.get("findings") or []):
            return STATE_PARTIAL, "infer frontend aborted translation of at least one method (legacy record, re-derived from raw output)"
        return STATE_NOT_ANALYZED, "infer frontend aborted translation of at least one method - the kernel body was not analyzed (legacy record, re-derived from raw output)"

    if tool == "compiler" and entry.get("exit_code") == -1:
        # legacy records did not persist timed_out; -1 is both the timeout
        # and the missing-binary code (the synthetic finding text tells)
        messages = " ".join(str(f.get("message") or "") for f in entry.get("findings") or [])
        if "timeout" in messages.lower():
            return STATE_TIMEOUT, "compile timed out (legacy record)"
        return STATE_TOOL_ERROR, "compiler process did not run to a verdict (legacy record, exit -1)"

    return STATE_COMPLETED, None


# Reasons/errors that mean "the tool's OWN front-end rejected the
# translation unit" (as opposed to a crash, a timeout or a budget limit).
_TU_REJECTED_RE = re.compile(
    r"did not compile|emit-llvm failed|exited with|could not parse|"
    r"clang-diagnostic-error|tool-side diagnostic|syntax|front-end",
    re.IGNORECASE,
)


# reason prefix of the record-level subsumption (effective_tool_state)
SUBSUMED_REASON_PREFIX = "translation unit rejected by"


def compiler_build_failed(record: dict[str, Any]) -> bool | None:
    """True/False from the authoritative compiler entry of the record, None
    when the record carries no completed compiler verdict."""
    entry = (record.get("tools") or {}).get("compiler")
    if not entry or not entry.get("ran"):
        return None
    if analysis_state_of(entry) != STATE_COMPLETED:
        return None
    details = entry.get("analysis_details") or {}
    if "build_ok" in details:
        return details["build_ok"] is False
    if entry.get("exit_code") is not None:
        return entry.get("exit_code") != 0
    # legacy / minimal entries: the compiler tool only emits BLOCKING
    # findings for build errors, so a blocking finding means "did not build"
    return any(f.get("blocking") for f in entry.get("findings") or [])


def effective_tool_state(record: dict[str, Any], tool_name: str) -> tuple[str, str | None]:
    """Record-level analysis state of one tool: the entry's own state, EXCEPT
    that a front-end rejection (TOOL_ERROR / PARTIAL with a TU-rejected
    signal) of a translation unit the authoritative compiler also rejected
    is NOT_ANALYZED - the model defect is already carried by `compiler`
    (COMPLETED + blocking); the specialised tool simply had nothing to
    analyze. Measured in pilot_001: every clang-diagnostic-error /
    gcc_analyzer exit-1 / infer error sits in a compiler-exit-1 record."""
    entry = (record.get("tools") or {}).get(tool_name)
    if entry is None:
        return STATE_NOT_ANALYZED, "no entry"
    state = analysis_state_of(entry)
    reason = analysis_gap_reason_of(entry)
    if tool_name == "compiler" or state not in (STATE_TOOL_ERROR, STATE_PARTIAL):
        return state, reason
    details = entry.get("analysis_details") or {}
    rejected = details.get("tu_rejected")
    if rejected is None:
        rejected = bool(_TU_REJECTED_RE.search("%s %s" % (reason or "", entry.get("error") or "")))
    if rejected and compiler_build_failed(record) is True:
        return STATE_NOT_ANALYZED, (
            "%s %s; subsumed by the compiler's build failure (the model defect "
            "is carried by `compiler`)" % (SUBSUMED_REASON_PREFIX, tool_name)
        )
    return state, reason


def effective_tool_states(record: dict[str, Any]) -> dict[str, tuple[str, str | None]]:
    return {
        name: effective_tool_state(record, name)
        for name in (record.get("tools") or {})
    }


def is_subsumed_rejection(state: str, reason: str | None) -> bool:
    return state == STATE_NOT_ANALYZED and bool(reason) and reason.startswith(SUBSUMED_REASON_PREFIX)


def record_analysis_gap(record: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
    """The gap entry a tool contributes to the record's stop decision, or
    None: no entry (pending, handled upstream), a complete verdict, or a
    rejection subsumed by the compiler's own blocking verdict."""
    entry = (record.get("tools") or {}).get(tool_name)
    if entry is None:
        return None
    state, reason = effective_tool_state(record, tool_name)
    if state not in ANALYSIS_GAP_STATES or is_subsumed_rejection(state, reason):
        return None
    return {"tool": tool_name, "analysis_state": state, "reason": reason}


def analysis_state_of(entry: dict[str, Any]) -> str:
    """analysis_state of a persisted tool entry - explicit if present, else the
    documented legacy derivation. THE single accessor consumers must use."""
    state = entry.get("analysis_state")
    if state in ANALYSIS_STATES:
        return state
    return legacy_analysis_state(entry)[0]


def analysis_gap_reason_of(entry: dict[str, Any]) -> str | None:
    if entry.get("analysis_state") in ANALYSIS_STATES:
        return entry.get("analysis_gap_reason")
    return legacy_analysis_state(entry)[1]


def entry_is_clean(entry: dict[str, Any]) -> bool:
    """CLEAN requires a COMPLETED analysis AND no blocking finding."""
    return (
        analysis_state_of(entry) == STATE_COMPLETED
        and int(entry.get("num_blocking", 0) or 0) == 0
    )


def entry_has_analysis_gap(entry: dict[str, Any]) -> bool:
    return analysis_state_of(entry) in ANALYSIS_GAP_STATES


@dataclass
class ToolResult:
    """Result of running one tool on one sample."""

    tool: str
    ran: bool
    exit_code: int | None
    duration_seconds: float
    findings: list[Finding] = field(default_factory=list)
    raw_stdout: str = ""
    raw_stderr: str = ""
    error: str | None = None  # set when the tool itself failed to run
    # Tool-state wave: explicit analysis state (see ANALYSIS_STATES). Tools set
    # it from their own exit-code / output semantics; a tool that leaves it
    # None gets the conservative legacy derivation at serialization time.
    analysis_state: str | None = None
    analysis_gap_reason: str | None = None
    # tool-specific, machine-readable detail (e.g. LLOV region counts, the
    # number of -Wanalyzer-too-complex give-ups, cppcheck XML presence)
    analysis_details: dict[str, Any] = field(default_factory=dict)

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    def resolved_state(self) -> tuple[str, str | None]:
        if self.analysis_state in ANALYSIS_STATES:
            return self.analysis_state, self.analysis_gap_reason
        return legacy_analysis_state({
            "tool": self.tool,
            "ran": self.ran,
            "exit_code": self.exit_code,
            "error": self.error,
            "findings": [f.to_dict() for f in self.findings],
            "raw_stderr": self.raw_stderr,
        })

    def to_dict(self, include_raw: bool = True) -> dict[str, Any]:
        state, gap_reason = self.resolved_state()
        num_blocking = len(self.blocking_findings)

        data: dict[str, Any] = {
            "tool": self.tool,
            "ran": self.ran,
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration_seconds, 3),
            "num_findings": len(self.findings),
            "num_blocking": num_blocking,
            "findings": [f.to_dict() for f in self.findings],
            "error": self.error,
            # tool-state wave (additive)
            "tool_state_schema": TOOL_STATE_SCHEMA_VERSION,
            "analysis_state": state,
            "analysis_complete": state == STATE_COMPLETED,
            "analysis_gap_reason": gap_reason,
            "tool_verdict": tool_verdict(state, num_blocking),
            "analysis_details": dict(self.analysis_details),
        }

        if include_raw:
            # Raw output is capped to keep the JSONL readable; the full
            # picture is reconstructable by re-running the tool on the
            # persisted source.
            data["raw_stdout"] = self.raw_stdout[:8000]
            data["raw_stderr"] = self.raw_stderr[:8000]

        return data


@dataclass
class AssembledSample:
    """An assembled sample joined with its assembly metadata."""

    sample_id: str
    model_id: str
    run_id: str
    execution_model: str
    problem_type: str
    name: str
    source_path: Path
    benchmark_dir: Path
    model_driver_file: str
    assembly_entry: dict[str, Any]

    @property
    def source_text(self) -> str:
        return self.source_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tool protocol and registry
# ---------------------------------------------------------------------------


class Tool(Protocol):
    name: str

    def is_available(self) -> bool:
        """Whether the tool binary is present in the environment."""
        ...

    def run(self, sample: AssembledSample, context: "EvaluationContext") -> ToolResult:
        ...


_TOOL_REGISTRY: dict[str, "Tool"] = {}


def register_tool(tool: "Tool") -> None:
    _TOOL_REGISTRY[tool.name] = tool


def get_tool(name: str) -> "Tool":
    if name not in _TOOL_REGISTRY:
        available = ", ".join(sorted(_TOOL_REGISTRY)) or "<none>"
        raise KeyError(f"Tool '{name}' is not registered. Registered: {available}")

    return _TOOL_REGISTRY[name]


def registered_tools() -> list[str]:
    return sorted(_TOOL_REGISTRY)


# ---------------------------------------------------------------------------
# Evaluation context
# ---------------------------------------------------------------------------


@dataclass
class EvaluationContext:
    """Shared paths and settings handed to every tool."""

    repo_root: Path
    drivers_cpp_dir: Path  # repo_root / "drivers" / "cpp"
    primary_compiler: str
    config: dict[str, Any]

    def include_dirs(self, sample: AssembledSample) -> list[str]:
        """Include dirs matching the upstream compile (-Icpp -Icpp/models)
        plus the directory holding the assembled generated-code.hpp."""
        return [
            str(self.drivers_cpp_dir),
            str(self.drivers_cpp_dir / "models"),
            str(sample.source_path.parent),
        ]


# ---------------------------------------------------------------------------
# Command runner
# ---------------------------------------------------------------------------


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_seconds: float


def run_command(
    argv: list[str],
    timeout: float,
    cwd: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> CommandResult:
    """Run a command without a shell; never raises on non-zero exit."""
    import os

    env = os.environ.copy()

    if extra_env:
        env.update(extra_env)

    started = time.time()

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            timed_out=False,
            duration_seconds=time.time() - started,
        )
    except subprocess.TimeoutExpired as expired:
        return CommandResult(
            returncode=-1,
            stdout=(expired.stdout or b"").decode(errors="replace")
            if isinstance(expired.stdout, bytes)
            else (expired.stdout or ""),
            stderr=(expired.stderr or b"").decode(errors="replace")
            if isinstance(expired.stderr, bytes)
            else (expired.stderr or ""),
            timed_out=True,
            duration_seconds=time.time() - started,
        )
    except FileNotFoundError as error:
        return CommandResult(
            returncode=-1,
            stdout="",
            stderr=f"command not found: {error}",
            timed_out=False,
            duration_seconds=time.time() - started,
        )


def binary_available(name: str) -> bool:
    import shutil

    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# Sample iteration
# ---------------------------------------------------------------------------


def iter_assembled_samples(
    repo_root: Path,
    intermediate_dir: Path,
    run_id: str,
    model_id: str,
) -> Iterator[AssembledSample]:
    """Yield assembled samples for one model from its assembly.jsonl.

    Only entries that were successfully assembled are yielded; skipped
    generations have no source file.
    """
    assembly_path = intermediate_dir / run_id / model_id / "assembly.jsonl"

    if not assembly_path.exists():
        return

    with assembly_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            entry = json.loads(line)

            if not entry.get("assembled"):
                continue

            drivers = entry.get("drivers", {})
            sample_id = entry["sample_id"]

            # sample_id layout:
            #   <model_id>__<problem_type>__<name>__<execution_model>__sample_<i>
            parts = sample_id.split("__")
            execution_model = parts[-2] if len(parts) >= 2 else "serial"
            name = parts[-3] if len(parts) >= 3 else "unknown"
            problem_type = parts[-4] if len(parts) >= 4 else "unknown"

            # Paths in assembly.jsonl may have been written on a different OS
            # (e.g. generated on Windows, then analyzed in the Linux
            # container). Backslashes are not separators on POSIX, so
            # normalize to forward slashes before building the Path; this
            # resolves correctly on both platforms.
            source_path = Path(entry["source_path"].replace("\\", "/"))

            if not source_path.is_absolute():
                source_path = repo_root / source_path

            benchmark_dir_raw = drivers.get("benchmark_dir", "").replace("\\", "/")

            yield AssembledSample(
                sample_id=sample_id,
                model_id=model_id,
                run_id=run_id,
                execution_model=execution_model,
                problem_type=problem_type,
                name=name,
                source_path=source_path,
                benchmark_dir=repo_root / benchmark_dir_raw,
                model_driver_file=drivers.get("model_driver", ""),
                assembly_entry=entry,
            )
