"""Read-only live-definition tests; run after freezing candidate definitions."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thesis.config.load_config import load_config
from thesis.evaluation import recovery_contract as contract, recovery_context as rc
from thesis.evaluation import recovery_equivalence as eq
from thesis.evaluation.recovery_lineage import RECOVERY, RecoveryRefused
from thesis.evaluation.verify_parent_base_evidence import read_json, records, BASE


class ContractTests(unittest.TestCase):
    def test_historical_planned_composite_against_its_exact_source_snapshot(self):
        from functools import partial
        from thesis.evaluation import composite_study, extension_contract, method_equivalence
        from thesis.evaluation.recovery_historical_source import git_blob
        manifest = read_json(rc.ROOT / BASE / "run_manifest.json")
        commit = manifest["git_commit"]
        certificate_path = "thesis/evaluation/full_extension_equivalence.json"
        certificate = json.loads(git_blob(rc.ROOT, commit, certificate_path))
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp)
            for relative in set(certificate["source_pins"]) | {certificate_path}:
                path = snapshot / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(git_blob(rc.ROOT, commit, relative))
            for relative in (
                "thesis/evaluation/full_001_composite.json",
                "thesis/results/intermediate/pilot_002/run_contract.json",
                "thesis/results/intermediate/full_ext_001/run_contract.json",
                "thesis/results/intermediate/pilot_002/post_run_verification.json"):
                path = snapshot / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((rc.ROOT / relative).read_bytes())
            with patch.object(extension_contract, "ROOT", snapshot), \
                 patch.object(extension_contract, "CERTIFICATE", snapshot / certificate_path), \
                 patch.object(composite_study, "compare_conditions", partial(method_equivalence.compare_conditions, root=snapshot)):
                result = composite_study.verify_manifest(snapshot / "thesis/evaluation/full_001_composite.json")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["composite_cells"], 1980)

    def test_live_contract_deterministic_and_matches_freeze(self):
        config = rc.ROOT / "thesis/config/recovery.yaml"
        first = contract.build(config, RECOVERY)
        self.assertEqual(first, contract.build(config, RECOVERY))
        self.assertEqual(first, read_json(rc.DEFINITIONS / "contract.json"))
        self.assertEqual(first["status"], "READY")
        self.assertEqual(first["recovery_provenance"]["recovery_base_cells"], 0)
        self.assertEqual(first["recovery_provenance"]["parent_base_cells"], 1584)

    def test_methodical_config_change_refused(self):
        config = load_config(rc.ROOT / "thesis/config/recovery.yaml")
        config["generation_defaults"]["max_output_tokens"] += 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(RecoveryRefused): contract.build(path, RECOVERY)

    def test_proof_unknown_source_and_domain_drift_refused(self):
        from thesis.evaluation import condition_hashing as ch
        original = read_json(rc.DEFINITIONS / "equivalence.json")
        for kind in ("source", "domain"):
            proof = copy.deepcopy(original)
            if kind == "source": proof["source_pins"][contract.SOURCES[0]] = "0" * 64
            else: proof["unchanged_domains"][eq.DOMAINS[0]]["new"] = "0" * 64
            proof["proof_sha256"] = ch.canonical_sha256({k:v for k,v in proof.items() if k != "proof_sha256"})
            with self.subTest(kind=kind), self.assertRaises(RecoveryRefused):
                eq.validate(proof, proof["proof_sha256"], rc.ROOT, contract.SOURCES)

    def test_historical_62_requests_fresh_derivation(self):
        from thesis.repair.recovery_routing import RecoveryRepairLoop
        c = load_config(rc.ROOT / "thesis/config/recovery.yaml")
        m = next(m for m in c["models"] if m["id"] == "openai_gpt55")
        loop = RecoveryRepairLoop(config=c, config_path="thesis/config/recovery.yaml",
            profile_name="recovery", profile=c["profiles"]["recovery"],model_config=m,
            variant="static_feedback",lineage=rc.load_lineage())
        historical = records(rc.ROOT / BASE / "openai_gpt55/repair/static_feedback/iter1/requests.jsonl")
        self.assertEqual(loop.verify_historical_request_set(historical)["request_count"], 62)
        historical[0]["request"] += "changed"
        with self.assertRaises(RecoveryRefused): loop.verify_historical_request_set(historical)

    def test_recovery_without_authorization_cannot_verify_complete(self):
        from thesis.evaluation.verify_recovery_run import verify
        from thesis.evaluation.run_authorization import StartRefused
        c = load_config(rc.ROOT / "thesis/config/recovery.yaml")
        with self.assertRaises(StartRefused): verify(c, rc.ROOT / "thesis/config/recovery.yaml")


if __name__ == "__main__":
    unittest.main()
