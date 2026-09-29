"""Synthetic authorization/resume checks, isolated under TemporaryDirectory."""
import tempfile
import copy
import hashlib
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from thesis.evaluation import pilot_run_contract as pc, recovery_contract as recovery
from thesis.evaluation import run_authorization as ra
from thesis.evaluation.recovery_lineage import RECOVERY, RecoveryRefused


class AuthorizationTests(unittest.TestCase):
    def test_repair_state_machine_fresh_then_resume_without_parent_state_adoption(self):
        from thesis.evaluation.test_post_run_verification import World
        from thesis.evaluation.recovery_lineage import PARENT, PILOT, OWNERSHIP, SCHEMA, RecoveryLineage, fingerprint
        from thesis.repair.recovery_routing import RecoveryRepairLoop
        with tempfile.TemporaryDirectory() as tmp:
            world = World(Path(tmp)/"fixture", run_id=PARENT)
            root = Path(tmp)/"repo"
            config = copy.deepcopy(world.config)
            artifacts = []
            for key, folder in (("raw_dir", "raw"), ("intermediate_dir", "intermediate")):
                target = root/"thesis/results"/folder
                shutil.copytree(Path(config["outputs"][key]), target)
                config["outputs"][key] = str(target)
                for path in (target/PARENT).rglob("*"):
                    if path.is_file():
                        data = path.read_bytes()
                        artifacts.append(dict(path=path.relative_to(root).as_posix(), raw_sha256=hashlib.sha256(data).hexdigest(),
                                              size=len(data), source_run=PARENT, stage="fixture"))
            document = dict(schema_version=SCHEMA, run_id=RECOVERY, parent_run_id=PARENT, pilot_run_id=PILOT,
                            stage_ownership=OWNERSHIP, recovery_base_cells=0, model_ids=world.models,
                            max_iterations=2, historical_repair_policy="EXCLUDE_ALL_PARENT_REPAIR",
                            artifacts=sorted(artifacts, key=lambda item:item["path"]))
            document["lineage_sha256"] = fingerprint(document)
            lineage = RecoveryLineage(root, document, document["lineage_sha256"])
            def make_loop():
                return RecoveryRepairLoop(config, str(world.config_path), "fixture", {"run_id":RECOVERY},
                                          config["models"][0], "static_feedback", lineage=lineage)
            loop = make_loop()
            self.assertEqual(loop.sample_states(), {})
            with patch.object(recovery,"build",return_value={}), patch.object(ra,"load_and_validate_run_authorization",return_value={}):
                for current in (loop, make_loop()):
                    with patch.object(current,"_submit",side_effect=AssertionError("no provider allowed")), \
                         patch.object(current,"_run_analysis_stages",side_effect=AssertionError("no measurement allowed")):
                        self.assertEqual(current.run(), "done")
            states = make_loop().sample_states()
            self.assertEqual(len(states), 2)
            self.assertTrue(all(row["run_id"] == RECOVERY for row in states.values()))
            lineage.verify_artifacts()

    def tearDown(self):
        ra.clear_context()

    def test_dispatch_uses_new_contract_not_historical_extension(self):
        with patch.object(recovery,"build",return_value={"fixture":True}) as builder:
            self.assertEqual(pc.build_contract(Path("fixture"),"recovery",RECOVERY),{"fixture":True})
        builder.assert_called_once_with(Path("fixture"),RECOVERY,"g++")

    def test_real_authorization_readback_resume_and_direct_revalidation(self):
        from thesis.evaluation.test_post_run_verification import World
        with tempfile.TemporaryDirectory() as tmp:
            world=World(Path(tmp),run_id=RECOVERY,repair_loops=False)
            saved=ra.load_authorization(world.config,RECOVERY)
            self.assertEqual(saved["decision"],"START_ALLOWED")
            validated=ra.load_and_validate_run_authorization(world.config,RECOVERY,
                config_path=world.config_path,profile="fixture",contract_path=world.contract_path)
            self.assertEqual(validated["authorization"]["authorization_sha256"],saved["authorization_sha256"])
            ra.require_provider_call(ra.CALL_KIND_DIRECT)
            with patch.object(pc,"build_contract",side_effect=RecoveryRefused("parent SHA drift")):
                with self.assertRaises(ra.PreRunInfrastructureFailure):
                    ra.require_provider_call(ra.CALL_KIND_DIRECT)
            self.assertEqual(ra.load_authorization(world.config,RECOVERY),saved)


if __name__ == "__main__": unittest.main()
