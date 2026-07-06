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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    @property
    def blocking_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.blocking]

    def to_dict(self, include_raw: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "tool": self.tool,
            "ran": self.ran,
            "exit_code": self.exit_code,
            "duration_seconds": round(self.duration_seconds, 3),
            "num_findings": len(self.findings),
            "num_blocking": len(self.blocking_findings),
            "findings": [f.to_dict() for f in self.findings],
            "error": self.error,
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
