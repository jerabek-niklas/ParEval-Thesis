"""Tests of thesis.study_closure.coverage: synthetic reports in temp
directories, fake contexts over temp trees, fake native verifier modules and
the pure helpers (never the real results tree). The real-repository tests -
the cheap evidence checks, both coverage maps and the 004 re-verification of
ONE model (minutes) - run only with STUDY_CLOSURE_REAL=1.

    python3 -B -m unittest -v thesis.study_closure.test_coverage
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import types
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest import mock

from thesis.evaluation import run_authorization as ra
from thesis.study_closure import core
from thesis.study_closure import coverage as cov

RUN_002 = core.OWNERS[1]
RUN_003 = core.OWNERS[2]
RUN_004 = core.OWNERS[3]
REAL = os.environ.get("STUDY_CLOSURE_REAL") == "1"
FAKE_VERIFIER = "_study_closure_test_fake_verifier"
FAKE_RUNNER = "_study_closure_test_fake_runner"


def variants_done():
    return OrderedDict((variant, cov.VARIANT_DONE) for variant in core.VARIANTS)


def write_json(root, relative, document):
    path = Path(root) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return relative


def check(name, status=core.PASS, detail=None):
    return OrderedDict([("check", name), ("status", status), ("detail", detail)])


def successor_report(run, model, status=core.PASS, scope=cov.SUCCESSOR_SCOPE, open_work=None,
                     variants=None, checks=None, schema=cov.SUCCESSOR_SCHEMA, written="2026-10-13T00:00:00Z"):
    if open_work is None:
        open_work = OrderedDict([(cov.PARENT_OPEN_WORK_KEY, {"owner": core.PARENT, "samples": 3}),
                                 ("%s__static_feedback__iter2" % run, {"owner": run, "samples": 2})])
    if checks is None:
        checks = [check(cov.AUTHORITY_CHECK), check("static_feedback: iteration-1 decisions reproduce"),
                  check("test_feedback: adopted"), check("provider endpoint binding")]
    return OrderedDict([
        ("schema_version", schema), ("scope", scope), ("run_id", run), ("model_id", model),
        ("status", status), ("variants", variants if variants is not None else variants_done()),
        ("model_complete", False), ("model_complete_reason", "open work"),
        ("counts", OrderedDict([("reused", OrderedDict()), ("new", OrderedDict([("iteration2_requests", 2)]))])),
        ("open_work", open_work), ("checks", checks), ("written_at_utc", written)])


def native_names():
    """The check names of a 002/003-style read-only result (the evidence floor
    plus a few trajectory checks), in native order."""
    return ([cov.AUTHORITY_CHECK, "predecessor bytes, membership and bindings unchanged"]
            + list(cov.DEEP_ONLY_CHECKS)
            + ["static_feedback: wave done", "static_feedback: continued",
               "test_feedback: adopted predecessor loop terminal", "test_feedback: adopted",
               "combined_feedback: wave done", "combined_feedback: continued"]
            + list(cov.FLOOR_CHECKS[:3])
            + ["provider endpoint equals the predecessor authorization", "provider endpoint binding"])


def native_result(authority_detail=cov.NO_AUTHORITY_DETAIL, failing=(), names=None, counts=None,
                  variants=None, run=RUN_003, model="m", open_work=None):
    """A read-only verify_model result: the authority check fails, the rest passes."""
    names = names or native_names()
    checks = []
    for name in names:
        if name == cov.AUTHORITY_CHECK:
            checks.append(check(name, core.FAIL, authority_detail))
        elif name in failing:
            checks.append(check(name, core.FAIL, "RecoveryRefused: drifted"))
        else:
            checks.append(check(name))
    if open_work is None:
        open_work = OrderedDict([(cov.PARENT_OPEN_WORK_KEY, {}), ("%s__static_feedback__iter2" % run, {})])
    return OrderedDict([("schema_version", cov.SUCCESSOR_SCHEMA), ("scope", cov.SUCCESSOR_SCOPE),
                        ("run_id", run), ("model_id", model),
                        ("status", "STOP"), ("variants", variants or variants_done()),
                        ("counts", counts or OrderedDict([("reused", OrderedDict()),
                                                          ("new", OrderedDict([("x", 1)]))])),
                        ("open_work", open_work), ("checks", checks)])


def persisted_from(result):
    """The report the run persisted: identical, but under a real authority."""
    document = core.json_stable(result)
    document["status"] = core.PASS
    for entry in document["checks"]:
        if entry["check"] == cov.AUTHORITY_CHECK:
            entry["status"] = core.PASS
            entry["detail"] = None
    document["written_at_utc"] = "2026-10-13T00:00:00Z"
    return document


def shallow_names(names=None):
    return [n for n in (names or native_names()) if n not in cov.DEEP_ONLY_CHECKS]


class Target:
    def __init__(self, model, run):
        self.model_id, self.source_run = model, run


class FakeTable:
    def __init__(self, targets):
        self.targets = targets


class FakeLineage:
    def __init__(self, document):
        self.document = document
        self.origin = (document.get("custody") or {}).get("origin_bindings") or {}


class FakeContext:
    """A context over a temp tree: contracts, manifests and start
    authorizations are consistent dicts (the fragment fingerprint reproduces
    through the native run_authorization helper); run_bindings agree."""

    def __init__(self, root, contracts, table=None, lineage=None, bindings=True):
        self.root = Path(root).resolve()
        self.contracts = OrderedDict(contracts)      # run -> model ids
        self.table = table or FakeTable([])
        self.lineage = lineage
        self.cache = OrderedDict()
        self.options = OrderedDict()
        self.logged = []
        if bindings:
            self.cache["run_bindings"] = OrderedDict(
                (run, OrderedDict([("contract_sha256", self.contract_sha(run)),
                                   ("authorization_sha256", self.authorization_sha(run)),
                                   ("checks", OrderedDict([("frozen_contract", core.PASS),
                                                           ("authorization", core.PASS)]))]))
                for run in self.contracts)

    def log(self, message):
        self.logged.append(message)

    def contract_sha(self, run):
        return hashlib.sha256(("contract:" + run).encode()).hexdigest()

    def authorization_content(self, run):
        content = OrderedDict([("run_id", run), ("decision", ra.DECISION_ALLOWED),
                               ("frozen_contract_sha256", self.contract_sha(run))])
        content["authorization_sha256"] = ra.authorization_fingerprint(content)
        return content

    def authorization_sha(self, run):
        return self.authorization_content(run)["authorization_sha256"]

    def run_config(self, run):
        return OrderedDict([("models", [])])

    def manifest(self, run):
        return OrderedDict([("run_id", run), ("contract_sha256", self.contract_sha(run)),
                            ("authorization", OrderedDict([("authorization_sha256", self.authorization_sha(run))]))])

    def frozen_contract(self, run):
        return OrderedDict([("run_id", run), ("status", "READY"), ("profile", core.RUN_REGISTRY[run]["profile"]),
                            ("contract_sha256", self.contract_sha(run)), ("model_ids", list(self.contracts[run]))])

    def authorization_fragment(self, run):
        return OrderedDict([("content", self.authorization_content(run))])


def fake_modules(script, policy=cov.AUTHORITY_NONE, schema=cov.SUCCESSOR_SCHEMA, bound=(None, None)):
    """A fake native verifier (verify_model scripted per model: a callable
    (model, deep) -> result or raising) and runner module."""
    verifier = types.ModuleType(FAKE_VERIFIER)
    verifier.SCHEMA = schema
    verifier.SCOPE = cov.SUCCESSOR_SCOPE
    verifier.calls = []

    def verify_model(config, config_path, model, authority=None, root=None, deep=True):
        verifier.calls.append((model, deep, authority))
        return script[model](model, deep)

    verifier.verify_model = verify_model
    runner = types.ModuleType(FAKE_RUNNER)

    class NullAuthority:
        contract_sha256 = None
        authorization_sha256 = None

        def check(self):
            raise core.ClosureRefused("read-only mode cannot step a loop")

    class ReadOnlyAuthority(NullAuthority):
        def __init__(self, config):
            self.contract_sha256, self.authorization_sha256 = bound

    runner.NullAuthority = NullAuthority
    runner.ReadOnlyAuthority = ReadOnlyAuthority
    return verifier, runner, policy


def detail_for(run):
    """The authority detail the run's NATIVE policy produces."""
    return cov.NO_AUTHORITY_DETAIL if cov.NATIVE[run][2] == cov.AUTHORITY_NONE else cov.NULL_AUTHORITY_DETAIL


