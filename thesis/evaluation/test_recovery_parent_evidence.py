"""Read-only integration/negative tests on the local immutable parent fixture.

Mutations are injected into decoded values in memory, never into parent files.
The ordinary inventory/verification code remains responsible for rejection.
"""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from thesis.evaluation import verify_parent_base_evidence as parent
from thesis.evaluation.recovery_lineage import RecoveryRefused, fingerprint


class ParentEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        if not (cls.root / parent.BASE / "run_contract.json").exists():
            raise unittest.SkipTest("local historical parent fixture unavailable")
        cls.document = parent.build_inventory(cls.root)

    def verify(self, document=None):
        document = document or self.document
        return parent.verify(self.root, document, document["lineage_sha256"])

    def test_exact_parent_population_and_historical_sources(self):
        report = self.verify()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["base_cells"], 1584)
        self.assertEqual(report["historical_source"]["verified_source_count"], 324)
        self.assertFalse(report["historical_repair_adopted"])

    def test_wrong_parent_byte_hash(self):
        doc = copy.deepcopy(self.document)
        doc["artifacts"][0]["raw_sha256"] = "0" * 64
        doc["lineage_sha256"] = fingerprint(doc)
        with self.assertRaises(RecoveryRefused):
            self.verify(doc)

    def test_missing_parent_artifact(self):
        actual = parent.files
        with patch.object(parent, "files", side_effect=lambda root: actual(root)[1:]):
            with self.assertRaises(RecoveryRefused):
                self.verify()

    def test_wrong_run_model_source_hash_and_duplicate(self):
        original = parent.records
        for field, value in (("run_id", "other"), ("model_id", "other"),
                             ("source_sha256", "0" * 64), ("duplicate", True)):
            def changed(path):
                rows = original(path)
                if Path(path).name == "assembly.jsonl" and rows:
                    rows = copy.deepcopy(rows)
                    if field == "duplicate":
                        rows.append(copy.deepcopy(rows[0]))
                    else:
                        rows[0][field] = value
                return rows
            with self.subTest(field=field), patch.object(parent, "records", side_effect=changed):
                with self.assertRaises(RecoveryRefused):
                    self.verify()

    def test_authorization_t0_population_mismatch(self):
        for key in ("parent_authorization_sha256", "parent_runtime_evidence_sha256", "parent_population_sha256"):
            doc = copy.deepcopy(self.document)
            doc[key] = "0" * 64
            doc["lineage_sha256"] = fingerprint(doc)
            with self.subTest(key=key), self.assertRaises(RecoveryRefused):
                self.verify(doc)


if __name__ == "__main__":
    unittest.main()
