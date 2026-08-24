"""Feedback and history formatter for the repair loop.

Every format decision here derives from thesis/docs/repair-loop-design.md
(section 4, "Repair request format"): stateless self-contained requests,
cleaned code as the line-number reference, driver-located compile errors
translated for the model, compressed history with truncated messages, and
NO old mismatch numbers in any history mode. CORRECTED RATIONALE
(2026-08-06): fillRand draws from UNSEEDED rand() (as if srand(1)), so the
validation inputs are IDENTICAL across runs and iterations — old
expected/got values are not "other random inputs". The rule stays because
the draw ORDER can shift between call sites within a process and, more
importantly, because old numbers describe the PREVIOUS code's output —
after a repair the current numbers are the only ones that apply.

This module is pure string building over existing stage records
(static_analysis.jsonl, dynamic_analysis.jsonl, correctness.jsonl). It
performs no API calls, holds no state, and changes no schemas; the loop
orchestrator (separate, later) supplies the data.

All behavior is config-driven (stages.repair in config.yaml); the module
defaults below mirror the config defaults so that a missing config entry
means design-default behavior.

Python 3.8 compatible.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation.tool_config import resolve_tool_settings  # noqa: E402
from thesis.evaluation.run_correctness import BASELINE_INCOMPATIBLE  # noqa: E402

# The assembled model file name is a scaffold invariant (assembly stage);
# findings in any other file are driver/TU context.
MODEL_FILE = "generated-code.hpp"

KNOWN_SOURCES = (
    "compiler_errors",
    "static_findings",
    "correctness_verdicts",
    "dynamic_findings",
)

HISTORY_MODES = ("compressed", "full")

# stage -> which sources draw from it (for enabled-tool filtering)
_SOURCE_STAGE = {
    "compiler_errors": "static_analysis",
    "static_findings": "static_analysis",
    "dynamic_findings": "dynamic_analysis",
}

DEFAULT_TEMPLATES = {
    "task_header": "## Original task",
    "history_iteration_header": "## Iteration {n} (previous attempt)",
    "current_header": "## Current version (fix this)",
    "feedback_header": "## Analysis feedback on the current version",
    "non_blocking_header": (
        "Non-blocking quality hints (optional improvements, not errors):"
    ),
    "instruction": (
        "Output the complete corrected function. Line numbers in the "
        "feedback refer to the current version shown above."
    ),
    "driver_error": (
        "error at the call site in the test driver (your function "
        "name/signature likely does not match the expected interface): "
        "{message}"
    ),
}

DEFAULT_FEEDBACK = {
    "low_confidence_prefix": (
        "Low-confidence hint (tool precision ~0.5 on validation suites) — "
        "verify at the given location before changing code:"
    ),
    "include_non_blocking": False,
    "history_message_max_chars": 80,
    "mismatch_report_max_indices": 3,
}

# design defaults (repair-loop-design.md §2): compiler_errors is base
# feedback in every variant
DEFAULT_STRATEGY_SOURCES = {
    "static_feedback": ["compiler_errors", "static_findings"],
    "test_feedback": ["compiler_errors", "correctness_verdicts", "dynamic_findings"],
    "combined_feedback": [
        "compiler_errors",
        "static_findings",
        "correctness_verdicts",
        "dynamic_findings",
    ],
}


@dataclass
class IterationRecord:
    """One past iteration as the orchestrator will hand it over."""

    iteration: int
    cleaned_code: str
    static_record: Optional[Dict[str, Any]] = None
    dynamic_record: Optional[Dict[str, Any]] = None
    correctness_record: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Config access (defaults == design defaults)
# ---------------------------------------------------------------------------


def _repair_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return (config.get("stages") or {}).get("repair") or {}


def feedback_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    """stages.repair.feedback merged over module defaults."""
    raw = _repair_config(config).get("feedback") or {}

    merged = dict(DEFAULT_FEEDBACK)
    for key, value in raw.items():
        if key != "templates" and value is not None:
            merged[key] = value

    templates = dict(DEFAULT_TEMPLATES)
    for key, value in (raw.get("templates") or {}).items():
        if value is not None:
            templates[key] = value

    # YAML folded scalars ('>') carry a trailing newline
    merged["low_confidence_prefix"] = str(merged["low_confidence_prefix"]).strip()
    merged["templates"] = {k: str(v).strip() for k, v in templates.items()}

    return merged


def history_mode(config: Dict[str, Any]) -> str:
    """compressed | full — DEFAULT 'full' since 2026-07-31.

    The design originally defaulted to 'compressed'. For the main run the
    decision was reversed: the loop is the object of study, so the model
    must see the full finding detail of every past iteration, otherwise a
    "the model kept reintroducing X" analysis cannot distinguish "was not
    told precisely enough" from "did not fix it". The cost is measurable
    up front — `run_repair.py --dry-run` renders each wave in BOTH modes
    and prints the character/token ratio. Documented in
    thesis/docs/repair-loop-design.md §4.
    """
    return _repair_config(config).get("history_mode", "full")


def strategy_sources(config: Dict[str, Any], strategy: str) -> List[str]:
    """Feedback sources of a loop variant (config or design default)."""
    strategies = _repair_config(config).get("strategies")

    if isinstance(strategies, dict) and strategy in strategies:
        entry = strategies[strategy] or {}
        sources = entry.get("sources")
        if sources:
            return list(sources)

    if strategy in DEFAULT_STRATEGY_SOURCES:
        return list(DEFAULT_STRATEGY_SOURCES[strategy])

    raise KeyError(
        "Unknown repair strategy '%s' (known: %s)"
        % (strategy, ", ".join(sorted(DEFAULT_STRATEGY_SOURCES)))
    )


def _enabled_tools(config: Dict[str, Any], stage_name: str) -> "set":
    """Enabled tool names of a stage — reuses tool_config (single source
    of tool truth; no second tool list)."""
    settings = resolve_tool_settings(config, stage_name)
    return {name for name, s in settings.items() if s.enabled}


# ---------------------------------------------------------------------------
# Finding collection
# ---------------------------------------------------------------------------


def _record_findings(
    record: Optional[Dict[str, Any]], allowed_tools: "set"
) -> Iterable[Dict[str, Any]]:
    if not record:
        return

    for tool_name, tool_result in (record.get("tools") or {}).items():
        if tool_name not in allowed_tools:
            continue

        for finding in tool_result.get("findings") or []:
            yield finding


def collect_findings(
    config: Dict[str, Any],
    sources: List[str],
    static_record: Optional[Dict[str, Any]],
    dynamic_record: Optional[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Split findings into rendering groups per the design format:

    - compiler_errors: blocking compiler findings (model-file and
      driver-located; the latter get the translation template)
    - blocking: blocking, not low_confidence, from static/dynamic sources
    - low_confidence: low_confidence findings of included sources
      (rendered after the normal blocking findings)
    - non_blocking: everything else (rendered only when
      include_non_blocking is true; never part of any stop criterion)

    Only tools enabled in stages.<stage>.tools contribute (tool_config is
    reused — no second tool list).
    """
    groups: Dict[str, List[Dict[str, Any]]] = {
        "compiler_errors": [],
        "blocking": [],
        "low_confidence": [],
        "non_blocking": [],
    }

    static_tools = _enabled_tools(config, "static_analysis")
    dynamic_tools = _enabled_tools(config, "dynamic_analysis")

    def bucket(finding: Dict[str, Any]) -> None:
        if finding.get("low_confidence"):
            groups["low_confidence"].append(finding)
        elif finding.get("blocking"):
            groups["blocking"].append(finding)
        else:
            groups["non_blocking"].append(finding)

    if "compiler_errors" in sources and static_record:
        for finding in _record_findings(static_record, {"compiler"}):
            if finding.get("blocking"):
                groups["compiler_errors"].append(finding)
            # compiler warnings are static analysis (design §2) and are
            # handled by the static_findings source below

    if "static_findings" in sources and static_record:
        for finding in _record_findings(static_record, static_tools - {"compiler"}):
            bucket(finding)
        # compiler warnings (non-blocking compiler findings) count as
        # static analysis per the design's compiler rule
        for finding in _record_findings(static_record, {"compiler"} & static_tools):
            if not finding.get("blocking"):
                bucket(finding)

    if "dynamic_findings" in sources and dynamic_record:
        for finding in _record_findings(dynamic_record, dynamic_tools):
            bucket(finding)

    return groups