def scripted(run):
    """The default behaviour: a consistent result (deep -> all names)."""
    def behaviour(model, deep):
        return native_result(detail_for(run), run=run, model=model, names=None if deep else shallow_names())
    return behaviour


class SuccessorReportsTest(unittest.TestCase):
    def setUp(self):
        self.models = [core.MODELS[0], core.MODELS[1]]
        self.reports = OrderedDict((m, successor_report(RUN_003, m)) for m in self.models)
        self.targets = OrderedDict((m, [core.PARENT, "%s__static_feedback__iter2" % RUN_003])
                                   for m in self.models)

    def problems(self, reports=None, **kwargs):
        return cov.successor_reports_problems(RUN_003, self.models, reports or self.reports, self.targets,
                                              **kwargs)

    def test_consistent_reports_have_no_problem(self):
        self.assertEqual(self.problems(), [])

    def test_no_contract_model_fails(self):
        self.assertTrue(any("no contract model" in p
                            for p in cov.successor_reports_problems(RUN_003, [], OrderedDict(), OrderedDict())))

    def test_missing_model_fails(self):
        reports = OrderedDict(self.reports)
        reports[self.models[1]] = None
        self.assertTrue(any("report missing" in p for p in self.problems(reports)))

    def test_status_fail_fails(self):
        reports = OrderedDict(self.reports)
        reports[self.models[0]] = successor_report(RUN_003, self.models[0], status=core.FAIL)
        self.assertTrue(any("status is 'FAIL'" in p for p in self.problems(reports)))

    def test_wrong_scope_fails(self):
        reports = OrderedDict(self.reports)
        reports[self.models[0]] = successor_report(RUN_003, self.models[0], scope="ANOTHER_SCOPE")
        self.assertTrue(any("scope is 'ANOTHER_SCOPE'" in p for p in self.problems(reports)))

    def test_wrong_run_id_fails(self):
        reports = OrderedDict(self.reports)
        reports[self.models[0]] = successor_report(RUN_004, self.models[0])
        self.assertTrue(any("run_id" in p for p in self.problems(reports)))

    def test_open_work_outside_the_targets_fails(self):
        reports = OrderedDict(self.reports)
        open_work = OrderedDict([(cov.PARENT_OPEN_WORK_KEY, {}),
                                 ("full_ext_recovery_009__static_feedback__iter2", {})])
        reports[self.models[0]] = successor_report(RUN_003, self.models[0], open_work=open_work)
        self.assertTrue(any("not a phase-2 target" in p for p in self.problems(reports)))

    def test_open_work_error_fails(self):
        reports = OrderedDict(self.reports)
        reports[self.models[0]] = successor_report(RUN_003, self.models[0], open_work={"error": "x"})
        self.assertTrue(any("open_work absent or errored" in p for p in self.problems(reports)))

    def test_variants_not_done_fails(self):
        variants = variants_done()
        variants[core.VARIANTS[0]] = "STOP"
        reports = OrderedDict(self.reports)
        reports[self.models[0]] = successor_report(RUN_003, self.models[0], variants=variants)
        self.assertTrue(any("variants not all done" in p for p in self.problems(reports)))

    def test_failing_check_in_report_fails(self):
        reports = OrderedDict(self.reports)
        reports[self.models[0]] = successor_report(RUN_003, self.models[0],
                                                   checks=[check("a"), check("b", core.FAIL)])
        self.assertTrue(any("not all PASS" in p for p in self.problems(reports)))

    def test_missing_written_at_fails(self):
        reports = OrderedDict(self.reports)
        reports[self.models[0]] = successor_report(RUN_003, self.models[0], written=None)
        self.assertTrue(any("written_at_utc" in p for p in self.problems(reports)))

    def test_report_of_a_foreign_model_fails(self):
        reports = OrderedDict(self.reports)
        reports[core.MODELS[5]] = successor_report(RUN_003, core.MODELS[5])
        self.assertTrue(any("outside the contract" in p for p in self.problems(reports)))

    def test_unexpected_file_fails(self):
        self.assertTrue(any("unexpected file" in p for p in self.problems(unexpected_files=["x.tmp"])))

    def test_open_work_key_of_the_parent(self):
        self.assertEqual(cov.open_work_source_run(cov.PARENT_OPEN_WORK_KEY), core.PARENT)
        self.assertEqual(cov.open_work_source_run("r__static_feedback__iter2"), "r__static_feedback__iter2")


