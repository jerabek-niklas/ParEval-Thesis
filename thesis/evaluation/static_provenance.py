#!/usr/bin/env python3
"""Static-analysis PROVENANCE and MERGE SAFETY (tool-state wave).

`static_analysis.jsonl` is merged per sample_id across several invocations
(main toolchain image -> PARCOACH image -> LLOV image), and `sample_id` is a
NAME, not a content address. Without a pinned source hash the record could
silently mix tool entries produced from two different generated-code.hpp
versions; without a per-tool execution condition the same tool could be
merged under two different conditions (settings, implementation, binary).

This module provides, content-addressed and independent of git HEAD:

  sample_source_sha256(sample)     the candidate source bytes
  tool_execution_condition(...)    per (tool, sample): implementation hash of
                                   the tool (class + helpers + tables), the
                                   shared framework/build/config modules,
                                   the effective settings and options, the
                                   build configuration, the TU strategy, the
                                   measured runtime tool identity, and the
                                   sample source hash
  tool_execution_fingerprint_sha256(condition)
  check_merge(...)                 the fail-closed merge rules

  static_analysis_condition(config, ...)  run-level static condition
  repair_condition(config)                run-level repair condition
  both with a content-addressed sha256, persisted by the runners into the
  run manifest / summaries.

MERGE RULES (fail-closed):
  * same sample_id + different sample_source_sha256      -> HARD FAIL
  * same tool + different tool execution fingerprint     -> HARD FAIL unless
    the invocation explicitly replaces that tool's entries
  * same tool + same fingerprint                         -> idempotent: the
    existing entry is kept (a persisted TIMEOUT/TOOL_ERROR is TERMINAL for
    resume - it is not re-run on every invocation; an explicit --rerun-gaps
    re-runs it)
  * different tool from its own (correct) container      -> merge allowed:
    fingerprints are PER TOOL, so PARCOACH and LLOV never have to share a
    toolchain with the main image

Python 3.8 compatible (runs inside the LLOV container).
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

STATIC_CONDITION_VERSION = "static_condition.v1"
REPAIR_CONDITION_VERSION = "repair_condition.v1"

# modules every static tool depends on (hashed as ONE shared component)
SHARED_MODULES = (
    "thesis/evaluation/framework.py",
    "thesis/evaluation/build_config.py",
    "thesis/evaluation/tool_config.py",
)

TU_STRATEGY = {
    "compiler": "full: model driver + benchmark cpu.cc + generated-code.hpp",
    "gcc_analyzer": "reduced: cpu.cc system-include preamble + <vector> + utilities.hpp + generated-code.hpp",
    "clang_tidy": "full: benchmark cpu.cc (includes generated-code.hpp), header-filter generated-code.hpp",
    "cppcheck": "full: benchmark cpu.cc (includes generated-code.hpp)",
    "infer": "full: benchmark cpu.cc with --headers",
    # tool-state wave: preamble added (pilot_001 ran WITHOUT it - a method
    # change for these two tools, see the readiness report)
    "parcoach": "reduced: cpu.cc system-include preamble + <vector> + utilities.hpp + generated-code.hpp, -emit-llvm, external declares stubbed",
    "llov": "reduced: cpu.cc system-include preamble + <vector> + utilities.hpp + generated-code.hpp, LLOV plugin compile",
}


def drivers_tree_sha256(root: Optional[Path] = None) -> str:
    """Content hash of drivers/cpp (*.cc, *.cpp, *.h, *.hpp, relative path +
    bytes, sorted): the shared part of every static translation unit."""
    base = root or (REPO_ROOT / "drivers" / "cpp")
    digest = hashlib.sha256()
    for path in sorted(base.rglob("*")):
        if path.suffix not in (".cc", ".cpp", ".h", ".hpp") or not path.is_file():
            continue
        digest.update(path.relative_to(base).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> Optional[str]:
    return sha256_bytes(path.read_bytes()) if path.is_file() else None


def canonical_sha256(obj: Any) -> str:
    return sha256_bytes(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                   default=str).encode("utf-8"))


def shared_modules_sha256() -> str:
    parts = []
    for relative in SHARED_MODULES:
        parts.append("%s:%s" % (relative, sha256_path(REPO_ROOT / relative)))
    return sha256_bytes("\n".join(parts).encode("utf-8"))


def sample_source_sha256(source_path: Path) -> Optional[str]:
    return sha256_path(Path(source_path))


# ---------------------------------------------------------------------------
# per-tool execution condition
# ---------------------------------------------------------------------------

def tool_execution_condition(
    tool: Any,
    settings: Any,
    execution_model: str,
    primary_compiler: str,
    source_sha256: Optional[str],
) -> "Dict[str, Any]":
    """Everything that can change one tool's result on one sample."""
    from thesis.evaluation import tools as tools_module
    from thesis.evaluation.build_config import get_build_config
    from thesis.evaluation.framework import TOOL_STATE_SCHEMA_VERSION

    name = tool.name
    build = get_build_config(execution_model, primary_compiler)
    condition = OrderedDict()
    condition["tool"] = name
    condition["tool_state_schema"] = TOOL_STATE_SCHEMA_VERSION
    condition["implementation_sha256"] = tools_module.tool_implementation_sha256(name)
    condition["shared_modules_sha256"] = shared_modules_sha256()
    condition["settings"] = OrderedDict([
        ("execution_models", list(getattr(settings, "execution_models", ()))),
        ("low_precision_warning", bool(getattr(settings, "low_precision_warning", False))),
        ("low_precision_families", list(getattr(settings, "low_precision_families", ()))),
    ])
    condition["options"] = OrderedDict(sorted(tools_module.tool_option_snapshot(tool).items()))
    condition["build"] = OrderedDict([
        ("execution_model", execution_model),
        ("primary_compiler", primary_compiler),
        ("macro", build.macro),
        ("cxxflags", list(build.cxxflags)),
    ])
    condition["tu_strategy"] = TU_STRATEGY.get(name, "unknown")
    condition["tool_identity"] = tools_module.tool_runtime_identity(name)
    condition["sample_source_sha256"] = source_sha256
    return condition


