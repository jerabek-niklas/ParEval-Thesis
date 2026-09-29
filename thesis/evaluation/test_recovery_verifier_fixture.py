"""Complete miniature on-disk recovery acceptance fixture.

Only the independently tested parent-contract/authorization discovery boundary
is injected. Terminal states, coverage, provenance, runtime/invocation stamps,
enhanced fingerprints and the final verifier execute normally. No tools run.
"""
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch, Mock

from thesis.evaluation import recovery_context as rc, recovery_contract, run_authorization as ra
from thesis.evaluation import verify_recovery_run as verifier, verify_pilot_run as vp, run_manifest
from thesis.evaluation.recovery_lineage import PARENT, PILOT, RECOVERY, VARIANTS, OWNERSHIP, SCHEMA, RecoveryLineage, fingerprint


class CompleteVerifierFixture(unittest.TestCase):
    def test_complete_fixture_then_missing_terminal_sample_refuses(self):
        from thesis.evaluation.test_post_run_verification import World
        from thesis.enhanced_tests import execution_provenance as ep
        from thesis.evaluation import atomic_io
        class BaseTerminalWorld(World):
            def loop_registers_invocation(self, model, variant):
                # All fixture loops stop at iteration zero using the complete
                # parent evidence; no repair analysis was invoked.
                return False
        models = ["m%d" % i for i in range(11)]
        overrides = {"repair":dict(enabled=True, max_iterations=2, variants=list(VARIANTS)),
                     "dynamic_analysis":dict(enabled=True, tools={})}
        with tempfile.TemporaryDirectory() as tmp:
            parent = BaseTerminalWorld(Path(tmp)/"parent", run_id=PARENT, models=models,
                           stage_overrides=overrides, repair_iteration=0)
            recovery = BaseTerminalWorld(Path(tmp)/"recovery", run_id=RECOVERY, models=models,
                             stage_overrides=overrides, repair_iteration=0)
            root = Path(tmp)/"repo"
            specs = Path("thesis/enhanced_tests/frozen/e3_final_specs.jsonl")
            (root/specs).parent.mkdir(parents=True,exist_ok=True)
            (root/specs).write_bytes((rc.ROOT/specs).read_bytes())
            for entry in parent.entries(models[0]):
                relative = Path(entry["drivers"]["benchmark_dir"])/"cpu.cc"
                target = root/relative
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes((rc.ROOT/relative).read_bytes())
            config = copy.deepcopy(recovery.config)
            for key, area in (("raw_dir","raw"),("intermediate_dir","intermediate")):
                target = root/"thesis/results"/area
                for world in (parent,recovery):
                    shutil.copytree(Path(world.config["outputs"][key])/world.run_id, target/world.run_id)
                config["outputs"][key] = str(target)
            intermediate = Path(config["outputs"]["intermediate_dir"])
            for model in models:
                (Path(config["outputs"]["raw_dir"])/RECOVERY/model/"generations.jsonl").unlink()
                for name in ("assembly.jsonl","static_analysis.jsonl","correctness.jsonl","dynamic_analysis.jsonl"):
                    (intermediate/RECOVERY/model/name).unlink()
            artifacts = []
            for area in ("raw","intermediate"):
                for path in (root/"thesis/results"/area/PARENT).rglob("*"):
                    if path.is_file():
                        data=path.read_bytes()
                        artifacts.append(dict(path=path.relative_to(root).as_posix(),raw_sha256=hashlib.sha256(data).hexdigest(),
                                              size=len(data),stage="fixture",source_run=PARENT))
            document=dict(schema_version=SCHEMA,run_id=RECOVERY,parent_run_id=PARENT,pilot_run_id=PILOT,
                          stage_ownership=OWNERSHIP,recovery_base_cells=0,model_ids=models,max_iterations=2,
                          historical_repair_policy="EXCLUDE_ALL_PARENT_REPAIR",artifacts=sorted(artifacts,key=lambda a:a["path"]))
            document["lineage_sha256"]=fingerprint(document)
            lineage=RecoveryLineage(root,document,document["lineage_sha256"])
            with ExitStack() as stack:
                stack.enter_context(patch.object(rc,"ROOT",root))
                stack.enter_context(patch.object(vp,"REPO_ROOT",root))
                stack.enter_context(patch.object(rc,"load_lineage",return_value=lineage))
                stack.enter_context(patch.object(recovery_contract,"build",return_value=recovery.contract))
                stack.enter_context(patch.object(ra,"load_and_validate_run_authorization",
                    return_value={"authorization":ra.load_authorization(config,RECOVERY)}))
                for model in models:
                    path=intermediate/RECOVERY/model/"enhanced_tests.jsonl"
                    rows=[json.loads(line) for line in path.read_text().splitlines()]
                    for row in rows:
                        row.update(rc.candidate_provenance(config,RECOVERY,model,row["sample_id"]))
                    atomic_io.atomic_write_jsonl(path,rows)
                    global_fp={"enhanced_execution_fingerprint_sha256":"f"*64,"components":{"fixture":True}}
                    candidate=ep.candidate_source_fingerprint(intermediate,PARENT,model,root)
                    run_manifest.register_model_execution(config,RECOVERY,model,
                        ep.model_fingerprint_sha(ep.model_execution_fingerprint(global_fp,candidate)))
                result=verifier.verify(config,recovery.config_path)
                self.assertEqual(result["status"],"PASS",[(c["check"],c["detail"]) for c in result["checks"] if c["status"]!="PASS"])
                self.assertEqual(result["repair_scope"]["terminal_loop_count"],33)
                from thesis.repair import run_backfill
                executor=Mock()
                for _ in range(2):
                    run_backfill.backfill_model(config,str(recovery.config_path),"fixture",RECOVERY,
                                               models[0],executor,None,False)
                self.assertEqual(executor.mock_calls, [])
                enhanced=intermediate/RECOVERY/models[0]/"enhanced_tests.jsonl"
                original=enhanced.read_bytes()
                rows=[json.loads(line) for line in original.decode().splitlines()]
                rows[0]["candidate_source_sha256"]="0"*64
                atomic_io.atomic_write_jsonl(enhanced,rows)
                with self.assertRaises(ValueError): verifier.verify(config,recovery.config_path)
                enhanced.write_bytes(original)
                state=intermediate/RECOVERY/models[0]/"repair/static_feedback/state.jsonl"
                state.write_text("",encoding="utf-8")
                with self.assertRaises(ValueError): verifier.verify(config,recovery.config_path)
                lineage.verify_artifacts()
        ra.clear_context()


if __name__ == "__main__": unittest.main()