class SuccessorReportsFactsTest(unittest.TestCase):
    """successor_reports_facts over a temp verification directory."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.models = [core.MODELS[0], core.MODELS[1]]
        targets = [Target(m, run) for m in self.models
                   for run in (core.PARENT, "%s__static_feedback__iter2" % RUN_003)]
        self.ctx = FakeContext(self.tmp.name, {RUN_003: self.models}, table=FakeTable(targets))
        for model in self.models:
            write_json(self.ctx.root, cov.successor_report_relative(RUN_003, model), successor_report(RUN_003, model))

    def tearDown(self):
        self.tmp.cleanup()

    def test_consistent_directory_passes_with_raw_shas(self):
        ok, detail = cov.successor_reports_facts(self.ctx, RUN_003)
        self.assertTrue(ok, detail["problems"])
        self.assertEqual(detail["files"], 2)
        self.assertTrue(detail["check_names_uniform"])
        for model in self.models:
            expected = hashlib.sha256((self.ctx.root / cov.successor_report_relative(RUN_003, model)).read_bytes()).hexdigest()
            self.assertEqual(detail["per_model"][model]["raw_sha256"], expected)
            self.assertEqual(detail["per_model"][model]["open_work_phase2_targets"], 2)

    def test_missing_report_file_fails(self):
        (self.ctx.root / cov.successor_report_relative(RUN_003, self.models[1])).unlink()
        ok, detail = cov.successor_reports_facts(self.ctx, RUN_003)
        self.assertFalse(ok)
        self.assertTrue(any("report missing" in p for p in detail["problems"]))
        self.assertIsNone(detail["per_model"][self.models[1]])

    def test_unexpected_file_in_the_directory_fails(self):
        write_json(self.ctx.root, core.RUN_REGISTRY[RUN_003]["verification"] + "/stray.json", {})
        ok, detail = cov.successor_reports_facts(self.ctx, RUN_003)
        self.assertFalse(ok)
        self.assertEqual(detail["unexpected_files"], ["stray.json"])


class ClassifyRetrospectiveTest(unittest.TestCase):
    def test_only_the_authority_check_failing_passes(self):
        verdict = cov.classify_retrospective(native_result())
        self.assertEqual(verdict["retrospective_status"], cov.RETROSPECTIVE_PASS, verdict["problems"])
        self.assertIsNone(verdict["persisted_match"])
        self.assertEqual(verdict["failing"], [cov.AUTHORITY_CHECK])

    def test_read_only_refusal_detail_accepted(self):
        verdict = cov.classify_retrospective(native_result(cov.NULL_AUTHORITY_DETAIL))
        self.assertEqual(verdict["retrospective_status"], cov.RETROSPECTIVE_PASS)

    def test_expected_authority_detail_enforced_when_given(self):
        result = native_result(cov.NULL_AUTHORITY_DETAIL)
        ok = cov.classify_retrospective(result, authority_detail=cov.NULL_AUTHORITY_DETAIL)
        self.assertEqual(ok["retrospective_status"], cov.RETROSPECTIVE_PASS)
        bad = cov.classify_retrospective(result, authority_detail=cov.NO_AUTHORITY_DETAIL)
        self.assertEqual(bad["retrospective_status"], core.FAIL)
        self.assertTrue(any("unexpected authority detail" in p for p in bad["problems"]))

    def test_unexpected_authority_detail_fails(self):
        verdict = cov.classify_retrospective(native_result("KeyError: 'x'"))
        self.assertEqual(verdict["retrospective_status"], core.FAIL)

    def test_another_failing_check_fails(self):
        verdict = cov.classify_retrospective(native_result(failing=("static_feedback: wave done",)))
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("static_feedback: wave done" in p for p in verdict["problems"]))

    def test_authority_check_passing_in_read_only_mode_fails(self):
        result = native_result()
        result["checks"][0]["status"] = core.PASS
        self.assertEqual(cov.classify_retrospective(result)["retrospective_status"], core.FAIL)

    def test_authority_check_absent_or_duplicated_fails(self):
        absent = native_result(names=[n for n in native_names() if n != cov.AUTHORITY_CHECK])
        verdict = cov.classify_retrospective(absent)
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("occurs 0 times" in p for p in verdict["problems"]))
        duplicated = native_result()
        duplicated["checks"].append(check(cov.AUTHORITY_CHECK, core.FAIL, cov.NO_AUTHORITY_DETAIL))
        verdict = cov.classify_retrospective(duplicated)
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("occurs 2 times" in p for p in verdict["problems"]))

    def test_substitute_not_ok_fails(self):
        verdict = cov.classify_retrospective(native_result(), substitute_ok=False)
        self.assertEqual(verdict["retrospective_status"], core.FAIL)

    def test_no_checks_fails(self):
        result = native_result()
        result["checks"] = []
        self.assertEqual(cov.classify_retrospective(result)["retrospective_status"], core.FAIL)

    def test_only_the_authority_check_is_no_evidence(self):
        """Regression: a result carrying nothing but the failing authority
        check (variants trivially done) must not classify PASS."""
        verdict = cov.classify_retrospective(native_result(names=[cov.AUTHORITY_CHECK]))
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("trajectory verdicts" in p for p in verdict["problems"]))
        self.assertTrue(any("model-independent checks missing" in p for p in verdict["problems"]))

    def test_skipped_variant_fails(self):
        names = [n for n in native_names() if not n.startswith("combined_feedback:")]
        verdict = cov.classify_retrospective(native_result(names=names))
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("combined_feedback: 0 PASS trajectory verdicts" in p for p in verdict["problems"]))

    def test_two_verdicts_for_one_variant_fail(self):
        verdict = cov.classify_retrospective(native_result(names=native_names() + ["static_feedback: fresh"]))
        self.assertEqual(verdict["retrospective_status"], core.FAIL)

    def test_missing_immutability_or_endpoint_check_fails(self):
        no_bytes = [n for n in native_names() if not n.endswith(cov.IMMUTABILITY_CHECK_SUFFIX)]
        verdict = cov.classify_retrospective(native_result(names=no_bytes))
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("immutability" in p for p in verdict["problems"]))
        no_endpoint = [n for n in native_names() if not n.startswith(cov.ENDPOINT_CHECK_PREFIX)]
        verdict = cov.classify_retrospective(native_result(names=no_endpoint))
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("provider endpoint" in p for p in verdict["problems"]))

    def test_004_style_names_satisfy_the_floor(self):
        names = ([cov.AUTHORITY_CHECK, "recovery_001 and sibling successor bytes, membership and bindings unchanged",
                  "no repair evidence of a 004 model outside 004"] + list(cov.DEEP_ONLY_CHECKS)
                 + ["%s: %s" % (v, c) for v in core.VARIANTS for c in ("wave done", "fresh")]
                 + list(cov.FLOOR_CHECKS[:3]) + ["provider endpoint equals the origin authorization",
                                                 "provider endpoint binding"])
        verdict = cov.classify_retrospective(native_result(names=names, run=RUN_004))
        self.assertEqual(verdict["retrospective_status"], cov.RETROSPECTIVE_PASS, verdict["problems"])

    def test_open_work_error_fails(self):
        """Regression: the native verifiers swallow open-work exceptions into
        {'error': ...}; the retrospective must not hide that."""
        verdict = cov.classify_retrospective(native_result(open_work={"error": "AttributeError: 'NoneType'"}))
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("open_work absent or errored" in p for p in verdict["problems"]))

    def test_open_work_absent_fails(self):
        result = native_result()
        del result["open_work"]
        verdict = cov.classify_retrospective(result)
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("open_work absent" in p for p in verdict["problems"]))

    def test_persisted_report_reproduced(self):
        result = native_result()
        verdict = cov.classify_retrospective(result, persisted_from(result))
        self.assertEqual(verdict["retrospective_status"], cov.RETROSPECTIVE_PASS, verdict["problems"])
        self.assertTrue(verdict["persisted_match"])

    def test_persisted_open_work_keys_drift_fails(self):
        result = native_result()
        persisted = persisted_from(result)
        persisted["open_work"]["%s__combined_feedback__iter2" % RUN_003] = {}
        verdict = cov.classify_retrospective(result, persisted)
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("open_work keys differ" in d for d in verdict["differences"]))

    def test_persisted_status_drift_fails(self):
        result = native_result()
        persisted = persisted_from(result)
        persisted["checks"][5]["status"] = core.FAIL
        verdict = cov.classify_retrospective(result, persisted)
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertFalse(verdict["persisted_match"])
        self.assertTrue(any("statuses differ" in d for d in verdict["differences"]))

    def test_persisted_check_names_drift_fails(self):
        result = native_result()
        persisted = persisted_from(result)
        persisted["checks"].append(check("combined_feedback: llov supplement covers every assembled iteration-1 sample"))
        verdict = cov.classify_retrospective(result, persisted)
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertTrue(any("check names differ" in d for d in verdict["differences"]))

    def test_persisted_counts_drift_fails(self):
        result = native_result()
        persisted = persisted_from(result)
        persisted["counts"]["new"]["x"] = 2
        verdict = cov.classify_retrospective(result, persisted)
        self.assertEqual(verdict["retrospective_status"], core.FAIL)
        self.assertIn("counts differ", verdict["differences"])

    def test_persisted_variants_drift_fails(self):
        result = native_result()
        persisted = persisted_from(result)
        persisted["variants"][core.VARIANTS[2]] = "STOP"
        verdict = cov.classify_retrospective(result, persisted)
        self.assertEqual(verdict["retrospective_status"], core.FAIL)

    def test_shallow_run_tolerates_only_the_deep_only_checks(self):
        full = native_result()
        persisted = persisted_from(full)
        shallow = native_result(names=shallow_names())
        self.assertEqual(cov.classify_retrospective(shallow, persisted, deep=False)["retrospective_status"],
                         cov.RETROSPECTIVE_PASS)
        self.assertEqual(cov.classify_retrospective(shallow, persisted, deep=True)["retrospective_status"],
                         core.FAIL)
        thinner = native_result(names=[n for n in shallow_names() if n != "static_feedback: wave done"])
        self.assertEqual(cov.classify_retrospective(thinner, persisted, deep=False)["retrospective_status"],
                         core.FAIL)


class RetrospectiveRunProblemsTest(unittest.TestCase):
    def record(self, deep=True, status=cov.RETROSPECTIVE_PASS, persisted_match=True, names=None):
        result = native_result(names=names)
        return OrderedDict([("retrospective_status", status), ("checks", result["checks"]),
                            ("persisted_match", persisted_match), ("deep", deep), ("problems", [])])

    def test_all_models_deep_and_passing(self):
        records = OrderedDict([("m1", self.record()), ("m2", self.record())])
        self.assertEqual(cov.retrospective_run_problems(records, ["m1", "m2"], True), [])
        self.assertEqual(cov.retrospective_run_problems(records, ["m1", "m2"], False), [])

    def test_no_contract_model_fails(self):
        self.assertTrue(any("no contract model" in p for p in cov.retrospective_run_problems(OrderedDict(), [], True)))

    def test_missing_model_fails(self):
        records = OrderedDict([("m1", self.record())])
        self.assertTrue(any("m2: not re-verified" in p for p in cov.retrospective_run_problems(records, ["m1", "m2"], True)))

    def test_failing_model_fails(self):
        records = OrderedDict([("m1", self.record(status=core.FAIL))])
        self.assertTrue(cov.retrospective_run_problems(records, ["m1"], False))

    def test_persisted_mismatch_fails_when_a_report_is_expected(self):
        records = OrderedDict([("m1", self.record(persisted_match=None))])
        self.assertTrue(cov.retrospective_run_problems(records, ["m1"], True))
        self.assertEqual(cov.retrospective_run_problems(records, ["m1"], False), [])

    def test_no_deep_model_fails(self):
        records = OrderedDict([("m1", self.record(deep=False))])
        self.assertTrue(any("deep=True" in p for p in cov.retrospective_run_problems(records, ["m1"], False)))

    def test_shallow_models_are_covered_by_one_deep_model(self):
        records = OrderedDict([("m1", self.record()), ("m2", self.record(deep=False, names=shallow_names()))])
        self.assertEqual(cov.retrospective_run_problems(records, ["m1", "m2"], False), [])
        records["m1"] = self.record(names=shallow_names())
        self.assertTrue(any("deep-only check" in p for p in cov.retrospective_run_problems(records, ["m1", "m2"], False)))

    def test_without_persisted_report_the_names_must_equal_the_deep_model(self):
        """Regression (002): a later model whose verifier emitted other check
        names than the run's deep model fails although every check passed."""
        other = native_names() + ["static_feedback: llov supplement covers every assembled iteration-1 sample"]
        records = OrderedDict([("m1", self.record()), ("m2", self.record(names=other))])
        problems = cov.retrospective_run_problems(records, ["m1", "m2"], False)
        self.assertTrue(any("m2: check names differ from the deep model m1" in p for p in problems), problems)
        # with a persisted report the per-model comparison already covers it
        self.assertEqual(cov.retrospective_run_problems(records, ["m1", "m2"], True), [])
        thin = [n for n in native_names() if n != "static_feedback: wave done"]
        records = OrderedDict([("m1", self.record()), ("m2", self.record(deep=False, names=thin))])
        self.assertTrue(any("check names differ" in p for p in cov.retrospective_run_problems(records, ["m1", "m2"], False)))


class AuthoritySubstituteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = FakeContext(self.tmp.name, {RUN_004: [core.MODELS[0]]})

    def tearDown(self):
        self.tmp.cleanup()

    def test_consistent_facts_with_agreeing_bindings_are_ok(self):
        substitute = cov.authority_substitute(self.ctx, RUN_004)
        self.assertTrue(substitute["ok"], substitute["problems"])
        self.assertTrue(substitute["run_bindings_agree"])
        self.assertEqual(substitute["replaced_by"], ["runs:%s:authorization" % RUN_004, "runs:%s:frozen_contract" % RUN_004])

    def test_missing_run_bindings_is_input_unavailable(self):
        """Regression: without the runs section the substitution claim has no backing."""
        del self.ctx.cache["run_bindings"]
        substitute = cov.authority_substitute(self.ctx, RUN_004)
        self.assertFalse(substitute["ok"])
        self.assertIsNone(substitute["run_bindings_agree"])
        self.assertTrue(any("input unavailable: run_bindings" in p for p in substitute["problems"]))
        self.ctx.cache["run_bindings"] = OrderedDict()
        substitute = cov.authority_substitute(self.ctx, RUN_004)
        self.assertFalse(substitute["ok"])
        self.assertTrue(any("input unavailable: run_bindings[%s]" % RUN_004 in p for p in substitute["problems"]))

    def test_disagreeing_bindings_fail(self):
        self.ctx.cache["run_bindings"][RUN_004]["contract_sha256"] = "d" * 64
        substitute = cov.authority_substitute(self.ctx, RUN_004)
        self.assertFalse(substitute["ok"])
        self.assertFalse(substitute["run_bindings_agree"])

    def test_runs_section_check_not_pass_fails(self):
        self.ctx.cache["run_bindings"][RUN_004]["checks"]["authorization"] = core.FAIL
        substitute = cov.authority_substitute(self.ctx, RUN_004)
        self.assertFalse(substitute["ok"])
        self.assertTrue(any("runs section checks not PASS" in p for p in substitute["problems"]))

    def test_broken_authorization_fingerprint_fails(self):
        content = self.ctx.authorization_content(RUN_004)
        content["decision"] = "START_REFUSED"
        with mock.patch.object(self.ctx, "authorization_fragment", return_value=OrderedDict([("content", content)])):
            substitute = cov.authority_substitute(self.ctx, RUN_004)
        self.assertFalse(substitute["ok"])
        self.assertFalse(substitute["authorization"]["ok"])

    def test_contract_manifest_mismatch_fails(self):
        manifest = self.ctx.manifest(RUN_004)
        manifest["contract_sha256"] = "e" * 64
        with mock.patch.object(self.ctx, "manifest", return_value=manifest):
            substitute = cov.authority_substitute(self.ctx, RUN_004)
        self.assertFalse(substitute["frozen_contract"]["ok"])
        self.assertFalse(substitute["ok"])


class NativeVerifierAndAuthorityTest(unittest.TestCase):
    def test_policy_none_needs_no_authority(self):
        self.assertEqual(cov.read_only_authority(None, cov.AUTHORITY_NONE, {}, {}), (None, None))

    def test_read_only_authority_must_be_bound_to_the_substitute(self):
        substitute = OrderedDict([("frozen_contract", {"contract_sha256": "c" * 64}),
                                  ("authorization", {"authorization_sha256": "a" * 64})])
        _, runner, _ = fake_modules({}, bound=("c" * 64, "a" * 64))
        authority, bound = cov.read_only_authority(runner, cov.AUTHORITY_READ_ONLY, {}, substitute)
        self.assertEqual(bound["contract_sha256"], "c" * 64)
        with self.assertRaises(core.ClosureRefused):
            authority.check()
        _, runner, _ = fake_modules({}, bound=("c" * 64, "b" * 64))
        with self.assertRaises(core.ClosureRefused):
            cov.read_only_authority(runner, cov.AUTHORITY_READ_ONLY, {}, substitute)
        _, runner, _ = fake_modules({}, bound=(None, None))
        with self.assertRaises(core.ClosureRefused):
            cov.read_only_authority(runner, cov.AUTHORITY_READ_ONLY, {}, substitute)

    def test_native_verifier_identity_drift_refused(self):
        verifier, runner, policy = fake_modules({}, schema="another.v9")
        with mock.patch.dict(sys.modules, {FAKE_VERIFIER: verifier, FAKE_RUNNER: runner}), \
                mock.patch.dict(cov.NATIVE, {RUN_004: (FAKE_VERIFIER, FAKE_RUNNER, policy)}):
            with self.assertRaises(core.ClosureRefused):
                cov.native_verifier(RUN_004)
        verifier, runner, policy = fake_modules({})
        with mock.patch.dict(sys.modules, {FAKE_VERIFIER: verifier, FAKE_RUNNER: runner}), \
                mock.patch.dict(cov.NATIVE, {RUN_004: (FAKE_VERIFIER, FAKE_RUNNER, policy)}):
            self.assertEqual(cov.native_verifier(RUN_004)[2], cov.AUTHORITY_NONE)


class ProviderIsolationTest(unittest.TestCase):
    VARIABLE = "STUDY_CLOSURE_TEST_PROVIDER_KEY"

    def tearDown(self):
        os.environ.pop(self.VARIABLE, None)

    def test_clean_environment_has_no_problem(self):
        config = {"models": [{"api_key_env": self.VARIABLE}]}
        self.assertEqual(cov.provider_isolation_problems(config), [])
        self.assertEqual(cov.provider_isolation_problems(config, cov.isolated_load_dotenv()), [])

    def test_provider_variable_present_fails(self):
        os.environ[self.VARIABLE] = "not-a-real-key"
        problems = cov.provider_isolation_problems({"models": [{"api_key_env": self.VARIABLE}]})
        self.assertTrue(any("provider variables present" in p for p in problems))

    def test_rebound_load_dotenv_detected(self):
        import thesis.config.load_config as loader

        isolated = cov.isolated_load_dotenv()
        loader.load_dotenv = lambda *a, **k: False       # a re-binding during the run
        problems = cov.provider_isolation_problems({"models": []}, isolated)
        self.assertTrue(any("re-bound" in p for p in problems))
        self.assertEqual(cov.provider_isolation_problems({"models": []}, cov.isolated_load_dotenv()), [])


