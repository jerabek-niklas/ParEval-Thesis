"""Post-run repair scope completeness fixtures (Pre-Run Infrastructure.1.2).

The frozen contract pins EVERY (model_id, variant) repair loop; the verifier
must prove each one was invoked, has its state file and is terminal at the
SAMPLE level (run_backfill.loop_state_terminality - the productive
definition), and must never accept a global runtime stamp or a single
correct invocation as evidence for the whole scope.

Every fixture builds a real mini run with the productive code (contract
builder, manifest fragments, orchestrator state writers) and mutates one
property. No LLM/API call, no docker.

Run:  python thesis/evaluation/test_repair_scope.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import atomic_io, pilot_run_contract  # noqa: E402
from thesis.evaluation import manifest_fragments as mf  # noqa: E402
from thesis.evaluation import repair_scope as rs  # noqa: E402
from thesis.evaluation import run_manifest  # noqa: E402
from thesis.evaluation.test_post_run_verification import World, status_of, BENCHMARK2  # noqa: E402
from thesis.generation import common  # noqa: E402
from thesis.repair import orchestrator  # noqa: E402
from thesis.repair.run_backfill import loop_state_terminality, loops_terminated  # noqa: E402

FAILURES = []

ALL_VARIANTS = list(orchestrator.VARIANTS)
SIX_LOOPS = {"repair": {"enabled": True, "max_iterations": 2, "variants": ALL_VARIANTS}}


def check(label, condition):
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def six_loop_world(tmp, **kwargs):
    """2 contracted models x the 3 productive variants = 6 expected loops."""
    return World(Path(tmp), models=("m1", "m2"), stage_overrides=SIX_LOOPS, **kwargs)


def scope_check(report):
    return status_of(report, "repair_scope_complete")


def scope(report):
    return report["repair_scope"]


def loop_status(report, model, variant):
    return status_of(report, "repair_loop:%s/%s" % (model, variant))


def loop_dir(world, model, variant):
    return world.repair_loop(model, variant).paths.repair_dir


def refreeze(world, mutate):
    """Re-freeze the fixture contract with one mutation (a new, self-consistent
    sha) - the run's bound sha then differs, which is reported separately."""
    contract = OrderedDict(json.loads(world.contract_path.read_text(encoding="utf-8")))
    contract.pop("contract_sha256", None)
    mutate(contract)
    pilot_run_contract.freeze_contract(contract, world.contract_path, allow_draft=True)
    world.contract = pilot_run_contract.load_frozen(world.contract_path)


def _synthetic_contract(**overrides):
    contract = OrderedDict([
        ("contract_sha256", "c" * 64),
        ("model_ids", ["m1", "m2"]),
        ("expected_stages", ["generation", "assembly", "correctness_tests", "repair"]),
        ("repair_plan", OrderedDict([("enabled", True), ("variants", ALL_VARIANTS),
                                     ("max_iterations", 2), ("api_mode", "direct"),
                                     ("external_tools", ["parcoach", "llov"]),
                                     ("evaluates_repair_candidates", True)])),
    ])
    contract.update(overrides)
    return contract


# ---------------------------------------------------------------------------
# expected set: FROZEN contract only, fail-closed
# ---------------------------------------------------------------------------

def test_expected_set():
    print("== the expected repair set comes from the FROZEN contract only ==")
    missing = _synthetic_contract()
    del missing["repair_plan"]
    result = rs.expected_repair_loops(missing)
    check("CASE A: repair_plan missing -> UNRESOLVED, empty set, no live-config fallback",
          result["status"] == "UNRESOLVED" and result["loops"] == []
          and "carries no repair_plan" in result["reason"])
    check("no contract at all -> UNRESOLVED", rs.expected_repair_loops(None)["status"] == "UNRESOLVED")

    for label, plan in (("variants missing", {"enabled": True, "max_iterations": 2}),
                        ("variants empty", {"enabled": True, "variants": [], "max_iterations": 2}),
                        ("repair_plan.error", {"enabled": True, "variants": ALL_VARIANTS,
                                               "max_iterations": 2, "error": "boom"}),
                        ("max_iterations invalid", {"enabled": True, "variants": ALL_VARIANTS,
                                                    "max_iterations": "two"})):
        result = rs.expected_repair_loops(_synthetic_contract(repair_plan=plan))
        check("CASE B: enabled + %s -> FAIL, never an empty PASS set" % label,
              result["status"] == "FAIL" and result["loops"] == [])
    result = rs.expected_repair_loops(_synthetic_contract(model_ids=[]))
    check("CASE B: enabled + empty model set -> FAIL", result["status"] == "FAIL")
    plan = dict(_synthetic_contract()["repair_plan"], variants=ALL_VARIANTS + ["custom_strategy"])
    check("CASE B: a variant the productive orchestrator refuses -> FAIL (unusable plan)",
          rs.expected_repair_loops(_synthetic_contract(repair_plan=plan))["status"] == "FAIL")
    plan = dict(_synthetic_contract()["repair_plan"], max_iterations=0)
    result = rs.expected_repair_loops(_synthetic_contract(repair_plan=plan))
    check("max_iterations = 0 is a RUNNABLE iteration-0-only plan: the expected set stands "
          "and the contradiction with evaluates_repair_candidates is reported, not fatal",
          result["status"] == "PASS" and len(result["loops"]) == 6
          and any("evaluates_repair_candidates" in note for note in result["notes"])
          and "evaluates_repair_candidates" in result["reason"])
    plan = dict(plan, evaluates_repair_candidates=False)
    check("max_iterations = 0 without the evaluation claim stays a usable (iteration-0) plan",
          rs.expected_repair_loops(_synthetic_contract(repair_plan=plan))["status"] == "PASS")

    for label, broken in (("a variant entry that is not a string",
                           {"enabled": True, "max_iterations": 2,
                            "variants": [{"static_feedback": None}]}),
                          ("an unhashable variant entry (would crash set())",
                           {"enabled": True, "max_iterations": 2,
                            "variants": [["static_feedback"]]}),
                          ("api_mode_overrides that is not a mapping",
                           {"enabled": True, "max_iterations": 2, "variants": ALL_VARIANTS,
                            "api_mode_overrides": 5})):
        try:
            status = rs.expected_repair_loops(_synthetic_contract(repair_plan=broken))["status"]
        except Exception as exc:  # noqa: BLE001
            status = "CRASH(%s)" % type(exc).__name__
        check("CASE B: %s -> FAIL, never a traceback" % label, status == "FAIL")

    result = rs.expected_repair_loops(_synthetic_contract(repair_plan={"enabled": False}))
    check("CASE C: repair disabled -> [] and NOT_APPLICABLE (the only legitimate empty set)",
          result["status"] == "NOT_APPLICABLE" and result["loops"] == [])

    result = rs.expected_repair_loops(_synthetic_contract())
    keys = [(l["model_id"], l["variant"]) for l in result["loops"]]
    check("expected set = model_ids x variants, deterministic order",
          result["status"] == "PASS" and len(keys) == 6 and keys == sorted(keys)
          and all(l["expected"] and l["reason"] and l["max_iterations"] == 2
                  for l in result["loops"]))
    check("api_mode and external_tools are carried but do NOT change the set size",
          len(rs.expected_repair_loops(_synthetic_contract(
              repair_plan=dict(_synthetic_contract()["repair_plan"], api_mode="batch",
                               external_tools=[])))["loops"]) == 6)
    check("api_mode_overrides are carried from the frozen plan",
          rs.expected_repair_loops(_synthetic_contract(repair_plan=dict(
              _synthetic_contract()["repair_plan"], api_mode_overrides={"openai": "batch"})))
          ["api_mode_overrides"] == {"openai": "batch"})
    check("the policy is versioned and fail-closed",
          rs.REPAIR_EXPECTED_SET_RULE == "FROZEN_CONTRACT_FAIL_CLOSED"
          and rs.REPAIR_EXPECTED_SET_POLICY == "repair_expected_set.v1")


def test_productive_config_expected_count():
    print("== the productive config's contract view: expected loop count ==")
    from thesis.config.load_config import load_config

    config_path = REPO_ROOT / "thesis" / "config" / "config.yaml"
    config = load_config(config_path)
    contract = pilot_run_contract.build_contract(config_path, "pilot")
    result = rs.expected_repair_loops(contract)
    enabled_models = sorted(m["id"] for m in config.get("models", []) if m.get("enabled"))
    configured_variants = list(orchestrator.repair_settings(config)["variants"])
    print("   contract: %d model(s) x %d variant(s) (%s) = %d expected loop(s)"
          % (len(enabled_models), len(configured_variants), ", ".join(configured_variants),
             len(result["loops"])))
    check("expected count == enabled contracted models x configured repair variants",
          result["status"] == "PASS"
          and len(result["loops"]) == len(enabled_models) * len(configured_variants))
    check("the variants are read from the config/contract, not hardcoded",
          result["variants"] == configured_variants
          and set(configured_variants) <= set(orchestrator.VARIANTS))


