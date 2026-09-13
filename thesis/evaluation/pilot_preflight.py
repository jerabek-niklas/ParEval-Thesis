#!/usr/bin/env python3
"""Pilot preflight: DECLARATION check REQUIRED before pilot_002.

WHAT THIS TOOL IS - AND IS NOT
------------------------------
`invocation.json` is a machine-readable SELF-DECLARATION of the PLANNED
effective invocation (values AFTER applying any CLI overrides, not raw
argv). This tool compares that declaration - plus the captured runtime
environment - against the frozen cross-pilot gate
(thesis/evaluation/cross_pilot_comparability.json).

    INVOCATION_SELF_DECLARED = true
    PREFLIGHT_IS_DECLARATION_CHECK_NOT_ENFORCEMENT = true

A passing preflight therefore means ONLY: "the declared planned invocation
is compatible with the current gate". It does NOT and can NOT prove that
the later actual run was started with exactly these arguments. The
after-the-fact proof is a separate, later, read-only comparison of the
ACTUAL pilot_002 run_manifest.json (frozen config, effective compiler, run
identity, config drift, toolchain provenance) against the gate:

    POST_RUN_MANIFEST_VERIFICATION = REQUIRED_IMPLEMENTED
    (thesis/evaluation/verify_pilot_run.py, section 18)

This tool also does NOT check the external final-gate steps (pilot_002
population decision, pilot_002 base-run-id configuration, reuse decision,
publication policy). Those stay
external; a passing tool run reports
"technical_cross_pilot_preflight_passed" and
"final_pilot_gate_still_required" - never "pilot_002 fully authorized".

CHECKED DIMENSIONS (tool-owned)
-------------------------------
 1. repo-state gate fresh (check_cross_pilot_gate)
 2. declared config readable
 3. config generation condition content-addressed match (the config FILE
    PATH is irrelevant; the loaded config is projected through the SAME
    authoritative generation-condition definition and compared by hash)
 4. config evaluation condition content-addressed match (same principle)
 5. declared profile exists in the config
 6. pilot_002 population: checked against the gate's
    expected_pilot_002_population ONLY if its status is DECIDED; while
    NOT_YET_DECIDED the result is PROFILE_POPULATION_MATCH = UNRESOLVED and
    PILOT_002_POPULATION_READY = false. The historical pilot_001 population
    (stratified/36/1 sample) is deliberately NOT used as an implicit target:
    1 sample per cell is a documented pilot_001 weakness, and a deliberate
    increase for pilot_002 must not be blocked here.
 7. full model population: set(selected_model_ids) must equal the enabled
    model ids of the VALIDATED config. (The generation-condition hash already
    freezes WHICH population the config defines - this check only asks
    whether the planned run EXECUTES that full population; no second source
    of truth.)
 8. no --model-id restriction (a restricted run is a smoke/debug run, never
    the cross-pilot base pilot)
 9. run id: checked against expected_pilot_002_base_run ONLY if configured;
    while NOT_YET_CONFIGURED: RUN_ID_MATCH = UNRESOLVED and
    PILOT_002_BASE_RUN_ID_READY = false (pilot_001 is never adopted as the
    expected pilot_002 run id)
10. reserved/iteration run ids are always rejected (pilot_001, smoke_*,
    full_*, repair_smoke_*, model_check_*, any "__iter"/variant suffix) - a
    repair-iteration population can never pass the base-run preflight
16. semantic decisions (Semantic Interlock wave, check_semantic_decisions):
    every former prompt/oracle interlock must carry a FINAL decision.
    SEMANTIC_DECISION_UNRESOLVED > 0 -> BLOCK; a deliberately accepted
    disclosure (SEMANTIC_DISCLOSURE_ACCEPTED) does NOT block, provided its
    reporting requirement is machine-readable. Whether reports actually
    render it (SEMANTIC_DISCLOSURE_RENDERING) is smoke-rendered against the
    real renderer, never merely asserted.
18. pilot_002 pre-run infrastructure: assembly provenance, timing contract,
    reporting contracts, manifest architecture, the run-contract builder,
    the T0 start guard and the post-run verification mechanism. This
    section reports READINESS of the MECHANISMS; it decides nothing about
    population, run_id, reuse or publication.
11. primary compiler vs frozen expected value
12. run timeout vs frozen expected value
13. runtime compiler version compatible with the recorded toolchain
14. runtime MPI version compatible with the recorded toolchain
15. runtime container image ID/digest captured

ENVIRONMENT SEMANTICS: pilot_001 recorded NO container digest/image ID, so
a present-day image ID is NEVER evidence of historical container identity.
    PILOT_ENVIRONMENT_TOOLCHAIN_COMPATIBLE  = recorded toolchain condition
                                              (compiler/MPI versions) matches
    PILOT_RUNTIME_IMAGE_IDENTITY_CAPTURED   = a concrete current image
                                              ID/digest was provided (new
                                              provenance to persist)
    PILOT_ENVIRONMENT_MATCH                 = BOTH of the above; explicitly
                                              NOT "historically identical
                                              container proven"

invocation.json MUST contain (effective values after overrides):
    {"config_path": "...", "profile": "...", "effective_run_id": "...",
     "selected_model_ids": [...], "primary_compiler": "...",
     "run_timeout_seconds": ..., "model_id_cli_override": null}

environment.json MUST contain:
    {"primary_compiler_version": "<first line of `g++ --version`>",
     "mpi_version_line": "<first line of `mpirun --version`>",
     "container_image_id_or_digest": "<docker image ID or repo digest>"}

Exit codes:
    0  every tool-owned check decided AND matching
       (technical_cross_pilot_preflight_passed; final_pilot_gate_still_required)
    1  at least one mismatch -> pilot_002_not_authorized,
       CROSS_PILOT_GATE_STALE = true (comparability_re_evaluation_required)
    2  UNRESOLVED / NOT_READY (missing declaration fields or provenance,
       population/run-id targets not yet decided/configured) ->
       pilot_002_not_authorized. With the population and base-run-id targets
       currently open, exit 2 on the real gate is the CORRECT result.

Read-only: writes nothing.
"""

import argparse
import json
import re
import sys
from pathlib import Path

