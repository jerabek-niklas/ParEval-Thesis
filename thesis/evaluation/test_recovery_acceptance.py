"""Synthetic complete acceptance and negative gate fixtures (no execution)."""
import copy
import unittest

from thesis.evaluation.recovery_lineage import RECOVERY, RecoveryRefused
from thesis.evaluation.verify_recovery_run import validate_completion_summary, validate_owned_invocations, validate_runtime_domain
from thesis.evaluation import effective_invocation as ei


class AcceptanceTests(unittest.TestCase):
    def test_productive_runtime_stamp_schema_and_unknown_drift(self):
        from thesis.evaluation import stage_runtime as sr
        expected = dict(image_ref="main", image_id="sha256:image", repo_digests=["main@sha256:digest"],
                        rootfs_layers_sha256="layers", tool_identities={"compiler":"fixture"}, evidence={"mpi":"fixture"})
        fields = sr.COMPARED_FIELDS[sr.MODE_DOCKER]
        digest = sr.domain_sha256(expected, fields=fields)
        observed = {k:v for k,v in expected.items() if k != "repo_digests"}
        observed.update(compared_fields=list(fields), expected_t0_domain_sha256=digest,
                        observed_domain_sha256=digest, match=True)
        validate_runtime_domain(expected, observed, fields)
        for key in ("image_id", "rootfs_layers_sha256", "tool_identities", "observed_domain_sha256"):
            wrong = copy.deepcopy(observed); wrong[key] = None
            with self.subTest(key=key), self.assertRaises(RecoveryRefused):
                validate_runtime_domain(expected, wrong, fields)

    def complete(self):
        return dict(parent_base_cells=1584, recovery_base_cells=0,
                    expected_loops=33, terminal_loops=33, active_samples=0,
                    parent_unchanged=True, authorization_valid=True,
                    coverage_complete=True, runtime_complete=True,
                    invocation_complete=True, historical_repair_adopted=False)

    def test_complete_acceptance_fixture(self):
        self.assertTrue(validate_completion_summary(self.complete()))

    def test_every_missing_acceptance_obligation_refuses(self):
        for key in self.complete():
            fixture = self.complete(); fixture.pop(key)
            with self.subTest(key=key), self.assertRaises(RecoveryRefused):
                validate_completion_summary(fixture)

    def test_every_contradictory_acceptance_obligation_refuses(self):
        for key, value in self.complete().items():
            fixture = self.complete(); fixture[key] = not value if type(value) is bool else value+1
            with self.subTest(key=key), self.assertRaises(RecoveryRefused):
                validate_completion_summary(fixture)

    def test_invocation_full_coverage_and_drift(self):
        contract = dict(model_ids=["m1","m2"], primary_compiler="g++")
        rows = {model:ei.build_invocation(RECOVERY,"enhanced","recovery",{},model_scope=[model],contract=contract)
                for model in contract["model_ids"]}
        manifest=dict(stage_invocations=rows)
        validate_owned_invocations(manifest,contract,{"enhanced":{"m1","m2"}})
        missing=copy.deepcopy(manifest);missing["stage_invocations"].pop("m2")
        with self.assertRaises(RecoveryRefused): validate_owned_invocations(missing,contract,{"enhanced":{"m1","m2"}})
        wrong=copy.deepcopy(manifest);wrong["stage_invocations"]["m1"]["run_id"]="full_ext_001"
        with self.assertRaises(RecoveryRefused): validate_owned_invocations(wrong,contract,{"enhanced":{"m1","m2"}})


if __name__ == "__main__": unittest.main()