def tool_execution_fingerprint_sha256(condition: "Dict[str, Any]") -> str:
    return canonical_sha256(condition)


class StaticMergeConflict(RuntimeError):
    """Fail-closed merge refusal (source drift or tool-condition drift)."""


def check_merge(
    existing_record: "Optional[Dict[str, Any]]",
    sample_id: str,
    current_source_sha256: Optional[str],
) -> None:
    """Refuse to merge into a record whose candidate source changed."""
    if not existing_record:
        return

    recorded = existing_record.get("sample_source_sha256")

    if recorded is None:
        # legacy record without a pinned source: cannot be verified; the
        # caller pins the current hash and logs the limitation
        return

    if current_source_sha256 != recorded:
        raise StaticMergeConflict(
            "sample %s: generated-code.hpp changed since the existing static "
            "record was written (recorded sha256 %s..., current %s...). Tool "
            "entries from two candidate versions must never be mixed under one "
            "record: use a fresh run_id or remove the stale record explicitly."
            % (sample_id, str(recorded)[:12], str(current_source_sha256)[:12])
        )


def check_tool_entry_merge(
    existing_entry: "Optional[Dict[str, Any]]",
    tool_name: str,
    sample_id: str,
    current_fingerprint: str,
    replace_allowed: bool,
) -> str:
    """Decide what to do with an existing entry of the same tool.

    Returns "run" (no entry, or replacement explicitly allowed) or "keep"
    (identical condition: idempotent). Raises StaticMergeConflict when the
    condition differs and replacement was not explicitly requested.
    """
    if not existing_entry:
        return "run"

    recorded = existing_entry.get("tool_execution_fingerprint_sha256")

    if recorded is None:
        # legacy entry (pre tool-state wave): condition unknown. Replacing it
        # is the only way to obtain provenance; refuse silently mixing.
        if replace_allowed:
            return "run"
        raise StaticMergeConflict(
            "sample %s, tool %s: the existing entry carries no execution "
            "fingerprint (legacy record) - re-running would mix an unprovenanced "
            "entry with a fingerprinted one. Pass --replace-tool-entries %s to "
            "replace it explicitly, or use a fresh run_id." % (sample_id, tool_name, tool_name)
        )

    if recorded == current_fingerprint:
        return "keep"

    if replace_allowed:
        return "run"

    raise StaticMergeConflict(
        "sample %s, tool %s: recorded under execution fingerprint %s... but this "
        "invocation runs the tool under %s... (implementation, settings, build "
        "config, TU strategy, tool binary or candidate source differ). Refusing to "
        "mix conditions: use a fresh run_id or pass --replace-tool-entries %s."
        % (sample_id, tool_name, recorded[:12], current_fingerprint[:12], tool_name)
    )