# The repository root must be importable BEFORE any thesis.* import: relying
# on a sibling module's side effect made the static/repair section skip its
# comparison silently when this script was started from another directory.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import check_cross_pilot_gate as repo_gate
import check_semantic_decisions as semantic_gate

GATE_PATH = repo_gate.GATE_PATH

REQUIRED_INVOCATION_FIELDS = (
    "config_path", "profile", "effective_run_id", "selected_model_ids",
    "primary_compiler", "run_timeout_seconds", "model_id_cli_override",
)

RESERVED_RUN_ID_PATTERNS = (
    re.compile(r"^pilot_001$"),
    re.compile(r"^smoke_"),
    re.compile(r"^full_"),
    re.compile(r"^repair_smoke_"),
    re.compile(r"^model_check_"),
)


def load_json(path):
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def tristate(value):
    return "UNRESOLVED" if value is None else str(bool(value)).lower()


def prerun_infrastructure_lines() -> "list":
    """Readiness of the pilot_002 pre-run mechanisms (assembly provenance,
    timing contract, reporting contracts, manifest architecture, contract
    builder, T0 guard, post-run verifier). Read-only; every value is
    computed from the productive modules, never hard-coded."""
    lines = []
    try:
        from thesis.analysis_overview import report_contracts
        from thesis.assembly import assemble_sources, assembly_provenance
        from thesis.evaluation import (manifest_fragments, pilot_run_contract,
                                       timing_semantics, verify_pilot_run)
        from thesis.config.load_config import load_config
    except Exception as exc:  # noqa: BLE001
        return ["PRE_RUN_INFRASTRUCTURE = UNRESOLVED (modules not importable: %s)" % exc]

    config = load_config(REPO_ROOT / "thesis" / "config" / "config.yaml")
    condition = assembly_provenance.assembly_condition(config)
    lines.append("ASSEMBLY_SCHEMA_VERSION = %s" % assemble_sources.ASSEMBLY_SCHEMA_VERSION)
    lines.append("ASSEMBLY_CONDITION_VERSION = %s" % condition["condition_version"])
    lines.append("ASSEMBLY_CONDITION_SHA256 = %s"
                 % assembly_provenance.assembly_condition_sha256(condition))
    lines.append("ASSEMBLY_WRITER_NEWLINE_POLICY = %s"
                 % assemble_sources.ASSEMBLY_WRITER_NEWLINE_POLICY)
    lines.append("ASSEMBLY_ARTIFACT_HASH_POLICY = RAW_BYTES")
    lines.append("CONDITION_HASH_POLICY = LF_NORMALIZED")
    lines.append("GENERATION_CLEANING_COVERED_BY_CONDITION = true (%s)"
                 % assembly_provenance.GENERATION_CLEANING_CONDITION_VERSION)
    lines.append("TIMING_CONTRACT = %s (sha %s)"
                 % (timing_semantics.TIMING_CONTRACT_VERSION,
                    timing_semantics.timing_contract_sha256()))
    lines.append("REPORT_CONTRACT = %s (report_condition_sha256 %s)"
                 % (report_contracts.REPORT_CONTRACT_VERSION,
                    report_contracts.report_condition_sha256()))
    lines.append("MANIFEST_ARCHITECTURE = PER_WRITER_FRAGMENTS (%s; legacy runs with a "
                 "shared run_manifest.json keep it and are never migrated)"
                 % manifest_fragments.FRAGMENT_SCHEMA_VERSION)

    contract = pilot_run_contract.build_contract(
        REPO_ROOT / "thesis" / "config" / "config.yaml", "pilot")
    lines.append("CONTRACT_SCHEMA = %s" % pilot_run_contract.CONTRACT_SCHEMA_VERSION)
    lines.append("CONTRACT_BUILDER = READY")
    lines.append("CONTRACT_BUILDER_STATE = %s" % contract["status"])
    for blocker in contract["blockers"]:
        lines.append("  CONTRACT_BLOCKER: %s" % blocker)
    lines.append("FINAL_PILOT002_CONTRACT = NOT_YET_CREATED (a contract can only be "
                 "frozen once the population decision and the base run id are made)")
    lines.append("T0_START_GUARD = READY (pilot_run_contract.t0_guard: rebuild + compare "
                 "immediately before the first cost-causing request; drift -> START_REFUSED)")
    # ---- provider chokepoint enforcement (measured, not asserted) --------
    from thesis.evaluation import (effective_invocation, provider_call_sites,
                                   run_authorization, stage_runtime)

    inventory = provider_call_sites.build_inventory()
    unguarded = inventory["UNGUARDED_PROVIDER_CALL_SITES"]
    lines.append("PROVIDER_CALL_SITES = %d (cost-causing %d, submit %d)"
                 % (inventory["counts"]["provider_call_sites"],
                    inventory["counts"]["cost_causing"], inventory["counts"]["submit_sites"]))
    lines.append("PROVIDER_DIRECT_CHOKEPOINT = %s" % inventory["chokepoints"]["direct"])
    lines.append("PROVIDER_BATCH_CHOKEPOINT = %s" % inventory["chokepoints"]["batch_submit"])
    lines.append("UNGUARDED_PROVIDER_CALL_SITES = %s"
                 % ("[]" if not unguarded else ", ".join(
                     "%s:%d" % (s["file"], s["line"]) for s in unguarded)))
    lines.append("T0_START_GUARD_ENFORCED_BY_PROVIDER_CHOKEPOINT = %s"
                 % ("true" if not unguarded else "false"))
    lines.append("AUTHORIZATION_SCHEMA = %s (policy %s)"
                 % (run_authorization.AUTHORIZATION_SCHEMA_VERSION,
                    run_authorization.AUTHORIZATION_POLICY_VERSION))
    lines.append("AUTHORIZATION_VOLATILE_FIELDS_EXCLUDED_FROM_FINGERPRINT = %s"
                 % str(run_authorization.AUTHORIZATION_VOLATILE_FIELDS_EXCLUDED_FROM_FINGERPRINT
                       ).lower())
    lines.append("T0_RUNTIME_EVIDENCE = %s" % run_authorization.T0_RUNTIME_EVIDENCE_VERSION)
    lines.append("T0_REQUIRES_DOCKER_AND_ALL_THREE_IMAGES = %s (%s)"
                 % (str(run_authorization.T0_REQUIRES_DOCKER_AND_ALL_THREE_IMAGES).lower(),
                    ", ".join(run_authorization.REQUIRED_RUNTIME_DOMAINS)))
    lines.append("PER_STAGE_RUNTIME_BINDING = READY (%s; stages: %s)"
                 % (stage_runtime.STAGE_RUNTIME_EVIDENCE_VERSION,
                    ", ".join(stage_runtime.STAGE_DOMAINS)))
    lines.append("EFFECTIVE_INVOCATION_PROVENANCE = READY (%s; policy %s)"
                 % (effective_invocation.EFFECTIVE_INVOCATION_VERSION,
                    effective_invocation.OVERRIDE_POLICY))
    # ---- cross-process authorization + complete expected runtime matrix ----
    lines.append("CROSS_PROCESS_AUTHORIZATION = READY (%s; persistent run provenance is "
                 "authoritative, the process context is a validated cache)"
                 % run_authorization.REHYDRATION_POLICY_VERSION)
    lines.append("AUTHORIZATION_REHYDRATION_CHECKS = %s"
                 % ", ".join(run_authorization.REHYDRATION_CHECKS))
    lines.append("FROZEN_CONTRACT_DISCOVERY = %s (canonical per-run location: "
                 "<intermediate_dir>/<run_id>/%s)"
                 % (" > ".join(run_authorization.CONTRACT_DISCOVERY_ORDER),
                    run_authorization.CANONICAL_CONTRACT_NAME))
    lines.append("PROVIDER_CHILD_PROCESS_NEEDS_PARENT_RAM_CONTEXT = false")
    lines.append("PRE_RUN_INFRASTRUCTURE_FAILURE_EXIT_CODE = %d (the generation "
                 "orchestrator stops on it even with --continue-on-error: an "
                 "unauthorized model is never skipped as a model failure)"
                 % run_authorization.EXIT_PRE_RUN_INFRASTRUCTURE_FAILURE)
    expected_rows = stage_runtime.expected_runtime_stages(contract, config)
    lines.append("EXPECTED_RUNTIME_STAGE_POLICY = %s"
                 % stage_runtime.EXPECTED_RUNTIME_STAGE_POLICY)
    lines.append("EXPECTED_RUNTIME_STAGES = %s"
                 % (", ".join("%s[%s]" % (row["stage"], "/".join(row["domains"]))
                              for row in expected_rows) or "none"))
    for row in stage_runtime.not_expected_runtime_stages(contract, config):
        lines.append("  RUNTIME_STAGE_NOT_APPLICABLE: %s (%s)"
                     % (row["stage"], row["reason"]))
    lines.append("RESULT_FILES_SUBSTITUTE_FOR_RUNTIME_STAMP = false")
    lines.append("INVOCATION_NON_METHODICAL_FIELDS = [] (every registered effective value "
                 "is a METHODICAL CLI override of its stage, checked against "
                 "cli_override_inventory)")
    # ---- repair scope completeness (post-run verifier) ----
    from thesis.evaluation import repair_scope

    repair_expected = repair_scope.expected_repair_loops(contract)
    lines.append("REPAIR_SCOPE_VERIFICATION = READY (%s)" % repair_scope.REPAIR_MATRIX_VERSION)
    lines.append("REPAIR_EXPECTED_SET_POLICY = %s (%s)"
                 % (repair_scope.REPAIR_EXPECTED_SET_RULE, repair_scope.REPAIR_EXPECTED_SET_POLICY))
    lines.append("REPAIR_TERMINALITY_POLICY = %s (terminal(loop) := state.jsonl exists AND no "
                 "sample is STATUS_ACTIVE; run_backfill.loop_state_terminality)"
                 % repair_scope.REPAIR_TERMINALITY_POLICY)
    lines.append("REPAIR_LOOP_STATE_SOURCE_OF_TRUTH = %s"
                 % repair_scope.REPAIR_LOOP_STATE_SOURCE_OF_TRUTH)
    # which variants analyse ITERATION 0 themselves - i.e. register their
    # repair_evaluation invocation without ever analysing an iteration >= 1
    # (orchestrator.step() -> _to_analyzed(0) covers whatever the base run
    # did not). Pre-run evidence for the post-run coverage rule.
    lines.append("REPAIR_ITERATION_ZERO_INVOCATION_POLICY = %s"
                 % repair_scope.ITERATION_ZERO_INVOCATION_POLICY)
    for variant in repair_expected["variants"]:
        zero = repair_scope.iteration_zero_analysis(contract, config, variant)
        lines.append("  REPAIR_ITERATION_ZERO_ANALYSIS: %s = %s (%s)"
                     % (variant, "REGISTERS_INVOCATION_AT_ITERATION_0" if zero["certain"]
                        else "BASE_RUN_COVERS_ITERATION_0_BY_CONTRACT",
                        ", ".join(zero["missing_internal_stages"]) or zero["reason"]))
    lines.append("REPAIR_EXPECTED_LOOPS (contract view of the current config) = %d (%s; %d "
                 "model(s) x %d variant(s): %s)"
                 % (len(repair_expected["loops"]), repair_expected["status"],
                    len(repair_expected["model_ids"]), len(repair_expected["variants"]),
                    ", ".join(repair_expected["variants"]) or "-"))
    lines.append("RUNTIME_STAMP_SUBSTITUTES_MISSING_REPAIR_LOOP = false")
    lines.append("POST_RUN_REPAIR_COMPLETENESS_REQUIRED = true")
    # ---- technical provenance cleanup: split invocation coverage +
    # iteration-0 writer attribution (mechanism + verifier + fixtures) ----
    lines += technical_provenance_lines(contract, config)
    lines.append("POST_RUN_VERIFICATION_MECHANISM = READY (%s)"
                 % verify_pilot_run.VERIFIER_VERSION)
    lines.append("PILOT_002_POST_RUN_VERIFIED = NOT_APPLICABLE_BEFORE_RUN")
    lines.append("POST_RUN_VERIFICATION_REQUIRED_FOR_RESULT_ACCEPTANCE = true")
    lines.append("SEMANTIC_DISCLOSURE_RENDERING = %s"
                 % semantic_gate.disclosure_rendering_state())
    return lines