# ---------------------------------------------------------------------------
# Rendering: single findings
# ---------------------------------------------------------------------------


def _is_driver_located(finding: Dict[str, Any]) -> bool:
    file_name = finding.get("file")
    return bool(file_name) and file_name != MODEL_FILE


def render_finding(finding: Dict[str, Any], settings: Dict[str, Any]) -> str:
    """`line {line}: [{check_id}] {message}`; driver-located compile errors
    are translated (a raw cpu.cc reference would mislead the model)."""
    if finding.get("tool") == "compiler" and _is_driver_located(finding):
        return settings["templates"]["driver_error"].format(
            message=finding.get("message", "")
        )

    line = finding.get("line")
    line_text = str(line) if line is not None else "?"

    return "line %s: [%s] %s" % (
        line_text,
        finding.get("check_id", "unknown"),
        finding.get("message", ""),
    )


def _render_compressed_finding(finding: Dict[str, Any], max_chars: int) -> str:
    line = finding.get("line")
    line_text = str(line) if line is not None else "?"
    message = (finding.get("message") or "")[:max_chars]

    return "%s:%s: %s" % (line_text, finding.get("check_id", "unknown"), message)


# ---------------------------------------------------------------------------
# Rendering: correctness verdicts
# ---------------------------------------------------------------------------


