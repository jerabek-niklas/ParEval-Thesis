"""full_ext_recovery_004: synthetic tests of the AST normalizer (reused) and the
successor handoff primitives (snapshot, absence proof, protected runs). No providers, analyses, authorization or writes
outside temporary directories."""
import ast
import copy
import json
import tempfile
import unittest
from pathlib import Path

from thesis.evaluation import successor_ast as sa
from thesis.recovery_successor_004 import handoff as sh
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
    def test_iteration_budget_never_resets(self):
        for value in (0, 3, True, "1"):
            with self.assertRaises(RecoveryRefused):
                sh.iteration_run(sh.SUCCESSOR, "static_feedback", value, 2)
        self.assertEqual(sh.iteration_run(sh.SUCCESSOR, "test_feedback", 2, 2),
                         "full_ext_recovery_004__test_feedback__iter2")

    def test_latest_by_sample_is_last_row_wins(self):
        rows = [dict(sample_id="s", iteration=0, status="active"),
                dict(sample_id="t", iteration=0, status="stopped_clean"),
                dict(sample_id="s", iteration=1, status="stopped_budget")]
        self.assertEqual({k: v["status"] for k, v in sh.latest_by_sample(rows).items()},
                         {"s": "stopped_budget", "t": "stopped_clean"})


class AbsenceTests(unittest.TestCase):
    """A fresh 004 model must have no repair evidence in any other run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        base = self.root / "thesis/results/intermediate/full_ext_001/m"
        base.mkdir(parents=True)
        (base / "assembly.jsonl").write_bytes(b"")  # base evidence is fine
        other = self.root / "thesis/results/intermediate/full_ext_recovery_001/other/repair/x"
        other.mkdir(parents=True)
        (other / "state.jsonl").write_bytes(b"")
        own = self.root / "thesis/results/raw/full_ext_recovery_004__static_feedback__iter1/m"
        own.mkdir(parents=True)
        (own / "generations.jsonl").write_bytes(b"")  # its own run is not foreign

    def test_absent(self):
        self.assertEqual(sh.absence_paths(self.root, "m"), [])

    def test_every_foreign_owner_is_found(self):
        cases = ["thesis/results/intermediate/full_ext_recovery_001/m/repair/static_feedback/state.jsonl",
                 "thesis/results/raw/full_ext_recovery_002__static_feedback__iter2/m/generations.jsonl",
                 "thesis/results/intermediate/full_ext_recovery_003__combined_feedback__iter2/m/a.jsonl",
                 "thesis/results/intermediate/full_ext_001/m/repair/static_feedback/state.jsonl",
                 "thesis/results/raw/full_ext_001__static_feedback__iter1/m/generations.jsonl"]
        for relative in cases:
            with self.subTest(relative=relative):
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
                self.assertIn(relative, sh.absence_paths(self.root, "m"))
                path.unlink()
                for parent in list(path.parents)[:4]:
                    if parent.exists() and parent != self.root / "thesis/results/intermediate/full_ext_001/m"                             and not any(parent.iterdir()):
                        parent.rmdir()
                self.assertEqual(sh.absence_paths(self.root, "m"), [])

    def test_invalid_model_refused(self):
        for model in ("", "a/b", "a\\b", "..", "."):
            with self.assertRaises(RecoveryRefused):
                sh.absence_paths(self.root, model)


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
