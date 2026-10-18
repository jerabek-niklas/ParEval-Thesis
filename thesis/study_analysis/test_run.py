"""Tests of run.py's output logic (no real data): estimate serialisation,
the never-overwrite formal write through a partial directory, the dump
writer and the README/validation renderings.

    python3 -B -m unittest -v thesis.study_analysis.test_run
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
from unittest import mock

from thesis.study_analysis import core, run


def estimate(metric_id="Q06", value=0.5, extra=None):
    est = OrderedDict([("metric_id", metric_id), ("population", "BASE"), ("block", "composite"),
                       ("strata", OrderedDict([("model_id", "m")])), ("numerator", 1), ("denominator", 2),
                       ("value", value), ("ci_low", 0.25), ("ci_high", 0.75),
                       ("ci_method", "cluster_bootstrap_percentile"), ("replicates", 2000), ("p_value", None),
                       ("p_holm", None), ("reject_holm", None), ("note", None)])
    est.update(extra or {})
    return est


class SerialisationTest(unittest.TestCase):
    def test_estimates_json_is_compact_deterministic_and_complete(self):
        estimates = [estimate(), estimate("E02", 0.25, {"post_freeze": False, "ci_degenerate": False})]
        first = run.estimates_json_bytes(estimates)
        self.assertEqual(first, run.estimates_json_bytes(estimates))
        self.assertEqual(json.loads(first.decode("utf-8")), json.loads(json.dumps(estimates)))
        self.assertNotIn(b"\n ", first)

    def test_estimates_csv_keeps_core_columns_and_extras(self):
        estimates = [estimate(extra={"post_freeze": True, "excluded": 3}), estimate("R04", -0.1)]
        rows = list(csv.reader(io.StringIO(run.estimates_csv_bytes(estimates).decode("utf-8"))))
        self.assertEqual(tuple(rows[0]), run.ESTIMATE_COLUMNS)
        self.assertEqual(len(rows), 3)
        header = rows[0]
        first = dict(zip(header, rows[1]))
        self.assertEqual(json.loads(first["strata"]), {"model_id": "m"})
        self.assertEqual(json.loads(first["extra"]), {"excluded": 3, "post_freeze": True})
        self.assertEqual(dict(zip(header, rows[2]))["extra"], "")

    def test_gzip_outputs_are_byte_stable(self):
        data = run.estimates_json_bytes([estimate()])
        self.assertEqual(core.gzip_bytes(data), core.gzip_bytes(data))
        self.assertEqual(gzip.decompress(core.gzip_bytes(data)), data)


class FormalWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.files = OrderedDict([("results.json", b"{}\n"), ("tables/T1.csv", b"a,b\n")])

    def tearDown(self):
        self.tmp.cleanup()

    def test_formal_write_creates_the_complete_tree_in_one_rename(self):
        target = run.formal_write(self.root, self.files)
        self.assertEqual(target, (self.root / core.OUTPUT_REL).resolve())
        self.assertEqual((target / "tables/T1.csv").read_bytes(), b"a,b\n")
        leftovers = [p.name for p in target.parent.iterdir() if ".partial-" in p.name]
        self.assertEqual(leftovers, [])

    def test_formal_write_never_overwrites(self):
        (self.root / core.OUTPUT_REL).mkdir(parents=True)
        with self.assertRaises(core.AnalysisRefused):
            run.formal_write(self.root, self.files)

    def test_failed_write_leaves_no_partial_directory(self):
        with mock.patch.object(core, "write_bytes", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run.formal_write(self.root, self.files)
        parent = (self.root / core.OUTPUT_REL).parent
        self.assertFalse((self.root / core.OUTPUT_REL).exists())
        self.assertEqual([p for p in parent.iterdir()] if parent.exists() else [], [])

    def test_write_tree_writes_exactly_the_given_files(self):
        written = run.write_tree(self.root / "dump", self.files)
        self.assertEqual(written, sorted(self.files))
        self.assertEqual((self.root / "dump/results.json").read_bytes(), b"{}\n")


class RenderingTest(unittest.TestCase):
    def test_validation_markdown_lists_every_check(self):
        doc = OrderedDict([("schema_version", core.VALIDATION_SCHEMA), ("status", "PASS"),
                           ("validation_sha256", "f" * 64),
                           ("checks", [{"check": "counts", "status": "PASS", "detail": {"a|b": 1}},
                                       {"check": "x", "status": "FAIL", "detail": "y" * 1000}]),
                           ("summary", {"n": 2})])
        text = run.validation_markdown(doc)
        self.assertIn("| counts | PASS |", text)
        self.assertIn("| x | FAIL |", text)
        self.assertIn("a\\|b", text)
        self.assertIn("...", text)

    def test_readme_names_post_freeze_and_disclosures(self):
        addendum = core.load_addendum()
        results = OrderedDict([("mode", "dry-run"), ("status", "PASS"), ("results_sha256", "a" * 64),
                               ("inputs", {"closure": {"closure_sha256": "c" * 64},
                                           "composite": {"composite_sha256": "d" * 64}}),
                               ("methodology", {"canonical_sha256": "e" * 64}),
                               ("addendum", {"canonical_sha256": "b" * 64, "status": addendum["status"]}),
                               ("pilot_label", "PILOT LABEL")])
        text = run.readme_markdown(results, [{"id": "T1_inventory", "title": "Inventory", "population": "all"}],
                                   [{"id": "F1", "title": "Figure"}], addendum)
        self.assertIn("post-hoc", text)
        self.assertIn("PILOT LABEL", text)
        for note in addendum["table_notes"]:
            self.assertIn(note["text"], text)
        for caveat in addendum["interpretive_caveats"]:
            self.assertIn(caveat["id"], text)
        self.assertIn("never repair successes", text)


class ArgumentTest(unittest.TestCase):
    def test_out_inside_the_repository_is_refused(self):
        with mock.patch.object(run, "run") as pipeline:
            with mock.patch("pathlib.Path.cwd", return_value=core.REPO_ROOT):
                code = run.main(["--dry-run", "--out", str(core.REPO_ROOT / "thesis" / "x")])
        self.assertEqual(code, 2)
        pipeline.assert_not_called()

    def test_out_with_write_is_refused(self):
        with mock.patch.object(run, "run") as pipeline:
            with mock.patch("pathlib.Path.cwd", return_value=core.REPO_ROOT):
                code = run.main(["--write", "--out", "/tmp/x"])
        self.assertEqual(code, 2)
        pipeline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
