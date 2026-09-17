"""Per-stage runtime binding + effective invocation provenance tests.

T0 proves the runtime at the provider start; it proves nothing about a
correctness, enhanced or static stage that runs hours later. These tests
drive the productive enforcement path (stage_runtime.enforce_stage) and the
post-run verifier over it:

    CONTRACT == T0 EVIDENCE == STAGE EVIDENCE      per runtime domain
    METHODICAL OVERRIDES ARE ALLOWED ONLY IF DECLARED AND PINNED

Run:  python thesis/evaluation/test_stage_enforcement.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from thesis.evaluation import atomic_io  # noqa: E402
from thesis.evaluation import effective_invocation as ei  # noqa: E402
from thesis.evaluation import manifest_fragments as mf  # noqa: E402
from thesis.evaluation import run_authorization as ra  # noqa: E402
from thesis.evaluation import run_manifest, verify_pilot_run  # noqa: E402
from thesis.evaluation import stage_runtime as sr  # noqa: E402
from thesis.evaluation.test_post_run_verification import (  # noqa: E402
    World, fake_environments, fake_prober, status_of)

FAILURES = []


def check(label, condition):
    print("  [%s] %s" % ("ok" if condition else "FAIL", label))
    if not condition:
        FAILURES.append(label)


def prober_with(mutate):
    def prober(config):
        return mutate(fake_environments())
    return prober


def mutate_field(domain, field, value):
    def apply(environments):
        environments[domain][field] = value
        return environments
    return apply


def mutate_identity(domain, tool, value):
    def apply(environments):
        environments[domain]["tool_identities"][tool] = value
        return environments
    return apply


def mutate_evidence(domain, key, value):
    def apply(environments):
        environments[domain]["evidence"][key] = value
        return environments
    return apply


def fresh_world(tmp, run_id="pilot_002_stage"):
    """An authorized run whose stages have NOT been stamped yet."""
    world = World(Path(tmp), run_id=run_id)
    intermediate = Path(world.config["outputs"]["intermediate_dir"])
    for stage in ("stage.correctness", "stage.enhanced", "stage.static.main",
                  "stage.static.parcoach", "stage.static.llov", "stage.dynamic",
                  "stage.repair_evaluation"):
        path = mf.fragment_path(intermediate, world.run_id, "runtime", stage)
        if path.is_file():
            path.unlink()
    for stage in ("correctness", "enhanced", "static.main"):
        path = mf.fragment_path(intermediate, world.run_id, "invocation", stage)
        if path.is_file():
            path.unlink()
    mf.write_snapshot(intermediate, world.run_id)
    sr.reset_cache()
    return world


def main():
    print("== 1. the contracted runtime: stage stamps match T0 ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        evidence = sr.enforce_stage(world.config, world.run_id, "correctness",
                                    effective_values={
                                        "effective_run_timeout_seconds": {"value": 120,
                                                                          "source": "CONFIG"}},
                                    profile="fixture", prober=fake_prober)
        check("T0 A + correctness A -> the stage is stamped and enforced",
              evidence["enforced"] and evidence["stage_runtime_sha256"])
        manifest = run_manifest.load_manifest(world.config, world.run_id)
        stamp = (manifest.get("stage_runtime_evidence") or {}).get("stage.correctness")
        check("the stamp is schema-versioned and bound to contract + authorization",
              stamp["schema_version"] == "stage_runtime_evidence.v1"
              and stamp["contract_sha256"] == manifest["contract_sha256"]
              and stamp["authorization_sha256"] == manifest["authorization_sha256"])
        check("the stamp records the domain identities it compared",
              stamp["domains"]["main"]["match"] is True
              and stamp["domains"]["main"]["tool_identities"]["compiler"].startswith("g++"))
        again = sr.enforce_stage(world.config, world.run_id, "correctness",
                                 effective_values={
                                     "effective_run_timeout_seconds": {"value": 120,
                                                                       "source": "CONFIG"}},
                                 profile="fixture", prober=fake_prober)
        check("an identical re-stamp is idempotent",
              again["stage_runtime_sha256"] == evidence["stage_runtime_sha256"])

    print("== 2-8. every runtime drift refuses the stage BEFORE records ==")
    drifts = [
        ("2: correctness main image B", "correctness",
         mutate_field("main", "image_id", "sha256:" + "b" * 64)),
        ("3: correctness compiler B", "correctness",
         mutate_identity("main", "compiler", "g++ 14.0.0")),
        ("4: correctness MPI B (evidence.mpi_version_line)", "correctness",
         mutate_evidence("main", "mpi_version_line", "mpirun (Open MPI) 5.0.0")),
        ("5: enhanced main image B", "enhanced",
         mutate_field("main", "image_id", "sha256:" + "e" * 64)),
        ("6: LLOV plugin Y", "static.llov",
         mutate_evidence("llov", "plugin_sha256", "y" * 64)),
        ("6b: LLOV image B", "static.llov",
         mutate_field("llov", "image_id", "sha256:" + "c" * 64)),
        ("7: PARCOACH executable Y", "static.parcoach",
         mutate_evidence("parcoach", "executable_sha256", "y" * 64)),
        ("7b: PARCOACH program version", "static.parcoach",
         mutate_identity("parcoach", "parcoach", "PARCOACH 9.9.9")),
        ("8: static main clang-tidy identity", "static.main",
         mutate_identity("main", "clang_tidy", "clang-tidy 19.0.0")),
    ]
    for label, stage, mutate in drifts:
        with tempfile.TemporaryDirectory() as tmp:
            world = fresh_world(tmp)
            try:
                sr.enforce_stage(world.config, world.run_id, stage,
                                 profile="fixture", prober=prober_with(mutate))
                check("%s -> STAGE_RUNTIME_DRIFT" % label, False)
            except sr.StageRuntimeDrift as drift:
                check("%s -> STAGE_RUNTIME_DRIFT" % label,
                      drift.failure_class == "STAGE_RUNTIME_DRIFT"
                      and drift.stage == stage and drift.drift_fields)
            manifest = run_manifest.load_manifest(world.config, world.run_id)
            owner = sr.STAGE_DOMAINS[stage][0]
            check("%s -> no stage evidence and no records" % label,
                  owner not in (manifest.get("stage_runtime_evidence") or {}))

    print("== the drift is a PROVENANCE failure, not a tool or model failure ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        try:
            sr.enforce_stage(world.config, world.run_id, "static.parcoach",
                             profile="fixture",
                             prober=prober_with(mutate_evidence("parcoach",
                                                                "executable_sha256", "z" * 64)))
        except sr.StageRuntimeDrift as drift:
            text = drift.render()
            check("the refusal names stage, domain, expected, observed and drift fields",
                  "static.parcoach" in text and "parcoach" in text and "drift" in text
                  and drift.expected and drift.observed)
            check("the refusal recommends a fresh run id / restored environment",
                  "fresh run_id" in drift.recommendation)
            from thesis.evaluation import framework

            check("it is NOT classified as a tool state or tool error",
                  drift.failure_class in ("STAGE_RUNTIME_DRIFT", "STAGE_RUNTIME_UNRESOLVED")
                  and drift.failure_class not in framework.ANALYSIS_STATES
                  and "TOOL_ERROR" not in text
                  and not isinstance(drift, ei.InvocationRefused))

    print("== a run without T0 evidence cannot stamp a stage ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        mf.fragment_path(intermediate, world.run_id, "runtime", "evidence").unlink()
        mf.write_snapshot(intermediate, world.run_id)
        try:
            sr.enforce_stage(world.config, world.run_id, "correctness",
                             profile="fixture", prober=fake_prober)
            check("no T0 evidence -> STAGE_RUNTIME_UNRESOLVED", False)
        except sr.StageRuntimeUnresolved as unresolved:
            check("no T0 evidence -> STAGE_RUNTIME_UNRESOLVED",
                  unresolved.failure_class == "STAGE_RUNTIME_UNRESOLVED")

    print("== a run without a frozen contract is NOT_APPLICABLE, never a silent pass ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        mf.fragment_path(intermediate, world.run_id, "contract").unlink()
        mf.write_snapshot(intermediate, world.run_id)
        result = sr.enforce_stage(world.config, world.run_id, "correctness",
                                  profile="fixture", prober=fake_prober)
        check("an uncontracted run reports PRE_RUN_ENFORCEMENT = NOT_APPLICABLE",
              result["enforced"] is False and "no frozen run contract" in result["reason"])

    print("== effective invocation: declared and pinned ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        contract = (run_manifest.load_manifest(world.config, world.run_id) or {}).get("contract")
        check("the contract pins run_timeout_seconds = 120",
              contract.get("run_timeout_seconds") == 120)

        ok = sr.enforce_stage(world.config, world.run_id, "correctness",
                              effective_values={
                                  "effective_run_timeout_seconds": {"value": 120,
                                                                    "source": "CONFIG"},
                                  "primary_compiler": {"value": "g++", "source": "DEFAULT"}},
                              profile="fixture", prober=fake_prober)
        check("A: config 120, no CLI override, contract 120 -> allowed",
              ok["enforced"] and ok["invocation_sha256"])
        invocation = (run_manifest.load_manifest(world.config, world.run_id)
                      .get("stage_invocations") or {}).get("correctness")
        check("A2: the effective value and its SOURCE are persisted",
              invocation["effective_values"]["effective_run_timeout_seconds"]
              == {"value": 120, "source": "CONFIG"}
              and invocation["override_policy"] == "ALLOWED_ONLY_IF_DECLARED_AND_PINNED")
        check("A3: the invocation carries the contract's expected value",
              (invocation.get("contract_expected_values") or {}).get(
                  "effective_run_timeout_seconds") == 120)

        same = sr.enforce_stage(world.config, world.run_id, "correctness",
                                effective_values={
                                    "effective_run_timeout_seconds": {"value": 120,
                                                                      "source": "CONFIG"},
                                    "primary_compiler": {"value": "g++", "source": "DEFAULT"}},
                                profile="fixture", prober=fake_prober)
        check("D: an identical re-registration is idempotent",
              same["invocation_sha256"] == ok["invocation_sha256"])

        try:
            ei.register_effective_invocation(
                world.config, world.run_id, "correctness",
                {"effective_run_timeout_seconds": {"value": 120, "source": "CONFIG"},
                 "primary_compiler": {"value": "clang++", "source": "CLI"}},
                profile="fixture")
            check("E: a DIFFERENT invocation for the same stage -> HARD FAIL", False)
        except ei.InvocationRefused as refusal:
            check("E: a DIFFERENT invocation for the same stage -> HARD FAIL",
                  "already registered a DIFFERENT" in str(refusal)
                  or "contract pins" in str(refusal))

    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        try:
            sr.enforce_stage(world.config, world.run_id, "correctness",
                             effective_values={
                                 "effective_run_timeout_seconds": {"value": 60,
                                                                   "source": "CLI"}},
                             profile="fixture", prober=fake_prober)
            check("B: config 120 + contract 120 + actual CLI 60 -> REFUSED", False)
        except ei.InvocationRefused as refusal:
            check("B: config 120 + contract 120 + actual CLI 60 -> REFUSED",
                  "contract pins 120" in str(refusal) and "60" in str(refusal))
        manifest = run_manifest.load_manifest(world.config, world.run_id)
        check("B2: the refused stage registered NO invocation and NO stage runtime",
              "correctness" not in (manifest.get("stage_invocations") or {})
              and "stage.correctness" not in (manifest.get("stage_runtime_evidence") or {}))

    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp, run_id="pilot_002_stage60")
        # the contract deliberately pins 60: the same CLI value is then legal
        contract_path = world.contract_path
        frozen = json.loads(contract_path.read_text(encoding="utf-8"))
        frozen["run_timeout_seconds"] = 60
        from thesis.evaluation import pilot_run_contract as prc

        frozen["contract_sha256"] = prc.contract_sha256(frozen)
        atomic_io.atomic_write_json(contract_path, frozen)
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        for kind, owner in (("contract", None), ("authorization", "start"),
                            ("runtime", "evidence")):
            path = mf.fragment_path(intermediate, world.run_id, kind, owner)
            if path.is_file():
                path.unlink()
        mf.write_snapshot(intermediate, world.run_id)
        ra.clear_context()
        # rebuild would not produce 60, so this is a fixture-level binding:
        # register the contract directly, then stamp with the CLI value
        run_manifest.register_contract(world.config, world.run_id,
                                       frozen["contract_sha256"], frozen)
        fresh = ra.measure_fresh_runtime(world.config, prober=fake_prober)
        run_manifest.register_runtime_evidence(
            world.config, world.run_id,
            ra.t0_runtime_evidence(world.run_id, frozen["contract_sha256"],
                                   fresh["sha256"], fresh),
            fingerprint=ra.t0_evidence_fingerprint(
                ra.t0_runtime_evidence(world.run_id, frozen["contract_sha256"],
                                       fresh["sha256"], fresh)))
        sr.reset_cache()
        result = sr.enforce_stage(world.config, world.run_id, "correctness",
                                  effective_values={
                                      "effective_run_timeout_seconds": {"value": 60,
                                                                        "source": "CLI"}},
                                  profile="fixture", prober=fake_prober)
        check("C: contract 60 + actual CLI 60 -> allowed", result["enforced"] is True)

    print("== invocation hygiene ==")
    check("F: config-only methodical values may not be duplicated",
          _refuses_duplicate())
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        try:
            sr.enforce_stage(world.config, world.run_id, "correctness",
                             effective_values={"effective_run_timeout_seconds":
                                               {"value": 120, "source": "CONFIG"}},
                             profile="fixture", model_scope=["m_not_contracted"],
                             prober=fake_prober)
            check("G: an undeclared model scope -> REFUSED", False)
        except ei.InvocationRefused as refusal:
            check("G: an undeclared model scope -> REFUSED",
                  "model_scope" in str(refusal))
    check("the fingerprint ignores volatile context",
          ei.invocation_fingerprint({
              "schema_version": ei.EFFECTIVE_INVOCATION_VERSION, "stage": "correctness",
              "run_id": "r", "profile": "p", "model_scope": None,
              "override_policy": ei.OVERRIDE_POLICY,
              "effective_values": {"a": {"value": 1, "source": "CLI"}},
              "registered_at": "now", "pid": 1})
          == ei.invocation_fingerprint({
              "schema_version": ei.EFFECTIVE_INVOCATION_VERSION, "stage": "correctness",
              "run_id": "r", "profile": "p", "model_scope": None,
              "override_policy": ei.OVERRIDE_POLICY,
              "effective_values": {"a": {"value": 1, "source": "CLI"}},
              "registered_at": "later", "pid": 2}))

    print("== post-run verification of the runtime chain ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))  # fully stamped by the fixture world
        report = world.verify()
        matrix = report["runtime_matrix"]
        check("the runtime matrix covers every expected result-producing stage",
              {row["stage"] for row in matrix}
              == {"correctness", "enhanced", "static.main", "repair_evaluation"}
              and all(row["status"] == "PASS" for row in matrix))
        check("Contract == T0 == Stage for every domain",
              all(status_of(report, "stage_runtime:%s.%s" % (row["stage"], row["domain"]))
                  == "PASS" for row in matrix))
        check("the authorization chain is verified",
              status_of(report, "start_authorization_present") == "PASS"
              and status_of(report, "start_authorization_allowed") == "PASS"
              and status_of(report, "t0_fresh_runtime_matched_readiness") == "PASS")
        check("the effective invocations are verified against the contract",
              status_of(report, "effective_invocation:correctness") == "PASS")
        check("a retrospective runtime probe is never accepted as a substitute",
              report["retrospective_runtime_substitution_allowed"] is False)

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        mf.fragment_path(intermediate, world.run_id, "runtime", "stage.enhanced").unlink()
        mf.write_snapshot(intermediate, world.run_id)
        report = world.verify()
        check("a MISSING stage stamp is UNRESOLVED even though the records exist",
              status_of(report, "stage_runtime:enhanced.main") == "UNRESOLVED"
              and report["status"] == "UNRESOLVED")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        path = mf.fragment_path(intermediate, world.run_id, "runtime", "stage.correctness")
        fragment = json.loads(path.read_text(encoding="utf-8"))
        fragment["content"]["domains"]["main"]["observed_domain_sha256"] = "f" * 64
        atomic_io.atomic_write_json(path, fragment)
        mf.write_snapshot(intermediate, world.run_id)
        report = world.verify()
        check("a hand-edited stage stamp is FAIL, never PASS",
              status_of(report, "stage_runtime:correctness.main") == "FAIL"
              and status_of(report, "run_provenance_integrity") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        path = mf.fragment_path(intermediate, world.run_id, "runtime", "stage.correctness")
        fragment = json.loads(path.read_text(encoding="utf-8"))
        fragment["content"]["contract_sha256"] = "0" * 64
        fragment["fingerprint_sha256"] = sr._evidence_fingerprint(fragment["content"])
        fragment["content"]["stage_runtime_sha256"] = fragment["fingerprint_sha256"]
        fragment["fingerprint_sha256"] = sr._evidence_fingerprint(fragment["content"])
        atomic_io.atomic_write_json(path, fragment)
        mf.write_snapshot(intermediate, world.run_id)
        report = world.verify()
        check("a stage stamp from ANOTHER contract is FAIL",
              status_of(report, "stage_runtime:correctness.main") == "FAIL")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        path = mf.fragment_path(intermediate, world.run_id, "runtime", "evidence")
        fragment = json.loads(path.read_text(encoding="utf-8"))
        del fragment["content"]["domains"]["llov"]["evidence"]["plugin_sha256"]
        atomic_io.atomic_write_json(path, fragment)
        mf.write_snapshot(intermediate, world.run_id)
        report = world.verify()
        check("a deleted required identity is FAIL/UNRESOLVED, never PASS",
              status_of(report, "run_provenance_integrity") == "FAIL"
              and report["status"] in ("FAIL", "UNRESOLVED"))

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        path = mf.fragment_path(intermediate, world.run_id, "invocation", "correctness")
        fragment = json.loads(path.read_text(encoding="utf-8"))
        fragment["content"]["effective_values"]["effective_run_timeout_seconds"] = {
            "value": 60, "source": "CLI"}
        atomic_io.atomic_write_json(path, fragment)
        mf.write_snapshot(intermediate, world.run_id)
        report = world.verify()
        check("an effective timeout that contradicts the contract is FAIL post-run",
              status_of(report, "effective_invocation:correctness") == "FAIL")

    test_expected_runtime_stage_derivation()
    test_split_container_runtime_matrix()
    test_invocation_field_classification()
    test_per_model_invocations()
    test_productive_invocation_fields_are_methodical()
    test_expected_set_check_is_reported()
    test_missing_authorization_is_unresolved()
    test_main_domain_presence_vs_drift()

    print()
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for item in FAILURES:
            print("  -", item)
        sys.exit(1)
    print("All stage enforcement tests passed.")


# ---------------------------------------------------------------------------
# the COMPLETE expected runtime stage matrix
# ---------------------------------------------------------------------------

def _contract(expected_stages, tools=None, population=("serial", "omp", "mpi"),
              repair=None, sha="c" * 64):
    """A frozen-contract-shaped dict: only the fields the derivation reads."""
    toolset = OrderedDict()
    for name, entry in (tools or {}).items():
        toolset[name] = OrderedDict([("enabled", entry[0]),
                                     ("execution_models", list(entry[1]))])
    contract = OrderedDict([
        ("contract_sha256", sha),
        ("expected_stages", list(expected_stages)),
        ("execution_models", list(population)),
        ("static_toolset", toolset),
    ])
    if repair is not None:
        contract["repair_plan"] = OrderedDict([("enabled", repair),
                                               ("evaluates_repair_candidates", repair)])
    return contract


FULL_TOOLS = {"compiler": (True, ["serial", "omp", "mpi"]),
              "clang_tidy": (True, ["serial", "omp", "mpi"]),
              "parcoach": (True, ["mpi"]),
              "llov": (True, ["omp"])}


def test_expected_runtime_stage_derivation():
    print("== expected runtime stages are derived from the FROZEN contract ==")
    full = _contract(["generation", "assembly", "correctness_tests", "static_analysis",
                      "dynamic_analysis", "enhanced_tests", "repair"],
                     tools=FULL_TOOLS, repair=True)
    stages = sr.expected_stages(full)
    check("A: main + PARCOACH + LLOV + repair + correctness + dynamic + enhanced",
          stages == ["correctness", "dynamic", "enhanced", "static.main",
                     "static.parcoach", "static.llov", "repair_evaluation"])
    check("A: every expected entry names WHY it is expected",
          all(entry["reason"] for entry in sr.expected_runtime_stages(full)))
    check("A: the derivation policy is versioned",
          sr.EXPECTED_RUNTIME_STAGE_POLICY == "expected_runtime_stages.v2")

    no_split = _contract(["correctness_tests", "static_analysis"],
                         tools={"compiler": (True, ["serial"]),
                                "parcoach": (False, ["mpi"]), "llov": (False, ["omp"])},
                         population=["serial"])
    check("PARCOACH disabled in the frozen toolset -> not expected",
          "static.parcoach" not in sr.expected_stages(no_split))
    check("LLOV disabled in the frozen toolset -> not expected",
          "static.llov" not in sr.expected_stages(no_split))

    serial_only = _contract(["correctness_tests", "static_analysis"],
                            tools=FULL_TOOLS, population=["serial"])
    check("G/26: PARCOACH enabled but MPI not in the population -> NOT expected",
          "static.parcoach" not in sr.expected_stages(serial_only))
    check("G/26: LLOV enabled but OpenMP not in the population -> NOT expected",
          "static.llov" not in sr.expected_stages(serial_only))
    check("G/26: the main container is still expected",
          "static.main" in sr.expected_stages(serial_only))
    reasons = {e["stage"]: e["reason"]
               for e in sr.not_expected_runtime_stages(serial_only)}
    check("G/26: the non-applicability is REPORTED with its reason",
          "population" in reasons.get("static.parcoach", "")
          and "population" in reasons.get("static.llov", ""))

    mpi_only = _contract(["correctness_tests", "static_analysis"], tools=FULL_TOOLS,
                         population=["mpi"])
    check("an MPI-only population expects PARCOACH but not LLOV",
          "static.parcoach" in sr.expected_stages(mpi_only)
          and "static.llov" not in sr.expected_stages(mpi_only))

    no_repair = _contract(["correctness_tests", "repair"], tools=FULL_TOOLS, repair=False)
    check("F/25: a disabled repair plan does not require a repair stamp",
          "repair_evaluation" not in sr.expected_stages(no_repair))
    check("E/24: a contracted repair loop DOES require a repair stamp",
          "repair_evaluation" in sr.expected_stages(
              _contract(["repair"], tools=FULL_TOOLS, repair=True)))

    check("43: the dynamic expectation is unchanged (contract decides)",
          "dynamic" in sr.expected_stages(_contract(["dynamic_analysis"], tools=FULL_TOOLS))
          and "dynamic" not in sr.expected_stages(
              _contract(["correctness_tests"], tools=FULL_TOOLS)))
    toolless = OrderedDict([("expected_stages", ["static_analysis"])])
    check("a contract without a frozen toolset demands ALL THREE static stages "
          "fail-closed (applicability UNRESOLVED, never silently dropped)",
          sr.expected_stages(toolless)
          == ["static.main", "static.parcoach", "static.llov"])
    check("a toolless contract reports UNRESOLVED applicability, never a false "
          "'not enabled'",
          all(entry["status"] == "NOT_APPLICABLE"
              for entry in sr.not_expected_runtime_stages(toolless)))

    empty_scope = _contract(["static_analysis"],
                            tools={"compiler": (True, ["serial"]),
                                   "parcoach": (True, []), "llov": (False, ["omp"])},
                            population=["serial", "mpi"])
    check("a tool with an EMPTY effective scope can analyse nothing and is NOT required",
          "static.parcoach" not in sr.expected_stages(empty_scope))
    check("the empty-scope reason names the real cause",
          "EMPTY effective execution-model scope" in
          {e["stage"]: e["reason"] for e in
           sr.not_expected_runtime_stages(empty_scope)}["static.parcoach"])


def test_split_container_runtime_matrix():
    print("== a split-container static run: main + PARCOACH + LLOV + repair ==")
    split_tools = {"tools": {"compiler": {"enabled": True},
                             "clang_tidy": {"enabled": False},
                             "gcc_analyzer": {"enabled": False},
                             "cppcheck": {"enabled": False}, "infer": {"enabled": False},
                             "parcoach": {"enabled": True, "execution_models": ["mpi"]},
                             "llov": {"enabled": True, "execution_models": ["omp"]}},
                   "enabled": True}
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), execution_models=("serial", "omp", "mpi"),
                      stage_overrides={"static_analysis": split_tools})
        report = world.verify()
        matrix = report["runtime_matrix"]
        rows = {(row["stage"], row["domain"]): row for row in matrix}
        check("18: the matrix contains a row for main, PARCOACH and LLOV",
              {("static.main", "main"), ("static.parcoach", "parcoach"),
               ("static.llov", "llov")} <= set(rows))
        check("54: every expected domain has its own row",
              {row["domain"] for row in matrix} == {"main", "parcoach", "llov"})
        check("27/46: all three static stamps PASS",
              all(rows[key]["status"] == "PASS" for key in
                  [("static.main", "main"), ("static.parcoach", "parcoach"),
                   ("static.llov", "llov")]))
        check("46: repair_evaluation is stamped and PASSes",
              rows[("repair_evaluation", "main")]["status"] == "PASS")
        check("every expected stage - including the two container stages - has an "
              "EFFECTIVE INVOCATION, not only a runtime stamp",
              all(status_of(report, "effective_invocation:%s" % stage) == "PASS"
                  for stage in ("correctness", "enhanced", "static.main",
                                "static.parcoach", "static.llov", "repair_evaluation")))
        check("55: contract == T0 == every expected stage",
              all(row["status"] == "PASS" for row in matrix)
              and report["status"] in ("PASS", "UNRESOLVED"))
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        owners = sorted(p.name for p in
                        mf.fragments_dir(intermediate, world.run_id).glob("runtime.*.json"))
        check("the three static invocations keep SEPARATE fragment owners",
              {"runtime.stage.static.main.json", "runtime.stage.static.parcoach.json",
               "runtime.stage.static.llov.json"} <= set(owners))
        check("no same-owner conflict between the parallel containers",
              len(owners) == len(set(owners)))

    # each missing stamp is UNRESOLVED - never PASS because result files exist
    for missing, label in (("static.main", "19/47"), ("static.parcoach", "20/48"),
                           ("static.llov", "21/49"), ("repair_evaluation", "24/50")):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(Path(tmp), execution_models=("serial", "omp", "mpi"),
                          stage_overrides={"static_analysis": split_tools},
                          skip_stamps=(missing,))
            report = world.verify()
            domain = sr.STAGE_DOMAINS[missing][1][0]
            check("%s: a missing %s stamp -> UNRESOLVED"
                  % (label, missing),
                  status_of(report, "stage_runtime:%s.%s" % (missing, domain))
                  == "UNRESOLVED")
            if missing.startswith("static"):
                check("28/53: the static result files do NOT substitute for the stamp",
                      (world.model_dir() / "static_analysis.jsonl").is_file()
                      and status_of(report, "stage_runtime:%s.%s" % (missing, domain))
                      == "UNRESOLVED")

    # a stamp from another contract is a FAIL, not an UNRESOLVED
    for stage, label in (("static.parcoach", "22/51/52"), ("static.llov", "23/51/52")):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(Path(tmp), execution_models=("serial", "omp", "mpi"),
                          stage_overrides={"static_analysis": split_tools})
            intermediate = Path(world.config["outputs"]["intermediate_dir"])
            owner = sr.STAGE_DOMAINS[stage][0]
            path = mf.fragment_path(intermediate, world.run_id, "runtime", owner)
            fragment = json.loads(path.read_text(encoding="utf-8"))
            fragment["content"]["contract_sha256"] = "f" * 64
            atomic_io.atomic_write_json(path, fragment)
            mf.write_snapshot(intermediate, world.run_id)
            report = world.verify()
            domain = sr.STAGE_DOMAINS[stage][1][0]
            check("%s: a %s stamp of ANOTHER contract -> FAIL" % (label, stage),
                  status_of(report, "stage_runtime:%s.%s" % (stage, domain)) == "FAIL")

    # repair disabled: no repair stamp is required
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), stage_overrides={"repair": {"enabled": False}})
        report = world.verify()
        check("25/51: repair disabled + no repair stamp -> not required",
              "repair_evaluation" not in {row["stage"] for row in report["runtime_matrix"]}
              and status_of(report, "stage_runtime:repair_evaluation.main") is None)
        reasons = {entry["stage"]: entry["reason"] for entry in
                   sr.not_expected_runtime_stages(world.contract, world.config)}
        check("25: the NOT_APPLICABLE reason is recorded, not silently absent",
              "repair" in (reasons.get("repair_evaluation") or ""))


def test_invocation_field_classification():
    print("== effective invocation carries METHODICAL values only ==")
    check("29/57: output_file_name is refused by the invocation builder",
          _refuses_non_methodical("correctness", "output_file_name", "correctness.jsonl"))
    check("30: another NON_METHODICAL option (restart) is refused too",
          _refuses_non_methodical("correctness", "restart", True))
    check("30: a NON_METHODICAL enhanced option (force) is refused",
          _refuses_non_methodical("enhanced", "force", True))
    check("29: run_correctness.py no longer registers output_file_name",
          "\"output_file_name\": {\"value\"" not in
          (REPO_ROOT / "thesis" / "evaluation" / "run_correctness.py")
          .read_text(encoding="utf-8"))
    for field, dest in (("effective_run_timeout_seconds", "run_timeout"),
                        ("primary_compiler", "primary_compiler"),
                        ("specs", "specs"), ("jobs", "jobs"), ("tools", "tools"),
                        ("variant", "variant")):
        check("every registered field maps to a METHODICAL CLI dest: %s -> %s"
              % (field, dest), ei.cli_dest_for(field) == dest)
    check("31/59: config-only values stay forbidden", _refuses_duplicate())
    check("60: the override policy is unchanged",
          ei.OVERRIDE_POLICY == "ALLOWED_ONLY_IF_DECLARED_AND_PINNED")

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        invocations = ei.registered_invocations(
            run_manifest.load_manifest(world.config, world.run_id))
        offenders = []
        for owner, invocation in invocations.items():
            # the fragment OWNER carries the invocation scope; the methodical
            # classification is per STAGE
            stage = invocation.get("stage") or owner
            offenders += ["%s.%s" % (owner, problem) for problem in
                          ei.non_methodical_fields(
                              stage, invocation.get("effective_values") or {})]
        check("58: NO registered invocation field is NON_METHODICAL", offenders == [])
        correctness = ei.invocations_for_stage(
            run_manifest.load_manifest(world.config, world.run_id), "correctness")
        check("58: the correctness invocation fields are exactly the methodical ones",
              len(correctness) == 1
              and sorted(correctness[0].get("effective_values") or {})
              == ["effective_run_timeout_seconds", "primary_compiler"])
        duplicates = [name for invocation in invocations.values()
                      for name in (invocation.get("effective_values") or {})
                      if name in ei.FORBIDDEN_DUPLICATE_FIELDS]
        check("59: no duplicate source-of-truth field in any fragment", duplicates == [])


def test_missing_authorization_is_unresolved():
    print("== a run whose start authorization is gone is UNRESOLVED, never PASS ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        intermediate = Path(world.config["outputs"]["intermediate_dir"])
        path = mf.fragment_path(intermediate, world.run_id,
                                ra.AUTHORIZATION_FRAGMENT_KIND,
                                ra.AUTHORIZATION_FRAGMENT_OWNER)
        path.unlink()
        mf.write_snapshot(intermediate, world.run_id)
        report = world.verify()
        check("a missing start authorization is UNRESOLVED",
              status_of(report, "start_authorization_present") == "UNRESOLVED")
        check("the run does not verify as PASS without it", report["status"] != "PASS")
        check("a fresh process cannot rehydrate a run without an authorization",
              _rehydration_refused(world))


def _rehydration_refused(world) -> bool:
    try:
        ra.load_and_validate_run_authorization(
            world.config, world.run_id, config_path=world.config_path, profile="fixture")
        return False
    except ra.PreRunInfrastructureFailure:
        return True


def test_expected_set_check_is_reported():
    print("== the expected runtime stage SET is itself reported evidence ==")
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp))
        report = world.verify()
        entry = [c for c in report["checks"]
                 if c["check"] == "stage_runtime_expected_set"]
        check("54: the verifier reports the expected runtime stage set", len(entry) == 1)
        evidence = entry[0]["evidence"] if entry else {}
        check("54: the evidence names every expected stage with its reason",
              {row["stage"] for row in evidence.get("expected") or []}
              == {row["stage"] for row in report["runtime_matrix"]}
              and all(row.get("reason") for row in evidence.get("expected") or []))
        check("53: the evidence states that result files never substitute",
              evidence.get("result_files_substitute_for_runtime_stamp") is False)
        check("25/49/50: the NOT_APPLICABLE stages are named with a reason",
              all(row.get("reason") for row in evidence.get("not_applicable") or [])
              and {row["stage"] for row in evidence.get("not_applicable") or []}
              == set(sr.STAGE_DOMAINS) - {row["stage"] for row in report["runtime_matrix"]})
        check("37: the derivation policy version is published",
              evidence.get("policy") == sr.EXPECTED_RUNTIME_STAGE_POLICY)


def test_per_model_invocations():
    print("== per-model container/repair invocations coexist, drift still fails ==")
    check("every enforced stage is mapped to a CLI inventory stage",
          set(sr.STAGE_DOMAINS) <= set(ei.STAGE_TO_INVENTORY_STAGE))
    check("an unmapped stage is fail-closed, not fail-open",
          ei.field_classification("no_such_stage", "tools")["methodical"] is False)
    check("the owner carries the model scope only when there is one",
          ei.invocation_owner("static.parcoach") == "static.parcoach"
          and ei.invocation_owner("static.parcoach", ["m2", "m1"])
          == "static.parcoach@m1+m2")
    check("the owner also carries the variant/tool scope of the invocation",
          ei.invocation_owner("repair_evaluation", ["m1"],
                              {"variant": {"value": "test_feedback", "source": "CLI"}})
          == "repair_evaluation@m1@variant-test_feedback")

    # the REAL repair loop shape: 2 models x 3 variants over ONE base run id
    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), models=("m1", "m2"))
        refused = []
        for model in ("m1", "m2"):
            for variant in ("static_feedback", "test_feedback", "combined_feedback"):
                values = {"primary_compiler": {"value": "g++", "source": "DEFAULT"},
                          "variant": {"value": variant, "source": "CLI"}}
                if not _registers(world, "repair_evaluation", values, [model]):
                    refused.append("%s/%s" % (model, variant))
        check("every (model, variant) repair invocation is registered, none refused",
              refused == [])
        manifest = run_manifest.load_manifest(world.config, world.run_id)
        owners = {owner for owner in ei.registered_invocations(manifest)
                  if owner.startswith("repair_evaluation@")}
        check("all six (model, variant) repair invocations are visible under the stage",
              {"repair_evaluation@%s@variant-%s" % (m, v)
               for m in ("m1", "m2")
               for v in ("static_feedback", "test_feedback", "combined_feedback")}
              <= owners)
        contradiction = {"primary_compiler": {"value": "clang++", "source": "CLI"},
                         "variant": {"value": "static_feedback", "source": "CLI"}}
        check("a CONTRADICTING condition under the SAME (model, variant) is a HARD FAIL",
              not _registers(world, "repair_evaluation", contradiction, ["m1"]))

    with tempfile.TemporaryDirectory() as tmp:
        world = World(Path(tmp), models=("m1", "m2"))
        values = {"tools": {"value": ["parcoach"], "source": "CLI"},
                  "primary_compiler": {"value": "g++", "source": "DEFAULT"}}
        registered = []
        for model in ("m1", "m2"):
            try:
                ei.register_effective_invocation(
                    world.config, world.run_id, "static.parcoach", values,
                    profile="fixture", model_scope=[model], writer="static_analysis")
                registered.append(model)
            except ei.InvocationRefused as failure:
                print("   REFUSED for %s: %s" % (model, str(failure)[:120]))
        check("a per-model container invocation is registered for EVERY model",
              registered == ["m1", "m2"])
        manifest = run_manifest.load_manifest(world.config, world.run_id)
        check("both invocations are visible under the stage",
              len(ei.invocations_for_stage(manifest, "static.parcoach")) == 2)
        check("re-registering the identical invocation stays idempotent",
              _registers(world, "static.parcoach", values, ["m1"]))
        # a changed CONDITION (not a changed scope) under the same scope
        drifted = dict(values, primary_compiler={"value": "clang++", "source": "CLI"})
        check("a CHANGED condition under the SAME scope is still a HARD FAIL",
              not _registers(world, "static.parcoach", drifted, ["m1"]))


def _registers(world, stage, values, scope) -> bool:
    try:
        ei.register_effective_invocation(world.config, world.run_id, stage, values,
                                         profile="fixture", model_scope=scope,
                                         writer="static_analysis")
        return True
    except ei.InvocationRefused:
        return False


def productive_effective_values():
    """The effective_values field names each PRODUCTIVE runner really passes
    to stage_runtime.enforce_stage, read from the source by AST.

    Reading the runners instead of restating their dicts is the point: a
    runner that starts registering a NON_METHODICAL value fails this test
    without anyone remembering to update it."""
    import ast

    runners = {
        "thesis/evaluation/run_correctness.py": ["correctness"],
        "thesis/evaluation/run_dynamic_analysis.py": ["dynamic"],
        "thesis/evaluation/run_enhanced_tests.py": ["enhanced"],
        "thesis/evaluation/run_static_analysis.py": ["static.main", "static.parcoach",
                                                     "static.llov"],
        "thesis/repair/orchestrator.py": ["repair_evaluation"],
    }
    found = OrderedDict()
    for relative, stages in runners.items():
        source = (REPO_ROOT / relative).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        tree = ast.parse(source)
        names = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if not keys:
                continue
            # an effective_values dict maps a field name to {"value":..., "source":...}
            entries = [v for v in node.values if isinstance(v, ast.Dict)]
            if len(entries) != len(node.values) or not entries:
                continue
            if all(set(c.value for c in e.keys
                       if isinstance(c, ast.Constant)) >= {"value", "source"}
                   for e in entries):
                names.update(keys)
        for stage in stages:
            found.setdefault(stage, set()).update(names)
    return found


def test_productive_invocation_fields_are_methodical():
    print("== every PRODUCTIVE effective_values field is methodical (AST) ==")
    found = productive_effective_values()
    check("the AST found effective_values for EVERY enforced stage",
          set(found) == set(sr.STAGE_DOMAINS) and all(found.values()))
    offenders = []
    for stage, fields in found.items():
        values = {name: {"value": 1, "source": "CONFIG"} for name in sorted(fields)}
        offenders += ["%s: %s" % (stage, problem)
                      for problem in ei.non_methodical_fields(stage, values)]
    for stage in sorted(found):
        print("   %-18s %s" % (stage, ", ".join(sorted(found[stage]))))
    check("57/58: no productive runner registers a non-methodical field", offenders == [])
    for problem in offenders:
        print("   OFFENDER:", problem)
    # and the productive dicts really pass the builder, not just the classifier
    refused = []
    for stage, fields in found.items():
        values = {name: {"value": 1, "source": "CONFIG"} for name in sorted(fields)}
        try:
            ei.build_invocation("r", stage, "p", values)
        except ei.InvocationRefused as failure:
            refused.append("%s: %s" % (stage, failure))
    check("no productive stage would be refused by the invocation builder", refused == [])
    for problem in refused:
        print("   REFUSED:", problem)


def _refuses_non_methodical(stage, field, value) -> bool:
    try:
        ei.build_invocation("r", stage, "p", {field: {"value": value, "source": "CONFIG"}})
        return False
    except ei.InvocationRefused:
        return True


def _refuses_duplicate() -> bool:
    try:
        ei.build_invocation("r", "correctness", "p",
                            {"niter": {"value": 1, "source": "CONFIG"}})
        return False
    except ei.InvocationRefused:
        return True


# ---------------------------------------------------------------------------
# main-domain identities/evidence: PRESENCE (REQUIRED_IDENTITIES /
# REQUIRED_EVIDENCE -> UNRESOLVED) vs DRIFT (domain comparison -> DRIFT)
# pre-start fix 2026-09-16, STAGE_RUNTIME_MAIN_MPI_IDENTITY_NOT_MEASURABLE
# ---------------------------------------------------------------------------

def drop_identity(domain, tool):
    def apply(environments):
        environments[domain]["tool_identities"].pop(tool, None)
        return environments
    return apply


def drop_evidence(domain, key):
    def apply(environments):
        environments[domain]["evidence"].pop(key, None)
        return environments
    return apply


def _stamp(world, stage, prober):
    """(outcome, result-or-exception) of one enforce_stage attempt."""
    try:
        result = sr.enforce_stage(world.config, world.run_id, stage,
                                  profile="fixture", prober=prober)
        return "STAMPED", result
    except sr.StageRuntimeUnresolved as unresolved:
        return "UNRESOLVED", unresolved
    except sr.StageRuntimeDrift as drift:
        return "DRIFT", drift


def test_main_domain_presence_vs_drift():
    print("== presence vs drift: REQUIRED_IDENTITIES / REQUIRED_EVIDENCE vs domain comparison ==")
    from thesis.evaluation import probe_runtime_identity as pri

    check("policy: main requires only the compiler identity (MPI is evidence, never a tool identity)",
          sr.REQUIRED_IDENTITIES["main"] == ("compiler",)
          and "mpi" not in sr.REQUIRED_IDENTITIES["main"])
    check("policy: main requires the mpi_version_line evidence to be present",
          sr.REQUIRED_EVIDENCE["main"] == ("mpi_version_line",)
          and sr.REQUIRED_EVIDENCE["parcoach"] == () and sr.REQUIRED_EVIDENCE["llov"] == ())
    check("the canonical MPI source is the productive probe's main evidence (mpi_version_line); "
          "no second MPI identity definition",
          "mpi" not in pri.ROLE_TOOLS["main"]
          and "mpi_version_line" in fake_environments()["main"]["evidence"]
          and "mpi" not in fake_environments()["main"]["tool_identities"])

    # A: compiler present, mpi evidence present, identical -> PASS
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        outcome, result = _stamp(world, "correctness", fake_prober)
        check("A: compiler present + mpi evidence present + identical -> PASS (stamped)",
              outcome == "STAMPED" and result["enforced"]
              and bool(result.get("stage_runtime_sha256")))
    # B: compiler missing -> UNRESOLVED by REQUIRED_IDENTITIES
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        outcome, exc = _stamp(world, "correctness", prober_with(drop_identity("main", "compiler")))
        check("B: compiler missing -> UNRESOLVED (REQUIRED_IDENTITIES, tool_identities)",
              outcome == "UNRESOLVED" and exc.drift_fields == ["tool_identities"]
              and "required identities not measurable: compiler" in str(exc))
    # C: mpi_version_line missing/empty -> UNRESOLVED by REQUIRED_EVIDENCE
    #    (a DIFFERENT mechanism than D: presence, not comparison)
    for label, mutate in (("C: mpi_version_line missing", drop_evidence("main", "mpi_version_line")),
                          ("C2: mpi_version_line empty", mutate_evidence("main", "mpi_version_line", ""))):
        with tempfile.TemporaryDirectory() as tmp:
            world = fresh_world(tmp)
            outcome, exc = _stamp(world, "correctness", prober_with(mutate))
            check("%s -> UNRESOLVED (REQUIRED_EVIDENCE, evidence), not a drift" % label,
                  outcome == "UNRESOLVED" and exc.drift_fields == ["evidence"]
                  and "required evidence not measurable: mpi_version_line" in str(exc))
    # D: mpi_version_line present but changed -> REQUIRED_EVIDENCE passes; the
    #    existing domain comparison of `evidence` reports DRIFT (no second logic)
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        outcome, exc = _stamp(world, "correctness",
                              prober_with(mutate_evidence("main", "mpi_version_line",
                                                          "mpirun (Open MPI) 5.0.0")))
        check("D: mpi_version_line present but changed -> DRIFT via the evidence comparison "
              "(not UNRESOLVED)",
              outcome == "DRIFT" and exc.failure_class == "STAGE_RUNTIME_DRIFT"
              and exc.drift_fields == ["evidence"]
              and "required evidence not measurable" not in str(exc))
    # E: compiler changed -> DRIFT (tool_identities)
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        outcome, exc = _stamp(world, "correctness",
                              prober_with(mutate_identity("main", "compiler", "g++ 14.0.0")))
        check("E: compiler changed -> DRIFT (tool_identities)",
              outcome == "DRIFT" and exc.drift_fields == ["tool_identities"])
    # F: image identity changed -> DRIFT
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        outcome, exc = _stamp(world, "correctness",
                              prober_with(mutate_field("main", "image_id", "sha256:" + "f" * 64)))
        check("F: image identity changed -> DRIFT (image_id)",
              outcome == "DRIFT" and "image_id" in exc.drift_fields)
    # G/H: parcoach and llov unchanged -> their stages stamp
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        g_outcome, g_result = _stamp(world, "static.parcoach", fake_prober)
        h_outcome, h_result = _stamp(world, "static.llov", fake_prober)
        check("G: parcoach unchanged -> static.parcoach stamped",
              g_outcome == "STAMPED" and g_result["enforced"])
        check("H: llov unchanged -> static.llov stamped",
              h_outcome == "STAMPED" and h_result["enforced"])
    # I: the REAL productive main-probe shape (exactly the keys the productive
    #    probe emits, MPI only as evidence) -> PASS
    shape = fake_environments()["main"]
    check("I: the fixture world's main domain carries exactly the productive probe shape",
          set(shape["tool_identities"]) == set(pri.ROLE_TOOLS["main"])
          and set(shape["evidence"]) == {"mpi_version_line", "toolchain_versions_file",
                                         "toolchain_versions_sha256", "interpreter_identity"})
    with tempfile.TemporaryDirectory() as tmp:
        world = fresh_world(tmp)
        outcome, result = _stamp(world, "correctness", fake_prober)
        check("I: real productive main-probe shape -> PASS (stamped, MPI via evidence)",
              outcome == "STAMPED" and result["enforced"])


if __name__ == "__main__":
    main()
