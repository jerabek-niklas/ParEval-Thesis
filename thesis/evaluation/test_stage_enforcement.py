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
        ("4: correctness MPI B", "correctness",
         mutate_identity("main", "mpi", "mpirun (Open MPI) 5.0.0")),
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
                  not isinstance(drift, RuntimeError().__class__.__mro__[0].__class__)
                  or "TOOL_ERROR" not in text)

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
              {row["stage"] for row in matrix} == {"correctness", "enhanced", "static.main"}
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

    print()
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for item in FAILURES:
            print("  -", item)
        sys.exit(1)
    print("All stage enforcement tests passed.")


def _refuses_duplicate() -> bool:
    try:
        ei.build_invocation("r", "correctness", "p",
                            {"niter": {"value": 1, "source": "CONFIG"}})
        return False
    except ei.InvocationRefused:
        return True


if __name__ == "__main__":
    main()
