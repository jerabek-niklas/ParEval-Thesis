"""Synthetic-only recovery tests. No Docker, providers or experiment runners."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from thesis.evaluation import check_static_repair_readiness as readiness
from thesis.evaluation import recovery_lineage as rl


class ParserTests(unittest.TestCase):
    def inspect(self, payload, rc=0):
        output = payload if isinstance(payload, str) else json.dumps(payload)
        with patch.object(readiness.subprocess, "run", return_value=SimpleNamespace(
                returncode=rc, stdout=output, stderr="inspect failed")) as call:
            result = readiness.docker_image_identity("fixture")
            self.assertEqual(call.call_args.args[0], ["docker", "image", "inspect", "fixture"])
            return result

    def test_historical_success_equivalence(self):
        for digests, layers in [([], []), (["z", "a", "a"], ["layer2", "layer1"]),
                                (["image@sha256:a"], ["sha256:b"])]:
            # Independently reproduce the old successful template parser.
            parts = ("image-id\t" + ",".join(digests) + "\t" + ",".join(layers)).strip().split("\t")
            old_layers = [s for s in (parts[2] if len(parts) > 2 else "").split(",") if s.strip()]
            expected = dict(image_ref="fixture", image_id=parts[0],
                            repo_digests=sorted(s for s in (parts[1] if len(parts) > 1 else "").split(",") if s.strip()),
                            rootfs_layers_sha256=hashlib.sha256("\n".join(old_layers).encode()).hexdigest() if old_layers else None,
                            rootfs_layer_count=len(old_layers) if old_layers else None, inspect_error=None)
            self.assertEqual(self.inspect([dict(Id="image-id", RepoDigests=digests,
                                                RootFS=dict(Type="layers", Layers=layers))]), expected)

    def test_generic_json_arrays(self):
        result = self.inspect('[{"Id":"sha256:original","RepoDigests":["z","a","a"],"RootFS":{"Type":"layers","Layers":["b","a"]}}]')
        self.assertIsNone(result["inspect_error"])
        self.assertEqual(result["repo_digests"], ["a", "a", "z"])
        self.assertEqual(result["rootfs_layers_sha256"], hashlib.sha256(b"b\na").hexdigest())

    def test_malformed_json_and_shape_fail_closed(self):
        good = dict(Id="sha256:a", RepoDigests=[], RootFS=dict(Type="layers", Layers=[]))
        invalid = ["{", [], {}, [good, good], [None]]
        for key, value in [("Id", None), ("Id", 1), ("RepoDigests", None),
                           ("RepoDigests", [1]), ("RepoDigests", "a"),
                           ("RootFS", None), ("RootFS", {"Type":"layers","Layers":[{}]})]:
            item = copy.deepcopy(good); item[key] = value; invalid.append([item])
        for item in invalid:
            with self.subTest(item=item):
                r = self.inspect(item)
                self.assertTrue(r["inspect_error"])
                self.assertIsNone(r["image_id"])
                self.assertEqual(r["repo_digests"], [])
                self.assertIsNone(r["rootfs_layers_sha256"])

    def test_transport_failure(self):
        self.assertEqual(self.inspect("", 1)["inspect_error"], "inspect failed")


class LineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.relative = "thesis/results/intermediate/full_ext_001/model/assembly.jsonl"
        path = self.root / self.relative
        path.parent.mkdir(parents=True)
        path.write_bytes(b"fixture")
        self.doc = dict(schema_version=rl.SCHEMA, run_id=rl.RECOVERY, parent_run_id=rl.PARENT,
                        pilot_run_id=rl.PILOT, recovery_base_cells=0, stage_ownership=rl.OWNERSHIP.copy(),
                        historical_repair_policy="EXCLUDE_ALL_PARENT_REPAIR", max_iterations=2,
                        artifacts=[dict(path=self.relative,raw_sha256=hashlib.sha256(b"fixture").hexdigest(),
                                        size=7,stage="assembly",source_run=rl.PARENT)])
        self.seal()

    def seal(self):
        self.doc["lineage_sha256"] = rl.fingerprint(self.doc)

    def load(self):
        return rl.RecoveryLineage(self.root,self.doc,self.doc["lineage_sha256"])

    def test_parent_hash_and_missing(self):
        lineage = self.load(); lineage.verify_artifacts()
        path = self.root/self.relative
        path.write_bytes(b"tampered")
        with self.assertRaises(rl.RecoveryRefused):lineage.verify_artifacts()
        path.unlink()
        with self.assertRaises(rl.RecoveryRefused):lineage.verify_artifacts()

    def test_no_parent_write_no_fallback(self):
        lineage = self.load()
        with self.assertRaises(rl.RecoveryRefused):lineage.assert_writer(rl.PARENT,"enhanced","static_feedback",0)
        with self.assertRaises(rl.RecoveryRefused):lineage.assert_writer(rl.RECOVERY,"static","static_feedback",0)
        with self.assertRaises(rl.RecoveryRefused):lineage.read_path(self.relative+"missing")
        owner=lineage.assert_writer(rl.RECOVERY,"enhanced","static_feedback",0)
        self.assertEqual(owner.candidate_run,rl.PARENT)
        self.assertEqual(owner.authority_run,rl.RECOVERY)

    def test_third_population_and_duplicate_ref(self):
        self.doc['recovery_base_cells']=1584;self.seal()
        with self.assertRaises(rl.RecoveryRefused):self.load()
        self.doc['recovery_base_cells']=0
        self.doc['artifacts']*=2;self.seal()
        with self.assertRaises(rl.RecoveryRefused):self.load()

    def test_native_identity_preserved(self):
        row={'run_id':rl.PARENT,'sample_id':'s'}
        wrapped=self.load().envelope('static',row,rl.PARENT,'static_feedback',0)
        self.assertEqual(wrapped['record'],row)
        with self.assertRaises(rl.RecoveryRefused):self.load().envelope('static',row,rl.RECOVERY,'static_feedback',0)

    def test_no_historical_response(self):
        with self.assertRaises(rl.RecoveryRefused):rl.reject_historical_response({'run_id':rl.PARENT+'__static_feedback__iter1'})
        rl.reject_historical_response({'run_id':rl.RECOVERY+'__static_feedback__iter1'})

    def test_request_mismatch(self):
        row=dict(model_id='m',sample_id='s',variant='static_feedback',iteration=1,
                 built_from_iteration=0,strategy='static_feedback',request='unchanged')
        rl.compare_requests([row],[row])
        with self.assertRaises(rl.RecoveryRefused):rl.compare_requests([dict(row,request='changed')],[row])

    def test_active_and_incomplete_loops(self):
        row=dict(run_id=rl.RECOVERY,sample_id='s',status='terminal')
        rl.require_complete_loop([row],{'s'},{'terminal'})
        with self.assertRaises(rl.RecoveryRefused):rl.require_complete_loop([row],{'s','missing'},{'terminal'})
        with self.assertRaises(rl.RecoveryRefused):rl.require_complete_loop([dict(row,status='active')],{'s'},{'terminal'})

    def test_repair_read_paths_never_change_writer_identity(self):
        from thesis.repair.recovery_routing import RecoveryLoopPaths
        self.doc['model_ids']=['model'];self.seal()
        cfg={'outputs':{'raw_dir':str(self.root/'thesis/results/raw'),
                        'intermediate_dir':str(self.root/'thesis/results/intermediate')}}
        paths=RecoveryLoopPaths(cfg,'model','static_feedback',self.load())
        self.assertEqual(paths.assembly_path(0),self.root/self.relative)
        self.assertEqual(paths.iter_run_id(0),rl.RECOVERY)
        self.assertIn(rl.RECOVERY,paths.state_path.parts)
        self.assertNotIn(rl.PARENT,paths.state_path.parts)

    def test_definition_cannot_authorize(self):
        from thesis.evaluation.recovery_contract import build
        with self.assertRaises(rl.RecoveryRefused):build()

    def test_evidence_candidate_and_authorization(self):
        from thesis.evaluation.recovery_stage_evidence import validate_new_evidence
        candidate=dict(writer_run_id=rl.RECOVERY,candidate_source_run=rl.PARENT,
                       candidate_source_sha256='bound-source',model_id='m',sample_id='s')
        row=dict(candidate,run_id=rl.RECOVERY,authorization_sha256='bound-auth')
        self.assertTrue(validate_new_evidence(row,candidate,'bound-auth'))
        for key in ('candidate_source_sha256','authorization_sha256','run_id'):
            with self.assertRaises(rl.RecoveryRefused):validate_new_evidence(dict(row,**{key:'wrong'}),candidate,'bound-auth')

    def test_backfill_gap_is_present(self):
        from thesis.evaluation.recovery_stage_evidence import missing_recovery_keys
        rows=[dict(run_id=rl.RECOVERY,sample_id='s',state='TOOL_ERROR')]
        self.assertEqual(missing_recovery_keys(rows,{'s','missing'},lambda r:r['sample_id']),{'missing'})
        with self.assertRaises(rl.RecoveryRefused):missing_recovery_keys([dict(rows[0],run_id=rl.PARENT)],{'s'},lambda r:r['sample_id'])

    def test_equivalence_requires_separate_proofs(self):
        from thesis.evaluation import recovery_equivalence as eq
        with self.assertRaises(rl.RecoveryRefused):eq.validate({},'unproven',self.root,['missing'])


if __name__ == '__main__':
    unittest.main()
