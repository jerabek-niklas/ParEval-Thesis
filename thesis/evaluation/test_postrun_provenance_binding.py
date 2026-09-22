"""Read-only verifier proofs on synthetic, normally FRESH-authorized fixtures.
No provider calls, analyzer runs, runtime probes or productive artifact writes.
"""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from thesis.evaluation import manifest_fragments as mf, run_manifest as rm
from thesis.evaluation import run_authorization as ra, verify_pilot_run as v
from thesis.evaluation.test_post_run_verification import World, MODEL


class BindingProof(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.world = World(Path(self.temp.name))
        self.summary_path = (Path(self.world.config['outputs']['raw_dir']) /
                             self.world.run_id / MODEL / 'generation_summary.json')
        self.records_path = self.summary_path.with_name('generations.jsonl')
        summary = self.read(self.summary_path)
        summary['counts']['skipped_existing'] = 2
        self.write(self.summary_path, summary)

    @staticmethod
    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')

    def binding(self):
        w = self.world
        report = v.Report(w.run_id)
        v.check_authorization(report, w.config, w.run_id, w.contract, rm.load_manifest(w.config, w.run_id))
        v.check_population(report, Path(w.config['outputs']['raw_dir']), w.run_id, MODEL, w.contract)
        v.check_record_identity(report, w.config, w.run_id, [MODEL], w.contract)
        return next(c for c in report.checks if c['check'] == 'generation_authorization_binding:' + MODEL)

    def mutate_record(self, function):
        records = [json.loads(x) for x in self.records_path.read_text().splitlines()]
        function(records[0])
        self.records_path.write_text(''.join(json.dumps(r) + '\n' for r in records))

    def mutate_summary(self, function):
        summary = self.read(self.summary_path)
        function(summary)
        self.write(self.summary_path, summary)

    def test_clean_authorized_resume(self):
        check = self.binding()
        self.assertEqual('PASS', check['status'], check)
        self.assertEqual(2, check['evidence']['authorized_resume_proof']['records_checked'])

    def test_predating_record_fails(self):
        self.mutate_record(lambda r: r.update(created_at_utc='2000-01-01T00:00:00Z'))
        self.assertEqual('FAIL', self.binding()['status'])

    def test_unparseable_record_time_fails(self):
        self.mutate_record(lambda r: r.update(created_at_utc='not-a-time'))
        self.assertEqual('FAIL', self.binding()['status'])

    def test_foreign_run_fails(self):
        self.mutate_record(lambda r: r.update(run_id='pilot_001'))
        self.assertEqual('FAIL', self.binding()['status'])

    def test_wrong_model_id_provider_and_name_fail(self):
        original = self.records_path.read_bytes()
        for field in ('id', 'provider', 'model_name'):
            with self.subTest(field=field):
                self.records_path.write_bytes(original)
                self.mutate_record(lambda r: r['model'].__setitem__(field, 'wrong'))
                self.assertEqual('FAIL', self.binding()['status'])

    def test_other_summary_authorization_fails(self):
        self.mutate_summary(lambda s: s['run_authorization'].update(authorization_sha256='wrong'))
        self.assertEqual('FAIL', self.binding()['status'])

    def test_missing_persisted_authorization_unresolved(self):
        mf.fragment_path(Path(self.world.config['outputs']['intermediate_dir']),
                         self.world.run_id, 'authorization', 'start').unlink()
        self.assertEqual('UNRESOLVED', self.binding()['status'])

    def test_not_start_allowed_fails(self):
        path = mf.fragment_path(Path(self.world.config['outputs']['intermediate_dir']),
                                self.world.run_id, 'authorization', 'start')
        fragment = self.read(path)
        fragment['content']['decision'] = 'START_REFUSED'
        self.write(path, fragment)
        self.assertEqual('FAIL', self.binding()['status'])

    def test_zero_skipped_unchanged(self):
        self.mutate_summary(lambda s: s['counts'].update(skipped_existing=0))
        check = self.binding()
        self.assertEqual('PASS', check['status'])
        self.assertIsNone(check['evidence']['authorized_resume_proof'])

    def test_legacy_contract_not_upgraded(self):
        self.world.contract = copy.deepcopy(self.world.contract)
        self.world.contract['schema_version'] = 'pilot_run_contract.v2'
        self.assertEqual('UNRESOLVED', self.binding()['status'])

    def test_summary_run_and_model_must_be_exact(self):
        original = self.summary_path.read_bytes()
        for field in ('run_id', 'model_id', 'provider', 'model_name'):
            with self.subTest(field=field):
                self.summary_path.write_bytes(original)
                self.mutate_summary(lambda s: s.pop(field))
                self.assertEqual('FAIL', self.binding()['status'])

    def test_prompt_drift_fails(self):
        self.mutate_record(lambda r: r['prompt'].update(prompt_text='different'))
        self.assertEqual('FAIL', self.binding()['status'])

    def test_duplicate_records_fail(self):
        records = self.records_path.read_text().splitlines()
        self.records_path.write_text(records[0] + '\n' + records[0] + '\n')
        self.assertEqual('FAIL', self.binding()['status'])

    def test_unreadable_record_never_passes(self):
        self.records_path.write_text(self.records_path.read_text() + 'INVALID\n')
        self.assertNotEqual('PASS', self.binding()['status'])

    def conditions(self, mutate):
        manifest = copy.deepcopy(rm.load_manifest(self.world.config, self.world.run_id))
        mutate(manifest)
        report = v.Report(self.world.run_id)
        v.check_conditions(report, self.world.contract, manifest)
        return report.checks[0]

    def test_t0_only_repair_registration(self):
        check = self.conditions(lambda m: m.pop('repair_condition_sha256'))
        self.assertEqual('PASS', check['status'], check)
        self.assertEqual('manifest.runtime_evidence.repair_condition_sha256',
                         check['evidence']['repair_condition_registration_source'])

    def test_both_matching_sources_pass(self):
        self.assertEqual('PASS', self.conditions(lambda m: None)['status'])

    def test_missing_both_sources_unresolved(self):
        def mutate(m):
            m.pop('repair_condition_sha256')
            m['runtime_evidence'].pop('repair_condition_sha256')
        self.assertEqual('UNRESOLVED', self.conditions(mutate)['status'])

    def test_either_source_contradiction_fails(self):
        for source in ('top', 't0'):
            with self.subTest(source=source):
                def mutate(m):
                    target = m if source == 'top' else m['runtime_evidence']
                    target['repair_condition_sha256'] = 'wrong'
                self.assertEqual('FAIL', self.conditions(mutate)['status'])

    def test_t0_foreign_contract_fails(self):
        def mutate(m):
            m.pop('repair_condition_sha256')
            m['runtime_evidence']['contract_sha256'] = 'wrong'
        self.assertEqual('FAIL', self.conditions(mutate)['status'])

    def test_t0_missing_authorization_unresolved(self):
        def mutate(m):
            m.pop('repair_condition_sha256')
            m.pop('authorization')
        self.assertEqual('UNRESOLVED', self.conditions(mutate)['status'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
