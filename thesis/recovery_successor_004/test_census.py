"""Synthetic tests of the read-only experiment repair-loop census."""
import json
import tempfile
import unittest
from pathlib import Path

from thesis.recovery_successor_004 import census

CONDITION = "c" * 64


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


class CensusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.models = ["a", "b"]
        for relative in census.POPULATION_FILES.values():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model_ids": self.models}), encoding="utf-8")
        for block, run in census.BLOCKS.items():
            for model in self.models:
                cells = 2 if block == "pilot" else 3
                write(self.root / "thesis/results/intermediate" / run / model / "assembly.jsonl",
                      [{"sample_id": "%s_%s_%d" % (model, block, i)} for i in range(cells)])

    def loop(self, run, model, variant, rows, phase="done", extra=None):
        directory = self.root / "thesis/results/intermediate" / run / model / "repair" / variant
        wave = {"run_id": run, "model_id": model, "variant": variant, "iteration": 2, "phase": phase,
                "repair_condition_sha256": CONDITION}
        wave.update(extra or {})
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "wave_state.json").write_text(json.dumps(wave), encoding="utf-8")
        write(directory / "state.jsonl", [dict(r, run_id=run, model_id=model, variant=variant) for r in rows])

    def rows(self, model, block, statuses, iteration=0):
        return [{"sample_id": "%s_%s_%d" % (model, block, i), "iteration": iteration, "status": s}
                for i, s in enumerate(statuses)]

    def test_counts_owners_overlays_and_cells(self):
        for model in self.models:
            for variant in census.VARIANTS:
                self.loop("pilot_002", model, variant, self.rows(model, "pilot", ["stopped_clean"] * 2))
        # model a: recovery_001 head + a continued successor tail (static), adopted test
        self.loop(census.ORIGIN, "a", "static_feedback",
                  self.rows("a", "full_ext", ["stopped_clean", "active", "active"]),
                  phase="analyzed_waiting_external")
        self.loop("full_ext_recovery_003", "a", "static_feedback",
                  self.rows("a", "full_ext", ["stopped_clean", "stopped_budget", "stopped_budget"],
                            iteration=1)[1:], extra={"predecessor_run_id": census.ORIGIN})
        self.loop(census.ORIGIN, "a", "test_feedback", self.rows("a", "full_ext", ["stopped_tests_pass"] * 3))
        # model b: a native fresh 004 loop, one terminal and one still open
        self.loop("full_ext_recovery_004", "b", "static_feedback",
                  self.rows("b", "full_ext", ["stopped_clean", "stopped_budget", "repair_unusable"]))
        self.loop("full_ext_recovery_004", "b", "combined_feedback",
                  self.rows("b", "full_ext", ["stopped_clean", "active", "active"]), phase="requests_built")
        # a stray parent repair is never an owner
        self.loop("full_ext_001", "b", "test_feedback", self.rows("b", "full_ext", ["active"] * 3),
                  phase="assembled")
        summary = census.summary(census.census(self.root, self.models))
        self.assertEqual(summary["total_repair_loops_done"], "%d/12" % (6 + 3))
        full = summary["blocks"]["full_ext"]
        self.assertEqual(full["terminal"], 3)
        self.assertEqual(full["open"], ["b/combined_feedback"])
        self.assertEqual(sorted(full["not_started"]), ["a/combined_feedback", "b/test_feedback"])
        self.assertEqual(dict(summary["base_cells"]), {"pilot": 4, "full_ext": 6, "total": 10})
        self.assertEqual(summary["repair_conditions"], [CONDITION])

    def test_two_owners_and_foreign_rows_refuse(self):
        self.loop("full_ext_recovery_003", "a", "static_feedback", [])
        self.loop("full_ext_recovery_004", "a", "static_feedback", [])
        with self.assertRaises(ValueError):
            census.census(self.root, self.models)

    def test_a_continued_owner_may_not_write_iteration_zero(self):
        self.loop(census.ORIGIN, "a", "static_feedback", self.rows("a", "full_ext", ["active"] * 3))
        self.loop("full_ext_recovery_002", "a", "static_feedback",
                  self.rows("a", "full_ext", ["stopped_clean"] * 3), extra={"predecessor_run_id": census.ORIGIN})
        with self.assertRaises(ValueError):
            census.census(self.root, self.models)


if __name__ == "__main__":
    unittest.main()
