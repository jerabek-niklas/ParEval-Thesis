"""Tests of the acceptance section.

The REAL publication policy, post-run verification report and frozen pilot
contract are read (read-only; nothing under thesis/ is written, the only
files created live in a temp dir). The tests prove: the PENDING template
causes exactly the two pending reasons at the native gate, a forged or
defective acceptance is refused, a correct ACCEPTED fixture reaches the
gate (publication_allowed), and no closure function ever yields a document
with status ACCEPTED unless given one.

    python3 -B -m unittest -v thesis.study_closure.test_acceptance
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import types
import unittest
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation import pilot_freeze as pf
from thesis.study_closure import acceptance as ac
from thesis.study_closure import core

REPO_ROOT = core.REPO_ROOT
FIXTURE_DATE = "2026-10-17"
FIXTURE_AUTHOR = "fixture"


def _accepted_dicts(node, found):
    """Every dict in the tree whose `status` is ACCEPTED."""
    if isinstance(node, dict):
        if node.get("status") == "ACCEPTED":
            found.append(node)
        for value in node.values():
            _accepted_dicts(value, found)
    elif isinstance(node, list):
        for value in node:
            _accepted_dicts(value, found)
    return found


class FakeContext:
    """A context over a root without any artifact: every input load fails."""

    def __init__(self, root):
        self.root = Path(root)
        self.cache = OrderedDict()
        self.options = OrderedDict()
        self.timings = OrderedDict()

    def frozen_contract(self, run_id):
        raise core.ClosureRefused("no frozen contract for " + run_id)

    def log(self, message):
        pass

    def timed(self, key, function, *args, **kwargs):
        return function(*args, **kwargs)


class RealInputsTest(unittest.TestCase):
    """Read-only against the real repository (policy, report, contract)."""

    @classmethod
    def setUpClass(cls):
        cls.inputs = ac.load_inputs(REPO_ROOT)
        cls.template = ac.acceptance_template(cls.inputs["report"], cls.inputs["contract"], cls.inputs["policy"])
        cls.acceptance_rel = REPO_ROOT / core.RESULT_ACCEPTANCE_REL
        cls.acceptance_existed = cls.acceptance_rel.is_file()

    def accepted(self, **overrides):
        candidate = OrderedDict(self.template)
        candidate["status"] = "ACCEPTED"
        candidate["decided_by"] = FIXTURE_AUTHOR
        candidate["decided_on"] = FIXTURE_DATE
        candidate.update(overrides)
        return candidate

    def validate(self, candidate):
        return ac.validate_acceptance(REPO_ROOT, candidate, self.inputs)

    def tearDown(self):
        # nothing in the repository may change
        self.assertEqual(self.acceptance_rel.is_file(), self.acceptance_existed)

    def test_template_is_pending_with_only_the_pending_reasons(self):
        self.assertEqual(self.template["status"], ac.PENDING)
        self.assertIsNone(self.template["decided_by"])
        self.assertIsNone(self.template["decided_on"])
        self.assertEqual(self.template["run_id"], core.PILOT)
        self.assertEqual(self.template["post_run_verification_sha256"],
                         pf.post_run_report_digest(self.inputs["report"]))
        self.assertEqual(self.template["frozen_contract_sha256"], self.inputs["contract"]["contract_sha256"])
        gate = pf.publication_decision(self.inputs["policy"], self.inputs["report"], self.template, REPO_ROOT,
                                       self.inputs["contract"])
        self.assertFalse(gate["publication_allowed"])
        self.assertEqual(ac.template_problems(gate["reasons"]), [], gate["reasons"])
        self.assertEqual(len(gate["reasons"]), 2)

    def test_forged_accepted_without_decided_by_is_invalid(self):
        result = self.validate(self.accepted(decided_by=None))
        self.assertFalse(result["valid_for_gate"])
        self.assertFalse(result["publication_allowed"])
        self.assertTrue(any("decided_by" in p for p in result["problems"]), result["problems"])
        self.assertTrue(any("decided_by" in r for r in result["reasons"]), result["reasons"])

    def test_wrong_digest_reasons_mention_the_digest(self):
        result = self.validate(self.accepted(post_run_verification_sha256="0" * 64))
        self.assertFalse(result["valid_for_gate"])
        self.assertFalse(result["publication_allowed"])
        self.assertTrue(any("post-run verification report" in r for r in result["reasons"]), result["reasons"])
        self.assertTrue(any("post_run_verification_sha256" in p for p in result["problems"]), result["problems"])

    def test_wrong_contract_and_run_are_refused(self):
        result = self.validate(self.accepted(frozen_contract_sha256="1" * 64, run_id="pilot_001"))
        self.assertFalse(result["publication_allowed"])
        self.assertTrue(any("contract" in r for r in result["reasons"]), result["reasons"])
        self.assertTrue(any("run" in r for r in result["reasons"]), result["reasons"])
        self.assertTrue(any(p.startswith("run_id") for p in result["problems"]), result["problems"])

    def test_bad_date_and_unknown_status_are_invalid(self):
        result = self.validate(self.accepted(decided_on="17.10.2026"))
        self.assertFalse(result["valid_for_gate"])
        self.assertTrue(any("ISO date" in p for p in result["problems"]), result["problems"])
        result = self.validate(self.accepted(status="MAYBE"))
        self.assertFalse(result["valid_for_gate"])
        self.assertFalse(result["publication_allowed"])
        self.assertTrue(any("status" in p for p in result["problems"]), result["problems"])

    def test_non_object_is_invalid(self):
        result = self.validate(["not", "an", "object"])
        self.assertFalse(result["valid_for_gate"])
        self.assertFalse(result["publication_allowed"])

    def test_correct_accepted_fixture_reaches_the_gate(self):
        """The author can reach publication_allowed with a correct ACCEPTED
        file - proven in memory, nothing written."""
        result = self.validate(self.accepted())
        self.assertEqual(result["problems"], [])
        self.assertTrue(result["valid_for_gate"])
        self.assertEqual(result["reasons"], [])
        self.assertTrue(result["publication_allowed"])
        self.assertEqual(result["label_required"], self.inputs["policy"]["pilot_label"])

    def test_rejected_fixture_is_valid_but_not_allowed(self):
        result = self.validate(self.accepted(status="REJECTED"))
        self.assertTrue(result["valid_for_gate"], result["problems"])
        self.assertFalse(result["publication_allowed"])
        self.assertTrue(all(ac.acceptance_related(r) for r in result["reasons"]), result["reasons"])

    def live_gate(self, acceptance=None, exists=None):
        """The native gate over the real inputs with an (in-memory)
        acceptance; returns (gate, inputs) where inputs reflect the
        candidate as if it were the persisted artifact."""
        inputs = OrderedDict(self.inputs)
        if acceptance is not None:
            inputs["acceptance"] = acceptance
            inputs["acceptance_exists"] = True if exists is None else exists
        gate = pf.publication_decision(inputs["policy"], inputs["report"], inputs["acceptance"], REPO_ROOT,
                                       inputs["contract"])
        return gate, inputs

    def test_half_filled_decision_record_fails_the_gate_check(self):
        """A record whose status claims a decision (ACCEPTED or REJECTED)
        but lacks decided_by or decided_on is defective, never 'pending':
        the gate check FAILs and the readiness keeps the decision required."""
        for status, missing in (("ACCEPTED", "decided_by"), ("ACCEPTED", "decided_on"), ("REJECTED", "decided_by")):
            candidate = self.accepted(status=status)
            candidate[missing] = None
            gate, _ = self.live_gate(candidate)
            self.assertEqual(gate["result_acceptance_status"], status)
            self.assertTrue(any(missing in r for r in gate["reasons"]), gate["reasons"])
            ok, detail = ac.gate_check(gate, True)
            self.assertFalse(ok, detail)
            self.assertTrue(any("defective acceptance record" in p and missing in p for p in detail["problems"]),
                            detail["problems"])
            self.assertEqual(detail["result_acceptance_status"], status)
            state = ac.decision_state(gate, True)
            self.assertEqual(state["status"], ac.READINESS_STATUS)
            self.assertIsNone(state["recorded_status"])
            self.assertTrue(state["author_decision_required"])
        # the PENDING template with both decision fields empty is pending, not defective
        gate, _ = self.live_gate(self.template)
        self.assertEqual(gate["result_acceptance_status"], ac.PENDING)
        self.assertTrue(ac.gate_check(gate, True)[0])

    def test_readiness_refuses_without_the_gate_or_a_pending_template(self):
        ctx = types.SimpleNamespace(root=REPO_ROOT)
        with self.assertRaisesRegex(core.ClosureRefused, "gate unavailable"):
            ac.readiness_document(ctx, None, self.template, self.inputs)
        with self.assertRaisesRegex(core.ClosureRefused, "template"):
            ac.readiness_document(ctx, OrderedDict(), self.accepted(), self.inputs)

    def test_readiness_reflects_a_recorded_decision(self):
        """With a valid ACCEPTED/REJECTED record (in memory, nothing
        written) the readiness says DECISION_RECORDED with the recorded
        status under recorded_status - never as a `status` field; a
        defective record keeps the decision required."""
        ctx = types.SimpleNamespace(root=REPO_ROOT)
        for status, allowed in (("ACCEPTED", True), ("REJECTED", False)):
            gate, inputs = self.live_gate(self.accepted(status=status))
            readiness = ac.readiness_document(ctx, gate, self.template, inputs)
            self.assertEqual(readiness["status"], ac.DECISION_RECORDED)
            self.assertEqual(readiness["recorded_status"], status)
            self.assertFalse(readiness["author_decision_required"])
            self.assertEqual(readiness["gate_now"]["publication_allowed"], allowed)
            self.assertEqual(readiness["gate_now"]["result_acceptance_status"], status)
            self.assertEqual(_accepted_dicts(readiness, []), [])
            self.assertEqual(core.self_hash(readiness, "readiness_sha256"), readiness["readiness_sha256"])
        # the same ACCEPTED record not persisted on disk is no decision
        gate, inputs = self.live_gate(self.accepted(), exists=False)
        readiness = ac.readiness_document(ctx, gate, self.template, inputs)
        self.assertEqual(readiness["status"], ac.READINESS_STATUS)
        self.assertTrue(readiness["author_decision_required"])
        # a half-filled record is defective: decision still required
        gate, inputs = self.live_gate(self.accepted(decided_on=None))
        readiness = ac.readiness_document(ctx, gate, self.template, inputs)
        self.assertEqual(readiness["status"], ac.READINESS_STATUS)
        self.assertIsNone(readiness["recorded_status"])
        self.assertTrue(readiness["author_decision_required"])
        self.assertFalse(readiness["gate_now"]["publication_allowed"])

    def test_readiness_is_deterministic(self):
        ctx = types.SimpleNamespace(root=REPO_ROOT)
        gate, inputs = self.live_gate()
        first = ac.readiness_document(ctx, gate, self.template, inputs)
        second = ac.readiness_document(ctx, gate, self.template, inputs)
        self.assertEqual(first["readiness_sha256"], second["readiness_sha256"])
        self.assertEqual(json.dumps(first), json.dumps(second))

    def test_no_closure_function_yields_accepted(self):
        ctx = core.load_context(REPO_ROOT)
        gate = pf.publication_decision(self.inputs["policy"], self.inputs["report"], self.inputs["acceptance"],
                                       REPO_ROOT, self.inputs["contract"])
        readiness = ac.readiness_document(ctx, gate, self.template, self.inputs)
        self.assertIn(readiness["status"], (ac.READINESS_STATUS, ac.DECISION_RECORDED))
        if not self.inputs["acceptance_exists"]:
            self.assertEqual(readiness["status"], ac.READINESS_STATUS)
            self.assertTrue(readiness["author_decision_required"])
        self.assertEqual(_accepted_dicts(readiness, []), [])
        self.assertEqual(_accepted_dicts(self.template, []), [])
        self.assertEqual(core.self_hash(readiness, "readiness_sha256"), readiness["readiness_sha256"])
        self.assertTrue(readiness["template_gate"]["only_pending_reasons"])
        self.assertEqual(readiness["exact_values"]["post_run_verification_sha256"],
                         self.template["post_run_verification_sha256"])
        self.assertIn(ac.VALIDATE_COMMAND, json.dumps(readiness))

    def test_real_section_passes(self):
        ctx = core.load_context(REPO_ROOT)
        section = ac.collect(ctx)
        self.assertEqual(section.status, core.PASS, section.failing())
        self.assertEqual([c["check"].split(":")[1] for c in section.checks], list(ac.CHECK_IDS))
        self.assertEqual(ctx.cache["acceptance_template"]["status"], ac.PENDING)
        self.assertIn("publication_gate", ctx.cache)
        summary = section.data["summary"]
        self.assertEqual(summary["readiness_status"], ctx.cache["acceptance_readiness"]["status"])
        self.assertEqual(summary["author_decision_required"], ctx.cache["acceptance_readiness"]["author_decision_required"])
        if not self.inputs["acceptance_exists"]:
            self.assertEqual(ctx.cache["acceptance_readiness"]["status"], ac.READINESS_STATUS)
            self.assertTrue(summary["author_decision_required"])
            self.assertIsNone(summary["recorded_status"])
            self.assertFalse(summary["publication_allowed"])
            self.assertIsNone(summary["result_acceptance_status"])

    def test_cli_check_and_template_never_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            forged = Path(tmp) / "forged.json"
            forged.write_text(json.dumps(self.accepted(decided_by=None)), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ac.main(["--check", str(forged), "--root", str(REPO_ROOT)])
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(out.getvalue())["valid_for_gate"])
            good = Path(tmp) / "good.json"
            good.write_text(json.dumps(self.accepted()), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ac.main(["--check", str(good), "--root", str(REPO_ROOT)])
            self.assertEqual(code, 0)
            self.assertTrue(json.loads(out.getvalue())["publication_allowed"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ac.main(["--template", "--root", str(REPO_ROOT)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["status"], ac.PENDING)


class PureCheckTest(unittest.TestCase):

    def test_gate_problems_accepts_only_pending_reasons(self):
        self.assertEqual(ac.gate_problems({"reasons": ["result acceptance pending (no x artifact)"]}), [])
        self.assertEqual(ac.gate_problems({"reasons": ["result acceptance status is PENDING, not ACCEPTED",
                                                       "result acceptance lacks required field(s): decided_by"]}), [])
        self.assertEqual(ac.gate_problems({"reasons": []}), [])
        self.assertEqual(len(ac.gate_problems({"reasons": ["mandatory disclosure sources missing/unreadable/unsatisfied: x"]})), 1)
        self.assertEqual(len(ac.gate_problems({"reasons": ["result acceptance lacks required field(s): run_id, decided_by"]})), 1)
        self.assertEqual(len(ac.gate_problems({"reasons": ["result acceptance names another post-run verification report (a... vs this report b...)"]})), 1)

    def test_template_problems_demand_exactly_the_two_reasons(self):
        both = ["result acceptance status is PENDING, not ACCEPTED",
                "result acceptance lacks required field(s): decided_by, decided_on"]
        self.assertEqual(ac.template_problems(both), [])
        self.assertEqual(ac.template_problems(list(reversed(both))), [])
        self.assertTrue(ac.template_problems(both[:1]))
        self.assertTrue(ac.template_problems(both + ["the report was verified against contract a..., not the bound b..."]))
        self.assertTrue(ac.template_problems([]))

    def _fake_report(self):
        report = OrderedDict([("schema_version", ac.POST_RUN_SCHEMA), ("verifier_version", "v"),
                              ("run_id", core.PILOT), ("contract_sha256", "c" * 64), ("status", core.PASS),
                              ("counts", OrderedDict([("PASS", 3), ("FAIL", 0), ("UNRESOLVED", 0)]))])
        report["publication"] = OrderedDict([("post_run_verification_sha256", pf.post_run_report_digest(report))])
        return report

    def test_report_check(self):
        contract = {"contract_sha256": "c" * 64}
        ok, detail = ac.report_check(self._fake_report(), contract, "raw")
        self.assertTrue(ok, detail)
        self.assertEqual(detail["raw_sha256"], "raw")
        for mutate in (lambda r: r.update(status="FAIL"), lambda r: r["counts"].update(FAIL=1),
                       lambda r: r["counts"].pop("UNRESOLVED"), lambda r: r.update(run_id="pilot_001"),
                       lambda r: r.update(contract_sha256="d" * 64),
                       lambda r: r["publication"].update(post_run_verification_sha256="0" * 64),
                       lambda r: r.update(schema_version="other")):
            report = self._fake_report()
            mutate(report)
            ok, detail = ac.report_check(report, contract)
            self.assertFalse(ok, detail)
        # a changed body changes the digest the publication block must name
        report = self._fake_report()
        report["counts"]["PASS"] = 4
        self.assertFalse(ac.report_check(report, contract)[0])

    def test_policy_check_against_the_real_policy(self):
        policy = core.read_json(REPO_ROOT, core.PUBLICATION_POLICY_REL)
        bound = {"publication_policy": {"sha256": policy["publication_policy_sha256"]}}
        ok, detail = ac.policy_check(policy, bound)
        self.assertTrue(ok, detail)
        self.assertFalse(ac.policy_check(policy, {"publication_policy": {"sha256": "0" * 64}})[0])
        self.assertFalse(ac.policy_check(policy, {})[0])
        foreign = OrderedDict(policy)
        foreign["run_id"] = "pilot_001"
        self.assertFalse(ac.policy_check(foreign, bound)[0])

    def test_sources_check_against_the_real_policy(self):
        policy = core.read_json(REPO_ROOT, core.PUBLICATION_POLICY_REL)
        ok, detail = ac.sources_check(policy, REPO_ROOT)
        self.assertTrue(ok, detail)
        self.assertEqual(detail["sources"], len(policy["mandatory_disclosure_sources"]))
        with tempfile.TemporaryDirectory() as tmp:
            ok, detail = ac.sources_check(policy, tmp)
            self.assertFalse(ok)
            self.assertEqual(detail["satisfied"], 0)
        self.assertFalse(ac.sources_check({"mandatory_disclosure_sources": []}, REPO_ROOT)[0])

    def test_gate_check_detail(self):
        ok, detail = ac.gate_check({"publication_allowed": False, "result_acceptance_status": None,
                                    "reasons": ["result acceptance pending (no x artifact)"],
                                    "label_required": "label"}, False)
        self.assertTrue(ok)
        self.assertEqual(detail["problems"], [])
        ok, detail = ac.gate_check({"publication_allowed": False, "reasons": ["publication policy STALE: x"]}, False)
        self.assertFalse(ok)
        self.assertEqual(len(detail["problems"]), 1)

    def test_decided_record_without_decision_fields_is_defective(self):
        """ACCEPTED/REJECTED + 'lacks decided_by/decided_on' is a FAIL of the
        gate check; the same reason under PENDING (or no record) is pending."""
        lacks = "result acceptance lacks required field(s): decided_by"
        both = "result acceptance lacks required field(s): decided_by, decided_on"
        for status in ("ACCEPTED", "REJECTED"):
            reasons = [lacks] + (["result acceptance status is REJECTED, not ACCEPTED"] if status == "REJECTED" else [])
            ok, detail = ac.gate_check({"publication_allowed": False, "result_acceptance_status": status,
                                        "reasons": reasons}, True)
            self.assertFalse(ok, detail)
            self.assertEqual(len(detail["problems"]), 1)
            self.assertIn("defective acceptance record", detail["problems"][0])
            self.assertIn(status, detail["problems"][0])
            self.assertFalse(ac.acceptance_related(lacks, status))
            self.assertFalse(ac.acceptance_related(both, status))
        for status in (None, "PENDING"):
            self.assertTrue(ac.acceptance_related(lacks, status))
            self.assertTrue(ac.acceptance_related(both, status))
            ok, detail = ac.gate_check({"result_acceptance_status": status,
                                        "reasons": [both, "result acceptance status is %s, not ACCEPTED" % status]}, True)
            self.assertTrue(ok, detail)
        # a wrong digest is a problem whatever the status; a missing non-decision field never is pending
        for status in (None, "PENDING", "ACCEPTED"):
            self.assertEqual(len(ac.gate_problems({"result_acceptance_status": status, "reasons": [
                "result acceptance names another post-run verification report (a... vs this report b...)"]})), 1)
            self.assertEqual(len(ac.gate_problems({"result_acceptance_status": status, "reasons": [
                "result acceptance lacks required field(s): run_id, decided_by"]})), 1)

    def test_decision_state(self):
        pending = ac.decision_state({"result_acceptance_status": None,
                                     "reasons": ["result acceptance pending (no x artifact)"]}, False)
        self.assertEqual((pending["status"], pending["recorded_status"], pending["author_decision_required"]),
                         (ac.READINESS_STATUS, None, True))
        rejected = ac.decision_state({"result_acceptance_status": "REJECTED",
                                      "reasons": ["result acceptance status is REJECTED, not ACCEPTED"]}, True)
        self.assertEqual((rejected["status"], rejected["recorded_status"], rejected["author_decision_required"]),
                         (ac.DECISION_RECORDED, "REJECTED", False))
        accepted = ac.decision_state({"result_acceptance_status": "ACCEPTED", "reasons": [],
                                      "publication_allowed": True}, True)
        self.assertEqual((accepted["status"], accepted["recorded_status"]), (ac.DECISION_RECORDED, "ACCEPTED"))
        # an in-memory record is no decision; a defective or PENDING record neither
        self.assertEqual(ac.decision_state({"result_acceptance_status": "ACCEPTED", "reasons": []}, False)["status"],
                         ac.READINESS_STATUS)
        self.assertTrue(ac.decision_state({"result_acceptance_status": "ACCEPTED", "reasons": [
            "result acceptance lacks required field(s): decided_on"]}, True)["author_decision_required"])
        self.assertTrue(ac.decision_state({"result_acceptance_status": "ACCEPTED", "reasons": [
            "result acceptance names contract a..., the run's contract is b..."]}, True)["author_decision_required"])
        self.assertTrue(ac.decision_state({"result_acceptance_status": "PENDING", "reasons": [
            "result acceptance status is PENDING, not ACCEPTED"]}, True)["author_decision_required"])
        self.assertTrue(ac.decision_state(OrderedDict(), False)["author_decision_required"])

    def test_collect_fails_closed_without_artifacts(self):
        """A root without the policy/report/contract: every check FAILs
        with 'input unavailable', no exception escapes, nothing is cached."""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = FakeContext(tmp)
            section = ac.collect(ctx)
        self.assertEqual(section.status, core.FAIL)
        self.assertEqual([c["check"].split(":")[1] for c in section.checks], list(ac.CHECK_IDS))
        self.assertEqual(len(section.failing()), len(ac.CHECK_IDS))
        self.assertTrue(all(str(c["detail"]).startswith("input unavailable") for c in section.checks), section.checks)
        self.assertNotIn("publication_gate", ctx.cache)
        self.assertNotIn("acceptance_template", ctx.cache)


if __name__ == "__main__":
    unittest.main()
