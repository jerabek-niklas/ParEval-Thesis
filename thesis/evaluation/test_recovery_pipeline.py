"""Synthetic routing/reader gates. No provider, Docker or tool execution."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from thesis.evaluation import recovery_context as rc
from thesis.evaluation.recovery_lineage import PARENT, RECOVERY, PILOT, VARIANTS, RecoveryRefused
from thesis.evaluation.composite_study_v2 import population


class PipelineTests(unittest.TestCase):
    def test_exact_composite_population(self):
        self.assertEqual(population(self.blocks(), self.derived())["base_cells"], 1980)

    def blocks(self):
        result = []
        for run, start, end in ((PILOT, 0, 12), (PARENT, 12, 60)):
            result.append(dict(run_id=run, samples_per_prompt=1,
                               model_ids=["m%d" % i for i in range(11)],
                               prompt_hashes={"kind|b%d|%s" % (i, e): "hash"
                                              for i in range(start, end) for e in ("serial", "omp", "mpi")}))
        return result

    def derived(self):
        return dict(run_id=RECOVERY, parent_run_id=PARENT, base_cells=0)

    def test_third_population_overlap_and_model_drift_refused(self):
        blocks = self.blocks()
        cases = [blocks + [copy.deepcopy(blocks[0])], [blocks[0], blocks[0]]]
        wrong = copy.deepcopy(blocks); wrong[1]["model_ids"][0] = "different"; cases.append(wrong)
        for case in cases:
            with self.assertRaises(RecoveryRefused):
                population(case, self.derived())
        with self.assertRaises(RecoveryRefused):
            population(blocks, dict(self.derived(), base_cells=1584))

    def test_overview_explicit_stage_ownership(self):
        from thesis.analysis_overview.recovery_reader import stage_sources
        self.assertEqual(stage_sources("static"), (PILOT, PARENT))
        self.assertEqual(stage_sources("enhanced"), (PILOT, RECOVERY))
        self.assertEqual(stage_sources("repair"), (PILOT, RECOVERY))
        with self.assertRaises(RecoveryRefused):
            stage_sources("unknown")

    def test_native_reader_never_relabels(self):
        from thesis.analysis_overview.recovery_reader import read_stage
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for run in (PILOT, PARENT):
                p = root / "thesis/results/intermediate" / run / "m/static_analysis.jsonl"
                p.parent.mkdir(parents=True)
                p.write_text(json.dumps(dict(run_id=run, model_id="m", sample_id=run)), encoding="utf-8")
            rows = read_stage(root, "static", ["m"])
            self.assertEqual([r["source_run"] for r in rows], [PILOT, PARENT])
            self.assertTrue(all(r["record"]["run_id"] == r["source_run"] for r in rows))
            p.write_text(json.dumps(dict(run_id=RECOVERY, model_id="m", sample_id="s")), encoding="utf-8")
            with self.assertRaises(RecoveryRefused):
                read_stage(root, "static", ["m"])

    def test_authorization_discovers_definition_without_run_state(self):
        from thesis.evaluation import run_authorization as ra
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definitions = root / "definitions"; definitions.mkdir()
            (definitions / "contract.json").write_text("{}", encoding="utf-8")
            config = {"outputs": {"intermediate_dir": str(root / "results")}}
            with patch.object(rc, "DEFINITIONS", definitions):
                found = ra.discover_frozen_contract(config, RECOVERY)
            self.assertEqual(found["path"], definitions / "contract.json")
            self.assertFalse((root / "results").exists())

    def test_fresh_parent_references_do_not_prepopulate_recovery(self):
        from thesis.evaluation.run_freshness import inspect_run_freshness
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"outputs": {"raw_dir":str(root/"raw"), "intermediate_dir":str(root/"intermediate")}}
            parent = root / "raw" / PARENT / "m"; parent.mkdir(parents=True)
            (parent / "generations.jsonl").write_text("historical", encoding="utf-8")
            self.assertEqual(inspect_run_freshness(config, RECOVERY)["status"], "FRESH")
            recovery = root / "raw" / RECOVERY / "m"; recovery.mkdir(parents=True)
            (recovery / "generations.jsonl").write_text("illicit", encoding="utf-8")
            self.assertEqual(inspect_run_freshness(config, RECOVERY)["status"], "NOT_FRESH")

    def test_backfill_cannot_schedule_base_measurements(self):
        from thesis.repair.run_backfill import StageExecutor
        executor = object.__new__(StageExecutor)
        executor.config = {"profiles":{"recovery":{"run_id":RECOVERY}}}
        executor.profile_name = "recovery"
        for stage in ("static.main", "correctness", "dynamic"):
            with self.assertRaises(ValueError):
                executor._enforce(RECOVERY, "m", stage)

    def test_per_model_terminal_gate_missing_active_and_complete(self):
        from thesis.repair import orchestrator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {"outputs":{"raw_dir":str(root/"raw"), "intermediate_dir":str(root/"intermediate")}}
            assembly = root / "parent.jsonl"
            assembly.write_text(json.dumps({"sample_id":"s"}), encoding="utf-8")
            lineage = SimpleNamespace(document={"model_ids":["m", "other"]})
            with patch.object(rc,"load_lineage",return_value=lineage), patch.object(rc,"assembly_path",return_value=assembly):
                with self.assertRaises((RecoveryRefused, FileNotFoundError)):
                    rc.require_terminal(config, "m")
                for variant in VARIANTS:
                    paths = orchestrator.LoopPaths(config, RECOVERY, "m", variant)
                    paths.state_path.parent.mkdir(parents=True, exist_ok=True)
                    paths.state_path.write_text(json.dumps(dict(run_id=RECOVERY, model_id="m", variant=variant,
                        sample_id="s", iteration=0,status=orchestrator.TERMINAL_STATUSES[0]))+"\n", encoding="utf-8")
                    paths.wave_state_path.write_text(json.dumps(dict(run_id=RECOVERY,model_id="m",variant=variant,
                        iteration=0,phase="done")), encoding="utf-8")
                self.assertTrue(rc.require_terminal(config, "m"))
                rows=json.loads(paths.state_path.read_text()); rows["status"]="active"
                paths.state_path.write_text(json.dumps(rows),encoding="utf-8")
                with self.assertRaises(RecoveryRefused): rc.require_terminal(config,"m")

    def test_foreign_and_historical_result_rejected(self):
        from thesis.evaluation.verify_recovery_run import native_rows
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"rows.jsonl"
            p.write_text(json.dumps(dict(run_id=PARENT,model_id="m",sample_id="s")),encoding="utf-8")
            with self.assertRaises(RecoveryRefused): native_rows(p,RECOVERY+"__static_feedback__iter1","m")


if __name__ == "__main__":
    unittest.main()
