"""Tests of the frozen methodology contract and its derived markdown.

    python3 -B -m unittest -v thesis.study_analysis.test_methodology
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from thesis.study_analysis import core, methodology_doc

REQUIRED_METRIC_FIELDS = ("id", "name", "population", "unit", "meaning", "numerator", "denominator",
                          "applicability", "missingness", "aggregation", "limits")


class MethodologyContractTest(unittest.TestCase):
    def setUp(self):
        self.methodology = core.load_methodology()

    def test_every_metric_defines_every_required_field(self):
        for metric in self.methodology["metrics"]:
            missing = [f for f in REQUIRED_METRIC_FIELDS if not str(metric.get(f, "")).strip()]
            self.assertEqual(missing, [], metric["id"])

    def test_metric_ids_unique_and_grouped(self):
        ids = core.metric_ids(self.methodology)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i[0] in "QESDFRCG" and i[1:].isdigit() for i in ids), ids)

    def test_populations_are_separated_and_selection_rules_present(self):
        populations = self.methodology["populations"]
        for name in ("BASE", "STEP", "FINAL", "GENERATED", "REPAIR_CANDIDATES", "ENH_PAIRS"):
            self.assertIn(name, populations)
        rules = " ".join(populations["rules"])
        self.assertIn("never counted as successful repairs", rules)
        self.assertIn("no held-out", rules)
        self.assertIn("identical base-cell cohort", rules)

    def test_vocabularies_match_core(self):
        vocab = self.methodology["state_vocabularies"]
        self.assertEqual(tuple(vocab["tool_states"]), core.TOOL_STATES)
        self.assertEqual(tuple(vocab["analysis_gap_states"]), core.GAP_STATES)
        self.assertEqual(tuple(vocab["enhanced_gated"]), core.ENHANCED_GATED)
        self.assertEqual(tuple(vocab["correctness_verdicts"]), core.CORRECTNESS_VERDICTS)
        self.assertEqual(set(vocab["enhanced_statuses"]), set(core.ENHANCED_STATUSES))
        self.assertEqual(tuple(vocab["terminal_statuses"]), core.TERMINAL_STATUSES)
        self.assertEqual(tuple(vocab["non_model_terminal_statuses"]), core.NON_MODEL_TERMINAL)

    def test_statistics_protocol(self):
        stats = core.statistics_settings(self.methodology)
        boot = stats["bootstrap"]
        self.assertEqual(boot["stratified_by"].split()[0], "block")
        self.assertGreaterEqual(boot["replicates_primary"], boot["replicates_descriptive"])
        self.assertIsInstance(boot["seed"], int)
        self.assertIn("Holm", stats["tests"]["multiplicity"])
        self.assertIn("no model ranking", stats["not_done"])

    def test_official_research_questions_are_flagged_missing(self):
        self.assertTrue(self.methodology["study_goals"]["official_research_questions"].startswith("MISSING"))

    def test_loader_refuses_unfrozen_or_foreign_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / core.METHODOLOGY_REL
            target.parent.mkdir(parents=True)
            for mutate in (lambda d: d.update(status="DRAFT"), lambda d: d.update(methodology_id="other"),
                           lambda d: d["metrics"].append(copy.deepcopy(d["metrics"][0]))):
                document = copy.deepcopy(self.methodology)
                mutate(document)
                target.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(core.AnalysisRefused):
                    core.load_methodology(root)


class AddendumTest(unittest.TestCase):
    def setUp(self):
        self.methodology = core.load_methodology()
        self.addendum = core.load_addendum(methodology=self.methodology)

    def test_addendum_is_bound_to_the_frozen_methodology_and_post_freeze(self):
        self.assertEqual(self.addendum["status"], core.ADDENDUM_STATUS)
        self.assertIn("NOT modified", self.addendum["amends"]["rule"])
        ids = core.addendum_metric_ids(self.addendum)
        self.assertTrue(ids and all(i.startswith("X") for i in ids))
        self.assertFalse(set(ids) & set(core.metric_ids(self.methodology)))
        self.assertEqual(core.all_metric_ids(self.methodology, self.addendum),
                         core.metric_ids(self.methodology) + ids)

    def test_every_addendum_metric_is_complete_and_descriptive(self):
        for metric in self.addendum["metrics"]:
            missing = [f for f in REQUIRED_METRIC_FIELDS if not str(metric.get(f, "")).strip()]
            self.assertEqual(missing, [], metric["id"])
            self.assertIn("post-freeze", metric["limits"])

    def test_addendum_refuses_another_methodology_or_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / core.ADDENDUM_REL).parent.mkdir(parents=True)
            for mutate in (lambda d: d["amends"].update(methodology_canonical_sha256="0" * 64),
                           lambda d: d.update(status="FROZEN_BEFORE_AGGREGATION"),
                           lambda d: d["metrics"].append(dict(d["metrics"][0], id="Q06"))):
                document = copy.deepcopy(self.addendum)
                mutate(document)
                (root / core.ADDENDUM_REL).write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(core.AnalysisRefused):
                    core.load_addendum(root, methodology=self.methodology)

    def test_committed_addendum_markdown_equals_the_rendering(self):
        path = core.REPO_ROOT / methodology_doc.ADDENDUM_DOC_REL
        self.assertTrue(path.is_file(), "METHODOLOGY_ADDENDUM.md missing")
        self.assertEqual(path.read_bytes().replace(b"\r\n", b"\n"), methodology_doc.render_addendum_bytes())


class MarkdownTest(unittest.TestCase):
    def test_committed_markdown_equals_the_rendering(self):
        path = core.REPO_ROOT / methodology_doc.DOC_REL
        self.assertTrue(path.is_file(), "METHODOLOGY.md missing")
        self.assertEqual(path.read_bytes().replace(b"\r\n", b"\n"), methodology_doc.render_bytes(),
                         "METHODOLOGY.md is stale - re-render it from methodology.json")

    def test_rendering_contains_every_metric_and_rule(self):
        methodology = core.load_methodology()
        text = methodology_doc.render(methodology)
        for metric in methodology["metrics"]:
            self.assertIn("### %s `%s`" % (metric["id"], metric["name"]), text)
        self.assertIn("Official research questions", text)
        self.assertIn("Holm", text)


if __name__ == "__main__":
    unittest.main()
