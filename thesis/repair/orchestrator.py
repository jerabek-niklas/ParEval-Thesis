"""Repair-loop orchestrator (thesis/docs/repair-loop-design.md §2, §5-§7).

This module wires the existing building blocks into repair iterations:
feedback.py builds the stateless requests over the stage JSONLs, the
provider adapters (thesis/generation/generate-*.py) execute them, repair
answers go through the NORMAL assembly cleaning
(thesis/assembly/assemble_sources.py), and the existing stage runners
analyze the new artifacts. Nothing here re-implements analysis, cleaning,
or formatting — the orchestrator is the state machine around them.

Identity and layout (design §5)
-------------------------------
A repair artifact is identified by (sample_id, variant, iteration);
iteration 0 is the shared initial generation and is NEVER regenerated.
Iteration artifacts reuse the complete existing pipeline layout through a
RUN-ID CONVENTION instead of a schema change:

    iteration 0:  <base_run_id>                       (the existing run)
    iteration N:  <base_run_id>__<variant>__iter<N>   (N >= 1)

Rationale (smallest intervention): iter_assembled_samples() and all three
stage runners key every artifact on (intermediate_dir, run_id, model_id).
A synthetic run id per (variant, iteration) makes every existing runner —
including its resume/merge logic and the multi-container --tools split —
work on iteration artifacts unchanged; the only pipeline change is an
optional --run-id override on the stage runners. Raw repair responses use
the same convention (raw/<iter_run_id>/<model>/generations.jsonl) so
assemble_sources.assemble_model() runs unchanged on them.

Loop metadata lives under the BASE run (per-variant):

    intermediate/<run>/<model>/repair/<variant>/state.jsonl
    intermediate/<run>/<model>/repair/<variant>/wave_state.json
    intermediate/<run>/<model>/repair/<variant>/pending_external.txt
    intermediate/<run>/<model>/repair/<variant>/iter<N>/requests.jsonl
    intermediate/<run>/<model>/repair/<variant>/iter<N>/batch.json

Wave state machine (design §7; task phase names)
------------------------------------------------
Per (model, variant) one wave runs over all active samples:

    [start] -> analyzed(0) -> decided(0)
      -> requests_built(1) -> submitted(1) -> responses_merged(1)
      -> assembled(1) -> analyzed(1) [-> analyzed_waiting_external]
      -> decided(1) -> ... -> done

"need_feedback" from the task description is the entry action out of
`decided` (requests are built for the samples still active); it is not a
persisted phase of its own. `submitted` is only persisted in batch mode —
direct mode merges submit+merge into one idempotent step. The orchestrator
is restartable after EVERY step: each step re-derives its remaining work
from the persisted files (requests/responses/assembly/stage JSONLs) and
skips what already exists; wave_state.json only caches the phase pointer.

Held-out principle: enhanced tests are NEVER run by this orchestrator
(design §3/§6); phase-2 backfill is a separate runner.

Python 3.8 compatible.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.generation import common  # noqa: E402
from thesis.repair import feedback  # noqa: E402
from thesis.evaluation import framework  # noqa: E402
from thesis.evaluation.tool_config import (  # noqa: E402
    ToolSettings,
    resolve_tool_settings,
)

STATE_SCHEMA_VERSION = "repair_state.v1"
WAVE_SCHEMA_VERSION = "repair_wave.v1"
REQUEST_SCHEMA_VERSION = "repair_request.v1"

VARIANTS = ("static_feedback", "test_feedback", "combined_feedback")

STATUS_ACTIVE = "active"
STATUS_CLEAN = "stopped_clean"
STATUS_TESTS_PASS = "stopped_tests_pass"
STATUS_BUDGET = "stopped_budget"
STATUS_UNUSABLE = "repair_unusable"

TERMINAL_STATUSES = (
    STATUS_CLEAN,
    STATUS_TESTS_PASS,
    STATUS_BUDGET,
    STATUS_UNUSABLE,
)

PHASES = (
    "start",
    "analyzed",
    "analyzed_waiting_external",
    "decided",
    "requests_built",
    "submitted",
    "responses_merged",
    "assembled",
    "done",
)

# step() outcomes: "advanced"/"decided" continue the drive loop; the
# blocked_* outcomes end this invocation (the orchestrator never waits).
OUTCOME_ADVANCED = "advanced"
OUTCOME_DECIDED = "decided"  # advanced AND completed one wave decision
OUTCOME_DONE = "done"
OUTCOME_BLOCKED_EXTERNAL = "blocked_external"
OUTCOME_BLOCKED_BATCH = "blocked_batch"
OUTCOME_BLOCKED_API = "blocked_api"

BLOCKED_OUTCOMES = (
    OUTCOME_BLOCKED_EXTERNAL,
    OUTCOME_BLOCKED_BATCH,
    OUTCOME_BLOCKED_API,
)

API_MODES = ("direct", "batch")
EXTERNAL_TOOLS_MODES = ("manual", "docker")

# Providers with an implemented batch path (Teil 3). openai_compatible
# endpoints (Qwen/DeepSeek via DashScope) are not batch-verified — they
# fall back to direct with a log line unless the per-provider override
# explicitly forces batch (then the OpenAI-style batch client is used
# against their base_url).
BATCH_PROVIDERS = ("openai", "anthropic", "gemini")

DEFAULT_EXTERNAL_TOOLS = ("parcoach", "llov")

_ADAPTER_SCRIPTS = {
    "anthropic": ("generate-anthropic.py", "AnthropicAdapter"),
    "openai": ("generate-openai.py", "OpenAIAdapter"),
    "gemini": ("generate-gemini.py", "GeminiAdapter"),
    "openai_compatible": ("generate-openai-compatible.py", "OpenAICompatibleAdapter"),
}

_STAGE_FILE_DEFAULTS = {
    "static_analysis": "static_analysis.jsonl",
    "correctness_tests": "correctness.jsonl",
    "dynamic_analysis": "dynamic_analysis.jsonl",
}


# ---------------------------------------------------------------------------
# Config access
# ---------------------------------------------------------------------------


def repair_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    repair = (config.get("stages") or {}).get("repair") or {}

    return {
        "max_iterations": int(repair.get("max_iterations", 3)),
        "variants": list(repair.get("variants") or VARIANTS),
        "api_mode": repair.get("api_mode", "direct"),
        "api_mode_overrides": repair.get("api_mode_overrides") or {},
        "external_tools_mode": repair.get("external_tools_mode", "manual"),
        "external_tools": tuple(
            repair.get("external_tools", DEFAULT_EXTERNAL_TOOLS) or ()
        ),
        "external_tool_commands": repair.get("external_tool_commands") or {},
        "low_confidence_stop_mode": repair.get(
            "low_confidence_stop_mode", "grace_once"
        ),
    }


def stage_output_file(config: Dict[str, Any], stage_name: str) -> str:
    stage = (config.get("stages") or {}).get(stage_name) or {}
    return stage.get("output_file_name", _STAGE_FILE_DEFAULTS[stage_name])


def execution_model_of(sample_id: str) -> str:
    # sample_id layout (framework.iter_assembled_samples):
    #   <model_id>__<problem_type>__<name>__<execution_model>__sample_<i>
    parts = sample_id.split("__")
    return parts[-2] if len(parts) >= 2 else "serial"


def load_provider_adapter(provider: str) -> Any:
    """Import a generate-*.py provider adapter (hyphenated file names need
    an explicit spec import). Loaded lazily — only the submit/poll steps
    require the provider SDKs to be installed."""
    if provider not in _ADAPTER_SCRIPTS:
        raise KeyError(
            "No provider adapter for '%s' (known: %s)"
            % (provider, ", ".join(sorted(_ADAPTER_SCRIPTS)))
        )

    script, class_name = _ADAPTER_SCRIPTS[provider]
    path = REPO_ROOT / "thesis" / "generation" / script

    spec = importlib.util.spec_from_file_location(
        "thesis_generation_adapter_" + provider, str(path)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    return getattr(module, class_name)()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


@dataclass
class LoopPaths:
    """All paths of one (base_run, model, variant) loop."""

    config: Dict[str, Any]
    base_run_id: str
    model_id: str
    variant: str

    @property
    def intermediate_root(self) -> Path:
        return Path(self.config["outputs"]["intermediate_dir"])

    @property
    def raw_root(self) -> Path:
        return Path(self.config["outputs"]["raw_dir"])

    def iter_run_id(self, iteration: int) -> str:
        if iteration == 0:
            return self.base_run_id
        return "%s__%s__iter%d" % (self.base_run_id, self.variant, iteration)

    def iter_intermediate_dir(self, iteration: int) -> Path:
        return self.intermediate_root / self.iter_run_id(iteration) / self.model_id

    def iter_generations_path(self, iteration: int) -> Path:
        return (
            self.raw_root / self.iter_run_id(iteration) / self.model_id
            / "generations.jsonl"
        )

    def base_generations_path(self) -> Path:
        return self.iter_generations_path(0)

    def assembly_path(self, iteration: int) -> Path:
        return self.iter_intermediate_dir(iteration) / "assembly.jsonl"

    def stage_path(self, iteration: int, stage_name: str) -> Path:
        return self.iter_intermediate_dir(iteration) / stage_output_file(
            self.config, stage_name
        )

    def source_path(self, iteration: int, sample_id: str) -> Path:
        return (
            self.iter_intermediate_dir(iteration)
            / "sources" / sample_id / "generated-code.hpp"
        )

    @property
    def repair_dir(self) -> Path:
        return (
            self.intermediate_root / self.base_run_id / self.model_id
            / "repair" / self.variant
        )

    @property
    def state_path(self) -> Path:
        return self.repair_dir / "state.jsonl"

    @property
    def wave_state_path(self) -> Path:
        return self.repair_dir / "wave_state.json"

    @property
    def pending_external_path(self) -> Path:
        return self.repair_dir / "pending_external.txt"

    def requests_path(self, iteration: int) -> Path:
        return self.repair_dir / ("iter%d" % iteration) / "requests.jsonl"

    def batch_info_path(self, iteration: int) -> Path:
        return self.repair_dir / ("iter%d" % iteration) / "batch.json"


# ---------------------------------------------------------------------------
# State I/O (append-only JSONL; last record per sample wins)
# ---------------------------------------------------------------------------


def load_sample_states(state_path: Path) -> "Dict[str, Dict[str, Any]]":
    states: Dict[str, Dict[str, Any]] = {}

    if not state_path.exists():
        return states

    with state_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                states[record["sample_id"]] = record

    return states


# ---------------------------------------------------------------------------
# Stop logic (design §2 + low_confidence semantics; pure for unit tests)
# ---------------------------------------------------------------------------


@dataclass
class StopDecision:
    status: str
    stop_reason: str
    counts: Dict[str, int]
    test_verdict: Optional[str]
    low_confidence_keys: List[List[Any]]  # [[check_id, line], ...] of THIS iteration


def _finding_key(finding: Dict[str, Any]) -> Tuple[Any, Any]:
    return (finding.get("check_id", "unknown"), finding.get("line"))


def evaluate_stop(
    config: Dict[str, Any],
    variant: str,
    iteration: int,
    max_iterations: int,
    static_record: Optional[Dict[str, Any]],
    dynamic_record: Optional[Dict[str, Any]],
    correctness_record: Optional[Dict[str, Any]],
    previous_low_confidence_keys: Optional[List[List[Any]]],
) -> StopDecision:
    """One sample's stop decision on the analyzed iteration artifacts.

    Variant stop conditions (design §2; only the variant's OWN sources):
      static_feedback:   no compile errors, no blocking static findings
      test_feedback:     no compile errors, ParEval verdict pass, no
                         blocking dynamic findings
      combined_feedback: all of the above

    Source filtering, enabled-tool filtering, and the compiler rule are
    exactly feedback.collect_findings — the stop criterion counts what the
    feedback renders as blocking (single semantics, no second code path).

    low_confidence findings participate per stages.repair.
    low_confidence_stop_mode (ignore | grace_once | always_blocking).
    Under grace_once a low_confidence finding counts only while its key
    (check_id, line) did NOT occur in the previous iteration; a shifted
    line implies changed code and re-grants grace (design §4). Only
    findings the tool marked blocking can ever count toward the stop —
    non-blocking hints never stop the loop in any mode.
    """
    sources = feedback.strategy_sources(config, variant)

    if static_record is None:
        raise ValueError(
            "evaluate_stop: static_analysis record missing — the analyze "
            "phase must run the compiler (base feedback in every variant) "
            "before deciding"
        )

    needs_tests = "correctness_verdicts" in sources
    needs_dynamic = "dynamic_findings" in sources

    if needs_tests and correctness_record is None:
        raise ValueError(
            "evaluate_stop: correctness record missing for variant '%s'"
            % variant
        )
    if needs_dynamic and dynamic_record is None:
        raise ValueError(
            "evaluate_stop: dynamic_analysis record missing for variant '%s'"
            % variant
        )

    groups = feedback.collect_findings(config, sources, static_record, dynamic_record)

    compile_errors = len(groups["compiler_errors"])
    blocking = len(groups["blocking"])
    non_blocking = len(groups["non_blocking"])

    low_confidence_all = groups["low_confidence"]
    low_confidence_blocking = [f for f in low_confidence_all if f.get("blocking")]

    # Keys of ALL reported low_confidence findings — the identity set the
    # next iteration's grace check compares against ("occurred before").
    current_keys = sorted({_finding_key(f) for f in low_confidence_all})

    mode = repair_settings(config)["low_confidence_stop_mode"]

    if mode == "ignore":
        low_confidence_effective = 0
    elif mode == "always_blocking":
        low_confidence_effective = len(low_confidence_blocking)
    else:  # grace_once (default)
        previous = {tuple(key) for key in (previous_low_confidence_keys or [])}
        low_confidence_effective = sum(
            1
            for f in low_confidence_blocking
            if _finding_key(f) not in previous
        )

    test_verdict = correctness_record.get("verdict") if needs_tests else None
    tests_ok = (test_verdict == "pass") if needs_tests else True

    issues: List[str] = []
    if compile_errors:
        issues.append("%d compile error(s)" % compile_errors)
    if blocking:
        issues.append("%d blocking finding(s)" % blocking)
    if low_confidence_effective:
        issues.append(
            "%d new low-confidence finding(s) (%s)"
            % (low_confidence_effective, mode)
        )
    if needs_tests and not tests_ok:
        issues.append("ParEval verdict '%s'" % test_verdict)

    counts = {
        "compile_errors": compile_errors,
        "blocking": blocking,
        "low_confidence": len(low_confidence_all),
        "low_confidence_effective": low_confidence_effective,
        "non_blocking": non_blocking,
    }

    if not issues:
        status = STATUS_TESTS_PASS if variant == "test_feedback" else STATUS_CLEAN
        reason = "own sources clean at iteration %d" % iteration
        if needs_tests:
            reason += " (ParEval pass)"
    elif iteration >= max_iterations:
        status = STATUS_BUDGET
        reason = "iteration budget (%d) exhausted; unresolved: %s" % (
            max_iterations,
            "; ".join(issues),
        )
    else:
        status = STATUS_ACTIVE
        reason = "; ".join(issues)

    return StopDecision(
        status=status,
        stop_reason=reason,
        counts=counts,
        test_verdict=test_verdict,
        low_confidence_keys=[list(key) for key in current_keys],
    )


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


class RepairLoop:
    """State machine for one (model, variant) repair loop.

    All step methods are idempotent and re-derive remaining work from the
    persisted files, so the orchestrator can be killed and restarted after
    every step (resume is a requirement, not a nice-to-have).
    """

    def __init__(
        self,
        config: Dict[str, Any],
        config_path: str,
        profile_name: str,
        profile: Dict[str, Any],
        model_config: Dict[str, Any],
        variant: str,
        primary_compiler: str = "g++",
        adapter_factory: Any = None,
    ) -> None:
        if variant not in VARIANTS:
            raise ValueError(
                "Unknown variant '%s' (known: %s)" % (variant, ", ".join(VARIANTS))
            )

        self.config = config
        self.config_path = str(config_path)
        self.profile_name = profile_name
        self.profile = profile
        self.model_config = model_config
        self.model_id = model_config["id"]
        self.variant = variant
        self.primary_compiler = primary_compiler
        self.settings = repair_settings(config)
        self.paths = LoopPaths(config, profile["run_id"], self.model_id, variant)
        self._adapter_factory = adapter_factory or load_provider_adapter

    # -- logging ----------------------------------------------------------

    def log(self, message: str) -> None:
        print("[%s/%s] %s" % (self.model_id, self.variant, message))

    # -- wave state -------------------------------------------------------

    def load_wave_state(self) -> Dict[str, Any]:
        path = self.paths.wave_state_path

        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)

        return {"iteration": 0, "phase": "start", "batch": None}

    def save_wave_state(
        self, iteration: int, phase: str, batch: Optional[Dict[str, Any]] = None
    ) -> None:
        if phase not in PHASES:
            raise ValueError("unknown phase '%s'" % phase)

        state = {
            "schema_version": WAVE_SCHEMA_VERSION,
            "run_id": self.paths.base_run_id,
            "model_id": self.model_id,
            "variant": self.variant,
            "iteration": iteration,
            "phase": phase,
            "batch": batch,
            "updated_at_utc": common.utc_now_iso(),
        }
        common.write_json(self.paths.wave_state_path, state)

    # -- sample state -----------------------------------------------------

    def sample_states(self) -> "Dict[str, Dict[str, Any]]":
        return load_sample_states(self.paths.state_path)

    def append_sample_state(
        self,
        sample_id: str,
        iteration: int,
        status: str,
        stop_reason: str,
        counts: Optional[Dict[str, int]] = None,
        test_verdict: Optional[str] = None,
        low_confidence_keys: Optional[List[List[Any]]] = None,
        batch_id: Optional[str] = None,
    ) -> None:
        common.append_jsonl(
            self.paths.state_path,
            {
                "schema_version": STATE_SCHEMA_VERSION,
                "run_id": self.paths.base_run_id,
                "model_id": self.model_id,
                "variant": self.variant,
                "sample_id": sample_id,
                "iteration": iteration,
                "status": status,
                "stop_reason": stop_reason,
                "counts": counts or {},
                "test_verdict": test_verdict,
                "low_confidence_keys": low_confidence_keys or [],
                "batch_id": batch_id,
                "updated_at_utc": common.utc_now_iso(),
            },
        )

    def active_samples(self) -> List[str]:
        return sorted(
            sample_id
            for sample_id, state in self.sample_states().items()
            if state.get("status") == STATUS_ACTIVE
        )

    def mark_unusable(self, sample_id: str, iteration: int, reason: str) -> None:
        """Idempotent repair_unusable marking (logged, never silent)."""
        prior = self.sample_states().get(sample_id)

        if prior and prior.get("status") == STATUS_UNUSABLE:
            return

        self.log(
            "sample %s -> repair_unusable at iteration %d: %s"
            % (sample_id, iteration, reason)
        )
        self.append_sample_state(
            sample_id, iteration, STATUS_UNUSABLE, reason
        )

    # -- artifact loading -------------------------------------------------

    def load_assembly_entries(self, iteration: int) -> "Dict[str, Dict[str, Any]]":
        path = self.paths.assembly_path(iteration)
        entries: Dict[str, Dict[str, Any]] = {}

        if not path.exists():
            return entries

        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    entry = json.loads(line)
                    entries[entry["sample_id"]] = entry

        return entries

    def iteration_samples(self, iteration: int) -> List[str]:
        """Assembled sample ids of an iteration (iteration 0: the full
        shared base run)."""
        return sorted(
            sample_id
            for sample_id, entry in self.load_assembly_entries(iteration).items()
            if entry.get("assembled")
        )

    def load_stage_records(
        self, iteration: int, stage_name: str
    ) -> "Dict[str, Dict[str, Any]]":
        path = self.paths.stage_path(iteration, stage_name)
        records: Dict[str, Dict[str, Any]] = {}

        if not path.exists():
            return records

        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    record = json.loads(line)
                    records[record["sample_id"]] = record

        return records

    def load_base_prompts(self) -> "Dict[str, str]":
        """sample_id -> original task prompt text (from the base
        generations.jsonl; the request header block, design §4)."""
        path = self.paths.base_generations_path()

        if not path.exists():
            raise FileNotFoundError(
                "Base generations file missing: %s" % path
            )

        prompts: Dict[str, str] = {}

        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                prompt = record.get("prompt") or {}
                if record.get("sample_id") and prompt.get("prompt_text"):
                    prompts[record["sample_id"]] = prompt["prompt_text"]

        return prompts

    def load_base_generation_records(self) -> "Dict[str, Dict[str, Any]]":
        path = self.paths.base_generations_path()
        records: Dict[str, Dict[str, Any]] = {}

        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    record = json.loads(line)
                    records[record["sample_id"]] = record

        return records

    # -- stage planning ---------------------------------------------------

    def internal_static_settings(self) -> "Dict[str, ToolSettings]":
        """Static tools this loop runs in-process (phase-1 minimum, design
        §6): test_feedback needs only the compiler (compile errors are base
        feedback everywhere); the static variants run every enabled static
        tool that is NOT external (external ones live in their own
        containers and go through external_tools_mode)."""
        settings = resolve_tool_settings(self.config, "static_analysis")
        enabled = {name: s for name, s in settings.items() if s.enabled}

        if self.variant == "test_feedback":
            return {name: s for name, s in enabled.items() if name == "compiler"}

        external = set(self.settings["external_tools"])
        return {name: s for name, s in enabled.items() if name not in external}

    def dynamic_settings(self) -> "Dict[str, ToolSettings]":
        settings = resolve_tool_settings(self.config, "dynamic_analysis")
        return {name: s for name, s in settings.items() if s.enabled}

    def needs_tests(self) -> bool:
        sources = feedback.strategy_sources(self.config, self.variant)
        return "correctness_verdicts" in sources

    def needs_dynamic(self) -> bool:
        sources = feedback.strategy_sources(self.config, self.variant)
        return "dynamic_findings" in sources

    def missing_internal_stages(self, iteration: int) -> List[str]:
        """Which in-container stages still need to run for this iteration
        (coverage check per sample — this is the resume mechanism for the
        analyze phase)."""
        samples = self.iteration_samples(iteration)

        if not samples:
            raise RuntimeError(
                "No assembled samples for iteration %d (run %s) — assembly "
                "must exist before analysis"
                % (iteration, self.paths.iter_run_id(iteration))
            )

        missing: List[str] = []

        static_records = self.load_stage_records(iteration, "static_analysis")
        required_tools = set(self.internal_static_settings())

        def static_covered(sample_id: str) -> bool:
            record = static_records.get(sample_id)
            if record is None:
                return False
            present = set((record.get("tools") or {}).keys())
            return required_tools.issubset(present)

        if not all(static_covered(s) for s in samples):
            missing.append("static")

        if self.needs_tests():
            correctness = self.load_stage_records(iteration, "correctness_tests")
            if not all(s in correctness for s in samples):
                missing.append("correctness")

        if self.needs_dynamic():
            dynamic = self.load_stage_records(iteration, "dynamic_analysis")
            if not all(s in dynamic for s in samples):
                missing.append("dynamic")

        return missing

    def _check_tools_available(self, names: List[str]) -> None:
        unavailable = [
            name
            for name in names
            if not framework.get_tool(name).is_available()
        ]

        if unavailable:
            raise RuntimeError(
                "Required tools unavailable in this environment: %s. The "
                "analyze phase must run inside the pareval-thesis container "
                "— deciding on partial analysis would corrupt the stop "
                "criterion." % ", ".join(unavailable)
            )

    def _run_analysis_stages(self, iteration: int, stages: List[str]) -> None:
        """Run the missing in-container stages in-process via the existing
        stage runners (no subprocess, no duplication). Overridable in unit
        tests."""
        run_id = self.paths.iter_run_id(iteration)
        intermediate_root = self.paths.intermediate_root

        context = framework.EvaluationContext(
            repo_root=REPO_ROOT,
            drivers_cpp_dir=REPO_ROOT / "drivers" / "cpp",
            primary_compiler=self.primary_compiler,
            config=self.config,
        )

        if "static" in stages:
            from thesis.evaluation import run_static_analysis
            from thesis.evaluation.tools import register_default_tools

            register_default_tools(primary_compiler=self.primary_compiler)
            settings = self.internal_static_settings()
            self._check_tools_available(list(settings))

            self.log(
                "analyze iteration %d: static (%s)"
                % (iteration, ", ".join(settings))
            )
            run_static_analysis.run_model(
                context=context,
                intermediate_dir=intermediate_root,
                run_id=run_id,
                model_id=self.model_id,
                tool_settings=settings,
            )

        if "correctness" in stages:
            from thesis.evaluation import run_correctness

            if not framework.binary_available(self.primary_compiler):
                raise RuntimeError(
                    "Compiler '%s' unavailable — correctness stage needs the "
                    "pareval-thesis container." % self.primary_compiler
                )

            stage = (self.config.get("stages") or {}).get("correctness_tests") or {}

            self.log("analyze iteration %d: correctness" % iteration)
            run_correctness.run_model(
                context=context,
                intermediate_dir=intermediate_root,
                run_id=run_id,
                model_id=self.model_id,
                output_file_name=stage_output_file(self.config, "correctness_tests"),
                launch_overrides=stage.get("launch_overrides"),
                niter=int(stage.get("niter", run_correctness.DEFAULT_NITER)),
                build_timeout=float(
                    stage.get(
                        "build_timeout_seconds", run_correctness.DEFAULT_BUILD_TIMEOUT
                    )
                ),
                run_timeout=float(
                    stage.get(
                        "run_timeout_seconds", run_correctness.DEFAULT_RUN_TIMEOUT
                    )
                ),
            )

        if "dynamic" in stages:
            from thesis.evaluation import run_dynamic_analysis
            from thesis.evaluation.dynamic_tools import register_dynamic_tools

            register_dynamic_tools()
            settings = self.dynamic_settings()
            self._check_tools_available(list(settings))

            self.log(
                "analyze iteration %d: dynamic (%s)"
                % (iteration, ", ".join(settings))
            )
            run_dynamic_analysis.run_model(
                context=context,
                intermediate_dir=intermediate_root,
                run_id=run_id,
                model_id=self.model_id,
                tool_settings=settings,
                output_file_name=stage_output_file(self.config, "dynamic_analysis"),
            )

    # -- external tools (parcoach/llov containers) ------------------------

    def pending_external(self, iteration: int) -> List[Tuple[str, int]]:
        """(tool, missing-sample-count) for enabled external static tools
        whose records are still missing. A tool whose execution-model scope
        matches no sample of this iteration is never waited for."""
        if self.variant == "test_feedback":
            return []  # compile-only static: external static tools irrelevant

        settings = resolve_tool_settings(self.config, "static_analysis")
        static_records = self.load_stage_records(iteration, "static_analysis")

        pending: List[Tuple[str, int]] = []

        for name in self.settings["external_tools"]:
            tool = settings.get(name)
            if tool is None or not tool.enabled:
                continue

            relevant = [
                s
                for s in self.iteration_samples(iteration)
                if execution_model_of(s) in tool.execution_models
            ]
            missing = [
                s
                for s in relevant
                if name not in ((static_records.get(s) or {}).get("tools") or {})
            ]

            if missing:
                pending.append((name, len(missing)))

        return pending

    def external_command(self, tool: str, iteration: int) -> str:
        template = self.settings["external_tool_commands"].get(tool)

        if template:
            return template.format(
                repo=str(REPO_ROOT),
                config=self.config_path,
                profile=self.profile_name,
                run_id=self.paths.iter_run_id(iteration),
                model_id=self.model_id,
                tools=tool,
            )

        # manual default: the runner invocation to execute inside the
        # tool's container (repo mounted at the container workdir)
        return (
            "python3 thesis/evaluation/run_static_analysis.py "
            "--config %s --profile %s --run-id %s --model-id %s --tools %s"
            % (
                self.config_path,
                self.profile_name,
                self.paths.iter_run_id(iteration),
                self.model_id,
                tool,
            )
        )

    def write_pending_external(
        self, pending: List[Tuple[str, int]], iteration: int
    ) -> None:
        lines = [
            "# Repair loop %s/%s waiting for external static tools" % (self.model_id, self.variant),
            "# iteration %d, run id %s" % (iteration, self.paths.iter_run_id(iteration)),
            "# Run each command inside the tool's container (parcoach ->",
            "# parcoach-demo:2.4.1, llov -> pareval-llov; repo mounted), then",
            "# re-run run_repair.py — it verifies the records and continues.",
        ]

        for tool, count in pending:
            lines.append("# %s: %d sample(s) missing" % (tool, count))
            lines.append(self.external_command(tool, iteration))

        self.paths.pending_external_path.parent.mkdir(parents=True, exist_ok=True)
        self.paths.pending_external_path.write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

        self.log("waiting for external tools (see pending_external.txt):")
        for line in lines:
            print("    " + line)

    def run_external_docker(
        self, pending: List[Tuple[str, int]], iteration: int
    ) -> None:
        for tool, count in pending:
            template = self.settings["external_tool_commands"].get(tool)

            if not template:
                raise ValueError(
                    "external_tools_mode is 'docker' but stages.repair."
                    "external_tool_commands has no template for '%s'" % tool
                )

            command = self.external_command(tool, iteration)
            self.log("external %s (%d sample(s)): %s" % (tool, count, command))

            result = subprocess.run(command, shell=True)

            if result.returncode != 0:
                raise RuntimeError(
                    "External tool command for '%s' exited %d"
                    % (tool, result.returncode)
                )

    # -- phases -----------------------------------------------------------

    def _to_analyzed(self, iteration: int) -> str:
        missing = self.missing_internal_stages(iteration)

        if missing:
            self._run_analysis_stages(iteration, missing)

            still_missing = self.missing_internal_stages(iteration)
            if still_missing:
                raise RuntimeError(
                    "Analysis stages %s still incomplete after running — "
                    "check the runner output" % ", ".join(still_missing)
                )

        pending = self.pending_external(iteration)

        if pending:
            if self.settings["external_tools_mode"] == "docker":
                self.run_external_docker(pending, iteration)
                pending = self.pending_external(iteration)
                if pending:
                    raise RuntimeError(
                        "External tool records still missing after docker "
                        "run: %s" % pending
                    )
            else:
                self.write_pending_external(pending, iteration)
                self.save_wave_state(iteration, "analyzed_waiting_external")
                return OUTCOME_BLOCKED_EXTERNAL

        if self.paths.pending_external_path.exists():
            self.paths.pending_external_path.unlink()

        self.save_wave_state(iteration, "analyzed")
        self.log("iteration %d analyzed" % iteration)
        return OUTCOME_ADVANCED

    def compute_decisions(
        self, iteration: int
    ) -> "List[Tuple[str, Optional[Dict[str, Any]], StopDecision]]":
        """Stop decisions for every still-undecided sample of an iteration
        (pure read — used by both _decide and --dry-run)."""
        states = self.sample_states()
        samples = self.iteration_samples(iteration)

        static_records = self.load_stage_records(iteration, "static_analysis")
        correctness_records = (
            self.load_stage_records(iteration, "correctness_tests")
            if self.needs_tests()
            else {}
        )
        dynamic_records = (
            self.load_stage_records(iteration, "dynamic_analysis")
            if self.needs_dynamic()
            else {}
        )

        decisions: List[Tuple[str, Optional[Dict[str, Any]], StopDecision]] = []

        for sample_id in samples:
            prior = states.get(sample_id)

            if prior is not None:
                if prior.get("status") in TERMINAL_STATUSES:
                    continue  # loop already ended for this sample
                if int(prior.get("iteration", -1)) >= iteration:
                    continue  # this iteration is already decided (resume)

            decision = evaluate_stop(
                config=self.config,
                variant=self.variant,
                iteration=iteration,
                max_iterations=self.settings["max_iterations"],
                static_record=static_records.get(sample_id),
                dynamic_record=dynamic_records.get(sample_id),
                correctness_record=correctness_records.get(sample_id),
                previous_low_confidence_keys=(
                    prior.get("low_confidence_keys") if prior else None
                ),
            )
            decisions.append((sample_id, prior, decision))

        return decisions

    def _decide(self, iteration: int) -> str:
        # Bootstrap bookkeeping: base samples that never assembled cannot
        # enter the loop (design §5 — logged, not silently dropped).
        if iteration == 0:
            for sample_id, entry in self.load_assembly_entries(0).items():
                if not entry.get("assembled"):
                    self.mark_unusable(
                        sample_id,
                        0,
                        "initial generation not assembled (%s)"
                        % entry.get("skip_reason", "unknown"),
                    )

        outcomes: Counter = Counter()

        for sample_id, prior, decision in self.compute_decisions(iteration):
            self.append_sample_state(
                sample_id,
                iteration,
                decision.status,
                decision.stop_reason,
                counts=decision.counts,
                test_verdict=decision.test_verdict,
                low_confidence_keys=decision.low_confidence_keys,
            )
            outcomes[decision.status] += 1

        self.save_wave_state(iteration, "decided")

        summary = ", ".join(
            "%s: %d" % (status, count) for status, count in sorted(outcomes.items())
        ) or "nothing new to decide"
        self.log("iteration %d decided (%s)" % (iteration, summary))

        return OUTCOME_DECIDED

    def build_request_records(
        self, target_iteration: int, sample_ids: List[str]
    ) -> "List[Dict[str, Any]]":
        """Build the repair requests for a target iteration (pure — the
        write happens in _build_requests, --dry-run only counts).

        History = iterations 0..current-1, current = target-1; the past
        iteration header shows 1-based attempt numbers (iteration 0 is
        "Iteration 1 (previous attempt)"), matching the design §4 example.
        """
        current = target_iteration - 1
        prompts = self.load_base_prompts()

        records_by_iteration: Dict[int, Dict[str, Dict[str, Any]]] = {}
        for i in range(0, current + 1):
            records_by_iteration[i] = {
                "static": self.load_stage_records(i, "static_analysis"),
                "correctness": self.load_stage_records(i, "correctness_tests"),
                "dynamic": self.load_stage_records(i, "dynamic_analysis"),
            }

        requests: List[Dict[str, Any]] = []

        for sample_id in sample_ids:
            if sample_id not in prompts:
                raise KeyError(
                    "No base generation prompt for sample %s" % sample_id
                )

            history: List[feedback.IterationRecord] = []
            for i in range(0, current):
                history.append(
                    feedback.IterationRecord(
                        iteration=i + 1,
                        cleaned_code=self.paths.source_path(i, sample_id).read_text(
                            encoding="utf-8"
                        ),
                        static_record=records_by_iteration[i]["static"].get(sample_id),
                        dynamic_record=records_by_iteration[i]["dynamic"].get(sample_id),
                        correctness_record=records_by_iteration[i]["correctness"].get(
                            sample_id
                        ),
                    )
                )

            current_code = self.paths.source_path(current, sample_id).read_text(
                encoding="utf-8"
            )
            request_text = feedback.build_repair_request(
                task_prompt=prompts[sample_id],
                history=history,
                current_code=current_code,
                current_records={
                    "static": records_by_iteration[current]["static"].get(sample_id),
                    "dynamic": records_by_iteration[current]["dynamic"].get(sample_id),
                    "correctness": records_by_iteration[current]["correctness"].get(
                        sample_id
                    ),
                },
                strategy=self.variant,
                config=self.config,
            )

            requests.append(
                {
                    "schema_version": REQUEST_SCHEMA_VERSION,
                    "run_id": self.paths.base_run_id,
                    "model_id": self.model_id,
                    "sample_id": sample_id,
                    "variant": self.variant,
                    "iteration": target_iteration,
                    "built_from_iteration": current,
                    "strategy": self.variant,
                    "request": request_text,
                    "request_chars": len(request_text),
                    "created_at_utc": common.utc_now_iso(),
                }
            )

        return requests

    def _build_requests(self, target_iteration: int) -> str:
        actives = self.active_samples()

        requests_path = self.paths.requests_path(target_iteration)
        existing = set()

        if requests_path.exists():
            with requests_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        existing.add(json.loads(line)["sample_id"])

        todo = [s for s in actives if s not in existing]

        for record in self.build_request_records(target_iteration, todo):
            common.append_jsonl(requests_path, record)

        self.save_wave_state(target_iteration, "requests_built")
        self.log(
            "iteration %d: %d repair request(s) built (%d resumed)"
            % (target_iteration, len(todo), len(existing))
        )
        return OUTCOME_ADVANCED

    def load_requests(self, target_iteration: int) -> "List[Dict[str, Any]]":
        path = self.paths.requests_path(target_iteration)
        requests: List[Dict[str, Any]] = []

        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        requests.append(json.loads(line))

        return requests

    # -- API submission ---------------------------------------------------

    def api_mode(self) -> str:
        provider = self.model_config.get("provider")
        overrides = self.settings["api_mode_overrides"]
        mode = overrides.get(provider, self.settings["api_mode"])

        if mode == "batch" and provider not in BATCH_PROVIDERS:
            forced = overrides.get(provider) == "batch"
            if not forced:
                self.log(
                    "provider '%s' has no verified batch API — falling back "
                    "to direct (set stages.repair.api_mode_overrides.%s: "
                    "batch to force the OpenAI-style batch client)"
                    % (provider, provider)
                )
                return "direct"

        return mode

    def _load_terminal_responses(self, path: Path) -> "Dict[str, Dict[str, Any]]":
        """Terminal response records by sample_id. Mirrors
        common.load_resume_state, with one repair-specific difference:
        ModelRefusal is TERMINAL (a refusal of a repair request ends the
        sample as repair_unusable — retrying refusals forever would stall
        the wave), while transport/API errors stay retryable and are
        dropped for the next attempt."""
        if not path.exists():
            return {}

        terminal: Dict[str, Dict[str, Any]] = {}
        kept_lines: List[str] = []
        dropped = 0

        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    dropped += 1
                    continue

                success = (record.get("status") or {}).get("success") is True
                refusal = (record.get("status") or {}).get("error_type") == "ModelRefusal"

                if record.get("sample_id") and (success or refusal):
                    terminal[record["sample_id"]] = record
                    kept_lines.append(line if line.endswith("\n") else line + "\n")
                else:
                    dropped += 1

        if dropped:
            with path.open("w", encoding="utf-8") as handle:
                handle.writelines(kept_lines)
            self.log(
                "dropped %d failed response record(s) for retry" % dropped
            )

        return terminal

    def build_response_record(
        self,
        base_record: Dict[str, Any],
        request: Dict[str, Any],
        generation_parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """generation.v2-shaped record so assemble_sources consumes it
        unchanged. prompt.prompt_text stays the ORIGINAL task prompt: the
        assembly cleaning is prompt-aware (signature dedupe, include
        relocation), and iteration files must assemble byte-consistently
        with iteration 0. The repair request itself is persisted in
        requests.jsonl; the record carries the repair identity."""
        record = common.build_empty_record(
            run_id=self.paths.iter_run_id(int(request["iteration"])),
            model_config=self.model_config,
            prompt=dict(base_record["prompt"]),
            prompt_field="prompt_text",
            sample_index=(base_record.get("generation_parameters") or {}).get(
                "sample_index", 0
            ),
            generation_parameters=generation_parameters,
        )

        # make_sample_id reproduces the base id from the same prompt fields;
        # assert instead of assuming (identity is sample_id x variant x
        # iteration — variant/iteration live in the run id, the sample_id
        # NEVER changes across iterations).
        record["sample_id"] = request["sample_id"]
        record["prompt"] = dict(base_record["prompt"])
        record["repair"] = {
            "variant": self.variant,
            "iteration": request["iteration"],
            "strategy": request["strategy"],
            "built_from_iteration": request["built_from_iteration"],
            "request_chars": request["request_chars"],
        }

        return record

    def _submit(self, target_iteration: int) -> str:
        mode = self.api_mode()

        if mode == "direct":
            return self._submit_direct(target_iteration)

        return self._submit_batch(target_iteration)

    def _finish_responses(self, target_iteration: int) -> str:
        """Shared completion check for direct and batch merge: every
        requested sample needs a TERMINAL response; refusals become
        repair_unusable here."""
        generations_path = self.paths.iter_generations_path(target_iteration)
        terminal = self._load_terminal_responses(generations_path)
        requests = self.load_requests(target_iteration)

        missing = [r["sample_id"] for r in requests if r["sample_id"] not in terminal]

        for sample_id, record in terminal.items():
            if (record.get("status") or {}).get("error_type") == "ModelRefusal":
                self.mark_unusable(
                    sample_id,
                    target_iteration,
                    "model refused the repair request",
                )

        if missing:
            self.log(
                "iteration %d: %d response(s) still missing after retries — "
                "re-run run_repair.py to retry" % (target_iteration, len(missing))
            )
            return OUTCOME_BLOCKED_API

        self.save_wave_state(target_iteration, "responses_merged")
        self.log(
            "iteration %d: all %d response(s) merged"
            % (target_iteration, len(requests))
        )
        return OUTCOME_ADVANCED

    def _submit_direct(self, target_iteration: int) -> str:
        generations_path = self.paths.iter_generations_path(target_iteration)
        terminal = self._load_terminal_responses(generations_path)
        requests = self.load_requests(target_iteration)
        todo = [r for r in requests if r["sample_id"] not in terminal]

        if todo:
            provider = self.model_config["provider"]
            adapter = self._adapter_factory(provider)
            api_key = common.get_api_key(self.model_config, adapter.default_api_key_env)
            client = adapter.create_client(self.model_config, api_key)

            generation_defaults = self.config.get("generation_defaults", {})
            system_prompt = common.get_required_system_prompt(generation_defaults)
            retry_attempts = int(
                common.get_param(
                    self.model_config, generation_defaults, "retry_attempts", 2
                )
            )
            sleep_seconds = float(
                common.get_param(
                    self.model_config,
                    generation_defaults,
                    "sleep_seconds_between_requests",
                    0.0,
                )
            )
            generation_parameters = adapter.generation_parameters(
                self.model_config, generation_defaults
            )
            base_records = self.load_base_generation_records()

            self.log(
                "iteration %d: submitting %d repair request(s) (direct)"
                % (target_iteration, len(todo))
            )

            for index, request in enumerate(todo):
                record = self.build_response_record(
                    base_records[request["sample_id"]], request, generation_parameters
                )

                started = time.time()

                try:
                    result = adapter.generate(
                        client=client,
                        model_config=self.model_config,
                        generation_defaults=generation_defaults,
                        system_prompt=system_prompt,
                        messages=[{"role": "user", "content": request["request"]}],
                        retry_attempts=retry_attempts,
                        sleep_seconds=sleep_seconds,
                    )
                    record["output"]["raw_text"] = result.raw_text
                    record["output"]["cleaned_code"] = common.clean_generated_code(
                        result.raw_text
                    )
                    record["output"]["finish_reason"] = result.finish_reason
                    record["api_response"]["response_id"] = result.response_id
                    # prompt/completion token usage per request — the basis
                    # of the cost section (design §8)
                    record["api_response"]["usage"] = result.usage
                    record["status"]["success"] = True
                    record["status"]["truncated"] = result.truncated
                    outcome = "ok"
                except common.ModelRefusal as refusal:
                    record["status"]["error_type"] = "ModelRefusal"
                    record["status"]["error_message"] = str(refusal)
                    record["output"]["finish_reason"] = "refusal"
                    outcome = "refused"
                except Exception as error:  # transport/API: retryable on rerun
                    record["status"]["error_type"] = type(error).__name__
                    record["status"]["error_message"] = str(error)
                    outcome = "error"

                record["status"]["duration_seconds"] = round(time.time() - started, 3)
                common.append_jsonl(generations_path, record)
                self.log(
                    "  [%d/%d] %s: %s"
                    % (index + 1, len(todo), request["sample_id"], outcome)
                )

        return self._finish_responses(target_iteration)

    # -- batch mode (Teil 3) ----------------------------------------------

    def _submit_batch(self, target_iteration: int) -> str:
        from thesis.repair import batch_api

        info_path = self.paths.batch_info_path(target_iteration)

        if info_path.exists():
            # already submitted (resume): go straight to polling
            return self._poll_batch(target_iteration)

        generations_path = self.paths.iter_generations_path(target_iteration)
        terminal = self._load_terminal_responses(generations_path)
        requests = [
            r
            for r in self.load_requests(target_iteration)
            if r["sample_id"] not in terminal
        ]

        if not requests:
            return self._finish_responses(target_iteration)

        provider = self.model_config["provider"]
        generation_defaults = self.config.get("generation_defaults", {})
        system_prompt = common.get_required_system_prompt(generation_defaults)

        batch_info = batch_api.submit_batch(
            provider=provider,
            model_config=self.model_config,
            generation_defaults=generation_defaults,
            system_prompt=system_prompt,
            requests=[(r["sample_id"], r["request"]) for r in requests],
        )
        batch_info["provider"] = provider
        batch_info["iteration"] = target_iteration
        batch_info["sample_ids"] = [r["sample_id"] for r in requests]
        batch_info["submitted_at_utc"] = common.utc_now_iso()

        common.write_json(info_path, batch_info)
        self.save_wave_state(target_iteration, "submitted", batch=batch_info)

        self.log(
            "iteration %d: batch %s submitted (%d request(s)) — poll with "
            "run_repair.py --poll"
            % (target_iteration, batch_info.get("batch_id"), len(requests))
        )
        return OUTCOME_BLOCKED_BATCH

    def _poll_batch(self, target_iteration: int) -> str:
        from thesis.repair import batch_api

        info_path = self.paths.batch_info_path(target_iteration)

        if not info_path.exists():
            # nothing submitted yet (e.g. crash between requests_built and
            # submit) — go back through submit
            return self._submit_batch(target_iteration)

        with info_path.open("r", encoding="utf-8") as handle:
            batch_info = json.load(handle)

        status = batch_api.poll_batch(
            provider=batch_info["provider"],
            model_config=self.model_config,
            batch_info=batch_info,
        )

        if status.state == "running":
            self.log(
                "iteration %d: batch %s still %s"
                % (target_iteration, batch_info.get("batch_id"), status.detail)
            )
            return OUTCOME_BLOCKED_BATCH

        if status.state == "failed":
            # Terminal batch failure: drop the batch info so the next run
            # resubmits the still-unanswered requests (logged, not silent).
            self.log(
                "iteration %d: batch %s FAILED (%s) — will resubmit on next "
                "run" % (target_iteration, batch_info.get("batch_id"), status.detail)
            )
            info_path.unlink()
            return OUTCOME_BLOCKED_BATCH

        # completed: merge responses into the iteration generations file
        generations_path = self.paths.iter_generations_path(target_iteration)
        terminal = self._load_terminal_responses(generations_path)
        base_records = self.load_base_generation_records()
        requests_by_id = {
            r["sample_id"]: r for r in self.load_requests(target_iteration)
        }
        generation_parameters = {"api_mode": "batch", "batch_id": batch_info.get("batch_id")}

        merged = 0
        for sample_id, response in status.responses.items():
            if sample_id in terminal or sample_id not in requests_by_id:
                continue

            record = self.build_response_record(
                base_records[sample_id], requests_by_id[sample_id], generation_parameters
            )

            if response.error_type == "ModelRefusal":
                record["status"]["error_type"] = "ModelRefusal"
                record["status"]["error_message"] = response.error_message or ""
                record["output"]["finish_reason"] = "refusal"
            elif response.error_type:
                record["status"]["error_type"] = response.error_type
                record["status"]["error_message"] = response.error_message or ""
            else:
                record["output"]["raw_text"] = response.raw_text
                record["output"]["cleaned_code"] = common.clean_generated_code(
                    response.raw_text or ""
                )
                record["output"]["finish_reason"] = response.finish_reason
                record["api_response"]["response_id"] = response.response_id
                record["api_response"]["usage"] = response.usage
                record["status"]["success"] = True
                record["status"]["truncated"] = response.truncated

            record["repair"]["batch_id"] = batch_info.get("batch_id")
            common.append_jsonl(generations_path, record)
            merged += 1

        # per-sample batch attribution lives in batch.json (sample_ids) and
        # on each merged response record (repair.batch_id)
        self.log(
            "iteration %d: batch %s completed, %d response(s) merged"
            % (target_iteration, batch_info.get("batch_id"), merged)
        )

        return self._finish_responses(target_iteration)

    # -- assembly ---------------------------------------------------------

    def _assemble(self, target_iteration: int) -> str:
        from thesis.assembly import assemble_sources

        # Synthetic profile: assemble_model keys everything on run_id, so
        # the iteration run id routes it to the iteration artifacts — the
        # NORMAL assembly cleaning, not a copy (design §4: repair answers
        # go through the same cleaning as initial generations).
        profile = {"run_id": self.paths.iter_run_id(target_iteration)}

        assemble_sources.assemble_model(
            config=self.config,
            profile=profile,
            model_config=self.model_config,
            export_pareval_json=False,
        )

        entries = self.load_assembly_entries(target_iteration)

        for sample_id, entry in entries.items():
            if not entry.get("assembled"):
                self.mark_unusable(
                    sample_id,
                    target_iteration,
                    "repair answer not assembled (%s)"
                    % entry.get("skip_reason", "unknown"),
                )

        assembled = [s for s, e in entries.items() if e.get("assembled")]

        if not assembled:
            # every response was unusable — the loop ends for these samples
            self.save_wave_state(target_iteration, "decided")
            self.log(
                "iteration %d: no assemblable responses — wave ends"
                % target_iteration
            )
            return OUTCOME_DECIDED

        self.save_wave_state(target_iteration, "assembled")
        self.log(
            "iteration %d: %d sample(s) assembled" % (target_iteration, len(assembled))
        )
        return OUTCOME_ADVANCED

    # -- driving ----------------------------------------------------------

    def step(self) -> str:
        state = self.load_wave_state()
        phase = state["phase"]
        iteration = int(state["iteration"])

        if phase == "done":
            return OUTCOME_DONE

        if phase == "start":
            return self._to_analyzed(0)

        if phase == "analyzed_waiting_external":
            return self._to_analyzed(iteration)

        if phase == "analyzed":
            return self._decide(iteration)

        if phase == "decided":
            actives = self.active_samples()
            if not actives:
                self.save_wave_state(iteration, "done")
                self.log("loop finished (no active samples left)")
                return OUTCOME_DONE
            return self._build_requests(iteration + 1)

        if phase == "requests_built":
            return self._submit(iteration)

        if phase == "submitted":
            return self._poll_batch(iteration)

        if phase == "responses_merged":
            return self._assemble(iteration)

        if phase == "assembled":
            return self._to_analyzed(iteration)

        raise ValueError("unknown wave phase '%s'" % phase)

    def run(self, max_waves: Optional[int] = None) -> str:
        """Drive the loop until done or blocked (never busy-waits). A wave
        counts as completed when a decide transition finishes."""
        waves = 0

        while True:
            outcome = self.step()

            if outcome == OUTCOME_DONE:
                return outcome

            if outcome in BLOCKED_OUTCOMES:
                return outcome

            if outcome == OUTCOME_DECIDED:
                waves += 1
                if max_waves is not None and waves >= max_waves:
                    self.log("--max-wave %d reached, stopping" % max_waves)
                    return outcome

    # -- reporting --------------------------------------------------------

    def status_row(self) -> Dict[str, Any]:
        wave = self.load_wave_state()
        states = self.sample_states()
        by_status: Counter = Counter(s.get("status") for s in states.values())

        pending_external = 0
        if wave["phase"] == "analyzed_waiting_external":
            pending_external = sum(
                count for _, count in self.pending_external(int(wave["iteration"]))
            )

        batch = wave.get("batch") or {}

        return {
            "model_id": self.model_id,
            "variant": self.variant,
            "iteration": int(wave["iteration"]),
            "phase": wave["phase"],
            "active": by_status.get(STATUS_ACTIVE, 0),
            "stopped_clean": by_status.get(STATUS_CLEAN, 0),
            "stopped_tests_pass": by_status.get(STATUS_TESTS_PASS, 0),
            "stopped_budget": by_status.get(STATUS_BUDGET, 0),
            "repair_unusable": by_status.get(STATUS_UNUSABLE, 0),
            "pending_external": pending_external,
            "batch_id": batch.get("batch_id"),
        }

    def dry_run(self) -> None:
        """Build (in memory) what the next wave would send: request count,
        total characters, and a rough token estimate. Writes nothing."""
        wave = self.load_wave_state()
        phase = wave["phase"]
        iteration = int(wave["iteration"])

        if phase in ("start",):
            self.log(
                "dry-run: iteration 0 not analyzed yet — run the orchestrator "
                "once (analysis is local compute, no API cost) to get request "
                "estimates"
            )
            return

        if phase == "analyzed":
            actives = [
                sample_id
                for sample_id, prior, decision in self.compute_decisions(iteration)
                if decision.status == STATUS_ACTIVE
            ]
            # carry over samples already active from earlier decisions
            target = iteration + 1
        elif phase in ("decided", "requests_built"):
            actives = self.active_samples()
            target = iteration + 1 if phase == "decided" else iteration
        else:
            self.log(
                "dry-run: phase '%s' — no request building pending" % phase
            )
            return

        if not actives:
            self.log("dry-run: no active samples — nothing would be sent")
            return

        requests = self.build_request_records(target, actives)
        total_chars = sum(r["request_chars"] for r in requests)

        self.log(
            "dry-run: iteration %d would send %d request(s), %d chars total "
            "(~%d tokens at 4 chars/token), api_mode=%s"
            % (
                target,
                len(requests),
                total_chars,
                total_chars // 4,
                self.api_mode(),
            )
        )
