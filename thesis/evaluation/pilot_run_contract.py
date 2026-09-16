"""Pilot run contract (pilot_run_contract.v3) - builder, freeze, T0 guard.

The contract is the frozen, content-addressed description of the run that
is about to start: WHICH population, WHICH models, WHICH conditions. It is
built from the config profile and the pinned artifacts, frozen to a file
with its sha, bound to the run's provenance (manifest fragment) at T0, and
compared post-run by verify_pilot_run.py.

    T0 flow
      1. build_contract()  -> status READY / NOT_READY (+ blockers)
      2. freeze_contract() -> <path>, FROZEN_CONTRACT_SHA (refuses NOT_READY)
      3. t0_guard()        -> immediately before the first cost-causing
                              request: rebuild from the live state, compare
                              with the frozen sha; any drift -> START_REFUSED;
                              on match the contract sha and the runtime
                              evidence are registered in the run manifest
                              BEFORE any request is made

v3 (pilot_002 population + final methodology/run freeze, 2026-09-13) binds
the final decisions content-addressed: the methodology freeze sha, the
population sha (exact benchmarks, prompt keys and hashes, model set, samples
per prompt), the publication policy sha, the reuse policy, the base run id
and the methodical override plan (NONE). The builder is FAIL-CLOSED: an open
decision, a stale/missing freeze artifact, a population or model-set
mismatch, a non-empty override plan, a NOT_READY readiness artifact or a
missing condition pin is a blocker, never an informative note.

Hash classes: repository POLICY/IMPLEMENTATION artifacts are pinned
LF-normalized (checkout-independent); frozen evidence files (specs) by raw
bytes; prompts by the per-prompt UTF-8 rule of the cross-pilot gate.

    python thesis/evaluation/pilot_run_contract.py build --config thesis/config/config.yaml --profile pilot
    python thesis/evaluation/pilot_run_contract.py freeze ... --out <contract.json>
    python thesis/evaluation/pilot_run_contract.py t0 ... --frozen <contract.json> [--no-bind]

Python 3.8 compatible.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.config.load_config import load_config  # noqa: E402
from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import condition_hashing as ch  # noqa: E402

# v2 adds the two derivation inputs the EXPECTED RUNTIME STAGE MATRIX needs -
# `static_toolset` (which static tools are contracted, with their effective
# execution-model scope) and `repair_plan`. Before v2 the post-run verifier
# could only derive `static.main` from `static_analysis`, so a contracted
# PARCOACH/LLOV/repair-evaluation run without a runtime stamp was never
# reported as UNRESOLVED. Both fields are FROZEN with the contract, so a later
# config edit is contract drift instead of a silently changed expectation.
# v3 (pilot_002 freeze) adds `base_run`, `population_freeze`,
# `selected_prompt_hashes`, `reuse_policy`, `publication_policy`,
# `methodology_freeze`, `methodical_override_plan` and the E3.2 / technical
# provenance pins in `conditions` - every final methodical decision is bound
# by its content hash and every open decision is a blocker (never a note).
CONTRACT_SCHEMA_VERSION = "pilot_run_contract.v3"
POST_RUN_VERIFIER_VERSION = "verify_pilot_run.v1"

CROSS_PILOT_PATH = REPO_ROOT / "thesis" / "evaluation" / "cross_pilot_comparability.json"
SEMANTIC_DECISIONS_PATH = REPO_ROOT / "thesis" / "evaluation" / "semantic_decisions_pilot002.json"
READINESS_PATH = REPO_ROOT / "thesis" / "evaluation" / "static_repair_readiness.json"
FROZEN_SPECS_PATH = REPO_ROOT / "thesis" / "enhanced_tests" / "frozen" / "e3_final_specs.jsonl"
ENHANCED_POLICY_PATH = REPO_ROOT / "thesis" / "enhanced_tests" / "enhanced_policy.json"
HISTORICAL_PILOT_RUN_ID = "pilot_001"

STATUS_READY = "READY"
STATUS_NOT_READY = "NOT_READY"
START_ALLOWED = "START_ALLOWED"
START_REFUSED = "START_REFUSED"

# Fields that are NOT part of the contract sha (volatile / derived)
UNHASHED_FIELDS = ("built_at_utc", "builder", "status", "blockers", "contract_sha256")


class ContractNotReady(RuntimeError):
    """The contract cannot be frozen (open decisions or missing pins)."""


class ContractDrift(RuntimeError):
    """The live state no longer matches the frozen contract."""


def _load_json(path: Path) -> "Optional[Dict[str, Any]]":
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _utc_now() -> str:
    from thesis.generation.common import utc_now_iso

    return utc_now_iso()


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def population_view(config: Dict[str, Any], profile: Dict[str, Any]) -> "OrderedDict[str, Any]":
    """The population the run would generate: selection parameters, the
    per-prompt hash map (the gate's rule) and the expected sample count."""
    from thesis.generation import common

    prompts_cfg = config.get("prompts") or {}
    prompts_path = Path(prompts_cfg.get("path") or "thesis/prompts/generation-prompts-thesis.json")
    if not prompts_path.is_absolute():
        prompts_path = REPO_ROOT / prompts_path
    execution_models = prompts_cfg.get("execution_models")
    problem_types = prompts_cfg.get("problem_types")
    prompt_limit = profile.get("prompt_limit")
    selection = profile.get("selection", "prefix")
    num_samples = profile.get("num_samples_per_prompt")

    prompts = _load_json(prompts_path)
    prompt_hashes: "OrderedDict[str, str]" = OrderedDict()
    expected_prompts = None
    selected_keys: "List[str]" = []
    error = None
    if isinstance(prompts, list):
        for entry in prompts:
            key = "%s|%s|%s" % (entry.get("problem_type"), entry.get("name"),
                                entry.get("parallelism_model"))
            prompt_hashes[key] = ch.utf8_sha256(entry.get(prompts_cfg.get("prompt_field", "prompt")) or "")
        try:
            selected, _info = common.select_prompts(prompts, execution_models, problem_types,
                                                    prompt_limit, selection)
            selected_keys = sorted("%s|%s|%s" % (e.get("problem_type"), e.get("name"),
                                                 e.get("parallelism_model")) for e in selected)
            expected_prompts = len(selected)
        except Exception as exc:  # noqa: BLE001 - reported as a blocker
            error = "%s: %s" % (type(exc).__name__, exc)
    else:
        error = "prompt file missing or not a list: %s" % prompts_path
    expected_samples = (expected_prompts * int(num_samples)
                        if expected_prompts is not None and num_samples else None)
    return OrderedDict([
        ("selection", selection),
        ("prompt_limit", prompt_limit),
        ("num_samples_per_prompt", num_samples),
        ("execution_models", execution_models),
        ("problem_types", problem_types),
        ("prompts_path", ch.repo_relative(prompts_path)),
        ("prompt_set_sha256", ch.canonical_sha256(prompt_hashes)),
        ("prompt_count", len(prompt_hashes)),
        # the per-prompt map: the post-run verifier compares the text each
        # generation record was produced from against THIS map, so a prompt
        # edited between freeze and run is detectable per record
        ("prompt_hashes", prompt_hashes),
        ("selected_prompt_keys", selected_keys),
        ("expected_prompt_count", expected_prompts),
        ("expected_sample_count", expected_samples),
        ("error", error),
    ])


def conditions_view(config: Dict[str, Any], primary_compiler: str) -> "OrderedDict[str, Any]":
    from thesis.assembly import assembly_provenance as ap
    from thesis.evaluation.check_cross_pilot_gate import (
        canon_sha256, evaluation_condition_projection, generation_condition_projection)

    # `outputs.readiness_artifact` lets a fixture pin its own readiness proof;
    # production has no such key and reads the repository artifact
    readiness_path = ((config or {}).get("outputs") or {}).get("readiness_artifact")
    readiness = _load_json(Path(readiness_path) if readiness_path else READINESS_PATH) or {}
    from thesis.evaluation import pilot_freeze
    from thesis.evaluation import static_provenance

    # every pinned artifact is bound by its RECOMPUTED self-hash: a stored
    # self-hash that does not reproduce (edited without recomputation) pins
    # None, which the builder turns into a blocker - never a copied string
    cross_doc = _load_json(pilot_freeze.cross_pilot_path(config))
    cross = cross_doc if isinstance(cross_doc, dict) else {}
    cross_fp = pilot_freeze.cross_pilot_fingerprint(cross_doc)
    decisions = _load_json(SEMANTIC_DECISIONS_PATH) or {}
    e3_confirmation_pin = pilot_freeze.pinned_artifact(pilot_freeze.E3_2_CONFIRMATION_PATH,
                                                       "confirmation_sha256")
    e3_decisions_pin = pilot_freeze.pinned_artifact(pilot_freeze.E3_2_DECISIONS_PATH, "decisions_sha256")
    technical_pin = pilot_freeze.pinned_artifact(pilot_freeze.TECHNICAL_PROVENANCE_PATH, "artifact_sha256")
    e3_confirmation = e3_confirmation_pin["document"] or {}
    e3_decisions = e3_decisions_pin["document"] or {}
    technical = technical_pin["document"] or {}
    # the readiness artifact's static / repair conditions must reproduce from
    # the current repository state (a stale READY artifact is not a proof)
    readiness_stale: "List[str]" = []
    try:
        static_now = static_provenance.static_analysis_condition_sha256(
            static_provenance.static_analysis_condition(config, primary_compiler, None,
                                                        include_identities=False))
        repair_now = static_provenance.repair_condition_sha256(static_provenance.repair_condition(config))
    except Exception as exc:  # noqa: BLE001 - reported, never invented
        static_now = repair_now = None
        readiness_stale.append("static/repair conditions not recomputable: %s: %s" % (type(exc).__name__, exc))
    if readiness:
        if static_now is not None and readiness.get("static_analysis_condition_sha256") != static_now:
            readiness_stale.append("readiness static condition %s... != current %s..."
                                   % (str(readiness.get("static_analysis_condition_sha256"))[:12], static_now[:12]))
        if repair_now is not None and readiness.get("repair_condition_sha256") != repair_now:
            readiness_stale.append("readiness repair condition %s... != current %s..."
                                   % (str(readiness.get("repair_condition_sha256"))[:12], repair_now[:12]))
        if readiness.get("runtime_fully_pinned") is not True:
            readiness_stale.append("readiness runtime is not fully pinned")
    try:
        generation_sha = canon_sha256(generation_condition_projection())
    except Exception as exc:  # noqa: BLE001
        generation_sha = None
    try:
        evaluation_sha = canon_sha256(evaluation_condition_projection())
    except Exception as exc:  # noqa: BLE001
        evaluation_sha = None
    policy = _load_json(ENHANCED_POLICY_PATH) or {}
    return OrderedDict([
        ("generation_condition_sha256", generation_sha),
        ("assembly_condition_version", ap.ASSEMBLY_CONDITION_VERSION),
        ("assembly_condition_sha256", ap.assembly_condition_sha256(ap.assembly_condition(config))),
        ("generation_cleaning_condition_sha256",
         ap.generation_cleaning_condition_sha256(ap.generation_cleaning_condition())),
        ("evaluation_condition_sha256", evaluation_sha),
        ("enhanced_frozen_specs_sha256", ch.raw_sha256(FROZEN_SPECS_PATH)),
        ("enhanced_frozen_specs_path", ch.repo_relative(FROZEN_SPECS_PATH)),
        ("enhanced_policy_sha256_lf_normalized", ch.lf_normalized_sha256(ENHANCED_POLICY_PATH)),
        ("enhanced_policy_status", policy.get("status")),
        ("static_analysis_condition_sha256", readiness.get("static_analysis_condition_sha256")),
        ("repair_condition_sha256", readiness.get("repair_condition_sha256")),
        ("static_repair_runtime_condition_sha256", readiness.get("runtime_condition_sha256")),
        ("static_repair_readiness_gate", readiness.get("gate")),
        ("static_repair_readiness_schema", readiness.get("schema_version")),
        ("semantic_decisions_sha256_lf_normalized", ch.lf_normalized_sha256(SEMANTIC_DECISIONS_PATH)),
        ("semantic_decisions_counts", OrderedDict([
            ("resolved", decisions.get("resolved_count")),
            ("accepted_disclosure", decisions.get("disclosure_count")),
            ("unresolved", decisions.get("unresolved_count"))])),
        ("cross_pilot_artifact_sha256", cross_fp["recomputed"] if cross_fp["reproduces"] else None),
        ("cross_pilot_artifact_path", ch.repo_relative(pilot_freeze.cross_pilot_path(config))),
        ("cross_pilot_state_commit", cross.get("state_commit")),
        ("timing_contract_sha256", _timing_sha()),
        # v3: the E3.2 author confirmation, the E3.2 decisions and the technical
        # provenance cleanup are pinned directly by their RECOMPUTED self-hash
        ("e3_2_author_confirmation_sha256",
         e3_confirmation_pin["recomputed"] if e3_confirmation_pin["reproduces"] else None),
        ("e3_2_decisions_sha256", e3_decisions_pin["recomputed"] if e3_decisions_pin["reproduces"] else None),
        ("e3_2_decision", e3_decisions.get("E3_2_DECISION")),
        ("e3_2_author_choices", e3_confirmation.get("choices_short")),
        ("technical_provenance_cleanup_sha256",
         technical_pin["recomputed"] if technical_pin["reproduces"] else None),
        ("technical_provenance_cleanup_status",
         (technical.get("flags") or {}).get("TECHNICAL_PROVENANCE_CLEANUP")),
        ("readiness_artifact_path", ch.repo_relative(Path(readiness_path) if readiness_path else READINESS_PATH)),
        ("pins_not_reproducing", [name for name, ok in (
            ("cross_pilot_artifact_sha256", cross_fp["reproduces"] or cross_doc is None),
            ("e3_2_author_confirmation_sha256", e3_confirmation_pin["reproduces"] or not e3_confirmation_pin["present"]),
            ("e3_2_decisions_sha256", e3_decisions_pin["reproduces"] or not e3_decisions_pin["present"]),
            ("technical_provenance_cleanup_sha256", technical_pin["reproduces"] or not technical_pin["present"]))
            if not ok]),
        ("readiness_stale", readiness_stale),
        ("primary_compiler", primary_compiler),
    ])


def _timing_sha() -> "Optional[str]":
    try:
        from thesis.evaluation import timing_semantics

        return timing_semantics.timing_contract_sha256()
    except Exception:  # noqa: BLE001
        return None


def expected_stages(config: Dict[str, Any]) -> "List[str]":
    stages = config.get("stages") or {}
    order = ["generation", "assembly", "correctness_tests", "static_analysis",
             "dynamic_analysis", "enhanced_tests", "repair"]
    result = []
    for name in order:
        settings = stages.get(name)
        if name in ("generation", "assembly") or (isinstance(settings, dict)
                                                  and settings.get("enabled", True)):
            result.append(name)
    return result


def static_toolset_view(config: Dict[str, Any]) -> "OrderedDict[str, Any]":
    """The contracted static toolset with each tool's EFFECTIVE execution-model
    scope (config ∩ hard capabilities), read through the productive resolver
    so the contract cannot disagree with the runner about what is enabled."""
    from thesis.evaluation.tool_config import resolve_tool_settings

    view: "OrderedDict[str, Any]" = OrderedDict()
    try:
        settings = resolve_tool_settings(config, "static_analysis")
    except Exception as exc:  # noqa: BLE001 - surfaces as a contract blocker
        return OrderedDict([("error", "%s: %s" % (type(exc).__name__, exc))])
    for name in sorted(settings):
        tool = settings[name]
        view[name] = OrderedDict([
            ("enabled", bool(tool.enabled)),
            ("execution_models", list(tool.execution_models)),
        ])
    return view


def dynamic_toolset_view(config: Dict[str, Any]) -> "OrderedDict[str, Any]":
    """The contracted DYNAMIC toolset with each tool's effective execution-model
    scope (the post-run verifier's dynamic coverage check and the override
    plan need it: a narrowed `--tools` is a methodical override)."""
    from thesis.evaluation.tool_config import resolve_tool_settings

    view: "OrderedDict[str, Any]" = OrderedDict()
    section = (config.get("stages") or {}).get("dynamic_analysis")
    if not isinstance(section, dict) or not section.get("enabled", False):
        return view
    try:
        settings = resolve_tool_settings(config, "dynamic_analysis")
    except Exception as exc:  # noqa: BLE001 - surfaces as a contract blocker
        return OrderedDict([("error", "%s: %s" % (type(exc).__name__, exc))])
    for name in sorted(settings):
        tool = settings[name]
        view[name] = OrderedDict([
            ("enabled", bool(tool.enabled)),
            ("execution_models", list(tool.execution_models)),
        ])
    return view


def repair_plan_view(config: Dict[str, Any]) -> "OrderedDict[str, Any]":
    """Whether the contract expects a repair loop AND therefore a repair
    EVALUATION (the loop re-runs correctness/static on repair candidates, so
    it produces records under a runtime that has to be stamped)."""
    section = (config.get("stages") or {}).get("repair")
    repair = section if isinstance(section, dict) else {}
    # the SAME default as expected_stages(): a present stage section without
    # `enabled` is enabled, an absent section is not - otherwise the builder
    # could freeze a contract that lists 'repair' among its expected stages
    # while its own repair plan says disabled
    enabled = isinstance(section, dict) and bool(section.get("enabled", True))
    plan = OrderedDict([("enabled", enabled)])
    if not enabled:
        plan["evaluates_repair_candidates"] = False
        return plan
    try:
        from thesis.repair import orchestrator

        settings = orchestrator.repair_settings(config)
        plan["variants"] = list(settings.get("variants") or [])
        plan["max_iterations"] = settings.get("max_iterations")
        plan["api_mode"] = settings.get("api_mode")
        # per-provider overrides decide the EFFECTIVE provider mode, so they
        # are frozen too: the verifier's pending-batch contradiction check
        # must know whether any batch path exists under this plan
        plan["api_mode_overrides"] = OrderedDict(sorted(
            (str(k), v) for k, v in (settings.get("api_mode_overrides") or {}).items()))
        plan["external_tools"] = list(settings.get("external_tools") or [])
    except Exception as exc:  # noqa: BLE001 - surfaces as a contract blocker
        plan["error"] = "%s: %s" % (type(exc).__name__, exc)
    # the repair loop always analyses its candidates with the base evaluation
    # stages; that is what makes a repair_evaluation runtime stamp mandatory
    plan["evaluates_repair_candidates"] = True
    return plan


def provenance_policies_view() -> "OrderedDict[str, Any]":
    """The provenance policies the post-run verifier applies to a run frozen
    with this contract (their versions, read from the productive modules)."""
    from thesis.evaluation import repair_scope, stage_runtime, writer_attribution

    return OrderedDict([
        ("writer_attribution", writer_attribution.REPAIR_WRITER_ATTRIBUTION_VERSION),
        ("iteration_zero_writer_attribution", repair_scope.ITERATION_ZERO_WRITER_ATTRIBUTION_POLICY),
        ("split_invocation_coverage", stage_runtime.SPLIT_INVOCATION_COVERAGE_POLICY),
    ])


def _iteration_like(run_id: "Optional[str]") -> bool:
    """`<base>__<variant>__iterN` - and every `__` variant suffix or `_iterN`
    tail - names a repair-iteration / variant population, never a base run
    (the same rule the preflight and run_freshness apply)."""
    import re

    value = run_id or ""
    return "__" in value or re.search(r"_iter\d*$", value) is not None


def build_contract(config_path: Path, profile_name: str,
                   run_id_override: "Optional[str]" = None,
                   primary_compiler: str = "g++") -> "OrderedDict[str, Any]":
    from thesis.evaluation import pilot_freeze
    from thesis.generation import common

    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    profile = common.get_profile(config, profile_name)
    run_id = run_id_override or profile.get("run_id")
    cross_doc = _load_json(pilot_freeze.cross_pilot_path(config))
    cross = cross_doc if isinstance(cross_doc, dict) else {}
    population_policy = cross.get("expected_pilot_002_population")
    population_policy = population_policy if isinstance(population_policy, dict) else {}
    base_run_policy = cross.get("expected_pilot_002_base_run")
    base_run_policy = base_run_policy if isinstance(base_run_policy, dict) else {}

    models = sorted(str(m.get("id")) for m in (config.get("models") or [])
                    if isinstance(m, dict) and m.get("enabled", False))
    population = population_view(config, profile)
    conditions = conditions_view(config, primary_compiler)
    stages = config.get("stages") or {}
    # the pilot_002 freeze: population / publication / methodology artifacts
    # with their integrity + staleness verdicts, the reuse decision and the
    # override plan - bound by content hash, every problem a blocker
    freeze_error = None
    try:
        freeze = pilot_freeze.freeze_state(config, profile_name, primary_compiler, config_path,
                                           run_id=run_id)
    except Exception as exc:  # noqa: BLE001 - a malformed artifact is a blocker, never a traceback
        freeze_error = "%s: %s" % (type(exc).__name__, exc)
        freeze = pilot_freeze.freeze_state_unresolved(config, freeze_error)

    contract = OrderedDict()
    contract["schema_version"] = CONTRACT_SCHEMA_VERSION
    contract["run_id"] = run_id
    contract["profile"] = profile_name
    contract["model_ids"] = models
    contract["population"] = population
    contract["execution_models"] = population["execution_models"]
    contract["primary_compiler"] = primary_compiler
    contract["run_timeout_seconds"] = (stages.get("correctness_tests") or {}).get("run_timeout_seconds")
    contract["enhanced_run_timeout_seconds"] = (stages.get("enhanced_tests") or {}).get("run_timeout_seconds")
    contract["generation_timeout_seconds"] = (config.get("generation_defaults") or {}).get("timeout_seconds")
    contract["conditions"] = conditions
    contract["expected_stages"] = expected_stages(config)
    # frozen derivation inputs of the EXPECTED RUNTIME STAGE MATRIX
    contract["static_toolset"] = static_toolset_view(config)
    contract["dynamic_toolset"] = dynamic_toolset_view(config)
    contract["repair_plan"] = repair_plan_view(config)
    # provenance policies the run is verified under (technical provenance
    # cleanup): a run frozen with them is expected to carry per-model
    # invocation histories and split-container invocation coverage
    contract["provenance_policies"] = provenance_policies_view()
    # ---- v3: the final decisions, bound by content hash -------------------
    pop = freeze["population"]
    contract["base_run"] = OrderedDict([
        ("run_id", run_id),
        ("expected_base_run_id", base_run_policy.get("run_id")),
        ("status", base_run_policy.get("status")),
        ("forbid_iteration_variants", base_run_policy.get("forbid_iteration_variants")),
        ("historical_baseline_run_id", HISTORICAL_PILOT_RUN_ID),
    ])
    contract["population_freeze"] = OrderedDict([
        ("path", pop["path"]), ("schema_version", pop["schema_version"]),
        ("sha256", pop["sha256"]), ("status", pop["status"]),
        ("population_source", pop["population_source"]),
        ("benchmark_count", pop["benchmark_count"]), ("prompt_count", pop["prompt_count"]),
        ("model_count", pop["model_count"]), ("samples_per_prompt", pop["samples_per_prompt"]),
        ("total_model_prompt_cells", pop["total_model_prompt_cells"]),
        ("execution_models", pop["execution_models"]),
        ("benchmark_ids", pop["benchmark_ids"]),
        ("prompt_key_set_sha256", pop["prompt_key_set_sha256"]),
        ("prompt_set_sha256", pop["prompt_set_sha256"]),
        ("policy_status", population_policy.get("status")),
        ("policy_population_sha256", population_policy.get("population_sha256")),
    ])
    # the EXACT selected prompt hashes (the frozen population, not the whole
    # prompt file): the verifier compares every generation record against it
    contract["selected_prompt_hashes"] = OrderedDict(
        (key, population["prompt_hashes"].get(key)) for key in population["selected_prompt_keys"])
    contract["reuse_policy"] = freeze["reuse"]
    contract["publication_policy"] = OrderedDict([
        ("path", freeze["publication"]["path"]),
        ("schema_version", freeze["publication"]["schema_version"]),
        ("sha256", freeze["publication"]["sha256"]),
        ("status", freeze["publication"]["status"]),
        ("policy", freeze["publication"]["policy"]),
        ("decided", freeze["publication"]["decided"]),
        ("publication_allowed_before_result_acceptance", False),
    ])
    contract["methodology_freeze"] = OrderedDict([
        ("path", freeze["methodology"]["path"]),
        ("schema_version", freeze["methodology"]["schema_version"]),
        ("sha256", freeze["methodology"]["sha256"]),
        ("status", freeze["methodology"]["status"]),
    ])
    contract["methodical_override_plan"] = freeze["override_plan"]
    contract["policy_state"] = OrderedDict([
        ("population_status", population_policy.get("status")),
        ("expected_base_run_status", base_run_policy.get("status")),
        ("expected_base_run_id", base_run_policy.get("run_id")),
        ("forbid_iteration_variants", base_run_policy.get("forbid_iteration_variants")),
        ("reuse_status", cross.get("reuse_status")),
        ("publication_status", (cross.get("publication_policy") or {}).get("status")
         if isinstance(cross.get("publication_policy"), dict) else None),
    ])
    contract["post_run_verifier_version"] = POST_RUN_VERIFIER_VERSION
    contract["post_run_verification_required_for_result_acceptance"] = True

    blockers: "List[str]" = []
    if freeze_error:
        blockers.append("freeze artifacts not verifiable: %s" % freeze_error)
    if not isinstance(cross_doc, dict):
        blockers.append("cross-pilot artifact missing or not a JSON object")
    if population_policy.get("status") != "DECIDED":
        blockers.append("pilot_002 population: %s" % (population_policy.get("status") or "UNKNOWN"))
    if base_run_policy.get("status") != "CONFIGURED":
        blockers.append("pilot_002 base run id: %s" % (base_run_policy.get("status") or "UNKNOWN"))
    elif base_run_policy.get("run_id") != run_id:
        blockers.append("run_id %r differs from the configured expected base run %r"
                        % (run_id, base_run_policy.get("run_id")))
    if run_id == HISTORICAL_PILOT_RUN_ID or (run_id or "").startswith(HISTORICAL_PILOT_RUN_ID + "__"):
        blockers.append("run_id %r is the historical pilot_001 run (or one of its iteration runs)" % run_id)
    if _iteration_like(run_id):
        blockers.append("run_id %r looks like a repair-iteration / variant run id; the base run must not be one" % run_id)
    if not models:
        blockers.append("no enabled models")
    all_ids = [str(m.get("id")) for m in (config.get("models") or []) if isinstance(m, dict)]
    duplicates = sorted({i for i in all_ids if all_ids.count(i) > 1})
    if duplicates:
        blockers.append("duplicate model id(s) in the configuration: %s" % ", ".join(duplicates))
    if run_id == pilot_freeze.PILOT_002_RUN_ID and models != sorted(pilot_freeze.PILOT_002_MODEL_IDS):
        blockers.append("the enabled model set %s is not the author-frozen pilot_002 model set (%d models)"
                        % (models, len(pilot_freeze.PILOT_002_MODEL_IDS)))
    if run_id == pilot_freeze.PILOT_002_RUN_ID and profile_name != pilot_freeze.PILOT_002_PROFILE:
        blockers.append("run %s is frozen under profile %s, not %r"
                        % (run_id, pilot_freeze.PILOT_002_PROFILE, profile_name))
    if population["error"]:
        blockers.append("population: %s" % population["error"])
    if population["expected_sample_count"] is None:
        blockers.append("expected sample count undetermined")
    # ---- v3 freeze blockers (fail-closed) ---------------------------------
    if not freeze["reuse"]["decided"]:
        blockers.append("reuse policy not decided: reuse_status %r / policy %r (expected %s / %s)"
                        % (freeze["reuse"]["reuse_status"], freeze["reuse"]["policy"],
                           pilot_freeze.REUSE_STATUS_DECIDED, pilot_freeze.REUSE_POLICY))
    if not freeze["publication"]["decided"]:
        blockers.append("publication policy not decided: %s (%s)"
                        % (freeze["publication"]["status"],
                           "; ".join(freeze["publication"]["problems"]) or "no DECIDED policy artifact"))
    if freeze["methodology"]["status"] != pilot_freeze.FRESH:
        blockers.append("methodology freeze %s: %s"
                        % (freeze["methodology"]["status"],
                           "; ".join(freeze["methodology"]["problems"]) or "artifact missing"))
    if freeze["population"]["status"] != pilot_freeze.FRESH:
        blockers.append("population freeze %s: %s"
                        % (freeze["population"]["status"],
                           "; ".join(freeze["population"]["problems"]) or "artifact missing"))
    else:
        if population_policy.get("status") == "DECIDED" and \
                population_policy.get("population_sha256") != pop["sha256"]:
            blockers.append("population sha mismatch: cross-pilot policy %s... vs artifact %s..."
                            % (str(population_policy.get("population_sha256"))[:12], str(pop["sha256"])[:12]))
        if sorted(pop["model_ids"] or []) != models:
            blockers.append("model set mismatch: frozen population %s vs enabled config models %s"
                            % (pop["model_ids"], models))
        frozen_keys = list((pop.get("prompt_hashes") or {}).keys())
        if sorted(frozen_keys) != sorted(population["selected_prompt_keys"]):
            blockers.append("selected prompt set mismatch between the frozen population and the "
                            "current selection")
        if any(population["prompt_hashes"].get(k) != h for k, h in (pop.get("prompt_hashes") or {}).items()):
            blockers.append("selected prompt text changed since the population freeze")
        if pop.get("total_model_prompt_cells") != (population["expected_sample_count"] or 0) * len(models):
            blockers.append("frozen cell count %s != expected samples x models %s"
                            % (pop.get("total_model_prompt_cells"),
                               (population["expected_sample_count"] or 0) * len(models)))
        if pop.get("population_source") != pilot_freeze.POPULATION_SOURCE:
            blockers.append("population source %r is not %s" % (pop.get("population_source"),
                                                                 pilot_freeze.POPULATION_SOURCE))
    if freeze["override_plan"]["planned"] != "NONE":
        blockers.append("methodical override plan is %s (planned overrides must be NONE, declared "
                        "and pinned)" % freeze["override_plan"]["planned"])
    if conditions.get("technical_provenance_cleanup_status") != "COMPLETE":
        blockers.append("technical provenance cleanup: %s"
                        % (conditions.get("technical_provenance_cleanup_status") or "MISSING"))
    if conditions.get("e3_2_decision") != "ACCEPTED":
        blockers.append("E3.2 decision: %s" % (conditions.get("e3_2_decision") or "MISSING"))
    for name in conditions.get("pins_not_reproducing") or []:
        blockers.append("pinned artifact edited without recomputation: %s does not reproduce from "
                        "its content" % name)
    for problem in conditions.get("readiness_stale") or []:
        blockers.append("static/repair readiness artifact stale: %s" % problem)
    if conditions["static_repair_readiness_gate"] != "READY":
        blockers.append("static/repair readiness gate: %s" % conditions["static_repair_readiness_gate"])
    for key in ("generation_condition_sha256", "generation_cleaning_condition_sha256",
                "assembly_condition_sha256", "evaluation_condition_sha256",
                "enhanced_frozen_specs_sha256", "enhanced_policy_sha256_lf_normalized",
                "static_analysis_condition_sha256", "repair_condition_sha256",
                "static_repair_runtime_condition_sha256", "timing_contract_sha256",
                "semantic_decisions_sha256_lf_normalized", "cross_pilot_artifact_sha256",
                "e3_2_author_confirmation_sha256", "e3_2_decisions_sha256",
                "technical_provenance_cleanup_sha256"):
        if not conditions.get(key):
            blockers.append("condition pin missing: %s" % key)
    unresolved_semantic = conditions["semantic_decisions_counts"].get("unresolved")
    if not isinstance(unresolved_semantic, int) or unresolved_semantic > 0:
        blockers.append("semantic decisions unresolved: %s" % (unresolved_semantic if unresolved_semantic is not None
                                                                 else "count missing"))
    # without a resolvable static toolset the expected runtime stage matrix
    # cannot decide whether PARCOACH/LLOV are contracted - a contract must
    # never be frozen in that state
    if not contract["static_toolset"] or "error" in contract["static_toolset"]:
        blockers.append("static toolset not resolvable: %s"
                        % (contract["static_toolset"].get("error")
                           if contract["static_toolset"] else "no tools configured"))
    if contract["repair_plan"].get("error"):
        blockers.append("repair plan not resolvable: %s" % contract["repair_plan"]["error"])
    if "error" in contract["dynamic_toolset"]:
        blockers.append("dynamic toolset not resolvable: %s" % contract["dynamic_toolset"]["error"])

    contract["status"] = STATUS_NOT_READY if blockers else STATUS_READY
    contract["blockers"] = blockers
    contract["built_at_utc"] = _utc_now()
    contract["builder"] = OrderedDict([("platform", sys.platform),
                                       ("python_version", platform.python_version())])
    contract["contract_sha256"] = contract_sha256(contract)
    return contract


def contract_sha256(contract: Dict[str, Any]) -> str:
    body = OrderedDict((k, v) for k, v in contract.items() if k not in UNHASHED_FIELDS)
    return ch.canonical_sha256(body)


# ---------------------------------------------------------------------------
# freeze / load / T0 guard
# ---------------------------------------------------------------------------

def freeze_contract(contract: Dict[str, Any], path: Path, allow_draft: bool = False) -> str:
    """Write the contract file; refuses a NOT_READY contract unless a draft
    is explicitly requested (a draft can never pass the T0 guard)."""
    if contract.get("status") != STATUS_READY and not allow_draft:
        raise ContractNotReady("contract is %s: %s" % (contract.get("status"),
                                                        "; ".join(contract.get("blockers") or [])))
    sha = contract_sha256(contract)
    payload = OrderedDict(contract.items())
    payload["contract_sha256"] = sha
    atomic_io.atomic_write_json(Path(path), payload)
    return sha


def load_frozen(path: Path) -> "Dict[str, Any]":
    """Load a frozen contract and verify its own integrity (stored sha ==
    recomputed sha of the stored content)."""
    frozen = _load_json(Path(path))
    if not frozen:
        raise ContractDrift("frozen contract missing or unreadable: %s" % path)
    stored = frozen.get("contract_sha256")
    recomputed = contract_sha256(frozen)
    if stored != recomputed:
        raise ContractDrift("frozen contract %s is corrupt: stored sha %s... != content sha %s..."
                            % (path, str(stored)[:12], recomputed[:12]))
    return frozen


def contract_diff(frozen: Dict[str, Any], rebuilt: Dict[str, Any]) -> "List[str]":
    """Dot-paths where the hashed content differs."""
    from thesis.evaluation.run_manifest import config_key_diff

    a = {k: v for k, v in frozen.items() if k not in UNHASHED_FIELDS}
    b = {k: v for k, v in rebuilt.items() if k not in UNHASHED_FIELDS}
    return config_key_diff(json.loads(json.dumps(a, default=str)), json.loads(json.dumps(b, default=str)))


def runtime_evidence(contract_sha: str, probe_docker: bool = True) -> "OrderedDict[str, Any]":
    """T0 runtime evidence, identity-only (no timestamps): contract sha,
    the pinned static/repair runtime sha, the main image identity measured
    live (docker inspect) and the compiler/MPI identities from the readiness
    artifact. Missing evidence stays null - never invented."""
    readiness = _load_json(READINESS_PATH) or {}
    runtime_condition = readiness.get("runtime_condition") or {}
    main_live = None
    if probe_docker:
        try:
            from thesis.evaluation.check_static_repair_readiness import docker_image_identity

            main_live = docker_image_identity("pareval-thesis")
        except Exception as exc:  # noqa: BLE001
            main_live = {"inspect_error": "%s: %s" % (type(exc).__name__, exc)}
    identities = None
    for role, entry in (runtime_condition.get("environments") or runtime_condition).items() \
            if isinstance(runtime_condition, dict) else []:
        if isinstance(entry, dict) and entry.get("tool_identities"):
            identities = identities or OrderedDict()
            identities[role] = entry.get("tool_identities")
    return OrderedDict([
        ("evidence_version", "t0_runtime_evidence.v1"),
        ("contract_sha256", contract_sha),
        ("static_repair_runtime_condition_sha256", readiness.get("runtime_condition_sha256")),
        ("main_image_identity_live", main_live),
        ("tool_identities_pinned", identities),
        ("readiness_gate", readiness.get("gate")),
    ])


def t0_guard(config_path: Path, profile_name: str, frozen_path: Path,
             run_id_override: "Optional[str]" = None, bind: bool = True,
             probe_docker: bool = True) -> "OrderedDict[str, Any]":
    """Immediately before the first cost-causing request: rebuild the
    contract from the live state and compare it with the frozen one. Any
    drift -> START_REFUSED (nothing is registered). On match and bind=True
    the contract sha and the runtime evidence are registered in the run
    manifest BEFORE the caller may send a request."""
    frozen = load_frozen(frozen_path)
    frozen_sha = frozen["contract_sha256"]
    rebuilt = build_contract(config_path, profile_name, run_id_override,
                             primary_compiler=frozen.get("primary_compiler") or "g++")
    rebuilt_sha = contract_sha256(rebuilt)
    drift = contract_diff(frozen, rebuilt)
    decision = OrderedDict([
        ("decision", START_ALLOWED if (rebuilt_sha == frozen_sha and not drift
                                       and rebuilt["status"] == STATUS_READY) else START_REFUSED),
        ("frozen_contract_sha256", frozen_sha),
        ("rebuilt_contract_sha256", rebuilt_sha),
        ("drift_fields", drift),
        ("rebuilt_status", rebuilt["status"]),
        ("rebuilt_blockers", rebuilt["blockers"]),
        ("bound", False),
        ("checked_at_utc", _utc_now()),
    ])
    if decision["decision"] != START_ALLOWED:
        return decision
    if bind:
        from thesis.evaluation import run_manifest

        config = load_config(Path(config_path).resolve())
        run_manifest.ensure_run_manifest(config, rebuilt["run_id"], stage="t0_contract",
                                         profile=profile_name,
                                         primary_compiler=rebuilt["primary_compiler"])
        run_manifest.register_contract(config, rebuilt["run_id"], frozen_sha, frozen)
        evidence = runtime_evidence(frozen_sha, probe_docker=probe_docker)
        run_manifest.register_runtime_evidence(config, rebuilt["run_id"], evidence)
        decision["bound"] = True
        decision["runtime_evidence"] = evidence
    return decision


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "freeze", "t0"])
    parser.add_argument("--config", default="thesis/config/config.yaml")
    parser.add_argument("--profile", default="pilot")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--out", default=None, help="freeze: contract file to write")
    parser.add_argument("--frozen", default=None, help="t0: frozen contract file")
    parser.add_argument("--allow-draft", action="store_true")
    parser.add_argument("--no-bind", action="store_true")
    parser.add_argument("--skip-runtime-probe", action="store_true")
    args = parser.parse_args()

    if args.command in ("build", "freeze"):
        contract = build_contract(args.config, args.profile, args.run_id)
        print("CONTRACT_SCHEMA = %s" % CONTRACT_SCHEMA_VERSION)
        print("CONTRACT_BUILDER = READY")
        print("CONTRACT_STATUS = %s" % contract["status"])
        print("CONTRACT_SHA256 = %s" % contract["contract_sha256"])
        for blocker in contract["blockers"]:
            print("  BLOCKER: %s" % blocker)
        if args.command == "freeze":
            if not args.out:
                # the canonical per-run location, so a provider CHILD PROCESS
                # discovers the same contract without a new CLI parameter
                from thesis.evaluation.run_authorization import canonical_contract_path

                args.out = str(canonical_contract_path(
                    load_config(Path(args.config).resolve()), contract["run_id"]))
                print("FREEZE_TARGET = %s (canonical run location)" % args.out)
            try:
                sha = freeze_contract(contract, Path(args.out), allow_draft=args.allow_draft)
            except ContractNotReady as err:
                print("FREEZE_REFUSED: %s" % err)
                return 2
            print("FROZEN_CONTRACT_SHA = %s -> %s" % (sha, args.out))
        return 0 if contract["status"] == STATUS_READY else 2

    if not args.frozen:
        parser.error("--frozen is required for t0")
    decision = t0_guard(args.config, args.profile, Path(args.frozen), args.run_id,
                        bind=not args.no_bind, probe_docker=not args.skip_runtime_probe)
    print("T0_DECISION = %s" % decision["decision"])
    print("FROZEN_CONTRACT_SHA = %s" % decision["frozen_contract_sha256"])
    print("REBUILT_CONTRACT_SHA = %s" % decision["rebuilt_contract_sha256"])
    for field in decision["drift_fields"]:
        print("  DRIFT: %s" % field)
    print("CONTRACT_BOUND_TO_RUN = %s" % str(decision["bound"]).lower())
    return 0 if decision["decision"] == START_ALLOWED else 3


if __name__ == "__main__":
    sys.exit(main())