# ---------------------------------------------------------------------------
# terminality: the productive definition, sample level
# ---------------------------------------------------------------------------

def test_contract_builder_repair_plan():
    print("== the contract builder freezes a self-consistent repair plan ==")
    with tempfile.TemporaryDirectory() as tmp:
        # a repair section WITHOUT `enabled`: expected_stages treats it as
        # enabled, so the frozen plan must too (no self-contradictory contract)
        world = World(Path(tmp), stage_overrides={"repair": {"max_iterations": 2,
                                                              "variants": ALL_VARIANTS}})
        plan = world.contract["repair_plan"]
        check("a present repair section without `enabled` freezes as enabled, like expected_stages",
              plan["enabled"] is True and "repair" in world.contract["expected_stages"])
        check("the frozen plan carries api_mode_overrides",
              "api_mode_overrides" in plan and plan["api_mode_overrides"] == {})
        report = world.verify()
        check("and the run verifies with all loops present", scope_check(report) == "PASS"
              and scope(report)["expected_loop_count"] == 3)
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), stage_overrides={"repair": {"enabled": False}})
        check("an explicitly disabled section freezes as disabled and is not an expected stage",
              world.contract["repair_plan"]["enabled"] is False
              and "repair" not in world.contract["expected_stages"])


def test_terminality_definition():
    print("== sample-level terminality reuses the productive definition ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "static_feedback")
        terminality = loop_state_terminality(loop.paths.state_path)
        check("A: state exists, all samples terminal -> terminal true",
              terminality["state_present"] and terminality["terminal"]
              and terminality["samples_active"] == 0 and terminality["samples_total"] == 2)
        check("E: terminal breakdown sums to samples_total",
              sum(terminality["terminal_breakdown"].values()) == terminality["samples_total"]
              and set(terminality["terminal_breakdown"]) <= set(orchestrator.TERMINAL_STATUSES))
        check("the SAME function drives run_backfill.loops_terminated (one definition)",
              loops_terminated(world.config, world.run_id, "m1") == (True, []))

        loop.append_sample_state(world.assembled("m1")[0]["sample_id"], 2,
                                 orchestrator.STATUS_ACTIVE, "fixture: still active")
        terminality = loop_state_terminality(loop.paths.state_path)
        check("B: one STATUS_ACTIVE sample -> loop not terminal (latest record wins)",
              not terminality["terminal"] and terminality["samples_active"] == 1
              and terminality["max_iteration_observed"] == 2)
        check("B: loops_terminated agrees",
              loops_terminated(world.config, world.run_id, "m1")[0] is False)

        loop.paths.state_path.unlink()
        terminality = loop_state_terminality(loop.paths.state_path)
        check("C: no state.jsonl -> not terminal, nothing counted",
              not terminality["state_present"] and not terminality["terminal"]
              and terminality["samples_total"] == 0)

        common.append_jsonl(loop.paths.state_path, {
            "schema_version": orchestrator.STATE_SCHEMA_VERSION, "run_id": world.run_id,
            "model_id": "m1", "variant": "static_feedback",
            "sample_id": world.assembled("m1")[0]["sample_id"], "iteration": 1,
            "status": "stopped_somehow", "stop_reason": "fixture"})
        terminality = loop_state_terminality(loop.paths.state_path)
        check("D: an unknown sample status is neither active nor terminal - reported",
              terminality["unknown_statuses"] == {"stopped_somehow": 1})


# ---------------------------------------------------------------------------
# loop coverage fixtures
# ---------------------------------------------------------------------------

def test_exact_all_loops():
    print("== A: 6/6 expected loops, all terminal ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        report = world.verify()
        summary = scope(report)
        check("A: repair_scope_complete PASS", scope_check(report) == "PASS")
        check("A: 6 expected, 6 observed, 6 PASS loops",
              summary["expected_loop_count"] == 6 and summary["observed_loop_count"] == 6
              and summary["pass_loop_count"] == 6)
        check("A: the whole run verifies PASS", report["status"] == "PASS")
        totals = summary["sample_totals"]
        check("F: loop counts and sample counts are separate fields",
              totals["total_repair_samples"] == 12 and totals["terminal_repair_samples"] == 12
              and totals["active_repair_samples"] == 0
              and totals["sample_terminal_breakdown"] == {orchestrator.STATUS_CLEAN: 12}
              and totals["total_repair_samples"] != summary["expected_loop_count"])
        matrix = report["repair_matrix"]
        check("the matrix has exactly one row per expected loop",
              matrix["schema_version"] == rs.REPAIR_MATRIX_VERSION
              and len(matrix["rows"]) == 6
              and sorted((r["model_id"], r["variant"]) for r in matrix["rows"])
              == sorted((m, v) for m in ("m1", "m2") for v in ALL_VARIANTS))
        row = matrix["rows"][0]
        check("every row carries the required machine-readable fields",
              all(k in row for k in ("model_id", "variant", "expected", "invocation_status",
                                     "state_status", "terminal", "samples_total",
                                     "samples_active", "terminal_breakdown",
                                     "max_iteration_observed", "max_iterations_contract",
                                     "pending_batch", "pending_external", "finalized",
                                     "analysed_iterations", "iteration_zero_analysis_certain",
                                     "invocation_required", "status", "detail")))
        check("no single per-loop terminal_reason is invented",
              "terminal_reason" not in row and "current_iteration" not in row)
        check("invocation membership and coverage both PASS",
              status_of(report, "repair_invocation_membership") == "PASS"
              and status_of(report, "repair_invocation_coverage") == "PASS")


def test_missing_loops():
    print("== B/C/D/E: missing loops, with and without narrowing evidence ==")
    with tempfile.TemporaryDirectory() as tmp:
        # B: 5/6 loops - a state vanished, every invocation exists
        world = six_loop_world(tmp)
        shutil.rmtree(loop_dir(world, "m2", "combined_feedback"))
        report = world.verify()
        check("B: 5/6 loops, no narrowing evidence -> UNRESOLVED (never PASS, not speculated FAIL)",
              scope_check(report) == "UNRESOLVED"
              and loop_status(report, "m2", "combined_feedback") == "UNRESOLVED"
              and scope(report)["unresolved_loop_count"] == 1)
        check("B: the missing loop is listed", scope(report)["expected_loop_count"] == 6
              and report["repair_matrix"]["missing"]
              == [{"model_id": "m2", "variant": "combined_feedback"}])

    with tempfile.TemporaryDirectory() as tmp:
        # C: invocations only for --variant static_feedback, states only for those
        world = World(Path(tmp), models=("m1", "m2"), stage_overrides=SIX_LOOPS,
                      repair_loops=False)
        world.skip_repair_invocations = {(m, v) for m in ("m1", "m2")
                                         for v in ("test_feedback", "combined_feedback")}
        for stage in ("stage.repair_evaluation",):
            pass
        # re-register the invocations under the narrowed scope
        _reset_repair_invocations(world)
        world.stamp_stages(only=("repair_evaluation",))
        world.write_repair_loops(only={("m1", "static_feedback"), ("m2", "static_feedback")})
        report = world.verify()
        check("C: --variant narrowing (invocations + states only for one variant) -> FAIL",
              scope_check(report) == "FAIL"
              and report["repair_matrix"]["narrowing"]["narrowed"] is True
              and rs.NARROWED in report["repair_matrix"]["narrowing"]["reason"])
        check("C: the narrowed-out loops are FAIL, the invoked ones PASS",
              loop_status(report, "m1", "test_feedback") == "FAIL"
              and loop_status(report, "m1", "static_feedback") == "PASS")
        check("C: invocation coverage is FAIL under deliberate narrowing",
              status_of(report, "repair_invocation_coverage") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        # C': --model-id narrowing: invocations + states for m1 only
        world = World(Path(tmp), models=("m1", "m2"), stage_overrides=SIX_LOOPS,
                      repair_loops=False)
        world.skip_repair_invocations = {("m2", v) for v in ALL_VARIANTS}
        _reset_repair_invocations(world)
        world.stamp_stages(only=("repair_evaluation",))
        world.write_repair_loops(only={("m1", v) for v in ALL_VARIANTS})
        report = world.verify()
        check("C': --model-id narrowing -> FAIL", scope_check(report) == "FAIL"
              and report["repair_matrix"]["narrowing"]["models"] == ["m1"])

    with tempfile.TemporaryDirectory() as tmp:
        # D: all states present, ONE invocation missing
        world = six_loop_world(tmp)
        _remove_repair_invocation(world, "m2", "test_feedback")
        report = world.verify()
        check("D: all states, one invocation missing -> UNRESOLVED (the loop has state, so this "
              "is not a clean narrowing)",
              scope_check(report) == "UNRESOLVED"
              and status_of(report, "repair_invocation_coverage") == "UNRESOLVED"
              and loop_status(report, "m2", "test_feedback") == "UNRESOLVED")
        check("D: never PASS", report["status"] != "PASS")

    with tempfile.TemporaryDirectory() as tmp:
        # E: all invocations present, one state missing
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "combined_feedback")
        loop.paths.state_path.unlink()
        report = world.verify()
        check("E: all invocations, one state missing -> UNRESOLVED",
              scope_check(report) == "UNRESOLVED"
              and loop_status(report, "m1", "combined_feedback") == "UNRESOLVED")


def _reset_repair_invocations(world):
    from thesis.evaluation import stage_runtime

    intermediate = Path(world.config["outputs"]["intermediate_dir"])
    for path in mf.fragments_dir(intermediate, world.run_id).glob("invocation.repair_evaluation*.json"):
        path.unlink()
    mf.write_snapshot(intermediate, world.run_id)
    stage_runtime.reset_cache()


def _assembly_entries(world, model):
    from thesis.assembly import assembly_provenance as ap

    return ap.load_assembly_entries(world.model_dir(model) / "assembly.jsonl")


def _remove_repair_invocation(world, model, variant):
    intermediate = Path(world.config["outputs"]["intermediate_dir"])
    removed = 0
    for path in mf.fragments_dir(intermediate, world.run_id).glob("invocation.repair_evaluation*.json"):
        content = json.loads(path.read_text(encoding="utf-8"))["content"]
        if content.get("model_scope") == [model] \
                and (content.get("effective_values") or {}).get("variant", {}).get("value") == variant:
            path.unlink()
            removed += 1
    mf.write_snapshot(intermediate, world.run_id)
    # a loop the fixture world never registered (it analyses nothing at
    # iteration 0) has nothing to lose - the invocation is absent either way
    assert removed in (0, 1), removed


def test_unexpected_duplicate_unkeyable():
    print("== F/G/H/I: unexpected, duplicate and unkeyable loops ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))  # contract: m1 x [static_feedback]
        _write_raw_loop(world, "m1", "test_feedback", claim=("m1", "test_feedback"))
        report = world.verify()
        check("F: unexpected variant loop -> FAIL", scope_check(report) == "FAIL"
              and report["repair_matrix"]["unexpected"][0]["variant"] == "test_feedback")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        _write_raw_loop(world, "m9", "static_feedback", claim=("m9", "static_feedback"))
        report = world.verify()
        check("G: unexpected model loop -> FAIL", scope_check(report) == "FAIL"
              and report["repair_matrix"]["unexpected"][0]["model_id"] == "m9")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        # a second location whose records claim the genuine (m1, static_feedback) loop
        _write_raw_loop(world, "m1", "test_feedback", claim=("m1", "static_feedback"))
        report = world.verify()
        check("H: duplicate logical (model, variant) loop -> FAIL",
              scope_check(report) == "FAIL" and len(report["repair_matrix"]["duplicate"]) == 2)

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        loop = world.repair_loop("m1", "static_feedback")
        records = [json.loads(l) for l in loop.paths.state_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        records[0]["variant"] = "combined_feedback"  # records disagree among themselves
        atomic_io.atomic_write_jsonl(loop.paths.state_path, records)
        report = world.verify()
        check("I: unkeyable loop (records disagree on their identity) -> FAIL",
              scope_check(report) == "FAIL" and len(report["repair_matrix"]["unkeyable"]) == 1)

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        _write_raw_loop(world, "m1", "bogus_variant", claim=("m1", "bogus_variant"))
        report = world.verify()
        check("I': a loop under a non-productive variant name is unkeyable -> FAIL",
              scope_check(report) == "FAIL" and report["repair_matrix"]["unkeyable"])


def _write_raw_loop(world, path_model, path_variant, claim, status=None, iteration=1):
    intermediate = Path(world.config["outputs"]["intermediate_dir"])
    path = intermediate / world.run_id / path_model / "repair" / path_variant / "state.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    for entry in world.assembled("m1"):
        common.append_jsonl(path, {
            "schema_version": orchestrator.STATE_SCHEMA_VERSION, "run_id": world.run_id,
            "model_id": claim[0], "variant": claim[1], "sample_id": entry["sample_id"],
            "iteration": iteration, "status": status or orchestrator.STATUS_CLEAN,
            "stop_reason": "fixture"})
    return path


# ---------------------------------------------------------------------------
# iteration bounds and pending contradictions
# ---------------------------------------------------------------------------

def test_iteration_and_pending():
    print("== iteration bounds and pending batch/external consistency ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp, repair_iteration=2)  # max_iterations 2
        report = world.verify()
        check("A: max_iteration_observed == max_iterations -> PASS (stopped_budget is decided AT "
              "iteration == max_iterations)", scope_check(report) == "PASS"
              and all(r["max_iteration_observed"] == 2 for r in report["repair_matrix"]["rows"]))

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp, repair_iteration=3)
        report = world.verify()
        check("B: observed iteration beyond max_iterations -> FAIL", scope_check(report) == "FAIL"
              and all(r["status"] == "FAIL" for r in report["repair_matrix"]["rows"]))

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp, repair_sample_status=orchestrator.STATUS_BUDGET,
                               repair_iteration=2)
        report = world.verify()
        check("C: stopped_budget within the bound -> PASS", scope_check(report) == "PASS"
              and scope(report)["sample_totals"]["sample_terminal_breakdown"]
              == {orchestrator.STATUS_BUDGET: 12})

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "static_feedback")
        loop.save_wave_state(2, "submitted", batch={"batch_id": "job-1"})
        report = world.verify()
        check("D: terminal loop + pending batch -> FAIL", scope_check(report) == "FAIL"
              and loop_status(report, "m1", "static_feedback") == "FAIL")

    batch_plan = {"repair": dict(SIX_LOOPS["repair"], api_mode="batch")}
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), models=("m1", "m2"), stage_overrides=batch_plan)
        loop = world.repair_loop("m1", "static_feedback")
        loop.append_sample_state(world.assembled("m1")[0]["sample_id"], 2,
                                 orchestrator.STATUS_ACTIVE, "fixture: waiting for the batch")
        loop.save_wave_state(2, "submitted", batch={"batch_id": "job-1"})
        report = world.verify()
        check("E: non-terminal + pending batch in batch mode -> UNRESOLVED (legitimately "
              "unfinished)", scope_check(report) == "UNRESOLVED"
              and loop_status(report, "m1", "static_feedback") == "UNRESOLVED")

    override_plan = {"repair": dict(SIX_LOOPS["repair"], api_mode="direct",
                                    api_mode_overrides={"mock": "batch"})}
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), models=("m1", "m2"), stage_overrides=override_plan)
        loop = world.repair_loop("m1", "static_feedback")
        loop.append_sample_state(world.assembled("m1")[0]["sample_id"], 2,
                                 orchestrator.STATUS_ACTIVE, "fixture")
        loop.save_wave_state(2, "submitted", batch={"batch_id": "job-1"})
        report = world.verify()
        check("E': global direct but a frozen per-provider override to batch -> pending batch "
              "is legitimately unfinished (UNRESOLVED, not FAIL)",
              scope_check(report) == "UNRESOLVED"
              and loop_status(report, "m1", "static_feedback") == "UNRESOLVED")

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)  # api_mode direct: no batch path
        loop = world.repair_loop("m1", "static_feedback")
        loop.append_sample_state(world.assembled("m1")[0]["sample_id"], 2,
                                 orchestrator.STATUS_ACTIVE, "fixture")
        loop.save_wave_state(2, "submitted", batch={"batch_id": "job-1"})
        report = world.verify()
        check("F: pending batch in a mode that cannot batch -> FAIL even though non-terminal",
              scope_check(report) == "FAIL" and loop_status(report, "m1", "static_feedback") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "static_feedback")
        loop.paths.pending_external_path.write_text("parcoach 2\n", encoding="utf-8")
        report = world.verify()
        check("G: terminal + pending external -> FAIL", scope_check(report) == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)  # external tools enabled by default
        loop = world.repair_loop("m1", "static_feedback")
        loop.append_sample_state(world.assembled("m1")[0]["sample_id"], 1,
                                 orchestrator.STATUS_ACTIVE, "fixture")
        loop.save_wave_state(1, "analyzed_waiting_external")
        report = world.verify()
        check("H: non-terminal + pending external with external tools enabled -> UNRESOLVED",
              scope_check(report) == "UNRESOLVED"
              and loop_status(report, "m1", "static_feedback") == "UNRESOLVED")

    no_external = {"repair": dict(SIX_LOOPS["repair"], external_tools=[])}
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), models=("m1", "m2"), stage_overrides=no_external)
        loop = world.repair_loop("m1", "static_feedback")
        loop.append_sample_state(world.assembled("m1")[0]["sample_id"], 1,
                                 orchestrator.STATUS_ACTIVE, "fixture")
        loop.paths.pending_external_path.write_text("parcoach 2\n", encoding="utf-8")
        report = world.verify()
        check("I: pending external but external_tools=[] -> FAIL", scope_check(report) == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        (intermediate / ("%s__static_feedback__iter3" % world.run_id) / "m1").mkdir(parents=True)
        (intermediate / ("%s__static_feedback__iter1" % world.run_id) / "m7").mkdir(parents=True)
        (intermediate / ("%s__weird" % world.run_id)).mkdir(parents=True)
        report = world.verify()
        violations = report["repair_matrix"]["iteration_identity_violations"]
        check("iteration artifacts beyond the policy, foreign model, unparseable -> FAIL",
              status_of(report, "repair_iteration_identity") == "FAIL" and len(violations) >= 3)


# ---------------------------------------------------------------------------
# infrastructure terminal states, runtime stamp, legacy contracts
# ---------------------------------------------------------------------------

def _iteration_dir(world, variant, iteration, model="m1", with_manifest=True):
    """The PRODUCTIVE iteration run layout: <base>__<variant>__iter<N>/<model>/
    next to the iteration run's own per-writer manifest directory."""
    intermediate = Path(world.config["outputs"]["intermediate_dir"])
    run_dir = intermediate / ("%s__%s__iter%d" % (world.run_id, variant, iteration))
    (run_dir / model).mkdir(parents=True, exist_ok=True)
    if with_manifest:
        (run_dir / mf.FRAGMENTS_DIR_NAME).mkdir(parents=True, exist_ok=True)
        (run_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
    return run_dir


def test_productive_layout_and_writer_semantics():
    print("== the verifier follows the productive layout and writer semantics ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        _iteration_dir(world, "static_feedback", 1, "m1")
        _iteration_dir(world, "test_feedback", 1, "m2")
        report = world.verify()
        check("a complete run WITH productive iteration runs (incl. their run_manifest.fragments) "
              "-> PASS, no 'foreign model'", scope_check(report) == "PASS"
              and status_of(report, "repair_iteration_identity") == "PASS")

    with tempfile.TemporaryDirectory() as tmp:
        # in flight: iteration 1 assembled, samples still at iteration 0
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "static_feedback")
        for entry in world.assembled("m1"):
            loop.append_sample_state(entry["sample_id"], 0, orchestrator.STATUS_ACTIVE,
                                     "fixture: repair requested")
        loop.save_wave_state(1, "assembled")
        _iteration_dir(world, "static_feedback", 1, "m1")
        report = world.verify()
        check("an in-flight loop (iteration dir exists, samples not yet decided at that "
              "iteration) -> UNRESOLVED, never FAIL", scope_check(report) == "UNRESOLVED"
              and loop_status(report, "m1", "static_feedback") == "UNRESOLVED")

    with tempfile.TemporaryDirectory() as tmp:
        # Every sample stopped at iteration 0. Whether the loop nevertheless
        # ran _run_analysis_stages(0) - and with it registered its
        # repair_evaluation invocation - is decided by the CONTRACT, not by
        # the iteration: step() enters phase 'start' with _to_analyzed(0),
        # which analyses whatever the BASE run did not cover. This fixture's
        # contract has no dynamic_analysis stage, so static_feedback (compiler
        # + static findings) is fully covered while test_feedback and
        # combined_feedback (dynamic_findings) must analyse iteration 0
        # themselves.
        world = six_loop_world(tmp, repair_iteration=0)
        for model in ("m1", "m2"):
            _remove_repair_invocation(world, model, "static_feedback")
        report = world.verify()
        rows = {(r["model_id"], r["variant"]): r for r in report["repair_matrix"]["rows"]}
        check("a loop that stops at iteration 0 whose feedback the base run fully covered "
              "needs NO repair invocation -> PASS with invocation NOT_APPLICABLE",
              report["status"] == "PASS" and scope_check(report) == "PASS"
              and all(rows[(m, "static_feedback")]["invocation_status"] == "NOT_APPLICABLE"
                      and not rows[(m, "static_feedback")]["invocation_required"]
                      and not rows[(m, "static_feedback")]["iteration_zero_analysis_certain"]
                      for m in ("m1", "m2")))
        check("... and the top-level invocation COVERAGE check agrees (no false UNRESOLVED)",
              status_of(report, "repair_invocation_coverage") == "PASS")
        check("... while the variants whose feedback the contract does NOT cover are recorded "
              "as analysing iteration 0 themselves",
              all(rows[(m, v)]["iteration_zero_analysis_certain"]
                  and rows[(m, v)]["invocation_required"]
                  for m in ("m1", "m2") for v in ("test_feedback", "combined_feedback")))
        zero = report["repair_matrix"]["iteration_zero_analysis"]
        check("the iteration-0 determination is machine-readable per (model, variant), with "
              "its reason and both legs separated",
              report["repair_matrix"]["iteration_zero_invocation_policy"]
              == rs.ITERATION_ZERO_INVOCATION_POLICY
              and set(zero) == {"%s/%s" % (m, v) for m in ("m1", "m2") for v in ALL_VARIANTS}
              and zero["m1/combined_feedback"]["missing_internal_stages"] == ["dynamic"]
              and zero["m1/combined_feedback"]["contract_missing_stages"] == ["dynamic"]
              and zero["m1/combined_feedback"]["records_missing_stages"] == ["dynamic"]
              and zero["m1/static_feedback"]["missing_internal_stages"] == []
              and zero["m1/static_feedback"]["records_probed"]
              and "dynamic_findings" in zero["m1/combined_feedback"]["feedback_sources"])
        check("the NOT_APPLICABLE row's own evidence does not claim an invocation it has not",
              all("invocation present" not in rows[(m, "static_feedback")]["detail"]
                  and "no invocation required" in rows[(m, "static_feedback")]["detail"]
                  for m in ("m1", "m2")))
        coverage = next(c for c in report["checks"]
                        if c["check"] == "repair_invocation_coverage")
        check("... and the coverage evidence reports the ACTUAL counts",
              "4/6 expected repair invocation scope(s) present" in coverage["detail"]
              and "2 not required" in coverage["detail"]
              and "0 required and absent" in coverage["detail"])

    with tempfile.TemporaryDirectory() as tmp:
        # REGRESSION (iteration-0 invocation registration): _to_analyzed(0)
        # runs the analysis stages the base run did not cover, so a loop can
        # register its repair_evaluation invocation at ITERATION 0 and never
        # analyse an iteration >= 1. A lost invocation must NOT be excused as
        # NOT_APPLICABLE just because the state stops at iteration 0.
        world = six_loop_world(tmp, repair_iteration=0)
        _remove_repair_invocation(world, "m2", "combined_feedback")
        report = world.verify()
        row = next(r for r in report["repair_matrix"]["rows"]
                   if (r["model_id"], r["variant"]) == ("m2", "combined_feedback"))
        check("a loop that analysed ITERATION 0 itself (contract without dynamic_analysis) "
              "still requires its invocation -> UNRESOLVED, never PASS on a lost invocation",
              report["status"] != "PASS" and scope_check(report) == "UNRESOLVED"
              and row["analysed_iterations"] == [] and row["iteration_zero_analysis_certain"]
              and row["invocation_required"] and row["invocation_status"] == "UNRESOLVED"
              and row["status"] == "UNRESOLVED"
              and status_of(report, "repair_invocation_coverage") == "UNRESOLVED")
        check("... and the detail names the iteration-0 reason, not a generic absence",
              "iteration 0" in row["detail"] and "dynamic_analysis" in row["detail"])

    with tempfile.TemporaryDirectory() as tmp:
        # REGRESSION (record leg): dynamic_analysis IS a contracted stage, so
        # the contract alone says "the base run covered iteration 0" - but no
        # dynamic record exists for any sample, and missing_internal_stages
        # asks for RECORDS, not for stage names. The productive loop therefore
        # analyses iteration 0 and registers its invocation; a lost fragment
        # must not be excused.
        world = World(Path(tmp), models=("m1", "m2"), repair_iteration=0,
                      stage_overrides=dict(SIX_LOOPS,
                                           dynamic_analysis={"enabled": True, "tools": {}}))
        # the base run never produced m2's dynamic records (nor their history)
        (world.model_dir("m2") / "dynamic_analysis.jsonl").unlink()
        (world.model_dir("m2") / "dynamic_analysis_summary.json").unlink()
        missing = rs.productive_missing_internal_stages(
            world.config, world.run_id, "m2", "combined_feedback")[0]
        _remove_repair_invocation(world, "m2", "combined_feedback")
        report = world.verify()
        row = next(r for r in report["repair_matrix"]["rows"]
                   if (r["model_id"], r["variant"]) == ("m2", "combined_feedback"))
        zero = row["iteration_zero_analysis"]
        check("a CONTRACTED stage without records still forces the iteration-0 analysis "
              "(the productive missing_internal_stages(0) is asked, not the stage list)",
              missing == ["dynamic"] and zero["contract_missing_stages"] == []
              and zero["records_missing_stages"] == ["dynamic"] and zero["certain"])
        check("... so the lost invocation is NOT excused as NOT_APPLICABLE",
              row["analysed_iterations"] == [] and row["invocation_required"]
              and row["invocation_status"] == "UNRESOLVED" and row["status"] == "UNRESOLVED"
              and scope_check(report) == "UNRESOLVED" and report["status"] != "PASS")
        check("... while the same run's static_feedback loops stay NOT_APPLICABLE",
              all(r["invocation_status"] in ("PASS", "NOT_APPLICABLE")
                  for r in report["repair_matrix"]["rows"] if r["variant"] == "static_feedback"))

    with tempfile.TemporaryDirectory() as tmp:
        # the config may NARROW a variant's feedback sources -
        # feedback.strategy_sources REPLACES the defaults, so the loop then
        # never asks for dynamic findings and never analyses iteration 0. The
        # verifier must resolve the sources exactly as the orchestrator does,
        # or a complete run could never reach PASS.
        narrowed = dict(SIX_LOOPS)
        narrowed["repair"] = dict(SIX_LOOPS["repair"], strategies={
            "combined_feedback": {"sources": ["compiler_errors", "static_findings"]}})
        world = World(Path(tmp), models=("m1", "m2"), stage_overrides=narrowed,
                      repair_iteration=0)
        sources = rs.iteration_zero_analysis(world.contract, world.config,
                                             "combined_feedback")["feedback_sources"]
        _remove_repair_invocation(world, "m2", "combined_feedback")
        report = world.verify()
        row = next(r for r in report["repair_matrix"]["rows"]
                   if (r["model_id"], r["variant"]) == ("m2", "combined_feedback"))
        check("a config that narrows stages.repair.strategies REPLACES the default sources "
              "(no union), so the loop is not asked for records it never needs",
              "dynamic_findings" not in sources and sources == ["compiler_errors",
                                                                "static_findings"])
        check("... and a loop that stops at iteration 0 under that plan verifies PASS",
              report["status"] == "PASS" and scope_check(report) == "PASS"
              and row["status"] == "PASS" and row["invocation_status"] == "NOT_APPLICABLE"
              and not row["iteration_zero_analysis_certain"])

    with tempfile.TemporaryDirectory() as tmp:
        # a state line that is not a JSON object must produce a VERDICT
        world = six_loop_world(tmp)
        path = world.repair_loop("m1", "static_feedback").paths.state_path
        with path.open("a", encoding="utf-8") as handle:
            handle.write('[1, 2, 3]\n')
        try:
            report = world.verify()
            status = loop_status(report, "m1", "static_feedback")
            overall = report["status"]
        except Exception as exc:  # noqa: BLE001
            status, overall = "CRASH(%s)" % type(exc).__name__, "CRASH"
        check("a state line that is not a JSON object -> FAIL verdict, no traceback",
              status == "FAIL" and overall == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        # ... and neither does a record whose status is not a string
        world = six_loop_world(tmp)
        path = world.repair_loop("m1", "static_feedback").paths.state_path
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"schema_version": orchestrator.STATE_SCHEMA_VERSION,
                                     "run_id": world.run_id, "model_id": "m1",
                                     "variant": "static_feedback", "sample_id": "s-broken",
                                     "iteration": 1, "status": {"not": "a string"}}) + "\n")
        try:
            report = world.verify()
            status = loop_status(report, "m1", "static_feedback")
        except Exception as exc:  # noqa: BLE001
            status = "CRASH(%s)" % type(exc).__name__
        check("a record whose status is not a string -> verdict, no traceback",
              status in ("FAIL", "UNRESOLVED"))


    with tempfile.TemporaryDirectory() as tmp:
        # POSITIVE PROVENANCE: the loop's own iteration-0 static analysis is
        # LABELLED in the base run's static_analysis_summary.json
        # (_run_analysis_stages passes invocation_label into
        # run_static_analysis.run_model, which appends it). The records leg
        # cannot see that analysis afterwards - it wrote the very records it
        # filled - but the label survives, so the invocation stays required.
        src = (REPO_ROOT / "thesis" / "repair" / "orchestrator.py").read_text(encoding="utf-8")
        check("the label the verifier looks for is the one the orchestrator writes",
              rs.REPAIR_STATIC_INVOCATION_LABEL == "repair %s/%s iteration %d (internal static)"
              and 'invocation_label="repair %s/%s iteration %d (internal static)"' in src)
        world = six_loop_world(tmp, repair_iteration=0)
        summary = world.model_dir("m1") / "static_analysis_summary.json"
        summary.write_text(json.dumps({
            "schema_version": "static_analysis_summary.v3", "model_id": "m1",
            "invocations": [
                {"label": "run_static_analysis --tools compiler"},
                {"label": rs.REPAIR_STATIC_INVOCATION_LABEL % ("m1", "static_feedback", 0)},
            ]}), encoding="utf-8")
        _remove_repair_invocation(world, "m1", "static_feedback")
        report = world.verify()
        row = next(r for r in report["repair_matrix"]["rows"]
                   if (r["model_id"], r["variant"]) == ("m1", "static_feedback"))
        zero = row["iteration_zero_analysis"]
        check("a repair-written static invocation for iteration 0 proves the loop analysed - "
              "the lost invocation is not excused even though the records are complete now",
              zero["repair_labelled_static_iterations"] == [0]
              and zero["records_missing_stages"] == [] and zero["certain"]
              and row["invocation_required"] and row["invocation_status"] == "UNRESOLVED"
              and report["status"] != "PASS")
        check("... and the label of ANOTHER loop does not implicate this one",
              all(not r["iteration_zero_analysis"]["repair_labelled_static_iterations"]
                  for r in report["repair_matrix"]["rows"]
                  if (r["model_id"], r["variant"]) != ("m1", "static_feedback")))

    with tempfile.TemporaryDirectory() as tmp:
        # the base run's NON-assembled samples belong in the loop state:
        # _decide(0)'s bootstrap marks them repair_unusable by design. One
        # provider timeout must not FAIL every loop of that model.
        world = World(Path(tmp), models=("m1", "m2"), stage_overrides=SIX_LOOPS,
                      unsuccessful_generations=[("m1", BENCHMARK2)])
        skipped = sorted({e["sample_id"] for e in _assembly_entries(world, "m1")}
                         - {e["sample_id"] for e in world.assembled("m1")})
        for variant in ALL_VARIANTS:
            loop = world.repair_loop("m1", variant)
            for sid in skipped:
                loop.mark_unusable(sid, 0, "initial generation not assembled (fixture)")
        report = world.verify()
        check("a base sample the assembler SKIPPED is legitimately in the loop state "
              "(repair_unusable@0) -> PASS, not 'not a base sample'",
              len(skipped) == 1 and report["status"] == "PASS"
              and scope_check(report) == "PASS"
              and all(loop_status(report, "m1", v) == "PASS" for v in ALL_VARIANTS))
        loop = world.repair_loop("m2", "static_feedback")
        loop.append_sample_state("m2__ghost__sample_0", 0, orchestrator.STATUS_CLEAN, "fixture")
        report = world.verify()
        check("... while an id with no assembly entry at all is still FAIL",
              loop_status(report, "m2", "static_feedback") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        # the wave iteration is evidence, so it is bound by the same contract
        world = six_loop_world(tmp)
        world.repair_loop("m1", "static_feedback").save_wave_state(3, "done")  # max_iterations 2
        report = world.verify()
        row = next(r for r in report["repair_matrix"]["rows"]
                   if (r["model_id"], r["variant"]) == ("m1", "static_feedback"))
        check("a persisted wave iteration beyond the contracted max_iterations -> FAIL",
              row["status"] == "FAIL" and scope_check(report) == "FAIL"
              and "wave_state.json iteration 3 exceeds" in row["detail"])

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        wave = world.repair_loop("m1", "static_feedback").paths.wave_state_path
        wave.write_text(json.dumps({"run_id": world.run_id, "model_id": "m1",
                                    "variant": "static_feedback", "phase": "done",
                                    "iteration": "1"}), encoding="utf-8")
        report = world.verify()
        check("a wave iteration that is not an integer is a contradiction, not a silent False",
              loop_status(report, "m1", "static_feedback") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        world.repair_loop("m1", "static_feedback").paths.wave_state_path.write_text(
            "[1, 2, 3]", encoding="utf-8")
        try:
            report = world.verify()
            status = loop_status(report, "m1", "static_feedback")
        except Exception as exc:  # noqa: BLE001
            status = "CRASH(%s)" % type(exc).__name__
        check("a wave_state.json that is valid JSON but not an object -> verdict, no traceback",
              status == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        # END-TO-END: every contracted loop legitimately stops at iteration 0,
        # so the productive orchestrator registers NO repair_evaluation at all
        # - neither a per-loop invocation nor the global runtime stamp. The
        # generic wave-1.1 checks must not contradict the matrix that proves it.
        world = World(Path(tmp), repair_iteration=0, skip_stamps=("repair_evaluation",))
        _reset_repair_invocations(world)
        report = world.verify()
        stage_checks = {c["check"]: c["status"] for c in report["checks"]
                        if "repair_evaluation" in c["check"]}
        check("a run whose every loop stops at iteration 0 verifies PASS end to end "
              "(the global repair_evaluation expectation is reconciled, not contradicted)",
              report["status"] == "PASS" and scope_check(report) == "PASS"
              and stage_checks.get("stage_runtime:repair_evaluation.main") == "NOT_APPLICABLE"
              and stage_checks.get("effective_invocation:repair_evaluation") == "NOT_APPLICABLE")

    with tempfile.TemporaryDirectory() as tmp:
        # ... but as soon as ONE loop analysed an iteration, the missing stamp
        # is a real gap again
        world = World(Path(tmp), repair_iteration=1, skip_stamps=("repair_evaluation",))
        _reset_repair_invocations(world)
        report = world.verify()
        stage_checks = {c["check"]: c["status"] for c in report["checks"]
                        if "repair_evaluation" in c["check"]}
        check("... and a run whose loop DID analyse keeps the missing stamp unresolved",
              report["status"] != "PASS"
              and stage_checks.get("stage_runtime:repair_evaluation.main") == "UNRESOLVED"
              and stage_checks.get("effective_invocation:repair_evaluation") == "UNRESOLVED")

    with tempfile.TemporaryDirectory() as tmp:
        # the realistic mix: five loops analysed iteration 1 (invocation
        # present), ONE stopped every sample at iteration 0 without ever
        # analysing anything (static_feedback: fully covered by the base run,
        # so no invocation) - the WHOLE run must verify PASS
        world = six_loop_world(tmp)
        world.write_repair_loops(only={("m2", "static_feedback")}, iteration=0)
        _remove_repair_invocation(world, "m2", "static_feedback")
        report = world.verify()
        check("a mixed run (5 loops at iteration 1, 1 loop stopped at iteration 0 without an "
              "invocation) verifies PASS overall",
              report["status"] == "PASS" and scope_check(report) == "PASS"
              and loop_status(report, "m2", "static_feedback") == "PASS"
              and status_of(report, "repair_invocation_coverage") == "PASS")
    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)  # iteration 1: an analysis ran, invocations are required
        _reset_repair_invocations(world)
        report = world.verify()
        check("loops that ANALYSED iteration >= 1 DO require their invocation -> UNRESOLVED",
              scope_check(report) == "UNRESOLVED"
              and all(r["invocation_required"] and r["invocation_status"] == "UNRESOLVED"
                      and r["analysed_iterations"] == [1]
                      for r in report["repair_matrix"]["rows"]))

    # the orchestrator writes repair_unusable / stopped_api_exhausted at
    # iteration N BEFORE any analysis of N (refusal, exhausted reasoning
    # budget, transport failure) and then finishes the loop without ever
    # running _run_analysis_stages: complete, and legitimately without an
    # invocation - even though an iteration directory exists
    for status, label in ((orchestrator.STATUS_UNUSABLE, "repair_unusable after a refusal"),
                          (orchestrator.STATUS_API_EXHAUSTED, "stopped_api_exhausted")):
        with tempfile.TemporaryDirectory() as tmp:
            world = six_loop_world(tmp)
            loop = world.repair_loop("m1", "static_feedback")
            loop.paths.state_path.unlink()
            a, b = [e["sample_id"] for e in world.assembled("m1")]
            loop.append_sample_state(a, 0, orchestrator.STATUS_CLEAN, "fixture: clean at 0")
            loop.append_sample_state(b, 0, orchestrator.STATUS_ACTIVE, "fixture: repair requested")
            loop.append_sample_state(b, 1, status, "fixture: %s at 1, nothing analysed" % label)
            loop.save_wave_state(1, "done")
            _iteration_dir(world, "static_feedback", 1, "m1")
            _remove_repair_invocation(world, "m1", "static_feedback")
            report = world.verify()
            row = next(r for r in report["repair_matrix"]["rows"]
                       if (r["model_id"], r["variant"]) == ("m1", "static_feedback"))
            check("%s at iteration 1 without analysis: complete loop needs no invocation -> "
                  "PASS overall" % label,
                  report["status"] == "PASS" and scope_check(report) == "PASS"
                  and row["status"] == "PASS" and row["invocation_status"] == "NOT_APPLICABLE"
                  and not row["invocation_required"] and row["analysed_iterations"] == []
                  and row["terminal"] and row["max_iteration_observed"] == 1)
    with tempfile.TemporaryDirectory() as tmp:
        # ... but an ANALYSED iteration 1 (a decide-produced status) still requires it
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "static_feedback")
        loop.paths.state_path.unlink()
        a, b = [e["sample_id"] for e in world.assembled("m1")]
        loop.append_sample_state(a, 0, orchestrator.STATUS_CLEAN, "fixture")
        loop.append_sample_state(b, 1, orchestrator.STATUS_ACTIVE, "fixture: analysed at 1")
        loop.append_sample_state(b, 2, orchestrator.STATUS_UNUSABLE, "fixture: refused at 2")
        loop.save_wave_state(2, "done")
        _remove_repair_invocation(world, "m1", "static_feedback")
        report = world.verify()
        row = next(r for r in report["repair_matrix"]["rows"]
                   if (r["model_id"], r["variant"]) == ("m1", "static_feedback"))
        check("a decide-produced record at iteration >= 1 (analysis ran) keeps the invocation "
              "required even if the latest record is repair_unusable",
              row["invocation_required"] and row["analysed_iterations"] == [1]
              and row["status"] == "UNRESOLVED")

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "static_feedback")
        text = loop.paths.state_path.read_text(encoding="utf-8")
        loop.paths.state_path.write_text(text[: len(text) // 2], encoding="utf-8")
        try:
            report = world.verify()
            check("a malformed state.jsonl -> FAIL verdict, no traceback",
                  scope_check(report) == "FAIL"
                  and loop_status(report, "m1", "static_feedback") == "FAIL")
        except Exception as error:  # noqa: BLE001
            check("a malformed state.jsonl -> FAIL verdict, no traceback (raised %s)"
                  % type(error).__name__, False)

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "static_feedback")
        entry = world.assembled("m1")[0]
        common.append_jsonl(loop.paths.state_path, {
            "schema_version": orchestrator.STATE_SCHEMA_VERSION, "run_id": world.run_id,
            "model_id": "m1", "variant": "static_feedback", "sample_id": entry["sample_id"],
            "status": orchestrator.STATUS_CLEAN, "stop_reason": "fixture: no iteration"})
        report = world.verify()
        check("a sample record without a valid iteration cannot bypass the bound -> FAIL",
              loop_status(report, "m1", "static_feedback") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        # a base run id with a '__' variant suffix is refused by the contract
        # builder since the pilot_002 freeze (every '__' names a variant /
        # iteration population); the iteration-run parsing is exercised on a
        # base id with single underscores
        world = World(Path(tmp), run_id="pilot_x_fixture", models=("m1", "m2"),
                      stage_overrides=SIX_LOOPS)
        _iteration_dir(world, "combined_feedback", 1, "m2")
        report = world.verify()
        check("a base run id with single underscores parses its iteration runs -> PASS",
              scope_check(report) == "PASS"
              and status_of(report, "repair_iteration_identity") == "PASS")

    with tempfile.TemporaryDirectory() as tmp:
        # phase 'decided' with no active sample left: step() would only
        # rewrite it to 'done' on its next call and `--max-wave N` stops
        # before that - under SAMPLE_STATE_BASED terminality the loop is
        # complete, so this must NOT be downgraded
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "static_feedback")
        loop.save_wave_state(1, "decided")
        report = world.verify()
        check("all samples terminal, wave phase 'decided' (--max-wave) -> PASS, not a false "
              "UNRESOLVED", loop_status(report, "m1", "static_feedback") == "PASS"
              and scope_check(report) == "PASS")

    with tempfile.TemporaryDirectory() as tmp:
        # the same for the documented --poll stop: responses merged, every
        # sample terminal - the next step() call only walks it to done
        world = six_loop_world(tmp)
        world.repair_loop("m1", "static_feedback").save_wave_state(2, "responses_merged")
        report = world.verify()
        check("all samples terminal, wave phase 'responses_merged' (--poll) -> PASS",
              loop_status(report, "m1", "static_feedback") == "PASS"
              and scope_check(report) == "PASS")

    with tempfile.TemporaryDirectory() as tmp:
        # ... but an UNDECIDED iteration still contradicts the terminal
        # samples: the analysis of that iteration was never decided
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "static_feedback")
        loop.save_wave_state(2, "analyzed")
        report = world.verify()
        row = next(r for r in report["repair_matrix"]["rows"]
                   if (r["model_id"], r["variant"]) == ("m1", "static_feedback"))
        check("all samples terminal but an analysed iteration was never decided (phase "
              "analyzed) -> UNRESOLVED",
              loop_status(report, "m1", "static_feedback") == "UNRESOLVED"
              and "not finalized" in row["detail"])

    with tempfile.TemporaryDirectory() as tmp:
        # WAVE-PHASE EVIDENCE: interrupted between _to_analyzed(1) and
        # _decide(1) - no decided record for iteration 1 exists, but the
        # persisted phase proves the analysis (and its invocation) ran
        world = six_loop_world(tmp, repair_iteration=0)
        loop = world.repair_loop("m1", "static_feedback")
        loop.save_wave_state(1, "analyzed")
        _remove_repair_invocation(world, "m1", "static_feedback")
        report = world.verify()
        row = next(r for r in report["repair_matrix"]["rows"]
                   if (r["model_id"], r["variant"]) == ("m1", "static_feedback"))
        check("wave phase 'analyzed' at iteration 1 proves an analysed iteration >= 1 even "
              "without a decided record -> the invocation stays required",
              row["analysed_iterations"] == [] and row["wave_proves_analysis"]
              and row["invocation_required"] and row["invocation_status"] == "UNRESOLVED"
              and report["status"] != "PASS")

    with tempfile.TemporaryDirectory() as tmp:
        # ... while the same phase at iteration 0 proves nothing
        world = six_loop_world(tmp, repair_iteration=0)
        loop = world.repair_loop("m1", "static_feedback")
        loop.save_wave_state(0, "analyzed")
        report = world.verify()
        row = next(r for r in report["repair_matrix"]["rows"]
                   if (r["model_id"], r["variant"]) == ("m1", "static_feedback"))
        check("wave phase 'analyzed' at iteration 0 proves no analysed iteration >= 1",
              not row["wave_proves_analysis"])

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        loop = world.repair_loop("m1", "static_feedback")
        loop.paths.state_path.unlink()
        loop.append_sample_state(world.assembled("m1")[0]["sample_id"], 1,
                                 orchestrator.STATUS_CLEAN, "fixture: one of two")
        report = world.verify()
        check("a loop state covering 1 of 2 assembled samples -> UNRESOLVED",
              loop_status(report, "m1", "static_feedback") == "UNRESOLVED")
        loop.append_sample_state("m1__ghost__00__serial__sample_0", 1,
                                 orchestrator.STATUS_CLEAN, "fixture: not an assembled sample")
        report = world.verify()
        check("a loop state naming a sample that is not an assembled base sample -> FAIL",
              loop_status(report, "m1", "static_feedback") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        loop = world.repair_loop("m2", "test_feedback")
        entry = world.assembled("m2")[0]
        loop.append_sample_state(entry["sample_id"], 1, "stopped_somehow", "fixture")
        report = world.verify()
        check("verifier level: an unknown sample status -> repair_loop FAIL",
              loop_status(report, "m2", "test_feedback") == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        loop = world.repair_loop("m2", "test_feedback")
        loop.append_sample_state(world.assembled("m2")[0]["sample_id"], 1,
                                 orchestrator.STATUS_ACTIVE, "fixture")
        report = world.verify()
        check("verifier level: a STATUS_ACTIVE sample -> repair_loop UNRESOLVED",
              loop_status(report, "m2", "test_feedback") == "UNRESOLVED"
              and scope_check(report) == "UNRESOLVED")


def test_invocation_membership():
    print("== repair invocation MEMBERSHIP: unexpected, duplicate, foreign run ==")
    from thesis.evaluation import effective_invocation as ei

    def register(world, run_id, model, variant, owner_suffix=""):
        invocation = ei.build_invocation(
            run_id, "repair_evaluation", "fixture",
            {"primary_compiler": {"value": "g++", "source": "DEFAULT"},
             "variant": {"value": variant, "source": "CLI"}}, model_scope=[model])
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        mf.register_fragment(intermediate, world.run_id, "invocation",
                             ei.invocation_owner("repair_evaluation", [model],
                                                 invocation["effective_values"]) + owner_suffix,
                             invocation, fingerprint=invocation["invocation_sha256"],
                             writer="fixture")
        mf.write_snapshot(intermediate, world.run_id)

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        register(world, world.run_id, "m9", "static_feedback")
        report = world.verify()
        check("an invocation for a model outside the contract -> membership FAIL",
              status_of(report, "repair_invocation_membership") == "FAIL"
              and scope_check(report) == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        register(world, world.run_id, "m1", "static_feedback", owner_suffix="@second-location")
        report = world.verify()
        check("two invocations for ONE logical scope -> FAIL",
              scope_check(report) == "FAIL"
              and loop_status(report, "m1", "static_feedback") == "FAIL")
    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        register(world, "some_other_run", "m2", "combined_feedback", owner_suffix="@foreign")
        report = world.verify()
        check("an invocation fragment of ANOTHER run -> membership FAIL",
              status_of(report, "repair_invocation_membership") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        # a narrowing candidate whose missing key has an UNKEYABLE location:
        # not "no state" -> not a clean narrowing
        world = World(Path(tmp), models=("m1", "m2"), stage_overrides=SIX_LOOPS,
                      repair_loops=False)
        world.skip_repair_invocations = {("m2", v) for v in ALL_VARIANTS}
        _reset_repair_invocations(world)
        world.stamp_stages(only=("repair_evaluation",))
        world.write_repair_loops(only={("m1", v) for v in ALL_VARIANTS})
        _write_raw_loop(world, "m2", "static_feedback", claim=("m2", "bogus"))
        report = world.verify()
        check("an unkeyable location on a missing scope defeats the narrowing inference",
              report["repair_matrix"]["narrowing"]["narrowed"] is False
              and scope_check(report) == "FAIL")


def test_infrastructure_terminal_states():
    print("== terminal infrastructure states complete the loop with a limitation ==")
    for status, limitation in ((orchestrator.STATUS_ANALYSIS_INCOMPLETE, True),
                               (orchestrator.STATUS_API_EXHAUSTED, True),
                               (orchestrator.STATUS_UNUSABLE, False)):
        with tempfile.TemporaryDirectory() as tmp:
            world = six_loop_world(tmp, repair_sample_status=status)
            report = world.verify()
            row = report["repair_matrix"]["rows"][0]
            check("%s: loop completeness PASS" % status, scope_check(report) == "PASS")
            check("%s: %s in the report" % (status, "limitation reported" if limitation
                                            else "status reported, not a limitation"),
                  (bool(row["limitations"]) is limitation)
                  and row["terminal_breakdown"] == {status: 2}
                  and scope(report)["sample_totals"]["sample_terminal_breakdown"] == {status: 12})
            check("%s: not reclassified as a model failure" % status,
                  status in orchestrator.TERMINAL_STATUSES
                  and (status in orchestrator.NON_MODEL_TERMINAL_STATUSES) is limitation)


def test_runtime_stamp_does_not_substitute():
    print("== a valid global repair_evaluation runtime stamp never substitutes a loop ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        shutil.rmtree(loop_dir(world, "m2", "test_feedback"))
        _remove_repair_invocation(world, "m2", "test_feedback")
        report = world.verify()
        check("the global runtime stamp is still PASS",
              status_of(report, "stage_runtime:repair_evaluation.main") == "PASS")
        check("... but 5/6 loops -> repair_scope_complete != PASS",
              scope_check(report) != "PASS" and report["status"] != "PASS")
        check("RUNTIME_STAMP_SUBSTITUTES_MISSING_REPAIR_LOOP = false",
              rs.RUNTIME_STAMP_SUBSTITUTES_MISSING_REPAIR_LOOP is False
              and report["repair_matrix"]["runtime_stamp_substitutes_missing_repair_loop"] is False)


def test_legacy_invalid_disabled_contracts():
    print("== legacy / invalid / disabled repair plans post-run ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        refreeze(world, lambda c: c.pop("repair_plan"))
        report = world.verify()
        check("legacy/pre-v2: repair_plan missing -> repair_scope_complete UNRESOLVED, "
              "expected count not 0/PASS", scope_check(report) == "UNRESOLVED"
              and status_of(report, "repair_expected_set") == "UNRESOLVED"
              and scope(report)["expected_loop_count"] == 0 and report["status"] != "PASS")

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        refreeze(world, lambda c: c["repair_plan"].__setitem__("variants", []))
        report = world.verify()
        check("invalid plan (variants empty) -> FAIL, not an empty expected set",
              scope_check(report) == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = six_loop_world(tmp)
        refreeze(world, lambda c: c["repair_plan"].__setitem__("error", "resolver crashed"))
        report = world.verify()
        check("invalid plan (repair_plan.error) -> FAIL", scope_check(report) == "FAIL")

    disabled = {"repair": {"enabled": False}}
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), stage_overrides=disabled)
        report = world.verify()
        check("disabled repair -> expected loops 0, NOT_APPLICABLE, no evidence required",
              scope(report)["status"] == "NOT_APPLICABLE"
              and scope(report)["expected_loop_count"] == 0 and scope_check(report) == "PASS")
        _write_raw_loop(world, "m1", "static_feedback", claim=("m1", "static_feedback"))
        report = world.verify()
        check("disabled repair + an unexpected loop on disk -> FAIL", scope_check(report) == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), stage_overrides=disabled)
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        (intermediate / ("%s__static_feedback__iter1" % world.run_id) / "m1").mkdir(parents=True)
        report = world.verify()
        check("disabled repair + an iteration artifact directory -> FAIL",
              scope_check(report) == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), stage_overrides=disabled)
        from thesis.evaluation import effective_invocation as ei

        invocation = ei.build_invocation(world.run_id, "repair_evaluation", "fixture",
                                         {"variant": {"value": "static_feedback",
                                                      "source": "CLI"}},
                                         model_scope=["m1", "m2"])
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        mf.register_fragment(intermediate, world.run_id, "invocation",
                             ei.invocation_owner("repair_evaluation", ["m1", "m2"],
                                                 invocation["effective_values"]),
                             invocation, fingerprint=invocation["invocation_sha256"],
                             writer="fixture")
        mf.write_snapshot(intermediate, world.run_id)
        report = world.verify()
        check("disabled repair + an (unkeyable) repair invocation -> FAIL",
              scope_check(report) == "FAIL")


# ---------------------------------------------------------------------------
# PARCOACH / LLOV membership vs coverage: MEASURED (the technical provenance
# cleanup wave closed the gap; the measurement stays as the regression that
# proves it closed - see test_provenance_cleanup.py for the fixture matrix)
# ---------------------------------------------------------------------------

SPLIT_TOOLS = {"static_analysis": {"enabled": True, "tools": {
    "compiler": {"enabled": True}, "clang_tidy": {"enabled": False},
    "gcc_analyzer": {"enabled": False}, "cppcheck": {"enabled": False},
    "infer": {"enabled": False},
    "parcoach": {"enabled": True, "execution_models": ["mpi"]},
    "llov": {"enabled": True, "execution_models": ["omp"]}}}}


def measure_static_split_gap(tool, execution_model):
    """Two models with applicable <tool> samples. Remove ONE model's container
    invocation and measure whether the existing verifier still catches it."""
    stage = "static.%s" % tool
    results = OrderedDict()
    for variant in ("container_never_ran", "records_present_invocation_missing"):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(Path(tmp), models=("m1", "m2"), execution_model=execution_model,
                          execution_models=("serial", "omp", "mpi"), stage_overrides=SPLIT_TOOLS)
            world.skip_static_invocations = {(stage, "m2")}
            intermediate = Path(world.config["outputs"]["intermediate_dir"])
            for path in mf.fragments_dir(intermediate, world.run_id).glob(
                    "invocation.%s@m2*.json" % stage):
                path.unlink()
            mf.write_snapshot(intermediate, world.run_id)
            if variant == "container_never_ran":
                path = world.model_dir("m2") / "static_analysis.jsonl"
                records = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
                           if l.strip()]
                for record in records:
                    record["tools"].pop(tool, None)
                world.rewrite_jsonl(path, records)
                # a container that never ran left no history entry either
                summary_path = world.model_dir("m2") / "static_analysis_summary.json"
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                summary["invocations"] = [i for i in summary["invocations"]
                                          if tool not in (i.get("tools_run") or [])]
                summary_path.write_text(json.dumps(summary), encoding="utf-8")
            report = world.verify(skip_enhanced=True)
            split = report["split_static_invocation_coverage"]
            results[variant] = OrderedDict([
                ("overall", report["status"]),
                ("static_coverage_m2", status_of(report, "static_coverage:m2")),
                ("effective_invocation", status_of(report, "effective_invocation:%s" % stage)),
                ("stage_runtime", status_of(report, "stage_runtime:%s.%s" % (stage, tool))),
                ("split_membership", split["membership"]),
                ("split_coverage", split["coverage"]),
                ("split_missing", ["%s/%s" % (m["tool"], m["model_id"])
                                   for m in split["missing_scopes"]]),
                ("split_scope_m2", status_of(report, "split_static_invocation:%s/m2" % stage)),
            ])
    caught_by_static = results["container_never_ran"]["static_coverage_m2"] == "FAIL"
    false_pass = results["records_present_invocation_missing"]["overall"] == "PASS"
    closed = (not false_pass
              and results["records_present_invocation_missing"]["split_coverage"] == "UNRESOLVED"
              and results["records_present_invocation_missing"]["split_missing"] == ["%s/m2" % tool]
              and results["container_never_ran"]["split_coverage"] == "UNRESOLVED")
    classification = "OPEN_TECHNICAL_FINDING" if false_pass else ("CLOSED" if closed else "PARTIAL")
    return OrderedDict([("tool", tool), ("classification", classification),
                        ("caught_by_static_coverage_when_container_never_ran", caught_by_static),
                        ("false_pass_when_records_present_but_invocation_missing", false_pass),
                        ("measurements", results)])


def test_static_split_membership_vs_coverage():
    print("== PARCOACH / LLOV per-model invocation: membership vs coverage (MEASURED) ==")
    findings = OrderedDict()
    for tool, execution_model in (("parcoach", "mpi"), ("llov", "omp")):
        finding = measure_static_split_gap(tool, execution_model)
        findings[tool] = finding
        for variant, result in finding["measurements"].items():
            print("   %s / %s: %s" % (tool, variant, dict(result)))
        print("   STATIC_SPLIT_INVOCATION_COVERAGE_GAP[%s] = %s" % (tool, finding["classification"]))
        check("%s: the measurement ran both sub-cases" % tool,
              len(finding["measurements"]) == 2)
        check("%s: a container that never ran is caught by static coverage" % tool,
              finding["caught_by_static_coverage_when_container_never_ran"])
        check("%s: records present + invocation missing is NO LONGER a PASS - the split "
              "coverage names the missing model scope (UNRESOLVED)" % tool,
              finding["classification"] == "CLOSED"
              and finding["measurements"]["records_present_invocation_missing"]["split_scope_m2"]
              == "UNRESOLVED")
        check("%s: the membership check stays PASS (the surviving fragment is allowed) - "
              "membership and coverage are separate verdicts" % tool,
              finding["measurements"]["records_present_invocation_missing"]["split_membership"]
              == "PASS")
    global STATIC_SPLIT_FINDINGS
    STATIC_SPLIT_FINDINGS = findings


STATIC_SPLIT_FINDINGS = OrderedDict()


def main() -> int:
    test_expected_set()
    test_productive_config_expected_count()
    test_contract_builder_repair_plan()
    test_terminality_definition()
    test_exact_all_loops()
    test_missing_loops()
    test_unexpected_duplicate_unkeyable()
    test_iteration_and_pending()
    test_productive_layout_and_writer_semantics()
    test_invocation_membership()
    test_infrastructure_terminal_states()
    test_runtime_stamp_does_not_substitute()
    test_legacy_invalid_disabled_contracts()
    test_static_split_membership_vs_coverage()

    print()
    print("STATIC_SPLIT_INVOCATION_COVERAGE_GAP = %s" % json.dumps(
        {t: f["classification"] for t, f in STATIC_SPLIT_FINDINGS.items()}))
    if FAILURES:
        print("FAILURES (%d):" % len(FAILURES))
        for failure in FAILURES:
            print("  -", failure)
        return 1
    print("All repair scope completeness tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
