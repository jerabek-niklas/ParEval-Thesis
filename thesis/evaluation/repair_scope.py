"""Post-run repair scope completeness (repair_scope_matrix.v1).

The frozen contract pins the repair loops a pilot run must execute:

    EXPECTED_REPAIR_LOOPS = contract.model_ids x contract.repair_plan.variants

A run is only complete when EVERY expected (model_id, variant) loop is
actually evidenced - an invocation was registered for it, its state file
exists, and every sample in it reached a productive terminal status. A valid
global `repair_evaluation` runtime stamp proves the runtime, never that the
loops existed; a single correct invocation proves membership, never
coverage. Before this module the verifier accepted "33 expected, 1 present"
as PASS.

Policies (fail-closed, verifier-only, no repair semantics):

    REPAIR_EXPECTED_SET_POLICY   the FROZEN contract is the only source of the
                                 expected set. No repair_plan -> UNRESOLVED
                                 (never a live-config fallback); enabled but
                                 unusable plan -> FAIL; disabled -> [] and
                                 NOT_APPLICABLE (the ONLY legitimate empty set).
    REPAIR_TERMINALITY_POLICY    sample-state based, reusing the productive
                                 definition run_backfill.loop_state_terminality:
                                 terminal(loop) := state.jsonl exists AND no
                                 sample is STATUS_ACTIVE. No per-loop
                                 "terminal reason" is invented; the per-status
                                 breakdown of the samples is reported instead,
                                 and loop counts are never conflated with
                                 sample counts.
    REPAIR_LOOP_STATE_SOURCE_OF_TRUTH
                                 <intermediate_dir>/<base_run_id>/<model_id>/
                                 repair/<variant>/state.jsonl, schema
                                 orchestrator.STATE_SCHEMA_VERSION, read with
                                 orchestrator.load_sample_states (the latest
                                 record per sample_id wins - the orchestrator's
                                 own read rule).

Everything here is read-only and lives in the post-run verifier: the normal
thesis reporting renderer is untouched (FUTURE_REPORTING_REQUIREMENT below).

Python 3.8 compatible.
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPAIR_EXPECTED_SET_POLICY = "repair_expected_set.v1"
REPAIR_EXPECTED_SET_RULE = "FROZEN_CONTRACT_FAIL_CLOSED"
REPAIR_MATRIX_VERSION = "repair_scope_matrix.v1"
REPAIR_TERMINALITY_POLICY = "SAMPLE_STATE_BASED"
REPAIR_LOOP_STATE_SOURCE_OF_TRUTH = (
    "<intermediate_dir>/<base_run_id>/<model_id>/repair/<variant>/state.jsonl "
    "(orchestrator.STATE_SCHEMA_VERSION, read via orchestrator.load_sample_states: latest "
    "record per sample_id; terminality via run_backfill.loop_state_terminality)")
REPAIR_LOOP_IDENTITY = "(model_id, variant)"
RUNTIME_STAMP_SUBSTITUTES_MISSING_REPAIR_LOOP = False

# Documented here ONLY. The normal reporting renderer does not render it in
# this wave (REPORTING_SEMANTICS_CHANGED = false).
FUTURE_REPORTING_REQUIREMENT = (
    "report '<n>/<n> expected repair loops reached a terminal state' (LOOP level) and, "
    "separately labelled, the SAMPLE-level terminal breakdown per productive status")

PASS = "PASS"
FAIL = "FAIL"
UNRESOLVED = "UNRESOLVED"
NOT_APPLICABLE = "NOT_APPLICABLE"

STAGE = "repair_evaluation"

CATEGORY_EXPECTED_PRESENT = "expected_and_present"
CATEGORY_EXPECTED_MISSING = "expected_missing"
CATEGORY_UNEXPECTED = "unexpected_extra"
CATEGORY_DUPLICATE = "duplicate_identity"
CATEGORY_UNKEYABLE = "unkeyable"

NARROWED = "REPAIR_SCOPE_NARROWED_BELOW_CONTRACT"

# Wave phases that PROVE _to_analyzed(N) ran for the persisted iteration N
# itself: the orchestrator writes them only at the end of / inside
# _to_analyzed (orchestrator.save_wave_state at "analyzed" /
# "analyzed_waiting_external").
PHASES_PROVING_OWN_ITERATION = ("analyzed", "analyzed_waiting_external")
# Phases the orchestrator persists for an iteration it has only just STARTED
# (_build_requests/_submit/_finish_responses/_assemble write them for
# target_iteration = N+1, and the "no assemblable responses" branch writes
# "decided" for that same N+1 without analysing it). They therefore prove
# analysis of iteration N-1 only, i.e. nothing unless N >= 2.
PHASES_PROVING_PREVIOUS_ITERATION = ("decided", "requests_built", "submitted",
                                     "responses_merged", "assembled", "done")
# Phases that indicate OUTSTANDING work once every sample is terminal.
# samples_active == 0 already proves there is nothing left to decide, so the
# only phases that still contradict the state are the ones with an UNDECIDED
# iteration: "start" (no wave progress at all) and "analyzed" (an analysis
# whose decisions were never written). Every other phase is a loop the next
# step() call would only walk to "done" - including the documented --max-wave
# / --poll stops at "decided", "responses_merged" or "assembled". Pending
# batch and pending external have their own checks.
PHASES_WITH_OUTSTANDING_WORK = ("start", "analyzed")


def wave_proves_analysis(phase: "Optional[str]", iteration: "Any") -> bool:
    """Does the persisted wave state prove that an iteration >= 1 was
    analysed (and the repair_evaluation invocation registered)?"""
    if not isinstance(iteration, int) or isinstance(iteration, bool):
        return False
    if phase in PHASES_PROVING_OWN_ITERATION and iteration >= 1:
        return True
    return phase in PHASES_PROVING_PREVIOUS_ITERATION and iteration >= 2

# How the verifier decides whether a loop that never analysed an iteration
# >= 1 still had to register a repair_evaluation invocation (see
# iteration_zero_analysis below).
ITERATION_ZERO_INVOCATION_POLICY = "CONTRACT_STAGE_COVERAGE_FAIL_CLOSED"


# ---------------------------------------------------------------------------
# expected set (frozen contract only)
# ---------------------------------------------------------------------------

def expected_repair_loops(contract: "Optional[Dict[str, Any]]") -> "OrderedDict[str, Any]":
    """The contracted repair loops, or the reason there is no usable set.

    CASE A  repair_plan absent            -> UNRESOLVED (never a live-config fallback)
    CASE B  enabled but unusable plan     -> FAIL
    CASE C  repair disabled               -> [] and NOT_APPLICABLE
    otherwise                             -> model_ids x variants, sorted
    """
    result = OrderedDict([
        ("policy", REPAIR_EXPECTED_SET_POLICY),
        ("rule", REPAIR_EXPECTED_SET_RULE),
        ("status", UNRESOLVED),
        ("reason", None),
        ("model_ids", []),
        ("variants", []),
        ("max_iterations", None),
        ("api_mode", None),
        ("api_mode_overrides", {}),
        ("external_tools", None),
        ("loops", []),
    ])
    if not contract:
        result["reason"] = "no frozen contract: the expected repair loops are unknown"
        return result
    if "repair_plan" not in contract:
        result["reason"] = ("frozen contract carries no repair_plan (pre-v2, incomplete or "
                            "damaged contract) - the expected repair loops cannot be derived "
                            "and are NOT read from a live config")
        return result
    plan = contract.get("repair_plan")
    if not isinstance(plan, dict):
        result["status"] = FAIL
        result["reason"] = "frozen contract repair_plan is not a mapping (%r)" % type(plan).__name__
        return result

    enabled = plan.get("enabled")
    if enabled is False:
        result["status"] = NOT_APPLICABLE
        result["reason"] = "repair_plan.enabled = false: no repair loop is contracted"
        return result
    if enabled is not True:
        result["status"] = FAIL
        result["reason"] = "repair_plan.enabled is %r, not a boolean" % (enabled,)
        return result

    problems = []
    notes: "List[str]" = []
    if plan.get("error"):
        problems.append("repair_plan.error: %s" % plan.get("error"))
    variants = plan.get("variants")
    if not isinstance(variants, list) or not variants:
        problems.append("repair_plan.variants missing or empty")
    elif not all(isinstance(v, str) and v for v in variants) \
            or len(set(variants)) != len(variants):
        problems.append("repair_plan.variants is not a list of distinct non-empty names: %r"
                        % (variants,))
    else:
        from thesis.repair import orchestrator

        foreign = [v for v in variants if v not in orchestrator.VARIANTS]
        if foreign:
            # RepairLoop.__init__ refuses such a variant outright: a plan that
            # names one could never be executed, so it is unusable
            problems.append("repair_plan.variants names variant(s) the productive orchestrator "
                            "refuses: %s (known: %s)"
                            % (", ".join(foreign), ", ".join(orchestrator.VARIANTS)))
    max_iterations = plan.get("max_iterations")
    if isinstance(max_iterations, bool) or not isinstance(max_iterations, int) \
            or max_iterations < 0:
        problems.append("repair_plan.max_iterations not resolvable/valid: %r" % (max_iterations,))
    elif max_iterations < 1 and plan.get("evaluates_repair_candidates"):
        # decide() stops every sample as stopped_budget AT iteration 0, so no
        # repair candidate can ever exist and the plan's own
        # evaluates_repair_candidates claim is counterfactual. The plan is
        # still RUNNABLE (every loop is expected and terminates at iteration
        # 0), so this is reported as an observation - destroying the expected
        # set over it would throw away all the evidence the matrix is for.
        notes.append("repair_plan.max_iterations = %d cannot produce a repair candidate, yet "
                     "the plan asserts evaluates_repair_candidates: the expected set stands, "
                     "every loop is expected to terminate at iteration 0"
                     % max_iterations)
    model_ids = contract.get("model_ids")
    if not isinstance(model_ids, list) or not model_ids \
            or not all(isinstance(m, str) and m for m in model_ids):
        problems.append("contract.model_ids missing, empty or unusable: %r" % (model_ids,))
    elif len(set(model_ids)) != len(model_ids):
        problems.append("contract.model_ids contains duplicates: %r" % (model_ids,))
    overrides = plan.get("api_mode_overrides")
    if overrides is not None and not isinstance(overrides, dict):
        problems.append("repair_plan.api_mode_overrides is not a mapping: %r" % (overrides,))
    expected_stages = contract.get("expected_stages")
    if isinstance(expected_stages, list) and "repair" not in expected_stages:
        problems.append("repair_plan.enabled = true but 'repair' is not among the contract's "
                        "expected_stages - the frozen contract contradicts itself")
    if problems:
        result["status"] = FAIL
        result["reason"] = "repair enabled but the frozen plan is unusable: " + "; ".join(problems)
        return result

    result["status"] = PASS
    result["notes"] = notes
    result["reason"] = "%d contracted model(s) x %d contracted variant(s)%s" % (
        len(model_ids), len(variants),
        "; " + "; ".join(notes) if notes else "")
    result["model_ids"] = sorted(model_ids)
    result["variants"] = list(variants)
    result["max_iterations"] = max_iterations
    result["api_mode"] = plan.get("api_mode")
    result["api_mode_overrides"] = dict(plan.get("api_mode_overrides") or {})
    result["external_tools"] = plan.get("external_tools")
    loops = []
    for model_id in sorted(model_ids):
        for variant in sorted(variants):
            loops.append(OrderedDict([
                ("model_id", model_id),
                ("variant", variant),
                ("max_iterations", max_iterations),
                ("expected", True),
                ("reason", "contract.model_ids contains %s and repair_plan.variants contains %s"
                           % (model_id, variant)),
            ]))
    result["loops"] = loops
    return result


def expected_repair_invocation_scopes(contract: "Optional[Dict[str, Any]]") -> "List[Tuple[str, str]]":
    expected = expected_repair_loops(contract)
    return [(loop["model_id"], loop["variant"]) for loop in expected["loops"]]



# ---------------------------------------------------------------------------
# iteration-0 analysis (does the loop register its invocation at iteration 0?)
# ---------------------------------------------------------------------------

def _variant_feedback_sources(config, variant):
    """The variant's feedback sources EXACTLY as the orchestrator resolves
    them (feedback.strategy_sources REPLACES the defaults when the config
    narrows stages.repair.strategies - a union would demand records the loop
    never asks for). Only an unresolvable variant falls back, fail-closed."""
    try:
        from thesis.repair import feedback

        return sorted(set(feedback.strategy_sources(config or {}, variant))), None
    except Exception as exc:  # noqa: BLE001 - unknown variant / unusable config
        problem = "%s: %s" % (type(exc).__name__, exc)
    try:
        from thesis.repair import feedback

        return sorted(set(feedback.DEFAULT_STRATEGY_SOURCES.get(variant) or [])), problem
    except Exception as exc:  # noqa: BLE001 - feedback module unusable
        return [], "%s: %s" % (type(exc).__name__, exc)


# `_run_analysis_stages` passes this label into run_static_analysis.run_model,
# which APPENDS it to the model's static_analysis_summary.json invocations -
# an artifact the loop never rewrites away. It is the one durable, positive
# trace that the repair loop itself analysed an iteration.
REPAIR_STATIC_INVOCATION_LABEL = "repair %s/%s iteration %d (internal static)"
_REPAIR_STATIC_LABEL = re.compile(
    r"^repair (?P<model>.+)/(?P<variant>[^/]+) iteration (?P<iteration>\d+) "
    r"\(internal static\)$")


def repair_labelled_static_invocations(config, base_run_id, model_id, variant):
    """Iterations of THIS loop that appear as a repair-written invocation in
    the BASE run's static_analysis_summary.json.

    The records leg alone cannot see an iteration-0 analysis after the fact:
    _run_analysis_stages(0) writes into the base run's own stage files, so the
    gap it filled is gone by the time the verifier looks. The label survives.
    Returns (iterations, problem); a summary that cannot be read is reported,
    never silently treated as "no repair invocation"."""
    try:
        from thesis.repair import orchestrator

        paths = orchestrator.LoopPaths(config, base_run_id, model_id, variant)
        summary_path = paths.stage_path(0, "static_analysis").parent / \
            "static_analysis_summary.json"
    except Exception as exc:  # noqa: BLE001
        return [], "%s: %s" % (type(exc).__name__, exc)
    if not summary_path.is_file():
        return [], None
    summary, error = _read_json(summary_path)
    if error:
        return [], "static_analysis_summary.json: %s" % error
    iterations: "List[int]" = []
    for invocation in (summary or {}).get("invocations") or []:
        label = (invocation or {}).get("label") if isinstance(invocation, dict) else None
        if not isinstance(label, str):
            continue
        match = _REPAIR_STATIC_LABEL.match(label)
        if match and match.group("model") == model_id and match.group("variant") == variant:
            iterations.append(int(match.group("iteration")))
    return sorted(set(iterations)), None


def productive_missing_internal_stages(config, base_run_id, model_id, variant):
    """orchestrator.RepairLoop.missing_internal_stages(0), asked directly -
    the productive definition, not a re-implementation. Read-only: it only
    loads the base run's assembly and stage records.

    A probe that cannot run at all is fail-closed (reported as missing), so a
    loop is never excused on the strength of an unanswered question."""
    try:
        from thesis.repair import orchestrator

        loop = orchestrator.RepairLoop(
            config=config, config_path="<post-run verifier>",
            profile_name="<post-run verifier>", profile={"run_id": base_run_id},
            model_config={"id": model_id}, variant=variant)
        return list(loop.missing_internal_stages(0)), None
    except Exception as exc:  # noqa: BLE001 - a probe failure is a verdict, not a crash
        return ["<probe failed>"], "%s: %s" % (type(exc).__name__, exc)


def iteration_zero_analysis(contract: "Optional[Dict[str, Any]]",
                            config: "Optional[Dict[str, Any]]",
                            variant: str,
                            base_run_id: "Optional[str]" = None,
                            model_id: "Optional[str]" = None) -> "OrderedDict[str, Any]":
    """Does the productive loop NECESSARILY run its own analysis - and with it
    register the repair_evaluation invocation - already at ITERATION 0?

    orchestrator.step() enters a fresh loop in phase 'start' and calls
    _to_analyzed(0), which runs _run_analysis_stages (and inside it
    stage_runtime.enforce_stage(..., 'repair_evaluation', ...)) whenever
    missing_internal_stages(0) is non-empty. Iteration 0 IS the base run
    (LoopPaths.iter_run_id(0) == base_run_id), so those stage records normally
    come from the BASE evaluation - but missing_internal_stages does not ask
    which stages were CONTRACTED, it asks whether a record exists for every
    assembled sample (and, for static, whether it carries every internally
    required tool). Two independent reasons therefore make iteration-0
    analysis certain, and either one is enough:

      * CONTRACT: the frozen contract does not expect a stage the variant's
        feedback needs, so the base run cannot have written its records;
      * RECORDS: the base run's iteration-0 records do not cover the model's
        assembled samples NOW - asked through the productive
        missing_internal_stages(0) itself.

    The RECORDS leg is sound in exactly the direction the CONTRACT leg cannot
    reach: a loop that advanced past phase 'start' passed _to_analyzed(0),
    which RAISES if a stage is still missing afterwards, so incomplete
    iteration-0 records mean the loop either analysed them itself or the
    artifacts contradict the productive writer. Both must keep the invocation
    required. What stays unprovable is the opposite direction - records that
    are complete today do not say WHO completed them (the stage records carry
    no writer provenance); that residual is documented, not hidden.

    Everything unknown resolves TOWARDS "the invocation is required", so a
    missing fragment is never silently excused.
    """
    stages = None
    if isinstance(contract, dict):
        raw = contract.get("expected_stages")
        if isinstance(raw, list) and all(isinstance(s, str) for s in raw):
            stages = list(raw)

    sources, source_problem = _variant_feedback_sources(config, variant)

    contract_missing: "List[str]" = []
    reasons: "List[str]" = []
    if stages is None:
        contract_missing.append("static")
        reasons.append("the frozen contract carries no usable expected_stages list")
    else:
        if "static_analysis" not in stages:
            contract_missing.append("static")
            reasons.append("static_analysis is not a contracted stage, so the base run wrote "
                           "no static records for iteration 0")
        if "correctness_verdicts" in sources and "correctness_tests" not in stages:
            contract_missing.append("correctness")
            reasons.append("%s needs correctness_verdicts but correctness_tests is not a "
                           "contracted stage" % variant)
        if "dynamic_findings" in sources and "dynamic_analysis" not in stages:
            contract_missing.append("dynamic")
            reasons.append("%s needs dynamic_findings but dynamic_analysis is not a contracted "
                           "stage" % variant)
    if source_problem is not None and not sources:
        contract_missing.append("<feedback sources unresolved>")
        reasons.append("the variant's feedback sources could not be resolved (%s)"
                       % source_problem)

    records_missing: "List[str]" = []
    records_problem = None
    labelled_iterations: "List[int]" = []
    label_problem = None
    records_probed = bool(base_run_id) and bool(model_id)
    if records_probed:
        records_missing, records_problem = productive_missing_internal_stages(
            config or {}, base_run_id, model_id, variant)
        if records_missing:
            reasons.append("the base run's iteration-0 records do not cover %s for %s "
                           "(productive missing_internal_stages(0) = %s%s)"
                           % (", ".join(records_missing), model_id, records_missing,
                              "; probe: " + records_problem if records_problem else ""))
        labelled_iterations, label_problem = repair_labelled_static_invocations(
            config or {}, base_run_id, model_id, variant)
        if labelled_iterations:
            reasons.append("the base run's static_analysis_summary.json carries this loop's "
                           "OWN repair-written invocation for iteration(s) %s - the loop "
                           "analysed and therefore registered one"
                           % ", ".join(str(i) for i in labelled_iterations))
        if label_problem:
            reasons.append("the static invocation provenance could not be read (%s)"
                           % label_problem)

    missing = sorted(set(contract_missing) | set(records_missing))
    certain = bool(missing) or bool(labelled_iterations) or bool(label_problem)
    return OrderedDict([
        ("policy", ITERATION_ZERO_INVOCATION_POLICY),
        ("variant", variant),
        ("model_id", model_id),
        ("certain", certain),
        ("missing_internal_stages", missing),
        ("contract_missing_stages", contract_missing),
        ("records_missing_stages", records_missing),
        ("repair_labelled_static_iterations", labelled_iterations),
        ("repair_label_problem", label_problem),
        ("records_probed", records_probed),
        ("records_probe_problem", records_problem),
        ("feedback_sources", sources),
        ("feedback_sources_basis", "orchestrator (feedback.strategy_sources)"
         if source_problem is None else "DEFAULT_STRATEGY_SOURCES fallback"),
        ("contract_expected_stages", stages),
        ("source_problem", source_problem),
        ("reason", "; ".join(reasons) if reasons else (
            "every stage this variant's feedback needs is contracted AND the base run's "
            "iteration-0 records cover %s's assembled samples, so a loop that stops at "
            "iteration 0 registers no invocation" % model_id if records_probed else
            "every stage this variant's feedback needs is contracted; the base run's "
            "iteration-0 RECORD coverage was not probed (no run to measure), so this is the "
            "contract leg only")),
    ])# ---------------------------------------------------------------------------
# observed invocations (effective invocation fragments)
# ---------------------------------------------------------------------------

def observed_repair_invocation_scopes(manifest: "Optional[Dict[str, Any]]",
                                      contract: "Optional[Dict[str, Any]]" = None,
                                      base_run_id: "Optional[str]" = None
                                      ) -> "List[OrderedDict]":
    """Every registered repair_evaluation invocation, resolved to its logical
    (model_id, variant) scope. An invocation that does not resolve to exactly
    one model and one variant is unkeyable."""
    from thesis.evaluation import effective_invocation as ei

    scopes: "List[OrderedDict]" = []
    for invocation in ei.invocations_for_stage(manifest, STAGE):
        model_scope = invocation.get("model_scope")
        models = list(model_scope) if isinstance(model_scope, (list, tuple)) else (
            [model_scope] if isinstance(model_scope, str) else [])
        variant = ((invocation.get("effective_values") or {}).get("variant") or {})
        variant_value = variant.get("value") if isinstance(variant, dict) else variant
        identity_problems = []
        if len(models) != 1 or not isinstance(models[0], str) or not models[0]:
            identity_problems.append("model_scope does not name exactly one model: %r"
                                     % (model_scope,))
        if not isinstance(variant_value, str) or not variant_value:
            identity_problems.append("effective_values.variant does not name one variant: %r"
                                     % (variant_value,))
        problems = []
        if base_run_id is not None and invocation.get("run_id") not in (None, base_run_id):
            problems.append("the invocation fragment belongs to run %r, not %r"
                            % (invocation.get("run_id"), base_run_id))
        if contract:
            problems += ei.check_against_contract(invocation, contract)
            recomputed = ei.invocation_fingerprint(invocation)
            if recomputed != invocation.get("invocation_sha256"):
                problems.append("the invocation fragment does not match its own fingerprint")
        scopes.append(OrderedDict([
            ("model_id", models[0] if len(models) == 1 else None),
            ("variant", variant_value if isinstance(variant_value, str) else None),
            ("keyable", not identity_problems),
            ("problems", identity_problems + problems),
            ("invocation_sha256", invocation.get("invocation_sha256")),
        ]))
    return scopes


# ---------------------------------------------------------------------------
# observed loops (the repair state source of truth on disk)
# ---------------------------------------------------------------------------

# the remainder of an iteration run dir AFTER "<base_run_id>__" - anchoring
# on the known base id keeps a base run id that itself contains "__" parseable
_ITERATION_SUFFIX = re.compile(r"^(?P<variant>[A-Za-z0-9_]+?)__iter(?P<n>-?\d+)$")

# entries of a run directory that are never a model directory
_NON_MODEL_DIRS = ("run_manifest.fragments", "run_manifest.json")


def _read_records(path: Path) -> "Tuple[List[Dict[str, Any]], Optional[str]]":
    records: "List[Dict[str, Any]]" = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            malformed = 0
            for line in handle:
                if line.strip():
                    record = json.loads(line)
                    # a state line that is not a JSON OBJECT cannot be a
                    # sample record; keeping it would let .get() crash the
                    # whole verifier instead of producing a verdict
                    if isinstance(record, dict):
                        records.append(record)
                    else:
                        malformed += 1
    except (OSError, ValueError) as error:
        return records, "%s: %s" % (type(error).__name__, error)
    if malformed:
        return records, "%d state line(s) are malformed (not JSON objects)" % malformed
    return records, None


def _read_json(path: Path) -> "Tuple[Optional[Dict[str, Any]], Optional[str]]":
    if not path.is_file():
        return None, None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, "%s: %s" % (type(error).__name__, error)
    if parsed is not None and not isinstance(parsed, dict):
        # every caller does <json>.get(...): returning a list or a string here
        # would crash the whole verifier instead of producing a verdict for
        # this loop, so a wrong SHAPE is reported like an unreadable file
        return None, "not a JSON object (%s)" % type(parsed).__name__
    return parsed, None


def iteration_artifacts(intermediate_dir: Path, base_run_id: str) -> "List[OrderedDict]":
    """Every repair-iteration run directory of the base run, parsed strictly."""
    artifacts: "List[OrderedDict]" = []
    if not intermediate_dir.is_dir():
        return artifacts
    prefix = base_run_id + "__"
    for entry in sorted(intermediate_dir.iterdir()):
        if not entry.is_dir() or not entry.name.startswith(prefix):
            continue
        match = _ITERATION_SUFFIX.match(entry.name[len(prefix):])
        # model directories only: the iteration run carries its own
        # per-writer manifest (run_manifest.fragments) next to them
        models = sorted(p.name for p in entry.iterdir()
                        if p.is_dir() and p.name not in _NON_MODEL_DIRS
                        and not p.name.startswith("run_manifest"))
        if match is None:
            artifacts.append(OrderedDict([
                ("run_dir", entry.name), ("base_run_id", None), ("variant", None),
                ("iteration", None), ("models", models),
                ("problem", "not a <base>__<variant>__iter<N> repair-iteration run of %s"
                            % base_run_id)]))
            continue
        try:
            iteration = int(match.group("n"))
        except ValueError:
            iteration = None
        artifacts.append(OrderedDict([
            ("run_dir", entry.name), ("base_run_id", base_run_id),
            ("variant", match.group("variant")), ("iteration", iteration),
            ("models", models), ("problem", None)]))
    return artifacts


def loop_inventory(config: "Dict[str, Any]", base_run_id: str,
                   expected: "Dict[str, Any]") -> "OrderedDict[str, Any]":
    """ACTUAL repair loops of the base run, keyed by (model_id, variant).

    A loop is discovered where the productive layout places its state
    (LoopPaths.repair_dir), and its identity is validated against the state
    records themselves: records that claim another run, model or variant, or
    that carry no identity, make the loop unkeyable. Nothing is inferred from
    directory names alone, from summaries or from invocation fragments."""
    from thesis.repair import orchestrator
    from thesis.repair.run_backfill import loop_state_terminality

    intermediate_dir = Path(config["outputs"]["intermediate_dir"])
    run_dir = intermediate_dir / base_run_id
    loops: "List[OrderedDict]" = []
    if run_dir.is_dir():
        for model_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
            repair_dir = model_dir / "repair"
            if not repair_dir.is_dir():
                continue
            for variant_dir in sorted(p for p in repair_dir.iterdir() if p.is_dir()):
                paths = orchestrator.LoopPaths(config, base_run_id, model_dir.name,
                                               variant_dir.name)
                state_path = paths.state_path
                wave_path = paths.wave_state_path
                pending_path = paths.pending_external_path
                if not (state_path.is_file() or wave_path.is_file() or pending_path.is_file()):
                    continue
                loops.append(_inventory_entry(base_run_id, model_dir.name, variant_dir.name,
                                              state_path, wave_path, pending_path,
                                              loop_state_terminality, orchestrator))

    # every location's identity (claimed or by path), keyable or not: a
    # missing expected loop that has ANY location is not "no state"
    locations = {(loop["model_id"], loop["variant"]) for loop in loops}
    locations |= {tuple(loop["location"].split("/", 1)) for loop in loops}

    # logical identity + duplicates
    by_key: "Dict[Tuple[str, str], List[OrderedDict]]" = {}
    for loop in loops:
        if loop["keyable"]:
            by_key.setdefault((loop["model_id"], loop["variant"]), []).append(loop)
    for key, entries in by_key.items():
        if len(entries) > 1:
            for entry in entries:
                entry["duplicate_identity"] = True
                entry["contradictions"].append(
                    "duplicate logical loop %s/%s: %d state locations resolve to it"
                    % (key[0], key[1], len(entries)))

    # iteration artifacts bound to loops
    artifacts = iteration_artifacts(intermediate_dir, base_run_id)
    return OrderedDict([("loops", loops), ("iteration_artifacts", artifacts),
                        ("locations", sorted(locations))])


def _inventory_entry(base_run_id, path_model, path_variant, state_path, wave_path,
                     pending_path, loop_state_terminality, orchestrator) -> "OrderedDict":
    contradictions: "List[str]" = []
    try:
        terminality = loop_state_terminality(state_path)
    except Exception as error:  # noqa: BLE001 - a malformed state is a verdict, not a crash
        terminality = {"state_present": state_path.is_file(), "terminal": False,
                       "samples_total": 0, "samples_active": 0, "terminal_breakdown": {},
                       "unknown_statuses": {}, "max_iteration_observed": None,
                       "invalid_iterations": 0}
        contradictions.append("state.jsonl malformed: %s: %s" % (type(error).__name__, error))
    records, read_error = _read_records(state_path) if state_path.is_file() else ([], None)
    if read_error:
        contradictions.append("state.jsonl unreadable: %s" % read_error)
    if terminality.get("invalid_iterations"):
        contradictions.append("%d sample record(s) without a valid integer iteration - the "
                              "iteration bound cannot be checked"
                              % terminality["invalid_iterations"])

    # identity: the state RECORDS are the source of truth. A loop is keyable
    # when its records agree on exactly one (model_id, variant); a location
    # that disagrees with that claim is a contradiction (FAIL) but the loop
    # still resolves - which is what lets two locations claiming the same
    # logical loop be reported as duplicate_identity instead of vanishing.
    keyable = not any("malformed" in c for c in contradictions)
    identity_model, identity_variant = path_model, path_variant
    claimed_models = sorted({str(r.get("model_id")) for r in records if "model_id" in r})
    claimed_variants = sorted({str(r.get("variant")) for r in records if "variant" in r})
    claimed_runs = sorted({str(r.get("run_id")) for r in records if "run_id" in r})
    if records:
        if len(claimed_models) != 1 or len(claimed_variants) != 1:
            keyable = False
            contradictions.append("state records do not agree on one identity (models %s, "
                                  "variants %s)" % (claimed_models or ["<none>"],
                                                    claimed_variants or ["<none>"]))
        else:
            identity_model, identity_variant = claimed_models[0], claimed_variants[0]
            if identity_model != path_model:
                contradictions.append("state records claim model %s but live under model %s"
                                      % (identity_model, path_model))
            if identity_variant != path_variant:
                contradictions.append("state records claim variant %s but live under "
                                      "variant %s" % (identity_variant, path_variant))
        if claimed_runs and (len(claimed_runs) != 1 or claimed_runs[0] != base_run_id):
            contradictions.append("state records claim run %s but live under base run %s"
                                  % (claimed_runs, base_run_id))
        if any("sample_id" not in r for r in records):
            keyable = False
            contradictions.append("state records without sample_id")
    if identity_variant not in orchestrator.VARIANTS:
        keyable = False
        contradictions.append("variant %r is not a productive repair variant (%s)"
                              % (identity_variant, ", ".join(orchestrator.VARIANTS)))
    for status, count in (terminality.get("unknown_statuses") or {}).items():
        contradictions.append("%d sample(s) in unknown status %r (not STATUS_ACTIVE and not "
                              "in orchestrator.TERMINAL_STATUSES)" % (count, status))

    # EVIDENCE OF ANALYSIS at iteration >= 1: a state record whose status
    # the orchestrator produces only by deciding an analysed iteration
    # (_decide/evaluate_stop). repair_unusable (mark_unusable: refusal,
    # exhausted reasoning budget, unusable response) and stopped_api_exhausted
    # (exhaust_request_rounds: transport) are written BEFORE any analysis of
    # that iteration and prove nothing about it. Only an analysed iteration
    # registers the repair_evaluation invocation (_run_analysis_stages).
    analysis_statuses = {orchestrator.STATUS_ACTIVE} | (
        set(orchestrator.TERMINAL_STATUSES)
        - {orchestrator.STATUS_UNUSABLE, orchestrator.STATUS_API_EXHAUSTED})
    analysed_iterations = sorted({
        r.get("iteration") for r in records
        if isinstance(r.get("iteration"), int) and not isinstance(r.get("iteration"), bool)
        and r.get("iteration") >= 1 and isinstance(r.get("status"), str)
        and r.get("status") in analysis_statuses})

    wave, wave_error = _read_json(wave_path)
    if wave_error:
        contradictions.append("wave_state.json unreadable: %s" % wave_error)
    wave = wave or {}
    phase = wave.get("phase")
    if wave:
        for field, expected_value in (("run_id", base_run_id), ("model_id", path_model),
                                      ("variant", path_variant)):
            if field in wave and wave.get(field) != expected_value:
                contradictions.append("wave_state.json claims %s=%r, path says %r"
                                      % (field, wave.get(field), expected_value))
        if phase is not None and phase not in orchestrator.PHASES:
            contradictions.append("wave_state.json phase %r is not a productive phase" % phase)
        wave_iteration = wave.get("iteration")
        if "iteration" in wave and (isinstance(wave_iteration, bool)
                                    or not isinstance(wave_iteration, int)
                                    or wave_iteration < 0):
            contradictions.append("wave_state.json iteration %r is not a non-negative integer"
                                  % (wave_iteration,))
    batch = wave.get("batch") or None
    # `submitted` is the only phase the orchestrator persists with a live
    # batch job (docstring: "submitted is only persisted in batch mode")
    pending_batch = phase == "submitted"
    pending_external = pending_path.is_file() or phase == "analyzed_waiting_external"

    return OrderedDict([
        ("model_id", identity_model),
        ("variant", identity_variant),
        ("location", "%s/%s" % (path_model, path_variant)),
        ("state_path", str(state_path)),
        ("state_present", terminality["state_present"]),
        ("terminal", terminality["terminal"]),
        ("samples_total", terminality["samples_total"]),
        ("samples_active", terminality["samples_active"]),
        ("terminal_breakdown", terminality["terminal_breakdown"]),
        ("unknown_statuses", terminality["unknown_statuses"]),
        ("max_iteration_observed", terminality["max_iteration_observed"]),
        ("analysed_iterations", analysed_iterations),
        ("wave_phase", phase),
        ("finalized", phase == "done"),
        ("wave_iteration", wave.get("iteration")),
        ("pending_batch", pending_batch),
        ("batch_id", (batch or {}).get("batch_id") if isinstance(batch, dict) else None),
        ("pending_external", pending_external),
        ("keyable", keyable),
        ("duplicate_identity", False),
        ("contradictions", contradictions),
    ])


# ---------------------------------------------------------------------------
# narrowing evidence
# ---------------------------------------------------------------------------

def narrowing_evidence(expected_keys: "List[Tuple[str, str]]",
                       invocation_keys: "List[Tuple[str, str]]",
                       loops_by_key: "Dict[Tuple[str, str], OrderedDict]",
                       locations: "Optional[List[Tuple[str, str]]]" = None
                       ) -> "OrderedDict[str, Any]":
    """Is a missing expected loop explained by a DELIBERATE scope narrowing?

    The repair CLI narrows with a single --model-id and/or a single --variant,
    so a deliberate narrowing always leaves a RECTANGLE of invocations
    (models' x variants') that is a strict subset of the contract product set,
    and the loops outside it have no state at all. Anything else (no
    invocations, a non-rectangular subset, states without invocations) is
    unexplained evidence and stays UNRESOLVED rather than speculated FAIL."""
    expected = set(expected_keys)
    observed = set(invocation_keys) & expected
    if not observed or observed == expected:
        return OrderedDict([("narrowed", False), ("reason", None)])
    models = sorted({m for m, _ in observed})
    variants = sorted({v for _, v in observed})
    rectangle = {(m, v) for m in models for v in variants}
    if rectangle != observed:
        return OrderedDict([("narrowed", False),
                            ("reason", "observed invocation scopes are not a model x variant "
                                       "rectangle - not the shape of a CLI narrowing")])
    missing = expected - observed
    known_locations = set(tuple(k) for k in (locations or []))
    if any((loops_by_key.get(key) or {}).get("state_present") or key in known_locations
           for key in missing):
        return OrderedDict([("narrowed", False),
                            ("reason", "some loops outside the invoked scope carry state or a "
                                       "state location - not a clean narrowing")])
    expected_models = sorted({m for m, _ in expected})
    expected_variants = sorted({v for _, v in expected})
    return OrderedDict([
        ("narrowed", True),
        ("reason", "%s: repair invocations cover only %s x %s of the contracted %s x %s, and "
                   "no loop outside that scope carries any state - the shape of a deliberate "
                   "--model-id/--variant narrowing" % (
                       NARROWED, models, variants, expected_models, expected_variants)),
        ("models", models),
        ("variants", variants),
    ])


# ---------------------------------------------------------------------------
# the matrix
# ---------------------------------------------------------------------------

def build_repair_matrix(contract: "Optional[Dict[str, Any]]", config: "Dict[str, Any]",
                        base_run_id: str, manifest: "Optional[Dict[str, Any]]",
                        assembled_by_model: "Optional[Dict[str, List[str]]]" = None,
                        known_by_model: "Optional[Dict[str, List[str]]]" = None
                        ) -> "OrderedDict[str, Any]":
    from thesis.repair import orchestrator

    expected = expected_repair_loops(contract)
    expected_keys = [(loop["model_id"], loop["variant"]) for loop in expected["loops"]]
    inventory = loop_inventory(config, base_run_id, expected)
    loops = inventory["loops"]
    artifacts = inventory["iteration_artifacts"]
    invocations = observed_repair_invocation_scopes(manifest, contract, base_run_id)

    loops_by_key: "Dict[Tuple[str, str], OrderedDict]" = {}
    # locations that exist but cannot serve as a loop's evidence (unkeyable
    # or duplicate): an expected loop that only has such a location is a
    # contradiction, not "no state"
    unusable_by_key: "Dict[Tuple[str, str], OrderedDict]" = {}
    for loop in loops:
        if loop["keyable"] and not loop["duplicate_identity"]:
            loops_by_key[(loop["model_id"], loop["variant"])] = loop
        else:
            unusable_by_key.setdefault((loop["model_id"], loop["variant"]), loop)
            unusable_by_key.setdefault(tuple(loop["location"].split("/", 1)), loop)

    invocation_keys = [(s["model_id"], s["variant"]) for s in invocations if s["keyable"]]
    invocation_counts: "Dict[Tuple[str, str], int]" = {}
    for key in invocation_keys:
        invocation_counts[key] = invocation_counts.get(key, 0) + 1
    # membership/coverage are only decidable against a KNOWN expected set:
    # with an UNRESOLVED or FAIL expected set nothing can be called
    # "unexpected", and the aggregate already carries that status
    set_known = expected["status"] in (PASS, NOT_APPLICABLE)
    unexpected_invocations = (sorted(set(invocation_keys) - set(expected_keys))
                              if set_known else [])
    duplicate_invocations = sorted(k for k, n in invocation_counts.items() if n > 1)
    unkeyable_invocations = [s for s in invocations if not s["keyable"]]
    contradicting_invocations = [s for s in invocations if s["keyable"] and s["problems"]]
    # coverage is decided per ROW below: a loop that never analysed an
    # iteration >= 1 legitimately has no invocation (invocation_required =
    # false), so only required-and-absent scopes count as missing
    missing_invocations: "List[Tuple[str, str]]" = []

    narrowing = narrowing_evidence(expected_keys, invocation_keys, loops_by_key,
                                   inventory["locations"])

    max_iterations = expected.get("max_iterations")
    api_mode = expected.get("api_mode")
    external_tools = expected.get("external_tools")
    overrides = expected.get("api_mode_overrides") or {}
    # a batch path exists when the frozen global mode is batch OR any frozen
    # per-provider override is batch (the contract does not map models to
    # providers, so the check is per plan, not per loop); an unknown mode
    # cannot prove the absence of a batch path
    batch_possible = (api_mode == "batch" or api_mode is None
                      or any(mode == "batch" for mode in overrides.values()))
    external_enabled = external_tools is None or bool(external_tools)

    rows: "List[OrderedDict]" = []
    limitations: "Dict[str, int]" = {}
    # per (model, variant): does iteration 0 already register the
    # invocation? The record leg of that question is per MODEL - the base run
    # can be complete for one model and partial for another.
    zero_analysis: "Dict[str, OrderedDict]" = {}
    for loop in expected["loops"]:
        key = "%s/%s" % (loop["model_id"], loop["variant"])
        if key not in zero_analysis:
            zero_analysis[key] = iteration_zero_analysis(
                contract, config, loop["variant"], base_run_id, loop["model_id"])
    for loop in expected["loops"]:
        key = (loop["model_id"], loop["variant"])
        actual = loops_by_key.get(key)
        row = _row(loop, actual, invocation_counts.get(key, 0), narrowing, max_iterations,
                   batch_possible, api_mode, external_enabled, external_tools,
                   artifacts, base_run_id, orchestrator,
                   (assembled_by_model or {}).get(loop["model_id"]),
                   _loop_sample_ids(actual),
                   unusable_by_key.get(key) if actual is None else None,
                   zero_analysis.get("%s/%s" % (loop["model_id"], loop["variant"])),
                   (known_by_model or {}).get(loop["model_id"]))
        for status, count in (row.get("terminal_breakdown") or {}).items():
            if status in orchestrator.NON_MODEL_TERMINAL_STATUSES:
                limitations[status] = limitations.get(status, 0) + count
        rows.append(row)
        if row["invocation_required"] and row["invocation_count"] == 0:
            missing_invocations.append(key)

    unexpected_loops = [l for l in loops if l["keyable"] and not l["duplicate_identity"]
                        and (l["model_id"], l["variant"]) not in set(expected_keys)]         if set_known else []
    duplicate_loops = [l for l in loops if l["duplicate_identity"]]
    unkeyable_loops = [l for l in loops if not l["keyable"]]

    # iteration artifact identity
    iteration_violations: "List[str]" = []
    expected_models = set(expected.get("model_ids") or [])
    expected_variants = set(expected.get("variants") or [])
    for artifact in artifacts:
        if artifact["problem"]:
            iteration_violations.append("%s: %s" % (artifact["run_dir"], artifact["problem"]))
            continue
        if expected["status"] == PASS:
            if artifact["variant"] not in expected_variants:
                iteration_violations.append("%s: foreign variant %r" % (artifact["run_dir"],
                                                                        artifact["variant"]))
            for model in artifact["models"]:
                if model not in expected_models:
                    iteration_violations.append("%s/%s: foreign model" % (artifact["run_dir"],
                                                                          model))
        if artifact["iteration"] is None or artifact["iteration"] < 1:
            iteration_violations.append("%s: invalid iteration value %r"
                                        % (artifact["run_dir"], artifact["iteration"]))
        elif isinstance(max_iterations, int) and artifact["iteration"] > max_iterations:
            iteration_violations.append("%s: iteration %d beyond the contracted max_iterations "
                                        "%d" % (artifact["run_dir"], artifact["iteration"],
                                                max_iterations))
    # (a duplicate (model, variant, N) identity cannot arise from distinct
    # directories, so no vacuous check is made for it)

    # sample-level totals (kept apart from loop counts)
    totals = _sample_totals(rows, orchestrator)

    # aggregate
    aggregate, detail = _aggregate(expected, rows, unexpected_loops, duplicate_loops,
                                   unkeyable_loops, unexpected_invocations,
                                   duplicate_invocations, unkeyable_invocations,
                                   contradicting_invocations, iteration_violations, loops,
                                   invocations, artifacts)

    return OrderedDict([
        ("schema_version", REPAIR_MATRIX_VERSION),
        ("expected_set_policy", REPAIR_EXPECTED_SET_POLICY),
        ("expected_set_rule", REPAIR_EXPECTED_SET_RULE),
        ("terminality_policy", REPAIR_TERMINALITY_POLICY),
        ("loop_state_source_of_truth", REPAIR_LOOP_STATE_SOURCE_OF_TRUTH),
        ("loop_identity", REPAIR_LOOP_IDENTITY),
        ("runtime_stamp_substitutes_missing_repair_loop",
         RUNTIME_STAMP_SUBSTITUTES_MISSING_REPAIR_LOOP),
        ("expected_set", OrderedDict((k, v) for k, v in expected.items() if k != "loops")),
        ("expected_loop_count", len(expected["loops"])),
        ("observed_loop_count", len(loops)),
        ("pass_loop_count", sum(1 for r in rows if r["status"] == PASS)),
        ("unresolved_loop_count", sum(1 for r in rows if r["status"] == UNRESOLVED)),
        ("fail_loop_count", sum(1 for r in rows if r["status"] == FAIL)),
        ("terminal_loop_count", sum(1 for r in rows if r["terminal"])),
        ("non_terminal_loop_count", sum(1 for r in rows if not r["terminal"])),
        ("missing", [OrderedDict([("model_id", m), ("variant", v)])
                     for m, v in expected_keys if (m, v) not in loops_by_key]),
        ("unexpected", [_identity(l) for l in unexpected_loops]),
        ("duplicate", [_identity(l) for l in duplicate_loops]),
        ("unkeyable", [OrderedDict([("model_id", l["model_id"]), ("variant", l["variant"]),
                                    ("contradictions", l["contradictions"])])
                       for l in unkeyable_loops]),
        ("narrowing", narrowing),
        ("invocations", OrderedDict([
            ("expected_scope_count", len(expected_keys)),
            ("observed_scope_count", len(invocations)),
            ("present_scope_count", sum(1 for r in rows if r["invocation_count"] >= 1)),
            ("not_required_scope_count", sum(1 for r in rows if not r["invocation_required"]
                                             and r["invocation_count"] == 0)),
            ("missing_scopes", [OrderedDict([("model_id", m), ("variant", v)])
                                for m, v in missing_invocations]),
            ("unexpected_scopes", [OrderedDict([("model_id", m), ("variant", v)])
                                   for m, v in unexpected_invocations]),
            ("duplicate_scopes", [OrderedDict([("model_id", m), ("variant", v)])
                                  for m, v in duplicate_invocations]),
            ("unkeyable", [s["problems"] for s in unkeyable_invocations]),
            ("contradicting_contract", [OrderedDict([("model_id", s["model_id"]),
                                                     ("variant", s["variant"]),
                                                     ("problems", s["problems"])])
                                        for s in contradicting_invocations]),
            ("membership", PASS if not (unexpected_invocations or unkeyable_invocations
                                        or contradicting_invocations) else FAIL),
            ("coverage", (PASS if not missing_invocations else
                          (FAIL if narrowing["narrowed"] else UNRESOLVED))
             if expected["status"] == PASS else expected["status"]),
        ])),
        ("iteration_zero_invocation_policy", ITERATION_ZERO_INVOCATION_POLICY),
        ("iteration_zero_analysis", OrderedDict(sorted(zero_analysis.items()))),
        ("iteration_artifacts", artifacts),
        ("iteration_identity_violations", iteration_violations),
        ("sample_totals", totals),
        ("limitations", OrderedDict(sorted(limitations.items()))),
        ("max_iterations_contract", max_iterations),
        ("rows", rows),
        ("status", aggregate),
        ("detail", detail),
    ])


def _identity(loop: "Dict[str, Any]") -> "OrderedDict":
    return OrderedDict([("model_id", loop["model_id"]), ("variant", loop["variant"]),
                        ("state_present", loop["state_present"]),
                        ("contradictions", loop["contradictions"])])


def _loop_sample_ids(actual) -> "Optional[List[str]]":
    if not actual or not actual.get("state_present") or not actual.get("state_path"):
        return None
    try:
        from thesis.repair import orchestrator

        return sorted(orchestrator.load_sample_states(Path(actual["state_path"])))
    except Exception:  # noqa: BLE001 - reported as malformed elsewhere
        return None


def _row(loop, actual, invocation_count, narrowing, max_iterations, batch_possible, api_mode,
         external_enabled, external_tools, artifacts, base_run_id, orchestrator,
         assembled_sample_ids=None, loop_sample_ids=None, unusable=None,
         zero_analysis=None, known_sample_ids=None) -> "OrderedDict":
    model_id, variant = loop["model_id"], loop["variant"]
    problems: "List[str]" = []
    unresolved: "List[str]" = []

    own_artifacts = [a for a in artifacts if a.get("variant") == variant
                     and model_id in (a.get("models") or [])]
    # The repair_evaluation invocation is registered by _run_analysis_stages
    # only, i.e. exactly when an iteration was ANALYSED. Three ways to reach
    # that conclusion, in fail-closed order:
    #   1. no state at all -> nothing can be proven -> required (missing ->
    #      UNRESOLVED, or FAIL under a proven narrowing);
    #   2. the state shows an ANALYSED iteration >= 1 (a decide-produced
    #      status; repair_unusable after a refusal and stopped_api_exhausted
    #      after a transport failure are written BEFORE any analysis of that
    #      iteration and prove nothing) - a fresh iteration run has no stage
    #      records at all, so its analysis always ran;
    #   3. the persisted WAVE PHASE proves _to_analyzed(N >= 1) ran even
    #      when no decided record for N survived (interrupted between
    #      analysis and decision);
    #   4. ITERATION 0: _to_analyzed(0) runs the stages whenever the BASE run
    #      did not already cover them, so a loop can register the invocation
    #      without ever analysing an iteration >= 1 - iteration_zero_analysis
    #      decides that from the contract AND from the base run's records.
    # Only a loop that fails all four legitimately has no invocation. The
    # mere existence of an iteration directory proves nothing: _assemble
    # creates it even when no response was assemblable.
    zero_certain = bool((zero_analysis or {}).get("certain"))
    wave_evidence = wave_proves_analysis((actual or {}).get("wave_phase"),
                                         (actual or {}).get("wave_iteration"))
    invocation_required = (actual is None
                           or bool((actual or {}).get("analysed_iterations"))
                           or wave_evidence
                           or zero_certain)
    if invocation_count > 1:
        invocation_status = FAIL
        problems.append("%d invocations registered for one logical scope" % invocation_count)
    elif invocation_count == 1:
        invocation_status = PASS
    elif not invocation_required and actual is not None:
        invocation_status = NOT_APPLICABLE
    else:
        invocation_status = FAIL if narrowing["narrowed"] else UNRESOLVED
        if narrowing["narrowed"]:
            why = " - " + narrowing["reason"]
        elif wave_evidence and not (actual or {}).get("analysed_iterations"):
            why = (" - wave state %r at iteration %s proves an analysed iteration >= 1"
                   % ((actual or {}).get("wave_phase"), (actual or {}).get("wave_iteration")))
        elif zero_certain and not (actual or {}).get("analysed_iterations"):
            why = (" - the loop analyses iteration 0 itself (%s), so it registered one"
                   % (zero_analysis or {}).get("reason"))
        else:
            why = ""
        (problems if narrowing["narrowed"] else unresolved).append(
            "no effective invocation for this loop%s" % why)

    if actual is None and unusable is not None:
        # a state location exists for this loop but is unusable as evidence
        state_status = FAIL
        problems.append("the loop's state location %s is unusable: %s"
                        % (unusable.get("location"),
                           "; ".join(unusable.get("contradictions") or ["unkeyable"])))
    elif actual is None:
        state_status = FAIL if narrowing["narrowed"] else UNRESOLVED
        (problems if narrowing["narrowed"] else unresolved).append(
            "no repair state for this loop (state.jsonl absent)%s"
            % (" - " + narrowing["reason"] if narrowing["narrowed"] else ""))
    else:
        state_status = PASS if actual["state_present"] else UNRESOLVED
        if not actual["state_present"]:
            unresolved.append("no state.jsonl (only wave/pending bookkeeping)")
        problems += list(actual["contradictions"])
        if actual["state_present"] and actual["samples_total"] == 0:
            unresolved.append("state.jsonl carries no sample at all")
        if not actual["terminal"]:
            unresolved.append("%d sample(s) still %s" % (actual["samples_active"],
                                                          orchestrator.STATUS_ACTIVE))
        elif actual["state_present"] and not actual.get("finalized") \
                and (actual.get("wave_phase") in PHASES_WITH_OUTSTANDING_WORK
                     or actual.get("wave_phase") is None):
            # Every sample stopped. Under REPAIR_TERMINALITY_POLICY =
            # SAMPLE_STATE_BASED the sample states decide, so a phase that
            # merely has not been rewritten to 'done' yet ('decided': step()
            # would do that on its next call, and the documented --max-wave N
            # run stops before it) is NOT a downgrade. Only a phase that
            # indicates outstanding work - or no wave bookkeeping at all -
            # contradicts the terminal samples; pending batch/external have
            # their own checks below.
            unresolved.append("all samples terminal but the loop is not finalized "
                              "(wave phase %r, expected 'done' or 'decided')"
                              % actual.get("wave_phase"))
        # the loop iterates over the model's assembled base samples, so its
        # state must cover exactly them
        if assembled_sample_ids is not None and loop_sample_ids is not None:
            assembled = set(assembled_sample_ids)
            covered = set(loop_sample_ids)
            # _decide(0)'s bootstrap marks every NON-assembled base sample as
            # repair_unusable ("initial generation not assembled") by design,
            # so the loop state legitimately covers the model's whole assembly
            # set - assembled AND skipped. Only an id that appears in no base
            # assembly entry at all is fabricated.
            known = set(known_sample_ids if known_sample_ids is not None else assembled)
            if covered - known:
                problems.append("%d sample(s) in the loop state are not base samples of %s "
                                "(no assembly entry at all)" % (len(covered - known), model_id))
            if assembled - covered:
                unresolved.append("the loop state covers %d of %d assembled samples"
                                  % (len(covered & assembled), len(assembled)))
        # iteration bound: the orchestrator decides stopped_budget AT
        # iteration == max_iterations (decide(): iteration >= max_iterations),
        # so a recorded iteration may equal but never exceed the bound
        observed_iteration = actual["max_iteration_observed"]
        if isinstance(max_iterations, int) and isinstance(observed_iteration, int) \
                and observed_iteration > max_iterations:
            problems.append("max_iteration_observed %d exceeds the contracted max_iterations %d"
                            % (observed_iteration, max_iterations))
        # the loop's OWN wave bookkeeping is bound by the same contract: the
        # orchestrator never drives a wave past max_iterations, so a higher
        # persisted iteration is a budget violation even when no sample state
        # reached it (and it is the field invocation_required reads)
        wave_iteration = actual.get("wave_iteration")
        if isinstance(max_iterations, int) and isinstance(wave_iteration, int) \
                and not isinstance(wave_iteration, bool) and wave_iteration > max_iterations:
            problems.append("wave_state.json iteration %d exceeds the contracted "
                            "max_iterations %d" % (wave_iteration, max_iterations))
        # pending batch
        if actual["pending_batch"]:
            if not batch_possible:
                problems.append("pending batch job (phase submitted) but the frozen repair "
                                "plan allows no batch path (api_mode=%r)" % (api_mode,))
            elif actual["terminal"]:
                problems.append("loop is terminal but a batch job is still pending "
                                "(phase submitted, batch %s)" % actual.get("batch_id"))
            else:
                unresolved.append("batch job pending (phase submitted) - legitimately "
                                  "unfinished in batch mode")
        # pending external
        if actual["pending_external"]:
            if not external_enabled:
                problems.append("pending external tools but the frozen repair plan enables "
                                "no external tool (external_tools=%r)" % (external_tools,))
            elif actual["terminal"]:
                problems.append("loop is terminal but external tool records are still pending")
            else:
                unresolved.append("waiting for external tool records - legitimately unfinished")

    if actual is None:
        # no usable state: an empty record so the rest of the row renders
        actual = OrderedDict([("state_present", False), ("terminal", False),
                              ("samples_total", 0), ("samples_active", 0),
                              ("terminal_breakdown", {}), ("max_iteration_observed", None),
                              ("pending_batch", False), ("pending_external", False),
                              ("batch_id", None), ("wave_phase", None), ("finalized", False),
                              ("wave_iteration", None), ("analysed_iterations", []),
                              ("state_path", None), ("contradictions", [])])

    for artifact in own_artifacts:
        if artifact["iteration"] is not None and isinstance(max_iterations, int) \
                and artifact["iteration"] > max_iterations:
            problems.append("iteration artifact %s beyond max_iterations %d"
                            % (artifact["run_dir"], max_iterations))
        # an iteration directory is created (assembled) BEFORE its samples
        # are analysed and decided, so on an in-flight loop it legitimately
        # exceeds the recorded iterations; only a TERMINAL loop must have
        # reached every iteration it produced
        if actual.get("terminal") and isinstance(actual.get("max_iteration_observed"), int) \
                and artifact["iteration"] is not None \
                and artifact["iteration"] > actual["max_iteration_observed"]:
            problems.append("iteration artifact %s exists but no sample state reached "
                            "iteration %d although the loop is terminal"
                            % (artifact["run_dir"], artifact["iteration"]))

    if problems:
        status = FAIL
    elif unresolved:
        status = UNRESOLVED
    else:
        status = PASS
    limitation = OrderedDict((s, c) for s, c in (actual.get("terminal_breakdown") or {}).items()
                             if s in orchestrator.NON_MODEL_TERMINAL_STATUSES)
    detail_parts = problems + unresolved
    if status == PASS:
        if invocation_count == 1:
            invocation_clause = "invocation present"
        elif invocation_status == NOT_APPLICABLE:
            invocation_clause = ("no invocation required (%s)"
                                 % ((zero_analysis or {}).get("reason")
                                    or "the loop analysed no iteration"))
        else:
            invocation_clause = "invocation %s" % invocation_status
        detail_parts = ["%s, state present, %d/%d sample(s) terminal, "
                        "max iteration %s <= %s" % (
                            invocation_clause,
                            actual["samples_total"], actual["samples_total"],
                            actual["max_iteration_observed"], max_iterations)]
        if limitation:
            detail_parts.append("limitation (terminal infrastructure states, not model "
                                "failures): %s" % ", ".join("%s=%d" % kv
                                                             for kv in limitation.items()))
    return OrderedDict([
        ("model_id", model_id),
        ("variant", variant),
        ("expected", True),
        ("invocation_status", invocation_status),
        ("invocation_count", invocation_count),
        ("state_status", state_status),
        ("state_path", actual.get("state_path")),
        ("terminal", bool(actual.get("terminal"))),
        ("samples_total", actual.get("samples_total", 0)),
        ("samples_active", actual.get("samples_active", 0)),
        ("terminal_breakdown", actual.get("terminal_breakdown") or {}),
        ("max_iteration_observed", actual.get("max_iteration_observed")),
        ("max_iterations_contract", max_iterations),
        ("pending_batch", bool(actual.get("pending_batch"))),
        ("pending_external", bool(actual.get("pending_external"))),
        ("wave_phase", actual.get("wave_phase")),
        ("finalized", bool(actual.get("finalized"))),
        ("analysed_iterations", list(actual.get("analysed_iterations") or [])),
        ("wave_iteration", actual.get("wave_iteration")),
        ("wave_proves_analysis", wave_evidence),
        ("iteration_zero_analysis_certain", zero_certain),
        ("iteration_zero_analysis", zero_analysis or {}),
        ("invocation_required", invocation_required),
        ("iteration_artifacts", [a["run_dir"] for a in own_artifacts]),
        ("limitations", limitation),
        ("status", status),
        ("detail", "; ".join(detail_parts)),
    ])


def _sample_totals(rows, orchestrator) -> "OrderedDict[str, Any]":
    breakdown: "Dict[str, int]" = {}
    total = active = 0
    for row in rows:
        total += int(row.get("samples_total") or 0)
        active += int(row.get("samples_active") or 0)
        for status, count in (row.get("terminal_breakdown") or {}).items():
            breakdown[status] = breakdown.get(status, 0) + int(count)
    terminal = sum(breakdown.values())
    return OrderedDict([
        ("total_repair_samples", total),
        ("terminal_repair_samples", terminal),
        ("active_repair_samples", active),
        ("sample_terminal_breakdown", OrderedDict(sorted(breakdown.items()))),
        ("productive_terminal_statuses", list(orchestrator.TERMINAL_STATUSES)),
        ("non_model_terminal_statuses", list(orchestrator.NON_MODEL_TERMINAL_STATUSES)),
        ("breakdown_sums_to_terminal_samples", terminal + active == total),
    ])


def _aggregate(expected, rows, unexpected_loops, duplicate_loops, unkeyable_loops,
               unexpected_invocations, duplicate_invocations, unkeyable_invocations,
               contradicting_invocations, iteration_violations, loops,
               all_invocations, artifacts):
    if expected["status"] == NOT_APPLICABLE:
        # repair is disabled: ANY repair evidence - a loop location (keyable
        # or not), any repair invocation (keyable or not), any iteration
        # artifact directory - contradicts the frozen plan
        if loops or all_invocations or artifacts:
            return FAIL, ("repair is disabled in the frozen contract but %d repair loop "
                          "location(s), %d repair invocation(s) and %d iteration artifact "
                          "run(s) exist" % (len(loops), len(all_invocations), len(artifacts)))
        return NOT_APPLICABLE, expected["reason"]
    if expected["status"] == UNRESOLVED:
        return UNRESOLVED, expected["reason"]
    if expected["status"] == FAIL:
        return FAIL, expected["reason"]
    problems = []
    if unexpected_loops:
        problems.append("%d unexpected loop(s): %s" % (len(unexpected_loops), ", ".join(
            "%s/%s" % (l["model_id"], l["variant"]) for l in unexpected_loops)))
    if duplicate_loops:
        problems.append("%d duplicate logical loop location(s)" % len(duplicate_loops))
    if unkeyable_loops:
        problems.append("%d unkeyable loop(s)" % len(unkeyable_loops))
    if unexpected_invocations:
        problems.append("%d invocation scope(s) outside the contract: %s"
                        % (len(unexpected_invocations),
                           ", ".join("%s/%s" % k for k in unexpected_invocations)))
    if duplicate_invocations:
        problems.append("%d duplicated invocation scope(s)" % len(duplicate_invocations))
    if unkeyable_invocations:
        problems.append("%d unkeyable invocation(s)" % len(unkeyable_invocations))
    if contradicting_invocations:
        problems.append("%d invocation(s) contradict the contract" % len(contradicting_invocations))
    if iteration_violations:
        problems.append("%d iteration identity violation(s)" % len(iteration_violations))
    failed = [r for r in rows if r["status"] == FAIL]
    unresolved = [r for r in rows if r["status"] == UNRESOLVED]
    if failed:
        problems.append("%d/%d expected loop(s) FAIL" % (len(failed), len(rows)))
    if problems:
        return FAIL, "; ".join(problems)
    if unresolved:
        return UNRESOLVED, "%d/%d expected loop(s) lack sufficient evidence" % (
            len(unresolved), len(rows))
    return PASS, "%d/%d expected repair loops present, invoked and terminal" % (len(rows), len(rows))


def matrix_table(matrix: "Dict[str, Any]") -> "List[str]":
    """A plain-text rendering FOR THE VERIFIER OUTPUT ONLY."""
    lines = ["| Model | Variant | Invocation | State | Terminal | Samples Active | Max Iter | Status |",
             "|---|---|---|---|---|---|---|---|"]
    for row in matrix.get("rows") or []:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            row["model_id"], row["variant"], row["invocation_status"], row["state_status"],
            row["terminal"], row["samples_active"], row["max_iteration_observed"],
            row["status"]))
    return lines
