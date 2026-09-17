"""Content-addressed pins for the pre-start enforcement code (pilot_002
blocker-resolution wave, 2026-09-16).

The final environment gate of pilot_002 found two productive defects that NO
existing methodology condition had bound: the stage-runtime presence check
(thesis/evaluation/stage_runtime.py demanded an `mpi` tool identity the
productive probe never measures) and the dynamic tools' false-clean path
(thesis/evaluation/dynamic_tools.py persisted an abnormal launch exit as a
clean analysis). Neither file was hashed by any condition - the static
condition hashes framework.py / build_config.py / tool_config.py / tools.py,
the evaluation condition the correctness launch, nothing the stage
enforcement or the dynamic implementation. These two conditions close that
gap; the run contract and the methodology freeze bind their sha256.

    stage_runtime_enforcement.v1
        LF-normalized source of stage_runtime.py and probe_runtime_identity.py
        plus the canonical policy projection: STAGE_DOMAINS, REQUIRED_IDENTITIES,
        REQUIRED_EVIDENCE, the compared fields per observation mode, the
        runtime-environment field allowlist, the probe's role -> tools map and
        evidence producers, the split-invocation coverage policy version.

    dynamic_analysis_implementation.v1
        LF-normalized source of dynamic_tools.py and run_dynamic_analysis.py
        plus the result-semantics-relevant shared dependencies as the dynamic
        stage sees them (framework.py: ToolResult / tool-state derivation /
        verdict; build_config.py: launch; tool_config.py: tool settings) and
        the projected values the dynamic tools import from tools.py
        (DRIVER_PROBLEM_SIZE_DEFINE, mpi_include_flags source) plus the
        tool-state schema, the sanitizer/launch constants and the per-tool
        class policy (execution models, sanitize flags, launch grids, MUST
        timeouts). Deliberately NOT the whole repository.

Hash rule (both): condition_hashing.canonical_sha256 of the projection; file
hashes LF-normalized (condition_hashing.lf_normalized_sha256) under
repo-relative paths; no absolute paths, no timestamps, no host-dependent
values (the TSan OMP_TOOL_LIBRARIES entry is the installed archer library
PATH, host/image-dependent, and is therefore excluded here; the archer
library itself is part of the image identity the runtime condition pins).

Python 3.8 compatible.
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import condition_hashing as ch  # noqa: E402

STAGE_RUNTIME_ENFORCEMENT_VERSION = "stage_runtime_enforcement.v1"
DYNAMIC_ANALYSIS_IMPLEMENTATION_VERSION = "dynamic_analysis_implementation.v1"

STAGE_RUNTIME_ENFORCEMENT_FILES = (
    "thesis/evaluation/stage_runtime.py",
    "thesis/evaluation/probe_runtime_identity.py",
)

DYNAMIC_ANALYSIS_IMPLEMENTATION_FILES = (
    "thesis/evaluation/dynamic_tools.py",
    "thesis/evaluation/run_dynamic_analysis.py",
    "thesis/evaluation/framework.py",
    "thesis/evaluation/build_config.py",
    "thesis/evaluation/tool_config.py",
)

HASH_RULE = ("condition_hashing.canonical_sha256 (sort_keys, compact separators, ensure_ascii, "
             "default=str; SHA-256 over UTF-8) of the projection; file entries carry the "
             "LF-normalized SHA-256 under a repo-relative path")


def _file_entries(relatives: "Tuple[str, ...]") -> "list":
    return [ch.file_condition_entry(REPO_ROOT / relative) for relative in relatives]


# ---------------------------------------------------------------------------
# stage_runtime_enforcement.v1
# ---------------------------------------------------------------------------

def stage_runtime_enforcement_condition() -> "OrderedDict[str, Any]":
    from thesis.evaluation import probe_runtime_identity as pri
    from thesis.evaluation import stage_runtime as sr
    from thesis.evaluation import static_provenance as sp

    policy = OrderedDict([
        ("stage_runtime_evidence_version", sr.STAGE_RUNTIME_EVIDENCE_VERSION),
        ("stage_domains", OrderedDict(
            (stage, OrderedDict([("fragment_owner", owner), ("runtime_domains", list(domains))]))
            for stage, (owner, domains) in sr.STAGE_DOMAINS.items())),
        ("required_identities", OrderedDict(
            (domain, list(tools)) for domain, tools in sr.REQUIRED_IDENTITIES.items())),
        ("required_evidence", OrderedDict(
            (domain, list(keys)) for domain, keys in sr.REQUIRED_EVIDENCE.items())),
        ("presence_vs_drift", "REQUIRED_IDENTITIES / REQUIRED_EVIDENCE are presence checks "
                              "(StageRuntimeUnresolved); a present value that differs from the "
                              "T0 evidence is StageRuntimeDrift via domain_diff over the compared "
                              "fields - no second identity definition"),
        ("observation_modes", OrderedDict(
            (mode, list(fields)) for mode, fields in sorted(sr.COMPARED_FIELDS.items()))),
        ("runtime_condition_version", sp.RUNTIME_CONDITION_VERSION),
        ("runtime_environment_fields", list(sp.RUNTIME_ENVIRONMENT_FIELDS)),
        ("probe_role_tools", OrderedDict(
            (role, list(tools)) for role, tools in sorted(pri.ROLE_TOOLS.items()))),
        ("probe_evidence_producers", OrderedDict(
            (role, function.__name__) for role, function in sorted(pri.EVIDENCE.items()))),
        ("split_invocation_coverage_policy", sr.SPLIT_INVOCATION_COVERAGE_POLICY),
    ])
    return OrderedDict([
        ("condition_version", STAGE_RUNTIME_ENFORCEMENT_VERSION),
        ("files", _file_entries(STAGE_RUNTIME_ENFORCEMENT_FILES)),
        ("policy", policy),
        ("hash_rule", HASH_RULE),
    ])


def stage_runtime_enforcement_sha256() -> str:
    return ch.canonical_sha256(stage_runtime_enforcement_condition())


# ---------------------------------------------------------------------------
# dynamic_analysis_implementation.v1
# ---------------------------------------------------------------------------

def dynamic_analysis_implementation_condition() -> "OrderedDict[str, Any]":
    from thesis.evaluation import build_config as bc
    from thesis.evaluation import dynamic_tools as dt
    from thesis.evaluation import framework
    from thesis.evaluation import tools as tools_module

    asan = dt.AsanUbsanTool()
    tsan = dt.TsanTool()
    tool_policy = OrderedDict([
        ("asan_ubsan", OrderedDict([
            ("execution_models", list(dt.AsanUbsanTool.execution_models)),
            ("sanitize_flags", list(asan.sanitize_flags())),
            ("run_env", OrderedDict(sorted(asan.run_env().items()))),
        ])),
        ("tsan", OrderedDict([
            ("execution_models", list(dt.TsanTool.execution_models)),
            ("sanitize_flags", list(tsan.sanitize_flags())),
            # TSAN_OPTIONS is a constant; OMP_TOOL_LIBRARIES is the installed
            # archer PATH (host/image-dependent) - covered by the pinned image
            # identity of the runtime condition, not by this projection
            ("tsan_options", tsan.run_env().get("TSAN_OPTIONS")),
            ("compiler", "clang++"),
        ])),
        ("memcheck", OrderedDict([
            ("execution_models", list(dt.MemcheckTool.execution_models)),
            ("launch_params", dt.MemcheckTool.LAUNCH_PARAMS),
            ("valgrind_tool", dt.MemcheckTool.VALGRIND_TOOL),
        ])),
        ("must", OrderedDict([
            ("execution_models", list(dt.MustTool.execution_models)),
            ("launch_params", dt.MustTool.LAUNCH_PARAMS),
            ("must_timeout_seconds", dt.MustTool.MUST_TIMEOUT_SECONDS),
            ("mustrun", dt.MustTool.MUSTRUN),
            ("system_timeout_wrapper", dt.MustTool.SYSTEM_TIMEOUT),
        ])),
        ("helgrind", OrderedDict([("execution_models", list(dt.HelgrindTool.execution_models)),
                                  ("valgrind_tool", dt.HelgrindTool.VALGRIND_TOOL)])),
        ("drd", OrderedDict([("execution_models", list(dt.DrdTool.execution_models)),
                             ("valgrind_tool", dt.DrdTool.VALGRIND_TOOL)])),
    ])
    policy = OrderedDict([
        ("tool_state_schema_version", framework.TOOL_STATE_SCHEMA_VERSION),
        ("analysis_states", list(framework.ANALYSIS_STATES)),
        ("sanitizer_base_flags", list(dt.SANITIZER_BASE_FLAGS)),
        ("sanitizer_niter", dt.SANITIZER_NITER),
        ("output_cap_per_run", dt.OUTPUT_CAP_PER_RUN),
        ("abnormal_exit_gap", dt.ABNORMAL_EXIT_GAP),
        ("abnormal_exit_rule", "a launch is abnormal when it was killed by a signal (negative exit), "
                               "carries a crash signature no parser turns into a verdict, has a "
                               "missing/incomplete tool output, or exits non-zero without a tool report "
                               "(valgrind: never a report, its exit code is the client's); any abnormal "
                               "launch -> PARTIAL with findings, TOOL_ERROR without; timeouts keep "
                               "TIMEOUT; attribution and dedupe unchanged"),
        ("crash_signature_regex", dt.CRASH_SIGNATURE.pattern),
        ("driver_problem_size_define", tools_module.DRIVER_PROBLEM_SIZE_DEFINE),
        ("mpi_include_flags_source_sha256_lf_normalized",
         ch.lf_normalized_source_sha256(tools_module.mpi_include_flags)),
        ("default_launch_params", bc.DEFAULT_LAUNCH_PARAMS),
        ("model_driver_files", OrderedDict(sorted(bc.MODEL_DRIVER_FILES.items()))),
        ("tools", tool_policy),
    ])
    return OrderedDict([
        ("condition_version", DYNAMIC_ANALYSIS_IMPLEMENTATION_VERSION),
        ("files", _file_entries(DYNAMIC_ANALYSIS_IMPLEMENTATION_FILES)),
        ("policy", policy),
        ("hash_rule", HASH_RULE),
    ])


def dynamic_analysis_implementation_sha256() -> str:
    return ch.canonical_sha256(dynamic_analysis_implementation_condition())


def enforcement_conditions_view() -> "OrderedDict[str, Any]":
    """Both pins with their versions - the block the run contract's
    conditions_view and the methodology freeze embed."""
    return OrderedDict([
        ("stage_runtime_enforcement_condition_version", STAGE_RUNTIME_ENFORCEMENT_VERSION),
        ("stage_runtime_enforcement_condition_sha256", stage_runtime_enforcement_sha256()),
        ("dynamic_analysis_implementation_condition_version", DYNAMIC_ANALYSIS_IMPLEMENTATION_VERSION),
        ("dynamic_analysis_implementation_condition_sha256", dynamic_analysis_implementation_sha256()),
    ])


def main() -> int:
    import json

    print(json.dumps(OrderedDict([
        ("stage_runtime_enforcement", stage_runtime_enforcement_condition()),
        ("dynamic_analysis_implementation", dynamic_analysis_implementation_condition()),
        ("view", enforcement_conditions_view()),
    ]), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