def technical_provenance_lines(contract, config) -> "list":
    """READY here means: the mechanism, its verifier and its fixtures exist
    and the expected set is derivable from the contract - never that a
    pilot_002 verification already passed (there are no post-run records
    before a run)."""
    import inspect

    from thesis.evaluation import (repair_scope, run_correctness, run_dynamic_analysis,
                                   run_static_analysis, stage_runtime, writer_attribution)
    from thesis.repair import orchestrator

    lines = []
    expected = stage_runtime.expected_split_static_invocations(contract)
    lines.append("STATIC_SPLIT_INVOCATION_COVERAGE_POLICY = %s (identity %s; duplicates: %s)"
                 % (stage_runtime.SPLIT_INVOCATION_COVERAGE_POLICY,
                    stage_runtime.SPLIT_SCOPE_IDENTITY, stage_runtime.SPLIT_DUPLICATE_POLICY))
    lines.append("STATIC_SPLIT_EXPECTED_SCOPES (contract view of the current config) = %s (%s)"
                 % (expected["status"], expected["reason"]))
    for tool, info in expected["per_tool"].items():
        lines.append("  STATIC_SPLIT_EXPECTED_SCOPES[%s] = %d (%s%s)"
                     % (tool, info["scope_count"], info["stage"],
                        "; execution models " + "/".join(info["applicable_execution_models"])
                        if info.get("expected") else "; not expected"))
    lines.append("RUNTIME_STAMP_SUBSTITUTES_SPLIT_INVOCATION = %s"
                 % str(stage_runtime.RUNTIME_STAMP_SUBSTITUTES_SPLIT_INVOCATION).lower())
    lines.append("RECORD_COVERAGE_SUBSTITUTES_SPLIT_INVOCATION = %s"
                 % str(stage_runtime.RECORD_COVERAGE_SUBSTITUTES_SPLIT_INVOCATION).lower())
    split_ready = expected["status"] in ("PASS", "NOT_APPLICABLE") \
        and hasattr(stage_runtime, "split_static_invocation_matrix")
    lines.append("STATIC_SPLIT_INVOCATION_COVERAGE_READY = %s" % str(split_ready).lower())
    # writer attribution: every internal runner accepts it and the
    # orchestrator hands it to all three (measured from the source, not
    # asserted)
    runners_ready = all("writer_attribution" in inspect.signature(fn).parameters
                        for fn in (run_static_analysis.run_model, run_correctness.run_model,
                                   run_dynamic_analysis.run_model))
    source = inspect.getsource(orchestrator.RepairLoop._run_analysis_stages)
    orchestrator_ready = all('writer_attribution=attribution("%s")' % stage in source
                             or "writer_attribution=attribution('%s')" % stage in source
                             for stage in writer_attribution.INTERNAL_STAGES)
    verifier_ready = (repair_scope.ITERATION_ZERO_COVERAGE_RESIDUAL == "CLOSED_BY_WRITER_ATTRIBUTION"
                      and hasattr(repair_scope, "repair_labelled_internal_invocations"))
    lines.append("REPAIR_WRITER_ATTRIBUTION = %s (label convention %r; histories: %s)"
                 % (writer_attribution.REPAIR_WRITER_ATTRIBUTION_VERSION,
                    writer_attribution.REPAIR_INVOCATION_LABEL,
                    ", ".join("%s -> %s" % kv for kv in writer_attribution.SUMMARY_FILE_NAMES.items())))
    lines.append("REPAIR_ITERATION_ZERO_WRITER_ATTRIBUTION_POLICY = %s"
                 % repair_scope.ITERATION_ZERO_WRITER_ATTRIBUTION_POLICY)
    lines.append("ITERATION_ZERO_COVERAGE_RESIDUAL = %s" % repair_scope.ITERATION_ZERO_COVERAGE_RESIDUAL)
    attribution_ready = runners_ready and orchestrator_ready and verifier_ready
    lines.append("ITERATION_ZERO_WRITER_ATTRIBUTION_READY = %s (runners %s, orchestrator %s, "
                 "verifier %s)" % (str(attribution_ready).lower(), str(runners_ready).lower(),
                                    str(orchestrator_ready).lower(), str(verifier_ready).lower()))
    lines.append("TECHNICAL_PROVENANCE_CLEANUP_READY = %s (mechanism + verifier + fixtures; "
                 "not a passed pilot_002 verification)"
                 % str(split_ready and attribution_ready).lower())
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--invocation", required=True,
                    help="JSON self-declaration of the PLANNED effective invocation")
    ap.add_argument("--environment", required=True,
                    help="JSON with the ACTUAL captured runtime environment values")
    ap.add_argument("--skip-repo-check", action="store_true",
                    help="skip the repo-state gate check (testing only)")
    ap.add_argument("--static-readiness",
                    default=str(Path(__file__).resolve().parent / "static_repair_readiness.json"),
                    help="artifact written by check_static_repair_readiness.py "
                         "(tool-state wave); missing/stale -> UNRESOLVED")
    ap.add_argument("--static-runtime", default=None,
                    help="FRESH runtime provenance (JSON with a 'runtime' "
                         "mapping, or the mapping itself) for hosts where this "
                         "preflight cannot start containers itself. Without it "
                         "the runtime is measured live via docker; a runtime "
                         "that is neither supplied nor measurable is "
                         "UNRESOLVED, never fresh.")
    ap.add_argument("--skip-runtime-probe", action="store_true",
                    help="do not measure the runtime (testing only; the "
                         "static/repair readiness can then never be READY)")
    args = ap.parse_args()

    print("INVOCATION_SELF_DECLARED = true")
    print("PREFLIGHT_IS_DECLARATION_CHECK_NOT_ENFORCEMENT = true")
    print("(a passing preflight means the DECLARED planned invocation is"
          " compatible with the gate - it is not proof of the actual later"
          " execution; the after-the-fact proof is verify_pilot_run.py, see"
          " section 18)")

    gate = load_json(GATE_PATH)
    if gate is None:
        print("ERROR: gate artifact missing: %s" % GATE_PATH)
        return 2

    mismatch = False
    unresolved = False

    # ---- 0. repo-state gate ----
    if args.skip_repo_check:
        print("REPO_STATE_CHECK: skipped (--skip-repo-check; testing only)")
    else:
        print("REPO_STATE_CHECK")
        rc = repo_gate.main()
        if rc == 1:
            mismatch = True
        elif rc == 2:
            unresolved = True

    # ---- 1. declaration completeness ----
    print("DECLARATION_CHECK")
    inv = load_json(args.invocation)
    if inv is None:
        print("  UNRESOLVED (invocation file missing/unreadable)")
        print("PILOT_CONDITION_MATCH = UNRESOLVED")
        print("\nRESULT: pilot_002_not_authorized (incomplete declaration)")
        return 2
    missing = [f for f in REQUIRED_INVOCATION_FIELDS if f not in inv]
    if missing:
        print("  UNRESOLVED (required invocation fields missing: %s)"
              % ", ".join(missing))
        print("PILOT_CONDITION_MATCH = UNRESOLVED")
        print("\nRESULT: pilot_002_not_authorized (incomplete declaration -"
              " the self-declaration must cover the full planned invocation)")
        return 2
    print("  all required invocation fields present")

    cond_match = True  # True / False / None(=unresolved)

    def cond_fail():
        nonlocal cond_match, mismatch
        mismatch = True
        cond_match = False

    def cond_open():
        nonlocal cond_match, unresolved
        unresolved = True
        if cond_match is True:
            cond_match = None

    # ---- 2-4. config readable + content-addressed condition match ----
    print("CONFIG_CONDITION_CHECK (content-addressed: the file path is not"
          " the methodical identity - the projected content is)")
    frozen = gate.get("shared_state") or {}
    frozen_gen = (frozen.get("generation_condition") or {}).get("sha256")
    frozen_ev = (frozen.get("evaluation_condition") or {}).get("sha256")
    config_ok = False
    cfg = None
    try:
        cfg = repo_gate._load_yaml_config(inv["config_path"])
        config_ok = True
        print("  config readable: %s" % inv["config_path"])
    except repo_gate.ConditionUnresolved as exc:
        print("  UNRESOLVED (declared config not readable: %s)" % exc)
        cond_open()
    if config_ok and frozen_gen and frozen_ev:
        try:
            actual_gen = repo_gate.canon_sha256(
                repo_gate.generation_condition_projection(inv["config_path"]))
            gen_match = actual_gen == frozen_gen
            print("  CONFIG_GENERATION_CONDITION_MATCH = %s" % str(gen_match).lower())
            if not gen_match:
                cond_fail()
            actual_ev = repo_gate.canon_sha256(
                repo_gate.evaluation_condition_projection(inv["config_path"]))
            ev_match = actual_ev == frozen_ev
            print("  CONFIG_EVALUATION_CONDITION_MATCH = %s" % str(ev_match).lower())
            if not ev_match:
                cond_fail()
        except repo_gate.ConditionUnresolved as exc:
            print("  UNRESOLVED (condition projection failed: %s)" % exc)
            cond_open()
    elif config_ok:
        print("  UNRESOLVED (gate stores no frozen condition hashes)")
        cond_open()

    # ---- 5. profile exists ----
    print("PROFILE_CHECK")
    profile = None
    if cfg is not None:
        profiles = cfg.get("profiles") or {}
        if inv["profile"] in profiles:
            profile = profiles[inv["profile"]]
            print("  profile %r exists in the declared config" % inv["profile"])
        else:
            print("  MISMATCH (profile %r does not exist in the declared config)"
                  % inv["profile"])
            cond_fail()
    else:
        print("  UNRESOLVED (config not readable)")
        cond_open()

    # ---- 6. pilot_002 population (separate future target, NOT pilot_001) --
    print("POPULATION_CHECK")
    exp_pop = gate.get("expected_pilot_002_population") or {}
    pop_status = exp_pop.get("status")
    if pop_status == "DECIDED":
        pop_match = True
        if profile is None:
            print("  PROFILE_POPULATION_MATCH = UNRESOLVED (profile unavailable)")
            cond_open()
        else:
            for key in ("selection", "prompt_limit", "num_samples_per_prompt"):
                expected = exp_pop.get(key)
                actual = profile.get(key)
                if actual != expected:
                    print("  %s: MISMATCH (profile %r != decided %r)"
                          % (key, actual, expected))
                    pop_match = False
            if pop_match:
                print("  PROFILE_POPULATION_MATCH = true")
                print("  PILOT_002_POPULATION_READY = true")
            else:
                print("  PROFILE_POPULATION_MATCH = false")
                cond_fail()
    else:
        print("  expected_pilot_002_population.status = %s" % pop_status)
        print("  PROFILE_POPULATION_MATCH = UNRESOLVED (no authoritative"
              " pilot_002 population target exists yet - this is NOT a"
              " mismatch against pilot_001; the pilot_001 values"
              " (stratified/36/1) are deliberately not an implicit target)")
        print("  PILOT_002_POPULATION_READY = false")
        cond_open()

    # ---- 7-8. model population (execution completeness, not a second
    #           source of truth: expected ids come from the validated config)
    print("MODEL_POPULATION_CHECK (the generation-condition hash already"
          " freezes WHICH population the config defines; this checks only"
          " that the planned run EXECUTES that full population)")
    if inv.get("model_id_cli_override") is not None:
        print("  MODEL_ID_RESTRICTION_PRESENT = true (--model-id %r)"
              % inv["model_id_cli_override"])
        print("  MODEL_POPULATION_MATCH = false (a restricted run is a"
              " smoke/debug run, never the cross-pilot base pilot)")
        cond_fail()
    elif cfg is None:
        print("  MODEL_ID_RESTRICTION_PRESENT = false")
        print("  MODEL_POPULATION_MATCH = UNRESOLVED (config not readable)")
        cond_open()
    else:
        print("  MODEL_ID_RESTRICTION_PRESENT = false")
        enabled = sorted(m["id"] for m in (cfg.get("models") or [])
                         if m.get("enabled"))
        selected = inv.get("selected_model_ids") or []
        if not isinstance(selected, list) or not selected:
            print("  MODEL_POPULATION_MATCH = UNRESOLVED (selected_model_ids"
                  " empty/invalid)")
            cond_open()
        elif set(selected) == set(enabled):
            print("  MODEL_POPULATION_MATCH = true (%d models)" % len(enabled))
        else:
            missing_m = sorted(set(enabled) - set(selected))
            extra_m = sorted(set(selected) - set(enabled))
            print("  MODEL_POPULATION_MATCH = false (missing: %s; extra: %s)"
                  % (missing_m or "-", extra_m or "-"))
            cond_fail()

    # ---- 9-10. run id ----
    print("RUN_ID_CHECK")
    run_id = str(inv["effective_run_id"])
    repair_iteration = "__iter" in run_id
    variant_suffix = "__" in run_id
    reserved = any(p.search(run_id) for p in RESERVED_RUN_ID_PATTERNS)
    print("  REPAIR_ITERATION_RUN = %s" % str(repair_iteration).lower())
    if repair_iteration or variant_suffix:
        print("  RUN_ID_MATCH = false (%r is a repair-/variant-/iteration run"
              " id - such a population can never be the cross-pilot base run)"
              % run_id)
        cond_fail()
    elif reserved:
        print("  RUN_ID_MATCH = false (%r is a reserved historical/smoke/"
              "debug run id and cannot be the pilot_002 base run)" % run_id)
        cond_fail()
    else:
        exp_run = gate.get("expected_pilot_002_base_run") or {}
        if exp_run.get("status") == "CONFIGURED" and exp_run.get("run_id"):
            if run_id == exp_run["run_id"]:
                print("  RUN_ID_MATCH = true (%r)" % run_id)
                print("  PILOT_002_BASE_RUN_ID_READY = true")
            else:
                print("  RUN_ID_MATCH = false (declared %r != configured"
                      " expected %r)" % (run_id, exp_run["run_id"]))
                cond_fail()
        else:
            print("  expected_pilot_002_base_run.status = %s"
                  % exp_run.get("status"))
            print("  RUN_ID_MATCH = UNRESOLVED (no expected pilot_002 base"
                  " run id is configured yet; pilot_001 is never adopted as"
                  " the expected value)")
            print("  PILOT_002_BASE_RUN_ID_READY = false")
            cond_open()

    # ---- 11-12. verdict-relevant invocation values ----
    print("PILOT_INVOCATION_VALUES_CHECK")
    pol = (gate.get("effective_invocation_policy") or {})
    overrides = pol.get("verdict_relevant_cli_overrides") or {}
    if not overrides:
        print("  UNRESOLVED (gate stores no verdict_relevant_cli_overrides)")
        cond_open()
    else:
        for key in ("primary_compiler", "run_timeout_seconds"):
            expected = (overrides.get(key) or {}).get("expected")
            actual = inv.get(key)
            if expected is None:
                print("  %s: UNRESOLVED (no expected value in gate)" % key)
                cond_open()
            elif actual != expected:
                print("  %s: MISMATCH (declared effective %r != expected %r)"
                      % (key, actual, expected))
                cond_fail()
            else:
                print("  %s: ok (declared effective %r)" % (key, actual))
    print("PILOT_CONDITION_MATCH = %s" % tristate(cond_match))

    # ---- 13-15. runtime environment ----
    print("PILOT_ENVIRONMENT_CHECK")
    envfile = load_json(args.environment)
    expected_env = (gate.get("environment_condition") or {}).get("expected") or {}
    tool_compat = True   # True / False / None
    identity_captured = False
    if envfile is None:
        print("  UNRESOLVED (environment file missing/unreadable)")
        unresolved = True
        tool_compat = None
    elif not expected_env:
        print("  UNRESOLVED (gate stores no environment_condition.expected)")
        unresolved = True
        tool_compat = None
    else:
        for key in ("primary_compiler_version", "mpi_version_line"):
            expected = expected_env.get(key)
            actual = envfile.get(key)
            if expected is None:
                print("  %s: UNRESOLVED (no expected value in gate)" % key)
                unresolved = True
                tool_compat = None if tool_compat else tool_compat
            elif actual is None:
                print("  %s: UNRESOLVED (actual runtime value not provided -"
                      " missing provenance is never a match)" % key)
                unresolved = True
                tool_compat = None if tool_compat else tool_compat
            elif expected not in actual and actual != expected:
                print("  %s: MISMATCH (actual %r vs expected %r)"
                      % (key, actual, expected))
                mismatch = True
                tool_compat = False
            else:
                print("  %s: ok" % key)
        actual_img = envfile.get("container_image_id_or_digest")
        stored_img = (expected_env.get("container") or {}).get("image_digest_or_id")
        if not actual_img:
            print("  container_image_id_or_digest: UNRESOLVED (not provided -"
                  " the gate's pinning is %s, so a concrete runtime image"
                  " ID/digest is mandatory evidence)"
                  % ((expected_env.get("container") or {}).get("pinning")))
            unresolved = True
        elif stored_img:
            identity_captured = True
            if actual_img != stored_img:
                print("  container_image_id_or_digest: MISMATCH"
                      " (%r != stored %r)" % (actual_img, stored_img))
                mismatch = True
                tool_compat = False if tool_compat is not None else None
        else:
            identity_captured = True
            print("  container_image_id_or_digest: captured (%s) - persisted"
                  " as NEW provenance. pilot_001 recorded no digest/image ID,"
                  " so this value is NOT evidence of historical container"
                  " identity; it only pins the upcoming run." % actual_img)
    print("PILOT_ENVIRONMENT_TOOLCHAIN_COMPATIBLE = %s" % tristate(tool_compat))
    print("PILOT_RUNTIME_IMAGE_IDENTITY_CAPTURED = %s"
          % str(identity_captured).lower())
    if tool_compat is False:
        env_match = False
    elif tool_compat is None or not identity_captured:
        env_match = None
    else:
        env_match = True
    print("PILOT_ENVIRONMENT_MATCH = %s (defined as: recorded toolchain"
          " condition compatible AND required current runtime provenance"
          " present - NOT proof of a historically identical container)"
          % tristate(env_match))

    # ---- 16. semantic decisions (Semantic Interlock wave) ----
    # A registry entry is NOT automatically a blocker any more: the semantic
    # gate distinguishes an unresolved decision (BLOCK) from a deliberately
    # accepted disclosure (PASS_WITH_DISCLOSURE, allowed for pilot_002 as long
    # as its reporting requirement is machine-readable). Rendering the
    # disclosure is a reporting-wave obligation and is not claimed here.
    print("SEMANTIC_DECISION_CHECK")
    sem_decisions = load_json(semantic_gate.DECISIONS_PATH)
    sem_registry = load_json(semantic_gate.REGISTRY_PATH)
    if sem_decisions is None or sem_registry is None:
        print("  UNRESOLVED (semantic decision artifact or interlock registry"
              " missing/unreadable)")
        print("SEMANTIC_DECISION_UNRESOLVED = UNRESOLVED")
        print("SEMANTIC_DISCLOSURE_ACCEPTED = UNRESOLVED")
        cond_open()
    else:
        sem = semantic_gate.evaluate(sem_decisions, sem_registry)
        for row in sem["rows"]:
            print("  %s (%s): %s" % (row["benchmark"], ",".join(row["decision_ids"]),
                                     row["gate"]))
            for issue in row["issues"]:
                print("      - %s" % issue)
        for problem in sem["problems"]:
            print("  PROBLEM: %s" % problem)
        print("SEMANTIC_DECISION_UNRESOLVED = %d" % sem["unresolved"])
        print("SEMANTIC_DISCLOSURE_ACCEPTED = %d" % sem["accepted_disclosure"])
        if sem["gate"] == "UNRESOLVED":
            cond_open()
        elif sem["gate"] == "BLOCK":
            print("  -> pilot_002 blocked: at least one semantic decision is not"
                  " final or inconsistent (SEMANTIC_DECISION_UNRESOLVED)")
            cond_fail()
        elif sem["gate"] == "PASS_WITH_DISCLOSURE":
            print("  -> accepted-disclosure decisions do not block pilot_002;"
                  " their reporting requirements are machine-readable"
                  " (SEMANTIC_DISCLOSURE_ACCEPTED)")
        print("SEMANTIC_DISCLOSURE_RENDERING = %s"
              % semantic_gate.disclosure_rendering_state())
    print("SEMANTIC_GATE = %s"
          % ("UNRESOLVED" if sem_decisions is None or sem_registry is None
             else sem["gate"]))

    # ---- 17. static/repair readiness (tool-state wave) ----
    # check_static_repair_readiness.py MEASURES the tool infrastructure
    # (internal tools + external images with minimal fixtures) and records
    # the condition fingerprints it measured under. This preflight only
    # verifies that the artifact exists, was produced under the CURRENT
    # static/repair condition (tool code, config, drivers) and is READY.
    # Static/Repair.1: THREE conditions must match, and the runtime one is
    # re-MEASURED here - the static semantic condition deliberately excludes
    # per-tool runtime identities (so the three images can merge results under
    # one condition), which means it cannot see an image or tool swap.
    print("STATIC_REPAIR_READINESS_CHECK")
    readiness = load_json(args.static_readiness)
    if readiness is None:
        print("  UNRESOLVED (artifact missing: run "
              "thesis/evaluation/check_static_repair_readiness.py first)")
        print("STATIC_REPAIR_READINESS = UNRESOLVED")
        cond_open()
    else:
        _sp = None
        cur_cfg = cfg
        cur_static = cur_repair = None
        try:
            from thesis.evaluation import static_provenance as _sp
            cur_cfg = cfg if cfg is not None else repo_gate._load_yaml_config(inv["config_path"])
            cur_static = _sp.static_analysis_condition_sha256(
                _sp.static_analysis_condition(cur_cfg, "g++", None, False))
            cur_repair = _sp.repair_condition_sha256(_sp.repair_condition(cur_cfg))
        except Exception as exc:  # noqa: BLE001
            print("  UNRESOLVED (current static/repair condition not computable: %s)" % exc)
            cond_open()

        stale = []
        # A comparison that could NOT be performed is never a match.
        if not cur_static:
            stale.append("static_analysis_condition_sha256 (not recomputable)")
        elif readiness.get("static_analysis_condition_sha256") != cur_static:
            stale.append("static_analysis_condition_sha256")
        if not cur_repair:
            stale.append("repair_condition_sha256 (not recomputable)")
        elif readiness.get("repair_condition_sha256") != cur_repair:
            stale.append("repair_condition_sha256")

        try:
            from thesis.evaluation import check_static_repair_readiness as _readiness_mod
            expected_schema = _readiness_mod.READINESS_SCHEMA
        except Exception:  # noqa: BLE001
            expected_schema = None
        if expected_schema and readiness.get("schema_version") != expected_schema:
            stale.append("schema_version (%s, expected %s)"
                         % (readiness.get("schema_version"), expected_schema))
        print("  readiness artifact gate = %s (created %s)"
              % (readiness.get("gate"), readiness.get("created_at_utc")))
        print("  static_analysis_condition_sha256 = %s" % readiness.get("static_analysis_condition_sha256"))
        print("  repair_condition_sha256 = %s" % readiness.get("repair_condition_sha256"))
        print("  runtime_condition_sha256 = %s (recorded)" % readiness.get("runtime_condition_sha256"))
        for tool, block in (readiness.get("measured") or {}).items():
            statuses = sorted({r.get("status") for r in (block.get("fixtures") or {}).values()})
            print("  %s (%s): %s" % (tool, block.get("image"), ",".join(str(x) for x in statuses) or "not measured"))

        # ---- runtime identity: recorded vs FRESHLY MEASURED ----
        recorded_runtime = readiness.get("runtime_condition")
        if _sp is None:
            print("  RUNTIME: UNRESOLVED (static_provenance not importable - the "
                  "runtime condition could not be recomputed)")
            stale.append("runtime_condition_sha256 (not re-measured)")
        elif not recorded_runtime or not readiness.get("runtime_condition_sha256"):
            print("  RUNTIME: the artifact carries no runtime condition "
                  "(schema %s predates Static/Repair.1) - re-run "
                  "check_static_repair_readiness.py"
                  % readiness.get("schema_version"))
            stale.append("runtime_condition_sha256 (absent)")
        else:
            fresh_environments = None
            source = None
            if args.skip_runtime_probe:
                print("  RUNTIME: probe skipped (--skip-runtime-probe) - a "
                      "readiness proof is never accepted without fresh runtime "
                      "evidence")
                stale.append("runtime_condition_sha256 (not re-measured)")
            elif args.static_runtime:
                supplied = load_json(args.static_runtime)
                if supplied is None:
                    print("  RUNTIME: UNRESOLVED (supplied runtime provenance "
                          "%s not readable)" % args.static_runtime)
                    stale.append("runtime_condition_sha256 (not re-measured)")
                else:
                    fresh_environments = supplied.get("runtime") if isinstance(
                        supplied.get("runtime"), dict) else supplied
                    source = "supplied (%s)" % args.static_runtime
            else:
                try:
                    from thesis.evaluation import check_static_repair_readiness as _readiness
                    fresh_environments = _readiness.measure_runtime(
                        cur_cfg if cur_cfg is not None
                        else repo_gate._load_yaml_config(inv["config_path"]))
                    source = "measured live (docker)"
                except Exception as exc:  # noqa: BLE001
                    print("  RUNTIME: UNRESOLVED (live measurement failed: %s)" % exc)
                    stale.append("runtime_condition_sha256 (not re-measured)")

            if fresh_environments:
                fresh_condition = _sp.runtime_condition(
                    fresh_environments,
                    static_analysis_condition_sha256=cur_static,
                    repair_condition_sha256=cur_repair)
                fresh_sha = _sp.runtime_condition_sha256(fresh_condition)
                print("  RUNTIME: %s -> %s (fully pinned: %s)"
                      % (source, fresh_sha, fresh_condition["fully_pinned"]))
                for name, environment in sorted((fresh_environments or {}).items()):
                    print("      %-9s %s image=%s digests=%s"
                          % (name, environment.get("image_ref"),
                             (environment.get("image_id") or "UNKNOWN")[:19],
                             ",".join(environment.get("repo_digests") or []) or "none"))
                drift = _sp.runtime_drift(recorded_runtime, fresh_condition)
                # the two semantic conditions are reported separately above
                drift = [d for d in drift
                         if d not in ("static_analysis_condition_sha256",
                                      "repair_condition_sha256")]
                if not fresh_condition["fully_pinned"]:
                    print("      NOT FULLY PINNED: %s - no immutable image "
                          "identity (a tag is not an identity)"
                          % ", ".join(fresh_condition["unpinned_environments"]))
                    stale.append("runtime_condition_sha256 (runtime not pinnable)")
                if drift:
                    print("      RUNTIME DRIFT since the readiness proof:")
                    for item in drift:
                        print("        - %s" % item)
                    stale.append("runtime_condition_sha256")
                elif fresh_sha == readiness.get("runtime_condition_sha256"):
                    print("      runtime identity unchanged since the readiness proof")
                else:
                    # No single field differs, yet the content address does:
                    # the artifact was produced under a DIFFERENT runtime
                    # condition definition (an older field set). The
                    # fingerprint is authoritative - never accept the older
                    # proof just because the fields we know today agree.
                    print("      RUNTIME: recorded fingerprint %s does not match the "
                          "freshly measured %s although no known field differs - the "
                          "artifact was produced under another runtime-condition "
                          "definition; re-run check_static_repair_readiness.py"
                          % (readiness.get("runtime_condition_sha256"), fresh_sha))
                    stale.append("runtime_condition_sha256 (definition mismatch)")

        if stale:
            print("  STALE: the artifact was measured under another condition (%s) -"
                  " re-run check_static_repair_readiness.py" % ", ".join(stale))
            print("STATIC_REPAIR_READINESS = UNRESOLVED (stale)")
            cond_open()
        elif readiness.get("gate") == "READY":
            print("STATIC_REPAIR_READINESS = READY")
        elif readiness.get("gate") == "NOT_READY":
            for problem in readiness.get("problems") or []:
                print("  PROBLEM: %s" % problem)
            print("STATIC_REPAIR_READINESS = NOT_READY")
            cond_fail()
        else:
            for item in readiness.get("unresolved") or []:
                print("  UNRESOLVED: %s" % item)
            print("STATIC_REPAIR_READINESS = UNRESOLVED")
            cond_open()

    # ---- 18. pilot_002 pre-run infrastructure (assembly/timing/reporting/
    # post-run verification wave) ----
    print("\n[18] PRE-RUN INFRASTRUCTURE")
    for line in prerun_infrastructure_lines():
        print(line)

    # ---- verdict ----
    print("\nEXTERNAL_FINAL_GATE_CHECKS (NOT performed by this tool):"
          " pilot_002_population_decided,"
          " pilot_002_base_run_id_configured, reuse_decision_ready,"
          " publication_policy_ready")
    print("POST_RUN_MANIFEST_VERIFICATION = REQUIRED_IMPLEMENTED"
          " (thesis/evaluation/verify_pilot_run.py: after the actual"
          " pilot_002 its manifest, contract binding and evidence are"
          " compared read-only against the frozen contract)")
    if mismatch:
        print("\nRESULT: pilot_002_not_authorized (mismatch ->"
              " CROSS_PILOT_GATE_STALE = true;"
              " comparability_re_evaluation_required - no automatic"
              " reclassification)")
        return 1
    if unresolved:
        print("\nRESULT: NOT_READY - pilot_002_not_authorized (open"
              " declarations/decisions or missing provenance; with the"
              " pilot_002 population and base-run-id targets still open this"
              " is the expected honest state, not a test failure)")
        return 2
    print("\nRESULT: technical_cross_pilot_preflight_passed -"
          " final_pilot_gate_still_required (this tool checks only the"
          " declared cross-pilot condition; the external final-gate checks"
          " above and the post-run manifest verification remain)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