class ReverifyFlowTest(unittest.TestCase):
    """reverify_model / retrospective_run through a fake native verifier."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.models = ["m1", "m2", "m3"]
        self.ctx = FakeContext(self.tmp.name, {RUN_004: self.models, RUN_002: self.models})
        for model in self.models:
            write_json(self.ctx.root, cov.successor_report_relative(RUN_004, model),
                       persisted_from(native_result(run=RUN_004, model=model)))

    def tearDown(self):
        self.tmp.cleanup()

    def run_fake(self, run, script, function, *args, **kwargs):
        verifier, runner, policy = fake_modules(script, policy=cov.NATIVE[run][2],
                                                bound=(self.ctx.contract_sha(run), self.ctx.authorization_sha(run)))
        self.last_verifier = verifier
        with mock.patch.dict(sys.modules, {FAKE_VERIFIER: verifier, FAKE_RUNNER: runner}), \
                mock.patch.dict(cov.NATIVE, {run: (FAKE_VERIFIER, FAKE_RUNNER, policy)}):
            return function(*args, **kwargs), verifier

    def test_reverify_model_consistent_record(self):
        script = dict((m, scripted(RUN_004)) for m in self.models)
        record, verifier = self.run_fake(RUN_004, script, cov.reverify_model, self.ctx, RUN_004, "m1", True)
        self.assertEqual(record["retrospective_status"], cov.RETROSPECTIVE_PASS, record["problems"])
        self.assertTrue(record["persisted_match"])
        self.assertEqual(record["authority_variant"], cov.AUTHORITY_NONE)
        self.assertEqual(record["open_work_entries"], 2)
        self.assertIsNone(record["open_work_error"])
        self.assertEqual(verifier.calls, [("m1", True, None)])
        summary = cov.retrospective_summary(record)
        self.assertEqual(summary["open_work_keys"], record["open_work_keys"])
        json.dumps(core.json_stable(summary))

    def test_read_only_authority_policy_uses_the_runner(self):
        script = dict((m, lambda model, deep: native_result(cov.NULL_AUTHORITY_DETAIL, run=RUN_002, model=model))
                      for m in self.models)
        record, verifier = self.run_fake(RUN_002, script, cov.reverify_model, self.ctx, RUN_002, "m1", True)
        self.assertEqual(record["retrospective_status"], cov.RETROSPECTIVE_PASS, record["problems"])
        self.assertEqual(record["authority_variant"], cov.AUTHORITY_READ_ONLY)
        self.assertEqual(record["authority_bound_to"]["contract_sha256"], self.ctx.contract_sha(RUN_002))
        self.assertIsNone(record["persisted_match"])
        self.assertIsNotNone(verifier.calls[0][2])

    def test_wrong_authority_detail_for_the_policy_fails(self):
        script = {"m1": lambda model, deep: native_result(cov.NULL_AUTHORITY_DETAIL, run=RUN_004, model=model)}
        record, _ = self.run_fake(RUN_004, script, cov.reverify_model, self.ctx, RUN_004, "m1", True)
        self.assertEqual(record["retrospective_status"], core.FAIL)
        self.assertTrue(any("unexpected authority detail" in p for p in record["problems"]))

    def test_result_identity_drift_refused(self):
        script = {"m1": lambda model, deep: native_result(run=RUN_003, model=model)}
        with self.assertRaises(core.ClosureRefused):
            self.run_fake(RUN_004, script, cov.reverify_model, self.ctx, RUN_004, "m1", True)
        script = {"m1": lambda model, deep: native_result(run=RUN_004, model="other")}
        with self.assertRaises(core.ClosureRefused):
            self.run_fake(RUN_004, script, cov.reverify_model, self.ctx, RUN_004, "m1", True)

    def test_missing_persisted_report_fails_before_the_native_run(self):
        (self.ctx.root / cov.successor_report_relative(RUN_004, "m1")).unlink()
        script = {"m1": scripted(RUN_004)}
        with self.assertRaises(core.ClosureRefused):
            self.run_fake(RUN_004, script, cov.reverify_model, self.ctx, RUN_004, "m1", True)
        self.assertEqual(self.last_verifier.calls, [])

    def test_open_work_error_fails_the_model(self):
        script = {"m1": lambda model, deep: native_result(run=RUN_004, model=model, open_work={"error": "x"})}
        record, _ = self.run_fake(RUN_004, script, cov.reverify_model, self.ctx, RUN_004, "m1", True)
        self.assertEqual(record["retrospective_status"], core.FAIL)
        self.assertEqual(record["open_work_error"], "x")
        self.assertTrue(any("open_work absent or errored" in p for p in record["problems"]))

    def test_run_flips_to_shallow_after_a_slow_deep_model(self):
        script = dict((m, scripted(RUN_004)) for m in self.models)
        with mock.patch.object(cov, "DEEP_SECONDS_LIMIT", -1.0):
            (ok, detail), verifier = self.run_fake(RUN_004, script, cov.retrospective_run, self.ctx, RUN_004)
        self.assertTrue(ok, detail["problems"])
        self.assertEqual([c[1] for c in verifier.calls], [True, False, False])
        records = self.ctx.cache["successor_reverification"][RUN_004]
        self.assertEqual([r["deep"] for r in records.values()], [True, False, False])
        self.assertTrue(all(r["persisted_match"] for r in records.values()))
        self.assertEqual(detail["per_model"]["m2"]["checks"], len(shallow_names()))
        json.dumps(core.json_stable(detail))

    def test_a_raising_model_becomes_a_fail_record_and_the_run_continues(self):
        def boom(model, deep):
            raise RuntimeError("torn ledger")
        script = {"m1": scripted(RUN_004), "m2": boom, "m3": scripted(RUN_004)}
        (ok, detail), verifier = self.run_fake(RUN_004, script, cov.retrospective_run, self.ctx, RUN_004)
        self.assertFalse(ok)
        self.assertEqual([c[0] for c in verifier.calls], ["m1", "m2", "m3"])
        records = self.ctx.cache["successor_reverification"][RUN_004]
        self.assertEqual(records["m2"]["retrospective_status"], core.FAIL)
        self.assertEqual(records["m2"]["problems"], ["RuntimeError: torn ledger"])
        self.assertEqual(records["m3"]["retrospective_status"], cov.RETROSPECTIVE_PASS)
        self.assertTrue(any("m2: RuntimeError: torn ledger" in p for p in detail["problems"]))

    def test_isolation_violation_stops_the_run(self):
        variable = "STUDY_CLOSURE_TEST_PROVIDER_KEY_FLOW"

        def leak(model, deep):
            os.environ[variable] = "not-a-real-key"
            return scripted(RUN_004)(model, deep)
        script = {"m1": leak, "m2": scripted(RUN_004), "m3": scripted(RUN_004)}
        try:
            with mock.patch.object(self.ctx, "run_config", return_value={"models": [{"api_key_env": variable}]}):
                (ok, detail), verifier = self.run_fake(RUN_004, script, cov.retrospective_run, self.ctx, RUN_004)
        finally:
            os.environ.pop(variable, None)
        self.assertFalse(ok)
        self.assertEqual([c[0] for c in verifier.calls], ["m1"])
        records = self.ctx.cache["successor_reverification"][RUN_004]
        self.assertEqual(list(records), ["m1"])
        self.assertTrue(any("provider isolation violated after" in p for p in records["m1"]["problems"]))
        self.assertTrue(any("m2: not re-verified" in p for p in detail["problems"]))

    def test_run_without_persisted_report_requires_uniform_names(self):
        """Regression (002): the second model's verifier emits an extra check."""
        extra = native_names() + ["static_feedback: llov supplement covers every assembled iteration-1 sample"]
        script = {"m1": scripted(RUN_002),
                  "m2": lambda model, deep: native_result(detail_for(RUN_002), run=RUN_002, model=model, names=extra),
                  "m3": scripted(RUN_002)}
        (ok, detail), _ = self.run_fake(RUN_002, script, cov.retrospective_run, self.ctx, RUN_002)
        self.assertFalse(ok)
        self.assertTrue(any("m2: check names differ from the deep model m1" in p for p in detail["problems"]))
        script["m2"] = scripted(RUN_002)
        self.ctx.cache.pop("successor_reverification")
        (ok, detail), _ = self.run_fake(RUN_002, script, cov.retrospective_run, self.ctx, RUN_002)
        self.assertTrue(ok, detail["problems"])

    def test_substitute_without_run_bindings_fails_every_model(self):
        del self.ctx.cache["run_bindings"]
        script = dict((m, scripted(RUN_004)) for m in self.models)
        (ok, detail), _ = self.run_fake(RUN_004, script, cov.retrospective_run, self.ctx, RUN_004)
        self.assertFalse(ok)
        self.assertFalse(detail["substituted"]["ok"])
        self.assertTrue(any("input unavailable: run_bindings" in p for p in detail["substituted"]["problems"]))


class EvidenceEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.report = write_json(self.root, "reports/r.json", OrderedDict([
            ("model_id", "m"), ("checks", [check("x:a"), check("x:b"), check("y:c")])]))
        self.artifact = write_json(self.root, "artifacts/a.json", {"ok": True})

    def tearDown(self):
        self.tmp.cleanup()

    def test_selected_passing_checks_pass(self):
        entry = cov.evidence_entry(self.root, "e", "s", reports=[self.report], rule=lambda n: n.startswith("x:"),
                                   artifacts=[self.artifact])
        self.assertEqual(entry["status"], core.PASS)
        self.assertEqual(entry["check_count"], 2)
        self.assertEqual(entry["check_names"], ["x:a", "x:b"])
        self.assertEqual(entry["check_statuses"], OrderedDict([("PASS", 2)]))
        expected = hashlib.sha256((self.root / self.artifact).read_bytes()).hexdigest()
        self.assertEqual(entry["artifacts"][0]["raw_sha256"], expected)
        self.assertEqual(entry["artifacts"][0]["relative"], self.artifact)

    def test_no_evidence_fails(self):
        entry = cov.evidence_entry(self.root, "e", "s")
        self.assertEqual(entry["status"], core.FAIL)
        self.assertTrue(any("no evidence" in p for p in entry["problems"]))

    def test_missing_artifact_fails(self):
        entry = cov.evidence_entry(self.root, "e", "s", reports=[self.report], rule=lambda n: True,
                                   artifacts=["artifacts/missing.json"])
        self.assertEqual(entry["status"], core.FAIL)
        self.assertTrue(any("missing artifact" in p for p in entry["problems"]))

    def test_missing_report_fails(self):
        entry = cov.evidence_entry(self.root, "e", "s", reports=["reports/none.json"], rule=lambda n: True)
        self.assertEqual(entry["status"], core.FAIL)

    def test_referenced_failing_check_fails(self):
        report = write_json(self.root, "reports/f.json", {"checks": [check("x:a"), check("x:b", core.FAIL)]})
        entry = cov.evidence_entry(self.root, "e", "s", reports=[report], rule=lambda n: n.startswith("x:"))
        self.assertEqual(entry["status"], core.FAIL)
        self.assertTrue(any("x:b is FAIL" in p for p in entry["problems"]))

    def test_no_matching_check_fails(self):
        entry = cov.evidence_entry(self.root, "e", "s", reports=[self.report], rule=lambda n: n.startswith("z:"))
        self.assertEqual(entry["status"], core.FAIL)
        self.assertTrue(any("no matching check" in p for p in entry["problems"]))

    def test_foreign_report_identity_yields_no_check(self):
        identities = {self.report: OrderedDict([("model_id", "m")])}
        entry = cov.evidence_entry(self.root, "e", "s", reports=[self.report], rule=None, identities=identities)
        self.assertEqual(entry["status"], core.PASS)
        identities = {self.report: OrderedDict([("model_id", "other")])}
        entry = cov.evidence_entry(self.root, "e", "s", reports=[self.report], rule=None, identities=identities)
        self.assertEqual(entry["status"], core.FAIL)
        self.assertEqual(entry["check_count"], 0)
        self.assertTrue(any("foreign report" in p for p in entry["problems"]))

    def test_computed_facts_not_ok_fail(self):
        entry = cov.evidence_entry(self.root, "e", "s", artifacts=[self.artifact],
                                   computed=OrderedDict([("ok", False), ("problems", ["x"])]))
        self.assertEqual(entry["status"], core.FAIL)
        entry = cov.evidence_entry(self.root, "e", "s", artifacts=[self.artifact],
                                   computed=OrderedDict([("ok", True)]))
        self.assertEqual(entry["status"], core.PASS)

    def test_entry_serialises(self):
        entry = cov.evidence_entry(self.root, "e", "s", reports=[self.report], rule=None)
        json.dumps(core.json_stable(entry))

    def test_identity_helpers(self):
        self.assertEqual(cov.report_identity_problems({"a": 1}, OrderedDict([("a", 1), ("b", 2)])),
                         ["b is None (expected 2)"])
        self.assertEqual(cov.report_identity_problems({"a": 1}, None), [])
        identities = cov.phase2_identities(["m"])
        self.assertEqual(list(identities), [cov.phase2_report_relative("m")])
        self.assertEqual(identities[cov.phase2_report_relative("m")]["run_id"], core.PHASE2)
        identities = cov.successor_identities(RUN_003, ["m"])
        self.assertEqual(identities[cov.successor_report_relative(RUN_003, "m")]["scope"], cov.SUCCESSOR_SCOPE)


class EvaluateMapTest(unittest.TestCase):
    def document(self, entry_status=core.PASS, terminal=True, loops=1, retrospective=None, entries=1):
        return OrderedDict([
            ("covered_by", [OrderedDict([("evidence", "e"), ("status", entry_status), ("problems", ["p"])])] * entries),
            ("owned_loops", [OrderedDict([("model", "m"), ("variant", "v"), ("terminal", terminal)])] * loops),
            ("retrospective", retrospective)])

    def test_consistent_document_passes(self):
        ok, problems = cov.evaluate_map(self.document())
        self.assertTrue(ok, problems)

    def test_no_covered_by_entry_fails(self):
        ok, problems = cov.evaluate_map(self.document(entries=0))
        self.assertFalse(ok)
        self.assertTrue(any("no covered_by" in p for p in problems))

    def test_failing_entry_fails(self):
        self.assertFalse(cov.evaluate_map(self.document(entry_status=core.FAIL))[0])

    def test_open_loop_fails(self):
        self.assertFalse(cov.evaluate_map(self.document(terminal=False))[0])

    def test_no_owned_loop_fails(self):
        self.assertFalse(cov.evaluate_map(self.document(loops=0))[0])

    def test_retrospective_per_model_shape(self):
        good = OrderedDict([("m", OrderedDict([("retrospective_status", cov.RETROSPECTIVE_PASS)]))])
        bad = OrderedDict([("m", OrderedDict([("retrospective_status", core.FAIL)]))])
        self.assertTrue(cov.evaluate_map(self.document(retrospective=good))[0])
        self.assertFalse(cov.evaluate_map(self.document(retrospective=bad))[0])

    def test_retrospective_per_run_shape(self):
        good = OrderedDict([("m", OrderedDict([("retrospective_status", cov.RETROSPECTIVE_PASS)]))])
        bad = OrderedDict([("m", OrderedDict([("retrospective_status", core.FAIL)]))])
        self.assertTrue(cov.evaluate_map(self.document(retrospective=OrderedDict([("r1", good), ("r2", None)])))[0])
        self.assertFalse(cov.evaluate_map(self.document(retrospective=OrderedDict([("r1", good), ("r2", bad)])))[0])


class CensusInputTest(unittest.TestCase):
    def test_census_cache_miss_is_input_unavailable(self):
        ctx = FakeContext(tempfile.gettempdir(), {})
        with self.assertRaises(core.ClosureRefused) as caught:
            cov.census_loops(ctx)
        self.assertIn("input unavailable: census", str(caught.exception))
        ctx.cache["census"] = OrderedDict([("loops", [OrderedDict([("owner", cov.ORIGIN)])])])
        loops, source = cov.census_loops(ctx)
        self.assertEqual(len(loops), 1)
        self.assertEqual(source, "ctx.cache[census]")


def inventory(entries):
    """path -> {raw_sha256, size} from path -> (sha, size)."""
    return OrderedDict((p, OrderedDict([("raw_sha256", s), ("size", n)])) for p, (s, n) in entries.items())


