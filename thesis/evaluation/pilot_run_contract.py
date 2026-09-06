"""Pilot run contract (pilot_run_contract.v1) - builder, freeze, T0 guard.

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

Today (pilot_002 pre-run wave) the builder returns NOT_READY by design:
the population is NOT_YET_DECIDED and the base run id is NOT_YET_CONFIGURED
in cross_pilot_comparability.json, and the config pilot profile still
carries the historical pilot_001 run id. Nothing here makes those decisions.

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

CONTRACT_SCHEMA_VERSION = "pilot_run_contract.v1"
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
    cross = _load_json(CROSS_PILOT_PATH) or {}
    decisions = _load_json(SEMANTIC_DECISIONS_PATH) or {}
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
        ("cross_pilot_artifact_sha256", cross.get("cross_pilot_fingerprint_sha256")),
        ("cross_pilot_state_commit", cross.get("state_commit")),
        ("timing_contract_sha256", _timing_sha()),
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


def build_contract(config_path: Path, profile_name: str,
                   run_id_override: "Optional[str]" = None,
                   primary_compiler: str = "g++") -> "OrderedDict[str, Any]":
    from thesis.generation import common

    config = load_config(Path(config_path).resolve())
    profile = common.get_profile(config, profile_name)
    run_id = run_id_override or profile.get("run_id")
    cross = _load_json(CROSS_PILOT_PATH) or {}
    population_policy = cross.get("expected_pilot_002_population") or {}
    base_run_policy = cross.get("expected_pilot_002_base_run") or {}

    models = sorted(m["id"] for m in config.get("models", []) if m.get("enabled", False))
    population = population_view(config, profile)
    conditions = conditions_view(config, primary_compiler)
    stages = config.get("stages") or {}

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
    contract["policy_state"] = OrderedDict([
        ("population_status", population_policy.get("status")),
        ("expected_base_run_status", base_run_policy.get("status")),
        ("expected_base_run_id", base_run_policy.get("run_id")),
        ("forbid_iteration_variants", base_run_policy.get("forbid_iteration_variants")),
        ("reuse_status", cross.get("reuse_status")),
    ])
    contract["post_run_verifier_version"] = POST_RUN_VERIFIER_VERSION
    contract["post_run_verification_required_for_result_acceptance"] = True

    blockers: "List[str]" = []
    if population_policy.get("status") != "DECIDED":
        blockers.append("pilot_002 population: %s" % (population_policy.get("status") or "UNKNOWN"))
    if base_run_policy.get("status") != "CONFIGURED":
        blockers.append("pilot_002 base run id: %s" % (base_run_policy.get("status") or "UNKNOWN"))
    elif base_run_policy.get("run_id") != run_id:
        blockers.append("run_id %r differs from the configured expected base run %r"
                        % (run_id, base_run_policy.get("run_id")))
    if run_id == HISTORICAL_PILOT_RUN_ID or (run_id or "").startswith(HISTORICAL_PILOT_RUN_ID + "__"):
        blockers.append("run_id %r is the historical pilot_001 run (or one of its iteration runs)" % run_id)
    if "__" in (run_id or "") and "iter" in (run_id or ""):
        blockers.append("run_id %r looks like a repair-iteration run id; the base run must not be one" % run_id)
    if not models:
        blockers.append("no enabled models")
    if population["error"]:
        blockers.append("population: %s" % population["error"])
    if population["expected_sample_count"] is None:
        blockers.append("expected sample count undetermined")
    if conditions["static_repair_readiness_gate"] != "READY":
        blockers.append("static/repair readiness gate: %s" % conditions["static_repair_readiness_gate"])
    for key in ("generation_condition_sha256", "evaluation_condition_sha256",
                "enhanced_frozen_specs_sha256", "static_analysis_condition_sha256",
                "repair_condition_sha256", "static_repair_runtime_condition_sha256",
                "semantic_decisions_sha256_lf_normalized", "cross_pilot_artifact_sha256"):
        if not conditions.get(key):
            blockers.append("condition pin missing: %s" % key)
    if (conditions["semantic_decisions_counts"].get("unresolved") or 0) > 0:
        blockers.append("semantic decisions unresolved: %s" % conditions["semantic_decisions_counts"]["unresolved"])

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
                parser.error("--out is required for freeze")
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