# ---------------------------------------------------------------------------
# run-level conditions (static + repair)
# ---------------------------------------------------------------------------

def static_analysis_condition(
    config: "Dict[str, Any]",
    primary_compiler: str = "g++",
    tool_names: Optional[Any] = None,
    include_identities: bool = True,
) -> "Dict[str, Any]":
    """The static-analysis condition of a run, content-addressed.

    Covers: enabled tool list, effective per-tool settings and options,
    scopes, implementation hashes, shared modules, build config per
    execution model, TU strategies, external container command templates,
    measured tool identities (only for tools available in THIS process -
    other containers contribute their own identities per tool entry),
    low-confidence policy and the tool-state schema.
    """
    from thesis.evaluation import tools as tools_module
    from thesis.evaluation.build_config import EXECUTION_MODEL_MACROS, get_build_config
    from thesis.evaluation.framework import TOOL_STATE_SCHEMA_VERSION, get_tool
    from thesis.evaluation.tool_config import resolve_tool_settings, tool_option

    settings = resolve_tool_settings(config, "static_analysis")
    names = [n for n, s in settings.items() if s.enabled and (tool_names is None or n in tool_names)]

    per_tool = OrderedDict()
    for name in names:
        s = settings[name]
        entry = OrderedDict()
        entry["execution_models"] = list(s.execution_models)
        entry["low_precision_warning"] = bool(s.low_precision_warning)
        entry["low_precision_families"] = list(s.low_precision_families)
        entry["options"] = OrderedDict([
            ("gcc_analyzer.timeout_seconds", tool_option(config, "static_analysis", "gcc_analyzer", "timeout_seconds", 300.0)),
            ("infer.bufferoverrun_max_level", tool_option(config, "static_analysis", "infer", "bufferoverrun_max_level", 2)),
            ("parcoach.timeout_seconds", tool_option(config, "static_analysis", "parcoach", "timeout_seconds", 60.0)),
        ]) if name in ("gcc_analyzer", "infer", "parcoach") else OrderedDict()
        entry["implementation_sha256"] = tools_module.tool_implementation_sha256(name)
        entry["tu_strategy"] = TU_STRATEGY.get(name, "unknown")
        if include_identities:
            try:
                available = get_tool(name).is_available()
            except KeyError:
                available = False
            entry["tool_identity"] = tools_module.tool_runtime_identity(name) if available else None
        per_tool[name] = entry

    repair = (config.get("stages") or {}).get("repair") or {}
    condition = OrderedDict()
    condition["condition_version"] = STATIC_CONDITION_VERSION
    condition["tool_state_schema"] = TOOL_STATE_SCHEMA_VERSION
    condition["primary_compiler"] = primary_compiler
    condition["tools"] = per_tool
    condition["shared_modules_sha256"] = shared_modules_sha256()
    condition["tools_module_sha256"] = sha256_path(REPO_ROOT / "thesis/evaluation/tools.py")
    # every translation unit includes driver/benchmark sources; a change
    # there is invisible to the per-sample source hash (reviewer finding)
    condition["drivers_tree_sha256"] = drivers_tree_sha256()
    condition["build"] = OrderedDict(
        (m, OrderedDict([("macro", get_build_config(m, primary_compiler).macro),
                         ("cxxflags", list(get_build_config(m, primary_compiler).cxxflags))]))
        for m in sorted(EXECUTION_MODEL_MACROS))
    condition["external_tool_commands"] = OrderedDict(sorted((repair.get("external_tool_commands") or {}).items()))
    condition["external_tools"] = list(repair.get("external_tools") or [])
    condition["low_confidence_stop_mode"] = repair.get("low_confidence_stop_mode", "grace_once")
    return condition


