"""Config-driven tool settings for the analysis stages.

config.yaml describes each tool of stages.static_analysis / dynamic_analysis
as a mapping:

    tools:
      parcoach:
        enabled: true
        execution_models: [mpi]
        low_precision_warning: true
      clang_tidy:
        enabled: true
        execution_models: [serial, omp, mpi]
        low_precision_families:
          - "clang-analyzer-optin.mpi"

Rules implemented here:
  - `execution_models` in the config can only NARROW a tool's hard
    capabilities (HARD_CAPABILITIES below, mirrored by the tool classes'
    `execution_models` attributes and asserted in the test suite). A config
    scope outside the capabilities logs a warning and is intersected away —
    the config can never make a tool run where it technically cannot.
  - Unknown tool names or execution models are hard errors (raised by
    validate_stage_tools, called from load_config).
  - Defaults preserve the pre-config behavior: every current tool enabled
    with its current scope; helgrind/drd are implemented but disabled.
  - `low_precision_warning: true` marks ALL findings of the tool as
    low_confidence. `low_precision_families` marks only findings whose
    check_id starts with one of the listed prefixes (the clang_tidy case:
    one invocation bundles families of very different precision — the
    MPI-Checker family measured ~0.5 precision on MBI while the rest is
    fine).

low_confidence is a data field on Finding; how it affects the repair loop's
stop criterion is configured separately (stages.repair.
low_confidence_stop_mode: ignore | grace_once | always_blocking) and
evaluated by the loop orchestrator once it exists.

Python 3.8 compatible (the LLOV container runs the static runner).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

KNOWN_EXECUTION_MODELS = ("serial", "omp", "mpi")

_ALL = ("serial", "omp", "mpi")

# Hard capabilities: what each tool can technically analyze. Single source
# for config validation; the tool classes carry the same tuples as
# `execution_models` attributes (kept in sync by test_evaluation.py).
HARD_CAPABILITIES: "Dict[str, Tuple[str, ...]]" = {
    # static
    "compiler": _ALL,
    "clang_tidy": _ALL,
    "cppcheck": _ALL,
    "infer": _ALL,
    "parcoach": ("mpi",),
    "llov": ("omp",),
    # dynamic
    "asan_ubsan": _ALL,
    "tsan": ("omp",),
    "memcheck": ("serial", "omp"),
    "must": ("mpi",),
    "helgrind": ("omp",),
    "drd": ("omp",),
}

STAGE_TOOLS = {
    "static_analysis": ("compiler", "clang_tidy", "cppcheck", "infer", "parcoach", "llov"),
    "dynamic_analysis": ("asan_ubsan", "tsan", "memcheck", "must", "helgrind", "drd"),
}

# Default settings = current behavior. low_precision defaults follow the
# tool-validation measurements (results/summary.md): parcoach precision
# 0.506/0.51 on MBI; helgrind 0.52 / FP rate 0.89 on DRB; drd recall 0.20.
# The clang_tidy MPI-Checker family is precision-marked via families.
_DEFAULTS: "Dict[str, Dict[str, Any]]" = {
    "compiler":   {"enabled": True},
    "clang_tidy": {"enabled": True, "low_precision_families": ("clang-analyzer-optin.mpi",)},
    "cppcheck":   {"enabled": True},
    "infer":      {"enabled": True},
    "parcoach":   {"enabled": True, "low_precision_warning": True},
    "llov":       {"enabled": True},
    "asan_ubsan": {"enabled": True},
    "tsan":       {"enabled": True},
    "memcheck":   {"enabled": True},
    "must":       {"enabled": True},
    # implemented, disabled by default — enabling is a config decision;
    # the validation numbers justify the default (see
    # thesis/docs/static-analysis-filtering.md)
    "helgrind":   {"enabled": False, "low_precision_warning": True},
    "drd":        {"enabled": False, "low_precision_warning": True},
}


@dataclass
class ToolSettings:
    name: str
    enabled: bool
    execution_models: Tuple[str, ...]  # EFFECTIVE scope (config ∩ hard)
    low_precision_warning: bool
    low_precision_families: Tuple[str, ...]

    def applies_to(self, execution_model: str) -> bool:
        return execution_model in self.execution_models


def _stage_tools_config(config: "Dict[str, Any]", stage_name: str) -> Any:
    stage = (config.get("stages") or {}).get(stage_name) or {}
    return stage.get("tools")


def validate_stage_tools(config: "Dict[str, Any]", stage_name: str) -> None:
    """Hard schema validation, called from load_config.

    Unknown tool names and unknown execution models are configuration bugs
    and fail loudly; scope-vs-capability conflicts are warnings at resolve
    time (the run proceeds with the intersection).
    """
    tools_config = _stage_tools_config(config, stage_name)

    if tools_config is None or isinstance(tools_config, list):
        return  # legacy list schema or absent: resolver handles it

    if not isinstance(tools_config, dict):
        raise ValueError(
            "stages.%s.tools must be a mapping of tool name -> settings "
            "(got %s)" % (stage_name, type(tools_config).__name__)
        )

    known = STAGE_TOOLS[stage_name]

    for name, entry in tools_config.items():
        if name not in known:
            raise ValueError(
                "stages.%s.tools: unknown tool '%s'. Known tools for this "
                "stage: %s" % (stage_name, name, ", ".join(known))
            )

        if entry is None:
            continue

        if not isinstance(entry, dict):
            raise ValueError(
                "stages.%s.tools.%s must be a mapping (got %s)"
                % (stage_name, name, type(entry).__name__)
            )

        for model in entry.get("execution_models", []) or []:
            if model not in KNOWN_EXECUTION_MODELS:
                raise ValueError(
                    "stages.%s.tools.%s: unknown execution model '%s' "
                    "(known: %s)" % (stage_name, name, model,
                                     ", ".join(KNOWN_EXECUTION_MODELS))
                )


def resolve_tool_settings(
    config: "Dict[str, Any]", stage_name: str
) -> "OrderedDict[str, ToolSettings]":
    """Effective per-tool settings for a stage (defaults <- config overlay).

    Returns ALL stage tools (including disabled ones) in canonical order;
    callers filter on `.enabled`. Accepts the legacy flat list schema
    (tools listed = enabled with default scopes) with a warning.
    """
    tools_config = _stage_tools_config(config, stage_name)

    legacy_enabled = None
    if isinstance(tools_config, list):
        print(
            "[tool_config] stages.%s.tools uses the legacy list schema; "
            "listed tools run with default scopes." % stage_name
        )
        legacy_enabled = set(tools_config)
        tools_config = {}
    elif tools_config is None:
        tools_config = {}

    validate_stage_tools({"stages": {stage_name: {"tools": tools_config}}}, stage_name)

    settings: "OrderedDict[str, ToolSettings]" = OrderedDict()

    for name in STAGE_TOOLS[stage_name]:
        defaults = _DEFAULTS[name]
        entry = tools_config.get(name) or {}

        hard = HARD_CAPABILITIES[name]

        enabled = entry.get("enabled", defaults.get("enabled", True))
        if legacy_enabled is not None:
            enabled = name in legacy_enabled

        requested = tuple(entry.get("execution_models") or hard)
        effective = tuple(m for m in requested if m in hard)

        outside = [m for m in requested if m not in hard]
        if outside:
            print(
                "[tool_config] WARNING: stages.%s.tools.%s requests execution "
                "models %s outside the tool's capabilities %s — ignoring them "
                "(config can only narrow, never extend)."
                % (stage_name, name, outside, list(hard))
            )

        settings[name] = ToolSettings(
            name=name,
            enabled=bool(enabled),
            execution_models=effective,
            low_precision_warning=bool(
                entry.get("low_precision_warning",
                          defaults.get("low_precision_warning", False))
            ),
            low_precision_families=tuple(
                entry.get("low_precision_families",
                          defaults.get("low_precision_families", ()))
            ),
        )

    return settings


def mark_low_confidence(findings: Iterable[Any], tool_settings: ToolSettings) -> int:
    """Set Finding.low_confidence per the tool's settings; returns count.

    Tool-level low_precision_warning marks every finding; otherwise only
    findings whose check_id starts with a configured family prefix are
    marked (the clang_tidy case).
    """
    marked = 0

    for finding in findings:
        if tool_settings.low_precision_warning or any(
            finding.check_id.startswith(prefix)
            for prefix in tool_settings.low_precision_families
        ):
            finding.low_confidence = True
            marked += 1

    return marked


# Repair-loop stop semantics for low_confidence findings. The loop
# orchestrator (not yet built) evaluates this; documented here so the
# config schema is complete now:
#   ignore          low_confidence findings never affect the stop criterion
#                   (pure feedback hints)
#   grace_once      DEFAULT. A low_confidence finding counts as blocking
#                   while it is NEW; if the same finding (identity:
#                   check_id + line, the existing dedupe key) persists
#                   unchanged into the next iteration it stops counting —
#                   the model had one iteration to verify it, a persisting
#                   report is treated as checked/false alarm. New
#                   low_confidence findings get their own grace iteration.
#   always_blocking like normal blocking findings (permanent warners such
#                   as parcoach then always drive loops to max_iterations —
#                   an experiment option, not a default)
LOW_CONFIDENCE_STOP_MODES = ("ignore", "grace_once", "always_blocking")


# Valid feedback sources / history modes for the repair formatter
# (thesis/repair/feedback.py; kept here so load_config validates them
# without importing the repair package).
REPAIR_FEEDBACK_SOURCES = (
    "compiler_errors",
    "static_findings",
    "correctness_verdicts",
    "dynamic_findings",
)

REPAIR_HISTORY_MODES = ("compressed", "full")

# Orchestrator enums (thesis/repair/orchestrator.py); validated here so a
# config typo fails at load time in every entry point, not mid-loop.
REPAIR_API_MODES = ("direct", "batch")
REPAIR_EXTERNAL_TOOLS_MODES = ("manual", "docker")
REPAIR_DEFAULT_STRATEGIES = (
    "static_feedback",
    "test_feedback",
    "combined_feedback",
)


def validate_repair_config(config: "Dict[str, Any]") -> None:
    repair = (config.get("stages") or {}).get("repair") or {}
    mode = repair.get("low_confidence_stop_mode")

    if mode is not None and mode not in LOW_CONFIDENCE_STOP_MODES:
        raise ValueError(
            "stages.repair.low_confidence_stop_mode must be one of %s "
            "(got '%s')" % (", ".join(LOW_CONFIDENCE_STOP_MODES), mode)
        )

    hist = repair.get("history_mode")

    if hist is not None and hist not in REPAIR_HISTORY_MODES:
        raise ValueError(
            "stages.repair.history_mode must be one of %s (got '%s')"
            % (", ".join(REPAIR_HISTORY_MODES), hist)
        )

    strategies = repair.get("strategies")

    # mapping schema: {name: {sources: [...]}}; the legacy list form names
    # strategies without sources (design defaults apply) and stays valid
    if isinstance(strategies, dict):
        for name, entry in strategies.items():
            for source in (entry or {}).get("sources") or []:
                if source not in REPAIR_FEEDBACK_SOURCES:
                    raise ValueError(
                        "stages.repair.strategies.%s: unknown feedback "
                        "source '%s' (known: %s)"
                        % (name, source, ", ".join(REPAIR_FEEDBACK_SOURCES))
                    )

    # orchestrator keys -----------------------------------------------------

    known_strategies = set(REPAIR_DEFAULT_STRATEGIES)
    if isinstance(strategies, dict):
        known_strategies |= set(strategies)
    elif isinstance(strategies, list):
        known_strategies |= set(strategies)

    for variant in repair.get("variants") or []:
        if variant not in known_strategies:
            raise ValueError(
                "stages.repair.variants: unknown variant '%s' (known: %s)"
                % (variant, ", ".join(sorted(known_strategies)))
            )

    api_mode = repair.get("api_mode")
    if api_mode is not None and api_mode not in REPAIR_API_MODES:
        raise ValueError(
            "stages.repair.api_mode must be one of %s (got '%s')"
            % (", ".join(REPAIR_API_MODES), api_mode)
        )

    for provider, mode in (repair.get("api_mode_overrides") or {}).items():
        if mode not in REPAIR_API_MODES:
            raise ValueError(
                "stages.repair.api_mode_overrides.%s must be one of %s "
                "(got '%s')" % (provider, ", ".join(REPAIR_API_MODES), mode)
            )

    external_mode = repair.get("external_tools_mode")
    if external_mode is not None and external_mode not in REPAIR_EXTERNAL_TOOLS_MODES:
        raise ValueError(
            "stages.repair.external_tools_mode must be one of %s (got '%s')"
            % (", ".join(REPAIR_EXTERNAL_TOOLS_MODES), external_mode)
        )

    known_tools = set(STAGE_TOOLS["static_analysis"]) | set(
        STAGE_TOOLS["dynamic_analysis"]
    )
    for tool in repair.get("external_tools") or []:
        if tool not in known_tools:
            raise ValueError(
                "stages.repair.external_tools: unknown tool '%s' (known: %s)"
                % (tool, ", ".join(sorted(known_tools)))
            )
