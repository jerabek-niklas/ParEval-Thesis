"""full_ext_recovery_003: synthetic tests of the AST normalizer (reused) and the
successor handoff primitives. No providers, analyses, authorization or writes
outside temporary directories."""
import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path

from thesis.evaluation import successor_ast as sa
from thesis.recovery_successor_003 import handoff as sh
from thesis.evaluation.recovery_lineage import RecoveryRefused
from thesis.evaluation.condition_hashing import canonical_sha256


class AstTests(unittest.TestCase):
    def test_version_explicit(self):
        self.assertEqual(sa.VERSION, "successor_ast.index_v1")

    def test_legacy_index_wrapper(self):
        # Modern ast.Index constructors return their argument, so model the
        # actual 3.8 node shape instead of relying on that compatibility shim.
        Index = type("Index", (ast.AST,), {"_fields": ("value",)})
        node = Index(); node.value = ast.parse("i", mode="eval").body
        self.assertEqual(sa.normalize(node), sa.normalize(node.value))

    def test_unproven_extslice_refused(self):
        ExtSlice = type("ExtSlice", (ast.AST,), {"_fields": ("dims",)})
        node = ExtSlice(); node.dims = []
        with self.assertRaises(RecoveryRefused):
            sa.normalize(node)

    def test_unrecognized_index_shape_refused(self):
        Index = type("Index", (ast.AST,), {"_fields": ("value", "extra")})
        with self.assertRaises(RecoveryRefused):
            sa.normalize(Index())

    def test_actual_method_changes_remain_visible(self):
        pairs = [("x=a[i]", "x=a[j]"), ("x=a[1]", "x=a[2]"),
                 ("x=a+b", "x=a-b"), ("x=f(a)", "x=g(a)"),
                 ("if a: f()", "if b: f()"), ("x=a[1:2]", "x=a[1:3]"),
                 ("x=a[i,j]", "x=a[j,i]"), ("return a", "return b")]
        for before, after in pairs:
            with self.subTest(before=before):
                self.assertNotEqual(sa.projection_sha256(before), sa.projection_sha256(after))

    def test_routing_exclusion_does_not_remove_other_functions(self):
        a = "def route():\n return 1\ndef measure():\n return 1\n"
        b = a.replace("def route():\n return 1", "def route():\n return 2")
        c = a.replace("def measure():\n return 1", "def measure():\n return 2")
        self.assertEqual(sa.projection(a, ("route",)), sa.projection(b, ("route",)))
        self.assertNotEqual(sa.projection(a, ("route",)), sa.projection(c, ("route",)))


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = sh.iteration_run(sh.PREDECESSOR, "static_feedback", 1, 2)
        self.relative = "thesis/results/raw/%s/m/generations.jsonl" % self.run
        self.path = self.root / self.relative
        self.path.parent.mkdir(parents=True)
        self.row = dict(run_id=self.run, model={"id": "m"}, sample_id="s")
        self.path.write_text(json.dumps(self.row) + "\n", encoding="utf-8")

    def snapshot(self):
        d = sh.build_snapshot(self.root)
        return sh.Snapshot(self.root, d, d["snapshot_sha256"])

    def test_native_bytes_and_identity_preserved(self):
        before = self.path.read_bytes()
        snap = self.snapshot()
        self.assertTrue(snap.verify_all())
        rows = snap.rows(self.relative, self.run, "m")
        self.assertEqual(rows[0]["record"], self.row)
        self.assertEqual(rows[0]["source_run"], self.run)
        self.assertEqual(before, self.path.read_bytes())

    def test_drift_refused_on_every_read_including_resume(self):
        snap = self.snapshot()
        resumed = sh.Snapshot(self.root, snap.document, snap.document["snapshot_sha256"])
        self.path.write_bytes(b"changed")
        for reader in (snap, resumed):
            with self.assertRaises(RecoveryRefused):
                reader.read_bytes(self.relative)

    def test_new_member_refused(self):
        snap = self.snapshot()
        (self.path.parent / "unexpected.json").write_text("{}")
        with self.assertRaises(RecoveryRefused):
            snap.verify_all()

    def test_unregistered_read_refused(self):
        with self.assertRaises(RecoveryRefused):
            self.snapshot().read_bytes(self.relative + ".other")

    def test_duplicate_rows_refused(self):
        self.path.write_text((json.dumps(self.row) + "\n") * 2)
        with self.assertRaises(RecoveryRefused):
            self.snapshot().rows(self.relative, self.run, "m")

    def test_wrong_model_and_run_refused(self):
        snap = self.snapshot()
        for run, model in ((self.run, "wrong"), (sh.SUCCESSOR, "m")):
            with self.assertRaises(RecoveryRefused):
                snap.rows(self.relative, run, model)

    def test_historical_parent_repair_even_with_rehashed_manifest_refused(self):
        d = self.snapshot().document
        facts = d["files"].pop(self.relative)
        d["files"][self.relative.replace(sh.PREDECESSOR, "full_ext_001")] = facts
        d["snapshot_sha256"] = canonical_sha256({k:v for k,v in d.items() if k != "snapshot_sha256"})
        with self.assertRaises(RecoveryRefused):
            sh.Snapshot(self.root, d, d["snapshot_sha256"])