class SnapshotWorld:
    """The successor lineages (self-hashed), the phase-2 lineage document
    (custody + protected inventories) and the phase-2 reports of a tiny
    recovery_001 / recovery_002 world under a temp root."""

    def __init__(self, root):
        self.root = Path(root)
        self.origin_contract = "o" * 64
        self.inventory_002_sha = "i" * 64
        self.files_001 = inventory(OrderedDict([
            ("thesis/results/intermediate/%s/a/requests.jsonl" % cov.ORIGIN, ("a" * 64, 10)),
            ("thesis/results/intermediate/%s/b/requests.jsonl" % cov.ORIGIN, ("b" * 64, 20))]))
        self.files_002 = inventory(OrderedDict([
            ("thesis/results/intermediate/%s/c/requests.jsonl" % cov.SUCCESSOR_002, ("c" * 64, 30))]))
        self.lineages = OrderedDict()
        for index, run in enumerate(cov.REVERIFIED_RUNS):
            document = OrderedDict([
                ("schema_version", "test"), ("successor_run", run),
                ("predecessor", OrderedDict([("contract_sha256", self.origin_contract),
                                             ("parent_lineage_sha256", "p" * 64)])),
                ("predecessor_snapshot", OrderedDict([("source_run", cov.ORIGIN), ("files", core.json_stable(self.files_001)),
                                                      ("snapshot_sha256", str(index) * 64)]))])
            if run != cov.SUCCESSOR_002:
                document["sibling_successors"] = OrderedDict([(cov.SUCCESSOR_002, OrderedDict([
                    ("decision", "FROZEN"),
                    ("protected_inventory", OrderedDict([
                        ("schema_version", "test"), ("run_prefix", cov.SUCCESSOR_002), ("file_count", 1),
                        ("files", core.json_stable(self.files_002)), ("inventory_sha256", self.inventory_002_sha)]))]))])
            self.lineages[run] = document
        self.protected = OrderedDict([
            (cov.ORIGIN, OrderedDict([("schema_version", "test"), ("run_prefix", cov.ORIGIN), ("file_count", 2),
                                      ("files", core.json_stable(self.files_001)), ("inventory_sha256", "q" * 64)])),
            (cov.SUCCESSOR_002, OrderedDict([("schema_version", "test"), ("run_prefix", cov.SUCCESSOR_002),
                                             ("file_count", 1), ("files", core.json_stable(self.files_002)),
                                             ("inventory_sha256", self.inventory_002_sha)]))])
        self.custody = OrderedDict([
            ("recovery_001_snapshot_files", 2), ("full_ext_recovery_004_lineage_sha256", None),
            ("sibling_inventories_sha256", OrderedDict([(cov.SUCCESSOR_002, self.inventory_002_sha)])),
            ("origin_bindings", OrderedDict([("contract_sha256", self.origin_contract)]))])
        self.reports = OrderedDict((m, OrderedDict([
            ("schema_version", cov.pv.SCHEMA), ("scope", cov.pv.SCOPE), ("run_id", core.PHASE2), ("model_id", m),
            ("checks", [check("global:immutability"), check("full_ext:x")])])) for m in core.MODELS)

    def context(self):
        """Write the world (self-hashing the lineages) and build the context."""
        shas = OrderedDict()
        for run, document in self.lineages.items():
            document = core.json_stable(document)
            document.pop("lineage_sha256", None)
            document["lineage_sha256"] = cov.lineage_fingerprint(document)
            shas[run] = document["lineage_sha256"]
            write_json(self.root, cov.lineage_relative(run), document)
        write_json(self.root, cov.lineage_relative(core.PHASE2), {"schema_version": "test"})
        for model, report in self.reports.items():
            write_json(self.root, cov.phase2_report_relative(model), report)
        custody = core.json_stable(self.custody)
        if custody["full_ext_recovery_004_lineage_sha256"] is None:
            custody["full_ext_recovery_004_lineage_sha256"] = shas[RUN_004]
        lineage = FakeLineage(OrderedDict([("custody", custody), ("protected", core.json_stable(self.protected))]))
        ctx = FakeContext(self.root, {cov.ORIGIN: list(core.MODELS)}, lineage=lineage)
        ctx.contract_sha = lambda run: self.origin_contract
        return ctx


class SnapshotAndSiblingEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.world = SnapshotWorld(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_consistent_world_passes(self):
        ctx = self.world.context()
        entry = cov._snapshot_entry(ctx)
        self.assertEqual(entry["status"], core.PASS, entry["problems"])
        self.assertEqual(entry["check_count"], len(core.MODELS))
        self.assertEqual(entry["computed"]["phase2_protected_inventory_sha256"], "q" * 64)
        self.assertEqual(entry["computed"]["snapshots"][RUN_003]["paths_differing_from_phase2_protected"], 0)
        entry = cov._sibling_entry(ctx)
        self.assertEqual(entry["status"], core.PASS, entry["problems"])
        self.assertEqual(entry["computed"]["frozen_by_003_inventory_sha256"], self.world.inventory_002_sha)
        self.assertEqual(entry["computed"]["frozen_by_003_files"], 1)
        json.dumps(core.json_stable(entry))

    def test_snapshot_file_sha_differing_from_the_protected_inventory_fails(self):
        """Regression: same 1,506 paths, one different raw sha in the 003 snapshot."""
        path = list(self.world.files_001)[0]
        self.world.lineages[RUN_003]["predecessor_snapshot"]["files"][path]["raw_sha256"] = "z" * 64
        entry = cov._snapshot_entry(self.world.context())
        self.assertEqual(entry["status"], core.FAIL)
        self.assertTrue(any("%s snapshot differs from the phase-2 protected" % RUN_003 in p and path in p
                            for p in entry["problems"]), entry["problems"])
        self.assertEqual(entry["computed"]["snapshots"][RUN_003]["paths_differing_from_phase2_protected"], 1)

    def test_snapshot_membership_difference_fails(self):
        self.world.lineages[RUN_002]["predecessor_snapshot"]["files"].pop(list(self.world.files_001)[1])
        entry = cov._snapshot_entry(self.world.context())
        self.assertEqual(entry["status"], core.FAIL)
        self.assertTrue(any("snapshot membership differs" in p for p in entry["problems"]))

    def test_snapshot_of_another_run_or_contract_fails(self):
        self.world.lineages[RUN_004]["predecessor"]["contract_sha256"] = "x" * 64
        entry = cov._snapshot_entry(self.world.context())
        self.assertTrue(any("binds another" in p for p in entry["problems"]))

    def test_missing_protected_origin_inventory_fails(self):
        self.world.protected[cov.ORIGIN]["files"] = OrderedDict()
        entry = cov._snapshot_entry(self.world.context())
        self.assertEqual(entry["status"], core.FAIL)
        self.assertTrue(any("protects no" in p for p in entry["problems"]))

    def test_sibling_inventory_sha_frozen_by_003_differing_fails(self):
        """Regression: the 003-frozen 002 inventory was never compared."""
        self.world.lineages[RUN_003]["sibling_successors"][cov.SUCCESSOR_002]["protected_inventory"]["inventory_sha256"] = "y" * 64
        entry = cov._sibling_entry(self.world.context())
        self.assertEqual(entry["status"], core.FAIL)
        self.assertTrue(any("inventory shas disagree" in p for p in entry["problems"]), entry["problems"])

    def test_sibling_file_sha_frozen_by_003_differing_fails(self):
        path = list(self.world.files_002)[0]
        self.world.lineages[RUN_003]["sibling_successors"][cov.SUCCESSOR_002]["protected_inventory"]["files"][path]["size"] = 31
        entry = cov._sibling_entry(self.world.context())
        self.assertEqual(entry["status"], core.FAIL)
        self.assertTrue(any("frozen by 003 differs" in p and path in p for p in entry["problems"]), entry["problems"])

    def test_sibling_file_count_or_custody_mismatch_fails(self):
        self.world.custody["sibling_inventories_sha256"][cov.SUCCESSOR_002] = "w" * 64
        entry = cov._sibling_entry(self.world.context())
        self.assertTrue(any("inventory shas disagree" in p for p in entry["problems"]))
        self.world = SnapshotWorld(self.tmp.name)
        self.world.lineages[RUN_004]["sibling_successors"][cov.SUCCESSOR_002]["protected_inventory"]["files"]["extra"] = \
            OrderedDict([("raw_sha256", "e" * 64), ("size", 1)])
        entry = cov._sibling_entry(self.world.context())
        self.assertTrue(any("file counts disagree" in p for p in entry["problems"]))

    def test_foreign_phase2_report_fails_both_entries(self):
        self.world.reports[core.MODELS[0]]["model_id"] = core.MODELS[1]
        ctx = self.world.context()
        for entry in (cov._snapshot_entry(ctx), cov._sibling_entry(ctx)):
            self.assertEqual(entry["status"], core.FAIL)
            self.assertTrue(any("foreign report" in p for p in entry["problems"]))

    def test_inventory_differences(self):
        a = inventory(OrderedDict([("p", ("1" * 64, 1)), ("q", ("2" * 64, 2))]))
        b = inventory(OrderedDict([("p", ("1" * 64, 1)), ("q", ("3" * 64, 2)), ("r", ("4" * 64, 4))]))
        self.assertEqual(cov.inventory_differences(a, b), ["q", "r"])
        self.assertEqual(cov.inventory_differences(a, core.json_stable(a)), [])
        self.assertEqual(cov.inventory_differences(None, {}), [])


class PilotAndParentReportTest(unittest.TestCase):
    def pilot(self, **overrides):
        report = OrderedDict([
            ("schema_version", cov.PILOT_SCHEMA), ("verifier_version", cov.PILOT_VERIFIER),
            ("run_id", core.PILOT), ("contract_sha256", "c" * 64), ("status", core.PASS),
            ("counts", OrderedDict([("PASS", 2), ("FAIL", 0), ("UNRESOLVED", 0)])),
            ("repair_scope", OrderedDict([("status", core.PASS), ("expected_loop_count", 33),
                                          ("observed_loop_count", 33), ("pass_loop_count", 33),
                                          ("unresolved_loop_count", 0), ("fail_loop_count", 0)])),
            ("checks", [check("a"), check("b")])])
        report.update(overrides)
        return report

    def test_consistent_pilot_report(self):
        self.assertEqual(cov.pilot_report_problems(self.pilot(), 33, "c" * 64), [])

    def test_pilot_fail_count_fails(self):
        counts = OrderedDict([("PASS", 2), ("FAIL", 1), ("UNRESOLVED", 0)])
        self.assertTrue(cov.pilot_report_problems(self.pilot(counts=counts), 33, "c" * 64))

    def test_pilot_contract_mismatch_fails(self):
        self.assertTrue(any("contract" in p for p in cov.pilot_report_problems(self.pilot(), 33, "d" * 64)))

    def test_pilot_repair_scope_short_fails(self):
        self.assertTrue(any("repair scope" in p for p in cov.pilot_report_problems(self.pilot(), 32, "c" * 64)))

    def test_pilot_check_count_mismatch_fails(self):
        self.assertTrue(cov.pilot_report_problems(self.pilot(checks=[check("a")]), 33, "c" * 64))

    def parent(self, **overrides):
        report = OrderedDict([
            ("schema_version", cov.PARENT_SCHEMA), ("status", core.PASS), ("scope", cov.PARENT_SCOPE),
            ("source_run", core.PARENT), ("lineage_sha256", "l" * 64), ("base_cells", 1584),
            ("contract_sha256", "c" * 64), ("historical_repair_adopted", False),
            ("base_checks", [check("contract_present")])])
        report.update(overrides)
        return report

    def test_consistent_parent_report(self):
        self.assertEqual(cov.parent_report_problems(self.parent(), "l" * 64, "c" * 64, 1584), [])

    def test_parent_lineage_mismatch_fails(self):
        self.assertTrue(any("lineage_sha256" in p for p in cov.parent_report_problems(self.parent(), "m" * 64, "c" * 64, 1584)))

    def test_parent_base_cells_mismatch_fails(self):
        self.assertTrue(cov.parent_report_problems(self.parent(), "l" * 64, "c" * 64, 1583))

    def test_parent_failing_base_check_fails(self):
        report = self.parent(base_checks=[check("contract_present", core.FAIL)])
        self.assertTrue(cov.parent_report_problems(report, "l" * 64, "c" * 64, 1584))


class ScopesAndLoopsTest(unittest.TestCase):
    def test_scopes_distinct(self):
        rows = cov.scopes_table("pilot / schema", "BASE", "SUCC", "PHASE2")
        self.assertEqual(cov.scopes_problems(rows), [])
        self.assertIn(core.SCOPE, [r["scope"] for r in rows])
        self.assertIn(core.RETROSPECTIVE_SCOPE, [r["scope"] for r in rows])
        for row in rows:
            self.assertTrue(row["proves"] and row["does_not_prove"])

    def test_duplicate_scope_fails(self):
        rows = cov.scopes_table(core.SCOPE, "BASE", "SUCC", "PHASE2")
        self.assertTrue(cov.scopes_problems(rows))

    def loops(self):
        def loop(model, variant, owner, kind, terminal=True):
            return OrderedDict([("block", "full_ext"), ("model", model), ("variant", variant), ("owner", owner),
                                ("terminal", terminal), ("iteration", 2), ("kind", kind), ("samples", 3),
                                ("status_counts", OrderedDict([("stopped_clean", 3)]))])
        return [loop("m1", "test_feedback", cov.ORIGIN, "native"),
                loop("m1", "static_feedback", core.OWNERS[1], "continued"),
                loop("m1", "combined_feedback", core.OWNERS[1], "continued", terminal=False),
                loop("m2", "static_feedback", core.OWNERS[3], "native")]

    def test_owned_loops(self):
        owned = cov.owned_loops(self.loops(), core.OWNERS[1])
        self.assertEqual([(l["model"], l["variant"], l["terminal"]) for l in owned],
                         [("m1", "static_feedback", True), ("m1", "combined_feedback", False)])
        self.assertEqual(owned[0]["iterations"], 2)

    def test_adopted_vs_new(self):
        contracts = OrderedDict([(core.OWNERS[1], ["m1"]), (core.OWNERS[2], []), (core.OWNERS[3], ["m2"])])
        result = cov.adopted_vs_new(self.loops(), contracts)
        self.assertEqual(result[core.OWNERS[1]]["adopted_from_" + cov.ORIGIN], ["m1/test_feedback"])
        self.assertEqual(result[core.OWNERS[1]]["continued_from_" + cov.ORIGIN],
                         ["m1/static_feedback", "m1/combined_feedback"])
        self.assertEqual(result[core.OWNERS[3]]["fresh"], ["m2/static_feedback"])

    def test_targets_by_model_and_owner(self):
        table = FakeTable([Target("m1", core.PARENT), Target("m1", cov.ORIGIN + "__test_feedback__iter1"),
                           Target("m1", core.OWNERS[1] + "__static_feedback__iter2"), Target("m2", core.PARENT)])
        self.assertEqual(cov.targets_by_model(table),
                         OrderedDict([("m1", sorted([core.PARENT, cov.ORIGIN + "__test_feedback__iter1",
                                                     core.OWNERS[1] + "__static_feedback__iter2"])),
                                      ("m2", [core.PARENT])]))
        self.assertEqual(cov.targets_of_owner(table, cov.ORIGIN),
                         OrderedDict([("m1", [cov.ORIGIN + "__test_feedback__iter1"])]))

    def test_relative_paths_are_repo_relative(self):
        self.assertEqual(cov.successor_report_relative(RUN_004, "m"),
                         core.RUN_REGISTRY[RUN_004]["verification"] + "/m" + cov.SUCCESSOR_REPORT_SUFFIX)
        self.assertEqual(cov.phase2_report_relative("m"), core.PHASE2_VERIFICATION_REL + "/m" + cov.PHASE2_REPORT_SUFFIX)
        self.assertTrue(cov.wave_state_relative(cov.ORIGIN, "m", "v").startswith(core.INTERMEDIATE_REL + "/"))


@unittest.skipUnless(REAL, "real repository (STUDY_CLOSURE_REAL=1)")
class RealRepositoryTest(unittest.TestCase):
    """Read-only against the real repository: the runs section (seconds) and
    the census (seconds) feed the cache as the closure does, then the cheap
    evidence checks and both coverage maps; plus the 004 re-verification of
    ONE model (minutes)."""

    @classmethod
    def setUpClass(cls):
        from thesis.recovery_successor_004 import census
        from thesis.study_closure import runs

        cls.ctx = core.load_context(core.REPO_ROOT, options={"reverify": False})
        runs.collect_runs(cls.ctx)
        cls.ctx.cache["census"] = census.census(cls.ctx.root, list(core.MODELS))

    def test_cheap_evidence_checks_pass(self):
        ok, detail = cov.pilot_report_facts(self.ctx)
        self.assertTrue(ok, detail)
        ok, detail = cov.parent_report_facts(self.ctx)
        self.assertTrue(ok, detail)
        for run in cov.REPORTED_RUNS:
            ok, detail = cov.successor_reports_facts(self.ctx, run)
            self.assertTrue(ok, detail)

    def test_coverage_maps_pass_without_reverification(self):
        for builder in (cov.recovery_001_coverage, cov.recovery_002_coverage):
            ok, document = cov.coverage_map_facts(self.ctx, builder)
            self.assertTrue(ok, document["problems"])
            json.dumps(core.json_stable(document))

    def test_reverify_one_004_model(self):
        model = self.ctx.frozen_contract(RUN_004)["model_ids"][0]
        record = cov.reverify_model(self.ctx, RUN_004, model, deep=True)
        self.assertEqual(record["retrospective_status"], cov.RETROSPECTIVE_PASS, record["problems"])
        self.assertTrue(record["persisted_match"])
        self.assertEqual(record["authority_variant"], cov.AUTHORITY_NONE)
        self.assertEqual(record["substituted"]["ok"], True)
        self.assertIsNone(record["open_work_error"])


if __name__ == "__main__":
    unittest.main()
