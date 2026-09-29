"""Synthetic historical binding and narrow source-difference tests."""
import copy
import hashlib
import json
import unittest
from pathlib import Path

from thesis.evaluation import recovery_historical_source as history
from thesis.evaluation import condition_hashing as ch
from thesis.evaluation.recovery_lineage import RecoveryRefused


class HistoricalSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = b"unchanged\n"
        self.path = "thesis/evaluation/fixture.py"
        self.cert = dict(status="PROVEN", source_pins={
            self.path: hashlib.sha256(self.source).hexdigest()})
        self.cert["certificate_sha256"] = ch.canonical_sha256(self.cert)
        self.contract = dict(extension_provenance=dict(equivalence_sha256=self.cert["certificate_sha256"]))
        self.manifest = dict(git_commit="b" * 40, git_dirty=False)

    def read(self, root, commit, relative):
        self.assertEqual(commit, self.manifest["git_commit"])
        return json.dumps(self.cert).encode() if relative.endswith(".json") else self.source

    def test_clean_snapshot_not_live_head(self):
        result = history.verify(Path("."), self.manifest, self.contract, self.read)
        self.assertEqual(result["verified_source_count"], 1)
        self.assertEqual(result["commit"], "b" * 40)

    def test_changed_source_refused(self):
        self.source += b"changed"
        with self.assertRaises(RecoveryRefused):
            history.verify(Path("."), self.manifest, self.contract, self.read)

    def test_changed_certificate_refused(self):
        self.cert["status"] = "DRAFT"
        with self.assertRaises(RecoveryRefused):
            history.verify(Path("."), self.manifest, self.contract, self.read)

    def test_wrong_contract_binding_refused(self):
        self.contract["extension_provenance"]["equivalence_sha256"] = "wrong"
        with self.assertRaises(RecoveryRefused):
            history.verify(Path("."), self.manifest, self.contract, self.read)

    def test_dirty_or_unknown_snapshot_refused(self):
        for dirty in (True, None):
            with self.subTest(dirty=dirty), self.assertRaises(RecoveryRefused):
                history.verify(Path("."), dict(self.manifest, git_dirty=dirty), self.contract, self.read)

    def test_unknown_routing_edit_refused(self):
        from thesis.evaluation.recovery_source_projection import pre_recovery_enhanced_source
        source = (Path(__file__).parent / "run_enhanced_tests.py").read_text(encoding="utf-8")
        pre_recovery_enhanced_source(source)
        with self.assertRaises(ValueError):
            pre_recovery_enhanced_source(source.replace("candidate_source_run", "unexpected")) if "candidate_source_run" in source else pre_recovery_enhanced_source(source.replace("candidate_provenance(config", "unexpected(config"))


if __name__ == "__main__":
    unittest.main()