def _grid_point_label(execution_model: str, params: Dict[str, Any]) -> str:
    if "num_threads" in (params or {}):
        return "%s threads" % params["num_threads"]
    if "num_procs" in (params or {}):
        return "%s ranks" % params["num_procs"]
    return execution_model


def render_correctness(
    record: Optional[Dict[str, Any]],
    settings: Dict[str, Any],
    with_mismatch: bool,
) -> List[str]:
    """Per-grid-point verdicts; FAIL points get the bounded mismatch report
    when the driver-patch-provided fields exist, otherwise plain verdicts.

    Field contract (run_correctness.py, parse_mismatch_output):
        run["mismatches"] = [{"index": int?, "rel": float?, "expected": x, "got": y,
                              "input": v?}, ...]
        run["mismatch_total"] = <int>   # ALL differing indices, not just shown
    ("mismatch" is accepted as a legacy alias.) When total > shown, the
    difference is rendered explicitly — the model must be able to tell
    3-of-3 outliers from 3-of-47.
    """
    if not record:
        return []

    # Execution contract A1b: a non-finite REFERENCE is an oracle problem.
    # The model gets NO correctness feedback for it — there is nothing for it
    # to repair, and telling it "your tests failed" would be false.
    if record.get("verdict") == BASELINE_INCOMPATIBLE:
        return []

    lines = ["ParEval tests: %s" % record.get("verdict", "unknown")]

    for run in record.get("runs") or []:
        label = _grid_point_label(record.get("execution_model", ""), run.get("params"))
        lines.append("  %s: %s" % (label, run.get("verdict", "unknown")))

        if not with_mismatch or run.get("verdict") == "pass":
            continue

        max_indices = int(settings["mismatch_report_max_indices"])
        entries = (run.get("mismatches") or run.get("mismatch") or [])[:max_indices]

        for entry in entries:
            # values pass through VERBATIM — no re-formatting/rounding in
            # the renderer; the driver already prints round-trip precision,
            # and any rounding here would reintroduce the
            # "expected == got" self-contradiction the precision fix removed
            if entry.get("index") is not None:
                detail = "    index %s: expected %s, got %s" % (
                    entry.get("index"),
                    entry.get("expected"),
                    entry.get("got"),
                )
            else:  # scalar comparison: no index
                detail = "    expected %s, got %s" % (
                    entry.get("expected"),
                    entry.get("got"),
                )
            if entry.get("rel") is not None:
                # rounding-vs-logic signal for the model (rel ~1e-9 =
                # rounding hunt, rel large/nan = logic bug)
                detail += " (rel %.2e)" % float(entry["rel"])
            if "input" in entry:
                detail += " (input %s)" % entry["input"]
            lines.append(detail)

        total = run.get("mismatch_total")
        if entries and total is not None and total > len(entries):
            lines.append(
                "    ... and %d more differing indices (%d total)"
                % (total - len(entries), total)
            )

    return lines


def summarize_correctness(record: Optional[Dict[str, Any]]) -> Optional[str]:
    """One-sentence verdict for compressed history, e.g.
    'ParEval tests: FAIL (omp at 4/8 threads)'. Never mismatch numbers —
    a compression rule, not an input-identity one (inputs ARE identical
    across iterations, unseeded deterministic rand()): old expected/got
    describe the previous code's output (design §4, "Corrected
    rationale")."""
    if not record:
        return None

    verdict = record.get("verdict", "unknown")

    if verdict == "pass":
        return "ParEval tests: PASS"

    # contract A1b: not a model failure, so it must not enter the compressed
    # history as one either
    if verdict == BASELINE_INCOMPATIBLE:
        return None

    execution_model = record.get("execution_model", "")
    failing = []
    unit = execution_model

    for run in record.get("runs") or []:
        if run.get("verdict") == "pass":
            continue
        params = run.get("params") or {}
        if "num_threads" in params:
            failing.append(str(params["num_threads"]))
            unit = "threads"
        elif "num_procs" in params:
            failing.append(str(params["num_procs"]))
            unit = "ranks"

    if failing:
        return "ParEval tests: FAIL (%s at %s %s)" % (
            execution_model,
            "/".join(failing),
            unit,
        )

    return "ParEval tests: %s" % verdict.upper()


# ---------------------------------------------------------------------------
# Rendering: feedback blocks
# ---------------------------------------------------------------------------