def static_analysis_condition_sha256(condition: "Dict[str, Any]") -> str:
    # identities are measured per process and vary across the container split;
    # the FINGERPRINT excludes them so one run has one static condition, while
    # the per-tool entries keep the measured identity that produced them
    stripped = json.loads(json.dumps(condition, default=str))
    for entry in stripped.get("tools", {}).values():
        entry.pop("tool_identity", None)
    return canonical_sha256(stripped)


def feedback_template_fingerprint(config: "Dict[str, Any]") -> str:
    from thesis.repair import feedback
    repair = (config.get("stages") or {}).get("repair") or {}
    return canonical_sha256(OrderedDict([
        ("feedback_settings", repair.get("feedback") or {}),
        ("feedback_module_sha256", sha256_path(REPO_ROOT / "thesis/repair/feedback.py")),
        ("render_source", inspect.getsource(feedback.render_finding)),
    ]))


def repair_condition(config: "Dict[str, Any]") -> "Dict[str, Any]":
    from thesis.evaluation.framework import TOOL_STATE_SCHEMA_VERSION
    from thesis.repair import orchestrator

    settings = orchestrator.repair_settings(config)
    repair = (config.get("stages") or {}).get("repair") or {}
    generation_defaults = config.get("generation_defaults") or {}

    condition = OrderedDict()
    condition["condition_version"] = REPAIR_CONDITION_VERSION
    condition["tool_state_schema"] = TOOL_STATE_SCHEMA_VERSION
    condition["repair_state_schema"] = orchestrator.STATE_SCHEMA_VERSION
    condition["variants"] = list(settings["variants"])
    condition["max_iterations"] = settings["max_iterations"]
    condition["strategies"] = OrderedDict(sorted(
        (k, list((v or {}).get("sources") or []))
        for k, v in ((repair.get("strategies") or {}) if isinstance(repair.get("strategies"), dict) else {}).items()))
    condition["history_mode"] = repair.get("history_mode", "compressed")
    condition["low_confidence_stop_mode"] = settings["low_confidence_stop_mode"]
    condition["low_confidence_identity"] = list(orchestrator.LOW_CONFIDENCE_IDENTITY_FIELDS)
    condition["feedback_template_sha256"] = feedback_template_fingerprint(config)
    condition["api_mode"] = settings["api_mode"]
    condition["api_mode_overrides"] = OrderedDict(sorted(settings["api_mode_overrides"].items()))
    condition["external_tools_mode"] = settings["external_tools_mode"]
    condition["external_tools"] = list(settings["external_tools"])
    condition["retry_policy"] = OrderedDict([
        ("provider_internal_retry_attempts", generation_defaults.get("retry_attempts", 2)),
        ("request_retry_rounds", settings["request_retry_rounds"]),
        ("exhaustion_status", orchestrator.STATUS_API_EXHAUSTED),
    ])
    condition["terminal_statuses"] = list(orchestrator.TERMINAL_STATUSES)
    condition["orchestrator_sha256"] = sha256_path(REPO_ROOT / "thesis/repair/orchestrator.py")
    return condition


def repair_condition_sha256(condition: "Dict[str, Any]") -> str:
    return canonical_sha256(condition)