class OwnershipTests(unittest.TestCase):
    def test_gaps_errors_and_timeouts_are_present(self):
        for status in ("timeout", "tool_error", "partial", "not_analyzed"):
            envelope = dict(source_run=sh.PREDECESSOR, source_artifact_sha256="a"*64,
                            record=dict(run_id=sh.PREDECESSOR, status=status))
            self.assertEqual(sh.missing_tool_keys({"s"}, [("s", envelope)]), set())

    def test_duplicate_ownership_refused_even_if_identical(self):
        e = dict(source_run=sh.PREDECESSOR, source_artifact_sha256="a"*64,
                 record=dict(run_id=sh.PREDECESSOR))
        with self.assertRaises(RecoveryRefused):
            sh.missing_tool_keys({"s"}, [("s", e), ("s", e)])

    def test_iteration_budget_never_resets(self):
        for value in (0, 3, True, "1"):
            with self.assertRaises(RecoveryRefused):
                sh.iteration_run(sh.SUCCESSOR, "static_feedback", value, 2)

    def test_answered_requests_not_resubmitted(self):
        request = dict(run_id=sh.PREDECESSOR, model_id="m", sample_id="s",
                       variant="static_feedback", strategy="static_feedback", iteration=1,
                       built_from_iteration=0, request="exact feedback", request_chars=14)
        run = sh.iteration_run(sh.PREDECESSOR, "static_feedback", 1, 2)
        response = dict(run_id=run, model={"id":"m"}, sample_id="s", status={"success":True},
                        repair={k:request[k] for k in ("variant", "strategy", "iteration", "built_from_iteration", "request_chars")})
        before = copy.deepcopy((request, response))
        for _ in range(2):
            self.assertEqual(sh.unanswered_requests([request], [response], run, "m", "static_feedback", 1, 2), set())
        self.assertEqual((request, response), before)
        with self.assertRaises(RecoveryRefused):
            sh.unanswered_requests([request], [response, response], run, "m", "static_feedback", 1, 2)
        response["status"] = {"success":False, "error_type":"TransportError"}
        with self.assertRaises(RecoveryRefused):
            sh.unanswered_requests([request], [response], run, "m", "static_feedback", 1, 2)


class ProtectedRunTests(unittest.TestCase):
    """Sibling successor runs are inventoried byte for byte and never adopted."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.prefix = "full_ext_recovery_002"
        self.path = self.root / ("thesis/results/raw/%s__static_feedback__iter2/m/generations.jsonl"
                                 % self.prefix)
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b'{"sample_id": "s"}\n')
        other = self.root / "thesis/results/intermediate/full_ext_recovery_0020/m/x.json"
        other.parent.mkdir(parents=True)
        other.write_bytes(b"{}")  # a different run that merely shares the prefix text

    def test_inventory_covers_exactly_the_run_trees(self):
        document = sh.protected_inventory(self.root, self.prefix)
        self.assertEqual(list(document["files"]),
                         ["thesis/results/raw/%s__static_feedback__iter2/m/generations.jsonl" % self.prefix])
        self.assertTrue(sh.verify_protected(self.root, document))

    def test_changed_added_or_tampered_refuse(self):
        document = sh.protected_inventory(self.root, self.prefix)
        self.path.write_bytes(b'{"sample_id": "t"}\n')
        with self.assertRaises(RecoveryRefused):
            sh.verify_protected(self.root, document)
        self.path.write_bytes(b'{"sample_id": "s"}\n')
        (self.path.parent / "extra.jsonl").write_bytes(b"")
        with self.assertRaises(RecoveryRefused):
            sh.verify_protected(self.root, document)
        (self.path.parent / "extra.jsonl").unlink()
        tampered = copy.deepcopy(document)
        tampered["file_count"] = 2
        with self.assertRaises(RecoveryRefused):
            sh.verify_protected(self.root, tampered)
        self.assertTrue(sh.verify_protected(self.root, document))

    def test_own_runs_are_no_protected_prefix(self):
        for prefix in (sh.SUCCESSOR, sh.PREDECESSOR, "", "a/b"):
            with self.assertRaises(RecoveryRefused):
                sh.run_tree_paths(self.root, prefix)


if __name__ == "__main__":
    unittest.main()