def render_current_feedback(
    config: Dict[str, Any],
    sources: List[str],
    static_record: Optional[Dict[str, Any]] = None,
    dynamic_record: Optional[Dict[str, Any]] = None,
    correctness_record: Optional[Dict[str, Any]] = None,
) -> str:
    """Full-detail feedback for the current iteration (design §4)."""
    settings = feedback_settings(config)
    groups = collect_findings(config, sources, static_record, dynamic_record)

    lines: List[str] = []

    for finding in groups["compiler_errors"] + groups["blocking"]:
        lines.append(render_finding(finding, settings))

    for finding in groups["low_confidence"]:
        lines.append(
            "%s %s" % (settings["low_confidence_prefix"], render_finding(finding, settings))
        )

    if "correctness_verdicts" in sources:
        lines.extend(render_correctness(correctness_record, settings, with_mismatch=True))

    if settings["include_non_blocking"] and groups["non_blocking"]:
        lines.append("")
        lines.append(settings["templates"]["non_blocking_header"])
        for finding in groups["non_blocking"]:
            lines.append(render_finding(finding, settings))

    return "\n".join(lines).strip()


def render_history_iteration(
    config: Dict[str, Any],
    sources: List[str],
    record: IterationRecord,
) -> str:
    """Findings/verdicts of ONE past iteration.

    compressed (default): truncated `line:check_id: message` lines + a
    one-sentence test verdict; non-blocking findings always excluded
    (compression means: only what counts).
    full: full-detail rendering like current feedback.
    NEITHER mode renders old mismatch numbers — for COMPRESSION, not
    input identity: fillRand draws from unseeded rand() (as if srand(1)),
    so inputs are identical across iterations; but old expected/got
    describe the PREVIOUS code's output, and after a repair only the
    current numbers apply (design §4, "Corrected rationale").
    """
    mode = history_mode(config)
    settings = feedback_settings(config)

    if mode == "full":
        # full detail, but mismatch numbers OFF (verdicts only)
        groups = collect_findings(config, sources, record.static_record, record.dynamic_record)

        lines = []
        for finding in groups["compiler_errors"] + groups["blocking"]:
            lines.append(render_finding(finding, settings))
        for finding in groups["low_confidence"]:
            lines.append(
                "%s %s"
                % (settings["low_confidence_prefix"], render_finding(finding, settings))
            )
        if "correctness_verdicts" in sources:
            lines.extend(
                render_correctness(record.correctness_record, settings, with_mismatch=False)
            )
        if settings["include_non_blocking"] and groups["non_blocking"]:
            lines.append("")
            lines.append(settings["templates"]["non_blocking_header"])
            for finding in groups["non_blocking"]:
                lines.append(render_finding(finding, settings))

        return "\n".join(lines).strip()

    # compressed
    max_chars = int(settings["history_message_max_chars"])
    groups = collect_findings(config, sources, record.static_record, record.dynamic_record)

    lines = []
    for finding in (
        groups["compiler_errors"] + groups["blocking"] + groups["low_confidence"]
    ):
        lines.append(_render_compressed_finding(finding, max_chars))

    if "correctness_verdicts" in sources:
        sentence = summarize_correctness(record.correctness_record)
        if sentence:
            lines.append(sentence)

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Request builder
# ---------------------------------------------------------------------------


def build_repair_request(
    task_prompt: str,
    history: List[IterationRecord],
    current_code: str,
    current_records: Dict[str, Optional[Dict[str, Any]]],
    strategy: str,
    config: Dict[str, Any],
) -> str:
    """Assemble one stateless repair request (design §4 block order):

        task header + original prompt
        per past iteration: iteration header + cleaned code + findings
        current header + current cleaned code
        feedback header + current full-detail feedback
        instruction

    Line numbers refer to the current code included in the same request;
    the (configurable) instruction template states this. Pure string
    building — no API calls, no state.

    current_records keys: "static", "dynamic", "correctness" (each the
    stage JSONL record of the current iteration, or None).
    """
    settings = feedback_settings(config)
    templates = settings["templates"]
    sources = strategy_sources(config, strategy)

    blocks: List[str] = [templates["task_header"], task_prompt.strip()]

    for past in history:
        blocks.append(templates["history_iteration_header"].format(n=past.iteration))
        blocks.append(past.cleaned_code.strip())

        rendered = render_history_iteration(config, sources, past)
        if rendered:
            blocks.append(rendered)

    blocks.append(templates["current_header"])
    blocks.append(current_code.strip())

    blocks.append(templates["feedback_header"])
    feedback = render_current_feedback(
        config,
        sources,
        static_record=current_records.get("static"),
        dynamic_record=current_records.get("dynamic"),
        correctness_record=current_records.get("correctness"),
    )
    blocks.append(feedback if feedback else "(no findings)")

    blocks.append(templates["instruction"])

    return "\n\n".join(block for block in blocks if block)
