"""Tests of the closure document assembly (report.py) on synthetic sections:
self-hash, flag logic (the closure never sets the acceptance flags itself),
ordering and the markdown rendering.

    python3 -B -m unittest -v thesis.study_closure.test_report
"""
from __future__ import annotations

import json
import unittest
from collections import OrderedDict
from pathlib import Path

from thesis.evaluation.recovery_lineage import RecoveryRefused
from thesis.study_closure import core, report

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeContext:
    def __init__(self, cache=None, options=None):
        self.root = REPO_ROOT
        self.cache = OrderedDict(cache or {})
        self.options = OrderedDict(options or {})
        self.started_utc = "2026-10-17T00:00:00Z"
        self.timings = OrderedDict([("x", 1.5)])


def section(name, passing=True, data=None):
    s = core.Section(name)
    s.add("one", True, {"n": 1})
    s.add("two", passing, "detail")
    if data:
        s.data.update(data)
    return s


def all_sections(persisted=True, failing=None):
    failing = failing or ()
    return [
        section("identity", "identity" not in failing),
        section("runs", "runs" not in failing),
        section("tree", "tree" not in failing, {"phase2_inventory": OrderedDict([
            ("inventory_sha256", "f" * 64), ("file_count", 3), ("total_bytes", 10),
            ("files", OrderedDict([("a", {"sha256": "0" * 64, "size": 10})]))])}),
        section("history", "history" not in failing),
        section("population", "population" not in failing, {"composite": OrderedDict([
            ("relative", core.COMPOSITE_REL), ("persisted", persisted), ("raw_sha256", "a" * 64),
            ("composite_sha256", "b" * 64)])}),
        section("phase2", "phase2" not in failing, {"incidents": {"archived_torn_tails": 0}}),
        section("coverage", "coverage" not in failing, {"scopes": OrderedDict([("x", "proves y")]),
                                                        "runs_evidence": OrderedDict([("pilot_002", "report")])}),
        section("acceptance", "acceptance" not in failing),
        section("disclosures", "disclosures" not in failing),
    ]


class ReportTest(unittest.TestCase):
    def test_document_reproduces_its_hash_and_orders_sections(self):
        ctx = FakeContext(cache={"publication_gate": {"publication_allowed": False,
                                                      "result_acceptance_status": None,
                                                      "reasons": ["result acceptance pending (x)"]}})
        sections = list(reversed(all_sections()))
        document = report.build_document(sections, ctx, formal=False)
        self.assertTrue(report.verify_document(document))
        self.assertEqual([s["section"] for s in document["sections"]], list(report.SECTION_ORDER))
        self.assertEqual(document["status"], core.PASS)
        self.assertFalse(document["formal"])
        # json round trip keeps the hash
        again = json.loads(json.dumps(document), object_pairs_hook=OrderedDict)
        self.assertTrue(report.verify_document(again))
        again["status"] = core.FAIL
        with self.assertRaises(RecoveryRefused):
            report.verify_document(again)

    def test_flags_never_claim_acceptance_without_an_accepted_gate(self):
        ctx = FakeContext(cache={"publication_gate": {"publication_allowed": False,
                                                      "result_acceptance_status": "PENDING",
                                                      "reasons": ["result acceptance status is PENDING"]}})
        flags = report.flags(all_sections(), ctx, formal=True)
        self.assertEqual(flags["MEASUREMENTS_COMPLETE"], "YES")
        self.assertEqual(flags["COMPOSITE_VERIFICATION_COMPLETE"], "YES")
        self.assertEqual(flags["FORMAL_GLOBAL_VERIFICATION_COMPLETE"], "YES")
        self.assertEqual(flags["PILOT_ACCEPTANCE_COMPLETE"], "NO")
        self.assertEqual(flags["PUBLICATION_READY"], "NO")
        self.assertEqual(flags["READY_FOR_SCIENTIFIC_ANALYSIS"], "YES")
        # an accepted gate (author decision recorded elsewhere) flips the two author flags
        ctx.cache["publication_gate"] = {"publication_allowed": True, "result_acceptance_status": "ACCEPTED",
                                         "reasons": []}
        flags = report.flags(all_sections(), ctx, formal=True)
        self.assertEqual(flags["PILOT_ACCEPTANCE_COMPLETE"], "YES")
        self.assertEqual(flags["PUBLICATION_READY"], "YES")
        # ... but never in a dry run
        flags = report.flags(all_sections(), ctx, formal=False)
        self.assertEqual(flags["FORMAL_GLOBAL_VERIFICATION_COMPLETE"], "NO")
        self.assertEqual(flags["PUBLICATION_READY"], "NO")

    def test_flags_follow_failures_and_persistence(self):
        ctx = FakeContext()
        flags = report.flags(all_sections(persisted=False), ctx, formal=True)
        self.assertEqual(flags["COMPOSITE_VERIFICATION_COMPLETE"], "NO")
        self.assertEqual(flags["READY_FOR_SCIENTIFIC_ANALYSIS"], "NO")
        flags = report.flags(all_sections(failing=("phase2",)), ctx, formal=True)
        self.assertEqual(flags["MEASUREMENTS_COMPLETE"], "NO")
        self.assertEqual(flags["FORMAL_GLOBAL_VERIFICATION_COMPLETE"], "NO")
        self.assertEqual(flags["READY_FOR_SCIENTIFIC_ANALYSIS"], "NO")
        document = report.build_document(all_sections(failing=("coverage",)), ctx, formal=True)
        self.assertEqual(document["status"], core.FAIL)
        self.assertIn("coverage:two", document["sections"][6]["failing"])

    def test_markdown_renders_every_check_and_the_hash(self):
        ctx = FakeContext(cache={"publication_gate": {"publication_allowed": False,
                                                      "result_acceptance_status": None,
                                                      "reasons": ["result acceptance pending (x)"],
                                                      "label_required": "pilot label"},
                                 "run_bindings": OrderedDict([(core.PILOT, {"contract_sha256": "1" * 64,
                                                                            "authorization_sha256": "2" * 64,
                                                                            "manifest_complete": True,
                                                                            "git_commit": "abc",
                                                                            "model_ids": list(core.MODELS)})]),
                                 "census_summary": {"total_repair_loops_done": "66/66",
                                                    "blocks": {"pilot": {"owners": {"pilot_002": 33}},
                                                               "full_ext": {"owners": {"x": 33}}}}})
        document = report.build_document(all_sections(), ctx, formal=False)
        text = report.render_markdown(document)
        self.assertIn(document["closure_sha256"], text)
        for section in document["sections"]:
            for check in section["check_list"]:
                self.assertIn(check["check"], text)
        self.assertIn("66/66", text)
        self.assertIn("pilot label", text)
        self.assertIn("`PUBLICATION_READY = NO`", text)
        self.assertEqual(document["summary"]["runs"][core.PILOT]["models"], len(core.MODELS))


if __name__ == "__main__":
    unittest.main()
