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

    POST_RUN_MANIFEST_VERIFICATION = REQUIRED_NOT_IMPLEMENTED

This tool also does NOT check the external final-gate steps (pilot_002
population decision, pilot_002 base-run-id configuration, reuse decision,
publication policy, rendering of semantic disclosures). Those stay
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
    reporting requirement is machine-readable. Rendering the disclosure in
    reports is a later reporting-wave obligation
    (SEMANTIC_DISCLOSURE_RENDERING = NOT_IMPLEMENTED) and is never claimed
    here.
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--invocation", required=True,
                    help="JSON self-declaration of the PLANNED effective invocation")
    ap.add_argument("--environment", required=True,
                    help="JSON with the ACTUAL captured runtime environment values")
    ap.add_argument("--skip-repo-check", action="store_true",
                    help="skip the repo-state gate check (testing only)")
    args = ap.parse_args()

    print("INVOCATION_SELF_DECLARED = true")
    print("PREFLIGHT_IS_DECLARATION_CHECK_NOT_ENFORCEMENT = true")
    print("(a passing preflight means the DECLARED planned invocation is"
          " compatible with the gate - it is not proof of the actual later"
          " execution; POST_RUN_MANIFEST_VERIFICATION = REQUIRED_NOT_IMPLEMENTED)")

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
        print("SEMANTIC_DISCLOSURE_RENDERING = NOT_IMPLEMENTED (reporting-wave"
              " obligation; the requirement itself is verified above)")
    print("SEMANTIC_GATE = %s"
          % ("UNRESOLVED" if sem_decisions is None or sem_registry is None
             else sem["gate"]))

    # ---- verdict ----
    print("\nEXTERNAL_FINAL_GATE_CHECKS (NOT performed by this tool):"
          " pilot_002_population_decided,"
          " pilot_002_base_run_id_configured, reuse_decision_ready,"
          " publication_policy_ready, semantic_disclosure_rendering")
    print("POST_RUN_MANIFEST_VERIFICATION = REQUIRED_NOT_IMPLEMENTED"
          " (after the actual pilot_002, its run_manifest.json must be"
          " compared read-only against this gate)")
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
